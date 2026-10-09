#!/usr/bin/env python3
"""Builds Ultimate MeshCore Desktop for this computer (Windows or Linux).

    pip install -r requirements.txt pyinstaller pillow
    python build.py               # single program: dist/UltimateMeshCoreDesktop.exe or dist/ultimate-meshcore-desktop
    python build.py --installer   # Windows: dist/UltimateMeshCoreDesktop-Setup.exe (needs Inno Setup 6)
"""
import argparse
import os
import re
import shutil
import subprocess
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


def find_iscc():
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for rel in (r"Inno Setup 6\ISCC.exe", r"Programs\Inno Setup 6\ISCC.exe"):
            if base and (Path(base) / rel).exists():
                return str(Path(base) / rel)
    return None


def version():
    text = (PKG / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true", help="Windows installer (folder build + Inno Setup)")
    opts = ap.parse_args()
    web = PKG / "web"
    web.mkdir(exist_ok=True)
    shutil.copy(REPO / "web" / "umc" / "index.html", web / "index.html")
    make_icon()
    windows = sys.platform == "win32"
    if opts.installer and not windows:
        sys.exit("--installer is for Windows")
    name = "UltimateMeshCoreDesktop" if windows else "ultimate-meshcore-desktop"
    sep = os.pathsep
    args = [
        str(HERE / "run_umc_desktop.py"),
        "--name", name,
        "--onedir" if opts.installer else "--onefile",
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
    if not opts.installer:
        print("built", HERE / "dist" / (name + (".exe" if windows else "")))
        return
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup 6 not found (https://jrsoftware.org/isinfo.php)")
    subprocess.run([iscc, f"/DAppVersion={version()}", f"/DSourceDir={HERE / 'dist' / name}",
                    f"/DOutputDir={HERE / 'dist'}", str(HERE / "windows" / "installer.iss")], check=True)
    print("built", HERE / "dist" / "UltimateMeshCoreDesktop-Setup.exe")


if __name__ == "__main__":
    main()
