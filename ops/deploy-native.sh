#!/usr/bin/env bash
# Deploy a prepared release without a container registry or a server-side Node build.
set -euo pipefail
release=$(readlink -f "${1:-/opt/campus-ai/current}")
[[ $(id -u) == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ "$release" == /opt/campus-ai/releases/* && -f "$release/frontend/dist/index.html" ]] || { echo 'Prepared release or frontend build missing.' >&2; exit 1; }
[[ -f /opt/campus-ai/.env ]] || { echo 'Production environment missing.' >&2; exit 1; }
if systemctl is-active --quiet campus-ai; then
    echo 'An active release exists; back up and use the documented update procedure.' >&2
    exit 1
fi
getent passwd campus-ai >/dev/null || useradd --system --home-dir /var/lib/campus-ai --shell /usr/sbin/nologin campus-ai
chgrp campus-ai /opt/campus-ai /opt/campus-ai/releases
chgrp -R campus-ai "$release"
chmod 750 /opt/campus-ai /opt/campus-ai/releases "$release"
install -d -m 750 -o campus-ai -g campus-ai /var/lib/campus-ai /var/backups/campus-ai
python3 - "$release" <<'PY'
import pathlib, sys
root = pathlib.Path('/opt/campus-ai')
env = root / '.env'
lines = env.read_text().splitlines()
values = dict(line.split('=', 1) for line in lines if '=' in line and not line.startswith('#'))
if not values.get('ADMIN_PASSWORD') or not values.get('ENCRYPTION_KEY'):
    raise RuntimeError('Production credentials are missing')
lines = [line for line in lines if not line.startswith('DATA_DIR=')]
lines.append('DATA_DIR=/var/lib/campus-ai')
env.write_text('\n'.join(lines) + '\n')
env.chmod(0o600)
web = root / 'web.env'
web.write_text('SITE_ADDRESS=' + values['SITE_ADDRESS'] + '\n')
web.chmod(0o600)
release = pathlib.Path(sys.argv[1])
config = (release / 'deploy/Caddyfile').read_text().replace('portal:8000', '127.0.0.1:8000').replace('root * /srv', 'root * /var/www/campus-ai')
pathlib.Path('/etc/caddy/Caddyfile').write_text(config)
PY
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --disable-pip-version-check --no-cache-dir --require-hashes -r "$release/portal/requirements.lock.txt"
install -d -m 755 /var/www/campus-ai
cp -a "$release/frontend/dist/." /var/www/campus-ai/
find /var/www/campus-ai -type d -exec chmod 755 {} +
find /var/www/campus-ai -type f -exec chmod 644 {} +
install -d /etc/systemd/system/caddy.service.d
cat > /etc/systemd/system/caddy.service.d/campus-ai.conf <<'EOF'
[Service]
EnvironmentFile=/opt/campus-ai/web.env
EOF
cat > /etc/systemd/system/campus-ai.service <<'EOF'
[Unit]
Description=Campus AI control portal
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=campus-ai
Group=campus-ai
WorkingDirectory=/opt/campus-ai/current
EnvironmentFile=/opt/campus-ai/.env
Environment=PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ExecStart=/opt/campus-ai/current/.venv/bin/uvicorn portal.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/campus-ai /var/backups/campus-ai
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/campus-ai-backup.service <<'EOF'
[Unit]
Description=Campus AI consistent database backup
After=campus-ai.service

[Service]
Type=oneshot
User=campus-ai
Group=campus-ai
WorkingDirectory=/opt/campus-ai/current
EnvironmentFile=/opt/campus-ai/.env
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/campus-ai/current/.venv/bin/python ops/backup.py --data /var/lib/campus-ai --out /var/backups/campus-ai
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/campus-ai /var/backups/campus-ai
UMask=0077
EOF
cat > /etc/systemd/system/campus-ai-backup.timer <<'EOF'
[Unit]
Description=Daily Campus AI backup

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
EOF
set -a
source /opt/campus-ai/web.env
set +a
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl daemon-reload
systemctl enable --now campus-ai
for attempt in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/portal-api/health >/dev/null; then break; fi
    sleep 1
done
curl -fsS http://127.0.0.1:8000/portal-api/health
systemctl enable --now caddy campus-ai-backup.timer
systemctl start campus-ai-backup.service
systemctl is-active campus-ai caddy campus-ai-backup.timer
