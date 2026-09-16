"""Starts the local server and opens the app window.

The window is Microsoft Edge / Google Chrome / Chromium in app mode (no address bar), with
its own profile so it stays a separate program; closing it quits the app. Without one of
those browsers the default browser is used and the app keeps running until Quit.
"""
import argparse
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

from aiohttp import web

from . import __version__
from .server import config_dir, make_app

DEFAULT_PORT = 47815


def find_browser():
    names = ["msedge", "chrome", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge", "brave-browser"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    if os.name == "nt":
        import winreg
        for exe in ("msedge.exe", "chrome.exe", "brave.exe"):
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        p = winreg.QueryValue(k, None)
                    if p and Path(p.strip('"')).exists():
                        return p.strip('"')
                except OSError:
                    pass
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if not base:
                continue
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe", r"Chromium\Application\chrome.exe"):
                p = Path(base) / rel
                if p.exists():
                    return str(p)
    return None


def port_in_use(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/desk/status", timeout=1.5) as r:
            return b'"version"' in r.read()
    except Exception:
        return False


def open_window(url, browser_only=False):
    """Returns the window process, or None when the default browser was used."""
    exe = None if browser_only else find_browser()
    if exe:
        profile = config_dir() / "window"
        args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
                "--window-size=1280,860", "--disable-features=Translate"]
        try:
            return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    webbrowser.open(url)
    return None


async def serve(port, url, browser_only, no_window):
    app = make_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"Ultimate MeshCore Desktop {__version__} on {url}", flush=True)
    if no_window:
        await asyncio.Event().wait()
    proc = open_window(url, browser_only)
    if proc is None:
        print("Opened in your browser. Close this program (or press Quit on the connection page) to stop.", flush=True)
        await asyncio.Event().wait()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, proc.wait)
    await app["state"].disconnect()
    await runner.cleanup()


def main():
    ap = argparse.ArgumentParser(prog="umc-desktop", description="Ultimate MeshCore Desktop")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="local port for the interface")
    ap.add_argument("--browser", action="store_true", help="use the default browser instead of an app window")
    ap.add_argument("--no-window", action="store_true", help="only run the server")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    if port_in_use(args.port):
        if already_running(args.port):
            open_window(url, args.browser)
            return
        sys.exit(f"Port {args.port} is in use by another program; start with --port <number>.")
    try:
        asyncio.run(serve(args.port, url, args.browser, args.no_window))
    except KeyboardInterrupt:
        pass
