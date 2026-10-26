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


## The dashboard (admin page)

The broker itself has no web admin. Accounts are managed with `umcnet-user` on the server, and everything else
you can see is in the **dashboard**: `https://net.<your domain>/`, behind a login (user `admin`; the password is
printed by the installer and kept in `/root/umcnet-credentials.txt`).

```
curl -fsSL https://raw.githubusercontent.com/2E0LXY/ultimate-meshcore/main/server/umcnet/dash/install-dash.sh | sudo bash
```

It runs as its own unprivileged service on `127.0.0.1:9102` (Python standard library only), listens to the broker
with a read-only `monitor` account, tails the broker's log, samples the machine, and keeps 14 days of history in
SQLite under `/var/lib/umcnet-dash`. About 20 MB of memory.

| Tab | What it shows |
|---|---|
| Overview | Repeaters and clients online, packets and messages a minute, dials for CPU, memory, disk, load, certificate and logins, a live data-flow diagram, the checks, charts per repeater and bandwidth, the latest events |
| Network | A map of every node the repeaters hear, with a line for each link coloured by hops (green direct, blue 1 hop, purple 2, amber 3, orange 4+), filters, a table of links and the journey of each packet |
| Repeaters | One card per repeater: device id, model, firmware, radio, battery, uptime, noise floor, airtime, counters, clock, packet types; which repeaters hear the same packets and how many hear each |
| Clients | Everything connected to the broker: account, address, since when, keepalive, protocol, logins in the last hour |
| Accounts | Every account with its role, bound device id, whether it is online, last login and last data |
| Traffic | Live packets with the sender (an advert's name, or a hash matched to a known repeater) and the repeater that passed it on; packet types; delivery delay |
| Diagnostics | All checks, refused logins by address, the event history (14 days) |
| Broker | The broker's own statistics: every `$SYS` value, load averages, history |
| System | CPU, memory, disk, network, services, the TLS certificate, the dashboard's own footprint |
| Log | The broker's log, filterable |

The checks cover: the dashboard's link to the broker, each service, broker restarts, the certificate (amber under 14
days, red under 5), disk, memory, load, refused logins and where they came from, clients that reconnect too often, a
repeater account that is not bound to a device id, repeaters that are offline or silent, a repeater whose clock is
wrong, and messages the broker drops.

Limits: a publish that the access list silently drops is not logged by Mosquitto, so it cannot be shown. The
history starts when the dashboard is installed.


## Controlling repeaters, approvals and settings (dashboard 2.0)

**Control tab.** Pick a repeater, press *Read settings* to fill the boxes with what it has now, change a value and press
*Apply*, or use a quick action (advert, discover neighbours, stats, restart) or the console. Every command is checked,
signed and recorded in the audit log; restart, radio, region, bridge and similar commands ask you to confirm first.

How it is kept safe:

| Layer | What it does |
|---|---|
| Off by default | The repeater obeys nothing until you set a control key and `set mqtt.control on`. |
| Signature | Each command carries an HMAC-SHA-256 over device id, time, a counter and the command, made with a key only the dashboard and that repeater hold. A wrong signature gets no answer, so it cannot be used to test guesses. |
| Freshness | The time must be within 5 minutes, later than the repeater's last restart, and the counter must be higher than the last one used: a recorded command cannot be replayed. |
| Allow-list | Only reads, adverts, stats, clock, restart, and settings for the radio, forwarding, adverts, identity and UMC Net. Passwords, private keys, WiFi, access point, broker address and login, the control key itself, and firmware installs are refused by the repeater whatever the dashboard sends. |
| Rate limit | 60 commands a minute (enough to read every setting in one go). |
| Broker accounts | The `controller` account may only publish to `umcnet/v1/<area>/dev/<id>/cmd` and read `.../resp`. A repeater may read only its own command topic and write only its own answers. |

To put a repeater under control: *Control setup* on its card shows a block of commands (broker address, its account and
the control key). Paste it into the repeater's Console page, then press *Read settings*.

**Approving new repeaters.** *Add an account* on the Accounts tab creates a repeater account with no device id. It is
*pending*: it can connect and listen to statuses, but it cannot publish or be controlled. When the repeater connects, the
dashboard shows the account, the address it came from and the first characters of its device id; you paste its full
64-character id (under Identity, or on its display) and press *Approve*. The id must match the one that connected. Until
then nothing it sends is accepted. *Block* shuts an account out immediately; *New password* and *Remove* are there too.

**Settings tab.** Limits for each check, how long history is kept, whether risky commands need confirming, alerts to a
web address or an ntfy topic (silent repeater, back again, waiting for approval, many refused logins, certificate,
disk), the dashboard password, downloads (events, audit log, repeaters as CSV; settings as JSON) and service restarts.

**Privilege.** The dashboard runs unprivileged. Account changes, the dashboard password and service restarts go through
`umcnet_admin.py`, a small root helper on a Unix socket that only the dashboard's user can open; it accepts a fixed list
of operations and checks every argument.


### Joining with one line (dashboard 2.2, firmware 0.1.21)

Add a repeater on the **Accounts** tab (or press **Join code** on its row) and the dashboard shows one line:

```
set mqtt.join UMC1.AQBHQlILdWktdGVzdC1vbmUT...
```

Paste it into the repeater's Console (or the *Join code* box on its MQTT page). The repeater applies the broker (built into the
firmware, or carried in the code), the account and password, the area code, raw packets on, transmitted off, the bridge as set in
the dashboard's Settings, and the remote-control key when the repeater has been approved, then connects. `set mqtt.umcnet off|on`
switches the link, and `get mqtt.umcnet` reports `on, joined as <account>, area LBA, broker custom:wss:up, bridge on, control on`.

The code is `UMC1.` plus base64url of: version, flags (control key, bridge, own host), the three-character area, the account and
password, optionally a host and port, optionally the 32-byte control key, and a 3-byte SHA-256 check, so a mistyped or cut-off code
is refused rather than half applied. It contains the repeater's password: treat it like one. A new code gives the account a new
password. The format is in `src/helpers/mqtt/JoinCode.h` and `make_join_code` in `umcnet_dash.py`, tested against each other.
