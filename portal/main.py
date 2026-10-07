import asyncio
import hashlib
import hmac
import io
import ipaddress
import json
import re
import secrets
import sqlite3
import time
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator

from .config import Config, ROOT
from .database import Database
from .providers import get_adapter
from .security import digest, hash_password, private_file, random_token, verify_password


def now():
    return int(time.time())


def fail(status, message):
    raise HTTPException(status, message)


class AccountName(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r'^[\w.@+-]+$')

    @field_validator('username', mode='before')
    @classmethod
    def trim_username(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('username')
    @classmethod
    def validate_email(cls, value):
        if '@' in value and not re.fullmatch(r'[\w.+-]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,63}', value):
            raise ValueError('Invalid email format')
        return value


class Credentials(AccountName):
    password: str = Field(min_length=8, max_length=128)


class Registration(Credentials):
    display_name: str = Field(min_length=1, max_length=40)
    invite_code: str = Field(min_length=4, max_length=100)


class AccountInput(Credentials):
    display_name: str = Field(min_length=1, max_length=40)


class AccountEdit(AccountName):
    display_name: str = Field(min_length=1, max_length=40)


class PasswordInput(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class InventoryAction(BaseModel):
    action: str = Field(pattern=r'^(disable|enable)$')


class KeyAssignment(BaseModel):
    user_id: int = Field(gt=0)


class OrderInput(BaseModel):
    amount_fen: int
    method: str = Field(pattern=r'^(wechat|alipay)$')
    accept_policy: bool


class Review(BaseModel):
    action: str = Field(pattern=r'^(approve|reject)$')
    note: str = Field(default='', max_length=300)


class ImportKeys(BaseModel):
    provider_id: int = 1
    keys: list[str] = Field(min_length=1, max_length=500)


class InviteInput(BaseModel):
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_at: int | None = None


class UserAction(BaseModel):
    action: str = Field(pattern=r'^(block|activate|assign)$')
    provider_id: int = 1


class DeadlineInput(BaseModel):
    expires_at: int | None = None


class UsageInput(BaseModel):
    user_id: int
    key_id: int
    amount_fen: int = Field(ge=0, le=100_000_000)
    model: str = Field(min_length=1, max_length=80)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    period_start: int
    period_end: int
    reference: str = Field(min_length=1, max_length=100)


class ExchangeInput(BaseModel):
    ticket: str = Field(min_length=30, max_length=100)


class InstallerInput(BaseModel):
    clients: list[str] = Field(default_factory=lambda: ['claude-code'], min_length=1, max_length=2)

    @field_validator('clients')
    @classmethod
    def supported_clients(cls, value):
        if len(set(value)) != len(value) or any(item not in ('claude-code', 'deepseek-harness') for item in value):
            raise ValueError('Unsupported installation selection')
        return value


class ProviderInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    base_url: str = Field(max_length=200)
    models_url: str = Field(max_length=200)
    model: str = Field(min_length=1, max_length=80)


class NoticeInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=3000)


class SettingsInput(BaseModel):
    site_name: str = Field(min_length=1, max_length=60)
    payment_note: str = Field(default='', max_length=500)


def create_app(config: Config | None = None):
    cfg = config or Config()
    cfg.secure_cookies = cfg.public_origin.startswith('https://')
    cfg.data_dir = Path(cfg.data_dir).resolve()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    media = cfg.data_dir / 'media'
    media.mkdir(exist_ok=True)
    secret_path = cfg.data_dir / 'encryption.key'
    if cfg.encryption_key:
        key = cfg.encryption_key.encode()
    elif secret_path.exists():
        key = secret_path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        secret_path.write_bytes(key)
        private_file(secret_path)
    cipher = Fernet(key)
    db = Database(cfg.data_dir / 'portal.db')
    db.initialize()
    private_file(db.path)
    # Early, clear failure for a restored database with the wrong encryption key.
    sample = db.one('SELECT ciphertext FROM api_keys LIMIT 1')
    if sample:
        try:
            cipher.decrypt(sample['ciphertext'].encode())
        except InvalidToken:
            raise RuntimeError('Encryption key does not match database; restore the matching encryption.key') from None

    def audit(conn, actor, action, target, detail=''):
        conn.execute('INSERT INTO audits(actor_id,action,target,detail,created_at) VALUES(?,?,?,?,?)',
                     (actor, action, str(target), detail, now()))

    with db.transaction() as conn:
        if not conn.execute('SELECT id FROM users WHERE role="admin"').fetchone():
            if len(cfg.admin_password) < 12:
                raise RuntimeError('Set ADMIN_PASSWORD to at least 12 characters before the first start')
            conn.execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                         (cfg.admin_username, '管理员', hash_password(cfg.admin_password), 'admin', now()))
        conn.execute('''INSERT OR IGNORE INTO providers(id,name,kind,base_url,models_url,model,capabilities)
                     VALUES(1,?,?,?,?,?,?)''', ('DeepSeek 官方', 'deepseek',
                     'https://api.deepseek.com/anthropic', 'https://api.deepseek.com/models',
                     'deepseek-flash[1m]', json.dumps({'verified': True, 'remote_revoke': False,
                     'independent_budget': False, 'expiry': False, 'usage_api': False})))
        for name, value in [('site_name', '学院 AI Coding'), ('payment_note', '转账后请填写订单备注，并点击“我已付款”。'),
                            ('wechat_qr', ''), ('alipay_qr', '')]:
            conn.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', (name, value))
        conn.execute('''INSERT OR IGNORE INTO invite_creators(invite_id,user_id)
                        SELECT i.id,a.actor_id FROM invites i JOIN audits a ON a.target=CAST(i.id AS TEXT)
                        JOIN users u ON u.id=a.actor_id WHERE a.action='invite_created' ''')

    def sweep():
        with db.transaction() as conn:
            rows = conn.execute('SELECT id,owner_id FROM api_keys WHERE status="assigned" AND expires_at IS NOT NULL AND expires_at<=?', (now(),)).fetchall()
            for row in rows:
                conn.execute('UPDATE api_keys SET status="pending_revocation" WHERE id=?', (row['id'],))
                conn.execute('UPDATE users SET status="blocked" WHERE id=?', (row['owner_id'],))
                conn.execute('UPDATE tickets SET expires_at=0 WHERE user_id=? AND consumed_at IS NULL', (row['owner_id'],))
                audit(conn, None, 'deadline_pending_revocation', row['id'])
            conn.execute('DELETE FROM sessions WHERE expires_at<?', (now(),))
            conn.execute('DELETE FROM tickets WHERE expires_at<? AND created_at<?', (now(), now() - 7 * 86400))

    @asynccontextmanager
    async def lifespan(app):
        async def periodic():
            while True:
                await asyncio.to_thread(sweep)
                await asyncio.sleep(60)
        task = asyncio.create_task(periodic())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title='Campus AI — Direct Connect', lifespan=lifespan,
                  docs_url=None if cfg.production else '/portal-api/docs', redoc_url=None,
                  openapi_url=None if cfg.production else '/portal-api/openapi.json')
    app.state.db = db
    app.state.config = cfg
    app.state.cipher = cipher
    app.state.probe_transport = None
    limits = {}
    dummy_password_hash = hash_password('constant-dummy-password')

    @app.middleware('http')
    async def safeguards(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != cfg.public_origin:
                return JSONResponse({'detail': '请求来源不匹配'}, status_code=403)
            try:
                if int(request.headers.get('content-length', '0')) > 2_000_000:
                    return JSONResponse({'detail': '提交内容过大'}, status_code=413)
            except ValueError:
                return JSONResponse({'detail': '请求格式不正确'}, status_code=400)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo submitted passwords, tickets, or imported credentials.
        messages = {'username': '用户名需为3至128位，支持字母、数字、下划线或有效邮箱地址',
                    'password': '密码需为8至128位', 'display_name': '请填写1至40字的称呼',
                    'invite_code': '请填写完整邀请码', 'amount_fen': '充值金额格式不正确',
                    'keys': '请填写至少一个API Key，每行一个'}
        field = next((str(e['loc'][-1]) for e in exc.errors() if e['loc']), '')
        return JSONResponse({'detail': messages.get(field, '输入格式不正确，请检查必填项'),
                             'field': field if field in messages else None}, status_code=422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse({'detail': '记录已存在或发生重复操作，请刷新后重试'}, status_code=409)

    def rate_limit(request, category, ceiling=15):
        address = request.client.host if request.client else 'unknown'
        stamp = now()
        bucket = (address, category)
        recent = [t for t in limits.get(bucket, []) if t > stamp - 300]
        if len(recent) >= ceiling:
            fail(429, '操作太频繁，请五分钟后重试')
        limits[bucket] = recent + [stamp]
        if len(limits) > 5000:
            for item in list(limits):
                if not limits[item] or limits[item][-1] < stamp - 300:
                    del limits[item]

    def auth(request: Request):
        token = request.cookies.get('campus_session', '')
        row = db.one('''SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id
                        WHERE s.token_hash=? AND s.expires_at>?''', (digest(token), now()))
        if not row:
            fail(401, '请先登录')
        if request.method not in ('GET', 'HEAD') and not hmac.compare_digest(request.headers.get('x-csrf-token', ''), row['csrf']):
            fail(403, '会话校验失败，请刷新页面')
        return dict(row)

    def admin(user=Depends(auth)):
        if user['role'] != 'admin' or user['status'] != 'active':
            fail(403, '需要管理员权限')
        return user

    def require_active(user):
        if user['status'] != 'active':
            fail(403, '账户已暂停领取，请联系管理员；已发出的官方Key仍需官网撤销')

    def require_secure_delivery():
        parsed = urlparse(cfg.public_origin)
        local = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
        if parsed.scheme != 'https' and not local:
            fail(503, '真实密钥领取需要可信HTTPS，当前地址仅供界面验证')

    def login_response(conn, user_id, response):
        token, csrf = random_token(), random_token()
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), user_id, csrf, now() + 86400))
        response.set_cookie('campus_session', token, httponly=True, secure=cfg.secure_cookies,
                            samesite='lax', max_age=86400, path='/')
        return {'id': user_id, 'csrf': csrf}

    def assign(conn, user_id, provider_id=1):
        existing = conn.execute('SELECT id FROM api_keys WHERE owner_id=? AND status IN ("assigned","pending_revocation")', (user_id,)).fetchone()
        if existing:
            return existing['id']
        row = conn.execute('''SELECT k.id FROM api_keys k JOIN providers p ON k.provider_id=p.id
                              WHERE k.status="available" AND k.provider_id=? AND p.enabled=1 ORDER BY k.id LIMIT 1''', (provider_id,)).fetchone()
        if row:
            conn.execute('UPDATE api_keys SET owner_id=?,status="assigned",assigned_at=? WHERE id=? AND status="available"', (user_id, now(), row['id']))
            audit(conn, None, 'key_assigned', row['id'], f'user:{user_id}')
            return row['id']
        return None

    def profile(user):
        sweep()
        current_user = db.one('SELECT status FROM users WHERE id=?', (user['id'],))
        key_row = db.one('''SELECT k.id,k.masked,k.status,k.expires_at,k.verified_at,k.last_verification,
                            p.name AS provider,p.base_url,p.model FROM api_keys k JOIN providers p ON k.provider_id=p.id
                            WHERE k.owner_id=? ORDER BY k.id DESC LIMIT 1''', (user['id'],))
        totals = db.one('''SELECT COALESCE(SUM(CASE WHEN type='purchase' THEN amount_fen ELSE 0 END),0) bought,
                           COALESCE(SUM(amount_fen),0) reconciled FROM ledger WHERE user_id=?''', (user['id'],))
        checked = db.one('SELECT MAX(checked_at) checked_at, MAX(period_end) through FROM usage_entries WHERE user_id=? AND voided=0', (user['id'],))
        return {'id': user['id'], 'username': user['username'], 'display_name': user['display_name'],
                'role': user['role'], 'status': current_user['status'], 'csrf': user['csrf'],
                'key': dict(key_row) if key_row else None, 'purchased_fen': totals['bought'],
                'reconciled_fen': totals['reconciled'], 'checked_at': checked['checked_at'],
                'checked_through': checked['through']}

    @app.get('/portal-api/health')
    def health():
        db.one('SELECT 1')
        return {'status': 'ok', 'model_traffic': 'direct_to_provider'}

    @app.get('/portal-api/public')
    def public():
        parsed = urlparse(cfg.public_origin)
        return {'settings': {r['name']: r['value'] for r in db.all('SELECT * FROM settings')},
                'announcements': db.all('SELECT * FROM announcements WHERE published=1 ORDER BY id DESC LIMIT 10'),
                'service_fee_percent': 5, 'refunds': False, 'usage_mode': 'manual_reconciliation',
                'key_delivery_enabled': parsed.scheme == 'https' or parsed.hostname in ('127.0.0.1', 'localhost', '::1')}

    @app.post('/portal-api/auth/register')
    def register(body: Registration, request: Request, response: Response):
        rate_limit(request, 'register', 10)
        password_hash = hash_password(body.password)
        with db.transaction() as conn:
            invite = conn.execute('SELECT * FROM invites WHERE code_hash=?', (digest(body.invite_code.strip().upper()),)).fetchone()
            if not invite or not invite['enabled'] or invite['used'] >= invite['max_uses'] or (invite['expires_at'] and invite['expires_at'] <= now()):
                fail(400, '邀请码无效、已过期或已用完')
            creator = conn.execute('''SELECT u.status FROM invite_creators c JOIN users u ON u.id=c.user_id
                                      WHERE c.invite_id=?''', (invite['id'],)).fetchone()
            if creator and creator['status'] != 'active':
                fail(400, '邀请人的账户已暂停，请联系管理员获取新邀请码')
            if conn.execute('SELECT id FROM users WHERE username=?', (body.username,)).fetchone():
                fail(409, '用户名已存在')
            user_id = conn.execute('INSERT INTO users(username,display_name,password_hash,created_at) VALUES(?,?,?,?)',
                                   (body.username, body.display_name.strip(), password_hash, now())).lastrowid
            conn.execute('UPDATE invites SET used=used+1 WHERE id=?', (invite['id'],))
            assign(conn, user_id)
            audit(conn, user_id, 'registered', user_id)
            return login_response(conn, user_id, response)

    @app.post('/portal-api/auth/login')
    def login(body: Credentials, request: Request, response: Response):
        rate_limit(request, 'login')
        user = db.one('SELECT * FROM users WHERE username=?', (body.username,))
        encoded = user['password_hash'] if user else dummy_password_hash
        if not verify_password(body.password, encoded) or not user:
            fail(401, '用户名或密码不正确')
        with db.transaction() as conn:
            return login_response(conn, user['id'], response)

    @app.post('/portal-api/auth/logout')
    def logout(request: Request, response: Response, user=Depends(auth)):
        with db.transaction() as conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (digest(request.cookies.get('campus_session', '')),))
        response.delete_cookie('campus_session', path='/')
        return {'ok': True}

    @app.get('/portal-api/me')
    def me(user=Depends(auth)):
        return profile(user)

    @app.get('/portal-api/orders')
    def orders(user=Depends(auth)):
        return db.all('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 100', (user['id'],))

    @app.post('/portal-api/orders')
    def create_order(body: OrderInput, user=Depends(auth)):
        require_active(user)
        if not db.one('SELECT id FROM api_keys WHERE owner_id=? AND status="assigned"', (user['id'],)):
            fail(409, '请先等待管理员分配可用Key，再创建充值订单')
        if body.amount_fen not in (1000, 2000, 5000, 10000) or not body.accept_policy:
            fail(400, '请选择充值档位并确认服务费与不退款说明')
        settings = {r['name']: r['value'] for r in db.all('SELECT * FROM settings')}
        if not settings[body.method + '_qr']:
            fail(409, '管理员尚未配置此收款方式')
        fee = body.amount_fen * 5 // 100
        order_id = datetime.now(timezone.utc).strftime('%Y%m%d') + '-' + secrets.token_hex(4).upper()
        with db.transaction() as conn:
            pending = conn.execute('SELECT COUNT(*) FROM orders WHERE user_id=? AND status IN ("pending_payment","submitted")', (user['id'],)).fetchone()[0]
            if pending >= 3:
                fail(409, '请先处理已有充值订单')
            conn.execute('''INSERT INTO orders(id,user_id,gross_fen,fee_fen,net_fen,method,created_at,policy_accepted)
                            VALUES(?,?,?,?,?,?,?,1)''', (order_id, user['id'], body.amount_fen, fee, body.amount_fen - fee, body.method, now()))
            audit(conn, user['id'], 'order_created', order_id)
        return dict(db.one('SELECT * FROM orders WHERE id=?', (order_id,)))

    @app.post('/portal-api/orders/{order_id}/paid')
    def paid(order_id: str, user=Depends(auth)):
        require_active(user)
        with db.transaction() as conn:
            order = conn.execute('SELECT * FROM orders WHERE id=? AND user_id=?', (order_id, user['id'])).fetchone()
            if not order:
                fail(404, '订单不存在')
            if order['status'] == 'pending_payment':
                conn.execute('UPDATE orders SET status="submitted" WHERE id=?', (order_id,))
                audit(conn, user['id'], 'payment_claimed', order_id)
            elif order['status'] != 'submitted':
                fail(409, '订单已处理')
        return {'ok': True}

    @app.get('/portal-api/usage')
    def usage(user=Depends(auth)):
        return db.all('SELECT * FROM usage_entries WHERE user_id=? ORDER BY checked_at DESC LIMIT 200', (user['id'],))

    @app.post('/portal-api/orders/{order_id}/cancel')
    def cancel_order(order_id: str, user=Depends(auth)):
        with db.transaction() as conn:
            row = conn.execute('SELECT * FROM orders WHERE id=? AND user_id=?', (order_id, user['id'])).fetchone()
            if not row:
                fail(404, '订单不存在')
            if row['status'] == 'cancelled':
                return {'ok': True}
            if row['status'] != 'pending_payment':
                fail(409, '仅未付款订单可以取消，已提交或确认的订单不能撤回')
            conn.execute('UPDATE orders SET status="cancelled" WHERE id=?', (order_id,))
            audit(conn, user['id'], 'unpaid_order_cancelled', order_id)
        return {'ok': True}

    @app.post('/portal-api/installer/package')
    def package(request: Request, body: InstallerInput = InstallerInput(), user=Depends(auth)):
        rate_limit(request, 'installer', 15)
        require_secure_delivery()
        sweep()
        ticket = None
        with db.transaction() as conn:
            fresh = conn.execute('SELECT status FROM users WHERE id=?', (user['id'],)).fetchone()
            key_row = conn.execute('SELECT k.id FROM api_keys k JOIN providers p ON p.id=k.provider_id WHERE k.owner_id=? AND k.status="assigned" AND p.enabled=1', (user['id'],)).fetchone()
            if fresh['status'] != 'active':
                fail(409, '账户已暂停，请联系管理员')
            if key_row:
                ticket = random_token()
                conn.execute('UPDATE tickets SET expires_at=0 WHERE user_id=? AND consumed_at IS NULL', (user['id'],))
                conn.execute('INSERT INTO tickets VALUES(?,?,?,?,NULL,?)', (digest(ticket), user['id'], key_row['id'], now() + 1800, now()))
            audit(conn, user['id'], 'installer_issued', key_row['id'] if key_row else user['id'],
                  json.dumps({'clients': body.clients, 'configuration_available': bool(ticket)}))
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('CampusAI-Setup.ps1', 'Setup.Core.ps1', 'Harness.Launch.ps1', 'Start.cmd', 'README.txt'):
                content = (ROOT / 'installer' / name).read_text(encoding='utf-8-sig')
                encoding = 'utf-8-sig' if name.endswith('.ps1') else 'utf-8'
                archive.writestr(name, content.replace('\r\n', '\n').replace('\n', '\r\n').encode(encoding))
            archive.writestr('selection.json', json.dumps({'clients': body.clients, 'configuration_available': bool(ticket),
                                                          'download_url': cfg.public_origin + '/download'}, ensure_ascii=False))
            if ticket:
                archive.writestr('ticket.json', json.dumps({'endpoint': cfg.public_origin + '/portal-api/installer/exchange',
                                                           'ticket': ticket}, ensure_ascii=False))
        return Response(data.getvalue(), media_type='application/zip', headers={
            'Content-Disposition': 'attachment; filename="CampusAI-Setup.zip"', 'Cache-Control': 'no-store'})

    @app.post('/portal-api/installer/exchange')
    def exchange(body: ExchangeInput, request: Request):
        rate_limit(request, 'exchange', 30)
        require_secure_delivery()
        sweep()
        with db.transaction() as conn:
            row = conn.execute('''SELECT t.*,k.ciphertext,k.status AS key_status,u.status AS user_status,
                                  p.base_url,p.models_url,p.model,p.kind,p.enabled FROM tickets t
                                  JOIN api_keys k ON k.id=t.key_id JOIN users u ON u.id=t.user_id
                                  JOIN providers p ON p.id=k.provider_id WHERE t.token_hash=?''', (digest(body.ticket),)).fetchone()
            if not row or row['consumed_at'] or row['expires_at'] <= now():
                fail(410, '配置票据已使用或过期，请重新登录网站下载安装包')
            if row['user_status'] != 'active' or row['key_status'] != 'assigned' or not row['enabled']:
                fail(403, '已暂停领取，请联系管理员')
            conn.execute('UPDATE tickets SET consumed_at=? WHERE token_hash=? AND consumed_at IS NULL', (now(), digest(body.ticket)))
            raw = cipher.decrypt(row['ciphertext'].encode()).decode()
            audit(conn, row['user_id'], 'key_delivered_to_installer', row['key_id'])
            env = get_adapter(row['kind']).client_env(row['base_url'], row['model'], raw)
            return {'key_id': row['key_id'], 'env': env, 'models_url': row['models_url'], 'direct_connect': True,
                    'harness': {'supported': row['kind'] == 'deepseek', 'api_key': raw if row['kind'] == 'deepseek' else None,
                                'base_url': row['base_url'], 'model': row['model'].replace('[1m]', '')}}

    @app.get('/portal-api/media/{filename}')
    def get_media(filename: str):
        if not re.fullmatch(r'[a-f0-9]{32}\.(png|jpg)', filename) or not (media / filename).is_file():
            fail(404, '图片不存在')
        return FileResponse(media / filename)

    @app.get('/portal-api/admin/overview')
    def overview(user=Depends(admin)):
        sweep()
        return {'users': db.one('SELECT COUNT(*) n FROM users WHERE role="student"')['n'],
                'keys': db.all('SELECT status,COUNT(*) count FROM api_keys GROUP BY status'),
                'payments': dict(db.one('SELECT COALESCE(SUM(gross_fen),0) gross,COALESCE(SUM(fee_fen),0) fee,COALESCE(SUM(net_fen),0) net FROM orders WHERE status="approved"')),
                'usage_fen': db.one('SELECT COALESCE(SUM(amount_fen),0) n FROM usage_entries WHERE voided=0')['n'],
                'pending_orders': db.one('SELECT COUNT(*) n FROM orders WHERE status="submitted"')['n'],
                'pending_revocations': db.one('SELECT COUNT(*) n FROM api_keys WHERE status="pending_revocation"')['n']}

    @app.get('/portal-api/admin/users')
    def admin_users(user=Depends(admin)):
        sweep()
        return db.all('''SELECT u.id,u.username,u.display_name,u.role,u.status,u.created_at,
                        (SELECT COALESCE(SUM(amount_fen),0) FROM ledger WHERE user_id=u.id) reconciled_fen,
                        (SELECT COALESCE(SUM(amount_fen),0) FROM ledger WHERE user_id=u.id AND type="purchase") purchased_fen,
                        (SELECT id FROM api_keys WHERE owner_id=u.id ORDER BY id DESC LIMIT 1) key_id,
                        (SELECT masked FROM api_keys WHERE owner_id=u.id ORDER BY id DESC LIMIT 1) key_masked,
                        (SELECT status FROM api_keys WHERE owner_id=u.id ORDER BY id DESC LIMIT 1) key_status
                        FROM users u ORDER BY u.id DESC LIMIT 500''')

    @app.post('/portal-api/admin/users')
    def create_account(body: AccountInput, user=Depends(admin)):
        name = body.display_name.strip()
        if not name:
            fail(400, '请填写用户称呼')
        password_hash = hash_password(body.password)
        with db.transaction() as conn:
            if conn.execute('SELECT id FROM users WHERE username=?', (body.username,)).fetchone():
                fail(409, '用户名或邮箱已存在')
            user_id = conn.execute('INSERT INTO users(username,display_name,password_hash,created_at) VALUES(?,?,?,?)',
                                   (body.username, name, password_hash, now())).lastrowid
            assign(conn, user_id)
            audit(conn, user['id'], 'account_created', user_id)
        return {'id': user_id, 'message': '用户账户已创建；有可用库存时自动分配Key'}

    @app.patch('/portal-api/admin/users/{user_id}')
    def edit_account(user_id: int, body: AccountEdit, user=Depends(admin)):
        name = body.display_name.strip()
        if not name:
            fail(400, '请填写用户称呼')
        with db.transaction() as conn:
            target = conn.execute('SELECT * FROM users WHERE id=? AND role="student"', (user_id,)).fetchone()
            if not target:
                fail(404, '成员账户不存在，管理员账户不能通过此入口修改')
            if conn.execute('SELECT id FROM users WHERE username=? AND id<>?', (body.username, user_id)).fetchone():
                fail(409, '用户名或邮箱已存在')
            conn.execute('UPDATE users SET username=?,display_name=? WHERE id=?', (body.username, name, user_id))
            if target['username'] != body.username:
                conn.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            audit(conn, user['id'], 'account_edited', user_id)
        return {'ok': True}

    @app.post('/portal-api/admin/users/{user_id}/password')
    def reset_password(user_id: int, body: PasswordInput, user=Depends(admin)):
        password_hash = hash_password(body.password)
        with db.transaction() as conn:
            if not conn.execute('SELECT id FROM users WHERE id=? AND role="student"', (user_id,)).fetchone():
                fail(404, '成员账户不存在，管理员账户不能通过此入口修改')
            conn.execute('UPDATE users SET password_hash=? WHERE id=?', (password_hash, user_id))
            conn.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            conn.execute('UPDATE tickets SET expires_at=0 WHERE user_id=? AND consumed_at IS NULL', (user_id,))
            audit(conn, user['id'], 'password_reset', user_id)
        return {'ok': True, 'message': '密码已重置，旧登录会话和未使用安装票据已失效'}

    @app.post('/portal-api/admin/users/{user_id}/action')
    def user_action(user_id: int, body: UserAction, user=Depends(admin)):
        with db.transaction() as conn:
            target = conn.execute('SELECT * FROM users WHERE id=? AND role="student"', (user_id,)).fetchone()
            if not target:
                fail(404, '学生账户不存在')
            if body.action == 'block':
                conn.execute('UPDATE users SET status="blocked" WHERE id=?', (user_id,))
                conn.execute('UPDATE api_keys SET status="pending_revocation" WHERE owner_id=? AND status="assigned"', (user_id,))
                conn.execute('UPDATE tickets SET expires_at=0 WHERE user_id=? AND consumed_at IS NULL', (user_id,))
            elif body.action == 'activate':
                if conn.execute('SELECT id FROM api_keys WHERE owner_id=? AND status="pending_revocation"', (user_id,)).fetchone():
                    fail(409, '请先在官网撤销旧Key并通过核验')
                conn.execute('UPDATE users SET status="active" WHERE id=?', (user_id,))
                assign(conn, user_id, body.provider_id)
            else:
                if target['status'] != 'active':
                    fail(409, '账户尚未恢复领取')
                if not assign(conn, user_id, body.provider_id):
                    fail(409, '该渠道没有可分配Key')
            audit(conn, user['id'], 'user_' + body.action, user_id)
        return {'ok': True}

    @app.get('/portal-api/admin/keys')
    def admin_keys(user=Depends(admin)):
        sweep()
        return db.all('''SELECT k.id,k.provider_id,k.masked,k.status,k.owner_id,k.imported_at,k.assigned_at,
                        k.expires_at,k.revoked_at,k.last_verification,k.verified_at,p.name provider,
                        u.username,u.display_name FROM api_keys k JOIN providers p ON p.id=k.provider_id
                        LEFT JOIN users u ON u.id=k.owner_id ORDER BY k.id DESC LIMIT 1000''')

    @app.post('/portal-api/admin/keys/import')
    def import_keys(body: ImportKeys, user=Depends(admin)):
        require_secure_delivery()
        normalized = [x.strip() for x in body.keys if x.strip()]
        if not normalized:
            fail(400, '没有可导入的Key，请每行填写一个')
        if any(not re.fullmatch(r'[A-Za-z0-9_.-]{16,200}', x) for x in normalized):
            fail(400, 'Key格式不正确，每行一个，不要粘贴其他说明')
        imported = 0
        with db.transaction() as conn:
            if not conn.execute('SELECT id FROM providers WHERE id=? AND enabled=1', (body.provider_id,)).fetchone():
                fail(404, '渠道不存在')
            for raw in normalized:
                fingerprint = hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()
                result = conn.execute('''INSERT OR IGNORE INTO api_keys(provider_id,fingerprint,ciphertext,masked,imported_at)
                                         VALUES(?,?,?,?,?)''', (body.provider_id, fingerprint, cipher.encrypt(raw.encode()).decode(),
                                         raw[:5] + '••••••••' + raw[-4:], now()))
                imported += result.rowcount
            if body.provider_id == 1:
                waiting = conn.execute('''SELECT u.id FROM users u WHERE role="student" AND status="active"
                    AND NOT EXISTS(SELECT 1 FROM api_keys WHERE owner_id=u.id AND status IN ("assigned","pending_revocation")) ORDER BY u.id''').fetchall()
                for row in waiting:
                    assign(conn, row['id'])
            audit(conn, user['id'], 'keys_imported', body.provider_id, f'count:{imported}')
        return {'imported': imported, 'duplicates': len(normalized) - imported}

    @app.post('/portal-api/admin/keys/{key_id}/inventory')
    def inventory_action(key_id: int, body: InventoryAction, user=Depends(admin)):
        with db.transaction() as conn:
            row = conn.execute('SELECT * FROM api_keys WHERE id=?', (key_id,)).fetchone()
            if not row:
                fail(404, 'Key不存在')
            if row['owner_id'] is not None or row['assigned_at'] is not None or row['status'] not in ('available', 'disabled'):
                fail(409, '仅可管理从未分配的库存；已发Key需要走官网撤销流程')
            conn.execute('UPDATE api_keys SET status=? WHERE id=?', ('disabled' if body.action == 'disable' else 'available', key_id))
            audit(conn, user['id'], 'inventory_' + body.action, key_id)
        return {'ok': True}

    @app.post('/portal-api/admin/keys/{key_id}/assign')
    def assign_specific_key(key_id: int, body: KeyAssignment, user=Depends(admin)):
        sweep()
        with db.transaction() as conn:
            row = conn.execute('''SELECT k.* FROM api_keys k JOIN providers p ON p.id=k.provider_id
                               WHERE k.id=? AND p.enabled=1''', (key_id,)).fetchone()
            if not row or row['status'] != 'available' or row['owner_id'] is not None or row['assigned_at'] is not None:
                fail(409, 'Key不在可分配库存中')
            target = conn.execute('SELECT id FROM users WHERE id=? AND role="student" AND status="active"', (body.user_id,)).fetchone()
            if not target:
                fail(409, '请选择正常状态的成员账户')
            if conn.execute('SELECT id FROM api_keys WHERE owner_id=? AND status IN ("assigned","pending_revocation")', (body.user_id,)).fetchone():
                fail(409, '用户已有当前Key；替换前必须完成旧Key的官网撤销核验')
            conn.execute('UPDATE api_keys SET status="assigned",owner_id=?,assigned_at=? WHERE id=?', (body.user_id, now(), key_id))
            audit(conn, user['id'], 'key_assigned', key_id, 'user:' + str(body.user_id))
        return {'ok': True}

    @app.post('/portal-api/admin/keys/{key_id}/deadline')
    def deadline(key_id: int, body: DeadlineInput, user=Depends(admin)):
        with db.transaction() as conn:
            row = conn.execute('SELECT id FROM api_keys WHERE id=? AND status="assigned"', (key_id,)).fetchone()
            if not row:
                fail(409, '仅可设置已分配Key的截止提醒')
            conn.execute('UPDATE api_keys SET expires_at=? WHERE id=?', (body.expires_at, key_id))
            audit(conn, user['id'], 'deadline_set', key_id, str(body.expires_at))
        sweep()
        return {'ok': True}

    @app.post('/portal-api/admin/keys/{key_id}/verify-revocation')
    async def verify_revocation(key_id: int, user=Depends(admin)):
        row = db.one('''SELECT k.*,p.models_url,p.kind FROM api_keys k JOIN providers p ON p.id=k.provider_id
                        WHERE k.id=?''', (key_id,))
        if not row or row['status'] not in ('pending_revocation', 'revoked'):
            fail(409, '请先暂停领取，再到官网撤销Key')
        if row['status'] == 'revoked':
            return {'result': 'revoked', 'message': '已核验该Key不可鉴权'}
        adapter = get_adapter(row['kind'])
        if not adapter.capabilities.verified:
            fail(409, '此渠道的核验规则尚未验证，请先接入经验证的供应商适配器；保持待核实')
        validate_provider_url(row['models_url'])
        outcome = 'uncertain'
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False,
                                         transport=app.state.probe_transport) as client:
                result = await client.get(row['models_url'], headers={'Authorization': 'Bearer ' + cipher.decrypt(row['ciphertext'].encode()).decode()})
                outcome = adapter.probe_result(result.status_code)
        except (httpx.HTTPError, InvalidToken):
            pass
        with db.transaction() as conn:
            conn.execute('UPDATE api_keys SET last_verification=?,verified_at=? WHERE id=?', (outcome, now(), key_id))
            if outcome == 'revoked':
                conn.execute('UPDATE api_keys SET status="revoked",revoked_at=? WHERE id=? AND status="pending_revocation"', (now(), key_id))
            audit(conn, user['id'], 'revocation_checked', key_id, outcome)
        messages = {'revoked': '该Key已不可鉴权，停用核验通过；它不会重新进入库存',
                    'still_valid': '官方Key仍有效，请到DeepSeek官网删除后再次核验',
                    'uncertain': '网络或官方响应无法确认，保持待核实'}
        return {'result': outcome, 'message': messages[outcome]}

    @app.get('/portal-api/admin/orders')
    def admin_orders(user=Depends(admin)):
        return db.all('''SELECT o.*,u.username,u.display_name FROM orders o JOIN users u ON o.user_id=u.id
                        ORDER BY CASE WHEN o.status="submitted" THEN 0 ELSE 1 END,o.created_at DESC LIMIT 500''')

    @app.post('/portal-api/admin/orders/{order_id}/review')
    def review(order_id: str, body: Review, user=Depends(admin)):
        with db.transaction() as conn:
            row = conn.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if not row:
                fail(404, '订单不存在')
            if row['status'] in ('approved', 'rejected'):
                if (row['status'] == 'approved') == (body.action == 'approve'):
                    return {'ok': True, 'already_processed': True}
                fail(409, '订单已经处理，不能更改结果')
            if row['status'] != 'submitted':
                fail(409, '用户尚未声明付款')
            status = 'approved' if body.action == 'approve' else 'rejected'
            conn.execute('UPDATE orders SET status=?,reviewed_at=?,reviewed_by=?,note=? WHERE id=?',
                         (status, now(), user['id'], body.note, order_id))
            if status == 'approved':
                conn.execute('INSERT INTO ledger(user_id,order_id,type,amount_fen,created_at) VALUES(?,?,?,?,?)',
                             (row['user_id'], order_id, 'purchase', row['net_fen'], now()))
            audit(conn, user['id'], 'order_' + status, order_id)
        return {'ok': True}

    @app.get('/portal-api/admin/usage')
    def admin_usage(user=Depends(admin)):
        return db.all('SELECT e.*,u.username FROM usage_entries e JOIN users u ON u.id=e.user_id ORDER BY e.id DESC LIMIT 500')

    @app.post('/portal-api/admin/usage')
    def record_usage(body: UsageInput, user=Depends(admin)):
        if body.period_end <= body.period_start or body.period_end > now() + 60:
            fail(400, '核对区间不正确，结束时间不能晚于当前时间')
        with db.transaction() as conn:
            if not conn.execute('SELECT id FROM api_keys WHERE id=? AND owner_id=?', (body.key_id, body.user_id)).fetchone():
                fail(400, 'Key不属于该用户')
            if conn.execute('''SELECT id FROM usage_entries WHERE key_id=? AND model=? AND voided=0
                               AND period_start<? AND period_end>?''', (body.key_id, body.model, body.period_end, body.period_start)).fetchone():
                fail(409, '该Key同模型的核对区间已存在或重叠，避免重复记账')
            entry_id = conn.execute('''INSERT INTO usage_entries(user_id,key_id,amount_fen,model,input_tokens,output_tokens,
                                      period_start,period_end,checked_at,checked_by,reference) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                                      (body.user_id, body.key_id, body.amount_fen, body.model, body.input_tokens, body.output_tokens,
                                       body.period_start, body.period_end, now(), user['id'], body.reference)).lastrowid
            conn.execute('INSERT INTO ledger(user_id,type,amount_fen,source_id,created_at) VALUES(?,?,?,?,?)',
                         (body.user_id, 'usage', -body.amount_fen, entry_id, now()))
            audit(conn, user['id'], 'usage_reconciled', entry_id)
        return {'id': entry_id}

    @app.post('/portal-api/admin/usage/{entry_id}/void')
    def void_usage(entry_id: int, user=Depends(admin)):
        with db.transaction() as conn:
            row = conn.execute('SELECT * FROM usage_entries WHERE id=?', (entry_id,)).fetchone()
            if not row:
                fail(404, '记录不存在')
            if not row['voided']:
                conn.execute('UPDATE usage_entries SET voided=1 WHERE id=?', (entry_id,))
                conn.execute('INSERT INTO ledger(user_id,type,amount_fen,created_at) VALUES(?,?,?,?)',
                             (row['user_id'], 'usage_correction', row['amount_fen'], now()))
                audit(conn, user['id'], 'usage_voided', entry_id)
        return {'ok': True}

    @app.get('/portal-api/admin/invites')
    def get_invites(user=Depends(admin)):
        return db.all('''SELECT i.id,i.prefix,i.max_uses,i.used,i.expires_at,i.enabled,i.created_at,
                        u.username creator,u.display_name creator_name FROM invites i
                        LEFT JOIN invite_creators c ON c.invite_id=i.id LEFT JOIN users u ON u.id=c.user_id
                        ORDER BY i.id DESC LIMIT 100''')

    @app.post('/portal-api/admin/invites')
    def create_invite(body: InviteInput, user=Depends(admin)):
        code = 'CA-' + secrets.token_hex(8).upper()
        with db.transaction() as conn:
            row_id = conn.execute('INSERT INTO invites(code_hash,prefix,max_uses,expires_at,created_at) VALUES(?,?,?,?,?)',
                                  (digest(code), code[:7], body.max_uses, body.expires_at, now())).lastrowid
            conn.execute('INSERT INTO invite_creators VALUES(?,?)', (row_id, user['id']))
            audit(conn, user['id'], 'invite_created', row_id)
        return {'id': row_id, 'code': code}

    @app.post('/portal-api/admin/invites/{invite_id}/disable')
    def disable_invite(invite_id: int, user=Depends(admin)):
        with db.transaction() as conn:
            conn.execute('UPDATE invites SET enabled=0 WHERE id=?', (invite_id,))
            audit(conn, user['id'], 'invite_disabled', invite_id)
        return {'ok': True}

    @app.get('/portal-api/invites')
    def member_invites(user=Depends(auth)):
        rows = db.all('''SELECT i.id,i.prefix,i.max_uses,i.used,i.expires_at,i.enabled,i.created_at
                          FROM invites i JOIN invite_creators c ON c.invite_id=i.id
                          WHERE c.user_id=? ORDER BY i.id DESC LIMIT 100''', (user['id'],))
        count = db.one('''SELECT count(*) n FROM invites i JOIN invite_creators c ON c.invite_id=i.id
                          WHERE c.user_id=? AND i.enabled=1 AND i.used<i.max_uses
                          AND (i.expires_at IS NULL OR i.expires_at>?)''', (user['id'], now()))['n']
        return {'items': rows, 'remaining': max(0, 5-count), 'limit': 5, 'valid_days': 7}

    @app.post('/portal-api/invites')
    def create_member_invite(request: Request, user=Depends(auth)):
        rate_limit(request, 'member_invites', 10)
        code = 'CA-' + secrets.token_hex(8).upper()
        expires = now() + 7*86400
        with db.transaction() as conn:
            fresh = conn.execute('SELECT status FROM users WHERE id=?', (user['id'],)).fetchone()
            if fresh['status'] != 'active':
                fail(403, '账户已暂停，不能生成邀请码')
            count = conn.execute('''SELECT count(*) FROM invites i JOIN invite_creators c ON c.invite_id=i.id
                                      WHERE c.user_id=? AND i.enabled=1 AND i.used<i.max_uses
                                      AND (i.expires_at IS NULL OR i.expires_at>?)''', (user['id'], now())).fetchone()[0]
            if count >= 5:
                fail(409, '最多保留5个未使用的邀请码，请先使用或停用已有邀请码')
            invite_id = conn.execute('''INSERT INTO invites(code_hash,prefix,max_uses,expires_at,created_at)
                                         VALUES(?,?,1,?,?)''', (digest(code), code[:7], expires, now())).lastrowid
            conn.execute('INSERT INTO invite_creators VALUES(?,?)', (invite_id, user['id']))
            audit(conn, user['id'], 'member_invite_created', invite_id)
        return {'id': invite_id, 'code': code, 'expires_at': expires}

    @app.post('/portal-api/invites/{invite_id}/disable')
    def disable_member_invite(invite_id: int, user=Depends(auth)):
        with db.transaction() as conn:
            if not conn.execute('SELECT invite_id FROM invite_creators WHERE invite_id=? AND user_id=?', (invite_id, user['id'])).fetchone():
                fail(404, '邀请码不存在')
            conn.execute('UPDATE invites SET enabled=0 WHERE id=?', (invite_id,))
            audit(conn, user['id'], 'member_invite_disabled', invite_id)
        return {'ok': True}

    def validate_provider_url(url):
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            fail(400, '供应商地址格式不正确')
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment or port not in (None, 443):
            fail(400, '供应商地址必须为不带凭据、查询参数的HTTPS地址')
        if parsed.hostname not in [x.strip() for x in cfg.provider_allowed_hosts]:
            fail(400, '请先在PROVIDER_ALLOWED_HOSTS中明确添加此供应商域名')
        try:
            if not ipaddress.ip_address(parsed.hostname).is_global:
                fail(400, '不允许内部网络地址')
        except ValueError:
            pass

    @app.get('/portal-api/admin/providers')
    def providers(user=Depends(admin)):
        return db.all('SELECT * FROM providers ORDER BY id')

    @app.post('/portal-api/admin/providers')
    def add_provider(body: ProviderInput, user=Depends(admin)):
        validate_provider_url(body.base_url)
        validate_provider_url(body.models_url)
        with db.transaction() as conn:
            row_id = conn.execute('''INSERT INTO providers(name,kind,base_url,models_url,model,capabilities)
                                    VALUES(?,?,?,?,?,?)''', (body.name, 'custom', body.base_url.rstrip('/'), body.models_url,
                                    body.model, json.dumps({'verified': False, 'remote_revoke': False,
                                    'independent_budget': False, 'expiry': False, 'usage_api': False}))).lastrowid
            audit(conn, user['id'], 'provider_added', row_id)
        return {'id': row_id}

    @app.post('/portal-api/admin/settings')
    def save_settings(body: SettingsInput, user=Depends(admin)):
        with db.transaction() as conn:
            for name, value in body.model_dump().items():
                conn.execute('UPDATE settings SET value=? WHERE name=?', (value, name))
            audit(conn, user['id'], 'settings_updated', 'site')
        return {'ok': True}

    @app.post('/portal-api/admin/payment-qr/{method}')
    async def upload_qr(method: str, file: UploadFile, user=Depends(admin)):
        if method not in ('wechat', 'alipay'):
            fail(400, '收款渠道不正确')
        data = await file.read(1_000_001)
        if len(data) > 1_000_000:
            fail(413, '收款码图片不能超过1MB')
        try:
            image = Image.open(io.BytesIO(data))
            if image.format not in ('PNG', 'JPEG') or image.width * image.height > 12_000_000:
                fail(400, '仅支持PNG/JPEG，图片尺寸过大')
            image.verify()
            filename = secrets.token_hex(16) + ('.png' if image.format == 'PNG' else '.jpg')
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
            fail(400, '图片内容不正确')
        (media / filename).write_bytes(data)
        with db.transaction() as conn:
            conn.execute('UPDATE settings SET value=? WHERE name=?', ('/portal-api/media/' + filename, method + '_qr'))
            audit(conn, user['id'], 'payment_qr_updated', method)
        return {'ok': True}

    @app.post('/portal-api/admin/announcements')
    def publish_notice(body: NoticeInput, user=Depends(admin)):
        with db.transaction() as conn:
            row_id = conn.execute('INSERT INTO announcements(title,content,created_at) VALUES(?,?,?)', (body.title, body.content, now())).lastrowid
            audit(conn, user['id'], 'announcement_published', row_id)
        return {'id': row_id}

    @app.post('/portal-api/admin/announcements/{notice_id}/unpublish')
    def unpublish_notice(notice_id: int, user=Depends(admin)):
        with db.transaction() as conn:
            conn.execute('UPDATE announcements SET published=0 WHERE id=?', (notice_id,))
            audit(conn, user['id'], 'announcement_unpublished', notice_id)
        return {'ok': True}

    @app.get('/portal-api/admin/audits')
    def get_audits(user=Depends(admin)):
        return db.all('''SELECT a.*,u.username FROM audits a LEFT JOIN users u ON a.actor_id=u.id
                        ORDER BY a.id DESC LIMIT 200''')

    return app

