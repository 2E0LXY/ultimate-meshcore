#!/bin/bash
# Install the UMC Net MQTT broker on a Debian server. Safe to run again.
# It adds its own user, folders and systemd service and touches nothing else.
set -euo pipefail
RAW=${RAW:-https://raw.githubusercontent.com/2E0LXY/ultimate-meshcore/main/server/umcnet}
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }

if ! command -v mosquitto >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mosquitto mosquitto-clients
fi
# The packaged default broker is not used; ours is a separate instance.
systemctl disable --now mosquitto >/dev/null 2>&1 || true

id umcnet >/dev/null 2>&1 || useradd --system --home-dir /opt/umcnet --shell /usr/sbin/nologin umcnet
install -d -o umcnet -g umcnet -m 750 /opt/umcnet
install -d -o umcnet -g umcnet -m 750 /var/lib/umcnet

for f in mosquitto.conf umcnet-user; do curl -fsSL "$RAW/$f" -o "/opt/umcnet/$f"; done
chmod 755 /opt/umcnet/umcnet-user
ln -sf /opt/umcnet/umcnet-user /usr/local/bin/umcnet-user
curl -fsSL "$RAW/umcnet-mosquitto.service" -o /etc/systemd/system/umcnet-mosquitto.service
[ -e /opt/umcnet/passwd ] || : > /opt/umcnet/passwd
[ -e /opt/umcnet/acl ] || : > /opt/umcnet/acl
chown umcnet:umcnet /opt/umcnet/passwd /opt/umcnet/acl
chmod 600 /opt/umcnet/passwd /opt/umcnet/acl

CRED=/root/umcnet-credentials.txt
if [ ! -s /opt/umcnet/users.json ]; then
  : > "$CRED"; chmod 600 "$CRED"
  for pair in "admin admin" "v4-repeater repeater" "v3-repeater repeater" "tdeck-client client"; do
    set -- $pair
    umcnet-user add "$1" "$2" >> "$CRED"
  done
  echo "accounts created; passwords are in $CRED"
fi

systemctl daemon-reload
systemctl enable --now umcnet-mosquitto
sleep 1
systemctl is-active umcnet-mosquitto
