#!/bin/bash
# Installs a private ntfy notification server next to the UMC Net broker and prints what to enter on your phone.
#   * served by Caddy on https://<host>:8443 (your existing certificate; no DNS record needed)
#   * nothing is public: everything is denied except two logins on ONE secret topic
#       umc       your phone: read and send
#       umc-dash  the dashboard: send only
# Run as root:  HOST=net.example.org bash install-ntfy.sh      (HOST defaults to the name in the dashboard's Caddy site)
# Then in the dashboard, Settings > Alerts, set the address to the line this script prints, tick "enabled".
set -e
export DEBIAN_FRONTEND=noninteractive
HOST="${HOST:-$(grep -m1 -oE '^[a-z0-9.-]+\.[a-z]+' /etc/caddy/conf.d/umcnet.caddy 2>/dev/null || true)}"
[ -n "$HOST" ] || { echo "set HOST=your.domain"; exit 1; }
PORT="${PORT:-8443}"
if ! command -v ntfy >/dev/null 2>&1; then
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://archive.ntfy.sh/apt/keyring.gpg -o /etc/apt/keyrings/ntfy.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/ntfy.gpg] https://archive.ntfy.sh/apt stable main" > /etc/apt/sources.list.d/ntfy.list
  apt-get update -qq && apt-get install -y -qq ntfy >/dev/null
fi
CRED=/root/umcnet-ntfy.txt
if [ ! -s "$CRED" ]; then
  TOPIC="umc-ntfy-$(head -c 12 /dev/urandom | base32 | tr -d '=' | tr 'A-Z' 'a-z' | cut -c1-16)"
  PHONE_PW=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | cut -c1-20)
  DASH_PW=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | cut -c1-20)
  printf 'TOPIC=%s\nPHONE_USER=umc\nPHONE_PW=%s\nDASH_USER=umc-dash\nDASH_PW=%s\nSERVER=https://%s:%s\n' "$TOPIC" "$PHONE_PW" "$DASH_PW" "$HOST" "$PORT" > "$CRED"; chmod 600 "$CRED"
fi
. "$CRED"
mkdir -p /var/lib/ntfy /var/cache/ntfy; chown ntfy:ntfy /var/lib/ntfy /var/cache/ntfy
cat > /etc/ntfy/server.yml <<CFG
base-url: "$SERVER"
listen-http: "127.0.0.1:2586"
behind-proxy: true
cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "72h"
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"
upstream-base-url: "https://ntfy.sh"
CFG
systemctl enable ntfy >/dev/null 2>&1; systemctl restart ntfy; sleep 4          # once, so the login database exists
mkuser() { if ntfy user list 2>/dev/null | grep -q "^user $1 "; then NTFY_PASSWORD="$2" ntfy user change-pass "$1" >/dev/null; else NTFY_PASSWORD="$2" ntfy user add "$1" >/dev/null; fi; }
mkuser "$PHONE_USER" "$PHONE_PW"; mkuser "$DASH_USER" "$DASH_PW"
ntfy access "$PHONE_USER" "$TOPIC" rw >/dev/null; ntfy access "$DASH_USER" "$TOPIC" wo >/dev/null
chown -R ntfy:ntfy /var/lib/ntfy; systemctl restart ntfy
printf '%s:%s {\n\treverse_proxy 127.0.0.1:2586\n}\n' "$HOST" "$PORT" > /etc/caddy/conf.d/ntfy.caddy
caddy validate --config /etc/caddy/Caddyfile >/dev/null && systemctl reload caddy
(command -v ufw >/dev/null && ufw status | grep -q "Status: active" && ufw allow "$PORT"/tcp >/dev/null) || true
sleep 6
curl -fsS -m 20 -u "$DASH_USER:$DASH_PW" -H "Title: ntfy is installed" -d "If you can read this on your phone, alerts will reach you." "$SERVER/$TOPIC" >/dev/null && echo "test message sent"
echo
echo "Phone (ntfy app): server $SERVER   user $PHONE_USER   password $PHONE_PW   topic $TOPIC"
echo "Dashboard alert address: https://$DASH_USER:$DASH_PW@$HOST:$PORT/$TOPIC"
echo "(all of this is kept in $CRED)"
