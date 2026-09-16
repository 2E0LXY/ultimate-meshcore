#!/usr/bin/env python3
"""Build offline map tiles for the Ultimate MeshCore Client on a T-Deck.

The device draws raw RGB565 tiles straight from the SD card, so no image decoding is
needed on the radio. This script downloads (or converts) 256x256 map tiles and writes
them as /maps/<zoom>/<x>/<y>.bin on the card.

Examples
--------
Area around Leeds, zoom 10 to 13, onto a card mounted at E:\\ :

    python scripts/umc_make_map_tiles.py --bbox 53.5,-2.0,54.0,-1.2 --zoom 10-13 --out E:/maps

From tiles you already have on disk (any layout PNG/JPG, named <z>/<x>/<y>.png):

    python scripts/umc_make_map_tiles.py --from-dir ./tiles --out E:/maps

Tile servers have usage policies. OpenStreetMap's standard tiles are fine for small
personal areas (see https://operations.osmfoundation.org/policies/tiles/) but not for bulk
downloads: keep the area small, or point --url at your own or a commercial tile source.
Map data (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import math
import os
import sys
import time
import urllib.request

TILE = 256
DEFAULT_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "UltimateMeshCore-tile-tool/1.0 (personal offline maps)"


def deg2tile(lat, lon, z):
    lat_r = math.radians(lat)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def to_rgb565(img):
    """PIL image -> big-endian RGB565 bytes."""
    img = img.convert("RGB").resize((TILE, TILE))
    out = bytearray(TILE * TILE * 2)
    i = 0
    for r, g, b in img.getdata():
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[i] = (v >> 8) & 0xFF
        out[i + 1] = v & 0xFF
        i += 2
    return bytes(out)


def save(dest_root, z, x, y, data):
    d = os.path.join(dest_root, str(z), str(x))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{y}.bin"), "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser(description="Make offline map tiles for the Ultimate MeshCore Client")
    ap.add_argument("--out", required=True, help="output folder, e.g. E:/maps (the card's /maps)")
    ap.add_argument("--bbox", help="lat1,lon1,lat2,lon2 area to cover")
    ap.add_argument("--zoom", default="11-14", help="zoom level or range, e.g. 10-14")
    ap.add_argument("--url", default=DEFAULT_URL, help="tile URL template with {z}/{x}/{y}")
    ap.add_argument("--from-dir", help="convert tiles already downloaded into <dir>/<z>/<x>/<y>.png instead of downloading")
    ap.add_argument("--delay", type=float, default=0.2, help="seconds between downloads (be kind to tile servers)")
    ap.add_argument("--max-tiles", type=int, default=4000, help="safety limit")
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        sys.exit("This tool needs Pillow:  pip install pillow")

    if "-" in args.zoom:
        z0, z1 = (int(v) for v in args.zoom.split("-"))
    else:
        z0 = z1 = int(args.zoom)

    jobs = []
    if args.from_dir:
        for z in range(z0, z1 + 1):
            zdir = os.path.join(args.from_dir, str(z))
            if not os.path.isdir(zdir):
                continue
            for xs in os.listdir(zdir):
                for name in os.listdir(os.path.join(zdir, xs)):
                    stem, ext = os.path.splitext(name)
                    if ext.lower() in (".png", ".jpg", ".jpeg"):
                        jobs.append((z, int(xs), int(stem), os.path.join(zdir, xs, name)))
    else:
        if not args.bbox:
            sys.exit("Give --bbox lat1,lon1,lat2,lon2 (or --from-dir)")
        lat1, lon1, lat2, lon2 = (float(v) for v in args.bbox.split(","))
        for z in range(z0, z1 + 1):
            x0, y0 = deg2tile(max(lat1, lat2), min(lon1, lon2), z)
            x1, y1 = deg2tile(min(lat1, lat2), max(lon1, lon2), z)
            for x in range(min(x0, x1), max(x0, x1) + 1):
                for y in range(min(y0, y1), max(y0, y1) + 1):
                    jobs.append((z, x, y, None))

    if len(jobs) > args.max_tiles:
        sys.exit(f"That would be {len(jobs)} tiles (limit {args.max_tiles}). Use a smaller area or fewer zoom levels.")

    print(f"{len(jobs)} tiles -> {args.out}  ({len(jobs) * TILE * TILE * 2 / 1e6:.1f} MB)")
    done = 0
    for z, x, y, path in jobs:
        try:
            if path:
                img = Image.open(path)
            else:
                url = args.url.format(z=z, x=x, y=y)
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=30) as r:
                    import io
                    img = Image.open(io.BytesIO(r.read()))
                time.sleep(args.delay)
            save(args.out, z, x, y, to_rgb565(img))
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(jobs)}")
        except Exception as e:
            print(f"  skipped {z}/{x}/{y}: {e}")
    print(f"Done: {done} tiles written. Put the card in the T-Deck and open the Map tab.")


if __name__ == "__main__":
    main()
