#!/usr/bin/env bash
# Certbot deploy hook. Only the webserver's certificate key is shared with caddy.
set -euo pipefail
lineage=${RENEWED_LINEAGE:-/etc/letsencrypt/live/campus-ai-ip}
[[ "$lineage" == /etc/letsencrypt/live/campus-ai-ip ]] || exit 0
install -d -m 750 -o root -g caddy /etc/caddy/tls
install -m 640 -o root -g caddy "$lineage/fullchain.pem" /etc/caddy/tls/campus-ai-ip.fullchain.pem.new
install -m 640 -o root -g caddy "$lineage/privkey.pem" /etc/caddy/tls/campus-ai-ip.key.new
mv /etc/caddy/tls/campus-ai-ip.fullchain.pem.new /etc/caddy/tls/campus-ai-ip.fullchain.pem
mv /etc/caddy/tls/campus-ai-ip.key.new /etc/caddy/tls/campus-ai-ip.key
systemctl reload caddy
