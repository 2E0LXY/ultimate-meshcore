# Ultimate MeshCore — Roadmap and gap analysis

Last reviewed: 2026-10-22. Sources checked: upstream MeshCore `main` and `dev`, MeshCore-EastMesh, LocalMesh region configuration, agessaman/MeshCore (observer-firmware, abstract-networking, map uploader, alerts, SNMP), OffbandMesh, meshcomod, MeshCore-Low-Power (docs), MeshCore-BitChat, jmead MQTT gateway, redengin (Rust), openHop modem/flasher, mesh-loader, meshcore_py, meshcore-open, ZephCore, pyMC_Repeater, CubeCellMeshCore, awesome-meshcore, LitBomb FAQ, meshcore.co.uk guide, meshcore-regions catalogue.

✅ done · 🔜 next · 📋 planned · 💡 idea

## Done in 0.1.12

- ✅ Desktop: a Chat page for client radios with an IRC-style feed, a test-reply bot (labelled `[auto]`), optional beacons and a 24-hour dashboard, all set in forms. Ideas from MeshOmit (opensourcera, MIT). It also polls repeaters (battery, uptime, noise floor, trace SNR there and back, best neighbour) and keeps a history. Next: send direct messages from the page; rooms need firmware support for setting channels, which the companion protocol does not offer yet.
- ✅ UMC Net: a self-hosted MQTT broker (`server/umcnet`) and the repeater bridge. With `set mqtt.custom.bridge on` a repeater also listens for other repeaters' raw packets on the broker and passes them to the mesh (rate-limited, loop-safe), over the existing WSS connection. Off by default.
- ✅ Dashboard redesigned for the web interface and the Desktop app: KPI cards with trends, traffic and airtime charts, six dials, a live data-flow diagram, connections, donuts, neighbours and recent activity, in a dark-green style. History is kept in the browser (one sample a minute, 24 h).
- ✅ Android app 0.1.9: a native dashboard with the same cards, charts, dials, data flow and connections, with history kept on the phone.


## Done in 0.1.11

- ✅ LocalMesh region conventions implemented across repeater presets, Web Flasher, web/desktop client and T-Deck: exact `gb`/`gb-*` and separate `ioi` province hierarchies, strict identifiers, parent/local flooding, home selection, wildcard compatibility and 32 client scope choices
- ✅ Fixed Australian state presets to create `au-xx` beneath `au`, and reject overlong region names instead of silently truncating them
- ✅ Web Flasher multi-region picker backed by the live community GB catalogue, with a bundled snapshot refreshed automatically every week
- ✅ Restored active Let's Mesh EU/US MQTT analyzer presets and added IATA/broker setup to post-install USB provisioning

## Done in 0.1.10

- ✅ Persistent USB Web Client on the flasher page for installed repeaters and clients, with automatic bridge detection, device summary, common actions and access to every CLI function
- ✅ Reuses the open Web Client connection to complete first-boot setup; adds command history, full multi-line replies, secret redaction, disconnect handling and confirmations for disruptive commands

## Done in 0.1.9

- ✅ Web Flasher first-boot provisioning over USB: WiFi, complete radio-area preset list, region scopes, identity, passwords, location, timezone, PIN, hostname, TX and airtime limits, plus safe advanced CLI settings
- ✅ Credentials remain in browser memory, use the firmware's existing repeater/client USB bridges, and are cleared from the form after a successful setup

## Done in 0.1.8

- ✅ Republished all supported firmware targets, the USB Web Flasher, and the desktop packages with synchronized 0.1.8 version metadata

## Done in 0.1.7

- ✅ Repeater: fixed a reboot loop when Bluetooth was switched on (the Setup wizard can do it). The WiFi driver aborts if Bluetooth exists while WiFi power saving is off; Bluetooth now forces modem sleep, is created before WiFi starts, only at boot (`set ble on` takes effect after a reboot), and a start-up that crashes the board is skipped on the next boot instead of looping

## Done in 0.1.6

- ✅ Repeater: `stats-life` (lifetime boots, abnormal restarts, uptime, packets; saved every ten minutes)
- ✅ Repeater: `safety log|tail|state|clear` (every boot with its reset reason and the length of the run before it; watchdog and Bluetooth events; kept across reboots). No core dump yet
- ✅ Repeater: radio watchdog (receiver restarted when no noise burst completes for two minutes), `radio watchdog [on|off]`
- ✅ Repeater: Bluetooth on the Heltec V4 builds (`set ble on`, pairing with the last six digits of the PIN, idle auto-off, no memory used while off) — hardware test pending

## Done in 0.1.5

- ✅ Repeater: `stats-rf` (the recent spread of the noise floor, readable from the T-Deck's repeater page) and a **NOISE** page on the OLED: a trace of the last few minutes, each column from the lowest to the highest reading of a noise-floor burst, with a dot at the mean

## Done in 0.1.4

- ✅ T-Deck: chat bubbles are smaller (6pt text, tighter padding, shorter headings), so more of a conversation fits on the screen

## Done in 0.1.3

- ✅ T-Deck: tap a repeater in **Who** for its own page: **Status** (log in, then battery, uptime, noise, packet counts), **Path** (route, per-hop **trace**, set or clear the route) and **Admin** (any repeater command, quick buttons and a list of the usual ones)
- ✅ T-Deck: the **Radio** trace is auto-scaled with the driver's own low/mean/high per noise-floor burst, so small ripples show; heard packets are dots on it
- ✅ T-Deck: the newest message no longer sits behind the composer

## Done in 0.1.2

- ✅ T-Deck: smaller 7pt body font, with the Home and Radio tabs re-laid out so nothing overlaps or is cut off on the 320x240 screen

## Done in 0.1.1

- ✅ T-Deck / T-Deck Plus touch client (on hardware): Home dashboard (clock, sunrise/sunset, channel busy, tap-through cards) and Radio tab (airtime per packet, NOW / FLOOR / PEAK / MARGIN meters, live RSSI spectrum)

## Done in 0.1.0

- ✅ Routes & trace: route table from adverts, pinned routes, per-hop SNR trace
- ✅ Ultimate MeshCore Client: BLE (NimBLE) + USB + TCP 5000 + browser messenger (contacts, channels, remote admin, trace, telemetry), loop watchdog
- ✅ Ultimate MeshCore Desktop (Windows / Linux): full web interface over USB, Bluetooth, WiFi app link or the network; firmware install over USB; desktop bridge in client (CMD 112) and repeater (`@umc` on USB) firmware

- ✅ Web UI for every repeater setting, setup wizard, open setup hotspot, rescue hotspot, captive portal
- ✅ 3 WiFi networks, static IP, hostname/mDNS, scan, gateway watchdog
- ✅ Browser file OTA, internet OTA (check/install/auto), USB web flasher, CI builds + Pages + releases
- ✅ Telnet CLI, session auth, lockout
- ✅ OLED cycle (flashing IP → settings → live traffic), button paging
- ✅ Region tree editor, UK presets, `set radio` without reboot
- ✅ Backup/restore, factory reset, map location picker
- ✅ EastMesh MQTT observer, ESP-NOW bridge, classic HTTPS panel

## 1. Hardware and firmware types

| # | Item | Source | Status |
|---|---|---|---|
| 1.1 | Heltec V4 OLED / TFT / R8 repeater targets | upstream variants | ✅ builds (hardware test pending) |
| 1.2 | **Ultimate MeshCore Client** (companion) with USB + BLE + WiFi TCP (5000) + browser messenger at the same time, web UI, internet OTA | meshcomod, upstream companion, UMC | ✅ (WebSocket 8765 📋) |
| 1.3 | Room server firmware with the UMC web UI | upstream | 📋 |
| 1.4 | LilyGo T-TWR + SX1262 variant (after hardware identification) | new | 📋 |
| 1.6 | **T-Deck / T-Deck Plus touch client**: home dashboard, on-screen messenger, contacts, offline SD maps, radio meters and spectrum, GPS auto-detect | new | ✅ running on hardware |
| 1.5 | Dual-boot MeshCore/Meshtastic package (separate download) | mesh-loader | 💡 |

## 2. Upstream MeshCore `dev` (77 commits newer than our base)

| # | Item | Status |
|---|---|---|
| 2.1 | Upstream `dev` fixes: NUL-terminated command buffers (security), `set af` validation, LR2021 fixes, V4 R8 LNA, BLE flash size | ✅ cherry-picked (full `dev` merge waits for the next upstream release) |
| 2.2 | `TXT_TYPE_CLI_COMMAND`: CLI to companions over the mesh / app | 📋 (with 1.2) |
| 2.3 | Repeater "discover" screen on the display | 📋 |
| 2.4 | `loop.detect minimal` default, BMP/BME sensor probe fixes, charging indicator | 🔜 (merge) |

## 3. App connectivity

| # | Item | Source | Status |
|---|---|---|---|
| 3.1 | Repeater companion-protocol server on TCP 5000 + WebSocket 8765 (device info, stats, time, name, radio, adverts, CLI via `MESHCM` contact) so apps/meshcore_py/Home Assistant connect over LAN | meshcomod | ✅ (console contact: login, status, telemetry, neighbours, CLI) |
| 3.2 | **Bluetooth** on repeaters: NUS service advertised as `MeshCore-UMC-<name>`, same protocol subset + CLI, PIN pairing, idle auto-off | new (spec) | ✅ Heltec V4 builds (hardware test pending) |
| 3.3 | Web Bluetooth / Web Serial "UMC Config" page (no WiFi needed) | new | 📋 |
| 3.4 | BitChat `#mesh` bridge over BLE | MeshCore-BitChat | 📋 |
| 3.5 | Home Assistant MQTT discovery (sensors: battery, noise, packets, neighbours) | jmead, Offband | 📋 |

## 4. Reliability and maintenance

| # | Item | Source | Status |
|---|---|---|---|
| 4.1 | OTA rollback: mark new image valid only after a healthy run; otherwise boot the previous slot | Offband | ✅ |
| 4.2 | SafeBoot low-battery boot guard (V3.2 ADC polarity autodetect) | Offband | 📋 |
| 4.3 | Crash/safety log persisted across reboots, viewable in the web UI | Offband | ✅ CLI (`safety …`); web page and core dump 📋 |
| 4.4 | UDP syslog forwarding window (`caplog forward`) | Offband | 📋 |
| 4.5 | Persistent lifetime statistics (boots, packets, uptime) | CubeCellMeshCore | ✅ (`stats-life`) |
| 4.6 | Radio watchdog (reset radio if RX stalls) | agessaman | ✅ (`radio watchdog`) |
| 4.7 | Heap monitor + automatic recovery restart on prolonged low memory | agessaman, EastMesh | 📋 |

## 5. Mesh features

| # | Item | Source | Status |
|---|---|---|---|
| 5.1 | Per-type relay hop caps: `advert.hops.max`, `group.hops.max` | Low-Power | ✅ |
| 5.2 | RX duty cycle (sniff mode) for solar repeaters: `rx.duty` | Low-Power, ZephCore | 📋 |
| 5.3 | Adaptive contention window (dupe counting → dynamic retransmit delay) | ZephCore | 💡 |
| 5.4 | Fault alerts to a mesh channel (WiFi/MQTT down, OTA milestones): `alert.*` | agessaman | 📋 |
| 5.5 | Scheduled daily status report to admin over the mesh | CubeCellMeshCore | 💡 |
| 5.6 | Store-and-forward mailbox for offline nodes | CubeCellMeshCore | 💡 |
| 5.7 | Mesh health monitor (node offline alerts, per-node SNR EMA) | CubeCellMeshCore | 💡 |
| 5.8 | Packet policy rules in the web UI (drop by hops/type/region) | pyMC_Repeater | 💡 |
| 5.9 | Rate limiting of logins/requests/forwards | CubeCellMeshCore | 📋 |
| 5.10 | Upload repeater to map.meshcore.dev / KiekR map from the web UI | agessaman map uploader, awesome list | 📋 |
| 5.11 | Private (`$`) region keys editor | upstream | 📋 |

## 6. Web interface

| # | Item | Status |
|---|---|---|
| 6.1 | Live traffic page (packet list, filters) | ✅ |
| 6.2 | Stats history graphs (battery, noise, airtime, packets) on no-PSRAM boards | 📋 |
| 6.3 | Neighbours map (with lat/lon from adverts) | 💡 |
| 6.4 | MQTT broker presets for UK networks (ukmesh / meshrank) once endpoints are confirmed | 📋 |
| 6.5 | SNMP agent (`snmp on`, community) | 📋 |
| 6.6 | Optional HTTPS for the UMC UI on PSRAM boards | 📋 |

## 7. Out of scope / not mergeable

- MeshCoreTerm and MeshCore-Low-Power ship binaries only (features re-implemented from their docs instead).
- redengin/meshcore-firmware is a separate Rust code base (ideas only).
- openHop modem is host-driven (no on-device mesh logic).
- blxble/mesh-core-on-android is a Bluetooth SIG mesh stack, unrelated to LoRa MeshCore.
