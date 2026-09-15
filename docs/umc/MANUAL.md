# Ultimate MeshCore — User Manual

**Version 0.1.0** · Covers the Heltec V3 / V3.2 repeater firmware. Sections marked *(coming soon)* describe features that are planned but not in this release.

---

## Contents

1. [What is Ultimate MeshCore?](#1-what-is-ultimate-meshcore)
2. [What you need](#2-what-you-need)
3. [Installing the firmware](#3-installing-the-firmware)
4. [First-time setup](#4-first-time-setup)
5. [The device display and button](#5-the-device-display-and-button)
6. [The web interface](#6-the-web-interface)
7. [Dashboard](#7-dashboard)
8. [Radio](#8-radio)
9. [Mesh & routing](#9-mesh--routing)
10. [Identity & access](#10-identity--access)
11. [Regions](#11-regions)
12. [Network (WiFi, hotspot, services, time)](#12-network)
13. [MQTT](#13-mqtt)
14. [Bridge](#14-bridge)
15. [Power & hardware (GPS, display)](#15-power--hardware)
16. [Neighbours, routes, trace and live traffic](#16-neighbours-routes-trace-and-live-traffic)
17. [Console](#17-console)
18. [Firmware updates](#18-firmware-updates)
19. [Backup, restore and factory reset](#19-backup-restore-and-factory-reset)
20. [Using apps and other tools](#20-using-apps-and-other-tools)
21. [Security](#21-security)
22. [Troubleshooting](#22-troubleshooting)
23. [Command reference A–Z](#23-command-reference-az)
24. [Glossary A–Z](#24-glossary-az)

---

## 1. What is Ultimate MeshCore?

Ultimate MeshCore (UMC) is firmware for LoRa radios that run the [MeshCore](https://github.com/meshcore-dev/MeshCore) mesh network. It is fully compatible with standard MeshCore nodes and apps, and adds:

- a **web interface** in your browser for every setting,
- a **setup wizard** on its own WiFi hotspot,
- **firmware updates** from the internet, from a file, or with a USB web flasher,
- up to **three saved WiFi networks**, static IP, a `.local` name, and an automatic **rescue hotspot**,
- a **display** that cycles through the address, settings and live traffic,
- MQTT observer uploads, ESP-NOW bridging, telnet, region presets, backup and restore.

It builds on upstream MeshCore 1.17.1 and the MeshCore-EastMesh fork, and brings in ideas from many community projects (see `docs/umc/SOURCES.md`).

### Firmware types

| Type | What it does | Status |
|---|---|---|
| **Repeater** | Relays mesh packets to extend coverage. Managed over WiFi, USB, or remotely over the mesh. | Available (Heltec V3/V3.2) |
| **Client (companion)** | Your personal radio, used with the MeshCore phone/desktop apps. | *(coming soon)* |
| **Room server** | A shared message board on the mesh. | *(coming soon)* |

### Supported hardware

| Board | Repeater | Client |
|---|---|---|
| Heltec WiFi LoRa 32 V3 / V3.2 | ✅ | *(coming soon)* |
| Heltec V4 (OLED, TFT, R8) | ✅ (not yet tested on hardware) | *(coming soon)* |
| LilyGo T-TWR with SX1262 add-on | *(coming soon)* | *(coming soon)* |

---

## 2. What you need

- A supported board and a suitable **antenna for your band** (never transmit without an antenna).
- A **data** USB cable (some cables only charge).
- For USB flashing: a computer with **Chrome** or **Edge**.
- For setup: any phone, tablet or computer with WiFi and a web browser.
- Optional: a home WiFi network (2.4 GHz only) for remote management, internet updates and MQTT.

---

## 3. Installing the firmware

### 3.1 Web flasher (easiest)

1. Open **https://2e0lxy.github.io/ultimate-meshcore/** in Chrome or Edge on a computer.
2. Choose your **board** and **firmware type**.
3. Plug the device in and press **Install**, then pick its serial port.
4. When asked **“Erase device?”**:
   - **No** — update an existing MeshCore / EastMesh / UMC device and **keep** its identity, name, radio settings and everything else.
   - **Yes** — fresh install. All data is erased and a new identity is created.
5. Wait for “Installation complete”. The device restarts.

The flasher always offers the **latest build** of the `main` branch.

If the port doesn't appear: hold **PRG/BOOT**, tap **RST**, release **PRG**, and try again. Windows may need the CP210x USB driver.

### 3.2 esptool (command line)

Fresh install (erases everything):

```bash
esptool --chip esp32s3 erase-flash
esptool --chip esp32s3 write-flash 0x0 ultimate-meshcore-<version>-heltec_v3_repeater-merged.bin
```

Update and keep settings:

```bash
esptool --chip esp32s3 write-flash 0x0 bootloader.bin 0x8000 partitions.bin 0xe000 boot_app0.bin 0x10000 firmware.bin
```

Binaries are attached to the **latest** release on GitHub and published on the flasher site.

> **Back up first.** `esptool --chip esp32s3 read-flash 0 0x800000 backup.bin` saves the whole 8 MB flash (identity and settings included) so you can restore it exactly.

### 3.3 Building from source

```bash
git clone https://github.com/2E0LXY/ultimate-meshcore
cd ultimate-meshcore
pio run -e umc_heltec_v3_repeater
```

---

## 4. First-time setup

A new or erased device, or one where you run `setup start`, enters **setup mode**.

1. The display shows **SETUP: join WiFi**, the hotspot name `UMC-Setup-XXXX` and **Open – no password**.
2. Join that WiFi network from your phone or computer. The setup page usually opens by itself. If not, browse to **http://192.168.4.1**.
3. Follow the wizard:

| Step | What you set | Notes |
|---|---|---|
| Welcome | — | Shows the board, firmware type and version. Nothing is saved until the end. |
| Region & radio | Radio preset, TX power, duty cycle | Pick the preset used by your local mesh. In the UK/EU 869.4–869.65 MHz band the wizard suggests a **10 %** duty cycle, the legal limit there. |
| Name & location | Node name, optional latitude/longitude | **Pick from map…** opens OpenStreetMap; paste the coordinates or map link. Location is rounded to about 100 m. |
| Admin password | Admin password (8+ characters), guest password (repeaters) | Protects the web page, telnet and remote admin over the mesh. |
| Home WiFi | Network name and password | **Scan** lists nearby networks. Skip to stay on the hotspot. |
| Services | Telnet, MQTT location code | Everything can be changed later. |
| Review | — | Shows exactly what will change, then **Apply & finish**. |

4. The device joins your WiFi. Reconnect your phone/computer to your home network and open **http://umc-<name>.local/** or the IP address shown on the display.

Existing settings are **kept and pre-filled**: running setup again only changes what you edit.

---

## 5. The device display and button

### Display cycle

By default the display repeats this cycle:

| Screen | Default time | Shows |
|---|---|---|
| **Network** | 6 s | WiFi name, `.local` name, signal, and the **IP address flashing** in a bar. In setup mode: hotspot name and “Open – no password”. In rescue mode: hotspot name and PIN. |
| **Radio** | 5 s | Frequency, bandwidth, SF, CR, TX power, duty cycle, RX gain, AGC, noise floor |
| **Mesh** | 5 s | Node name, repeat on/off, flood hops, advert intervals, loop detection, path hash size, TX/RX delays |
| **WiFi** | 5 s | SSID, IP, signal and channel, hotspot mode, web and telnet status |
| **Status** | 5 s | Uptime, battery, UTC clock, packets received/sent, UMC version |
| **Traffic** | 60 s | Packets per minute and the last 5 packets, e.g. `RX CHAN F3 -97/6` (received channel message, flood, 3 hops, −97 dBm, SNR 6) |

Change the timings on **Power & hardware → Display** or with `set display.ip|page|traffic <seconds>`. For the IP to flash exactly once a minute, set traffic to 35 s.

Display modes (`set display.mode`):

- `cycle` — the cycle above (default)
- `status` — network screen only
- `off` — blank; press the button to wake it

`set display.timeout <seconds>` blanks the screen after that long without a button press (0 = never). Long-term installs benefit from blanking to reduce OLED burn-in.

### Button (PRG)

| Action | Result |
|---|---|
| Short press | Wake the display, then step through Network → Radio → Mesh → WiFi → Status → Traffic. The automatic cycle pauses for 30 s. |
| Long press | Power off the device. |

---

## 6. The web interface

Open `http://<device IP>/` or `http://umc-<name>.local/` from any device on the same network.

- **Sign in** with the admin password. Sessions end after 30 minutes idle (`set http.timeout`).
- After 5 wrong passwords, sign-in is locked for 1 minute.
- Sign-in is refused while the admin password is still the factory default `password`. Change it over USB (`password <new>`) or re-run setup.
- The sidebar lists every page. On a phone, tap ☰.
- Each setting has its own **Save** button, and **Save all changes** saves everything you edited (changed fields are outlined). Replies from the device appear beside each field and as pop-ups.
- If the device reboots or moves networks, a **Device not reachable** screen explains why, links to its home-network address, and reconnects automatically.

Every web setting is a normal command. You can do the same from the USB serial console, telnet, or remotely over the mesh (see [§23](#23-command-reference-az)).

---

## 7. Dashboard

- **Node summary**: uptime, battery, UTC clock, packets received/sent, neighbour count, transmit queue, repeat status, free memory.
- **Network**: WiFi network, LAN IP, signal, hotspot, `.local` name, MQTT status.
- **Radio**: preset name, frequency, BW · SF · CR, TX power, noise floor, last RSSI/SNR, TX airtime.
- **Quick actions**: flood advert, zero-hop advert, **Set clock from this browser**, refresh.
- A banner appears when a **firmware update is available**.

The dashboard refreshes every 15 seconds.

---

## 8. Radio

All nodes in a mesh must use the same **frequency, bandwidth and spreading factor**. The coding rate can differ.

| Setting | Command | Range / default | Explanation |
|---|---|---|---|
| Preset + frequency/BW/SF/CR | `set radio <MHz>,<kHz>,<SF>,<CR>` | e.g. `869.618,62.5,8,8` | Applies **immediately** on UMC (no reboot). |
| TX power | `set tx <dBm>` | 1–22 | Radio chip power. Boards with an amplifier (Heltec V4) add gain on top. Stay within your licence or local limits. |
| Duty cycle | `set dutycycle <%>` | 1–100, default 50 | Maximum share of time spent transmitting. **UK/EU 869.4–869.65 MHz: 10 %.** |
| RX boosted gain | `set radio.rxgain on\|off` | on | Better receive sensitivity for slightly more current. |
| AGC reset interval | `set agc.reset.interval <s>` | 0 = off, multiples of 4 | Periodically resets the receiver's gain control. **4** cures “deafness” caused by strong nearby signals. |
| Channel activity detection | `set cad on\|off` | off | Listens for LoRa activity before transmitting. |
| Interference threshold | `set int.thresh <n>` | 0 | Defers transmission when the channel is noisy. |
| Temporary radio test | `tempradio <MHz>,<kHz>,<SF>,<CR>,<minutes>` | — | Tries settings for a while, then reverts. Not saved. |

**Presets** (same as the MeshCore apps): EU/UK Narrow (869.618 MHz, 62.5 kHz, SF8), EU/UK Medium Range, EU/UK Long Range, Switzerland, Czech Republic, Portugal 869/433, EU 433 MHz, USA/Canada, USA Arizona, USA Philly, Australia (and Narrow, Mid, SA/WA/QLD), New Zealand (and Narrow), Vietnam.

---

## 9. Mesh & routing

*(Repeaters and room servers)*

| Setting | Command | Range / default | Explanation |
|---|---|---|---|
| Repeat | `set repeat on\|off` | on | Turn packet relaying on or off. |
| Loop detection | `set loop.detect off\|minimal\|moderate\|strict` | minimal | Drops flood packets that appear to be looping. |
| Advert path hash size | `set path.hash.mode 0\|1\|2` | 0 (1 byte) | Size of this node's ID in its own adverts. 2- and 3-byte IDs are safe on firmware 1.14+. Doesn't affect what it forwards. |
| Max flood hops | `set flood.max <n>` | 0–64, 64 | Floods that have already travelled more hops are not repeated. |
| Max hops, unscoped | `set flood.max.unscoped <n>` | 0–64 | Hop limit for packets without a region. |
| Max hops, adverts | `set flood.max.advert <n>` (alias `advert.hops.max`) | 0–64, 8 | Hop limit for flooded adverts. |
| Max hops, channel messages | `set group.hops.max <n>` | 0–64, 64 | How far public/group channel messages are relayed. 0 = never relay them. |
| Extra ACKs | `set multi.acks 0\|1` | — | Sends acknowledgements twice for reliability. |
| Flood retransmit delay | `set txdelay <0–2>` | 0.5 | Random wait before repeating floods, which reduces collisions. |
| Direct retransmit delay | `set direct.txdelay <0–2>` | 0.2 | The same for direct (routed) packets. |
| RX delay | `set rxdelay <0–20>` | 0 | Experimental: stronger-signal repeaters forward first. |
| Zero-hop advert | `set advert.interval <minutes>` | 0 or 60–240 | Announces the node to direct neighbours. |
| Flood advert | `set flood.advert.interval <hours>` | 0 or 3–168 | Announces across the mesh. UK guidance: use an **odd** number of hours (e.g. 51). |

Actions: `advert` (flood advert now), `advert.zerohop`, `discover.neighbors`.

---

## 10. Identity & access

| Setting | Command | Explanation |
|---|---|---|
| Node name | `set name <name>` | Up to 23 bytes when a location is included, 31 without. |
| Latitude / longitude | `set lat <deg>`, `set lon <deg>` | Optional. Round to 2–3 decimals to avoid pinpointing your home. **Set location from map…** helps. |
| Owner info | `set owner.info <text>` | Shown to others on request. `\|` becomes a new line. |
| Admin password | `password <new>` | Minimum 8 characters recommended (the web page requires it). |
| Guest password | `set guest.password <pw>` | Blank lets anyone log in as guest to view basic stats. Never reuse other passwords here: admins can read it remotely. |
| Public key | `get public.key` | This node's identity. |
| Private key | `get prv.key` / `set prv.key <hex>` | Keep it secret. Importing a key makes this device take over that identity (after reboot). |
| Permissions (ACL) | `setperm <pubkey> <0-3>` | 0 guest, 1 read-only, 2 read-write, 3 admin. Omit the number to remove. |

---

## 11. Regions

Regions limit how far **flood** traffic spreads, so local chatter stays local.

- Each repeater keeps a **region tree**. `*` is everything without a region.
- **F / Flooding on** means the repeater repeats floods for that region.
- Region names are **case-sensitive**. Every repeater in the same area must use exactly the same name: `yorkshire` and `Yorkshire` are different regions.
- Changes work immediately but are **lost on reboot** until you press **Save regions** (`region save`).

On the **Regions** page:

- The tree lists every region. Each row has a **Flooding** switch, **Set home** and **Remove**. Remove deletes sub-regions first and asks before doing so.
- **UK presets** add names used on the public map: `yorkshire`, `northwest`, or `uk` containing both.
- **Add region** creates a region under a parent.
- **Define in one line** uses `region def`, e.g. `uk yorkshire leeds|yorkshire wakefield`.

Commands: `region`, `region put <name> [parent]`, `region remove <name>`, `region allowf <name>`, `region denyf <name>`, `region home <name>`, `region default <name>`, `region def <tokens>`, `region preset yorkshire|northwest|uk`, `region save`.

---

## 12. Network

### 12.1 WiFi networks

- Save up to **three** networks. The device tries them in order and moves to the next if one fails.
- **Scan…** lists nearby networks. Tap one to fill in its name.
- Passwords are never shown, only “password set”.

| Command | Explanation |
|---|---|
| `set wifi.ssid <name>` / `set wifi.pwd <pw>` | Network 1 |
| `set wifi.ssid2 …` / `set wifi.pwd2 …`, `wifi.ssid3` / `wifi.pwd3` | Networks 2 and 3 |
| `wifi clear <1-3>` | Forget a network |
| `wifi scan` then `get wifi.scan` | Scan |
| `get wifi.status` | Connection, IP, channel, signal, gateway health |
| `wifi reconnect` | Drop and rejoin |
| `set wifi.enabled on\|off` | WiFi radio on/off (off also stops the hotspot, except during setup) |
| `set wifi.powersaving none\|min\|max` | WiFi power saving (more saving = slower web page) |

The device checks every 30 seconds that your router is still reachable. If the router stops responding for 3 minutes, it reconnects by itself.

### 12.2 IP address and name

| Command | Explanation |
|---|---|
| `set net.ip dhcp` | Automatic address (default) |
| `set net.ip <ip> <mask> <gateway> [dns]` | Static address, e.g. `192.168.1.50 255.255.255.0 192.168.1.1` |
| `set net.hostname <name>` | Blank = automatic `umc-<node name>` |
| `set net.mdns on\|off` | `http://<hostname>.local/` on the network |

### 12.3 Hotspot (access point)

| Mode (`set ap.mode`) | Behaviour |
|---|---|
| `auto` (default) | Hotspot for **first setup** (open network), and a **rescue hotspot** whenever no saved WiFi has connected for `ap.rescue` seconds (default 60). Rescue stops once WiFi is back and nobody is using it. |
| `on` | Always on, alongside WiFi |
| `off` | Never (setup mode still uses it) |

- The hotspot address is always **192.168.4.1**. Any website you type redirects to the device page.
- The **setup hotspot** is open (no password).
- **Rescue** and **always-on** hotspots use `ap.password`, or the **device PIN** if none is set. The PIN is 8 digits, shown on the display, and changed with `set pin <8 digits>`.
- `get ap.status` shows whether it's up and how many clients are connected.

### 12.4 Services

| Command | Default | Explanation |
|---|---|---|
| `set http on\|off` | on | Web interface on port 80 |
| `set http.timeout <minutes>` | 30 | Idle sign-out time |
| `set telnet on\|off` | off | Password-protected command line on port 23. Only starts once the admin password is not the default. Plain text: use on trusted networks only. |
| `set web on\|off` | off | The classic EastMesh HTTPS panel on port 443 (uses more memory) |
| `set web.stats on\|off` | — | Stats history for the classic panel |

### 12.5 Time

- The mesh always uses **UTC**. On WiFi the clock sets itself from time servers (`ntp.server1–3`, default `uk.pool.ntp.org`, `time.cloudflare.com`, `time.google.com`).
- Without WiFi, use **Set clock from this browser** on the dashboard or firmware page, or `time <epoch seconds>`.
- `set timezone <POSIX TZ>` only affects local-time display (default Europe/London).
- The Heltec V3 has **no backup clock battery**: after a power cut, the time is wrong until WiFi or you set it again.

---

## 13. MQTT

MQTT uploads what the repeater hears to network maps and analysers.

1. Set a **location code** (IATA airport code for your area, e.g. `LBA`): `set mqtt.iata LBA`. Brokers stay idle while it is `UNSET`.
2. Enable **up to two brokers**: `set mqtt.meshmapper on` (global), `set mqtt.waev on`, `set mqtt.eastmesh-au on`, or a **custom** broker.
3. Choose what to publish: `mqtt.packets`, `mqtt.raw`, `mqtt.tx`, `mqtt.status` (on/off).
4. Optional: `mqtt.owner <64-hex public key>` and `mqtt.email <address>` identify you to brokers that use JWT authentication.

Custom broker: `set mqtt.custom on`, `mqtt.custom.host`, `mqtt.custom.port`, `mqtt.custom.transport tcp|wss`, `mqtt.custom.username`, `mqtt.custom.password`.

Status: `get mqtt.status` shows WiFi, time sync, location code and each broker (`conn` = connecting, `up` = connected). Topics are `meshcore/<IATA>/<device>/packets|raw|status`.

---

## 14. Bridge

A bridge links two LoRa areas through another medium. The Heltec V3 build includes **ESP-NOW** (2.4 GHz, directly between two nearby devices).

| Command | Explanation |
|---|---|
| `set bridge.enabled on\|off` | Start/stop the bridge |
| `set bridge.source logTx\|logRx` | Bridge packets this node transmits (default) or receives |
| `set bridge.delay <ms>` | Delay before a bridged packet enters the mesh (0–10000, default 500) |
| `set bridge.channel <1-14>` | ESP-NOW channel. **Must match your WiFi channel** when connected (see `get wifi.status`). |
| `set bridge.secret <text>` | Shared secret, up to 15 characters, identical on both ends |
| `get bridge.type` | Which bridge this build has |

---

## 15. Power & hardware

| Setting | Command | Explanation |
|---|---|---|
| Power saving | `powersaving on\|off` | Sleep between packets. On UMC builds the WiFi services keep the processor awake, so this has little effect. |
| Battery calibration | `set adc.multiplier <n>` | 0 = board default |
| GPS | `gps on\|off`, `gps advert none\|share\|prefs`, `gps setloc`, `gps sync` | Only with a GPS module fitted |
| Display | `display.mode`, `display.ip`, `display.page`, `display.traffic`, `display.timeout` | See [§5](#5-the-device-display-and-button) |
| Board, boot reason | `board`, `get pwrmgt.bootreason` | Information |
| Power off | `poweroff` | Or long-press the button |

---

## 16. Neighbours, routes, trace and live traffic

- **Neighbours** page: repeaters heard directly, with how long ago and SNR. **Forget** removes one. **Discover neighbours** asks nearby repeaters to answer.

### Routes & trace

The repeater learns a **route table** from every advert it hears. Each advert carries the chain of repeaters it passed through, so the table shows, for every node heard, the route from this repeater back to that node.

- **Routes & trace** page: every node with its type, key, route (hops shown by key prefix and, when known, the repeater's name), hop count, when it was heard and SNR. Type in **Find** to filter by name or key.
- **Trace**: sends a trace packet out along the route and back. Each repeater on the way adds the SNR it received, and the result table shows the signal quality of every hop plus the final hop back to this repeater. No answer within 30 seconds means a hop didn't hear or forward it.
- **Add route / Edit route**: pin your own out-and-back list of repeater key prefixes (2 hex digits each, e.g. `27,da,27`) to use when tracing that node. **Unpin** goes back to the learned route.
- **Trace custom path**: trace any list of repeaters, e.g. `a1,b2,a1`.
- **Forget** removes a node from the table. The table holds the 48 most recently heard nodes (pinned routes are kept).

| Command | Explanation |
|---|---|
| `routes` | Summary list of nodes and hop counts |
| `route <name or key>` | Show a node's learned route, SNR, age and pinned route |
| `route find <text>` | Same, searching by name or key prefix |
| `route pin <node> <a1,b2,a1>` | Add/replace the trace route for a node |
| `route unpin <node>` / `route forget <node>` | Remove the pinned route / forget the node |
| `trace route <node>` | Trace out and back along the node's route |
| `trace <a1,b2,a1>` | Trace a custom list of repeaters |
| `get trace` | Result: `waiting`, `timeout` or `done` with the SNR for each hop and the final SNR |
- **Live traffic** page: the last 16 packets (direction, type, flood/direct, hops, RSSI, SNR, size), totals and packets per minute, with RX/TX and type filters and pause. Refreshes every 3 s.
- `get traffic`: total packets and the last 16 packets with age, type, route (F flood / D direct), hops, RSSI and SNR.
- `stats-core`, `stats-radio`, `stats-packets`: JSON statistics. `clear stats` resets them.
- `log start|stop|erase` and `log` (USB): a packet log stored on the device.

Packet types: ADVERT (node announcements), CHAN (channel message), MSG (direct message), ACK, PATH, REQ/RESP (requests and responses such as logins and stats), ANON, TRACE, CTRL (control/discovery), MULTI, RAW.

---

## 17. Console

The **Console** page runs any command, exactly like the USB serial console. ↑ and ↓ recall previous commands.

Other ways to reach the same command line:

- **USB serial**: 115200 baud, commands end with Enter.
- **Telnet**: `telnet <device IP>`, then the admin password.
- **Over the mesh**: log in as admin to the repeater from the MeshCore app or meshcore-open and use its command-line screen.

---

## 18. Firmware updates

### 18.1 From the internet (on the device)

**Firmware & maintenance → Update from the internet**

- **Check for updates** compares this build with the latest published build.
- **Install latest** downloads the build for this exact board and firmware type over verified HTTPS, installs it and reboots. Identity and settings are kept.
- **Automatic**: *Off*, *Check daily and show on dashboard* (default), or *Install updates automatically*, with a custom interval in hours.

Commands: `update check`, `update install`, `get update.status`, `set update.auto off|check|install`, `set update.interval <hours>`, `set update.url <https://…/>`, `get build`.

### Automatic rollback

Every update method that goes through the device (internet update, file upload, legacy OTA hotspot) writes the new firmware to the **spare slot** and keeps the old one.

- After an update, the new firmware must run healthily for **60 seconds** before it is confirmed.
- If it crashes, reboots or can't start the radio before then, the device automatically goes back to the **previous firmware**.
- `get ota.state` shows which slot is running, its state (`pending-verify` / `valid`) and what's in the other slot.
- `ota rollback` switches back to the previous firmware on purpose.

Firmware flashed over USB replaces the running slot directly, so rollback only applies to on-device updates.

### 18.2 From a file (in the browser)

Choose the **non-merged** `.bin` for your board and firmware type and press **Upload & install**. The device checks that it is a valid ESP32-S3 app image before writing it. Merged/full-flash files are rejected, and file names that look like the wrong board or type trigger a warning.

### 18.3 USB web flasher

See [§3.1](#31-web-flasher-easiest).

### 18.4 Legacy OTA hotspot

`start ota` opens a `MeshCore-OTA` hotspot with an upload page at `http://192.168.4.1/update`, as on standard MeshCore.

---

## 19. Backup, restore and factory reset

- **Backup** downloads a JSON file with every readable setting, the region tree and saved WiFi network names. WiFi, MQTT and admin passwords are never included. Tick **Include private key** to be able to restore the same identity.
- **Restore** shows every command before applying it. Regions are listed for you to re-enter on the Regions page.
- **Re-run setup wizard**: `setup start`.
- **Factory reset** erases the identity, all settings, WiFi and regions. On the Firmware page type `ERASE` to confirm, or send `factory reset confirm`.

---

## 20. Using apps and other tools

| Tool | How it connects to a UMC repeater |
|---|---|
| **Official MeshCore app**, **meshcore-open** | Connect to your own client radio, then log in to the repeater over the mesh with its admin password. Status, settings and command line all work. |
| **config.meshcore.io**, **meshcore-cli** | USB serial |
| **Telnet / PuTTY** | `telnet <IP>` |
| **Web browser** | `http://<IP>/` or `http://umc-<name>.local/` |
| **MQTT maps / analysers** | Via the MQTT settings |
| **Official MeshCore app**, **meshcore-open** over WiFi | Add a TCP / WiFi device with the repeater's IP and port **5000**. See below. |
| **meshcore_py**, **meshcore-cli**, **Home Assistant (meshcore-ha)** | TCP to the repeater's IP, port 5000 |
| Direct app connection over Bluetooth | *(coming soon)* |

### Connecting an app over WiFi (port 5000)

1. Make sure the phone/computer is on the same network as the repeater, and **App connection (TCP port 5000)** is on (**Network → Services**, or `set app.tcp on`).
2. In the app, add a **TCP / WiFi** connection: host = the repeater's IP (shown on the display or `get wifi.status`), port = **5000**.
3. The app connects and shows one contact: **“<repeater name> (console)”**.
4. Open that contact and **log in** with the admin password (or the guest password for read-only status).
5. The app's usual repeater screens now work directly over WiFi: **status**, **telemetry**, **neighbours**, **command line** and settings.

Notes:
- A repeater has no chat identity, contacts or channels, so messaging and channels aren't available through it. Use client (companion) firmware for that.
- Up to 3 apps can be connected at once. Changing settings requires the admin login on that connection.
- `get app.status` shows whether it's on and how many apps are connected.

---

## 21. Security

- **Change the admin password** from `password`. The web page and telnet refuse to sign you in until you do.
- The first-time **setup hotspot is open**. Anyone in range can configure a device that is in setup mode, so finish setup promptly.
- The rescue hotspot is protected by the device PIN or `ap.password`.
- The web page and telnet use **plain HTTP/telnet on your local network**. Don't forward them to the internet.
- Sign-in locks for 1 minute after 5 wrong passwords.
- Keep the **private key** secret. Backups only include it if you tick the box.
- Internet updates are downloaded only over HTTPS, verified against trusted certificate authorities.

---

## 22. Troubleshooting

| Problem | Fix |
|---|---|
| **Web page shows “Device not reachable”** | The device rebooted or moved from the hotspot to your home WiFi. Put your phone/computer on the same network and open the address shown on the display. |
| **Can't find the setup hotspot** | Setup is already done. Use the home-network address, or run `setup start` over USB. |
| **`.local` name doesn't open** | Some Android phones and older Windows don't support mDNS. Use the IP address from the display or `get wifi.status`. |
| **Sign-in refused: default password** | Set a new admin password over USB: `password <new>`. |
| **Repeater hears nothing** | Check the antenna. Try `set agc.reset.interval 4`. Confirm the radio preset matches your mesh. |
| **Clock wrong after power cut** | Normal on the V3 (no clock battery). It fixes itself on WiFi, or press **Set clock from this browser**. |
| **Region traffic not matching others** | Names are case-sensitive: check spelling and capitals with neighbouring repeater owners. |
| **“Location only allowed from secure origins”** | Browsers block GPS on plain HTTP pages. Use **Set location from map…** and paste coordinates. |
| **Update check says “HTTP 404” / “can't reach update server”** | The device needs internet access. Check `get update.url`. |
| **ESP-NOW bridge not linking** | Both ends need the same channel and secret, and the channel must match the WiFi channel. |
| **USB flasher can't see the device** | Use Chrome/Edge, a data cable, install the CP210x driver, and enter boot mode (hold PRG, tap RST). |

---

## 23. Command reference A–Z

Replies start with `>` for values, `OK` for success, or `Err`/`Error` for problems. *R* = repeater/room server.

| Command | Description |
|---|---|
| `advert` | Send a flood advert now |
| `advert.zerohop` | Send a zero-hop advert now |
| `board` | Board name |
| `clear stats` | Reset statistics |
| `clkreboot` | Reset clock and reboot |
| `clock` | Show UTC time |
| `clock sync` | Set clock from the remote admin's app (over the mesh) |
| `discover.neighbors` | Ask nearby repeaters to respond *(R)* |
| `erase` | Format the file system (USB only) |
| `factory reset confirm` | Erase identity and all settings, then reboot |
| `get acl` | Print access list (USB) *(R)* |
| `get/set adc.multiplier <n>` | Battery reading calibration |
| `get/set advert.interval <min>` | Zero-hop advert interval (0, 60–240) *(R)* |
| `get/set agc.reset.interval <s>` | AGC reset (0 = off, multiples of 4) |
| `get/set allow.read.only on\|off` | Room server read-only logins |
| `get/set ap.mode auto\|on\|off` | Hotspot mode |
| `get/set ap.password <pw>\|pin` | Rescue/always-on hotspot password |
| `get/set ap.rescue <s>` | Seconds offline before the rescue hotspot starts (15–3600) |
| `get ap.status` | Hotspot state and clients |
| `get/set ble on\|off`, `ble.idle <min>` | Bluetooth *(coming soon)* |
| `get/set bridge.channel <1-14>` | ESP-NOW channel |
| `get/set bridge.delay <ms>` | Bridge delay |
| `get/set bridge.enabled on\|off` | Bridge on/off |
| `get/set bridge.source logTx\|logRx` | Which packets to bridge |
| `get/set bridge.secret <text>` | ESP-NOW secret |
| `get bridge.type` | Bridge type in this build |
| `get build` | UMC version, build target and commit |
| `get/set cad on\|off` | Channel activity detection |
| `get/set direct.txdelay <0-2>` | Direct retransmit delay factor *(R)* |
| `get/set display.ip <s>` | Flashing network screen time |
| `get/set display.mode cycle\|status\|off` | Display mode |
| `get/set display.page <s>` | Time per settings screen |
| `get/set display.timeout <s>` | Blank after (0 = never) |
| `get/set display.traffic <s>` | Live traffic screen time |
| `get/set dutycycle <%>` | Transmit duty cycle limit |
| `get/set flood.advert.interval <h>` | Flood advert interval (0, 3–168) *(R)* |
| `get/set flood.max <n>` | Max flood hops *(R)* |
| `get/set flood.max.advert <n>` / `advert.hops.max` | Max hops for flooded adverts *(R)* |
| `get/set group.hops.max <n>` | Max hops for channel messages *(R)* |
| `get/set flood.max.unscoped <n>` | Max hops for unscoped floods *(R)* |
| `get/set freq <MHz>` | Frequency only (prefer `set radio`) |
| `get/set guest.password <pw>` | Guest password *(R)* |
| `gps [on\|off\|sync\|setloc]`, `gps advert none\|share\|prefs` | GPS control |
| `get/set http on\|off` | Web interface |
| `get/set http.timeout <min>` | Web session timeout |
| `get/set int.thresh <n>` | Interference threshold |
| `get/set lat <deg>`, `lon <deg>` | Location |
| `log`, `log start\|stop\|erase` | Packet log |
| `get/set loop.detect off\|minimal\|moderate\|strict` | Loop detection *(R)* |
| `memory` | Heap / PSRAM usage (JSON) |
| `get/set mqtt.custom on\|off`, `.host`, `.port`, `.transport tcp\|wss`, `.username`, `.password` | Custom MQTT broker |
| `get/set mqtt.eastmesh-au\|meshmapper\|waev\|letsmesh-eu\|letsmesh-us on\|off` | Preset MQTT brokers |
| `get/set mqtt.email <addr>`, `mqtt.owner <hex>` | MQTT identity |
| `get/set mqtt.iata <code>` | MQTT location code (`UNSET` = idle) |
| `get/set mqtt.packets\|raw\|tx\|status on\|off` | What MQTT publishes |
| `get mqtt.status`, `mqtt.client_version` | MQTT state |
| `get/set multi.acks 0\|1` | Extra ACKs |
| `get/set name <name>` | Node name |
| `neighbor.remove <prefix>` | Forget a neighbour *(R)* |
| `neighbors` | List neighbours *(R)* |
| `get/set net.hostname <name>` | Network hostname (blank = automatic) |
| `get/set net.ip dhcp\|<ip> <mask> <gw> [dns]` | IP configuration |
| `get/set net.mdns on\|off` | `.local` name |
| `get net.status` | Network summary (JSON) |
| `get/set ntp.server1\|2\|3 <host>` | Time servers |
| `get/set owner.info <text>` | Owner information *(R)* |
| `password <new>` | Change admin password |
| `get/set path.hash.mode 0\|1\|2` | Advert ID size *(R)* |
| `get/set pin <8 digits>` | Device PIN (rescue hotspot password) |
| `poweroff` / `shutdown` | Power off |
| `powersaving [on\|off]` | Sleep between packets *(R)* |
| `get/set prv.key <hex>` | Private key |
| `get public.key` | Public key |
| `get pwrmgt.bootmv\|bootreason\|source\|support` | Power management info |
| `get/set radio <MHz>,<kHz>,<SF>,<CR>` | Radio parameters (applied immediately) |
| `get/set radio.rxgain on\|off` | RX boosted gain |
| `reboot` | Restart |
| `route <node>`, `route find\|pin\|unpin\|forget …` | Learned and pinned routes |
| `routes` | Route table summary |
| `region` | Show region tree |
| `region allowf\|denyf <name>` | Allow/deny flooding for a region |
| `region def <tokens>` | Define a region hierarchy in one line |
| `region default [name]` | Default scope region |
| `region home [name]` | Home region |
| `region list allowed\|denied` | List regions (USB) |
| `region load` | Interactive bulk load (USB) |
| `region preset yorkshire\|northwest\|uk` | Add UK region presets |
| `region put <name> [parent]` | Create a region |
| `region remove <name>` | Remove a region (no sub-regions) |
| `region save` | Save region changes |
| `get/set repeat on\|off` | Repeat packets *(R)* |
| `get role` | Firmware role |
| `get/set rxdelay <0-20>` | RX delay base *(R)* |
| `sensor list\|get\|set` | Sensors (if fitted) |
| `get setup`, `setup start`, `setup done` | Setup mode |
| `setperm <pubkey> [0-3]` | Access permissions *(R)* |
| `start ota` | Legacy OTA hotspot |
| `stats-core`, `stats-radio`, `stats-packets` | Statistics (JSON) |
| `get/set telnet on\|off` | Telnet command line |
| `get/set app.tcp on\|off`, `get app.status` | MeshCore app connection on TCP port 5000 |
| `tempradio <MHz>,<kHz>,<SF>,<CR>,<min>` | Temporary radio settings |
| `time <epoch>` | Set clock |
| `trace <a1,b2,…>`, `trace route <node>`, `get trace` | Trace a path and read the per-hop SNR |
| `get/set timezone <POSIX TZ>` | Display time zone |
| `get traffic` | Recent packets |
| `get/set tx <dBm>` | TX power |
| `get/set txdelay <0-2>` | Flood retransmit delay factor *(R)* |
| `get umc.version` | Ultimate MeshCore version |
| `update check`, `update install`, `get update.status` | Internet firmware update |
| `get ota.state`, `ota rollback` | Firmware slots and manual rollback |
| `get/set update.auto off\|check\|install`, `update.interval <h>`, `update.url <https>` | Update settings |
| `ver` | MeshCore base version (used by apps) |
| `get/set web on\|off`, `web.stats on\|off`, `get web.status` | Classic HTTPS panel |
| `get/set wifi.enabled on\|off` | WiFi radio |
| `get wifi.networks` | Saved network names |
| `get/set wifi.powersaving none\|min\|max` | WiFi power saving |
| `set wifi.pwd[2\|3] <pw>` / `get wifi.pwd[2\|3]` | WiFi passwords (get shows only “set”) |
| `wifi clear <1-3>` | Forget a saved network |
| `wifi reconnect` | Rejoin WiFi |
| `wifi scan`, `get wifi.scan` | Scan networks |
| `get/set wifi.ssid[2\|3] <name>` | WiFi network names |
| `get wifi.status` | WiFi connection details |

---

## 24. Glossary A–Z

- **ACK** — acknowledgement that a message arrived.
- **Admin password** — password for full control of a repeater: web, telnet and remote admin.
- **Advert** — a packet announcing a node's name, key and optional location. *Zero-hop* adverts reach direct neighbours; *flood* adverts cross the mesh.
- **AGC** — automatic gain control in the radio receiver.
- **AP / hotspot** — the WiFi network the device itself creates.
- **Bandwidth (BW)** — width of the radio channel. Narrower goes further but is slower.
- **Bridge** — joins two LoRa areas through another link (ESP-NOW, RS-232, MQTT).
- **CAD** — channel activity detection: listening for LoRa before transmitting.
- **Coding rate (CR)** — error-correction overhead (4/5 … 4/8). Nodes with different CRs can still talk.
- **Companion / client** — a personal radio used with a phone or desktop app.
- **Direct routing** — a packet follows a known path instead of flooding.
- **Duty cycle** — share of time spent transmitting. Legally limited in some bands.
- **ESP-NOW** — Espressif's direct 2.4 GHz link between ESP32 devices.
- **Flood** — a packet repeated by every repeater until its hop limit.
- **Guest** — limited login that can view basic information.
- **Hop** — one repeater relaying a packet.
- **IATA code** — three-letter airport code used as an MQTT location tag.
- **Identity / public key / private key** — cryptographic keys that identify a node. The private key must stay secret.
- **LoRa** — the long-range, low-power radio technology MeshCore uses.
- **mDNS / .local** — finding a device by name (`umc-<name>.local`) on a local network.
- **MeshCore** — the open-source mesh networking firmware and protocol UMC is built on.
- **MQTT** — a lightweight messaging protocol used to upload mesh data to maps and analysers.
- **Neighbour** — a repeater heard directly, without hops.
- **Noise floor** — background radio noise level (lower is better, e.g. −105 dBm).
- **OTA** — over-the-air firmware update.
- **PIN** — 8-digit device code: rescue hotspot password (and future Bluetooth pairing).
- **Preset** — a named set of radio parameters shared by a regional mesh.
- **Region** — a named area used to scope flood traffic. Names are case-sensitive.
- **Repeater** — a node that relays packets to extend coverage.
- **Rescue hotspot** — hotspot that appears when the device can't reach any saved WiFi.
- **Room server** — a node hosting a shared message board.
- **RSSI** — received signal strength (dBm, closer to 0 is stronger).
- **SNR** — signal-to-noise ratio (dB, higher is better. LoRa works below 0).
- **Spreading factor (SF)** — how much each symbol is spread (5–12). Higher goes further but is slower.
- **Telnet** — plain-text remote command line.
- **TX power** — transmit power in dBm.
- **UMC** — Ultimate MeshCore.
- **UTC** — Coordinated Universal Time. The mesh clock always uses UTC.
- **Zero-hop** — reaches direct neighbours only; not repeated.
