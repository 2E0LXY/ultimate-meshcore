"""Repeater over USB, and Ultimate MeshCore devices on the network."""
import asyncio
import json
import re

import aiohttp


class RepeaterSerialBackend:
    """Repeater / room server on USB. UMC firmware answers '@umc' bridge requests with the
    same JSON as its web API; other firmware gets a plain command line."""

    role = "repeater"

    def __init__(self, link):
        self.link = link
        self.bridge = False
        self.status = "connecting"
        self.plain = {}

    async def start(self):
        await self.link.open()
        self.link.on_close = self._on_close
        try:
            info = json.loads(await self.link.request("info", timeout=4))
            self.bridge = isinstance(info, dict)
        except Exception:
            self.bridge = False
        if not self.bridge:
            ver = await self.link.command("ver")
            if not ver:
                raise RuntimeError("no reply on this port - is it a MeshCore repeater or companion radio?")
            self.plain = {"ver": ver, "name": (await self.link.command("get name")).lstrip("> "),
                          "role": (await self.link.command("get role")).lstrip("> ") or "repeater",
                          "board": (await self.link.command("board")).lstrip("> ")}
        self.status = "connected"

    def _on_close(self, reason):
        self.status = f"disconnected ({reason})"

    async def close(self):
        await self.link.close()

    async def api(self, method, path, query, body):
        if self.status != "connected":
            return 503, {"error": "device not connected"}
        if path == "/api/login":
            return 200, {"token": "desktop"}
        if path == "/api/logout":
            return 200, {"ok": True}
        if path == "/api/info":
            if self.bridge:
                info = json.loads(await self.link.request("info"))
            else:
                p = self.plain
                info = {"fw": "MeshCore", "umc": p["ver"].lstrip("> v"), "api": 1, "name": p["name"], "role": p["role"].replace(" ", "_"),
                        "ver": p["ver"], "board": p["board"], "env": "", "setup": False, "default_pw": False,
                        "auth_required": False, "features": [], "net": {}}
            info["link"] = "usb"
            return 200, info
        if path == "/api/cli":
            out = []
            for line in body.decode("utf-8", "replace").split("\n"):
                line = line.strip()
                if not line:
                    continue
                if len(line) > 150:
                    out.append("Err - command too long for USB")
                elif self.bridge:
                    try:
                        out.extend(json.loads(await self.link.request("cli " + line, timeout=12)))
                    except asyncio.TimeoutError:
                        out.append("Err - no reply")
                else:
                    out.append(await self.link.command(line))
            return 200, out
        if path in ("/api/routes", "/api/traffic", "/api/scan"):
            if not self.bridge:
                return 200, {"routes": []} if path == "/api/routes" else {"rx_total": 0, "tx_total": 0, "packets": []} if path == "/api/traffic" else []
            req = path[5:] + (" refresh" if path == "/api/scan" and "refresh" in query else "")
            return 200, json.loads(await self.link.request(req, timeout=10))
        return 404, {"error": "not available over USB"}


class ProxyBackend:
    """An Ultimate MeshCore repeater or client on the network: everything is passed through."""

    role = "network"

    def __init__(self, base):
        base = base.strip()
        if not re.match(r"^https?://", base):
            base = "http://" + base
        self.base = base.rstrip("/")
        self.session = None
        self.status = "connecting"
        self.info = {}

    async def start(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120, connect=6))
        async with self.session.get(self.base + "/api/info") as r:
            if r.status != 200:
                raise RuntimeError(f"{self.base} answered HTTP {r.status}")
            self.info = await r.json(content_type=None)
        if self.info.get("fw") != "UMC":
            raise RuntimeError("that address isn't an Ultimate MeshCore device")
        self.status = "connected"

    async def close(self):
        if self.session:
            await self.session.close()

    async def forward(self, method, path_qs, body, headers):
        h = {k: v for k, v in headers.items() if k.lower() in ("x-auth-token", "content-type")}
        async with self.session.request(method, self.base + path_qs, data=body if body else None, headers=h) as r:
            return r.status, await r.read(), r.headers.get("Content-Type", "application/octet-stream")
