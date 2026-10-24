#!/bin/bash
# Publish the broker through Caddy at https://net.<domain>/mqtt (WebSocket MQTT over TLS).
# Adds one separate site file and one `import` line; backs the Caddyfile up first and puts it
# back if Caddy does not accept the result. Run after the DNS record for the name exists.
set -euo pipefail
RAW=${RAW:-https://raw.githubusercontent.com/2E0LXY/ultimate-meshcore/main/server/umcnet}
HOST=${HOST:-net.2e0lxy.uk}
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
CF=/etc/caddy/Caddyfile
mine=$(curl -fsS https://api.ipify.org 2>/dev/null || true)
there=$(getent hosts "$HOST" | awk '{print $1; exit}')
echo "this server: ${mine:-unknown}   $HOST resolves to: ${there:-nothing}"
[ -n "$there" ] && [ "$there" = "$mine" ] || { echo "the DNS record for $HOST is missing or points elsewhere - not publishing yet"; exit 3; }

mkdir -p /etc/caddy/conf.d
curl -fsSL "$RAW/umcnet.caddy" | sed "s/net\.2e0lxy\.uk/$HOST/" > /etc/caddy/conf.d/umcnet.caddy
cp -a "$CF" "$CF.backup-$(date +%Y%m%d-%H%M%S)-before-umcnet"
grep -q 'import /etc/caddy/conf.d/\*.caddy' "$CF" || printf '\nimport /etc/caddy/conf.d/*.caddy\n' >> "$CF"
if caddy validate --config "$CF" --adapter caddyfile >/tmp/caddy-validate.log 2>&1; then
  systemctl reload caddy
  echo "published: wss://$HOST/mqtt"
else
  cat /tmp/caddy-validate.log | tail -5
  b=$(ls -1t "$CF".backup-*-before-umcnet | head -1); cp -a "$b" "$CF"
  rm -f /etc/caddy/conf.d/umcnet.caddy
  echo "Caddy rejected it; the Caddyfile is back as it was"; exit 4
fi
