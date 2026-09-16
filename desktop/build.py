#!/usr/bin/env python3
"""Builds Ultimate MeshCore Desktop into a single program for this computer (Windows or Linux).

    pip install -r requirements.txt pyinstaller pillow
    python build.py

Output: dist/UltimateMeshCoreDesktop.exe (Windows) or dist/ultimate-meshcore-desktop (Linux).
"""
import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PKG = HERE / "umc_desktop"


def make_icon():
    """A simple app icon: radio waves on a blue tile."""
    from PIL import Image, ImageDraw
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, size - 8, size - 8], radius=48, fill=(11, 107, 203, 255))
    cx, cy = size // 2, size // 2 + 40
    for r in (40, 78, 116):
        d.arc([cx - r, cy - r, cx + r, cy + r], start=220, end=320, fill=(255, 255, 255, 255), width=14)
    d.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], fill=(255, 255, 255, 255))
    d.rectangle([cx - 6, cy, cx + 6, size - 40], fill=(255, 255, 255, 255))
    img.save(HERE / "icon.png")
    img.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    web = PKG / "web"
    web.mkdir(exist_ok=True)
    shutil.copy(REPO / "web" / "umc" / "index.html", web / "index.html")
    make_icon()
    windows = sys.platform == "win32"
    name = "UltimateMeshCoreDesktop" if windows else "ultimate-meshcore-desktop"
    sep = os.pathsep
    args = [
        str(HERE / "run_umc_desktop.py"),
        "--name", name,
        "--onefile",
        "--noconfirm",
        "--clean",
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
        "--paths", str(HERE),
        "--add-data", f"{PKG / 'static'}{sep}umc_desktop/static",
        "--add-data", f"{web}{sep}umc_desktop/web",
        "--collect-data", "esptool",
        "--collect-submodules", "esptool",
        "--collect-submodules", "bleak",
        "--icon", str(HERE / "icon.ico"),
    ]
    if windows:
        args += ["--windowed", "--collect-submodules", "winrt"]
    else:
        args += ["--collect-submodules", "dbus_fast"]
    PyInstaller.__main__.run(args)
    print("built", HERE / "dist" / (name + (".exe" if windows else "")))


if __name__ == "__main__":
    main()
