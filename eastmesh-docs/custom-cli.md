# Custom CLI Commands

This page covers the EastMesh-specific CLI commands added in this repository.

It does not try to repeat the full upstream MeshCore CLI surface.

## Start Here

If you are doing first-time setup, these are the commands most users need before anything else:

```text
set wifi.ssid <your-ssid>
set wifi.pwd <your-password>
get wifi.status
set mqtt.iata <code>
get mqtt.status
```

For observers with the local web panel, these are also useful:

```text
set web on
get web.status
set web off
```

Use `set web on` while setting up or troubleshooting, then use `set web off` when a fixed observer needs maximum memory headroom.

## Observer Commands

These commands are available on `*_repeater_observer` firmware targets.

No-argument `get` commands must be entered exactly as shown.

### MQTT Status And Routing

- `get mqtt.status`: shows Wi-Fi, NTP, IATA, endpoint status, custom endpoint transport, status publishing state, TX state, and `leaked:<n>` (MQTT clients intentionally left unfreed after a heap-integrity failure at teardown; should stay `0`).
- `get mqtt.statuscfg`: shows whether periodic status messages are enabled as a simple `on` or `off` value. Most users can just use `get mqtt.status`.
- `get mqtt.client_version`: shows the MQTT `client_version` string published by the repeater.
- `get mqtt.client_env`: shows the PlatformIO env used to build the repeater firmware.
- `get mqtt.iata`: shows the IATA/location code used in MQTT topics.
- `set mqtt.iata <code>`: sets the IATA/location code, for example `MEL`.
- `set mqtt.iata UNSET`: marks MQTT IATA as not configured yet. While it is `UNSET`, enabled MQTT brokers stay disconnected until a real code is saved.

### MQTT Identity

- `get mqtt.owner`: shows the configured owner public key.
- `set mqtt.owner <64-hex-char-public-key>`: sets the owner public key used in JWT metadata.
- `mqtt.owner <64-hex-char-public-key>`: shorthand for setting the owner public key.
- `get mqtt.email`: shows the configured owner email.
- `set mqtt.email <email>`: sets the owner email used in JWT metadata.
- `mqtt.email <email>`: shorthand for setting the owner email.

### MQTT Message Controls

- `get mqtt.packets`: shows whether packet messages are published.
- `set mqtt.packets on|off`: enables or disables packet publishing.
- `get mqtt.raw`: shows whether raw packet payloads are published.
- `set mqtt.raw on|off`: enables or disables the separate `raw` MQTT topic.
- `set mqtt.status on|off`: enables or disables periodic MQTT status publishing.
- `get mqtt.tx`: shows whether TX packets are included.
- `set mqtt.tx on|off`: enables or disables TX packet publishing.
- `get mqtt.advert`: shows whether advert checking is on, how many adverts were checked, `mqtt.advert_drop` (the total dropped, split into `sig` bad signature and `short` malformed), `advert_skip` (adverts not checked because the check budget was empty; these are not published either) and `repeats` (adverts heard again, which reuse the earlier verdict without a new check).
- `set mqtt.advert.verify on|off`: before an advert heard on the radio is published to MQTT, check its structure and Ed25519 signature (the same rule the mesh uses) and drop corrupted ones. Default `on`, including for settings files saved by older firmware (an older file never switches it off by accident). Only adverts heard by radio are checked, not the repeater's own. Each distinct advert is checked once: hearing it again within 2 minutes (by another route, or a retransmission) reuses the verdict and costs nothing. Fresh checks are limited to a burst of 2 and 2 a second, so a flood of adverts cannot stall the receiver; adverts beyond that are counted in `advert_skip` and not published. A valid signature only means the advert is well formed and was signed by the key it names; it does not mean the node is trusted. `advert_drop` and `advert_skip` are published as `stats.advert_drop` and `stats.advert_skip` in the status message sent to a custom broker only, not to the public brokers.

### MQTT Boot ID

The MQTT status message (and its offline will) and the UMC Net telemetry message carry `"boot_id"`: a random 64-bit number chosen at each boot, sent as a 16-character upper-case hex string (for example `"3F9A07C1D2B84E65"`). A change means the repeater restarted. It is chosen once, early in start-up, so status and telemetry always show the same value. It is sent to the custom (your own) broker only; the public brokers (LetsMesh, EastMesh, MeshMapper) do not receive it. It is not stored, not derived from the device key, MAC or location, and holds no personal data. It is not a command; there is nothing to configure.

### Trial Settings (tryset)

Try a setting for a while and have it go back by itself if you lose contact. Available on repeater builds.

- `tryset <secs> <key> <value>`: applies the setting now, without saving it, for 30 to 3600 seconds. The value is checked exactly as `set <key> <value>` checks it, and also against the trial limits below. One trial at a time.
- `tryset keep`: ends the trial and saves the value, the same way a plain `set` saves (so, for example, a local advert interval under 60 minutes is switched off, exactly as `set` does).
- `tryset revert`: puts the original value back now and reads it back to confirm it.
- `tryset status`: shows the setting on trial and the time left.
- `tryset keys [n]`: lists the settings that can be trialled, a page at a time (`tryset keys 2` for the next page).

Trailing spaces are ignored (`tryset keep ` is `tryset keep`).

If the timer runs out the original value is restored (and read back). A reboot also restores it, because the trial value was never saved. While a trial runs, `set` of any trialable setting is refused (`tryset keep` or `tryset revert` first); `set` of anything else still works, so you can still change the node name, passwords and the like to recover. Any save of the settings made during a trial writes the original value of the trialled setting, so a trial value cannot reach flash by another route, and the trial value is put back live afterwards. `tryset` is an ordinary CLI command: it needs the same administrator access as `set`. Commands that change a trial run one at a time (a lock), because web and MQTT commands arrive on a different task from the one that expires trials; if the lock is busy at the moment the timer ends, the revert happens a moment later. Start, keep, revert and timer expiry are logged on the serial console (key only, never the value).

Settings that can be trialled, with the limit applied to a trial (plain `set` is unchanged):

| Key | Trial limit |
| --- | --- |
| `dutycycle` | 10 to 100 (lower would make an airtime factor the saved-settings loader clamps) |
| `af` | 0 to 9 |
| `advert.interval`, `flood.advert.interval` | as `set` (0 or 60 to 240 minutes; 0 or 3 to 168 hours) |
| `flood.max`, `flood.max.advert`, `flood.max.unscoped` | 1 to 64 (0 would stop forwarding) |
| `rxdelay` | 0 to 10 |
| `txdelay`, `direct.txdelay` | 0 to 1 |
| `agc.reset.interval` | 0 to 1020 |
| `multi.acks` | 0 or 1 (the saved-settings loader clamps it to 0 to 1; plain `set multi.acks 300` wraps a byte, an upstream quirk left unchanged) |

These were chosen to be recoverable by the timer: none touches the radio parameters the admin link depends on. That is a judgement, not a guarantee; a poor value can still cost airtime or reach until the timer ends or `tryset revert` is heard.

Deliberately not trialable, so `tryset` refuses them (`Err - cannot trial that setting`): radio frequency, bandwidth, spreading factor, coding rate, presets and regions, TX power, the interference threshold, passwords and keys, access control, WiFi, MQTT and broker settings, and anything else that could cut you off. Radio parameters stay excluded until a hardware rollback has been proven; use `tempradio` for a timed radio test.

### MQTT Endpoints

- `get mqtt.eastmesh-au`
- `set mqtt.eastmesh-au on|off`
- `get mqtt.meshmapper`
- `set mqtt.meshmapper on|off`
- `get mqtt.waev`
- `set mqtt.waev on|off`
- `get mqtt.letsmesh-eu` (retired)
- `set mqtt.letsmesh-eu on|off` (retired)
- `get mqtt.letsmesh-us` (retired)
- `set mqtt.letsmesh-us on|off` (retired)
- `get mqtt.custom`
- `set mqtt.custom on|off`
- `get mqtt.custom.host`
- `set mqtt.custom.host <host>`
- `get mqtt.custom.port`
- `set mqtt.custom.port <port>`
- `get mqtt.custom.transport`: shows `tcp` or `wss`.
- `set mqtt.custom.transport tcp|wss`
- `get mqtt.custom.username`
- `set mqtt.custom.username <username>`
- `get mqtt.custom.password`: shows `set` when a custom password is configured.
- `set mqtt.custom.password <password>`

Notes:

- new observer installs default `mqtt.iata` to `UNSET`
- a maximum of two MQTT brokers can be enabled at once
- `meshmapper` is the curated global broker (`wss://mqtt.meshmapper.net:443/mqtt`); like `eastmesh-au` it uses WSS, verified TLS, and MeshCore JWT auth with the broker host as the token audience
- `waev` is a curated broker (`wss://mqtt.waev.app:443/mqtt`); like `eastmesh-au` it uses WSS, verified TLS, and MeshCore JWT auth with the broker host as the token audience, but enforces a 1-hour auth token lifetime (the firmware mints a shorter-lived token for it automatically)
- `letsmesh-eu` and `letsmesh-us` are retired (LetsMesh is no longer maintained) and off by default; any saved selections are cleared once on upgrade, though the endpoints stay selectable for legacy use
- if `mqtt.iata` is `UNSET`, enabled MQTT brokers will not connect
- custom MQTT uses the configured username and password, not JWT authentication
- custom MQTT defaults to TCP; set `mqtt.custom.transport wss` for MQTT over secure WebSockets using the fixed `/mqtt` websocket path and the ESP-IDF x509 root CA bundle
- `get mqtt.status` reports the two enabled broker slots as `p:<broker>:<state>` (primary) and `s:<broker>:<state>` (secondary), or `-` when a slot is empty; custom appears as `custom:<transport>:<state>` (for example `p:custom:wss:up`); `conn` means connecting and `up` means connected
- custom MQTT uses the same `meshcore/<IATA>/<device>/<leaf>` topics as the curated brokers
- turning off a connected broker publishes a retained MQTT status update with `"status":"offline"` before the client disconnects
- changing `mqtt.iata` away from a configured value also publishes retained offline status to the old status topic, restarts connected broker clients, and reconnects under the new topic path

Legacy dotted aliases are also accepted:

- `mqtt.eastmesh.au`
- `mqtt.letsmesh.eu`
- `mqtt.letsmesh.us`

### Wi-Fi Settings For Observers

- `get wifi.status`: shows SSID, connection state, raw Wi-Fi status code, IP, channel, and signal when connected, plus gateway health (`gw:ok|lost`) and the watchdog reconnect count (`wd:<n>`).
- `get wifi.ssid`: shows the configured Wi-Fi SSID.
- `set wifi.ssid <ssid>`: sets the Wi-Fi SSID.
- `set wifi.pwd <password>`: sets the Wi-Fi password.
- `get wifi.powersaving`: shows the current Wi-Fi power save mode.
- `set wifi.powersaving none|min|max`: sets Wi-Fi power saving mode.
- `wifi reconnect`: drops the current association and rejoins from a full channel scan. Use when a node reports connected but is unreachable over the network.

Observers also run a connectivity watchdog: while Wi-Fi reports connected, the node ARP-probes its gateway every 30 seconds. If the gateway stays silent for 3 minutes (for example, an AP that keeps beaconing after losing its wired uplink), the node forces a full reconnect on its own, backing off up to 48 minutes between attempts while the outage persists. `wd:<n>` in `get wifi.status` counts these forced reconnects since boot.

### NTP Settings For Observers

- `get ntp.server1`: shows the primary NTP server.
- `get ntp.server2`: shows the secondary NTP server.
- `get ntp.server3`: shows the tertiary NTP server.
- `set ntp.server1 <host>`: sets the primary NTP server and restarts time sync.
- `set ntp.server2 <host>`: sets the secondary NTP server and restarts time sync.
- `set ntp.server3 <host>`: sets the tertiary NTP server and restarts time sync.

Default servers are `au.pool.ntp.org`, `time.google.com`, and `time.cloudflare.com`.

### ESP-NOW Bridge Settings For Observer ESP-NOW Builds

These commands are available on `*_repeater_observer_espnow` firmware targets that use the ESP-NOW bridge transport.

Bridge commands are for local ESP-NOW bridge use between nearby repeaters, such as linking repeaters on `Australia (Narrow)` and `Australia (Mid)`. They are not MQTT-over-WAN, VPN, or internet bridge controls.

- `get bridge.channel`: shows the configured ESP-NOW bridge channel.
- `set bridge.channel <channel>`: sets the ESP-NOW bridge channel and restarts the bridge. Use a value from `1` to `14`.
- `get bridge.secret`: shows the configured ESP-NOW bridge secret.
- `set bridge.secret <secret>`: sets the shared ESP-NOW bridge secret and restarts the bridge.

After running `set bridge.channel`, expect the bridge and web panel connection to drop briefly while the radio restarts. On current observer ESP-NOW builds, this can look like the board rebooted.

For `*_repeater_observer_espnow` builds that are connected to Wi-Fi, the ESP-NOW bridge channel must match the active 2.4 GHz Wi-Fi channel:

1. Run `get wifi.status`.
2. Read the `channel:<n>` value from the connected Wi-Fi status.
3. Run `get bridge.channel`.
4. If the values differ, run `set bridge.channel <n>` using the Wi-Fi channel value.
5. Use the same `bridge.channel` and `bridge.secret` on every ESP-NOW bridge node that should talk together.

Example:

```text
> get wifi.status
> ssid:EastMesh-IoT status:connected code:3 state:connected ip:192.168.1.50 channel:6 rssi:-61 quality:78% signal:good gw:ok wd:0
> get bridge.channel
> 1
> set bridge.channel 6
OK
```

### Web Panel Controls

- `get web`
- `get web.status`: shows whether the local HTTPS panel is available, plus `heals:<n>` (times the panel was restarted because internal heap was too fragmented for a TLS handshake) and `deferred:<n>` (start attempts postponed until heap headroom recovered).
- `get web.stats.status`: shows whether the dedicated stats page and history subsystem are enabled, whether recent history is active, whether PSRAM-backed history is available, and whether the SD-backed archive is mounted. When enabled, the history capture now covers supported environment telemetry too, not just the original battery/radio series. GPS-active boards also record per-minute satellites samples for the `/stats` history view. If archive access drops while stats remain enabled, the repeater retries the SD mount periodically.
- At boot, archive-backed stats restore uses bounded reads of the latest summary, events, and neighbour snapshots so malformed or unexpectedly large archive files do not delay MQTT or web startup.
- `set web on|off`
- `set.web on|off`: enables or disables the local HTTPS panel.
- `set web.stats on|off`
- `set.web.stats on|off`: enables or disables the dedicated `/stats` page and historical stats collection.
- `purge sd`: deletes files and directories from the mounted SD card archive, then recreates the empty `/stats` archive directory so runtime stats capture can continue. It does not erase the internal repeater filesystem or stored settings.

### Runtime Diagnostics

- `memory`: shows current heap and PSRAM usage.
- `stats-core`: shows battery, uptime, sticky error count, and outbound queue depth.
- `stats-radio`: shows radio noise floor, last RSSI, last SNR, and TX/RX airtime.
- `stats-packets`: shows packet receive/send totals, flood/direct breakdown, and receive errors.

> If `noise_floor` reports `0`, check `get agc.reset.interval`; if it is not `0`, try `set agc.reset.interval 0` and test again.

### Flood Forwarding Limit

- `get flood.max.unscoped`: shows the hop limit for unscoped flood packets.
- `set flood.max.unscoped <0-64>`: sets the hop limit for unscoped flood packets.
- `get flood.max.advert`: shows the hop limit for flooded advert packets.
- `set flood.max.advert <0-64>`: sets the hop limit for flooded advert packets.

Observer builds default `flood.max.unscoped` to `64`. Lower values can limit how far unscoped flood traffic is repeated while leaving scoped/region flood forwarding controlled by `flood.max`.

### Board Battery Reporting

- On observer builds, background battery sampling used for MQTT/status history is rate-limited to about once per minute. Explicit status and telemetry requests still refresh the reading immediately.

### T-Beam 1W Fan Control

These commands are only available on `LilyGo_TBeam_1W_*` repeater builds.

- `get fan`: shows the current fan mode, current fan state, and the last NTC-based board temperature when available.
- `set fan auto`: returns the fan to automatic control and persists that mode across reboot.
- `set fan on`: forces the fan on and persists that mode across reboot.
- `set fan off`: forces the fan off and persists that mode across reboot.
- `set fan timeout <Ns>`: changes the automatic post-TX hold window in seconds and persists it across reboot, for example `set fan timeout 45s`.

Auto mode behaviour:

- forces the fan on during TX and keeps it on for the configured timeout afterward
- otherwise turns the fan on at `48C`
- turns it back off at `42C`
- keeps the fan on if the NTC reading is unavailable

Notes:

- default repeater fan mode is `auto`
- default post-TX timeout is `30s`
- fan mode and timeout are stored in repeater prefs and survive reboot
- only `LilyGo_TBeam_1W_*` repeater builds use these persisted fan settings
- accepted range is `0s` to `600s`

## UMC Radio Defaults

- UK default radio: `869.431` MHz, `62.5` kHz, SF `8`, CR `5` (`get radio` returns `869.431,62.5,8,5`)
- fresh installs apply these defaults on first boot
- devices with persisted radio settings keep them across upgrade; change them with `set radio 869.431,62.5,8,5`
- regions: the device should be left with the wildcard `*` region only

## Web Panel CLI Access

When the repeater web panel is enabled and you are authenticated, the browser CLI panel can run the same CLI commands accepted by the repeater.

Notes:

- the panel still uses the repeater admin password for access
- commands run with the same care as if you typed them into the repeater CLI directly
- this is intended for local admin use on a trusted network
- `start ota` releases the local HTTP redirect listener on port `80` so the OTA HTTP listener can take over without stopping the rest of the repeater services, regardless of whether the command is run from the web panel, serial CLI, or a remote companion/app CLI session
- if the old redirect listener has not fully released port `80`, the OTA listener retries for up to about 30 seconds before giving up
- the web `Purge SD` button runs `purge sd` after browser confirmation
- `start ota` uses the repeater's existing Wi-Fi address when already connected, or starts the `MeshCore-OTA` access point when Wi-Fi is not connected
- the `/app` Regions shortcut runs the existing MeshCore region commands in sequence: `region put au`, `region put au-STATE`, `region allowf au`, `region allowf au-STATE`, then `region save`

## Companion Wi-Fi Rescue Commands

These commands are available in the serial rescue CLI for `*_companion_radio_wifi` builds.

To enter `CLI Rescue`:

- open a serial monitor at `115200` baud
- reboot the device
- long-press the user button within the first 8 seconds after boot
- wait for `========= CLI Rescue =========`

- `get wifi.status`: shows configured SSID, connection status, raw Wi-Fi status code, IP, channel, and signal when connected.
- `get wifi.ssid`: shows the configured Wi-Fi SSID.
- `get wifi.powersaving`: shows the current Wi-Fi power saving mode.
- `set wifi.ssid <ssid>`: saves a Wi-Fi SSID and immediately retries connection.
- `set wifi.pwd <password>`: saves a Wi-Fi password and immediately retries connection.
- `set wifi.powersaving none|min|max`: changes the Wi-Fi power save mode.

Companion Wi-Fi builds also still support the existing rescue commands such as:

- `set pin <6-digit-pin>`
- `rebuild`
- `erase`
- `ls ...`
- `cat ...`
- `rm ...`
- `reboot`

### Recovery Access Point

When a companion Wi-Fi device has no Wi-Fi credentials configured, or cannot connect
to its configured network for 60 seconds, it broadcasts its own `EastMesh-WiFi`
access point so it can be rescued without a serial cable.

**The AP password is the device pin, zero-padded to 8 digits** (WPA2 requires at
least 8 characters). The pin follows the same rules as the Bluetooth pairing pin on
BLE builds:

| Device                      | Active pin                                                             | `EastMesh-WiFi` password                                       |
| --------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------- |
| Has a screen, no pin set    | random 6-digit pin each boot, shown as `Pin:NNNNNN` on the home screen | `00NNNNNN` — read it off the screen                            |
| No screen, no pin set       | `123456` (default)                                                     | `00123456`                                                     |
| Pin set via `set pin <pin>` | your configured pin (any device)                                       | your pin zero-padded to 8 digits, e.g. pin `4242` → `00004242` |

Notes on the pin:

- on devices with a screen, the pin is only random while no pin has been saved; run
  `set pin <pin>` for a fixed password (takes effect next boot)
- headless devices in public areas should always get a custom pin — `00123456` is a
  documented default, so treat it like a default router password

Recovery steps:

1. join the `EastMesh-WiFi` network with the password from the table above
2. open the rescue CLI with `telnet 192.168.4.1` (or `nc 192.168.4.1 23`) — all
   rescue commands above are available
3. `set wifi.ssid <ssid>`, then `set wifi.pwd <password>` — the device immediately
   retries the network with the new credentials
4. `reboot` (or just wait — see below)

While the AP is up the device keeps retrying its configured network about once a
minute (expect a brief AP hiccup at each attempt); as soon as the station
connection succeeds, the recovery AP shuts down automatically (this also drops
your rescue session — that's the sign it worked).

### Using the Companion App over the AP (Roaming)

The recovery AP is not just for fixing credentials — the full companion protocol
is available through it, which makes it a roaming access mode when the device is
away from its configured network:

1. join `EastMesh-WiFi` with the pin-derived password (see the table above)
2. in the MeshCore companion app, add/connect a Wi-Fi device with host
   `192.168.4.1` and port `5000`
3. use the app normally — messages, contacts, channels all work over the AP

Notes for roaming use:

- run `set pin <pin>` once so the AP password stays fixed across reboots;
  otherwise devices with a screen pick a new random pin every boot
- the AP appears about 60 seconds after boot (the device tries its configured
  network first), and stays up for as long as that network is unreachable
- back in range of its configured network, the device joins it and shuts the AP
  down automatically — reconnect the app via the LAN address instead

## Sensor Telemetry (UMC builds)

No new CLI commands. UMC builds of `simple_repeater` read the sensors every `SENSOR_READ_INTERVAL_SECS` (60) only while someone is listening: a UMC Net broker connection, or a radio subscriber (request types `0x08` and `0x09`, see `docs/payloads.md`). With the UMC Net link up the repeater publishes `meshcore/<area>/<id>/telemetry` on change and at least every 15 minutes; it never publishes it to public brokers. Adds about 100 bytes of RAM per ACL client (`TELEM_SUB_MAX_ENTRIES` 8).

## Wi-Fi Motion Sensing (UMC `*_csi` builds)

- `get csi`: `off`, `on, waiting for Wi-Fi`, `on, calibrating`, or `on, motion|idle, movement <0..1>`; `not in this build` on normal builds.
- `set csi on|off`: saved; off by default. Presence and movement are added to telemetry (channels 20 and 21) while sensing is running.
- Built only with `-D UMC_WIFI_CSI=1` (environments `umc_*_repeater_csi`, pioarduino platform, ESPectre library, GPLv3).

## Heap Health Check Script

`eastmesh-tools/web-heap-check.sh <host> [--stress] [--rounds N]` reads `memory`, `get web.status`, `get mqtt.status` and `get wifi.status` over the HTTPS API and, with `--stress`, simulates browser page-load bursts before re-reading `memory`. Authenticate with `REPEATER_PASSWORD` or `REPEATER_TOKEN` in the environment (or enter the password at the prompt). Watch `heap_max` (largest internal block; TLS needs ~40KB), `heap_min`, and the `heals`/`deferred`/`leaked` counters.
