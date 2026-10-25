#!/bin/bash
# Installs the UMC Net dashboard beside the broker:
#   - a read-only "monitor" account for the broker,
#   - a service on 127.0.0.1:9102 (Python standard library only, nothing to pip install),
#   - the page at https://net.<domain>/ behind a login (the MQTT path /mqtt is unchanged).
# Run as root, after install.sh and enable-caddy.sh. Safe to run again: it updates in place.
set -euo pipefail
REF=${REF:-main}
RAW=${RAW:-https://raw.githubusercontent.com/2E0LXY/ultimate-meshcore/$REF/server/umcnet}
HOST=${HOST:-net.2e0lxy.uk}
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
[ -d /opt/umcnet ] || { echo "the broker is not installed here (run install.sh first)"; exit 2; }

getent group umcnet-dash >/dev/null || groupadd --system umcnet-dash
id umcnet-dash >/dev/null 2>&1 || useradd --system --gid umcnet-dash --home-dir /nonexistent --shell /usr/sbin/nologin umcnet-dash
install -d -o root -g root -m 755 /opt/umcnet-dash
install -d -o umcnet-dash -g umcnet-dash -m 750 /var/lib/umcnet-dash
for f in umcnet_dash.py dash.html umcnet-dash.service umcnet_admin.py umcnet-admin.service; do curl -fsSL "$RAW/dash/$f" -o "/opt/umcnet-dash/$f.new"; done
curl -fsSL "$RAW/umcnet-user" -o /opt/umcnet/umcnet-user.new && chmod 755 /opt/umcnet/umcnet-user.new && mv /opt/umcnet/umcnet-user.new /opt/umcnet/umcnet-user
python3 -m py_compile /opt/umcnet-dash/umcnet_dash.py.new
mv /opt/umcnet-dash/umcnet_dash.py.new /opt/umcnet-dash/umcnet_dash.py; mv /opt/umcnet-dash/dash.html.new /opt/umcnet-dash/dash.html
mv /opt/umcnet-dash/umcnet-dash.service.new /etc/systemd/system/umcnet-dash.service
python3 -m py_compile /opt/umcnet-dash/umcnet_admin.py.new && mv /opt/umcnet-dash/umcnet_admin.py.new /opt/umcnet-dash/umcnet_admin.py
mv /opt/umcnet-dash/umcnet-admin.service.new /etc/systemd/system/umcnet-admin.service
chmod 644 /opt/umcnet-dash/umcnet_admin.py
chmod 644 /opt/umcnet-dash/umcnet_dash.py /opt/umcnet-dash/dash.html
/opt/umcnet/umcnet-user export          # the dashboard keeps its own copy of the account list (no passwords)

# the broker account the dashboard listens with
if [ ! -s /opt/umcnet-dash/mqtt.pass ]; then
  NEWACCOUNT=1; pw=$(/opt/umcnet/umcnet-user add dash monitor | sed -n 's/.*password: //p')
  install -m 640 -o root -g umcnet-dash /dev/null /opt/umcnet-dash/mqtt.pass; printf '%s' "$pw" > /opt/umcnet-dash/mqtt.pass
else
  /opt/umcnet/umcnet-user list | grep -q '^dash ' || { echo "the dash account is missing; remove /opt/umcnet-dash/mqtt.pass and run again"; exit 3; }
  /opt/umcnet/umcnet-user add dash monitor --password "$(cat /opt/umcnet-dash/mqtt.pass)" >/dev/null     # refresh its permissions
fi

# the control channel's own broker account: it may send commands and read answers, nothing else
if [ ! -s /opt/umcnet-dash/ctl.pass ]; then
  NEWACCOUNT=1; cpw=$(/opt/umcnet/umcnet-user add controller controller | sed -n 's/.*password: //p')
  install -m 640 -o root -g umcnet-dash /dev/null /opt/umcnet-dash/ctl.pass; printf '%s' "$cpw" > /opt/umcnet-dash/ctl.pass
else
  /opt/umcnet/umcnet-user add controller controller --password "$(cat /opt/umcnet-dash/ctl.pass)" >/dev/null
fi

# the dashboard login (user "admin"), kept with the other credentials
CRED=/root/umcnet-credentials.txt; touch "$CRED"; chmod 600 "$CRED"
if ! grep -q '^dashboard-login ' "$CRED"; then
  webpw=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | cut -c1-20)
  printf 'dashboard-login admin %s   (https://%s/)\n' "$webpw" "$HOST" >> "$CRED"
fi
webpw=$(grep '^dashboard-login ' "$CRED" | awk '{print $3}')
hash=$(caddy hash-password --plaintext "$webpw")
# the admin helper checks the current password with its own salted hash when the login is changed
install -d -m 700 /etc/umcnet-dash
[ -s /etc/umcnet-dash/admin.pbkdf2 ] || WEBPW="$webpw" python3 -c "import hashlib,os,secrets;s=secrets.token_bytes(16);print('200000$%s$%s' % (s.hex(), hashlib.pbkdf2_hmac('sha256', os.environ['WEBPW'].encode(), s, 200000).hex()))" > /etc/umcnet-dash/admin.pbkdf2 && chmod 600 /etc/umcnet-dash/admin.pbkdf2

# publish through Caddy, keeping the old file if Caddy does not like the result
CF=/etc/caddy/Caddyfile; mkdir -p /etc/caddy/conf.d
cp -a /etc/caddy/conf.d/umcnet.caddy /etc/caddy/conf.d/umcnet.caddy.backup-before-dash 2>/dev/null || true
curl -fsSL "$RAW/umcnet.caddy" | sed "s/net\.2e0lxy\.uk/$HOST/; s|__DASH_HASH__|$(printf '%s' "$hash" | sed 's/[&|\\]/\\&/g')|" > /etc/caddy/conf.d/umcnet.caddy.new
mv /etc/caddy/conf.d/umcnet.caddy.new /etc/caddy/conf.d/umcnet.caddy
if caddy validate --config "$CF" --adapter caddyfile >/tmp/caddy-validate.log 2>&1; then
  systemctl reload caddy
else
  tail -5 /tmp/caddy-validate.log
  [ -f /etc/caddy/conf.d/umcnet.caddy.backup-before-dash ] && cp -a /etc/caddy/conf.d/umcnet.caddy.backup-before-dash /etc/caddy/conf.d/umcnet.caddy
  echo "Caddy rejected the new site file; the old one is back"; exit 4
fi

systemctl daemon-reload; systemctl enable --now umcnet-admin umcnet-dash >/dev/null 2>&1; systemctl restart umcnet-admin umcnet-dash
# the broker only needs to re-read its permissions when the monitor account was just created; a restart drops every repeater for a minute
if [ -n "${NEWACCOUNT:-}" ]; then systemctl reload umcnet-mosquitto 2>/dev/null || systemctl restart umcnet-mosquitto; fi
sleep 3
systemctl is-active umcnet-admin umcnet-dash umcnet-mosquitto caddy
curl -fsS http://127.0.0.1:9102/api/health && echo
echo "dashboard: https://$HOST/   login: admin / $webpw   (also in $CRED)"
