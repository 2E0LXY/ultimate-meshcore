#!/bin/bash
# Makes this server a time server for the UMC Net repeaters (NTP, UDP port 123), so every repeater keeps the same clock as the
# broker and the dashboard. Signed remote commands are accepted only within a minute of the repeater's clock, so a shared,
# reliable time source matters. chrony keeps this server right from the public pool and answers the repeaters, rate-limited.
# Run as root:  bash install-time.sh        then on each repeater:  set ntp.server1 <this server's name>
set -e
export DEBIAN_FRONTEND=noninteractive
command -v chronyd >/dev/null || apt-get install -y -qq chrony >/dev/null
mkdir -p /etc/chrony/conf.d
cat > /etc/chrony/conf.d/umcnet.conf <<'CONF'
# UMC Net: serve the time to the repeaters, rate-limited
allow all
ratelimit interval 1 burst 16 leak 2
CONF
systemctl enable chrony >/dev/null 2>&1; systemctl restart chrony; sleep 6
(command -v ufw >/dev/null && ufw status | grep -q "Status: active" && ufw allow 123/udp >/dev/null) || true
echo "chrony: $(systemctl is-active chrony)"; chronyc tracking | grep -E "Reference|Stratum|System time"
echo "serving on: $(ss -lun | awk '$4 ~ /:123$/ {print $4}' | tr '\n' ' ')"
