#!/usr/bin/env python3
"""Send map tiles to an Ultimate MeshCore Client over WiFi, no card removal needed.

The tiles made by umc_make_map_tiles.py normally go onto the SD card in a reader. If the
card is already in the device, this pushes the same files to it over HTTP instead - the
device writes them to /maps itself.

    python scripts/umc_upload_map_tiles.py --host 192.168.4.1 --dir C:/mcbuild/umc-maps

The device must be reachable: either join its own setup hotspot (then it is at
192.168.4.1), or give it your WiFi and use the address it reports on the Info screen.
Already-sent tiles are skipped, so the command can be run again after an interruption.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

TILE_BYTES = 256 * 256 * 2


def get_status(host, timeout=10):
    with urllib.request.urlopen(f"http://{host}/api/map", timeout=timeout) as r:
        return json.loads(r.read().decode())


def put_tile(host, z, x, y, data, timeout=30):
    req = urllib.request.Request(
        f"http://{host}/api/map?z={z}&x={x}&y={y}", data=data, method="POST",
        headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(data))})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def find_tiles(root):
    """Yield (z, x, y, path) for every <root>/<z>/<x>/<y>.bin."""
    for zs in sorted(os.listdir(root), key=lambda v: int(v) if v.isdigit() else 99):
        zdir = os.path.join(root, zs)
        if not (zs.isdigit() and os.path.isdir(zdir)):
            continue
        for xs in sorted(os.listdir(zdir)):
            xdir = os.path.join(zdir, xs)
            if not (xs.isdigit() and os.path.isdir(xdir)):
                continue
            for name in sorted(os.listdir(xdir)):
                stem, ext = os.path.splitext(name)
                if ext == ".bin" and stem.isdigit():
                    yield int(zs), int(xs), int(stem), os.path.join(xdir, name)


def main():
    ap = argparse.ArgumentParser(description="Upload map tiles to a T-Deck over WiFi")
    ap.add_argument("--host", required=True, help="the device's address, e.g. 192.168.4.1")
    ap.add_argument("--dir", required=True, help="folder of tiles, as made by umc_make_map_tiles.py")
    ap.add_argument("--zoom", help="only these zooms, e.g. 12 or 11-13")
    ap.add_argument("--retries", type=int, default=3, help="attempts per tile")
    args = ap.parse_args()

    try:
        status = get_status(args.host)
    except Exception as err:
        sys.exit(f"Cannot reach {args.host}: {err}")
    if not status.get("supported"):
        sys.exit(f"That device cannot store tiles: {status.get('status')}")
    print(f"device: {status.get('status')}")

    zoom_lo, zoom_hi = 0, 99
    if args.zoom:
        if "-" in args.zoom:
            zoom_lo, zoom_hi = (int(v) for v in args.zoom.split("-"))
        else:
            zoom_lo = zoom_hi = int(args.zoom)

    jobs = [t for t in find_tiles(args.dir) if zoom_lo <= t[0] <= zoom_hi]
    if not jobs:
        sys.exit(f"No tiles found under {args.dir}")
    print(f"{len(jobs)} tiles, {len(jobs) * TILE_BYTES / 1e6:.1f} MB")

    sent = failed = 0
    started = time.time()
    for i, (z, x, y, path) in enumerate(jobs, 1):
        with open(path, "rb") as f:
            data = f.read()
        if len(data) != TILE_BYTES:
            print(f"  {z}/{x}/{y}: wrong size ({len(data)} bytes), skipped")
            failed += 1
            continue
        for attempt in range(1, args.retries + 1):
            try:
                put_tile(args.host, z, x, y, data)
                sent += 1
                break
            except Exception as err:
                if attempt == args.retries:
                    print(f"  {z}/{x}/{y}: {err}")
                    failed += 1
                else:
                    time.sleep(1.0 * attempt)      # the card may be busy; back off and retry
        if i % 10 == 0 or i == len(jobs):
            rate = sent * TILE_BYTES / max(0.1, time.time() - started) / 1000
            print(f"  {i}/{len(jobs)}  {rate:.0f} kB/s")

    print(f"Done: {sent} tiles stored, {failed} failed.")
    try:
        print(f"device: {get_status(args.host).get('status')}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
