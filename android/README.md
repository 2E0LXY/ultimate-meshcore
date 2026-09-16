# Ultimate MeshCore App (Android)

The phone app for Ultimate MeshCore radios — and for any standard MeshCore companion radio.

[**⬇ Install the latest APK**](https://github.com/2E0LXY/ultimate-meshcore/releases/tag/app-latest)

## What it does

| | |
|---|---|
| **Connect** | Bluetooth (pair with the PIN on the radio's screen) or WiFi (TCP port 5000 on an Ultimate MeshCore client or repeater). Radios you use are remembered and reconnected. |
| **Messages** | Channels and direct messages, with delivery ticks, round-trip time, hops and signal, and retry when a message isn't confirmed. |
| **Contacts** | Everyone the radio knows: log in, **status**, **telemetry**, **trace path**, **discover path**, reset path, share, export/import `meshcore://` contacts, favourites, remove — and a **remote admin console** for repeaters and room servers. |
| **Channels** | Public, hashtag (`#name`), private (random key) and shared-key channels. |
| **Map** | Everyone who shares a location, on OpenStreetMap. Tiles you have already viewed keep working offline. |
| **Radio** | The radio's own settings: presets, frequency/bandwidth/SF/CR, TX power, name, location, delivery confirmations, location sharing, manual contact adding, Bluetooth PIN, reboot. |
| **Device** | The full web interface of any Ultimate MeshCore device on your WiFi: every command, neighbours, network status, clock, and **firmware updates** (check and install). |

## Building it yourself

```bash
cd android
./gradlew :app:assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
```

You need JDK 17 and the Android SDK (API 35). Gradle downloads the rest.

Releases are built by [`.github/workflows/umc-android.yml`](../.github/workflows/umc-android.yml) and signed with the standard debug key so they install by sideloading; sign with your own key before publishing to a store.

## Permissions

- **Bluetooth (scan and connect)** — to find and talk to radios. Android 11 and older ask for location instead, which is how Android gates Bluetooth scanning; the app does not use your position.
- **Internet** — the WiFi connection to a radio, the device web interface and map tiles.
- **Notifications** — new message alerts.

## Compatibility

Works with any MeshCore companion radio (the protocol is the standard companion protocol). The **Device** tab needs an Ultimate MeshCore device, because it uses the UMC web interface.
