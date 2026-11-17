#!/bin/bash
# Install Caddy (auto HTTPS) in front of the login receiver.   Usage: sudo bash install_caddy.sh shyam-trader.duckdns.org
set -e
DOMAIN="${1:?usage: install_caddy.sh <domain>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
if ! command -v caddy >/dev/null; then
  apt-get update -y
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi
sed "s/DOMAIN/$DOMAIN/" "$HERE/Caddyfile.tpl" > /etc/caddy/Caddyfile
systemctl enable caddy
systemctl restart caddy
sleep 5
systemctl is-active caddy
echo "Test from anywhere:  curl -s -o /dev/null -w '%{http_code}\n' https://$DOMAIN/   (expect 404)"
