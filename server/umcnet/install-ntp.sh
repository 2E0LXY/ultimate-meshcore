#!/bin/bash
# Makes this UMC Net server an accurate time server for the repeaters.
#   * chrony keeps the server's clock to the UK's National Physical Laboratory (ntp1/ntp2.npl.co.uk, traceable to UTC(NPL)),
#     with the UK NTP pool as a fallback only if both NPL servers are unreachable
#   * it answers time requests on UDP 123 (rate-limited), so repeaters can use this server as their time server
# Run as root:  bash install-ntp.sh
# Then point the repeaters at it (dashboard Control tab, or the console):  set ntp.server1 <this host>
set -e
export DEBIAN_FRONTEND=noninteractive
command -v chronyd >/dev/null 2>&1 || { apt-get update -qq; apt-get install -y -qq chrony >/dev/null; }
systemctl disable --now systemd-timesyncd >/dev/null 2>&1 || true          # one clock keeper only
CONF=/etc/chrony/chrony.conf
# the distribution's own pool lines would compete with NPL: keep them, commented out
sed -i -E 's/^(pool|server) /# (UMC Net uses NPL) &/' "$CONF"
grep -q '^confdir /etc/chrony/conf.d' "$CONF" || echo "confdir /etc/chrony/conf.d" >> "$CONF"
mkdir -p /etc/chrony/conf.d
cat > /etc/chrony/conf.d/umcnet.conf <<'CFG'
# UMC Net time: the National Physical Laboratory first, the UK pool only as a fallback
server ntp1.npl.co.uk iburst prefer
server ntp2.npl.co.uk iburst prefer
pool uk.pool.ntp.org iburst maxsources 2
# keep stepping out of the way: small corrections are slewed, a big error at start-up is stepped
makestep 1 3
# serve the time to the repeaters (and anyone else), rate-limited
allow all
ratelimit interval 1 burst 16 leak 2
CFG
(command -v ufw >/dev/null && ufw status | grep -q "Status: active" && ufw allow 123/udp >/dev/null) || true
systemctl enable chrony >/dev/null 2>&1; systemctl restart chrony
sleep 10
echo "chrony: $(systemctl is-active chrony)"
chronyc -n sources | sed -n '1,12p'
chronyc tracking | grep -E "Reference ID|Stratum|System time|RMS offset|Leap status"
