# UMC Net

A small MQTT network that joins Ultimate MeshCore repeaters and clients over the internet.
It is its own Mosquitto instance (own user, folders and systemd service), so it shares nothing
with the other services on the server. Caddy provides TLS in front of it.

```
repeater ──wss──► Caddy (443, TLS) ──► Mosquitto (127.0.0.1:9101) ◄──wss── repeater / client
```

Nodes connect to `wss://net.2e0lxy.uk/mqtt` with their own username and password. The firmware's
custom-broker mode already speaks this (`mqtt.custom.transport wss`).

## Topics

The standard MeshCore MQTT layout, which the firmware's uplink already publishes, so analysers
and maps can read this broker as well:

| Topic | Who writes | Who reads | Meaning |
|---|---|---|---|
| `meshcore/<area>/<device id>/raw` | that repeater | repeaters, clients | a packet it heard: `{"origin":..,"origin_id":..,"timestamp":..,"type":"RAW","data":"<hex>"}` |
| `meshcore/<area>/<device id>/packets` | that repeater | clients | the same packet, decoded |
| `meshcore/<area>/<device id>/status` | that repeater (retained, with a last-will) | everyone | online or offline, version, radio |

`<area>` is the code set with `set mqtt.iata` (for example `LBA`), `<device id>` the repeater's
64-digit public key in capitals. Create a repeater's account with
`umcnet-user add <name> repeater --device <id>` and it can write only under its own id.

## How the bridge works

On a repeater, `set mqtt.custom.bridge on` makes the MQTT uplink also subscribe to
`meshcore/<area>/+/raw`. Each packet another repeater published is passed to the mesh as if it had
arrived by radio, after the bridge delay. The mesh drops what it has already seen, so nothing
loops, and forwards the rest by its normal rules (hop limit, regions, duty cycle). At most
`mqtt.custom.rate` packets a minute are passed on (default 20). Our own packets are skipped.

## Roles

`admin` everything · `repeater` writes only under its own device id, reads everyone's raw packets
and status · `client` and `viewer` read only.

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
