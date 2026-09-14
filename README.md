# Ultimate MeshCore (UMC)

All-in-one MeshCore firmware for Heltec V3 / V3.2, Heltec V4 (OLED, TFT, R8) and, later, LilyGo T-TWR with an add-on SX1262 radio.
It combines upstream MeshCore with the best features of the community forks and adds a complete WiFi web interface.

> Status: **0.1.0 — early, under active development.** Heltec V3 repeater builds and runs on hardware. V4, companion (client) and T-TWR builds are in progress.

## Credits and lineage

- [MeshCore](https://github.com/meshcore-dev/MeshCore) — Scott Powell / Ripple Radios and contributors (MIT)
- [MeshCore-EastMesh](https://github.com/xJARiD/MeshCore-EastMesh) — WiFi/MQTT observer, HTTPS panel, ESP-NOW bridge (this repository's base; original README in [docs/EASTMESH_README.md](docs/EASTMESH_README.md))
- Features and ideas from agessaman/MeshCore, OffbandMesh, meshcomod, MeshCore-Low-Power, MeshCore-BitChat, jmead's MQTT gateway and others — see [docs/umc/SOURCES.md](docs/umc/SOURCES.md)

## What UMC adds (so far)

- **Web interface for every setting** (`http://<device>/` or `http://umc-<name>.local/`): dashboard, radio (with regional presets), mesh & routing, identity & passwords, regions (with UK presets), network, MQTT, bridge, power & display, neighbours, console, firmware update, backup & restore.
- **First-time setup wizard** on an open hotspot `UMC-Setup-XXXX` (no password), with captive portal. The rescue hotspot of a configured device is WPA2 (8-digit PIN on the display).
- **WiFi**: up to 3 saved networks, static IP, hostname + mDNS, automatic rescue hotspot when the home network is unreachable, network scan.
- **Firmware update over WiFi** from the browser (validates the image; rejects merged/wrong-chip files). Identity and settings are kept.
- **Telnet CLI** (password protected, off by default).
- **OLED display cycle**: flashing IP address → radio / mesh / WiFi / status pages → live packet traffic; button steps through pages. All timings configurable.
- **Radio changes apply without a reboot** (`set radio`).
- Every web setting maps 1:1 to a serial CLI command, and upstream command names and reply formats are unchanged, so existing apps and tools keep working.

## Build

```bash
pio run -e umc_heltec_v3_repeater
```

Targets live in [variants/umc/platformio.ini](variants/umc/platformio.ini). The web UI source is [web/umc/index.html](web/umc/index.html); it is gzipped into the firmware at build time by `scripts/umc_embed_web.py`. Open `web/umc/index.html?mock` through a local web server to try the UI against a simulated device.

## Flashing

- **Updating an existing MeshCore / EastMesh / UMC device** (keeps identity and settings): flash `bootloader.bin` @0x0, `partitions.bin` @0x8000, `boot_app0.bin` @0xe000, `firmware.bin` @0x10000 — or upload `firmware.bin` from the web UI.
- Back up first: `esptool --chip esp32s3 read-flash 0 0x800000 backup.bin`.

## UMC CLI additions

See [docs/umc/SPEC.md](docs/umc/SPEC.md) for the full catalogue. Highlights:

```
get/set wifi.ssid[2|3] / wifi.pwd[2|3]   wifi scan / get wifi.scan   wifi clear <n>
get/set net.ip dhcp|<ip> <mask> <gw> [dns]   net.hostname   net.mdns on|off
get/set ap.mode auto|on|off   ap.password <pw>|pin   ap.rescue <s>   get ap.status
get/set pin   http on|off   http.timeout <min>   telnet on|off   timezone <posix>
get/set display.mode cycle|status|off   display.ip|page|traffic|timeout <s>
region preset yorkshire|northwest|uk   get traffic   get setup / setup start|done
get umc.version   factory reset confirm
```

## License

MIT, as upstream MeshCore — see [license.txt](license.txt).
