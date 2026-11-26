# Ultimate MeshCore App (Android)

The phone app for Ultimate MeshCore radios — and for any standard MeshCore companion radio.

[**⬇ Install the latest APK**](https://github.com/2E0LXY/ultimate-meshcore/releases/tag/app-latest)

## What it does

| | |
|---|---|
| **Home** | The first screen is a grid of square tiles for everything the app does. The menu at the top right (☰) lists the same places; the Back button returns to Home. |
| **Connect** | Bluetooth (pair with the PIN on the radio's screen) or WiFi (TCP port 5000 on an Ultimate MeshCore client or repeater). Radios you use are remembered and reconnected. |
| **Messages** | Radio groups and room servers together with your **UMC Net** (internet) channels, newest first. UMC Net messages from the last 24 hours are kept on the phone, so history is there offline. Queued, pending, delivered, replied and failed states; ACK round-trip time kept separate from reply return-path hops; failure diagnosis; retry on the same route or automatic recovery through a recently ACKed route, live discovery and flood fallback. |
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

## Updating

The app checks the `app-latest` release on start and every 6 hours. When the published build differs from the installed one, a flashing **Update available** button appears left of the menu. Tap it: the APK downloads (progress shows on the button) and installs through the system installer. **Check for update** and the current build (version + commit) are in the menu. Debug builds (`GIT_SHA` = `dev`) never show the button.

First use asks once for "Install unknown apps" for this app; allow it, then press the button again.

Updates only install over the same signing key. CI signs releases with a stable key when these repo secrets exist:

| Secret | Value |
| --- | --- |
| `UMC_KEYSTORE_B64` | base64 of the `.jks` keystore (`base64 -w0 umc.jks`) |
| `UMC_KEYSTORE_PASSWORD` | store and key password (key alias `umc`) |

Create the key once: `keytool -genkeypair -v -keystore umc.jks -alias umc -keyalg RSA -keysize 2048 -validity 10000`. Without the secrets the build falls back to the debug key, and CI logs a warning.

Builds made before the stable key (debug-signed) need **one uninstall** before the first stable build, which loses the UMC Net enrolment on that phone. After that, in-app updates work. `versionCode` is `100 + CI run number`, so each build is newer than the last.

## Permissions

- **Bluetooth (scan and connect)** — to find and talk to radios. Android 11 and older ask for location instead, which is how Android gates Bluetooth scanning; the app does not use your position.
- **Internet** — the WiFi connection to a radio, the device web interface and map tiles.
- **Notifications** — new message alerts.

## Compatibility

Works with any MeshCore companion radio (the protocol is the standard companion protocol). The **Device** tab needs an Ultimate MeshCore device, because it uses the UMC web interface.
