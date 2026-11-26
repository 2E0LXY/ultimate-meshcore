# UMC presence: Wi-Fi CSI first, PIR and mmWave optional

ESPHome firmware for a Heltec WiFi LoRa 32 V3 / V3.2 or V4 (both ESP32-S3). Wi-Fi sensing ([ESPectre](https://espectre.dev/), built into ESPHome 2026.11+) is the default detector and needs no extra hardware. A PIR and an LD2410 mmWave module are drop-in add-ons.

**This replaces the MeshCore firmware on that board.** ESPHome has no MeshCore stack, so the board is a presence sensor, not a repeater. Use a separate board for each job. To keep MeshCore on the board and add Wi-Fi sensing as a switch, use the `umc_*_repeater_csi` firmware instead (MANUAL 13.3). This ESPHome package is for a dedicated sensor board.

## Use

1. Copy `secrets.example.yaml` to `secrets.yaml` and fill in a **2.4 GHz** network (802.11n).
2. In `heltec-v3.yaml` or `heltec-v4.yaml`, remove the `#` from `pir:` and/or `mmwave:` if fitted.
3. `esphome run heltec-v3.yaml` (or `heltec-v4.yaml`), first flash by USB.
4. Keep the room still for a few seconds after boot while Wi-Fi sensing calibrates.

| Entity | What it is |
|---|---|
| **Presence** | The fused result. Use this in automations. Holds for 30 s after the last detection. |
| Wi-Fi Motion, Wi-Fi Movement Score, Wi-Fi Calibrating | The CSI detector (always present) |
| PIR Motion | Only with `addon-pir.yaml` |
| mmWave Presence | Only with `addon-mmwave-ld2410.yaml`; also sees a person sitting still |
| **Presence Mode** | How the three are combined (below) |
| **Wi-Fi Sensing** | Switch it off to run on PIR / mmWave alone |

| Presence Mode | Result |
|---|---|
| Any detector (default) | On if any available detector says so. With nothing fitted this is plain Wi-Fi sensing, so adding a PIR or mmWave only ever adds detections |
| Wi-Fi only | CSI decides; add-ons are used only while Wi-Fi sensing is off or calibrating |
| Confirmed (2 of 3) | Needs two detectors to agree when at least two are available (fewer false alarms, more misses) |
| Add-ons only | Ignores Wi-Fi sensing |

## Wiring (assumed pins: check against your board's pinout before powering)

| Add-on | Module pin | Board pin |
|---|---|---|
| PIR | OUT | GPIO4 (`pir_pin`) |
| mmWave LD2410 | TX / RX | GPIO5 / GPIO6 (`mmw_rx_pin` / `mmw_tx_pin`), 256000 baud |
| both | VCC / GND | 5 V (LD2410, HC-SR501) or 3V3 (AM312) / GND |

Change the pins with `substitutions:` in the board file. Avoid pins the board uses for LoRa (8 to 14), the OLED, USB and the strapping pins.

## Status and limits

* All eight combinations (V3 and V4, with none, PIR, mmWave, both) pass `esphome config` on ESPHome 2026.11.1. **Not compiled or flashed**: no toolchain here. Pins, LD2410 wiring and detection quality are untested on hardware.
* Wi-Fi sensing needs the board connected to a 2.4 GHz access point, covers about one room per board, and detects movement, not people or counts. Static presence is weak: that is what the mmWave add-on is for.
* ESPectre and its ESPHome frontend are GPLv3. This directory only configures them; the UMC MeshCore firmware (MIT) does not include them.
* Not a safety or security system.

## Getting readings into UMC Net

Not wired up yet. The dash and app take sensor readings from the repeater `telemetry` topic (see MANUAL 13.2). This board could publish to the broker with ESPHome's `mqtt` component, and the dash would need a small JSON form of the topic. CSI inside the MeshCore firmware itself is possible (ESPectre also ships an Arduino library and C++ SDK), but it changes the licence of that firmware to GPLv3, adds load next to MQTT TLS and the web panel, and needs the repeater to be a Wi-Fi client of a nearby 2.4 GHz access point. Both are decisions for you.
