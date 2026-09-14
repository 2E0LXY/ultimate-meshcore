# Heltec V3.2 "all-in-one" MeshCore repeater — feature inventory & merge plan

Target: Heltec WiFi LoRa 32 V3.2 (ESP32-S3, 8 MB flash, **no PSRAM**, SX1262, SSD1306 OLED)
Build base: `eastmesh/main` (upstream 1.17.1 + 266 commits, only 2 behind upstream main) → branch `v3-allinone`

## Sources and what each contributes

| # | Source | Kind | Usable code? | Contribution |
|---|---|---|---|---|
| 1 | meshcore-dev/MeshCore | upstream C++ | yes (base) | Repeater, room server, companion, OTA (`start ota`), ESP-NOW + RS232 bridge, KISS modem, regions, path hash mode |
| 2 | agessaman/MeshCore (mqtt-bridge-implementation, observer-firmware, feat/abstract-networking) | fork C++ | yes | MQTT observer (multi-slot presets, JWT, WSS), SNMP agent, radio watchdog, fault alerts (WiFi/MQTT down → mesh alert), timezone, heap monitoring, Ethernet-preferred networking abstraction, web OTA server |
| 3 | dt267/MeshCore-Low-Power-Firmware | **binaries + docs only** (MIT) | no source | Re-implement from docs: `rx.duty`, `advert.hops.max`, `group.hops.max`, `set radio` w/o reboot, `tempradio`, `radio.rxgain`, `bridge.tx/delay/source/enabled/peer`, `adc.multiplier`, `poweroff`, SX1262 register r/w, config portal w/ backup/restore, GPS tuning |
| 4 | openhop-dev/openHop-Modem-Flasher (+ openhop_modem) | browser flasher + host-driven modem fw | different architecture | Not a repeater (mesh logic runs on a host). Ideas: USB/TCP raw-modem transport, AP provisioning portal. MeshCore already has `kiss_modem` role |
| 5 | redengin/meshcore-firmware | Rust, 37 files, early | no (different language) | Concept only: WiFi LAN binding, extended per-node config, distributed room servers |
| 6 | OffbandMesh/meshcore-firmware | fork C++ | yes | SafeBoot (low-battery boot guard, V3.2 ADC polarity autodetect), safety/crash log, caplog + UDP syslog forward, MQTT command channel (ota_enable, reboot, wifi_keepalive), burst-WiFi telemetry, OTA over STA, NimBLE |
| 7 | samuk/awesome-meshcore | link list | n/a | Index (pyMC_Repeater, ZephCore, RemoteTerm, UK maps: meshrank.net, ukmesh.com, map.meshradio.uk) |
| 8 | ALLFATHER-BV/meshcomod | fork C++ | yes | Repeater TCP (5000) + WebSocket (8765) companion-protocol server → control repeater from app over LAN; `set wifi.apply/clear/radio`; `ota url <https>` pull-OTA; OLED network pages |
| 9 | marcelverdult/meshcore-nightly | CI workflow | n/a | Nightly build pipeline pattern |
| 10 | xJARiD/MeshCore-EastMesh | fork C++ | yes (base) | WiFi CLI + watchdog + `wifi reconnect`, NTP servers, MQTT uplink (2 slots, custom TCP/WSS), HTTPS web panel `/app` + `/stats`, ghost-node mode, ESP-NOW bridge, peer MQTT bridge, `memory`/`stats-*`, `flood.max.unscoped/advert`, OTA over LAN |
| 11 | dabeani/meshcoreterm | **binaries + docs only** | no source | T-Deck/SenseCAP touch UI — not applicable to a headless V3 repeater |
| 12 | Mraanderson/meshcore-ota | docs | n/a | OTA procedure (non-merged .bin) |
| 13 | meshcore.co.uk user guide | docs | n/a | UK: EU/UK Narrow preset, odd flood advert interval (e.g. 51 h), admin pw ≥8 chars, guest pw, agc reset, `time` sync |
| 14 | jmead/Meshcore-Repeater-MQTT-Gateway | standalone beta C++ | partially | Bidirectional MQTT (MQTT → mesh messages), `commands/#` subscription, ISO-coded topic prefix (MESHCORE/GB/…), custom CA upload, TLS 8883 |
| 15 | LitBomb/MeshCore-FAQ | docs | n/a | `agc.reset.interval 4` for deafness; path.hash.mode 1/2 safe; stock repeaters have no BLE; V3 coil antenna → short BT/WiFi range |
| 16 | jooray/MeshCore-BitChat (feature/bitchat-bridge) | fork C++ (companion only, 27 commits on 1.17.0) | yes | BitChat app ↔ MeshCore `#mesh` channel bridge over BLE (BitchatBLEService, BitchatProtocol, miniz long msgs). Port to repeater as a BLE-mode option (repeater must hold the `#mesh` hashtag channel key) |
| 17 | eliahreeves/mesh-loader | loader + patch set (V3, V4) | packaging only | Dual-boot MeshCore/Meshtastic via OTA slots + 2 s button loader. **Conflicts** with OTA rollback/SafeBoot and with identity-preserving app-only updates (needs its own partition table, full 0x0 flash). Offer as a separate optional package, not merged into the repeater image |
| 18 | meshcore-dev/meshcore_py (v2.3.10) | Python client library | tooling | Serial/BLE/TCP companion-protocol client → use to test the repeater's TCP/WS/BLE servers from the PC |

## Hard constraints (V3.2)
- No PSRAM: TLS (~40 KB internal heap per session) + HTTPS panel + BLE (NimBLE ~60–90 KB) cannot all be live at once reliably. → All compiled in, **runtime-selectable**; USB always on.
- No Ethernet PHY on V3. "LAN" = WiFi LAN (TCP/WS/HTTPS/SNMP/syslog). W5500 SPI add-on only via agessaman abstract-networking (optional, off).
- 8 MB flash: fine; partition table must keep SPIFFS at the same place for app-only update that preserves identity/prefs.

## Merge order
1. Baseline: build `Heltec_v3_repeater_observer` from EastMesh (verify toolchain).
2. Port meshcomod repeater TCP/WS companion server (LAN app control).
3. Add BLE transport for repeater (new work; companion-protocol subset shared with #2), mutually exclusive with WiFi at runtime.
4. Port Offband SafeBoot + safety log + syslog forward.
5. Port agessaman SNMP, radio watchdog, fault alerts, timezone.
6. Re-implement Low-Power repeater CLI features (rx.duty, hop caps, bridge.tx/delay/source, radio w/o reboot, poweroff, backup/restore).
7. MQTT inbound commands (Offband cmd channel + jmead bidirectional), UK defaults (NTP uk.pool.ntp.org, EU/UK Narrow, UK broker presets).
8. Build, size/heap check, docs (`CLI.md`), then flash (app-only, preserves identity) — **only with user confirmation**.
