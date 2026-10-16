#!/usr/bin/env python3
"""Flash a board after checking it is the board you meant.

A port number is not an identity: unplugging a device and plugging in another gives the
second one whatever port is free, and firmware built for one board will happily write to
another and leave it unable to start. This asks the chip what it is first, and refuses
anything that does not match.

    python scripts/umc_flash.py --env umc_heltec_v4_oled_repeater --port COM19
    python scripts/umc_flash.py --env umc_lilygo_tdeck_client --port COM16 --expect-mac 20:6e:f1:b8:a9:84
    python scripts/umc_flash.py --list
"""
import argparse
import re
import subprocess
import sys

# What each environment needs of the chip it is written to. A mismatch here is the
# difference between a working radio and one stuck in a boot loop.
BOARDS = {
    "umc_lilygo_tdeck_client": {"psram": "octal", "note": "T-Deck, 8 MB octal PSRAM"},
    "umc_heltec_v3_client": {"psram": "none", "note": "Heltec V3, no PSRAM"},
    "umc_heltec_v3_repeater": {"psram": "none", "note": "Heltec V3, no PSRAM"},
    "umc_heltec_v4_oled_client": {"psram": "embedded", "note": "Heltec V4, 2 MB embedded PSRAM"},
    "umc_heltec_v4_oled_repeater": {"psram": "embedded", "note": "Heltec V4, 2 MB embedded PSRAM"},
    "umc_heltec_v4_tft_client": {"psram": "embedded", "note": "Heltec V4 TFT"},
    "umc_heltec_v4_tft_repeater": {"psram": "embedded", "note": "Heltec V4 TFT"},
    "umc_heltec_v4_r8_oled_client": {"psram": "embedded", "note": "Heltec V4 R8"},
    "umc_heltec_v4_r8_oled_repeater": {"psram": "embedded", "note": "Heltec V4 R8"},
    "umc_heltec_v4_r8_tft_client": {"psram": "embedded", "note": "Heltec V4 R8 TFT"},
    "umc_heltec_v4_r8_tft_repeater": {"psram": "embedded", "note": "Heltec V4 R8 TFT"},
}


def esptool(*args):
    return subprocess.run([sys.executable, "-m", "esptool", *args],
                          capture_output=True, text=True, timeout=120).stdout


def identify(port):
    """What is on this port: its MAC, and how much PSRAM it has."""
    out = esptool("--chip", "esp32s3", "-p", port, "--after", "no-reset", "read-mac")
    mac = re.search(r"^MAC:\s*([0-9a-f:]{17})", out, re.M | re.I)
    features = re.search(r"^Features:\s*(.+)$", out, re.M)
    if not mac:
        return None
    feat = features.group(1) if features else ""
    if "Embedded PSRAM" in feat:
        psram = "embedded"
    elif "PSRAM" in feat:
        psram = "octal"
    else:
        psram = "none"
    return {"mac": mac.group(1).lower(), "features": feat, "psram": psram}


def list_ports():
    import serial.tools.list_ports
    for p in serial.tools.list_ports.comports():
        tag = " <- Espressif native USB" if p.vid == 0x303A else ""
        print(f"  {p.device:8} vid={hex(p.vid or 0)}  {p.description}{tag}")


def main():
    ap = argparse.ArgumentParser(description="Flash a board, checking first that it is the right one")
    ap.add_argument("--env", help="the PlatformIO environment to write")
    ap.add_argument("--port", help="the serial port it is on")
    ap.add_argument("--expect-mac", help="refuse unless the board has this MAC")
    ap.add_argument("--list", action="store_true", help="show the ports and stop")
    ap.add_argument("--baud", default="921600")
    ap.add_argument("--force", action="store_true", help="write even if the board looks wrong")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return
    if not args.env or not args.port:
        sys.exit("Give --env and --port, or --list")

    want = BOARDS.get(args.env)
    if want is None:
        sys.exit(f"I do not know what board {args.env} is for. Add it to BOARDS first.")

    found = identify(args.port)
    if found is None:
        sys.exit(f"Nothing answered on {args.port}. Is it connected, and is anything else using the port?")

    print(f"{args.port}: {found['mac']}  {found['features']}")
    print(f"{args.env}: {want['note']}")

    if args.expect_mac and found["mac"] != args.expect_mac.lower():
        sys.exit(f"Refusing: that is {found['mac']}, not {args.expect_mac.lower()}.")

    if found["psram"] != want["psram"] and not args.force:
        sys.exit(
            f"Refusing: this build wants {want['psram']} PSRAM and the board has {found['psram']}.\n"
            "Writing it would leave the board unable to start. Use --force only if you are sure."
        )

    firmware = f".pio/build/{args.env}/firmware.bin"
    print(f"writing {firmware} ...")
    out = esptool("--chip", "esp32s3", "-p", args.port, "-b", args.baud, "--after", "watchdog-reset",
                  "write-flash", "-z", "0x10000", firmware)
    ok = out.count("Hash of data verified")
    print("verified" if ok else "something went wrong:")
    if not ok:
        print(out[-800:])
        sys.exit(1)


if __name__ == "__main__":
    main()
