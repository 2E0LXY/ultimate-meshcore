# Ultimate MeshCore (UMC) — firmware specification v0.1

Working name: **Ultimate MeshCore** · short tag **UMC** · env prefix `umc_` · version `umc-<upstream>-<n>` (e.g. `umc-1.17.1-1`).
(GitHub search 2026-09-14: "Ultimate MeshCore" / "MeshCore Ultimate" unused. "UltiCore" has minor collisions.)
Base: MeshCore 1.17.1 via EastMesh `main`, plus merged features from all sources in PLAN.md.

---

## 1. Device × role matrix

| Board | MCU / Flash / PSRAM | Display | Repeater env | Client (companion) env |
|---|---|---|---|---|
| Heltec V3 / V3.2 | ESP32-S3, 8 MB, none | SSD1306 OLED | `umc_heltec_v3_repeater` | `umc_heltec_v3_companion` |
| Heltec V4 OLED | ESP32-S3, 16 MB, 2 MB | SSD1306 OLED | `umc_heltec_v4_oled_repeater` | `umc_heltec_v4_oled_companion` |
| Heltec V4 TFT | ESP32-S3, 16 MB, 2 MB | ST7789 TFT + touch | `umc_heltec_v4_tft_repeater` | `umc_heltec_v4_tft_companion` |
| Heltec V4 R8 (OLED / TFT) | ESP32-S3, 16 MB, 8 MB | OLED or TFT | `umc_heltec_v4_r8_{oled,tft}_repeater` | `umc_heltec_v4_r8_{oled,tft}_companion` |
| LilyGo T-TWR Plus + SX1262 add-on | ESP32-S3R8, 16 MB, 8 MB | SH1106 OLED, PMU, GPS | `umc_ttwr_sx1262_repeater` | `umc_ttwr_sx1262_companion` |

T-TWR note: the stock board has only an SA868 FM module — **no LoRa**. UMC adds a new variant for an external SX1262 module (e.g. Ebyte E22-900M22S, Seeed Wio-SX1262) on the expansion header; pin map to be fixed once the module + wiring is chosen. SA868 stays unused (optionally: APRS/voice later, out of scope).

Each env produces `*-merged.bin` (first install at 0x0) and `*.bin` (app-only update at 0x10000 / OTA). Identical partition layout within a board family so app-only updates keep identity and settings.

---

## 2. App & tool compatibility (contract — must not break)

| Client | Transport | What UMC must provide |
|---|---|---|
| Official MeshCore app (Android/iOS/desktop/web) | BLE, USB, WiFi TCP | Companion protocol; BLE NUS UUID `6e400001-b5a3-f393-e0a9-e50e24dcca9e`; BLE name prefix **`MeshCore-`**; TCP port **5000** |
| meshcore-open (Flutter, MIT) | BLE, USB, TCP (web via WS bridge) | Same as above + **WebSocket** companion server (port 8765) so the web build works without a bridge |
| app.meshcore.io web app, HopRadar | Web Serial, Web BLE | Unchanged USB/BLE companion protocol |
| config.meshcore.io, meshcore-cli, MeshFirmware | USB serial CLI | Upstream CLI names **and reply format** (`> value`, `OK`, `Error: …`) unchanged |
| Repeater admin in any app (login over LoRa) | LoRa via a companion | Upstream remote-admin + CLI-over-mesh unchanged; new commands follow the same `get/set` pattern |
| meshcore_py, meshcore-ha, RemoteTerm, MeshMonitor, bots, MC-WebUI | Serial / BLE / TCP | Companion protocol over TCP 5000 on the network |
| Meshcomod web client | TCP / WS | meshcomod repeater subset (device query, stats, CLI via `MESHCM` contact) |
| LetsMesh analyzer, MeshMapper, UK Mesh Network, meshrank, CoreScope, MQTT live map | MQTT | agessaman/EastMesh observer topic format `meshcore/<IATA>/<device>/{packets,raw,status}` + JWT/WSS |
| BitChat app | BLE | BitChat BLE service (companion; repeater optional in BLE mode) |
| Home Assistant | MQTT | HA discovery topics (new) + meshcore-ha via TCP |
| SNMP tools / syslog / Grafana | UDP | SNMP agent (agessaman), UDP syslog (Offband) |

Explicitly **not** compatible (different technology): blxble/mesh-core-on-android (Bluetooth SIG mesh stack, unrelated to LoRa MeshCore).

---

## 3. Network access (WiFi) — repeater and client

### 3.1 Connectivity
- STA with up to **3 saved networks** (priority order), DHCP or static IP, hostname + **mDNS** `umc-<name>.local`.
- **Provisioning / rescue AP** `UMC-<4hex>` when no network is reachable for 60 s (WPA2, password = device PIN padded to 8 digits; PIN shown on display or set via `set pin`). Captive portal redirects to the web UI.
- Gateway watchdog + auto-reconnect with back-off (EastMesh), `wifi reconnect`, `wifi scan`.
- Modes: `always` · `burst` (connect every N min to publish, solar) · `off`. Schedule window optional.
- WiFi TX power and power-save levels; ESP-NOW bridge channel auto-follows STA channel.
- Bluetooth/WiFi coexistence policy per board: V4/R8/T-TWR run both; V3 runs both for plain TCP/BLE, but TLS services (HTTPS/WSS MQTT) are budgeted by a heap governor that defers/sheds lowest-priority service.

### 3.2 Web UI (served from flash, gzip, works offline — no CDN)
Login with admin password (repeater) or portal password/PIN (client); session token; rate-limited, lockout after 5 failures; HTTP on port 80, optional HTTPS (self-signed) on 443 (default on for PSRAM boards, opt-in on V3).

Pages:
1. **Dashboard** — name, role, version, uptime, battery, clock, noise floor, RSSI/SNR, airtime/duty-cycle use, packet counters, WiFi/MQTT/BLE status, heap.
2. **Radio** — preset picker (EU/UK Narrow etc.), freq/bw/sf/cr, tx power (board-limited), rxgain, agc reset, CAD, int.thresh, duty cycle (region-aware warning), `tempradio`.
3. **Routing & mesh** — repeat, flood.max / unscoped / advert / group hop caps, loop.detect, txdelay/direct/rxdelay, multi.acks, path.hash.mode, advert intervals, ghost-node mode.
4. **Regions** — tree editor (put/def/allowf/denyf/home/default) + UK presets.
5. **Identity & access** — name, lat/lon (with privacy rounding), owner info, admin/guest password, ACL table, public key, private key export/import (confirm dialog).
6. **Network** — WiFi networks, static IP, mDNS, AP settings, NTP servers, timezone, services on/off (web, telnet, TCP 5000, WS 8765, SNMP, syslog).
7. **MQTT** — observer presets (LetsMesh EU, MeshMapper, UK Mesh Network, meshrank, custom ×N), IATA/region code, packets/raw/tx/status toggles, owner/email JWT, command channel secret, HA discovery.
8. **Bridges** — ESP-NOW (channel, secret, tx, delay, source), RS232, peer MQTT bridge, BitChat.
9. **Neighbours & live log** — neighbour table (SNR, age), live packet log via WebSocket, `discover.neighbors`, remove.
10. **Stats** — trend graphs (battery, noise, airtime, packets, heap), longer history on PSRAM boards.
11. **Console** — full CLI terminal (same parser as serial).
12. **Firmware** — current version, **upload .bin** (dual-slot OTA with automatic rollback), **update from URL** / check GitHub releases, safety/crash log, reboot, power-off.
13. **Backup / restore** — JSON export/import of all settings (secrets excluded unless ticked), factory reset.
14. **Client only** — BLE pairing PIN, display settings, GPS, contacts/channels count, message persistence.

### 3.3 Other network services
- **Telnet CLI** port 23 (same as upstream Ethernet CLI), password-gated.
- **Companion TCP** 5000 + **WebSocket** 8765 (client: full protocol; repeater: meshcomod subset + CLI).
- **REST API** `/api/v1/*` (JSON get/set of every setting, stats, cli) — documented for scripts/HA.
- **MQTT** observer (multi-slot, TLS/WSS/JWT), command channel (reboot, ota_enable, wifi_keepalive, cli), fault alerts to mesh.
- **SNMP** agent, **UDP syslog** forward (caplog), **NTP** client.
- **OTA**: web upload, URL pull (`ota url`), MQTT `ota_enable`, classic `start ota` AP — all write the inactive slot, rollback on boot failure.

---

## 3A. First-time setup (both roles, all boards)

On first boot (or after factory reset, or 5 × button press) the device enters **Setup mode** and offers **both** paths at once; the display shows the SSID, PIN, IP and BLE name.

**Path 1 — WiFi AP + web wizard**
1. Device starts AP `UMC-Setup-<4hex>` (WPA2, password = 8-digit PIN on the display; headless boards: printed on serial + default documented PIN that must be changed in step 2).
2. Captive portal opens the **Setup Wizard** (`http://192.168.4.1`, also `http://umc.local`):
   1. Language / region preset (UK default) → radio preset, duty cycle, timezone
   2. Role confirmation + node name + optional location (with privacy rounding)
   3. **Admin password** (required, ≥ 8 chars) + guest password (repeater) / BLE PIN (client)
   4. Home WiFi (scan list, up to 3 networks, or "stay AP-only")
   5. Services: web/HTTPS, TCP/WS app access, telnet, MQTT observer preset + IATA, BLE on/off
   6. Clock: auto from the phone/browser time (one tap) or NTP once on WiFi
   7. Review → Save → reboot into normal mode; wizard shows the new LAN URL / mDNS name
3. After setup the full web UI (§3.2) is available on the home network; the AP only returns as a rescue AP.

**Path 2 — Bluetooth + app**
- Device advertises BLE as `MeshCore-UMC-<name>` (keeps the `MeshCore-` prefix so the Official app and meshcore-open discover it) with the standard NUS service.
- **Client firmware:** full companion protocol → Official app / meshcore-open do everything (radio, name, channels, contacts) natively; UMC-specific settings (WiFi, MQTT, services) via the app's CLI screen or the UMC web app.
- **Repeater firmware:** BLE exposes the companion-protocol **repeater subset** (device info, stats, time sync, name, radio, tx, advert) so apps can connect directly, plus the full text CLI over the same link (meshcomod `MESHCM` contact / `TXT_TYPE_CLI_DATA`) → every setting reachable from the app's CLI screen.
- **UMC Config web app** (static PWA, hosted on GitHub Pages and bundled in firmware): Web Bluetooth + Web Serial, renders the same forms as the device web UI by driving the CLI — works on Android Chrome and desktop Chrome/Edge without WiFi.
- BLE pairing PIN required for setup commands; after setup BLE can stay on (client default), auto-off after N minutes idle (repeater default), or be disabled.

**Rescue**: if WiFi fails for 60 s the rescue AP returns; hold button 8 s at boot → serial rescue CLI; USB serial CLI is always available.

---

## 4. Complete settings catalogue (CLI = source of truth; web/REST/app map 1:1)

Legend: **U** upstream 1.17.1 · **E** EastMesh · **A** agessaman · **O** Offband · **M** meshcomod · **L** Low-Power (re-implemented) · **N** new in UMC. R = repeater, C = client.

### Operational
`reboot` U · `poweroff`/`shutdown` U · `clkreboot` U · `clock` / `clock sync` / `time <epoch>` U · `advert` / `advert.zerohop` U · `start ota` U · `ota url <https>` M · `erase` U · `factory reset` N · `backup` / `restore` L/N · `ver` U · `version` (upstream+UMC) O · `board` U · `help` L

### Diagnostics
`stats-core` / `stats-radio` / `stats-packets` / `clear stats` U · `memory` E · `neighbors` / `neighbor.remove` / `discover.neighbors` U · `log start|stop|erase` / `log` U · `safety log [N]|tail|clear` / `safety partitions|state` O · `caplog start <lvl>` / `caplog forward <s>|off` O · `get agc.resets` / `clear agc.resets` L · `radio watchdog` A · `get pwrmgt.*` U

### Radio
`get/set radio f,bw,sf,cr` U (no reboot needed — L) · `tempradio …,mins` U · `get/set freq` U · `get/set tx` U · `get/set radio.rxgain` U/L · `get/set radio.fem.rxgain|txgain` U · `get/set rx.duty` L · `get/set cad` U · `get/set int.thresh` U · `get/set agc.reset.interval` U · `get/set dutycycle` U (`af` deprecated) · `radio reg <addr> [val]` L · `get/set region.preset` N (EU/UK Narrow…)

### System / identity
`get/set name` U · `get/set lat|lon` U · `get/set owner.info` U · `password <pw>` U · `get/set guest.password` U · `get public.key` U · `get/set prv.key` U · `get role` U · `get/set adc.multiplier` U/L · `powersaving on|off` U · `get/set pin` E (client/AP) · `get/set timezone` A · `get/set display.*` N

### Routing
`get/set repeat` U · `get/set path.hash.mode` U · `get/set loop.detect` U · `get/set txdelay|direct.txdelay|rxdelay` U · `get/set multi.acks` U · `get/set advert.interval` U · `get/set flood.advert.interval` U · `get/set flood.max|flood.max.unscoped|flood.max.advert` U/E · `get/set group.hops.max` L · `ghost on|off` E/N

### ACL & regions
`setperm` / `get acl` U · `get/set allow.read.only` U · `region load|save|allowf|denyf|get|home|default|put|def|remove|list` U

### GPS / sensors
`gps [on|off|sync|setloc|advert]` U · `get/set gps.interval|gps.minsat|gps.hdop|gps.mode` L · `sensor list|get|set` U

### Bridges
`get bridge.type` U · `get/set bridge.enabled|delay|source|baud|channel|secret` U · `get/set bridge.tx` L · `get bridge.peer` L · `set bridge.peer.host|port|username|password` E · `get/set bitchat on|off` N

### WiFi / network
`get/set wifi.ssid[1-3]` E/N · `set wifi.pwd[1-3]` E/N · `wifi.apply` / `wifi.clear` M · `wifi reconnect` E · `wifi scan` N · `get wifi.status` E · `get/set wifi.mode always|burst|off` O/N · `get/set wifi.powersaving` E · `get/set wifi.tx` A · `get/set net.ip dhcp|<ip>/<mask>/<gw>/<dns>` L/N · `get/set net.hostname` N · `get/set ntp.server1..3` E · `get/set ap.enabled|ap.timeout` N · `get/set web on|off` E · `get/set web.https on|off` N · `get/set web.stats on|off` E · `get/set telnet on|off` N · `get/set tcp on|off` / `ws on|off` M · `get/set ble on|off` N · `get/set snmp on|off|community` A · `get/set syslog.host|port` O

### MQTT
`get mqtt.status|client_version|client_env` E · `get/set mqtt.iata` E · `get/set mqtt.owner|email` A/E · `get/set mqtt.packets|raw|tx|status` A/E · `get/set mqtt.<preset> on|off` A/E · `get/set mqtt.custom.host|port|transport|username|password` E · `get/set mqtt.cmd on|off|secret` O/N · `get/set mqtt.ha on|off` N · `get/set mqtt.alerts on|off` A

### Power
`get/set safeboot on|off|wake|sleep` O · low-battery shutdown thresholds L · button: 5 s hold = power off (R) / force BLE (C) L

---

## 5. Defaults (UK profile, applied on first boot only)
Radio 869.618/62.5/SF8/CR8 · tx 22 (V3) / board-safe max (V4 FEM) · **dutycycle 10** · advert.interval 120 · flood.advert.interval 51 · loop.detect minimal · agc.reset.interval 4 · NTP uk.pool.ntp.org, time.cloudflare.com · timezone Europe/London · MQTT iata UNSET (brokers idle until set) · web on, https auto, telnet off, tcp/ws on (client) / off (repeater until admin password ≠ default) · admin password must be changed before network admin services start.

## 6. Security rules
- Network admin services refuse to start while admin password is the default `password`.
- Passwords never echoed back over network (show `set`), never included in backup unless explicitly selected, never in MQTT/syslog.
- Private key export only over USB serial or authenticated HTTPS with confirmation.
- OTA images verified (size, chip, board ID) before write; rollback on failed boot.
