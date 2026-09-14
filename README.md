# Ultimate MeshCore (UMC)

**All-in-one MeshCore firmware with a complete WiFi web interface.**
Fully compatible with standard MeshCore nodes and apps, with setup, management and updates you can do from any browser.

[**⚡ Install with the USB web flasher**](https://2e0lxy.github.io/ultimate-meshcore/) · [**📖 User manual (A–Z)**](docs/umc/MANUAL.md) · [**⬇ Latest build**](https://github.com/2E0LXY/ultimate-meshcore/releases/tag/latest)

> **Status: 0.1.0 (early).** The Heltec V3 / V3.2 **repeater** is available and running on hardware. Heltec V4 (OLED/TFT/R8) repeater builds are published but not yet tested on V4 hardware. Client (companion) and room-server builds, Bluetooth and the T-TWR are in progress — see the [roadmap](docs/umc/ROADMAP.md).

---

## Supported hardware

| Board | Repeater | Client | Room server |
|---|---|---|---|
| Heltec WiFi LoRa 32 V3 / V3.2 | ✅ | planned | planned |
| Heltec V4 OLED / TFT / R8 | ✅ build (hardware test pending) | planned | planned |
| LilyGo T-TWR + SX1262 add-on | planned | planned | — |

---

## All functions

### Installation and updates
- **USB web flasher** (Chrome/Edge). It always installs the newest build, and can **update** (keeping identity and settings) or do a **fresh install**.
- **Internet updates on the device**: check and install the latest build for the exact board and firmware type over verified HTTPS, optionally automatic.
- **Upload a firmware file** in the browser, with image validation (rejects merged/wrong-chip images, warns about the wrong board or type).
- **Automatic rollback**: an update must run healthily for 60 s or the device returns to the previous firmware; `ota rollback` on demand.
- Legacy `start ota` hotspot, esptool, and **automatic CI builds** of every target on each push.

### First-time setup
- **Open setup hotspot** `UMC-Setup-XXXX` with a captive portal: join it and the setup page opens.
- **Setup wizard**: radio preset, TX power, duty cycle (suggests 10 % in the UK/EU 869.4–869.65 MHz band), name, location from a map (rounded ~100 m), admin and guest passwords, WiFi with scan, telnet, MQTT location code, and clock set from the browser.
- Keeps existing settings and only applies what you change. It can be re-run at any time.

### Web interface (every setting)
- **Dashboard**: uptime, battery, clock, packets, neighbours, queue, memory, WiFi, hotspot, MQTT, radio preset, noise floor, RSSI/SNR, airtime, quick actions, update banner.
- **Radio**: regional presets (same list as the MeshCore apps), frequency/BW/SF/CR **applied without reboot**, TX power, duty cycle, RX gain, AGC reset, CAD, interference threshold, temporary radio test.
- **Mesh & routing**: repeat, loop detection, path hash size, flood/unscoped/advert/**channel** hop limits, extra ACKs, TX/direct/RX delays, advert intervals, send adverts, discover neighbours.
- **Identity & access**: name, location (map picker), owner info, admin/guest passwords, public key, private key export/import, ACL permissions.
- **Regions**: tree view with per-region **flooding switch, set home, remove** (sub-regions first), **UK presets** (`yorkshire`, `northwest`, `uk`), add, one-line definitions, unsaved-change reminder.
- **Network**: 3 saved WiFi networks with scan, static IP / DHCP, hostname and `.local` name, hotspot mode (auto/on/off), rescue delay, hotspot password/PIN, session timeout, telnet, NTP servers, time zone.
- **MQTT**: location code, identity, what to publish, preset brokers (MeshMapper, waev, EastMesh, LetsMesh), custom TCP/WSS broker, status.
- **Bridge**: ESP-NOW (channel, secret, delay, source) and RS-232 settings.
- **Power & hardware**: power saving, battery calibration, GPS, **display cycle settings**, board info.
- **Neighbours**: list with age/SNR, forget, discover.
- **Live traffic**: packet list with type/route/hops/RSSI/SNR, filters and per-minute counts.
- **Routes & trace**: route table learned from adverts (hop chain with repeater names), find, **add/pin a route**, **trace** out and back with per-hop SNR, forget.
- **Console**: full command line with history.
- **Firmware & maintenance**: internet update, file update, clock sync, reboot, stats/log controls, legacy OTA, re-run setup, power off, factory reset.
- **Backup & restore**: JSON backup (passwords excluded, private key optional) with a preview before restore.
- Sign-in with session timeout and lockout, a “device not reachable” screen with auto-reconnect, and mobile-friendly light/dark themes.

### WiFi and networking
- Up to **three networks**, tried in order, with gateway watchdog and automatic reconnect.
- **Rescue hotspot** when no saved network is reachable (PIN protected). Always-on and never modes too.
- Static IP, custom hostname, **mDNS** (`http://umc-<name>.local/`), network scan, captive portal.
- **Telnet** command line (port 23, password protected, off by default).
- Time sync from NTP (UK servers by default). Mesh time stays UTC.
- Optional classic EastMesh HTTPS panel with stats history.

### Display (OLED)
- Cycle: **flashing IP address** → radio → mesh → WiFi → status → **live packet traffic**, all with adjustable timings. Modes cycle/status/off, blank-after timeout.
- Button steps through screens; long press powers off.
- Setup and rescue screens show the hotspot name and password state.

### Mesh features (from MeshCore / EastMesh)
- Full MeshCore 1.17.1 repeater: flood/direct routing, regions and scopes, ACLs, remote admin over the mesh, neighbours, statistics, packet log, GPS and sensors.
- **MQTT observer** uploads with JWT/WSS, two broker slots and status publishing.
- **ESP-NOW bridge** between nearby LoRa segments.

### Command line additions
Everything in the web interface is also a command (USB serial, telnet, web console, or remote admin over the mesh). UMC adds:

```
wifi.ssid2/3, wifi.pwd2/3, wifi clear, wifi scan, get wifi.scan, wifi.enabled, get wifi.networks
net.ip, net.hostname, net.mdns, get net.status
ap.mode, ap.password, ap.rescue, get ap.status, pin
http, http.timeout, telnet, timezone
display.mode, display.ip, display.page, display.traffic, display.timeout
region preset yorkshire|northwest|uk, get traffic, group.hops.max, advert.hops.max
routes, route <node>, route find|pin|unpin|forget, trace <path>, trace route <node>, get trace
update check, update install, get update.status, update.auto, update.interval, update.url, get build
get ota.state, ota rollback
get setup, setup start, setup done, get umc.version, factory reset confirm
```

The full list with explanations is in the [manual's command reference](docs/umc/MANUAL.md#23-command-reference-az).

---

## Quick start

1. Open the [web flasher](https://2e0lxy.github.io/ultimate-meshcore/), choose your board, and press **Install**. Choose **No** at “Erase device?” to keep an existing node's identity.
2. Join the `UMC-Setup-XXXX` WiFi hotspot and follow the setup wizard.
3. Reconnect to your home WiFi and open `http://umc-<name>.local/` or the IP shown on the display.

## Building

```bash
git clone https://github.com/2E0LXY/ultimate-meshcore
cd ultimate-meshcore
pio run -e umc_heltec_v3_repeater            # build
pio run -e umc_heltec_v3_repeater -t upload  # build and flash over USB
```

- Targets: [`variants/umc/platformio.ini`](variants/umc/platformio.ini)
- Web UI source: [`web/umc/index.html`](web/umc/index.html), gzipped into the firmware at build time. Serve `web/umc/` locally and open `index.html?mock` to try the UI against a simulated device.
- Web flasher: [`flasher/`](flasher/), published by [`.github/workflows/umc-firmware.yml`](.github/workflows/umc-firmware.yml)

## Documentation

| Document | Contents |
|---|---|
| [MANUAL.md](docs/umc/MANUAL.md) | Complete user guide from installation to every setting, troubleshooting, command reference and glossary |
| [ROADMAP.md](docs/umc/ROADMAP.md) | What's next, and features found in other projects that are being added |
| [SPEC.md](docs/umc/SPEC.md) | Design specification |
| [SOURCES.md](docs/umc/SOURCES.md) | Every project reviewed and what each contributes |

## Credits

- [MeshCore](https://github.com/meshcore-dev/MeshCore) — Scott Powell / Ripple Radios and contributors
- [MeshCore-EastMesh](https://github.com/xJARiD/MeshCore-EastMesh) — WiFi, MQTT observer, HTTPS panel, ESP-NOW bridge ([original README](docs/EASTMESH_README.md))
- Ideas and features from agessaman/MeshCore, OffbandMesh, meshcomod, MeshCore-Low-Power, MeshCore-BitChat, jmead's MQTT gateway, meshcore-open, LitBomb's FAQ, the UK MeshCore guide and others — see [SOURCES.md](docs/umc/SOURCES.md)
- USB flashing by [ESP Web Tools](https://esphome.github.io/esp-web-tools/)

## License

MIT, as upstream MeshCore — see [license.txt](license.txt).
