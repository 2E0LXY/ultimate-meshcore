# Ultimate MeshCore Desktop

The complete Ultimate MeshCore interface on Windows and Linux, for radios on USB, Bluetooth, WiFi or your network.

By **Daren Loxley 2E0LXY**.

[**⬇ Download (Windows / Linux)**](https://github.com/2E0LXY/ultimate-meshcore/releases/tag/desktop-latest) · [Manual section 20.1](../docs/umc/MANUAL.md#201-ultimate-meshcore-desktop-windows-and-linux)

![Connection page](../docs/images/desktop-connect.png)

## What it does

- **USB**:
  - repeaters, room servers and client radios, with the full web interface even when the radio has no WiFi;
  - **firmware updates over USB**, keeping identity and settings.
- **Bluetooth** and **WiFi app link (TCP 5000)**: client radios, with the messenger, contacts, channels, routes and trace, map, region scope and settings.
- **On your network**:
  - any Ultimate MeshCore repeater or client, with its complete web interface;
  - **Search this network** finds them.
- **Works with other MeshCore companion radios too**: messages, contacts, channels, map, radio, messaging and identity settings.
- **Recent connections**, and automatic reconnect after a restart.

![Messages over a WiFi app link](../docs/images/desktop-messages.png)

## Install

| System | Download | Then |
|---|---|---|
| Windows 10/11 | `UltimateMeshCoreDesktop-windows.exe` | Run it. If SmartScreen appears: **More info → Run anyway**. |
| Linux x86-64 | `ultimate-meshcore-desktop-linux-x86_64.tar.gz` | Extract it and run `./install.sh`. For USB, run `sudo usermod -aG dialout $USER` and log in again. |

The window uses Edge, Chrome, Chromium or Brave in app mode if one is installed, and your default browser otherwise.

## Run from source

```bash
cd desktop
pip install -r requirements.txt
python -m umc_desktop            # --browser, --no-window, --port 47815
```

## Build

```bash
pip install -r requirements.txt pyinstaller pillow
python build.py                  # dist/UltimateMeshCoreDesktop.exe or dist/ultimate-meshcore-desktop
```

CI builds both on every change ([`umc-desktop.yml`](../.github/workflows/umc-desktop.yml)) and publishes them to the `desktop-latest` release.

## How it works

- A small local server (`127.0.0.1:47815`) serves the same web interface the firmware serves.
- It answers the interface's `/api/*` requests from the connected radio:
  - **Client radios:** app-protocol frames go to the page as they would on the device. Settings, routes, traffic and the WiFi scan come through the desktop bridge command (`CMD 112`), or are translated to app commands on other companion radios.
  - **Repeaters on USB:** the `@umc` serial bridge returns the same JSON as the device's web API.
  - **Devices on the network:** requests are passed straight through.

| File | Purpose |
|---|---|
| `umc_desktop/links.py` | USB serial, TCP and Bluetooth connections |
| `umc_desktop/companion.py` | Client radio backend and settings translation |
| `umc_desktop/backends.py` | Repeater on USB, and network devices |
| `umc_desktop/flash.py` | Firmware install over USB |
| `umc_desktop/server.py` | Local web server and connection handling |
| `umc_desktop/static/` | Connection page and the connection bar |
