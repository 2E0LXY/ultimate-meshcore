"""Local web server: the connection page, and the Ultimate MeshCore web interface backed by
whichever radio is connected."""
import asyncio
import ipaddress
import json
import os
import socket
import time
from pathlib import Path

import aiohttp
from aiohttp import web

from . import __version__
from .backends import ProxyBackend, RepeaterSerialBackend, normalise_role
from .companion import CompanionBackend
from .flash import flash_app
from .omit import web as omit_web
from .omit.runtime import Runtime
from .links import (BleFrameLink, SerialFrameLink, SerialTextLink, TcpFrameLink, list_serial_ports, open_serial,
                    scan_ble)

HERE = Path(__file__).resolve().parent     # also inside the packaged app
STATIC = HERE / "static"


def config_dir():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
        d = base / "Ultimate MeshCore Desktop"
    else:
        d = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ultimate-meshcore-desktop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def index_html():
    for p in (HERE / "web" / "index.html", HERE.parent.parent / "web" / "umc" / "index.html"):
        if p.exists():
            html = p.read_text(encoding="utf-8")
            break
    else:
        return "<h1>Web interface files are missing</h1>"
    html = html.replace('<script data-dev-only src="mock.js"></script>', "")
    return inject(html)


def inject(html):
    tag = '<script src="/desk/shell.js"></script>'
    return html.replace("</body>", tag + "</body>") if "</body>" in html else html + tag


class State:
    def __init__(self):
        self.backend = None
        self.kind = ""
        self.label = ""
        self.target = {}
        self.busy = asyncio.Lock()
        self.note = ""
        self.recent_file = config_dir() / "recent.json"
        self.omit = Runtime(config_dir())             # chat, bot and dashboard (the radio attaches below)

    # ------------------------------------------------------------ recent connections
    def recent(self):
        try:
            return json.loads(self.recent_file.read_text())
        except Exception:
            return []

    def remember(self, target, label):
        items = [r for r in self.recent() if r.get("target") != target]
        items.insert(0, {"target": target, "label": label, "when": int(time.time())})
        try:
            self.recent_file.write_text(json.dumps(items[:8], indent=1))
        except Exception:
            pass

    # ------------------------------------------------------------ connect
    async def disconnect(self):
        self.omit.detach()
        if self.backend:
            try:
                await self.backend.close()
            except Exception:
                pass
        self.backend, self.kind, self.label = None, "", ""

    async def connect(self, target):
        await self.disconnect()
        t = target.get("type")
        if t == "usb":
            backend = await connect_serial(target["port"])
            self.kind = "usb-" + backend.role
            self.label = f"USB {target['port']}"
        elif t == "tcp":
            host = target["host"].strip()
            port = int(target.get("port") or 5000)

            async def reopen():
                link = TcpFrameLink(host, port)
                await link.open()
                return link

            backend = CompanionBackend(await reopen(), reconnect=reopen)
            await start_or_close(backend)
            self.kind, self.label = "tcp", f"WiFi app link {host}:{port}"
        elif t == "ble":
            addr, name = target["address"], target.get("name", "")

            async def reopen():
                link = BleFrameLink(addr, name)
                await link.open()
                return link

            backend = CompanionBackend(await reopen(), reconnect=reopen)
            await start_or_close(backend)
            self.kind, self.label = "ble", f"Bluetooth {name or addr}"
        elif t == "web":
            backend = ProxyBackend(target["host"])
            await start_or_close(backend)
            backend.role = normalise_role(backend.info.get("role"), "repeater")
            self.kind = "web-" + backend.role
            self.label = f"{backend.info.get('name', '')} · {backend.base.split('://', 1)[1]}"
        else:
            raise ValueError("unknown connection type")
        self.backend, self.target = backend, target
        if isinstance(backend, CompanionBackend) and backend.role == "companion":
            self.omit.attach(backend)                 # a client radio: the chat page can use it
        self.remember(target, self.label)


async def start_or_close(backend):
    try:
        await asyncio.wait_for(backend.start(), 30)
    except BaseException:
        try:
            await backend.close()
        except Exception:
            pass
        raise


async def wait_for_port(port, seconds=30):
    """Boards wired to the ESP32's own USB disappear while they restart."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if any(p["port"].lower() == str(port).lower() for p in list_serial_ports()):
            return True
        await asyncio.sleep(1)
    return False


async def connect_serial(port):
    """Companion radios answer an app-protocol query; repeaters answer the command line."""
    loop = asyncio.get_running_loop()

    async def reopen():
        l2 = SerialFrameLink(port)
        await l2.open()
        return l2

    # Opening the port restarts some boards (the T-Deck and other native-USB ones), so the
    # first hello can be lost while it starts up again. Give it a few goes.
    link = await reopen()
    companion = CompanionBackend(link, reconnect=reopen)
    try:
        await asyncio.wait_for(companion.start(), 60)
        return companion
    except Exception:
        companion.closed = True
        if companion.worker:
            companion.worker.cancel()
        try:
            await link.close()
        except Exception:
            pass
    await asyncio.sleep(0.4)
    ser = await loop.run_in_executor(None, open_serial, port)
    text = SerialTextLink(port, ser)
    rep = RepeaterSerialBackend(text)
    try:
        await rep.start()
    except Exception:
        await text.close()
        raise
    return rep


async def probe_app_port(ip, port, timeout=1.2):
    """Asks a MeshCore app port who it is, by speaking the companion protocol at it.

    Any MeshCore device with its app connection on TCP answers this, whatever firmware it
    runs, so a stock repeater or client is found as readily as one of ours."""
    try:
        fut = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(fut, timeout)
    except Exception:
        return None
    try:
        # CMD_APP_START: protocol version 3, six reserved bytes, then our name
        payload = bytes([1, 3, 0, 0, 0, 0, 0, 0]) + b"umc-desktop"
        writer.write(b"<" + len(payload).to_bytes(2, "little") + payload)
        await writer.drain()

        head = await asyncio.wait_for(reader.readexactly(3), timeout)
        if head[0:1] != b">":
            return None
        body = await asyncio.wait_for(reader.readexactly(int.from_bytes(head[1:3], "little")), timeout)
        if not body or body[0] != 5:          # RESP_CODE_SELF_INFO
            return None
        # byte 1 is the advert type: 1 chat node, 2 repeater, 3 room server
        kinds = {1: "companion", 2: "repeater", 3: "room_server", 4: "sensor"}
        name = body[58:].split(b"\x00")[0].decode("utf-8", "replace") if len(body) > 58 else ""
        return {"role": kinds.get(body[1], "companion"), "name": name}
    except Exception:
        return None
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def discover_network(port=80, app_port=5000):
    """Looks for MeshCore devices on this computer's local /24 network.

    Two ways in: our own firmware answers a web API on port 80, and any MeshCore device
    with a TCP app connection answers the companion protocol on port 5000. The first gives
    the web interface, the second gives full protocol control, and a device offering both
    is listed once with both noted."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 80))
        me = s.getsockname()[0]
        s.close()
    except OSError:
        return []
    net = ipaddress.ip_network(me + "/24", strict=False)
    found = {}
    sem = asyncio.Semaphore(64)
    timeout = aiohttp.ClientTimeout(total=1.5, connect=0.7)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def probe(ip):
            ip = str(ip)
            async with sem:
                try:
                    async with session.get(f"http://{ip}:{port}/api/info") as r:
                        if r.status == 200:
                            info = await r.json(content_type=None)
                            if info.get("fw") == "UMC":
                                found[ip] = {"host": ip, "name": info.get("name"),
                                             "role": normalise_role(info.get("role")),
                                             "board": info.get("board"), "version": info.get("umc"),
                                             "web": True, "app_port": None}
                except Exception:
                    pass
                me_too = await probe_app_port(ip, app_port)
                if me_too:
                    entry = found.get(ip, {"host": ip, "name": me_too["name"], "role": me_too["role"],
                                           "board": "", "version": "", "web": False})
                    entry["app_port"] = app_port
                    if not entry.get("name"):
                        entry["name"] = me_too["name"]
                    found[ip] = entry
        await asyncio.gather(*(probe(ip) for ip in net.hosts()))
    return sorted(found.values(), key=lambda d: tuple(int(p) for p in d["host"].split(".")))


def make_app():
    state = State()
    app = web.Application(client_max_size=16 * 1024 * 1024)

    def js(data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    async def root(request):
        if state.backend is None:
            raise web.HTTPFound("/connect")
        if isinstance(state.backend, ProxyBackend):
            status, body, ctype = await state.backend.forward("GET", "/", b"", request.headers)
            html = body.decode("utf-8", "replace")
            return web.Response(text=inject(html), content_type="text/html", headers={"Cache-Control": "no-store"})
        return web.Response(text=index_html(), content_type="text/html", headers={"Cache-Control": "no-store"})

    async def connect_page(request):
        return web.FileResponse(STATIC / "connect.html", headers={"Cache-Control": "no-store"})

    async def shell(request):
        return web.FileResponse(STATIC / "shell.js", headers={"Cache-Control": "no-store"})

    async def status(request):
        b = state.backend
        return js({"connected": b is not None, "kind": state.kind, "label": state.label, "version": __version__,
                   "state": getattr(b, "status", "") if b else "", "note": state.note})

    async def ports(request):
        return js(list_serial_ports())

    async def ble(request):
        try:
            return js(await scan_ble(float(request.query.get("seconds", "5"))))
        except Exception as err:
            return js({"error": f"Bluetooth scan failed: {err}"}, 500)

    async def discover(request):
        return js(await discover_network())

    async def recent(request):
        return js(state.recent())

    async def do_connect(request):
        target = await request.json()
        async with state.busy:
            try:
                await state.connect(target)
            except asyncio.TimeoutError:
                return js({"error": "the device didn't answer in time"}, 504)
            except Exception as err:
                return js({"error": str(err) or err.__class__.__name__}, 502)
        return js({"ok": True, "kind": state.kind, "label": state.label})

    async def do_disconnect(request):
        async with state.busy:
            await state.disconnect()
        return js({"ok": True})

    async def api(request):
        b = state.backend
        if b is None:
            return js({"error": "not connected"}, 503)
        body = await request.read()
        if isinstance(b, ProxyBackend):
            try:
                st, data, ctype = await b.forward(request.method, request.path_qs, body, request.headers)
            except Exception as err:
                return js({"error": f"device not reachable: {err}"}, 502)
            return web.Response(body=data, status=st, content_type=ctype.split(";")[0], headers={"Cache-Control": "no-store"})
        if request.path == "/api/ota":
            return await ota(b, body)
        try:
            st, data = await b.api(request.method, request.path, request.query, body)
        except Exception as err:
            return js({"error": str(err) or err.__class__.__name__}, 502)
        if request.path == "/api/cli" and isinstance(b, CompanionBackend) and b"reboot" in body:
            asyncio.create_task(rehandshake(b))
        return js(data, st)

    async def rehandshake(b):
        """USB-serial radios keep the port open across a restart: say hello again afterwards."""
        await asyncio.sleep(9)
        if state.backend is b and not b.closed:
            try:
                await b._handshake()
                b.boot += 1
            except Exception:
                pass

    async def ota(b, body):
        port = getattr(getattr(b, "link", None), "port", None)
        if not port:
            return js({"error": "Firmware can be installed over USB or WiFi. Over Bluetooth, connect the radio by USB (or use its web page on WiFi)."}, 400)
        async with state.busy:
            target, label = state.target, state.label
            await state.disconnect()
            state.label = f"Installing firmware on {port}…"
            state.note = "installing"
            try:
                await asyncio.get_running_loop().run_in_executor(None, flash_app, port, body)
            except Exception as err:
                state.note = ""
                asyncio.create_task(reconnect_later(target, 1))
                return js({"error": str(err)}, 400)
            state.note = "restarting"
            asyncio.create_task(reconnect_later(target, 5))
        return js({"ok": True, "reboot": True})

    async def reconnect_later(target, delay):
        await asyncio.sleep(delay)
        for _ in range(20):
            async with state.busy:
                if state.backend is not None:
                    break
                try:
                    await state.connect(target)
                    state.note = ""
                    return
                except Exception:
                    pass
            await asyncio.sleep(3)
        state.note = ""

    async def quit_app(request):
        asyncio.get_running_loop().call_later(0.3, lambda: os._exit(0))
        return js({"ok": True})

    omit_web.setup(app, state)
    app.router.add_get("/", root)
    app.router.add_get("/index.html", root)
    app.router.add_get("/connect", connect_page)
    app.router.add_get("/desk/shell.js", shell)
    app.router.add_get("/desk/status", status)
    app.router.add_get("/desk/ports", ports)
    app.router.add_get("/desk/ble", ble)
    app.router.add_get("/desk/discover", discover)
    app.router.add_get("/desk/recent", recent)
    app.router.add_post("/desk/connect", do_connect)
    app.router.add_post("/desk/disconnect", do_disconnect)
    app.router.add_post("/desk/quit", quit_app)
    app.router.add_static("/desk/static", STATIC)
    app.router.add_route("*", "/api/{tail:.*}", api)
    app["state"] = state
    return app
