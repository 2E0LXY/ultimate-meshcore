"""Companion radio backend: serves the web interface's /api/* from an app-protocol link.

Frames from the radio go to a numbered ring that the web page polls (/api/app), exactly as
on the device. Commands are sent one at a time so replies can't be confused. Ultimate
MeshCore Clients answer the desktop bridge command (full command line, routes, traffic and
WiFi scan); other companion radios get the common settings translated to app commands.
"""
import asyncio
import collections
import hashlib
import json
import random
import struct
import time

from .links import LinkClosed

CMD_APP_START, CMD_GET_TIME, CMD_SET_TIME, CMD_ADVERT = 1, 5, 6, 7
CMD_SET_NAME, CMD_SYNC, CMD_SET_RADIO, CMD_SET_TX, CMD_SET_LATLON = 8, 10, 11, 12, 14
CMD_REBOOT, CMD_SET_TUNING, CMD_DEVICE_QUERY, CMD_SET_PIN, CMD_SET_OTHER = 19, 21, 22, 37, 38
CMD_GET_TUNING, CMD_GET_STATS, CMD_SET_AUTOADD, CMD_GET_AUTOADD = 43, 56, 58, 59
CMD_SET_HASH_MODE, CMD_SET_SCOPE, CMD_GET_SCOPE, CMD_BRIDGE, CMD_GET_CHANNEL = 61, 63, 64, 112, 31

RESP_OK, RESP_ERR, RESP_CONTACTS_START, RESP_END_CONTACTS = 0, 1, 2, 4
RESP_NO_MORE = 10
MESSAGE_CODES = (7, 8, 16, 17)
PUSH_MSG_WAITING, PUSH_LOG_RX = 0x83, 0x88

APP_NAME = b"Ultimate MeshCore Desktop"
AUTOADD_BITS = {"chat": 0x02, "repeater": 0x04, "room": 0x08, "sensor": 0x10, "overwrite": 0x01}
TELEM = {0: "deny", 1: "contacts", 2: "all"}
TELEM_BACK = {v: k for k, v in TELEM.items()}
RING = 400
BOARD_ENV = {"heltec v3": "heltec_v3", "heltec v4": "heltec_v4_oled", "t-deck": "lilygo_tdeck", "lilygo t-deck": "lilygo_tdeck"}


class Job:
    def __init__(self, frame, kind, future=None):
        self.frame, self.kind, self.future = frame, kind, future


class CompanionBackend:
    role = "companion"

    def __init__(self, link, reconnect=None):
        self.link = link
        self.reconnect = reconnect          # async () -> new link, used after a restart
        self.ring = collections.deque(maxlen=RING)
        self.seq = 0
        self.boot = random.randint(1, 2**31)
        self.jobs = asyncio.Queue()
        self.current = None                 # job in flight
        self.reply_event = asyncio.Event()
        self.replies = []
        self.device = {}
        self.me = {}
        self.bridge = False
        self.sync_pending = False
        self.closed = False
        self.worker = None
        self.supervisor = None
        self.status = "connecting"

    # ------------------------------------------------------------ link plumbing
    def attach(self, link):
        self.link = link
        link.on_frame = self._on_frame
        link.on_close = self._on_close

    def _on_close(self, reason):
        self.status = f"disconnected ({reason})"
        if not self.closed and self.reconnect and self.supervisor is None:
            self.supervisor = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        delay = 2
        try:
            while not self.closed:
                await asyncio.sleep(delay)
                try:
                    link = await self.reconnect()
                    self.attach(link)
                    await self._handshake()
                    self.boot = random.randint(1, 2**31)   # the page reloads its lists
                    self.status = "connected"
                    return
                except Exception:
                    delay = min(delay * 2, 20)
        finally:
            self.supervisor = None

    def _on_frame(self, f):
        if not f:
            return
        code = f[0]
        job = self.current
        if code == PUSH_MSG_WAITING:
            self._queue_sync()
            return
        if code == PUSH_LOG_RX:
            return
        if code < 0x80 and job is not None:
            if job.kind == "sync":
                if code == RESP_NO_MORE:
                    self.replies.append(f)
                    self.reply_event.set()
                    return
                if code in MESSAGE_CODES:
                    self._store(f)
                    self.replies.append(f)
                    self.reply_event.set()
                    return
            elif job.kind == "backend":
                if code not in MESSAGE_CODES:
                    self.replies.append(f)
                    self.reply_event.set()
                    return
            else:
                self.replies.append(f)
                self.reply_event.set()
        self._store(f)

    def _store(self, f):
        self.seq += 1
        self.ring.append((self.seq, f.hex()))

    def _queue_sync(self):
        if not self.sync_pending:
            self.sync_pending = True
            self.jobs.put_nowait(Job(bytes([CMD_SYNC]), "sync"))

    # ------------------------------------------------------------ command worker
    async def _wait_reply(self, timeout, have=0):
        """Waits until more than `have` replies have arrived."""
        deadline = time.monotonic() + timeout
        while len(self.replies) <= have:
            self.reply_event.clear()
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            try:
                await asyncio.wait_for(self.reply_event.wait(), left)
            except asyncio.TimeoutError:
                return len(self.replies) > have
        return True

    async def _run(self):
        while not self.closed:
            job = await self.jobs.get()
            self.current = job
            self.replies = []
            try:
                if job.kind == "sync":
                    self.sync_pending = False
                    for _ in range(200):
                        self.replies = []
                        await self.link.send(job.frame)
                        if not await self._wait_reply(4) or self.replies[-1][0] == RESP_NO_MORE:
                            break
                elif job.kind == "backend":
                    await self.link.send(job.frame)
                    ok = await self._wait_reply(6)
                    if not job.future.done():
                        if ok:
                            job.future.set_result(self.replies[0])
                        else:
                            job.future.set_exception(TimeoutError("no reply from the radio"))
                else:   # a command from the web page: its replies go to the page
                    await self.link.send(job.frame)
                    contacts = job.frame[0] == 4
                    deadline = time.monotonic() + (25 if contacts else 4)
                    while time.monotonic() < deadline:
                        if not await self._wait_reply(max(0.05, deadline - time.monotonic()), len(self.replies) if self.replies else 0):
                            break
                        if not contacts or any(r[0] in (RESP_END_CONTACTS, RESP_ERR) for r in self.replies):
                            await asyncio.sleep(0.05)
                            break
            except LinkClosed as err:
                if job.future and not job.future.done():
                    job.future.set_exception(err)
            except Exception as err:
                if job.future and not job.future.done():
                    job.future.set_exception(err)
            finally:
                self.current = None

    async def cmd(self, frame, timeout=10):
        fut = asyncio.get_running_loop().create_future()
        await self.jobs.put(Job(bytes(frame), "backend", fut))
        return await asyncio.wait_for(fut, timeout)

    async def want(self, frame, code, size=1):
        r = await self.cmd(frame)
        if r[0] != code or len(r) < size:
            raise ValueError("not supported by this radio")
        return r

    async def ok(self, frame):
        r = await self.cmd(frame)
        if r[0] == RESP_ERR:
            raise ValueError({1: "not supported", 2: "not found", 3: "busy", 6: "invalid value"}.get(r[1] if len(r) > 1 else 0, "rejected"))
        return r

    # ------------------------------------------------------------ start
    async def start(self):
        self.attach(self.link)
        self.worker = asyncio.create_task(self._run())
        await self._handshake()
        self.status = "connected"

    async def _handshake(self):
        d = await self.cmd([CMD_DEVICE_QUERY, 8])
        if d[0] != 13:
            raise RuntimeError("this device doesn't answer as a MeshCore companion radio")
        self.device = parse_device_info(d)
        await self.refresh_self()
        try:
            info = await self.bridge_request("info")
            self.bridge = isinstance(json.loads(info), dict)
        except Exception:
            self.bridge = False
        self._queue_sync()   # messages that arrived while no app was connected

    async def refresh_self(self):
        r = await self.cmd(bytes([CMD_APP_START, 3, 0, 0, 0, 0, 0, 0]) + APP_NAME)
        self.me = parse_self_info(r)

    async def close(self):
        self.closed = True
        if self.worker:
            self.worker.cancel()
        if self.supervisor:
            self.supervisor.cancel()
        await self.link.close()

    # ------------------------------------------------------------ desktop bridge (UMC clients)
    async def bridge_request(self, req):
        r = await self.cmd(bytes([CMD_BRIDGE, 0]) + req.encode())
        if r[0] != CMD_BRIDGE:
            raise ValueError("no bridge")
        total = struct.unpack_from("<H", r, 1)[0]
        data = bytearray(r[5:])
        while len(data) < total:
            r = await self.cmd(bytes([CMD_BRIDGE, 1]) + struct.pack("<H", len(data)))
            if r[0] != CMD_BRIDGE or len(r) <= 5:
                raise ValueError("bridge read failed")
            data += r[5:]
        return data.decode("utf-8", "replace")

    async def bridge_cli(self, commands):
        out, batch = [], []

        async def flush():
            if batch:
                out.extend(json.loads(await self.bridge_request("cli " + "\n".join(batch))))
                batch.clear()

        for c in commands:
            if len(c.encode()) > 165:
                out.append("Err - command too long for this connection")
                continue
            if len(("\n".join(batch + [c])).encode()) > 165:
                await flush()
            batch.append(c)
        await flush()
        return out

    # ------------------------------------------------------------ web API
    async def api(self, method, path, query, body):
        if path == "/api/info":
            return 200, await self.info()
        if path == "/api/login":
            return 200, {"token": "desktop"}
        if path == "/api/logout":
            return 200, {"ok": True}
        if path == "/api/app" and method == "GET":
            since = int(query.get("since", "0") or 0)
            items = [x for x in self.ring if x[0] > since]
            out = items[:24]
            return 200, {"frames": [h for _, h in out], "boot": self.boot, "seq": out[-1][0] if out else self.seq,
                         "first": self.ring[0][0] if self.ring else self.seq + 1, "more": len(items) > 24}
        if path == "/api/app" and method == "POST":
            for line in body.decode().split("\n"):
                line = line.strip()
                if line:
                    await self.jobs.put(Job(bytes.fromhex(line), "page"))
            return 200, {"accepted": 1}
        if path == "/api/cli":
            cmds = [c for c in body.decode("utf-8", "replace").split("\n") if c.strip()]
            if self.bridge:
                return 200, await self.bridge_cli(cmds)
            return 200, [await self.emulate(c.strip()) for c in cmds]
        if path in ("/api/routes", "/api/traffic", "/api/scan"):
            if not self.bridge:
                return 200, {"routes": []} if path == "/api/routes" else {"rx_total": 0, "tx_total": 0, "packets": []} if path == "/api/traffic" else []
            req = path[5:] + (" refresh" if path == "/api/scan" and "refresh" in query else "")
            return 200, json.loads(await self.bridge_request(req))
        return 404, {"error": "not available over this connection"}

    async def info(self):
        if self.bridge:
            try:
                info = json.loads(await self.bridge_request("info"))
                info["link"] = self.link.kind
                return info
            except Exception:
                pass
        dev, me = self.device, self.me
        board = dev.get("model", "Companion radio")
        env = ""
        for k, v in BOARD_ENV.items():
            if board.lower().startswith(k):
                env = f"umc_{v}_client"
        return {"fw": "MeshCore", "umc": dev.get("version", "?").lstrip("v"), "api": 1, "name": me.get("name", "radio"), "role": "companion",
                "ver": dev.get("version", ""), "build": dev.get("build", ""), "board": board, "env": env, "commit": "",
                "setup": False, "default_pw": False, "auth_required": False, "features": [], "link": self.link.kind,
                "net": {"sta": {"mac": me.get("key", "")[:12]}}}

    # ------------------------------------------------------------ settings for other companion radios
    async def emulate(self, line):
        try:
            return await self._emulate(line)
        except ValueError as err:
            return f"Err - {err}"
        except Exception as err:
            return f"Err - {err}"

    async def _emulate(self, line):
        parts = line.split(" ", 2)
        verb = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""
        me, dev = self.me, self.device

        if verb == "get":
            if key in ("af", "rxdelay"):
                r = await self.want([CMD_GET_TUNING], 23, 9)
                rx, af = struct.unpack_from("<II", r, 1)
                return "> " + fmt_num((af if key == "af" else rx) / 1000)
            if key.startswith("autoadd."):
                r = await self.want([CMD_GET_AUTOADD], 25, 3)
                if key == "autoadd.maxhops":
                    return f"> {r[2]}"
                bit = AUTOADD_BITS.get(key[8:])
                return "> " + ("on" if bit and r[1] & bit else "off")
            if key == "scope":
                r = await self.want([CMD_GET_SCOPE], 28)
                return "> " + (r[1:32].split(b"\0")[0].decode() if len(r) > 1 else "-")
            if key == "contacts.count":
                return "> " + json.dumps({"contacts": "—", "max_contacts": dev.get("max_contacts"), "channels": "—",
                                          "max_channels": dev.get("max_channels"), "queued": 0})
            if key == "app.links":
                return "> " + json.dumps({"ble": {"present": self.link.kind == "ble", "on": True, "connected": self.link.kind == "ble"},
                                          "tcp": {"on": self.link.kind == "tcp", "port": 5000, "clients": 1 if self.link.kind == "tcp" else 0},
                                          "web": False, "queued": 0})
            await self.refresh_self()
            me = self.me
            simple = {
                "name": me.get("name"), "lat": fmt_num(me.get("lat", 0), 6), "lon": fmt_num(me.get("lon", 0), 6),
                "radio": f"{fmt_num(me['freq'])},{fmt_num(me['bw'])},{me['sf']},{me['cr']}" if "freq" in me else None,
                "tx": me.get("tx"), "multi.acks": me.get("multi_acks"), "advert.loc": "share" if me.get("advert_loc") else "none",
                "telemetry.base": TELEM.get(me.get("telem", 0) & 3), "telemetry.loc": TELEM.get((me.get("telem", 0) >> 2) & 3),
                "telemetry.env": TELEM.get((me.get("telem", 0) >> 4) & 3),
                "contacts.manual": "on" if me.get("manual_add", 0) & 1 else "off",
                "repeat": "on" if dev.get("repeat") else "off", "path.hash.mode": dev.get("path_hash_mode", 0),
                "ble.pin": dev.get("ble_pin", 0), "ble.activepin": "—", "public.key": me.get("key"), "role": "companion",
                "ble": "on", "app.tcp": "off", "update.status": "—", "umc.version": "—",
            }
            if key in simple and simple[key] is not None:
                return f"> {simple[key]}"
            if key == "net.status":
                return "> {}"
            return "Err - not available on this radio"

        if verb == "set":
            await self.refresh_self()
            me = self.me
            if key == "name":
                await self.ok(bytes([CMD_SET_NAME]) + value.encode()[:31])
            elif key in ("lat", "lon"):
                lat = float(value) if key == "lat" else me.get("lat", 0)
                lon = float(value) if key == "lon" else me.get("lon", 0)
                await self.ok(bytes([CMD_SET_LATLON]) + struct.pack("<ii", round(lat * 1e6), round(lon * 1e6)))
            elif key == "radio":
                f, bw, sf, cr = value.split(",")
                await self.ok(bytes([CMD_SET_RADIO]) + struct.pack("<II", round(float(f) * 1000), round(float(bw) * 1000))
                              + bytes([int(sf), int(cr), 1 if dev.get("repeat") else 0]))
            elif key == "repeat":
                on = value == "on"
                await self.ok(bytes([CMD_SET_RADIO]) + struct.pack("<II", round(me["freq"] * 1000), round(me["bw"] * 1000))
                              + bytes([me["sf"], me["cr"], 1 if on else 0]))
                self.device["repeat"] = on
            elif key == "tx":
                await self.ok(bytes([CMD_SET_TX, int(value) & 0xFF]))
            elif key in ("af", "rxdelay"):
                r = await self.want([CMD_GET_TUNING], 23, 9)
                rx, af = struct.unpack_from("<II", r, 1)
                if key == "af":
                    af = round(float(value) * 1000)
                else:
                    rx = round(float(value) * 1000)
                await self.ok(bytes([CMD_SET_TUNING]) + struct.pack("<II", rx, af) + bytes(8))
            elif key in ("multi.acks", "advert.loc", "contacts.manual") or key.startswith("telemetry."):
                manual = me.get("manual_add", 0)
                telem = me.get("telem", 0)
                loc = me.get("advert_loc", 0)
                acks = me.get("multi_acks", 0)
                if key == "multi.acks":
                    acks = int(value)
                elif key == "advert.loc":
                    loc = 1 if value == "share" else 0
                elif key == "contacts.manual":
                    manual = 1 if value == "on" else 0
                else:
                    shift = {"base": 0, "loc": 2, "env": 4}[key[10:]]
                    telem = (telem & ~(3 << shift)) | (TELEM_BACK[value] << shift)
                await self.ok(bytes([CMD_SET_OTHER, manual, telem, loc, acks]))
            elif key.startswith("autoadd."):
                r = await self.want([CMD_GET_AUTOADD], 25, 3)
                cfg, hops = r[1], r[2]
                if key == "autoadd.maxhops":
                    hops = min(int(value), 64)
                else:
                    bit = AUTOADD_BITS[key[8:]]
                    cfg = cfg | bit if value == "on" else cfg & ~bit
                await self.ok(bytes([CMD_SET_AUTOADD, cfg, hops]))
            elif key == "path.hash.mode":
                await self.ok(bytes([CMD_SET_HASH_MODE, 0, int(value)]))
                self.device["path_hash_mode"] = int(value)
            elif key == "scope":
                name = value.strip()
                if name in ("", "-", "none"):
                    await self.ok(bytes([CMD_SET_SCOPE]))
                else:
                    k = hashlib.sha256(("#" + name).encode()).digest()[:16]
                    await self.ok(bytes([CMD_SET_SCOPE]) + name.encode()[:30].ljust(31, b"\0") + k)
            elif key == "ble.pin":
                await self.ok(bytes([CMD_SET_PIN]) + struct.pack("<I", int(value)))
                self.device["ble_pin"] = int(value)
                return "OK - applies after reboot"
            else:
                return "Err - not available on this radio"
            return "OK"

        if line in ("advert", "advert.flood"):
            await self.ok(bytes([CMD_ADVERT, 1 if line == "advert.flood" else 0]))
            return "OK - advert sent"
        if line == "reboot":
            try:
                await self.link.send(bytes([CMD_REBOOT]) + b"reboot")
            except Exception:
                pass
            return "OK - rebooting"
        if line == "clock":
            r = await self.cmd([CMD_GET_TIME])
            t = struct.unpack_from("<I", r, 1)[0]
            return "> " + time.strftime("%H:%M - %d/%m/%Y UTC", time.gmtime(t))
        if verb == "time" and key:
            await self.ok(bytes([CMD_SET_TIME]) + struct.pack("<I", int(key)))
            return "OK - clock set"
        if line.startswith("stats-"):
            kind = {"stats-core": 0, "stats-radio": 1, "stats-packets": 2}.get(line)
            if kind is None:
                return "Err - unknown"
            try:
                r = await self.want([CMD_GET_STATS, kind], 24, 11)
            except ValueError:
                return "> {}"
            if kind == 0:
                mv, up, err, q = struct.unpack_from("<HIHB", r, 2)
                return "> " + json.dumps({"battery_mv": mv, "uptime_secs": up, "errors": err, "queue_len": q})
            if kind == 1:
                nf, rssi, snr, txa, rxa = struct.unpack_from("<hbbII", r, 2)
                return "> " + json.dumps({"noise_floor": nf, "last_rssi": rssi, "last_snr": snr / 4, "tx_air_secs": txa, "rx_air_secs": rxa})
            recv, sent = struct.unpack_from("<II", r, 2)
            return "> " + json.dumps({"recv": recv, "sent": sent})
        if line == "memory":
            return "> {}"
        if line == "ver":
            return f"> {dev.get('version', '')} (build {dev.get('build', '')})"
        if line == "board":
            return f"> {dev.get('model', '')}"
        return "Err - this radio doesn't support that command (Ultimate MeshCore Client does)"


def fmt_num(v, places=3):
    s = f"{v:.{places}f}".rstrip("0").rstrip(".")
    return s or "0"


def cstr(b):
    return b.split(b"\0")[0].decode("utf-8", "replace")


def parse_device_info(d):
    out = {"ver_code": d[1]}
    if len(d) >= 4:
        out["max_contacts"] = d[2] * 2
        out["max_channels"] = d[3]
    if len(d) >= 80:
        out["ble_pin"] = struct.unpack_from("<I", d, 4)[0]
        out["build"] = cstr(d[8:20])
        out["model"] = cstr(d[20:60])
        out["version"] = cstr(d[60:80])
    if len(d) >= 81:
        out["repeat"] = d[80] != 0
    if len(d) >= 82:
        out["path_hash_mode"] = d[81]
    return out


def parse_self_info(r):
    me = {"type": r[1], "tx": r[2], "max_tx": r[3], "key": r[4:36].hex()}
    lat, lon = struct.unpack_from("<ii", r, 36)
    me["lat"], me["lon"] = lat / 1e6, lon / 1e6
    me["multi_acks"], me["advert_loc"], me["telem"], me["manual_add"] = r[44], r[45], r[46], r[47]
    freq, bw = struct.unpack_from("<II", r, 48)
    me["freq"], me["bw"], me["sf"], me["cr"] = freq / 1000, bw / 1000, r[56], r[57]
    me["name"] = r[58:].decode("utf-8", "replace").rstrip("\0")
    return me
