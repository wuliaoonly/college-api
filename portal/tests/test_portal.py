import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from portal.config import Config
from portal.main import create_app

PASSWORD = 'test-password-very-long'
FAKE_KEYS = ['sk-fixture-only-aaaaaaaaaaaaaaa1', 'sk-fixture-only-bbbbbbbbbbbbbbb2']


@pytest.fixture
def app(tmp_path):
    return create_app(Config(data_dir=tmp_path, public_origin='https://testserver', admin_password=PASSWORD, encryption_key=''))


def login(client, username='admin'):
    response = client.post('/portal-api/auth/login', json={'username': username, 'password': PASSWORD})
    assert response.status_code == 200
    return {'X-CSRF-Token': response.json()['csrf']}


def invite(client, headers, uses=1):
    result = client.post('/portal-api/admin/invites', headers=headers, json={'max_uses': uses})
    assert result.status_code == 200
    return result.json()['code']


def register(client, code, username='student'):
    result = client.post('/portal-api/auth/register', json={'username': username, 'display_name': username,
                         'password': PASSWORD, 'invite_code': code})
    assert result.status_code == 200, result.text
    return {'X-CSRF-Token': result.json()['csrf']}


def import_keys(client, headers):
    response = client.post('/portal-api/admin/keys/import', headers=headers, json={'keys': FAKE_KEYS})
    assert response.status_code == 200


def qr(client, headers):
    stream = io.BytesIO()
    Image.new('RGB', (10, 10), 'white').save(stream, format='PNG')
    result = client.post('/portal-api/admin/payment-qr/wechat', headers=headers,
                         files={'file': ('qr.png', stream.getvalue(), 'image/png')})
    assert result.status_code == 200


def create_student(app, username='student'):
    admin = TestClient(app, base_url='https://testserver')
    admin_headers = login(admin)
    import_keys(admin, admin_headers)
    code = invite(admin, admin_headers)
    student = TestClient(app, base_url='https://testserver')
    student_headers = register(student, code, username)
    return admin, admin_headers, student, student_headers


def unpack_ticket(response):
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert {'Start.cmd', 'CampusAI-Setup.ps1', 'Setup.Core.ps1', 'ticket.json'} <= set(archive.namelist())
    assert all(key.encode() not in response.content for key in FAKE_KEYS)
    for name in archive.namelist():
        assert all(key.encode() not in archive.read(name) for key in FAKE_KEYS)
    return json.loads(archive.read('ticket.json'))['ticket']


def test_keyless_admin_and_waiting_member_can_download_software_without_tickets(app):
    admin = TestClient(app, base_url='https://testserver')
    ah = login(admin)
    member = TestClient(app, base_url='https://testserver')
    mh = register(member, invite(admin, ah), 'waiting')
    for client, headers in ((admin, ah), (member, mh)):
        response = client.post('/portal-api/installer/package', headers=headers,
                               json={'clients':['deepseek-harness']})
        assert response.status_code == 200
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        assert 'ticket.json' not in archive.namelist()
        assert 'Harness.Launch.ps1' in archive.namelist()
        selection = json.loads(archive.read('selection.json'))
        assert selection['clients'] == ['deepseek-harness']
        assert selection['configuration_available'] is False
    assert app.state.db.all('SELECT * FROM tickets') == []
    assert app.state.db.all('SELECT * FROM api_keys') == []


@pytest.mark.parametrize('clients', [['claude-code'], ['deepseek-harness'], ['claude-code','deepseek-harness']])
def test_selected_clients_are_packaged_with_owner_bound_configuration(app, clients):
    admin, ah, member, mh = create_student(app)
    response = member.post('/portal-api/installer/package',headers=mh,json={'clients':clients})
    ticket = unpack_ticket(response)
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert json.loads(archive.read('selection.json')) == {
        'clients':clients,'configuration_available':True,'download_url':'https://testserver/download'}
    payload = member.post('/portal-api/installer/exchange',json={'ticket':ticket}).json()
    assert payload['harness']['api_key'] == payload['env']['ANTHROPIC_AUTH_TOKEN']
    assert payload['harness']['supported'] is True
    assert payload['harness']['model'] == 'deepseek-flash'


@pytest.mark.parametrize('clients', [[], ['unknown'], ['claude-code','claude-code'], ['claude-code','deepseek-harness','unknown']])
def test_invalid_installer_choices_do_not_issue_tickets(app, clients):
    admin = TestClient(app, base_url='https://testserver')
    ah = login(admin)
    assert admin.post('/portal-api/installer/package',headers=ah,json={'clients':clients}).status_code == 422
    assert app.state.db.all('SELECT * FROM tickets') == []


def test_concurrent_registration_key_and_invite_atomicity(app):
    with TestClient(app, base_url='https://testserver') as admin:
        headers = login(admin)
        import_keys(admin, headers)
        code = invite(admin, headers, uses=3)
    def sign_up(index):
        with TestClient(app, base_url='https://testserver') as client:
            headers = register(client, code, f'user{index}')
            return client.get('/portal-api/me').json()
    with ThreadPoolExecutor(max_workers=3) as executor:
        users = list(executor.map(sign_up, range(3)))
    assigned = [u['key']['id'] for u in users if u['key']]
    assert len(assigned) == len(set(assigned)) == 2
    assert sum(u['key'] is None for u in users) == 1
    with TestClient(app, base_url='https://testserver') as client:
        assert client.post('/portal-api/auth/register', json={'username':'extra', 'display_name':'extra',
                           'password':PASSWORD, 'invite_code':code}).status_code == 400


def test_ticket_once_even_under_concurrency_and_credentials_encrypted(app):
    admin, ah, student, sh = create_student(app)
    ticket = unpack_ticket(student.post('/portal-api/installer/package', headers=sh))
    def exchange(_):
        with TestClient(app, base_url='https://testserver') as client:
            return client.post('/portal-api/installer/exchange', json={'ticket': ticket})
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(exchange, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 410]
    payload = next(r.json() for r in responses if r.status_code == 200)
    assert payload['env']['ANTHROPIC_AUTH_TOKEN'] in FAKE_KEYS
    assert payload['env']['ANTHROPIC_BASE_URL'] == 'https://api.deepseek.com/anthropic'
    assert payload['direct_connect'] is True
    for item in app.state.config.data_dir.glob('portal.db*'):
        assert all(key.encode() not in item.read_bytes() for key in FAKE_KEYS)
    assert ticket not in str(app.state.db.all('SELECT * FROM tickets'))
    assert all(key not in admin.get('/portal-api/admin/keys', headers=ah).text for key in FAKE_KEYS)


def test_user_isolation_admin_only_csrf_and_no_proxy(app):
    admin, ah, student, sh = create_student(app)
    assert student.get('/portal-api/admin/keys').status_code == 403
    assert student.post('/portal-api/installer/package').status_code == 403
    assert admin.post('/portal-api/admin/invites', headers={**ah, 'Origin':'https://evil.example'}, json={}).status_code == 403
    assert student.post('/v1/messages', json={'model':'anything'}).status_code == 404
    code = invite(admin, ah)
    other = TestClient(app, base_url='https://testserver')
    oh = register(other, code, 'otheruser')
    assert student.get('/portal-api/me').json()['key']['id'] != other.get('/portal-api/me').json()['key']['id']
    assert student.get('/portal-api/orders').json() == []
    assert all(key not in other.get('/portal-api/me').text for key in FAKE_KEYS)


def test_fee_and_repeated_concurrent_approval_do_not_double_credit(app):
    admin, ah, student, sh = create_student(app)
    qr(admin, ah)
    result = student.post('/portal-api/orders', headers=sh, json={'amount_fen':10000,'method':'wechat','accept_policy':True})
    order = result.json()
    assert (order['gross_fen'], order['fee_fen'], order['net_fen']) == (10000, 500, 9500)
    assert student.post('/portal-api/orders/'+order['id']+'/paid', headers=sh).status_code == 200
    assert student.get('/portal-api/me').json()['purchased_fen'] == 0
    def approve(_):
        return admin.post('/portal-api/admin/orders/'+order['id']+'/review', headers=ah, json={'action':'approve'})
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert all(r.status_code == 200 for r in executor.map(approve, range(2)))
    assert student.get('/portal-api/me').json()['purchased_fen'] == 9500
    assert len(app.state.db.all('SELECT * FROM ledger')) == 1
    other = TestClient(app, base_url='https://testserver')
    oh = register(other, invite(admin, ah), 'otheruser')
    assert other.post('/portal-api/orders/'+order['id']+'/paid', headers=oh).status_code == 404


@pytest.mark.parametrize('http_status, expected', [(200,'still_valid'),(401,'revoked'),(402,'uncertain'),(403,'uncertain'),(429,'uncertain'),(500,'uncertain')])
def test_revocation_only_auth_failure_proves_unusable(app, http_status, expected):
    admin, ah, student, sh = create_student(app)
    me = student.get('/portal-api/me').json()
    admin.post(f"/portal-api/admin/users/{me['id']}/action", headers=ah, json={'action':'block'})
    assert student.post('/portal-api/installer/package', headers=sh).status_code == 409
    app.state.probe_transport = httpx.MockTransport(lambda request: httpx.Response(http_status, json={}))
    response = admin.post(f"/portal-api/admin/keys/{me['key']['id']}/verify-revocation", headers=ah)
    assert response.json()['result'] == expected
    key = app.state.db.one('SELECT * FROM api_keys WHERE id=?', (me['key']['id'],))
    assert key['status'] == ('revoked' if expected=='revoked' else 'pending_revocation')


def test_timeout_is_not_revocation_and_expired_deadline_only_blocks_delivery(app):
    admin, ah, student, sh = create_student(app)
    me = student.get('/portal-api/me').json()
    admin.post(f"/portal-api/admin/keys/{me['key']['id']}/deadline", headers=ah, json={'expires_at':int(time.time())-1})
    assert student.get('/portal-api/me').json()['key']['status'] == 'pending_revocation'
    def timeout(request):
        raise httpx.ReadTimeout('fixture timeout')
    app.state.probe_transport = httpx.MockTransport(timeout)
    assert admin.post(f"/portal-api/admin/keys/{me['key']['id']}/verify-revocation", headers=ah).json()['result']=='uncertain'


def test_manual_ledger_prevents_overlap_and_can_audit_correction(app):
    admin, ah, student, sh = create_student(app)
    me = student.get('/portal-api/me').json()
    usage = {'user_id':me['id'],'key_id':me['key']['id'],'amount_fen':300,'model':'deepseek-flash',
             'period_start':int(time.time())-200,'period_end':int(time.time())-100,'reference':'bill-one'}
    row = admin.post('/portal-api/admin/usage', headers=ah, json=usage)
    assert row.status_code == 200
    assert student.get('/portal-api/me').json()['reconciled_fen'] == -300
    assert admin.post('/portal-api/admin/usage', headers=ah, json={**usage,'reference':'bill-two'}).status_code == 409
    assert admin.post('/portal-api/admin/usage/'+str(row.json()['id'])+'/void', headers=ah).status_code == 200
    assert admin.post('/portal-api/admin/usage/'+str(row.json()['id'])+'/void', headers=ah).status_code == 200
    assert student.get('/portal-api/me').json()['reconciled_fen'] == 0


def test_no_key_recycling_and_old_tickets_invalid_after_replacement(app):
    admin, ah, student, sh = create_student(app)
    me = student.get('/portal-api/me').json()
    ticket = unpack_ticket(student.post('/portal-api/installer/package', headers=sh))
    admin.post(f"/portal-api/admin/users/{me['id']}/action", headers=ah, json={'action':'block'})
    app.state.probe_transport = httpx.MockTransport(lambda r: httpx.Response(401))
    admin.post(f"/portal-api/admin/keys/{me['key']['id']}/verify-revocation", headers=ah)
    admin.post(f"/portal-api/admin/users/{me['id']}/action", headers=ah, json={'action':'activate'})
    assert student.get('/portal-api/me').json()['key']['id'] != me['key']['id']
    assert student.post('/portal-api/installer/exchange', json={'ticket':ticket}).status_code == 410
    assert app.state.db.one('SELECT owner_id,status FROM api_keys WHERE id=?',(me['key']['id'],))['owner_id']==me['id']


def test_remote_http_cannot_deliver_credentials(tmp_path):
    app = create_app(Config(data_dir=tmp_path, public_origin='http://101.37.242.39', admin_password=PASSWORD))
    with TestClient(app, base_url='http://101.37.242.39') as client:
        headers = login(client)
        assert client.post('/portal-api/admin/keys/import', headers=headers, json={'keys':FAKE_KEYS}).status_code==503


def test_provider_cannot_claim_unverified_management_capabilities(app):
    with TestClient(app, base_url='https://testserver') as admin:
        headers = login(admin)
        assert admin.post('/portal-api/admin/providers', headers=headers, json={
            'name':'unsafe','model':'model','base_url':'https://127.0.0.1','models_url':'https://127.0.0.1/models'}).status_code==400
        caps = json.loads(admin.get('/portal-api/admin/providers', headers=headers).json()[0]['capabilities'])
        assert caps['remote_revoke'] is False and caps['independent_budget'] is False


def test_backup_restore_preserves_credentials_and_auth(app, tmp_path):
    from ops.backup import backup_data
    from ops.restore import restore_data
    admin, ah, student, sh = create_student(app)
    snapshot = backup_data(app.state.config.data_dir, tmp_path.parent / (tmp_path.name + '-snapshots'))
    restored_dir = restore_data(snapshot, tmp_path.parent / (tmp_path.name + '-restored'))
    restored = create_app(Config(data_dir=restored_dir, public_origin='https://testserver',
                         admin_password=PASSWORD, encryption_key=''))
    with TestClient(restored, base_url='https://testserver') as client:
        headers = login(client, 'student')
        ticket = unpack_ticket(client.post('/portal-api/installer/package', headers=headers))
        response = client.post('/portal-api/installer/exchange',json={'ticket':ticket})
        assert response.json()['env']['ANTHROPIC_AUTH_TOKEN'] == FAKE_KEYS[0]
    with pytest.raises(ValueError):
        restore_data(snapshot, restored_dir)


def test_unpaid_cancellation_and_missing_key_do_not_accept_payment(app):
    admin, ah, student, sh = create_student(app)
    qr(admin, ah)
    result = student.post('/portal-api/orders', headers=sh, json={'amount_fen':1000,'method':'wechat','accept_policy':True})
    order_id = result.json()['id']
    assert student.post(f'/portal-api/orders/{order_id}/cancel', headers=sh).status_code == 200
    assert student.post(f'/portal-api/orders/{order_id}/paid', headers=sh).status_code == 409
    assert student.get('/portal-api/me').json()['purchased_fen'] == 0
    register(TestClient(app, base_url='https://testserver'), invite(admin, ah), 'anotherstudent')
    waiting = TestClient(app, base_url='https://testserver')
    wh = register(waiting, invite(admin, ah), 'waitingstudent')
    assert waiting.get('/portal-api/me').json()['key'] is None
    assert waiting.post('/portal-api/orders',headers=wh,json={'amount_fen':1000,'method':'wechat','accept_policy':True}).status_code == 409


def test_corrupt_image_rejected_and_unverified_provider_not_marked_revoked(app):
    admin, ah, student, sh = create_student(app)
    corrupt = bytes.fromhex('89504e470d0a1a0a') + b'not-a-valid-png'
    assert admin.post('/portal-api/admin/payment-qr/wechat',headers=ah,files={'file':('bad.png',corrupt,'image/png')}).status_code==400
    provider = admin.post('/portal-api/admin/providers',headers=ah,json={
        'name':'Unverified test provider','model':'test-model','base_url':'https://api.deepseek.com/anthropic',
        'models_url':'https://api.deepseek.com/models'}).json()['id']
    admin.post('/portal-api/admin/keys/import',headers=ah,json={'provider_id':provider,'keys':['sk-unverified-fixture-ccccccccc3']})
    register(TestClient(app,base_url='https://testserver'),invite(admin,ah),'secondstudent')
    waiting=TestClient(app,base_url='https://testserver')
    register(waiting,invite(admin,ah),'thirdstudent')
    target=waiting.get('/portal-api/me').json()
    admin.post(f"/portal-api/admin/users/{target['id']}/action",headers=ah,json={'action':'assign','provider_id':provider})
    key_id=waiting.get('/portal-api/me').json()['key']['id']
    admin.post(f"/portal-api/admin/users/{target['id']}/action",headers=ah,json={'action':'block'})
    app.state.probe_transport=httpx.MockTransport(lambda r:httpx.Response(401))
    assert admin.post(f'/portal-api/admin/keys/{key_id}/verify-revocation',headers=ah).status_code==409
    assert app.state.db.one('SELECT status FROM api_keys WHERE id=?',(key_id,))['status']=='pending_revocation'


def test_email_registration_preserves_invite_on_validation_and_accepts_trimmed_case(app):
    admin = TestClient(app, base_url='https://testserver')
    ah = login(admin)
    code = invite(admin, ah)
    student = TestClient(app, base_url='https://testserver')
    body = {'username': 'bad@@example.com', 'password': PASSWORD, 'display_name': '邮箱成员', 'invite_code': code}
    result = student.post('/portal-api/auth/register', json=body)
    assert result.status_code == 422 and result.json()['field'] == 'username'
    assert PASSWORD not in result.text and '金额' not in result.text
    assert app.state.db.one('SELECT used FROM invites')['used'] == 0
    result = student.post('/portal-api/auth/register', json={**body, 'username': ' 793582219@qq.com ', 'invite_code': code.lower()})
    assert result.status_code == 200
    assert student.get('/portal-api/me').json()['username'] == '793582219@qq.com'
    other = TestClient(app, base_url='https://testserver')
    assert other.post('/portal-api/auth/login', json={'username':' 793582219@QQ.COM ', 'password':PASSWORD}).status_code == 200
    assert student.get('/portal-api/me').json()['key'] is None


def test_admin_account_edit_reset_invalidates_sessions_and_tickets_without_changing_key(app):
    admin, ah, student, sh = create_student(app)
    me = student.get('/portal-api/me').json()
    ticket = unpack_ticket(student.post('/portal-api/installer/package', headers=sh))
    assert admin.patch(f"/portal-api/admin/users/{me['id']}", headers=ah, json={'username':'member@example.com','display_name':'新称呼'}).status_code == 200
    assert student.get('/portal-api/me').status_code == 401
    sh = login(student, 'member@example.com')
    replacement = 'new-fixture-password-456'
    response = admin.post(f"/portal-api/admin/users/{me['id']}/password", headers=ah, json={'password':replacement})
    assert response.status_code == 200 and replacement not in response.text
    assert student.get('/portal-api/me').status_code == 401
    assert student.post('/portal-api/installer/exchange', json={'ticket':ticket}).status_code == 410
    assert student.post('/portal-api/auth/login', json={'username':'member@example.com','password':PASSWORD}).status_code == 401
    assert student.post('/portal-api/auth/login', json={'username':'member@example.com','password':replacement}).status_code == 200
    assert student.get('/portal-api/me').json()['key']['id'] == me['key']['id']
    assert replacement not in str(app.state.db.all('SELECT * FROM audits'))


def test_account_creation_protection_duplicates_and_student_permissions(app):
    admin = TestClient(app, base_url='https://testserver')
    ah = login(admin)
    payload = {'username':'created@example.com','display_name':'管理创建','password':PASSWORD}
    response = admin.post('/portal-api/admin/users', headers=ah, json=payload)
    assert response.status_code == 200
    student_id = response.json()['id']
    assert app.state.db.one('SELECT role FROM users WHERE id=?',(student_id,))['role'] == 'student'
    assert admin.post('/portal-api/admin/users', headers=ah, json={**payload,'username':'CREATED@example.com'}).status_code == 409
    admin_id = admin.get('/portal-api/me').json()['id']
    assert admin.patch(f'/portal-api/admin/users/{admin_id}', headers=ah, json={'username':'replacement','display_name':'x'}).status_code == 404
    assert admin.post(f'/portal-api/admin/users/{admin_id}/password',headers=ah,json={'password':PASSWORD}).status_code == 404
    student = TestClient(app, base_url='https://testserver')
    sh = login(student, payload['username'])
    assert student.post('/portal-api/admin/users',headers=sh,json={**payload,'username':'extra'}).status_code == 403
    assert student.post(f'/portal-api/admin/users/{student_id}/password',headers=sh,json={'password':PASSWORD}).status_code == 403


def test_inventory_disable_reenable_and_concurrent_specific_assignment(app):
    admin = TestClient(app, base_url='https://testserver')
    ah = login(admin)
    import_keys(admin, ah)
    key_id = admin.get('/portal-api/admin/keys').json()[-1]['id']
    # Stop both inventory keys before creating waiting members.
    for row in admin.get('/portal-api/admin/keys').json():
        assert admin.post(f"/portal-api/admin/keys/{row['id']}/inventory",headers=ah,json={'action':'disable'}).status_code == 200
    users=[]
    for index in range(2):
        response=admin.post('/portal-api/admin/users',headers=ah,json={'username':f'waiting{index}','display_name':'等待成员','password':PASSWORD})
        users.append(response.json()['id'])
    assert not app.state.db.all('SELECT id FROM api_keys WHERE owner_id IS NOT NULL')
    assert admin.post(f'/portal-api/admin/keys/{key_id}/inventory',headers=ah,json={'action':'enable'}).status_code == 200
    def assign(index):
        with TestClient(app,base_url='https://testserver') as client:
            headers=login(client)
            return client.post(f'/portal-api/admin/keys/{key_id}/assign',headers=headers,json={'user_id':users[index]}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(assign,range(2))) == [200,409]
    assert admin.post(f'/portal-api/admin/keys/{key_id}/inventory',headers=ah,json={'action':'disable'}).status_code == 409
    assert app.state.db.one('SELECT owner_id FROM api_keys WHERE id=?',(key_id,))['owner_id'] in users


def test_import_deduplication_and_waiting_replacement_after_revocation(app):
    admin, ah, student, sh = create_student(app)
    # Allocate the remaining stock, then stop and verify the first user's old key.
    admin.post('/portal-api/admin/users',headers=ah,json={'username':'second','display_name':'第二位','password':PASSWORD})
    me=student.get('/portal-api/me').json()
    admin.post(f"/portal-api/admin/users/{me['id']}/action",headers=ah,json={'action':'block'})
    app.state.probe_transport=httpx.MockTransport(lambda r:httpx.Response(401))
    admin.post(f"/portal-api/admin/keys/{me['key']['id']}/verify-revocation",headers=ah)
    admin.post(f"/portal-api/admin/users/{me['id']}/action",headers=ah,json={'action':'activate'})
    fresh='sk-new-stock-fixture-12345678'
    response=admin.post('/portal-api/admin/keys/import',headers=ah,json={'keys':[fresh,fresh,FAKE_KEYS[0]]})
    assert response.json() == {'imported':1,'duplicates':2}
    assert student.get('/portal-api/me').json()['key']['id'] != me['key']['id']
    assert admin.post('/portal-api/admin/keys/import',headers=ah,json={'keys':['   ']}).status_code == 400


def test_member_invite_ownership_expiry_and_single_use_registration(app):
    admin, ah, student, sh = create_student(app)
    assert student.get('/portal-api/invites').json()['items'] == []
    response=student.post('/portal-api/invites',headers=sh)
    assert response.status_code == 200
    created=response.json()
    assert 7*86400-5 <= created['expires_at']-int(time.time()) <= 7*86400
    own=student.get('/portal-api/invites').json()
    assert own['remaining']==4 and own['items'][0]['max_uses']==1
    assert created['code'] not in str(own)
    newcomer=TestClient(app,base_url='https://testserver')
    register(newcomer,created['code'],'invited@example.com')
    nh=login(newcomer,'invited@example.com')
    assert newcomer.get('/portal-api/invites').json()['items']==[]
    assert newcomer.post(f"/portal-api/invites/{created['id']}/disable",headers=nh).status_code==404
    assert newcomer.post('/portal-api/auth/register',json={'username':'secondinvite','display_name':'x','password':PASSWORD,'invite_code':created['code']}).status_code==400
    assert any(r['creator']=='student' for r in admin.get('/portal-api/admin/invites').json())


def test_member_invite_quota_is_atomic_and_disabled_invite_frees_capacity(app):
    admin, ah, student, sh = create_student(app)
    created=[student.post('/portal-api/invites',headers=sh).json() for _ in range(4)]
    def create(_):
        with TestClient(app,base_url='https://testserver') as client:
            headers=login(client,'student')
            return client.post('/portal-api/invites',headers=headers).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(create,range(2)))==[200,409]
    assert student.get('/portal-api/invites').json()['remaining']==0
    assert student.post(f"/portal-api/invites/{created[0]['id']}/disable",headers=sh).status_code==200
    assert student.get('/portal-api/invites').json()['remaining']==1
    assert student.post('/portal-api/invites',headers=sh).status_code==200


def test_paused_member_cannot_create_or_use_remaining_invites(app):
    admin, ah, student, sh = create_student(app)
    created=student.post('/portal-api/invites',headers=sh).json()
    user_id=student.get('/portal-api/me').json()['id']
    admin.post(f'/portal-api/admin/users/{user_id}/action',headers=ah,json={'action':'block'})
    assert student.post('/portal-api/invites',headers=sh).status_code==403
    newcomer=TestClient(app,base_url='https://testserver')
    assert newcomer.post('/portal-api/auth/register',json={'username':'stoppedinvite','display_name':'x','password':PASSWORD,'invite_code':created['code']}).status_code==400
    assert app.state.db.one('SELECT used FROM invites WHERE id=?',(created['id'],))['used']==0


