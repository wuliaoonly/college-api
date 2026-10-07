#!/usr/bin/env bash
# Update an existing installation while preserving its database, secrets and TLS setup.
set -euo pipefail
root=/opt/campus-ai
archive=${1:-/opt/campus-ai/campus-ai-client-options.zip}
old=$(readlink -f "$root/current")
release="$root/releases/$(date -u +%Y%m%dT%H%M%SZ)-client-options"
[[ $(id -u) == 0 && "$old" == "$root/releases/"* && -d "$old/.venv" && -f "$archive" ]]
systemctl start campus-ai-backup.service
mkdir -m 750 "$release"
python3 - "$release" "$archive" <<'PY'
import pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1])
with zipfile.ZipFile(sys.argv[2]) as archive:
    for item in archive.infolist():
        target=(root/item.filename).resolve()
        if root not in target.parents: raise RuntimeError('Unsafe archive path')
    archive.extractall(root)
PY
ln -s "$(readlink -f "$old/.venv")" "$release/.venv"
chgrp -R campus-ai "$release"
find "$release" -type d -exec chmod 750 {} +
find "$release" -type f -exec chmod 640 {} +
chmod 750 "$release/ops/deploy_ip_certificate.sh"
"$release/.venv/bin/python" -m py_compile "$release/portal/main.py"
rollback() {
    ln -sfn "$old" "$root/current.restore"
    mv -Tf "$root/current.restore" "$root/current"
    cp "$old/frontend/dist/index.html" /var/www/campus-ai/index.html
    systemctl restart campus-ai
    echo 'Release rolled back after a failed check.' >&2
}
trap rollback ERR
ln -s "$release" "$root/current.next"
mv -Tf "$root/current.next" "$root/current"
cp -a "$release/frontend/dist/assets/." /var/www/campus-ai/assets/
find /var/www/campus-ai/assets -type d -exec chmod 755 {} +
find /var/www/campus-ai/assets -type f -exec chmod 644 {} +
cp "$release/frontend/dist/index.html" /var/www/campus-ai/index.html.new
chmod 644 /var/www/campus-ai/index.html.new
mv -f /var/www/campus-ai/index.html.new /var/www/campus-ai/index.html
systemctl restart campus-ai
"$release/.venv/bin/python" "$release/ops/smoke_deployment.py" --env "$root/.env"
systemctl start campus-ai-backup.service
systemctl is-active campus-ai caddy campus-ai-backup.timer campus-ai-certificate.timer
readlink -f "$root/current"
trap - ERR
