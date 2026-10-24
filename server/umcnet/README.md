# UMC Net

A small MQTT network that joins Ultimate MeshCore repeaters and clients over the internet.
It is its own Mosquitto instance (own user, folders and systemd service), so it shares nothing
with the other services on the server. Caddy provides TLS in front of it.

```
repeater ──wss──► Caddy (443, TLS) ──► Mosquitto (127.0.0.1:9101) ◄──wss── repeater / client
```

Nodes connect to `wss://net.2e0lxy.uk/mqtt` with their own username and password. The firmware's
custom-broker mode already speaks this (`mqtt.custom.transport wss`).

## Topics (`umcnet/v1/<area>/...`)

| Topic | Who writes | Who reads | Meaning |
|---|---|---|---|
| `bus/rx` | bridging repeaters | everyone | a packet heard on RF |
| `node/<name>/status` | the node (retained) | everyone | state, version, uptime |
| `node/<name>/cmd` | admin | that node | a command for the node |
| `node/<name>/resp` | the node | admin | its reply |
| `client/<name>/tx` | that client | repeaters | a packet the client wants sent over RF |

`<area>` is a coverage area (`uk` to start), so separate regions can share one broker.

## Payload (`bus/rx`, `client/<name>/tx`)

```json
{"v":1,"o":"v4-repeater","s":1234,"t":1760000000,"r":-98,"n":7.5,"p":"<hex of the MeshCore packet>","m":"rf"}
```

`o` origin node, `s` its sequence number, `t` time, `r`/`n` RSSI and SNR where it was heard, `p` the
packet, `m` `rf` (heard on air) or `net` (came from the network). A repeater re-sends only `m:"rf"`
packets from other origins, and drops any packet it has already seen (MeshCore's own duplicate
table), so nothing loops.

## Roles

`admin` everything · `repeater` publishes `bus/rx`, reads `bus/rx` and `client/+/tx`, takes
commands on its own `cmd` topic · `client` reads `bus/rx`, publishes its own `tx` · `viewer` reads.

## Install

```
curl -fsSL https://raw.githubusercontent.com/2E0LXY/ultimate-meshcore/main/server/umcnet/install.sh | sudo bash
umcnet-user add <name> <admin|repeater|client|viewer>     # prints the password
# once the DNS record for net.2e0lxy.uk points at this server:
curl -fsSL https://raw.githubusercontent.com/2E0LXY/ultimate-meshcore/main/server/umcnet/enable-caddy.sh | sudo bash
```

Passwords for the first accounts are written to `/root/umcnet-credentials.txt` (mode 600) and are
never stored in the repository.

## Duty cycle

Re-sending traffic from the network over 869 MHz counts against the repeater's duty cycle. The
bridge is off by default, and a repeater drops network packets rather than exceed its limit.
