#!/usr/bin/env python3
"""UMC Net dashboard: everything the broker, the repeaters and this server can tell you, in one page.

Reads the broker as a read-only 'monitor' account (its $SYS statistics and the meshcore/# topics), tails the
broker's log for who connects and who is refused, samples the machine, and serves a JSON API and the page on
127.0.0.1 for Caddy to put behind a login. Python standard library only: no packages to install.
"""
import base64, collections, csv, hashlib, hmac, io, json, os, re, secrets, shutil, socket, sqlite3, ssl, struct, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import umcnet_enrol as ENR
import umcnet_msgs as MSG

CFG = {
    "mqtt_host": os.environ.get("DASH_MQTT_HOST", "127.0.0.1"), "mqtt_port": int(os.environ.get("DASH_MQTT_PORT", "1884")),
    "mqtt_user": os.environ.get("DASH_MQTT_USER", "dash"), "mqtt_pass_file": os.environ.get("DASH_MQTT_PASS_FILE", "/opt/umcnet-dash/mqtt.pass"),
    "http_host": os.environ.get("DASH_HTTP_HOST", "127.0.0.1"), "http_port": int(os.environ.get("DASH_HTTP_PORT", "9102")),
    "data": os.environ.get("DASH_DATA", "/var/lib/umcnet-dash"), "users": os.environ.get("DASH_USERS", "/var/lib/umcnet-dash/accounts.json"),
    "unit": os.environ.get("DASH_UNIT", "umcnet-mosquitto"), "host": os.environ.get("DASH_HOST", "net.2e0lxy.uk"),
    "services": os.environ.get("DASH_SERVICES", "umcnet-mosquitto,caddy,umcnet-dash,umcnet-admin").split(","),
    "static": os.environ.get("DASH_STATIC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dash.html")),
    "public_static": os.environ.get("DASH_PUBLIC_STATIC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "public.html")),
    "logfile": os.environ.get("DASH_LOGFILE", ""), "ctl_pass_file": os.environ.get("DASH_CTL_PASS_FILE", "/opt/umcnet-dash/ctl.pass"),
    "ctl_user": os.environ.get("DASH_CTL_USER", "controller"), "admin_sock": os.environ.get("DASH_ADMIN_SOCK", "/run/umcnet-admin/admin.sock"),
    "keep_days": int(os.environ.get("DASH_KEEP_DAYS", "14")), "journal": os.environ.get("DASH_JOURNAL", "1") == "1",
}
LOCK = threading.RLock()
START = time.time()
VERSION = "2.18"

# ----------------------------------------------------------------------------- state
SYS = {}                                   # "$SYS/..." -> [value, ts]
DEV = {}                                   # device id -> dict
PKTS = collections.deque(maxlen=400)       # recent packets, newest last
HEARD = collections.OrderedDict()          # packet hash -> {"t", "devs": {id: ts}, "type"}
PAIRS = collections.Counter()              # (a, b) -> packets both heard
CLIENTS = {}                               # client id -> dict (from the broker's log)
EVENTS = collections.deque(maxlen=600)     # connections, refusals, denials
LOG = collections.deque(maxlen=400)        # raw broker log lines
COUNT = collections.Counter()              # totals since this service started
RATE = collections.defaultdict(lambda: collections.deque(maxlen=4000))   # name -> timestamps
MQTT = {"state": "starting", "since": 0, "reconnects": 0, "error": ""}
LATENCY = collections.deque(maxlen=300)    # seconds between a device's timestamp and our clock
DB = None

NODES = {}                                 # full public key -> what its adverts said about it (name, kind, position)
LINKS = {}                                 # (hearing device, heard node) -> counts, nearest hop count, signal
JOURNEYS = collections.deque(maxlen=300)   # recent packets as a chain: sender, repeaters on the way, receiver
PTYPES = {0: "REQ", 1: "RESP", 2: "MSG", 3: "ACK", 4: "ADVERT", 5: "CHAN", 6: "CHDATA", 7: "ANON", 8: "PATH", 9: "TRACE", 10: "MULTI", 11: "CTRL"}
DEVICE_SETTING_KEYS = (
    "radio", "tx", "dutycycle", "radio.rxgain", "agc.reset.interval", "cad",
    "repeat", "loop.detect", "flood.max", "flood.max.unscoped", "flood.max.advert",
    "group.hops.max", "multi.acks", "txdelay", "direct.txdelay", "advert.interval",
    "flood.advert.interval", "name", "lat", "lon", "owner.info", "mqtt.iata", "mqtt.raw",
    "mqtt.tx", "mqtt.custom.bridge", "mqtt.custom.rate", "powersaving",
)
STATUS_SETTING_KEYS = ("update.status", "update.auto", "update.interval", "build", "ota.state")
PUBLIC_SETTING_KEYS = tuple(k for k in DEVICE_SETTING_KEYS if k not in ("lat", "lon", "owner.info"))
SETTINGS = {}                              # device id -> values, update time and preload state

# ----------------------------------------------------------------------------- packets
def parse_packet(raw):
    """What a packet says about itself, without decrypting anything (same layout the radios use)."""
    try:
        if not raw: return None
        h = raw[0]; route = h & 3; ptype = (h >> 2) & 15; i = 1
        if route in (0, 3): i += 4
        pl = raw[i]; i += 1
        count, size = pl & 63, (pl >> 6) + 1
        if size > 3 or i + count * size > len(raw): return None
        path = [raw[i + k * size: i + (k + 1) * size].hex().upper() for k in range(count)]
        i += count * size; p = raw[i:]
        out = {"type": PTYPES.get(ptype, "RAW"), "flood": route in (0, 1), "hops": count, "path": path, "via": path[-1] if path else "", "src": "", "dst": "", "chan": "", "key": "", "name": ""}
        if ptype in (0, 1, 2, 8) and len(p) >= 2: out["dst"], out["src"] = "%02X" % p[0], "%02X" % p[1]
        elif ptype in (5, 6) and p: out["chan"] = "%02X" % p[0]
        elif ptype == 4 and len(p) > 100:
            out["key"] = p[:4].hex().upper(); out["fkey"] = p[:32].hex().upper(); j = 100; f = p[j]; j += 1
            out["atype"] = f & 0x0F
            if f & 0x10:
                if j + 8 <= len(p):
                    la, lo = struct.unpack("<ii", p[j:j + 8]); la, lo = la / 1e6, lo / 1e6
                    if (la or lo) and abs(la) <= 90 and abs(lo) <= 180: out["lat"], out["lon"] = la, lo
                j += 8
            if f & 0x20: j += 2
            if f & 0x40: j += 2
            if f & 0x80 and j < len(p): out["name"] = p[j:].decode("utf-8", "replace").rstrip("\0").strip()
        return out
    except Exception:
        return None

def node_for_hash(h):
    """The one known node whose key starts with this hash, or None when it fits none or several."""
    if not h: return None
    hits = [k for k in NODES if k.startswith(h.upper())]
    return hits[0] if len(hits) == 1 else None

def hop_name(h):
    k = node_for_hash(h)
    return (NODES[k]["name"] or h) if k else h

def note_network(did, info, snr, rssi, now):
    """Called for every packet a connected repeater heard: learn the node behind an advert, and the link to it."""
    if not info: return
    sender = None
    if info.get("fkey"):
        k = info["fkey"]; n = NODES.get(k)
        if n is None:
            if len(NODES) >= 3000: return
            n = NODES[k] = {"key": k, "name": "", "type": 0, "lat": None, "lon": None, "first": now, "last": 0, "adverts": 0}
        n["last"] = now; n["adverts"] += 1
        if info.get("name"): n["name"] = info["name"]
        if info.get("atype"): n["type"] = info["atype"]
        if info.get("lat") is not None: n["lat"], n["lon"] = info["lat"], info["lon"]
        sender = k
        try: decoded_advert(did, n, info, snr, now)
        except Exception as e: sys.stderr.write("advert copy: %s\n" % e)
    elif info.get("src"): sender = node_for_hash(info["src"])
    if sender and sender != did:
        l = LINKS.get((did, sender))
        if l is None: l = LINKS[(did, sender)] = {"n": 0, "hops_min": 99, "hops_last": 0, "snr": None, "rssi": None, "first": now, "last": 0, "types": collections.Counter()}
        l["n"] += 1; l["hops_min"] = min(l["hops_min"], info["hops"]); l["hops_last"] = info["hops"]; l["last"] = now; l["types"][info["type"]] += 1
        try:
            if snr is not None and (l["snr"] is None or float(snr) > l["snr"]): l["snr"] = float(snr)
            if rssi is not None and (l["rssi"] is None or int(rssi) > l["rssi"]): l["rssi"] = int(rssi)
        except (ValueError, TypeError): pass
    if sender or info.get("path"):
        JOURNEYS.append({"t": now, "pkt": info.get("pkt"), "size": info.get("size"), "type": info["type"], "flood": info["flood"], "hops": info["hops"], "from": sender or (info.get("src") or info.get("chan") or ""), "path": [{"h": h, "n": hop_name(h)} for h in info.get("path", [])], "to": did, "snr": snr, "rssi": rssi})

def packet_routes(limit=40):
    """One row per packet: when, type, size, the first repeater that heard it, how many repeaters heard it,
    the route it took (the first copy's hops, named) and who sent it to whom. Like the LetsMesh analyzer's table."""
    groups = collections.OrderedDict()
    for j in list(JOURNEYS):
        if not j.get("pkt"): continue
        g = groups.get(j["pkt"])
        if g is None:
            g = groups[j["pkt"]] = {"pkt": j["pkt"], "t": j["t"], "type": j["type"], "size": j.get("size"), "first": j["to"],
                                    "from": j["from"], "heard": 0, "path": j["path"], "hops": j["hops"], "seen_by": set()}
        g["heard"] += 1; g["seen_by"].add(j["to"]); g["t"] = max(g["t"], j["t"])
    rows = []
    for g in list(groups.values())[::-1][:limit]:
        def nm(dev):
            d = DEV.get(dev); return (d["name"] if d and d["name"] else dev[:8])
        rows.append({"pkt": g["pkt"], "t": g["t"], "type": g["type"], "size": g["size"], "first": nm(g["first"]),
                     "heard": g["heard"], "route": [{"h": h["h"], "n": h["n"]} for h in g["path"]], "from": g["from"], "to": nm(g["first"]), "hops": g["hops"]})
    return rows

def nodes_path(): return os.path.join(CFG["data"], "nodes.json")
def nodes_save():
    try:
        with LOCK: data = {"nodes": NODES, "links": [{"r": a, "s": b, **{k: v for k, v in l.items() if k != "types"}, "types": dict(l["types"])} for (a, b), l in LINKS.items()]}
        tmp = nodes_path() + ".tmp"; json.dump(data, open(tmp, "w")); os.replace(tmp, nodes_path())
    except Exception as e: sys.stderr.write("nodes: %s\n" % e)
def nodes_load():
    try: d = json.load(open(nodes_path()))
    except Exception: return
    NODES.update(d.get("nodes", {}))
    for l in d.get("links", []):
        LINKS[(l["r"], l["s"])] = {"n": l["n"], "hops_min": l["hops_min"], "hops_last": l.get("hops_last", 0), "snr": l.get("snr"), "rssi": l.get("rssi"), "first": l.get("first", 0), "last": l["last"], "types": collections.Counter(l.get("types", {}))}

def device_info(d, now):
    """What the dashboard knows about a connected repeater, for its popup on the map."""
    st = d.get("stats") or {}; sv = (SETTINGS.get(d["id"]) or {}).get("values", {}); br = d.get("bridge") or {}
    strip = lambda v: str(v or "").lstrip("> ").strip()
    return {"id": d["id"], "name": d["name"], "area": d["area"], "board": d.get("model", ""), "fw": d.get("fw", ""), "client": d.get("client", ""), "radio": d.get("radio", ""), "repeat": d.get("repeat", ""), "status": d.get("status", ""),
            "first": d.get("first", 0), "last": d.get("last", 0), "skew": d.get("skew"), "pm": round(rate_per_min("pkt:" + d["id"], 300), 2), "n_rx": d.get("n_rx", 0), "n_tx": d.get("n_tx", 0), "rssi": d.get("rssi"), "snr": d.get("snr"),
            "stats": {k: st.get(k) for k in ("battery_mv", "uptime_secs", "noise_floor", "tx_air_secs", "rx_air_secs", "recv_errors", "n_sent_flood", "n_sent_direct", "n_recv_flood", "n_recv_direct", "total_up_time_secs", "queue_len", "errors") if k in st} or dict(st),
            "bridge": br, "types": dict(d.get("types") or {}), "build": strip(sv.get("build")), "update": strip(sv.get("update.status")), "tx_power": strip(sv.get("tx")), "advert_every": strip(sv.get("advert.interval")), "flood_advert_every": strip(sv.get("flood.advert.interval")),
            "flood_max": strip(sv.get("flood.max")), "bridge_on": strip(sv.get("mqtt.custom.bridge")).split(",")[0], "include_tx": strip(sv.get("mqtt.tx")), "has_key": d["id"] in KEYS}

def network_view(hours=24):
    now = time.time(); cutoff = now - max(1.0, float(hours)) * 3600
    with LOCK:
        nodes = []; seen = set()
        for k, n in NODES.items():
            d = DEV.get(k); seen.add(k)
            conn = bool(d and d["last"] and now - d["last"] < CONF["stale_minutes"] * 60)
            if not conn and n["last"] < cutoff: continue                       # not on the network and not heard lately: not on the map
            nodes.append({"key": k, "name": (d["name"] if d and d["name"] else n["name"]) or k[:8], "type": n["type"], "lat": n["lat"], "lon": n["lon"], "last": n["last"], "first": n.get("first", 0), "adverts": n["adverts"], "connected": conn,
                          "online": conn and (d.get("status") != "offline"), "info": device_info(d, now) if d else None})
        for k, d in DEV.items():
            if k not in seen:
                conn = bool(d["last"] and now - d["last"] < CONF["stale_minutes"] * 60)
                if conn: nodes.append({"key": k, "name": d["name"] or k[:8], "type": 2, "lat": d.get("lat"), "lon": d.get("lon"), "last": d["last"], "first": d.get("first", 0), "adverts": 0, "connected": True, "online": d.get("status") != "offline", "info": device_info(d, now)})
        for n in nodes:                                       # a connected repeater's position may come from the control channel
            d = DEV.get(n["key"])
            if d and n["lat"] is None and d.get("lat") is not None: n["lat"], n["lon"] = d["lat"], d["lon"]
        # one station, one dot: a reflashed or replaced station comes back with a new key under the same name; show the newest
        # (and always the repeater that is on this network), not every identity it ever had
        out, names = [], set()
        for n in sorted(nodes, key=lambda x: (not x.get("info"), -(x["last"] or 0))):
            nm = (n["name"] or "").strip().lower()
            if nm and nm in names and not n.get("info"): continue
            if nm and n["name"] != n["key"][:8]: names.add(nm)
            out.append(n)
        nodes = out
        keep = {n["key"] for n in nodes}
        links = [{"recv": a, "node": b, "hops": l["hops_min"], "hops_last": l["hops_last"], "n": l["n"], "snr": l["snr"], "rssi": l["rssi"], "first": l["first"], "last": l["last"], "types": dict(l["types"])} for (a, b), l in LINKS.items() if a in keep and b in keep]
        journeys = [dict(j) for j in list(JOURNEYS)[-80:]][::-1]
    return {"now": now, "hours": hours, "nodes": nodes, "links": links, "journeys": journeys, "confirmed": confirmed_links()}

def locate_loop():
    """Ask each repeater that has a control key where it is, until we know (for the map)."""
    time.sleep(120)
    while True:
        try:
            for dev in list(KEYS):
                d = DEV.get(dev); n = NODES.get(dev)
                if not d or not d["last"] or time.time() - d["last"] > 600 or d.get("lat") is not None or (n and n["lat"] is not None): continue
                got = {}
                for axis in ("lat", "lon"):
                    r = send_command(dev, "get " + axis, "locator", timeout=10)
                    try: got[axis] = float(str(r.get("reply", "")).lstrip("> ").strip()) if r.get("ok") else None
                    except ValueError: got[axis] = None
                if got.get("lat") and got.get("lon") and abs(got["lat"]) <= 90 and abs(got["lon"]) <= 180: d["lat"], d["lon"] = got["lat"], got["lon"]
        except Exception as e: sys.stderr.write("locate: %s\n" % e)
        time.sleep(1200)

def note_rate(name, n=1):
    now = time.time()
    with LOCK:
        d = RATE[name]
        for _ in range(n): d.append(now)

def rate_per_min(name, window=60):
    now = time.time()
    with LOCK:
        d = RATE[name]
        while d and d[0] < now - 3600: d.popleft()
        return sum(1 for t in d if t >= now - window) * 60.0 / window

def device(did, area=""):
    d = DEV.get(did)
    if d is None:
        d = DEV[did] = {"id": did, "area": area, "name": "", "first": time.time(), "last": 0, "last_status": 0, "status": "unknown", "model": "", "fw": "", "radio": "", "client": "", "repeat": "",
                        "stats": {}, "n_raw": 0, "n_pkt": 0, "n_rx": 0, "n_tx": 0, "types": collections.Counter(), "rssi": None, "snr": None, "bytes": 0, "skew": None, "topics": collections.Counter()}
    if area: d["area"] = area
    return d

def on_publish(topic, payload, retained=False):
    now = time.time()
    if topic.startswith("$SYS/"):
        with LOCK: SYS[topic] = [payload.decode("utf-8", "replace"), now]
        return
    m = re.match(r"^meshcore/([^/]+)/([0-9A-Fa-f]{64})/(raw|packets|status)$", topic)
    COUNT["messages"] += 1; note_rate("messages")
    if not m:
        COUNT["other_topics"] += 1; return
    area, did, kind = m.group(1), m.group(2).upper(), m.group(3)
    if did == DASH_ID: return                       # the dashboard's own messages on their way to the repeaters: not a repeater
    try: j = json.loads(payload.decode("utf-8", "replace"))
    except Exception: COUNT["bad_json"] += 1; return
    with LOCK:
        d = device(did, area)
        if not retained: d["last"] = now; d["topics"][kind] += 1
        if j.get("origin"): d["name"] = j["origin"]
        ts = j.get("timestamp")
        if isinstance(ts, str) and not retained:
            try:
                import datetime
                t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp(); d["skew"] = round(now - t, 1); LATENCY.append(now - t)
            except Exception: pass
        if kind == "status":
            if not retained: d["last_status"] = now
            d["status"] = j.get("status", "unknown"); d["status_retained"] = retained
            for k_src, k_dst in (("model", "model"), ("firmware_version", "fw"), ("radio", "radio"), ("client_version", "client"), ("repeat", "repeat")):
                if j.get(k_src) is not None: d[k_dst] = j[k_src]
            if isinstance(j.get("stats"), dict): d["stats"] = j["stats"]
            return
        if kind == "raw": d["n_raw"] += 1
        else: d["n_pkt"] += 1
        raw_hex = j.get("data") if kind == "raw" else j.get("raw")
        try: raw = bytes.fromhex(raw_hex) if raw_hex else b""
        except ValueError: raw = b""
        info = parse_packet(raw) or {}
        try:
            info["pkt"] = hashlib.sha1(MSG.parse_wire(raw)["payload"]).hexdigest()[:12] if raw and MSG.parse_wire(raw) else None
        except Exception: info["pkt"] = None
        info["size"] = len(raw)
        direction = j.get("direction", "rx") if kind == "packets" else "rx"
        # a device that publishes both topics is counted once: count 'packets', and 'raw' only when no packets arrive
        counted = kind == "packets" or d["n_pkt"] == 0
        if counted:
            d["n_tx" if direction == "tx" else "n_rx"] += 1; note_rate("pkt:" + did); note_rate("packets")
            d["types"][info.get("type") or ("T%s" % j.get("packet_type", "?"))] += 1; d["bytes"] += len(raw)
            try: d["rssi"] = int(j["RSSI"]) if "RSSI" in j else d["rssi"]; d["snr"] = float(j["SNR"]) if "SNR" in j else d["snr"]
            except (ValueError, TypeError): pass
            if direction == "rx" and raw:
                note_network(did, info, j.get("SNR"), j.get("RSSI"), now)
                try: note_message(did, raw, j.get("SNR"), j.get("RSSI"), now)
                except Exception as e: sys.stderr.write("message: %s\n" % e)
                h = hashlib.sha1(raw).hexdigest()[:16]
                e = HEARD.get(h)
                if e is None: e = HEARD[h] = {"t": now, "devs": {}, "type": info.get("type", "?")}; note_rate("unique")
                if did not in e["devs"]:
                    for other in e["devs"]: PAIRS[tuple(sorted((did, other)))] += 1
                    e["devs"][did] = now
                while HEARD and next(iter(HEARD.values()))["t"] < now - 900: HEARD.popitem(last=False)
            PKTS.append({"t": now, "area": area, "dev": did, "dname": d["name"], "dir": direction, "type": info.get("type") or "T%s" % j.get("packet_type", "?"), "flood": info.get("flood", j.get("route") == "F"),
                         "hops": info.get("hops", 0), "via": info.get("via", ""), "src": info.get("src", ""), "dst": info.get("dst", ""), "chan": info.get("chan", ""), "key": info.get("key", ""), "name": info.get("name", ""),
                         "len": len(raw) or j.get("len"), "rssi": j.get("RSSI"), "snr": j.get("SNR"), "k": kind})

# ----------------------------------------------------------------------------- MQTT client (3.1.1, QoS 0, just enough to listen)
def _rl(n):
    out = bytearray()
    while True:
        b = n % 128; n //= 128
        if n: b |= 128
        out.append(b)
        if not n: return bytes(out)

def _s(x): x = x.encode(); return struct.pack(">H", len(x)) + x

class MqttConn:
    """A minimal MQTT 3.1.1 client (QoS 0): enough to listen to some topics and publish a few messages."""
    def __init__(self, user, pass_file, subs, on_msg, status):
        self.user, self.pass_file, self.subs, self.on_msg, self.status = user, pass_file, subs, on_msg, status
        self.sock = None; self.lock = threading.Lock(); self.up = False; self.error = ""
        status.update(state="starting", since=0, reconnects=0, error="")

    def publish(self, topic, payload, retain=False):
        body = _s(topic) + payload
        with self.lock: self.sock.sendall(bytes([0x31 if retain else 0x30]) + _rl(len(body)) + body)

    def run(self):
        backoff = 2
        while True:
            try:
                pw = open(self.pass_file).read().strip()
                s = socket.create_connection((CFG["mqtt_host"], CFG["mqtt_port"]), timeout=10); s.settimeout(40)
                vh = _s("MQTT") + bytes([4, 0xC2]) + struct.pack(">H", 60)
                body = vh + _s("umcnet-%s-%d" % (self.user, os.getpid())) + _s(self.user) + _s(pw)
                s.sendall(bytes([0x10]) + _rl(len(body)) + body)
                ack = s.recv(4)
                if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0: raise RuntimeError("the broker refused the %s account (code %s)" % (self.user, ack[3] if len(ack) >= 4 else "?"))
                subs = b"".join(_s(t) + b"\x00" for t in self.subs)
                s.sendall(bytes([0x82]) + _rl(2 + len(subs)) + b"\x00\x01" + subs)
                self.sock = s; self.up = True; self.error = ""
                self.status.update(state="connected", since=time.time(), error=""); backoff = 2
                buf = b""; last_ping = time.time()
                while True:
                    if time.time() - last_ping > 30:
                        with self.lock: s.sendall(b"\xc0\x00")
                        last_ping = time.time()
                    try: chunk = s.recv(65536)
                    except socket.timeout: continue
                    if not chunk: raise RuntimeError("the broker closed the connection")
                    buf += chunk
                    while len(buf) >= 2:
                        mult, ln, i = 1, 0, 1
                        while True:
                            if i >= len(buf): break
                            b = buf[i]; ln += (b & 127) * mult; mult *= 128; i += 1
                            if not b & 128: break
                        else: break
                        if i > len(buf) or len(buf) < i + ln: break
                        first = buf[0]; typ, pkt, buf = first >> 4, buf[i:i + ln], buf[i + ln:]
                        if typ == 3:
                            tl = struct.unpack(">H", pkt[:2])[0]; topic = pkt[2:2 + tl].decode("utf-8", "replace"); self.on_msg(topic, pkt[2 + tl:], bool(first & 1))
            except Exception as e:
                self.up = False; self.error = str(e); self.status.update(state="disconnected", error=str(e)); self.status["reconnects"] = self.status.get("reconnects", 0) + 1
                time.sleep(backoff); backoff = min(60, backoff * 2)

def mqtt_loop():
    MqttConn(CFG["mqtt_user"], CFG["mqtt_pass_file"], ["$SYS/#", "meshcore/#"], on_publish, MQTT).run()

CTL_STATUS = {}
def control_loop():
    if not os.path.exists(CFG["ctl_pass_file"]):
        CTL_STATUS.update(state="not set up", error="no control account yet: run install-dash.sh again"); return
    CTL["conn"] = MqttConn(CFG["ctl_user"], CFG["ctl_pass_file"], ["umcnet/v1/+/dev/+/resp", "umcnet/v1/enrol/hello"], on_control_reply, CTL_STATUS)
    CTL["conn"].run()

# ----------------------------------------------------------------------------- broker log: who connects, who is refused
RX_NEW = re.compile(r"New client connected from (\S+?)(?::(\d+))? as (.+?) \(p(\d), c(\d), k(\d+)(?:, u'(.*)')?\)")
RX_CLOSE = re.compile(r"Client (.+?) (closed its connection|disconnected|has exceeded timeout, disconnecting|already connected, closing old connection)")
RX_DENY = re.compile(r"Denied (PUBLISH|SUBSCRIBE|UNSUBSCRIBE) from (.+?) \((?:.*?)'([^']*)'")
RX_DENY2 = re.compile(r"Denied (PUBLISH|SUBSCRIBE|UNSUBSCRIBE) from (.+?)[ (]")
RX_AUTH = re.compile(r"(?:Client (.+?) disconnected, not authorised|Client <unknown> disconnected|bad user name or password|not authorised|CONNACK.*(?:4|5))")
RX_FROM = re.compile(r"from (\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+)(?::\d+)?")

def event(kind, text, client="", user="", ip="", at=None):
    e = {"t": at or time.time(), "kind": kind, "text": text, "client": client, "user": user, "ip": ip}
    with LOCK: EVENTS.append(e); COUNT["ev:" + kind] += 1
    if DB:
        try: DB.execute("INSERT INTO events(ts,kind,client,user,ip,text) VALUES(?,?,?,?,?,?)", (int(e["t"]), kind, client, user, ip, text[:300])); DB.commit()
        except Exception: pass

LAST_IP = [""]
RX_CONN = re.compile(r"New connection from (\S+?)(?::\d+)? on port")

def handle_log(line, at=None):
    at = at or time.time()
    with LOCK: LOG.append({"t": at, "line": line})
    m = RX_CONN.search(line)
    if m: LAST_IP[0] = m.group(1); return                    # a login attempt: the refusal, if any, is the next line
    m = RX_NEW.search(line)
    if m:
        ip, port, cid, ver, clean, keep, user = m.groups()
        with LOCK:
            c = CLIENTS.setdefault(cid, {"client": cid, "connects": 0, "first": at})
            c.update(user=user or "", ip=ip, port=port or "", since=at, state="connected", proto=int(ver), keepalive=int(keep), clean=bool(int(clean)), last=at); c["connects"] += 1
            c.setdefault("history", collections.deque(maxlen=60)).append(at)
        event("connect", "connected from %s as %s" % (ip, user or "?"), cid, user or "", ip, at); return
    m = RX_DENY.search(line) or RX_DENY2.search(line)
    if m:
        cid = m.group(2); topic = m.group(3) if m.lastindex and m.lastindex >= 3 else ""
        with LOCK: c = CLIENTS.get(cid, {})
        event("denied", "%s %s refused by the access list" % (m.group(1).lower(), topic), cid, c.get("user", ""), c.get("ip", "")); return
    if "not authorised" in line or "bad user name" in line:
        ip = LAST_IP[0]; cid = re.search(r"Client (.+?) ", line)
        event("auth_fail", "login refused" + (" from " + ip if ip else ""), cid.group(1) if cid else "", "", ip, at); return
    m = RX_CLOSE.search(line)
    if m:
        cid, why = m.group(1), m.group(2)
        with LOCK:
            c = CLIENTS.get(cid)
            if c and "already connected" in why:       # the same client id came back: the next 'disconnected' is its old, stale session
                c["takeover"] = True; return
            if c and c.pop("takeover", False): return   # the broker logs: "already connected, closing old" -> "New client connected" -> "closed its connection" (the old one)
            if c: c["state"] = "disconnected"; c["last"] = at; c["why"] = why
        event("timeout" if "timeout" in why else "disconnect", why, cid, (c or {}).get("user", ""), (c or {}).get("ip", ""), at); return
    if re.search(r"\b(Error|error|Warning|warning)\b", line): event("warn", line[:200], at=at)

RX_JLINE = re.compile(r"^(\d+\.\d+) \S+ [^:]+: (.*)$")

def replay_journal():
    """Rebuild who is connected from the broker's log of the last week, so a restart of the dashboard forgets nothing."""
    try:
        out = subprocess.run(["journalctl", "-u", CFG["unit"], "--since", "-7 days", "-o", "short-unix", "--no-pager"], capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        event("warn", "cannot replay the broker log: %s" % e); return
    for line in out.splitlines():
        m = RX_JLINE.match(line)
        if m: handle_log(m.group(2), float(m.group(1)))

def journal_loop():
    if not CFG["journal"]: return
    if not CFG["logfile"]: replay_journal()
    while True:
        try:
            cmd = ["tail", "-n", "400", "-F", CFG["logfile"]] if CFG["logfile"] else ["journalctl", "-u", CFG["unit"], "-f", "-n", "0", "-o", "cat", "--no-pager"]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            for line in p.stdout: handle_log(line.rstrip("\n"))
        except Exception as e:
            event("warn", "cannot read the broker log: %s" % e)
        time.sleep(5)

# ----------------------------------------------------------------------------- the machine
def read(path, default=""):
    try:
        with open(path) as f: return f.read()
    except Exception: return default

_cpu_prev = [None]
def cpu_pct():
    parts = [int(x) for x in read("/proc/stat").splitlines()[0].split()[1:8]] if read("/proc/stat") else []
    if not parts: return None
    idle, total = parts[3] + parts[4], sum(parts); prev = _cpu_prev[0]; _cpu_prev[0] = (idle, total)
    if not prev or total == prev[1]: return None
    return round(100.0 * (1 - (idle - prev[0]) / (total - prev[1])), 1)

def system():
    mem = {l.split(":")[0]: int(l.split()[1]) for l in read("/proc/meminfo").splitlines() if ":" in l}
    la = read("/proc/loadavg").split(); up = float((read("/proc/uptime") or "0 0").split()[0])
    net = {}
    for l in read("/proc/net/dev").splitlines()[2:]:
        if ":" in l:
            n, rest = l.split(":"); f = rest.split(); net[n.strip()] = {"rx": int(f[0]), "tx": int(f[8])}
    st = shutil.disk_usage("/")
    svc = {}
    for u in CFG["services"]:
        try: svc[u] = subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception: svc[u] = "unknown"
    pid = ""
    try: pid = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", CFG["unit"]], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception: pass
    mrss = mfd = None
    if pid.isdigit() and pid != "0":
        mrss = next((int(l.split()[1]) for l in read("/proc/%s/status" % pid).splitlines() if l.startswith("VmRSS")), None)
        try: mfd = len(os.listdir("/proc/%s/fd" % pid))
        except Exception: pass
    return {"cpu": cpu_pct(), "cores": os.cpu_count(), "load": [float(x) for x in la[:3]] if la else [], "uptime": up, "mem_total": mem.get("MemTotal", 0) * 1024, "mem_avail": mem.get("MemAvailable", 0) * 1024,
            "clock": clock_status(), "swap_total": mem.get("SwapTotal", 0) * 1024, "swap_free": mem.get("SwapFree", 0) * 1024, "disk_total": st.total, "disk_free": st.free, "net": net, "services": svc, "broker_rss": mrss, "broker_fds": mfd,
            "dash_rss": next((int(l.split()[1]) * 1024 for l in read("/proc/self/status").splitlines() if l.startswith("VmRSS")), None), "db_bytes": os.path.getsize(os.path.join(CFG["data"], "dash.sqlite")) if os.path.exists(os.path.join(CFG["data"], "dash.sqlite")) else 0}

_cert = {"t": 0, "v": None}
def certificate():
    if time.time() - _cert["t"] < 600: return _cert["v"]
    v = None
    try:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("127.0.0.1", 443), timeout=5) as raw, ctx.wrap_socket(raw, server_hostname=CFG["host"]) as s:
            der = s.getpeercert(binary_form=True)
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f: f.write(ssl.DER_cert_to_PEM_cert(der)); pem = f.name
        info = ssl._ssl._test_decode_cert(pem); os.unlink(pem)
        end = ssl.cert_time_to_seconds(info["notAfter"]); issuer = " ".join("%s" % x[0][1] for x in info.get("issuer", ()) if x and x[0][0] in ("organizationName", "commonName"))
        v = {"host": CFG["host"], "expires": end, "days": round((end - time.time()) / 86400, 1), "issuer": issuer}
    except Exception as e:
        v = {"host": CFG["host"], "error": str(e)}
    _cert.update(t=time.time(), v=v); return v

def accounts():
    try: raw = json.load(open(CFG["users"]))
    except Exception: return []
    out = []
    for n, v in sorted(raw.items()):
        v = v if isinstance(v, dict) else {"role": v}
        with LOCK:
            online = [c for c in CLIENTS.values() if c.get("user") == n and c.get("state") == "connected"]
            last = max([c.get("last", 0) for c in CLIENTS.values() if c.get("user") == n] or [0])
        dev = v.get("device", ""); d = DEV.get(dev)
        out.append({"name": n, "role": v.get("role", ""), "state": v.get("state", "approved"), "device": dev, "online": len(online), "last": last, "ip": online[0]["ip"] if online else "", "device_name": d["name"] if d else "", "device_seen": d["last"] if d else 0})
    return out

# ----------------------------------------------------------------------------- history
def db_init():
    global DB
    os.makedirs(CFG["data"], exist_ok=True)
    DB = sqlite3.connect(os.path.join(CFG["data"], "dash.sqlite"), check_same_thread=False, isolation_level=None)
    DB.execute("PRAGMA journal_mode=WAL"); DB.execute("PRAGMA synchronous=NORMAL")
    DB.execute("CREATE TABLE IF NOT EXISTS samples(ts INTEGER, k TEXT, v REAL)"); DB.execute("CREATE INDEX IF NOT EXISTS s_k ON samples(k, ts)")
    DB.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, seen INTEGER, chan TEXT, chash TEXT, region TEXT, sender TEXT, text TEXT, pkey TEXT UNIQUE, dir TEXT, hops INTEGER, snr REAL, rssi INTEGER, heard TEXT)"); DB.execute("CREATE INDEX IF NOT EXISTS m_seen ON messages(seen)")
    DB.execute("CREATE TABLE IF NOT EXISTS links(a TEXT, b TEXT, first INTEGER, last INTEGER, snr REAL, rssi INTEGER, PRIMARY KEY(a, b))")
    DB.execute("CREATE TABLE IF NOT EXISTS events(ts INTEGER, kind TEXT, client TEXT, user TEXT, ip TEXT, text TEXT)"); DB.execute("CREATE INDEX IF NOT EXISTS e_ts ON events(ts)")
    DB.execute("CREATE TABLE IF NOT EXISTS audit(ts INTEGER, who TEXT, action TEXT, target TEXT, detail TEXT, ok INTEGER)"); DB.execute("CREATE INDEX IF NOT EXISTS a_ts ON audit(ts)")

def sysnum(topic, default=0):
    v = SYS.get(topic)
    try: return float(v[0]) if v else default
    except ValueError: return default

def snapshot_values():
    s = system()
    with LOCK:
        online = [d for d in DEV.values() if time.time() - d["last"] < 900]
        vals = {"clients": sysnum("$SYS/broker/clients/connected"), "subs": sysnum("$SYS/broker/subscriptions/count"), "msgs_pm": rate_per_min("messages", 300), "pkts_pm": rate_per_min("packets", 300), "unique_pm": rate_per_min("unique", 300),
                "repeaters": len(online), "retained": sysnum("$SYS/broker/retained messages/count"), "bytes_rx_1m": sysnum("$SYS/broker/load/bytes/received/1min"), "bytes_tx_1m": sysnum("$SYS/broker/load/bytes/sent/1min"),
                "pub_rx_1m": sysnum("$SYS/broker/load/publish/received/1min"), "pub_tx_1m": sysnum("$SYS/broker/load/publish/sent/1min"), "conn_1m": sysnum("$SYS/broker/load/connections/1min"), "dropped_1m": sysnum("$SYS/broker/load/publish/dropped/1min"),
                "heap": sysnum("$SYS/broker/heap/current"), "load1": s["load"][0] if s["load"] else 0, "mem_pct": 100.0 * (1 - s["mem_avail"] / s["mem_total"]) if s["mem_total"] else 0, "disk_pct": 100.0 * (1 - s["disk_free"] / s["disk_total"]) if s["disk_total"] else 0}
        if s["cpu"] is not None: vals["cpu"] = s["cpu"]
        for did, d in DEV.items(): vals["dev:" + did[:16]] = rate_per_min("pkt:" + did, 300)
    for n, v in s["net"].items():
        if n != "lo": vals["net_rx:" + n] = v["rx"]; vals["net_tx:" + n] = v["tx"]
    return vals

def sampler_loop():
    while True:
        time.sleep(60)
        try:
            if int(time.time()) % 300 < 60: nodes_save()
            enrol_housekeeping()
            if int(time.time()) % 3600 < 60: messages_housekeeping()
            if int(time.time()) % 600 < 60: nodes_housekeeping()
            now = int(time.time()); vals = snapshot_values()
            DB.executemany("INSERT INTO samples VALUES(?,?,?)", [(now, k, float(v)) for k, v in vals.items()])
            if now % 3600 < 60:
                cut = now - CONF["keep_days"] * 86400; DB.execute("DELETE FROM samples WHERE ts<?", (cut,)); DB.execute("DELETE FROM events WHERE ts<?", (cut,))
        except Exception as e:
            sys.stderr.write("sampler: %s\n" % e)

def history(keys, seconds):
    if not DB: return {}
    cut = int(time.time()) - seconds; out = {}
    for k in keys:
        rows = DB.execute("SELECT ts,v FROM samples WHERE k=? AND ts>=? ORDER BY ts", (k, cut)).fetchall()
        if len(rows) > 600:
            step = len(rows) / 600.0; rows = [rows[int(i * step)] for i in range(600)]
        out[k] = rows
    return out

# ----------------------------------------------------------------------------- settings of the dashboard itself
DASH_ID = "DA" * 32                          # the id the dashboard publishes its own messages under (a repeater's bridge hands them to its radio)
SCAN_NAMES = ["yorkshire", "sheffield", "wakefield", "leeds", "bradford", "halifax", "huddersfield", "hull", "york", "doncaster",
  "rotherham", "barnsley", "harrogate", "scarborough", "lincolnshire", "lincoln", "derbyshire", "nottingham", "northwest", "northeast",
  "eng-yh", "eng-ne", "uk", "england", "public", "general", "test", "help", "news", "weather", "emergency", "chat", "hamradio",
  "mesh", "meshcore", "repeater", "repeaters", "solar", "traffic", "events", "club", "net", "scout", "rescue", "hiking", "cycling",
  "bolton", "manchester", "liverpool", "birmingham", "london", "bristol", "cardiff", "edinburgh", "glasgow", "newcastle", "carlisle",
  "lancashire", "cheshire", "norfolk", "suffolk", "essex", "kent", "sussex", "surrey", "hampshire", "devon", "cornwall", "wales",
  "scotland", "ireland", "europe", "dx", "sota", "portable", "mobile", "fixed", "emcomm", "lora", "ham", "ukmesh", "ukrepeaters",
  # wider Yorkshire and neighbours
  "westyorkshire", "southyorkshire", "northyorkshire", "eastyorkshire", "west-yorkshire", "south-yorkshire", "north-yorkshire",
  "east-yorkshire", "yorks", "pontefract", "castleford", "dewsbury", "batley", "keighley", "ilkley", "otley", "wetherby", "selby",
  "goole", "ripon", "whitby", "skipton", "settle", "malton", "pickering", "thirsk", "northallerton", "richmond", "catterick",
  "beverley", "bridlington", "grimsby", "scunthorpe", "chesterfield", "matlock", "buxton", "derby", "mansfield", "worksop",
  "oldham", "rochdale", "burnley", "blackburn", "preston", "blackpool", "lancaster", "wigan", "stockport", "warrington", "salford",
  "sunderland", "durham", "middlesbrough", "teesside", "darlington", "gateshead", "leicester", "stoke", "sheffieldmesh", "leedsmesh",
  "peak", "peakdistrict", "dales", "yorkshiredales", "moors", "pennines", "lakes", "lakedistrict", "cumbria", "northumberland",
  "midlands", "eastmidlands", "westmidlands", "north", "south", "east", "west", "gb", "britain", "unitedkingdom", "eng",
  # habits seen on MeshCore networks
  "local", "random", "offtopic", "off-topic", "bot", "bots", "ping", "pong", "testing", "test1", "test2", "tests", "echo",
  "admin", "sysop", "ops", "infra", "status", "alerts", "alert", "wx", "aprs", "gps", "telemetry", "sensors", "nodes", "net1",
  "meshtastic", "mesh-uk", "uk-mesh", "meshuk", "ukmeshcore", "meshcoreuk", "meshcore-uk", "community", "social", "hello",
  "lobby", "main", "radio", "amateur", "amateurradio", "ham-radio", "hams", "raynet", "rsgb", "scouts", "jota", "foxhunt",
  "satellite", "sats", "iss", "hf", "vhf", "uhf", "2m", "70cm", "dmr", "ysf", "dstar", "allstar", "echolink", "contest",
  "sar", "mountainrescue", "lifeboat", "fire", "police", "ambulance", "flood", "storm", "power", "outage", "blackout",
  "family", "friends", "home", "work", "pub", "beer", "food", "music", "gaming", "tech", "linux", "dev", "makers", "hackspace"]
MSG_DEFAULTS = {"tx_enabled": True, "sender": "UMC-DASH", "keep_days": 30,
                "channels": [{"name": "Public", "psk": MSG.PUBLIC_PSK}, {"name": "#yorkshire"}, {"name": "#northwest"}, {"name": "#northeast"}, {"name": "#derbyshire"}, {"name": "#lincolnshire"}, {"name": "#sheffield"}, {"name": "#wakefield"}],
                "regions": ["yorkshire", "eng-yh", "northwest", "eng-ne", "derbyshire", "lincolnshire", "sheffield", "wakefield"]}
DEFAULTS = {"publish_decoded": True, "web_users": {}, "messages": MSG_DEFAULTS, "map_hours": 24, "enrol_enabled": True, "join_bridge": True, "join_iata": "LBA", "title": "UMC Net", "stale_minutes": 15, "cert_warn_days": 14, "cert_bad_days": 5, "disk_warn_pct": 85, "mem_warn_pct": 85, "flap_count": 5, "skew_seconds": 120,
            "auth_fail_warn": 1, "auth_fail_bad": 20, "keep_days": 14, "confirm_risky": True, "control_enabled": True,
            "alerts": {"enabled": False, "url": "", "offline": True, "online": True, "pending": True, "auth_fail": True, "cert": True, "disk": True, "control": True},
            "labels": {}}
RANGES = {"map_hours": (1, 8760), "stale_minutes": (2, 1440), "cert_warn_days": (2, 60), "cert_bad_days": (1, 30), "disk_warn_pct": (50, 99), "mem_warn_pct": (50, 99), "flap_count": (2, 50),
          "skew_seconds": (5, 3600), "auth_fail_warn": (1, 1000), "auth_fail_bad": (2, 10000), "keep_days": (1, 90)}
CONF = json.loads(json.dumps(DEFAULTS))

def conf_path(): return os.path.join(CFG["data"], "config.json")

def conf_load():
    try: raw = json.load(open(conf_path()))
    except Exception: raw = {}
    merged = json.loads(json.dumps(DEFAULTS))
    for k, v in raw.items():
        if k == "alerts" and isinstance(v, dict): merged["alerts"].update({a: b for a, b in v.items() if a in merged["alerts"]})
        elif k == "messages" and isinstance(v, dict): merged["messages"].update(v)
        elif k == "web_users" and isinstance(v, dict): merged["web_users"] = v
        elif k in merged: merged[k] = v
    CONF.clear(); CONF.update(merged)

def conf_save():
    tmp = conf_path() + ".tmp"
    with open(tmp, "w") as f: json.dump(CONF, f, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600); os.replace(tmp, conf_path())

def conf_update(patch):
    """Validate and apply a settings change. Returns an error text or None."""
    if not isinstance(patch, dict): return "not a settings object"
    new = json.loads(json.dumps(CONF))
    for k, v in patch.items():
        if k in RANGES:
            try: v = int(v)
            except (TypeError, ValueError): return "%s must be a whole number" % k
            lo, hi = RANGES[k]
            if not lo <= v <= hi: return "%s must be between %d and %d" % (k, lo, hi)
            new[k] = v
        elif k in ("confirm_risky", "control_enabled", "join_bridge", "enrol_enabled", "publish_decoded"): new[k] = bool(v)
        elif k == "join_iata":
            if not isinstance(v, str) or not re.match(r"^[A-Za-z0-9]{3}$", v): return "join_iata: the three-character area code"
            new[k] = v.upper()
        elif k == "title":
            if not isinstance(v, str) or not 1 <= len(v) <= 40: return "title: 1 to 40 characters"
            new[k] = v.strip()
        elif k == "alerts":
            if not isinstance(v, dict): return "alerts must be an object"
            for a, b in v.items():
                if a not in new["alerts"]: continue
                if a == "url":
                    if not isinstance(b, str) or (b and not re.match(r"^https?://[^\s]{4,300}$", b)): return "the alert address must start with http:// or https://"
                    new["alerts"][a] = b.strip()
                else: new["alerts"][a] = bool(b)
        elif k == "messages":
            if not isinstance(v, dict): return "messages must be an object"
            m = new["messages"]
            for a, b in v.items():
                if a == "tx_enabled": m[a] = bool(b)
                elif a == "keep_days":
                    try: b = int(b)
                    except (TypeError, ValueError): return "keep_days must be a whole number"
                    if not 1 <= b <= 365: return "keep_days must be between 1 and 365"
                    m[a] = b
                elif a == "sender":
                    if not isinstance(b, str) or not re.match(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,23}$", b.strip()): return "the sender name is 1 to 24 letters, digits, spaces, dots, dashes or underscores"
                    m[a] = b.strip()
                elif a == "regions":
                    if not isinstance(b, list) or len(b) > 40 or not all(isinstance(x, str) and re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,30}$", x.strip().lstrip("#")) for x in b): return "regions: a list of names (letters, digits, dashes)"
                    m[a] = [x.strip().lstrip("#") for x in b]
                elif a == "channels":
                    if not isinstance(b, list) or len(b) > 40: return "channels: a list of up to 40"
                    out = []
                    for c in b:
                        if not isinstance(c, dict) or not isinstance(c.get("name"), str): return "each channel needs a name"
                        e = {"name": c["name"].strip()}
                        if c.get("psk"): e["psk"] = str(c["psk"]).strip()
                        try: MSG.Channel(e["name"], e.get("psk"))
                        except Exception as ex: return "channel %s: %s" % (e["name"], ex)
                        if len(e["name"]) > 31 or not re.match(r"^[A-Za-z0-9#][A-Za-z0-9 #_-]*$", e["name"]): return "channel names are letters, digits, # _ - and spaces"
                        out.append(e)
                    m[a] = out
        elif k == "labels":
            if not isinstance(v, dict): return "labels must be an object"
            lab = {}
            for dev, d in v.items():
                if re.match(r"^[0-9A-F]{64}$", dev) and isinstance(d, dict): lab[dev] = {"label": str(d.get("label", ""))[:40], "note": str(d.get("note", ""))[:300]}
            new["labels"] = lab
    if new["cert_bad_days"] >= new["cert_warn_days"]: return "the red certificate limit must be below the amber one"
    CONF.clear(); CONF.update(new); conf_save()
    return None

def make_join_code(user, password, iata="LBA", key_hex=None, bridge=True, host=None, port=443):
    """One line a repeater applies with `set mqtt.join <code>` (format: src/helpers/mqtt/JoinCode.h)."""
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,23}$", user or ""): raise ValueError("the account name is 2 to 24 lowercase letters, digits and dashes")
    if not (8 <= len(password or "") <= 40) or not all(0x21 <= ord(c) <= 0x7e for c in password): raise ValueError("the password must be 8 to 40 printable characters with no spaces")
    if not re.match(r"^[A-Z0-9]{3}$", iata or ""): raise ValueError("the area code is three capital letters or digits")
    if key_hex is not None and not re.match(r"^[0-9a-fA-F]{64}$", key_hex): raise ValueError("the control key is 64 hex characters")
    if host is not None and not (3 <= len(host) <= 63 and all(0x21 <= ord(c) <= 0x7e for c in host) and 0 < port < 65536): raise ValueError("the host or port is not valid")
    flags = (1 if key_hex else 0) | (2 if bridge else 0) | (4 if host else 0)
    b = bytes([1, flags]) + iata.encode() + bytes([len(user)]) + user.encode() + bytes([len(password)]) + password.encode()
    if host: b += bytes([len(host)]) + host.encode() + struct.pack(">H", port)
    if key_hex: b += bytes.fromhex(key_hex)
    b += hashlib.sha256(b).digest()[:3]
    code = "UMC1." + base64.urlsafe_b64encode(b).decode().rstrip("=")
    if len(code) > 140: raise ValueError("that code is too long for the repeater's console")
    return code

def audit(who, action, target, detail, ok=True):
    try:
        DB.execute("INSERT INTO audit(ts,who,action,target,detail,ok) VALUES(?,?,?,?,?,?)", (int(time.time()), who, action, target, str(detail)[:400], 1 if ok else 0))
    except Exception: pass

# ----------------------------------------------------------------------------- the privileged helper (accounts, login)
def admin_call(**req):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(40); s.connect(CFG["admin_sock"])
        s.sendall((json.dumps(req) + "\n").encode()); buf = b""
        while not buf.endswith(b"\n"):
            c = s.recv(65536)
            if not c: break
            buf += c
        s.close(); return json.loads(buf.decode() or "{}")
    except Exception as e:
        return {"ok": False, "error": "the admin helper is not answering (%s)" % e}

# ----------------------------------------------------------------------------- remote control of repeaters
READ_ONLY_EXACT = ("ver", "board", "neighbors", "routes", "stats-core", "stats-radio", "stats-packets", "stats-rf", "stats-life", "memory", "safety state")
SECRET_WORDS = ("password", "guest", "prv", "private", "wifi.", "ap.", "net.ip", "set pin", "get pin", "ble.pin", "mqtt.custom.", "mqtt.control.key", "bridge.secret", "mqtt.join", "owner.info", "set lat", "set lon", "get lat", "get lon")

def command_allowed(cmd):
    """The signed administrator gets the full CLI; reject only malformed transport input."""
    if not isinstance(cmd, str) or not cmd or len(cmd) > 140 or cmd != cmd.strip(): return False
    if any(ord(c) < 32 or ord(c) == 127 or c in '"\\' for c in cmd): return False
    return True

def command_risky(cmd):
    low = cmd.lower()
    if low.startswith("get ") and low[4:] in DEVICE_SETTING_KEYS + STATUS_SETTING_KEYS: return False     # the settings the page itself reads (some names, like lat or mqtt.custom.rate, contain words used to hide secrets)
    if any(s in low for s in SECRET_WORDS): return True
    return not (low.startswith("get ") or low in READ_ONLY_EXACT or low.startswith("stats-") or low.startswith("safety log"))

def command_secret(cmd):
    low = (cmd or "").lower()
    return any(s in low for s in SECRET_WORDS)

def audit_command(cmd, reply=None):
    if command_secret(cmd):
        name = cmd.split(" ", 2)[:2]
        return "%s [secret redacted]%s" % (" ".join(name), " -> [reply redacted]" if reply is not None else "")
    return "%s%s" % (cmd, " -> %s" % reply if reply is not None else "")

def sign(key_hex, dev, ts, n, cmd):
    return hmac.new(bytes.fromhex(key_hex), ("%s|%d|%d|%s" % (dev, ts, n, cmd)).encode(), hashlib.sha256).hexdigest()

KEYS = {}                                  # device id -> {"key": hex, "created": ts}
CTL = {"waiting": {}, "last_n": 0, "lock": threading.Lock(), "conn": None, "state": "idle", "last": {}}

def keys_path(): return os.path.join(CFG["data"], "control.json")
def keys_load():
    try: KEYS.update(json.load(open(keys_path())))
    except Exception: pass
def keys_save():
    tmp = keys_path() + ".tmp"
    with open(tmp, "w") as f: json.dump(KEYS, f)
    os.chmod(tmp, 0o600); os.replace(tmp, keys_path())

def control_key(dev, create=False, new=False):
    with LOCK:
        if (new or create and dev not in KEYS):
            KEYS[dev] = {"key": secrets.token_hex(32), "created": int(time.time())}; keys_save()
        return KEYS.get(dev, {}).get("key")

# ----------------------------------------------------------------------------- dashboard users
# Caddy checks the password and passes the signed-in name in X-UMC-User (the public pages strip it). "admin" can do
# everything. Any other user sees the whole network but controls only the repeaters listed for them, and can send messages.
WEBNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,30}$")
OWNER_POSTS = ("/api/control", "/api/control/batch", "/api/control/preload", "/api/control/setup", "/api/messages/send", "/api/password")

def role_of(who):
    if who == "admin": return "admin"
    u = CONF["web_users"].get(who)
    return (u.get("role") if u and u.get("role") in ("admin", "owner", "viewer") else "viewer") if u else "viewer"

def devices_of(who):
    return [d.upper() for d in (CONF["web_users"].get(who) or {}).get("devices", [])]

def may_control(who, dev):
    r = role_of(who)
    return r == "admin" or (r == "owner" and str(dev or "").upper() in devices_of(who))

def me_view(who):
    r = role_of(who); u = CONF["web_users"].get(who) or {}
    return {"name": who, "role": r, "devices": None if r == "admin" else devices_of(who), "sender": u.get("sender") or ""}

def users_save(body):
    name = str(body.get("name", "")).strip().lower()
    if not WEBNAME.match(name) or name == "admin": return {"ok": False, "error": "user names are 2 to 31 lowercase letters, digits, dots, dashes or underscores (not admin)"}
    role = str(body.get("role", "owner"))
    if role not in ("admin", "owner", "viewer"): return {"ok": False, "error": "role: admin, owner or viewer"}
    devs = [str(d).upper() for d in body.get("devices", []) if re.match(r"^[0-9A-Fa-f]{64}$", str(d))]
    sender = str(body.get("sender", "")).strip()
    if sender and not re.match(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,23}$", sender): return {"ok": False, "error": "the sender name is 1 to 24 letters, digits, spaces, dots, dashes or underscores"}
    pw = str(body.get("password", ""))
    if name not in CONF["web_users"] and not pw: return {"ok": False, "error": "a new user needs a password"}
    if pw:
        r = admin_call(op="web_user_set", name=name, password=pw)
        if not r.get("ok"): return r
    CONF["web_users"][name] = {"role": role, "devices": devs, "sender": sender}; conf_save()
    return {"ok": True}

def users_remove(name):
    name = str(name or "")
    if name not in CONF["web_users"]: return {"ok": False, "error": "no such user"}
    r = admin_call(op="web_user_remove", name=name)
    if not r.get("ok"): return r
    CONF["web_users"].pop(name, None); conf_save()
    return {"ok": True}

# ----------------------------------------------------------------------------- decoded copies for other apps
# Read-only JSON copies of what the dashboard decodes, for Home Assistant, Node-RED and the like. They do not replace the radio
# traffic: repeaters keep bridging the real packets both ways. Topics, under the network's area:
#   umcnet/v1/<area>/messages        each channel message (heard or sent from here)
#   umcnet/v1/<area>/adverts         each node's advert (at most every ten minutes per node, or when it changes)
#   umcnet/v1/<area>/nodes/<key>     retained: the node's name, kind, position, last heard and online (heard in the last day)
NODE_KIND = {1: "companion", 2: "repeater", 3: "room", 4: "sensor"}
ADV_PUB = {}; NODE_ONLINE = {}

def publish_decoded(suffix, obj, retain=False):
    if not CONF.get("publish_decoded", True): return
    conn = CTL.get("conn")
    if not conn or not getattr(conn, "up", False): return
    try: conn.publish("umcnet/v1/%s/%s" % (CONF["join_iata"], suffix), json.dumps(obj, separators=(",", ":")).encode(), retain)
    except Exception as e: sys.stderr.write("decoded publish: %s\n" % e)

def decoded_advert(did, n, info, snr, now):
    k = n["key"]; prev = ADV_PUB.get(k); cur = (n["name"], n["lat"], n["lon"])
    if prev is not None and now - prev[0] < 600 and prev[1:] == cur: return
    ADV_PUB[k] = (now,) + cur
    d = DEV.get(did); kind = NODE_KIND.get(n["type"], "node")
    try: snr = float(snr) if snr not in (None, "") else None
    except ValueError: snr = None
    publish_decoded("adverts", {"key": k, "name": n["name"], "type": kind, "lat": n["lat"], "lon": n["lon"], "time": int(now), "heard_by": (d or {}).get("name") or did[:8], "hops": info.get("hops"), "snr": snr})
    publish_decoded("nodes/" + k, {"key": k, "name": n["name"], "type": kind, "lat": n["lat"], "lon": n["lon"], "last": int(now), "online": True}, retain=True)
    NODE_ONLINE[k] = True

def nodes_housekeeping():
    """A node not heard for a day is published as offline (retained), once."""
    now = time.time()
    for k, on in list(NODE_ONLINE.items()):
        n = NODES.get(k)
        if on and n and now - n["last"] > 86400:
            publish_decoded("nodes/" + k, {"key": k, "name": n["name"], "type": NODE_KIND.get(n["type"], "node"), "lat": n["lat"], "lon": n["lon"], "last": int(n["last"]), "online": False}, retain=True)
            NODE_ONLINE[k] = False

def decoded_message(row_id, ts, chan, region, sender, text, direction, heard):
    publish_decoded("messages", {"id": row_id, "time": ts, "channel": chan, "region": region, "sender": sender, "text": text, "dir": direction, "heard_by": heard})

# ----------------------------------------------------------------------------- messages (channels and regions)
RECENT_GRP = collections.deque(maxlen=600)   # (time, payload) of group packets we cannot read yet: the scan tests names against them
MSGSTAT = {}                                # channel hash -> deque of (time, region): messages we cannot read, kept 24 h
TX_TIMES = collections.deque(maxlen=20)

def msg_channels():
    out = []
    for c in CONF["messages"]["channels"]:
        try: out.append(MSG.Channel(c["name"], c.get("psk") or None))
        except Exception: pass
    return out

def note_message(did, raw, snr, rssi, now):
    """A repeater heard a packet: if it is a group text, record it (once, with every repeater that heard it)."""
    if did == DASH_ID or not DB: return
    p = MSG.parse_wire(raw)
    if not p or p["ptype"] != 5 or len(p["payload"]) < 19: return
    pkey = hashlib.sha1(p["payload"]).hexdigest()[:20]
    entry = {"d": did, "h": len(p["path"]), "s": float(snr) if snr not in (None, "") else None, "r": int(rssi) if rssi not in (None, "") else None, "t": int(now)}
    regions = CONF["messages"]["regions"]
    region = (MSG.find_region(regions, p) or "?") if p["codes"] else ""
    with LOCK:
        row = DB.execute("SELECT id, heard, region, hops, snr FROM messages WHERE pkey=?", (pkey,)).fetchone()
        if row:
            heard = json.loads(row[1] or "[]"); old = next((e for e in heard if e["d"] == did), None)
            if old is None: heard.append(entry)
            elif entry["h"] < old["h"]: old.update(entry)
            hops = min(row[3] if row[3] is not None else 99, entry["h"]); snrs = [x for x in (row[4], entry["s"]) if x is not None]
            DB.execute("UPDATE messages SET heard=?, hops=?, snr=?, region=? WHERE id=?", (json.dumps(heard, separators=(",", ":")), hops, max(snrs) if snrs else None, row[2] if row[2] not in ("", "?") or not region else region, row[0]))
            return
    r = MSG.decrypt_group(msg_channels(), p["payload"])
    with LOCK:
        if r is None:                                           # a channel we have no key for: count it, keep it for the name scan
            RECENT_GRP.append((int(now), p["payload"]))
            MSGSTAT.setdefault("%02X" % p["payload"][0], collections.deque(maxlen=5000)).append((now, region or "-"))
            return
        ch, ts, flags, text = r
        sender, body = MSG.split_sender(text)
        try: cur = DB.execute("INSERT OR IGNORE INTO messages(ts,seen,chan,chash,region,sender,text,pkey,dir,hops,snr,rssi,heard) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (ts, int(now), ch.name, "%02X" % ch.hash, region, sender, body, pkey, "rx", entry["h"], entry["s"], entry["r"], json.dumps([entry], separators=(",", ":"))))
        except Exception as e: sys.stderr.write("messages: %s\n" % e); cur = None
        dn = (DEV.get(did) or {}).get("name") or did[:8]
    if cur is not None and cur.rowcount: decoded_message(cur.lastrowid, ts, ch.name, region, sender, body, "rx", [{"name": dn, "hops": entry["h"], "snr": entry["s"], "rssi": entry["r"]}])

def unreadable_stats(hours=24):
    """Channels heard in the last day that the dashboard has no key for. Call with LOCK held."""
    cut = time.time() - hours * 3600
    out = {}
    for k in list(MSGSTAT):
        q = MSGSTAT[k]
        while q and q[0][0] < cut: q.popleft()
        if not q: del MSGSTAT[k]; continue
        out[k] = {"n": len(q), "last": q[-1][0], "regions": dict(collections.Counter(r for _, r in q))}
    return out

GROUP_SCAN_EVERY = 600
GROUP_SCAN_MIN = 3          # packets a hashtag name must open before it is added on its own

def group_scan_loop():
    """Hashtag groups are public by design: the key is derived from the name. Every few minutes the
    recent unreadable packets are tested against the name list, and any group that opens enough of
    them is added, so its messages are shown from then on. Private (random-key) channels stay unread."""
    time.sleep(180)
    while True:
        try:
            if CONF["messages"].get("auto_groups", True):
                for g in scan_public_groups():
                    if g["packets"] < GROUP_SCAN_MIN: continue
                    if any(c.get("name") == g["name"] for c in CONF["messages"]["channels"]): continue
                    CONF["messages"]["channels"].append({"name": g["name"]}); conf_save()
                    h = "%02X" % MSG.Channel(g["name"]).hash
                    with LOCK: MSGSTAT.pop(h, None)
                    audit("system", "group added", g["name"], "public hashtag group opened %d heard packets" % g["packets"])
                    event("info", "public group %s found on the mesh and added" % g["name"])
        except Exception as e: sys.stderr.write("group scan: %s\n" % e)
        time.sleep(GROUP_SCAN_EVERY)

def scan_public_groups(names=None):
    """Find hashtag groups heard locally: for each public name, derive its key, and look for packets it can open.
    Returns the groups that matched, with how many packets they account for. Nothing is decrypted without its name."""
    found = {}
    cands = []
    for nm in (names or SCAN_NAMES):
        nm = nm.strip().lstrip("#").lower()
        if not nm or any(c.get("name", "").lstrip("#").lower() == nm for c in CONF["messages"]["channels"]):
            continue
        try: ch = MSG.Channel("#" + nm)
        except Exception: continue
        cands.append((nm, ch))
    with LOCK: packets = list(RECENT_GRP)
    for t, payload in packets:
        for nm, ch in cands:
            if ch.hash != payload[0]: continue
            if MSG.decrypt_group([ch], payload) is not None:
                g = found.setdefault("#" + nm, {"name": "#" + nm, "packets": 0, "last": 0})
                g["packets"] += 1; g["last"] = max(g["last"], t)
                break
    return sorted(found.values(), key=lambda g: -g["packets"])

def rooms_heard():
    """Room servers the repeaters have heard in the last month. Joining one needs its password, which is not kept here."""
    now = time.time()
    with LOCK:
        return sorted([{"key": k, "name": n["name"] or k[:8], "last": n["last"], "lat": n["lat"], "lon": n["lon"]}
                       for k, n in NODES.items() if n["type"] == 3 and now - n["last"] < 30 * 86400], key=lambda r: -r["last"])

def messages_view(chan="", region="", direction="", before=0, limit=100, q=""):
    where, args = [], []
    if chan: where.append("chan=?"); args.append(chan)
    if region == "-": where.append("region=''")
    elif region: where.append("region=?"); args.append(region)
    if direction in ("rx", "tx"): where.append("dir=?"); args.append(direction)
    if before: where.append("id<?"); args.append(int(before))
    if q: where.append("(text LIKE ? OR sender LIKE ?)"); args += ["%" + q + "%"] * 2
    sql = "SELECT id,ts,seen,chan,chash,region,sender,text,dir,hops,snr,rssi,heard FROM messages" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    with LOCK:
        rows = DB.execute(sql, args + [max(1, min(int(limit), 300))]).fetchall()
        day = int(time.time()) - 86400
        counts = [{"chan": r[0], "region": r[1], "n": r[2]} for r in DB.execute("SELECT chan, region, COUNT(*) FROM messages WHERE seen>? GROUP BY chan, region", (day,)).fetchall()]
        unread = unreadable_stats()
        names = {d["id"]: (d["name"] or d["id"][:8]) for d in DEV.values()}
    out = []
    for r in rows:
        heard = json.loads(r[12] or "[]")
        out.append({"id": r[0], "ts": r[1], "seen": r[2], "chan": r[3], "chash": r[4], "region": r[5], "sender": r[6], "text": r[7], "dir": r[8], "hops": r[9], "snr": r[10], "rssi": r[11],
                    "heard": [{"name": names.get(h["d"], h["d"][:8]), "hops": h["h"], "snr": h["s"], "rssi": h["r"]} for h in sorted(heard, key=lambda x: x["h"])]})
    c = CONF["messages"]
    return {"messages": out, "channels": [{"name": x["name"], "hash": "%02X" % MSG.Channel(x["name"], x.get("psk")).hash} for x in c["channels"]], "regions": c["regions"], "counts": counts,
            "unreadable": unread, "tx_enabled": bool(c["tx_enabled"]), "sender": c["sender"]}

def send_message(who, chan, region, text, sender=None):
    c = CONF["messages"]
    if not c["tx_enabled"]: return {"ok": False, "error": "sending is switched off in Settings"}
    conn = CTL.get("conn")
    if not conn or not conn.up: return {"ok": False, "error": "the control link to the broker is down, so the message cannot be handed to the repeaters"}
    text = (text or "").strip()
    if not text: return {"ok": False, "error": "type a message first"}
    if len(text.encode("utf-8")) > 130: return {"ok": False, "error": "that message is too long (130 characters at most)"}
    if any(ord(ch) < 32 for ch in text): return {"ok": False, "error": "no line breaks"}
    sender = (sender or c["sender"] or "UMC-DASH").strip()
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,23}$", sender): return {"ok": False, "error": "the sender name is 1 to 24 letters, digits, spaces, dots, dashes or underscores"}
    ch = next((x for x in msg_channels() if x.name == chan), None)
    if not ch: return {"ok": False, "error": "that channel is not set up"}
    region = (region or "").strip().lstrip("#")
    if region and region not in c["regions"]: return {"ok": False, "error": "that region is not in the list"}
    now = time.time()
    with LOCK:
        while TX_TIMES and now - TX_TIMES[0] > 60: TX_TIMES.popleft()
        if len(TX_TIMES) >= 6: return {"ok": False, "error": "at most 6 messages a minute"}
        TX_TIMES.append(now)
    live = [d for d in DEV.values() if d["last"] and now - d["last"] < CONF["stale_minutes"] * 60]
    if not live: return {"ok": False, "error": "no repeater is online to send it"}
    raw = MSG.build_group_text(ch, sender, text, int(now), region or None)
    area = CONF["join_iata"]
    body = json.dumps({"origin": "UMC Dashboard", "origin_id": DASH_ID, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now)), "type": "RAW", "data": raw.hex().upper()}, separators=(",", ":")).encode()
    conn.publish("meshcore/%s/%s/raw" % (area, DASH_ID), body)
    pkey = hashlib.sha1(MSG.parse_wire(raw)["payload"]).hexdigest()[:20]
    with LOCK: cur = DB.execute("INSERT OR IGNORE INTO messages(ts,seen,chan,chash,region,sender,text,pkey,dir,hops,snr,rssi,heard) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (int(now), int(now), ch.name, "%02X" % ch.hash, region, sender, text, pkey, "tx", 0, None, None, "[]"))
    decoded_message(cur.lastrowid, int(now), ch.name, region, sender, text, "tx", [])
    audit(who, "message sent", ch.name + (" / " + region if region else ""), "%s: %s" % (sender, text[:60]))
    return {"ok": True, "repeaters": [d["name"] or d["id"][:8] for d in live]}

BRIDGE_RX = re.compile(r"heard (\d+), passed on (\d+), dropped (\d+)")
def bridge_poll_loop():
    """Once a minute ask each online repeater how many packets its UMC Net bridge heard from the others and passed on to its radio."""
    time.sleep(90)
    while True:
        try:
            for dev in list(KEYS):
                d = DEV.get(dev)
                if not d or not d.get("last") or time.time() - d["last"] > CONF["stale_minutes"] * 60: continue
                r = send_command(dev, "get mqtt.custom.bridge", "bridge-poll", timeout=10, quiet=True)
                m = BRIDGE_RX.search(r.get("reply") or "") if r.get("ok") else None
                if not m: continue
                heard, passed, dropped = (int(x) for x in m.groups()); now = time.time(); b = d.get("bridge")
                if b and now - b["t"] < 400 and heard >= b["heard"] and passed >= b["passed"]:
                    dt = max(1.0, (now - b["t"]) / 60.0)
                    d["bridge"] = {"t": now, "heard": heard, "passed": passed, "dropped": dropped, "heard_pm": round((heard - b["heard"]) / dt, 2), "passed_pm": round((passed - b["passed"]) / dt, 2), "dropped_pm": round((dropped - b["dropped"]) / dt, 2)}
                else: d["bridge"] = {"t": now, "heard": heard, "passed": passed, "dropped": dropped, "heard_pm": 0, "passed_pm": 0, "dropped_pm": 0}
                time.sleep(1.2)
        except Exception as e: sys.stderr.write("bridge poll: %s\n" % e)
        time.sleep(55)

def messages_housekeeping():
    try:
        with LOCK: DB.execute("DELETE FROM messages WHERE seen<?", (int(time.time()) - CONF["messages"]["keep_days"] * 86400,))
    except Exception: pass

# ----------------------------------------------------------------------------- zero-touch enrolment (docs/umc/ENROL.md)
ENROL = {"pending": {}, "declined": {}, "approved": {}}

def enrol_path(): return os.path.join(CFG["data"], "enrol.json")

def enrol_save():
    try:
        with LOCK: data = json.dumps(ENROL)
        tmp = enrol_path() + ".tmp"; open(tmp, "w").write(data); os.replace(tmp, enrol_path())
    except Exception as e: sys.stderr.write("enrol: %s\n" % e)

def enrol_load():
    try: d = json.load(open(enrol_path()))
    except Exception: return
    for k in ENROL:
        if isinstance(d.get(k), dict): ENROL[k].update(d[k])

def enrol_slug(name, dev):
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:20].strip("-")
    if len(base) < 2: base = "rpt-" + dev[:6].lower()
    taken = {a["name"] for a in accounts()}
    slug, n = base, 2
    while slug in taken: slug = "%s-%d" % (base[:20], n); n += 1
    return slug

def enrol_hello(payload, retained=False):
    """A repeater is asking to join. Only a request signed by the key that its id names is accepted."""
    if retained or not CONF.get("enrol_enabled", True): return
    info, why = ENR.verify_hello(payload)
    now = time.time()
    if not info:
        with LOCK: COUNT["enrol_refused"] += 1
        if why in ("signature does not match the id", "clock too far off"): event("enrol", "a request was refused: " + why, at=now)
        return
    dev = info["id"]; new = False
    with LOCK:
        if dev in ENROL["declined"]: ENROL["declined"][dev]["last"] = now; return
        p = ENROL["pending"].get(dev)
        if p is None:
            if len(ENROL["pending"]) >= 50: return                  # a flood of requests: keep what is waiting
            ENROL["pending"][dev] = p = {"id": dev, "first": now, "count": 0}; new = True
        if now - p.get("last", 0) < 20 and not new: return            # one update every 20 s is plenty
        p.update(name=info["name"], fw=info["fw"], board=info["bd"], last=now, count=p["count"] + 1)
    if new:
        event("enrol", "%s (%s...) is asking to join" % (info["name"] or "a repeater", dev[:8]), "", "enrol", "", now)
        enrol_save()
        send_alert("A repeater is asking to join", "%s (id %s...) is asking to join UMC Net. Open the dashboard, Accounts tab, to approve or decline it." % (info["name"] or "A repeater", dev[:8]), "info", "enrol")
    elif int(now) % 5 == 0: enrol_save()

def enrol_approve(who, dev, name=None, bridge=None):
    dev = str(dev).upper()
    conn = CTL.get("conn")
    if not conn or not conn.up: return {"ok": False, "error": "the control link to the broker is down, so the answer could not be sent"}
    with LOCK: p = ENROL["pending"].get(dev)
    if not p: return {"ok": False, "error": "that request is no longer waiting"}
    existing = next((a for a in accounts() if a["device"] == dev), None)
    if existing: slug = existing["name"]; r = admin_call(op="user_passwd", name=slug)
    else:
        slug = enrol_slug(name or p.get("name"), dev); r = admin_call(op="user_add", name=slug, role="repeater", device=dev)
    if not r.get("ok") or not r.get("password"):
        audit(who, "enrol approve", dev[:12], r.get("error") or r.get("output") or "failed", False)
        return {"ok": False, "error": r.get("error") or r.get("output") or "could not make the account"}
    try: code = make_join_code(slug, r["password"], CONF["join_iata"], control_key(dev, create=True), CONF["join_bridge"] if bridge is None else bool(bridge))
    except ValueError as e: return {"ok": False, "error": str(e)}
    conn.publish("umcnet/v1/enrol/grant/" + dev, ENR.make_grant(dev, code).encode(), retain=True)
    with LOCK:
        ENROL["pending"].pop(dev, None)
        ENROL["approved"][dev] = {"account": slug, "name": p.get("name", ""), "at": time.time(), "delivered": False}
    enrol_save(); export_accounts_soon()
    audit(who, "enrol approve", dev[:12], "account %s, remote control key included" % slug)
    return {"ok": True, "account": slug}

def enrol_decline(who, dev):
    dev = str(dev).upper()
    with LOCK:
        p = ENROL["pending"].pop(dev, None)
        if not p: return {"ok": False, "error": "that request is no longer waiting"}
        ENROL["declined"][dev] = {"id": dev, "name": p.get("name", ""), "at": time.time(), "last": time.time()}
        while len(ENROL["declined"]) > 200: ENROL["declined"].pop(next(iter(ENROL["declined"])))
    enrol_save(); audit(who, "enrol decline", dev[:12], p.get("name", "")); return {"ok": True}

def enrol_forget(who, dev):
    dev = str(dev).upper()
    with LOCK: gone = ENROL["declined"].pop(dev, None)
    enrol_save(); audit(who, "enrol forget", dev[:12], "may ask again"); return {"ok": bool(gone)}

def enrol_housekeeping():
    """Drop requests nobody has seen for a day, and take a delivered grant off the broker."""
    now = time.time(); conn = CTL.get("conn"); changed = False
    with LOCK:
        for dev in [d for d, p in ENROL["pending"].items() if now - p.get("last", 0) > 86400]: ENROL["pending"].pop(dev); changed = True
        approved = list(ENROL["approved"].items())
    for dev, a in approved:
        with LOCK: online = any(c.get("user") == a["account"] and c.get("state") == "connected" for c in CLIENTS.values())
        if not a.get("delivered") and (online or now - a["at"] > 7 * 86400):
            if conn and conn.up:
                try: conn.publish("umcnet/v1/enrol/grant/" + dev, b"", retain=True)       # an empty retained message clears it
                except Exception: continue
            with LOCK: a["delivered"] = bool(online); a["cleared"] = True
            changed = True
    if changed: enrol_save()

def enrol_view():
    now = time.time()
    with LOCK:
        pend = [dict(p) for p in ENROL["pending"].values()]; dec = [dict(d) for d in ENROL["declined"].values()]
        app = [dict(a, id=d) for d, a in ENROL["approved"].items() if now - a["at"] < 7 * 86400][-10:]
        ips = {c.get("client", ""): c.get("ip", "") for c in CLIENTS.values()}
    accts = {a["device"]: a["name"] for a in accounts() if a["device"]}
    for p in pend:
        p["ip"] = ips.get("umc-enrol-" + p["id"][:12], ""); p["age"] = int(now - p["last"]); p["existing"] = accts.get(p["id"], "")
    return {"enabled": bool(CONF.get("enrol_enabled", True)), "pending": sorted(pend, key=lambda x: x["first"]), "declined": sorted(dec, key=lambda x: -x["at"]), "approved": app}

def on_control_reply(topic, payload, retained=False):
    if topic == "umcnet/v1/enrol/hello": return enrol_hello(payload, retained)
    m = re.match(r"^umcnet/v1/[^/]+/dev/([0-9A-Fa-f]{64})/resp$", topic)
    if not m or retained: return
    try: j = json.loads(payload.decode("utf-8", "replace"))
    except Exception: return
    w = CTL["waiting"].get(j.get("id"))
    if w and w["dev"] == m.group(1).upper(): w["reply"] = j; w["event"].set()

def remember_setting(dev, cmd, reply):
    if not cmd.startswith("get "): return
    key = cmd[4:]
    if key not in DEVICE_SETTING_KEYS + STATUS_SETTING_KEYS: return
    with LOCK:
        s = SETTINGS.setdefault(dev, {"values": {}, "updated": 0, "loading": False, "error": ""})
        s["values"][key] = reply
        s["updated"] = time.time(); s["error"] = ""

def send_command(dev, cmd, who="dashboard", confirm=False, timeout=14, quiet=False):
    dev = (dev or "").upper()
    if not CONF["control_enabled"]: return {"ok": False, "error": "remote control is switched off in the settings"}
    if not re.match(r"^[0-9A-F]{64}$", dev): return {"ok": False, "error": "no such repeater"}
    if not command_allowed(cmd): return {"ok": False, "error": "that command cannot be run remotely"}
    if command_risky(cmd) and CONF["confirm_risky"] and not confirm: return {"ok": False, "needs_confirm": True, "error": "this changes how the repeater behaves; confirm to send it"}
    key = KEYS.get(dev, {}).get("key")
    if not key: return {"ok": False, "error": "no control key for this repeater yet: open Control setup and give it the key"}
    conn = CTL["conn"]
    if conn is None or not conn.up: return {"ok": False, "error": "the control link to the broker is down (%s)" % (conn.error if conn else "not started")}
    d = DEV.get(dev)
    if d is None or time.time() - d["last"] > CONF["stale_minutes"] * 60 * 4: return {"ok": False, "error": "that repeater is offline: nothing has been heard from it recently"}
    area = d["area"] or "LBA"
    with CTL["lock"]:
        n = max(CTL["last_n"] + 1, int(time.time() * 1000)); CTL["last_n"] = n
    ts = int(time.time()); cid = secrets.token_hex(6)
    msg = {"id": cid, "ts": ts, "n": n, "cmd": cmd, "sig": sign(key, dev, ts, n, cmd)}
    w = CTL["waiting"][cid] = {"dev": dev, "event": threading.Event(), "reply": None}
    try:
        conn.publish("umcnet/v1/%s/dev/%s/cmd" % (area, dev), json.dumps(msg, separators=(",", ":")).encode())
        got = w["event"].wait(timeout)
    finally:
        CTL["waiting"].pop(cid, None)
    if not got:
        if not quiet: audit(who, "command", dev[:12], audit_command(cmd, "no answer"), False)
        return {"ok": False, "error": "no answer in %d s: control may be off on the repeater, the key may not match, or its clock may be wrong" % timeout}
    r = w["reply"]; ok = bool(r.get("ok")); text = str(r.get("reply", ""))
    if not quiet or not ok: audit(who, "command", dev[:12], audit_command(cmd, text), ok)
    if ok: remember_setting(dev, cmd, text)
    CTL["last"][dev] = {"cmd": "[secret command]" if command_secret(cmd) else cmd, "reply": "[redacted]" if command_secret(cmd) else text, "ok": ok, "t": time.time()}
    return {"ok": ok, "reply": text, "error": None if ok else text}

def settings_path(): return os.path.join(CFG["data"], "settings_cache.json")

def settings_save():
    """What was last read from each repeater, so a restarted dashboard shows it at once instead of 'loading'."""
    try:
        with LOCK: snap = {d: {"values": dict(s["values"]), "updated": s["updated"]} for d, s in SETTINGS.items() if s.get("values")}
        tmp = settings_path() + ".tmp"
        with open(tmp, "w") as f: json.dump(snap, f)
        os.replace(tmp, settings_path())
    except Exception as e: sys.stderr.write("settings save: %s\n" % e)

def settings_load():
    try:
        for d, s in json.load(open(settings_path())).items():
            SETTINGS[d] = {"values": dict(s.get("values", {})), "updated": float(s.get("updated", 0)), "loading": False, "error": ""}
    except FileNotFoundError: pass
    except Exception as e: sys.stderr.write("settings load: %s\n" % e)

def preload_settings(dev, force=False):
    now = time.time()
    with LOCK:
        state = SETTINGS.setdefault(dev, {"values": {}, "updated": 0, "loading": False, "error": ""})
        if state["loading"] or not force and state["updated"] and now - state["updated"] < 900: return
        state["loading"] = True; state["error"] = ""
    good = 0; error = ""
    try:
        for key in STATUS_SETTING_KEYS + DEVICE_SETTING_KEYS:              # firmware status first: the Control tab shows it at the top
            r = send_command(dev, "get " + key, "settings-preload", timeout=10, quiet=True)
            if r.get("ok"): good += 1
            elif not error: error = r.get("error", "could not read settings")
            if "no answer" in str(r.get("error", "")): break
            time.sleep(.08)
    finally:
        with LOCK:
            state = SETTINGS.setdefault(dev, {"values": {}, "updated": 0, "loading": False, "error": ""})
            state["loading"] = False; state["error"] = "" if good else error
            if good: state["updated"] = time.time()
        if good: settings_save()

NEIGH_RX = re.compile(r"([0-9A-Fa-f]{4,16}):(\d+):(-?\d+)")
NEIGH_EVERY = 1800

def neighbour_poll_once():
    """Ask each online repeater who it hears directly. A link is confirmed by the repeater itself, with its own SNR."""
    now = time.time()
    for dev in list(KEYS):
        d = DEV.get(dev)
        if not d or not d.get("last") or now - d["last"] > CONF["stale_minutes"] * 60: continue
        r = send_command(dev, "neighbors", "neighbour-poll", timeout=12, quiet=True)
        if not r.get("ok"): continue
        rows = []
        for m in NEIGH_RX.finditer(r.get("reply") or ""):
            try: rows.append((dev, m.group(1).upper(), int(now), float(m.group(3)) / 4.0))
            except ValueError: pass
        if not rows: continue
        with LOCK:
            for a, b, t, snr in rows:
                DB.execute("INSERT INTO links(a,b,first,last,snr,rssi) VALUES(?,?,?,?,?,NULL) ON CONFLICT(a,b) DO UPDATE SET last=excluded.last, snr=excluded.snr", (a, b, t, t, snr))
            DB.execute("DELETE FROM links WHERE last < ?", (int(now) - 14 * 86400,))

def neighbour_loop():
    time.sleep(120)
    while True:
        try: neighbour_poll_once()
        except Exception as e: sys.stderr.write("neighbour poll: %s\n" % e)
        time.sleep(NEIGH_EVERY)

def confirmed_links(hours=48):
    with LOCK:
        rows = DB.execute("SELECT a, b, first, last, snr FROM links WHERE last > ?", (int(time.time()) - hours * 3600,)).fetchall()
    return [{"a": a, "b": b, "first": f, "last": l, "snr": s} for a, b, f, l, s in rows]

def settings_loop():
    """Keep every online controlled repeater's editable settings warm for the dashboard."""
    time.sleep(12)
    while True:
        try:
            now = time.time()
            for dev in list(KEYS):
                d = DEV.get(dev)
                if d and d.get("last") and now - d["last"] < CONF["stale_minutes"] * 60 * 4:
                    preload_settings(dev)
        except Exception as e: sys.stderr.write("settings preload: %s\n" % e)
        time.sleep(60)

def setup_commands(name, password, dev, area):
    key = control_key(dev, create=True) if dev else None
    lines = ["set mqtt.iata %s" % (area or "LBA"), "set mqtt.custom.host %s" % CFG["host"], "set mqtt.custom.port 443", "set mqtt.custom.transport wss", "set mqtt.custom.username %s" % name]
    if password: lines.append("set mqtt.custom.password %s" % password)
    lines += ["set mqtt.custom on", "set mqtt.raw on", "set mqtt.tx off"]
    if key: lines += ["set mqtt.control.key %s" % key, "set mqtt.control on"]
    return "\n".join(lines)

# ----------------------------------------------------------------------------- alerts
ALERT_STATE = {}
def build_alert_request(url, title, text, level="warn"):
    """The HTTP request for one alert. A ntfy address (the word 'ntfy' in it) gets ntfy's headers; an address of the form
    https://user:password@host/topic is sent with that login (HTTP basic), so a private ntfy server can be used."""
    u = urlparse(url); headers = {}
    if u.username is not None:
        import base64 as _b64
        headers["Authorization"] = "Basic " + _b64.b64encode(("%s:%s" % (unquote(u.username), unquote(u.password or ""))).encode()).decode()
        url = u._replace(netloc=(u.hostname or "") + (":%d" % u.port if u.port else "")).geturl()
    if "ntfy" in url:
        headers.update({"Title": title.encode("ascii", "replace").decode(), "Priority": "high" if level == "bad" else "default", "Tags": "warning" if level != "ok" else "white_check_mark"})
        return urllib.request.Request(url, data=text.encode(), headers=headers)
    headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=json.dumps({"title": title, "message": text, "level": level, "host": CFG["host"], "time": int(time.time())}).encode(), headers=headers)

def send_alert(title, text, level="warn", kind="x"):
    a = CONF["alerts"]
    event("alert", "%s: %s" % (title, text))
    try: DB.execute("INSERT INTO audit(ts,who,action,target,detail,ok) VALUES(?,?,?,?,?,?)", (int(time.time()), "alerts", "alert", kind, "%s - %s" % (title, text), 1))
    except Exception: pass
    if not a["enabled"] or not a["url"]: return "alerts are switched off or no address is set"
    def go():
        try:
            req = build_alert_request(a["url"], title, text, level)
            urllib.request.urlopen(req, timeout=8).read()
        except Exception as e:
            event("warn", "could not send an alert: %s" % e)
    threading.Thread(target=go, daemon=True).start()
    return None

def alert_loop():
    time.sleep(40)
    while True:
        try:
            now = time.time(); a = CONF["alerts"]; st = ALERT_STATE
            with LOCK: devs = [dict(d) for d in DEV.values()]
            for d in devs:
                name = d["name"] or d["id"][:12]; off = d["last"] and now - d["last"] > CONF["stale_minutes"] * 60; was = st.get("off:" + d["id"], False)
                if off and not was and a["offline"]: send_alert("Repeater silent: " + name, "nothing heard for %d minutes" % CONF["stale_minutes"], "warn", "offline")
                if not off and was and a["online"]: send_alert("Repeater back: " + name, "it is sending again", "ok", "online")
                st["off:" + d["id"]] = bool(off)
            for p in pending_list():
                k = "pend:" + p["name"] + p.get("prefix", "")
                if k not in st and a["pending"]: send_alert("A repeater is waiting for approval", "account %s from %s (device %s...)" % (p["name"], p.get("ip", "?"), p.get("prefix", "?")), "warn", "pending")
                st[k] = True
            hour = [e for e in EVENTS if now - e["t"] < 3600 and e["kind"] == "auth_fail"]
            if len(hour) >= CONF["auth_fail_bad"] and now - st.get("authfail", 0) > 3600 and a["auth_fail"]:
                st["authfail"] = now; send_alert("Many refused logins", "%d in the last hour" % len(hour), "bad", "auth_fail")
            c = certificate()
            if c and c.get("days") is not None and c["days"] < CONF["cert_warn_days"] and now - st.get("cert", 0) > 86400 and a["cert"]:
                st["cert"] = now; send_alert("Certificate expires soon", "%.0f days left for %s" % (c["days"], c["host"]), "bad" if c["days"] < CONF["cert_bad_days"] else "warn", "cert")
            sy = system(); used = 100.0 * (1 - sy["disk_free"] / sy["disk_total"]) if sy["disk_total"] else 0
            if used > CONF["disk_warn_pct"] and now - st.get("disk", 0) > 86400 and a["disk"]:
                st["disk"] = now; send_alert("Disk nearly full", "%.0f%% used" % used, "warn", "disk")
        except Exception as e:
            sys.stderr.write("alerts: %s\n" % e)
        time.sleep(30)

def pending_list():
    out = []
    try: accs = accounts()
    except Exception: return out
    with LOCK:
        for a in accs:
            if a["role"] != "repeater" or not (a.get("state") == "pending" or not a["device"]) or a.get("state") == "blocked": continue
            cl = [c for c in CLIENTS.values() if c.get("user") == a["name"] and c.get("state") == "connected"]
            out.append({"name": a["name"], "prefix": (cl[0]["client"].rsplit("-", 1)[-1] if cl and "-" in cl[0]["client"] else ""), "ip": cl[0]["ip"] if cl else "", "since": cl[0].get("since", 0) if cl else 0, "online": bool(cl)})
    return out

# ----------------------------------------------------------------------------- the overview the page draws
CLOCK = {"t": 0, "v": None}
def clock_status():
    """The server clock as chrony sees it: source, stratum, offset. None when chrony is not installed."""
    if time.time() - CLOCK["t"] < 30: return CLOCK["v"]
    CLOCK["t"] = time.time(); v = None
    try:
        out = subprocess.run(["chronyc", "-c", "tracking"], capture_output=True, text=True, timeout=5).stdout.strip().split(",")
        if len(out) >= 14:
            names = {}
            try:
                for l in subprocess.run(["chronyc", "-c", "-n", "sources"], capture_output=True, text=True, timeout=5).stdout.splitlines():
                    f = l.split(",")
                    if len(f) > 2: names[f[2]] = f[1]
            except Exception: pass
            src = out[1]; v = {"source": src, "stratum": int(out[2]), "offset": float(out[4]), "rms": float(out[6]), "freq_ppm": float(out[7]), "leap": out[13],
                               "ok": out[13] == "Normal" and int(out[2]) < 16 and abs(float(out[4])) < 0.1, "npl": "npl.co.uk" in src or src in ("139.143.5.30", "139.143.5.31")}
    except Exception: v = None
    CLOCK["v"] = v
    return v

def diagnostics(sysinfo, accs, cert):
    out = []; now = time.time(); C = CONF
    def add(level, title, detail): out.append({"level": level, "title": title, "detail": detail})
    add("ok" if MQTT["state"] == "connected" else "bad", "Dashboard link to the broker", "connected since %s" % time.strftime("%H:%M:%S", time.localtime(MQTT["since"])) if MQTT["state"] == "connected" else "not connected: %s" % MQTT["error"])
    add("ok" if CTL_STATUS.get("state") == "connected" else "warn", "Control link to the broker", "ready" if CTL_STATUS.get("state") == "connected" else "not ready (%s)" % CTL_STATUS.get("error", CTL_STATUS.get("state", "")))
    for u, st in sysinfo["services"].items(): add("ok" if st == "active" else "bad", "Service " + u, st)
    ck = sysinfo.get("clock")
    if ck: add("ok" if ck["ok"] else "warn", "Server clock", "%s, stratum %d, %+.1f ms (repeaters take their time from here)" % ("National Physical Laboratory" if ck["npl"] else ck["source"], ck["stratum"], ck["offset"] * 1000) if ck["ok"] else "not synchronised (%s, %+.3f s): the repeaters' time comes from here, so check chrony" % (ck["leap"], ck["offset"]))
    up = sysnum("$SYS/broker/uptime", -1)
    if up >= 0: add("warn" if up < 300 else "ok", "Broker uptime", "%d min%s" % (up // 60, " (it restarted recently)" if up < 300 else ""))
    if cert and "days" in cert: add("bad" if cert["days"] < C["cert_bad_days"] else "warn" if cert["days"] < C["cert_warn_days"] else "ok", "TLS certificate for %s" % cert["host"], "%.0f days left (%s)" % (cert["days"], cert.get("issuer", "")))
    elif cert: add("bad", "TLS certificate", cert.get("error", "cannot read it"))
    used = 100.0 * (1 - sysinfo["disk_free"] / sysinfo["disk_total"]) if sysinfo["disk_total"] else 0
    add("bad" if used > 95 else "warn" if used > C["disk_warn_pct"] else "ok", "Disk space", "%.0f%% used" % used)
    mu = 100.0 * (1 - sysinfo["mem_avail"] / sysinfo["mem_total"]) if sysinfo["mem_total"] else 0
    add("bad" if mu > 95 else "warn" if mu > C["mem_warn_pct"] else "ok", "Memory", "%.0f%% used" % mu)
    if sysinfo["load"]: add("warn" if sysinfo["load"][0] > (sysinfo["cores"] or 1) * 1.5 else "ok", "Load", "%.2f %.2f %.2f on %d core(s)" % (*sysinfo["load"], sysinfo["cores"] or 1))
    hour = [e for e in EVENTS if now - e["t"] < 3600]
    fails = [e for e in hour if e["kind"] == "auth_fail"]; ips = collections.Counter(e["ip"] or "?" for e in fails)
    add("bad" if len(fails) >= C["auth_fail_bad"] else "warn" if len(fails) >= C["auth_fail_warn"] else "ok", "Refused logins, last hour", "%d%s" % (len(fails), " from " + ", ".join("%s x%d" % x for x in ips.most_common(4)) if fails else ""))
    for c in CLIENTS.values():
        h = [t for t in c.get("history", []) if now - t < 600]
        if len(h) >= C["flap_count"]: add("warn", "Reconnecting often: " + (c.get("user") or c["client"]), "%d connections in 10 minutes (%s): a weak WiFi link or two devices sharing one account" % (len(h), c.get("ip", "")))
    for pnd in pending_list():
        add("warn", "Waiting for approval: " + pnd["name"], "connected from %s as device %s... : approve it on the Accounts tab" % (pnd["ip"] or "?", pnd["prefix"] or "?") if pnd["online"] else "created, nobody has used it yet")
    by_user = {}
    for c in CLIENTS.values():
        if c.get("state") == "connected": by_user.setdefault(c.get("user"), []).append(c)
    for a in accs:
        if a["role"] != "repeater": continue
        if a["state"] == "blocked": add("ok", "Blocked: " + a["name"], "everything is refused for this account"); continue
        if a["device"] and a["state"] != "pending":
            cl = by_user.get(a["name"], [])
            if not cl: add("warn", "Repeater offline: " + a["name"], "last connected %s" % (time.strftime("%d %b %H:%M", time.localtime(a["last"])) if a["last"] else "never since this dashboard started"))
            for c in cl:
                pre = c["client"].rsplit("-", 1)[-1].upper() if "-" in c["client"] else ""
                if pre and re.match(r"^[0-9A-F]{6}$", pre) and not a["device"].startswith(pre): add("bad", "Different device on %s" % a["name"], "the connected device starts %s but the account is bound to %s... : someone else may be using these credentials" % (pre, a["device"][:6]))
    for d in DEV.values():
        age = now - d["last"] if d["last"] else None; nm = d["name"] or d["id"][:12]
        if age is None: add("warn", "No data yet from %s" % nm, "known only from its saved status message; nothing live since the dashboard started")
        elif age > C["stale_minutes"] * 60: add("warn", "No data from %s" % nm, "last heard %d min ago" % (age // 60))
        if d["skew"] is not None and abs(d["skew"]) > C["skew_seconds"]: add("warn", "Clock off on %s" % nm, "%+.0f s against this server (its NTP may be down)" % d["skew"])
        if d["status"] == "offline" and (age is None or age > 300): add("warn", "%s reports itself offline" % nm, "its last status message said offline and nothing has arrived since")
    dr = sysnum("$SYS/broker/load/publish/dropped/1min")
    if dr > 0: add("warn", "Broker is dropping messages", "%.1f a minute (a slow subscriber or full queues)" % dr)
    # mesh issues: nodes gone quiet for a day, repeaters with no position, low batteries, a bridge that holds packets back
    # Our own repeaters are checked one by one (and they are not "stale" while they report). Other nodes heard
    # across the mesh are summarised in one line, so the list stays readable.
    own = {d["id"] for d in DEV.values() if d["last"] and now - d["last"] < CONF["stale_minutes"] * 60}
    quiet = [(n["name"] or k[:8]) for k, n in NODES.items() if k not in own and n["type"] in (2, 3) and n["last"] and 86400 < now - n["last"] < 30 * 86400]
    if quiet:
        add("warn", "%d mesh node%s quiet for over a day" % (len(quiet), "" if len(quiet) == 1 else "s"), ", ".join(sorted(quiet, key=str.lower)[:15]) + (" …" if len(quiet) > 15 else ""))
    for d in DEV.values():
        sv = (SETTINGS.get(d["id"]) or {}).get("values", {})          # the position the repeater reports for itself (read over the control link)
        has_pos = d.get("lat") is not None or any(str(sv.get(k, "")).strip(" >") not in ("", "0", "0.0", "(not set)") for k in ("lat",))
        if d["id"] in own and not has_pos and not (CONF.get("locations") or {}).get(d["id"]):
            add("warn", "No position: %s" % (d["name"] or d["id"][:8]), "this repeater has no position, so it cannot be placed on the map")
    for d in DEV.values():
        nm = d["name"] or d["id"][:12]; mv = (d.get("stats") or {}).get("battery_mv")
        if mv and mv < 3500 and now - d["last"] < 900: add("warn", "Low battery: %s" % nm, "%.2f V" % (mv / 1000))
        b = d.get("bridge") or {}
        if b.get("heard") and b.get("dropped") and b["dropped"] / max(1, b["heard"]) > 0.10:
            add("warn", "Bridge holding back packets: %s" % nm, "%d of %d heard were held back by the rate limit" % (b["dropped"], b["heard"]))
    return out

def prometheus_text():
    """Node and traffic numbers in the Prometheus text format (behind the dashboard's login)."""
    now = time.time(); out = []
    def g(name, help_, samples):
        out.append("# HELP umcnet_%s %s" % (name, help_)); out.append("# TYPE umcnet_%s gauge" % name)
        for labels, v in samples: out.append("umcnet_%s%s %s" % (name, ("{%s}" % labels) if labels else "", v))
    reps = [d for d in DEV.values() if d["last"] and now - d["last"] < CONF["stale_minutes"] * 60]
    g("repeaters_online", "Repeaters reporting now", [("", len(reps))])
    g("packets_per_minute", "Packets heard per minute by each repeater", [('repeater="%s"' % (d["name"] or d["id"][:8]), round(rate_per_min("pkt:" + d["id"], 300), 2)) for d in reps])
    g("bridge_passed_total", "Packets each bridge has passed on to its radio", [('repeater="%s"' % (d["name"] or d["id"][:8]), (d.get("bridge") or {}).get("passed", 0)) for d in reps])
    g("bridge_held_total", "Packets each bridge held back by its rate limit", [('repeater="%s"' % (d["name"] or d["id"][:8]), (d.get("bridge") or {}).get("dropped", 0)) for d in reps])
    g("clock_skew_seconds", "Each repeater's clock against this server", [('repeater="%s"' % (d["name"] or d["id"][:8]), round(d["skew"] or 0, 3)) for d in reps if d.get("skew") is not None])
    g("nodes_known", "Nodes heard in the last 30 days", [("", sum(1 for n in NODES.values() if n["last"] and now - n["last"] < 30 * 86400))])
    g("confirmed_links", "Neighbour links confirmed in the last 48 hours", [("", len(confirmed_links()))])
    ck = CLOCK.get("v") or {}
    g("server_clock_offset_seconds", "This server's clock against its time source", [("", ck.get("offset", 0))])
    g("broker_up", "1 when the dashboard's link to the broker is up", [("", 1 if MQTT.get("state") == "connected" else 0)])
    return "\n".join(out) + "\n"

def overview():
    sysinfo = system(); cert = certificate(); accs = accounts(); now = time.time()
    with LOCK:
        devs = []
        for d in DEV.values():
            x = dict(d); x["types"] = dict(d["types"]); x["topics"] = dict(d["topics"]); x["pm"] = round(rate_per_min("pkt:" + d["id"], 300), 2); x["has_key"] = d["id"] in KEYS; x["label"] = CONF["labels"].get(d["id"], {}); x["last_cmd"] = CTL["last"].get(d["id"]); x["age"] = round(now - d["last"], 1) if d["last"] else 10 ** 9
            cached = SETTINGS.get(d["id"], {}); x["settings"] = dict(cached.get("values", {})); x["settings_updated"] = cached.get("updated", 0); x["settings_loading"] = bool(cached.get("loading")); x["settings_error"] = cached.get("error", ""); devs.append(x)
        devs.sort(key=lambda d: -d["last"])
        clients = []
        for c in CLIENTS.values():
            x = {k: v for k, v in c.items() if k != "history"}; x["age"] = round(now - c.get("since", now)); x["recent"] = len([t for t in c.get("history", []) if now - t < 3600]); clients.append(x)
        clients.sort(key=lambda c: (c.get("state") != "connected", -c.get("last", c.get("since", 0))))
        clients = [c for i, c in enumerate(clients) if c.get("state") == "connected" or i < 60]       # all that are connected, then the most recent that left
        for cid in [k for k, c in CLIENTS.items() if c.get("state") != "connected" and now - c.get("last", now) > 86400]: del CLIENTS[cid]
        overlap = []
        ids = [d["id"] for d in devs[:12]]
        for a in ids:
            overlap.append([PAIRS.get(tuple(sorted((a, b))), 0) if a != b else None for b in ids])
        multi = collections.Counter(len(e["devs"]) for e in HEARD.values())
        types = collections.Counter()
        for d in DEV.values(): types.update(d["types"])
        sysd = {k: v[0] for k, v in SYS.items()}
        try: msg_last = (DB.execute("SELECT MAX(id) FROM messages").fetchone() or [0])[0] or 0
        except Exception: msg_last = 0
        res = {"routes": packet_routes(), "msg_last": msg_last, "version": VERSION, "now": now, "started": START, "mqtt": dict(MQTT), "sys": sysd, "system": sysinfo, "cert": cert, "devices": devs, "clients": clients, "accounts": accs,
               "packets": [dict(p) for p in list(PKTS)[-60:]][::-1], "events": [dict(e) for e in list(EVENTS)[-80:]][::-1], "log": [dict(l) for l in list(LOG)[-60:]][::-1], "count": dict(COUNT),
               "rates": {"messages": rate_per_min("messages"), "packets": rate_per_min("packets"), "unique": rate_per_min("unique")},
               "overlap": {"ids": ids, "names": [DEV[i]["name"] or i[:8] for i in ids], "m": overlap}, "heard_by": dict(sorted(multi.items())), "types": dict(types),
               "latency": {"n": len(LATENCY), "avg": round(sum(LATENCY) / len(LATENCY), 2) if LATENCY else None, "max": round(max(LATENCY), 2) if LATENCY else None},
               "ev_hour": dict(collections.Counter(e["kind"] for e in EVENTS if now - e["t"] < 3600)), "host": CFG["host"], "config": CONF, "control": {"state": CTL_STATUS.get("state", "idle"), "error": CTL_STATUS.get("error", ""), "keys": sorted(KEYS)}}
    res["pending"] = pending_list()
    res["enrol"] = enrol_view()
    res["diagnostics"] = diagnostics(sysinfo, accs, cert)
    return res

def public_overview():
    """Operational data safe to publish: no accounts, addresses, logs, keys or write state."""
    o = overview(); now = o["now"]; devices = []
    for d in o["devices"]:
        devices.append({k: d.get(k) for k in ("id", "area", "name", "first", "last", "last_status", "status", "model", "fw", "radio", "client", "repeat", "stats", "n_raw", "n_pkt", "n_rx", "n_tx", "types", "rssi", "snr", "bytes", "skew", "topics", "pm", "label", "age")})
        br = d.get("bridge") or {}
        devices[-1]["pm"] = d.get("pm"); devices[-1]["age"] = d.get("age")
        devices[-1]["bridge"] = {k: br.get(k) for k in ("heard_pm", "passed_pm", "dropped_pm")} if br else None      # rates only: how much each bridge passes on
        devices[-1]["label"] = {"label": d.get("label", {}).get("label", "")}
        devices[-1]["settings"] = {k: d.get("settings", {}).get(k) for k in PUBLIC_SETTING_KEYS if k in d.get("settings", {})}
        devices[-1]["settings_updated"] = d.get("settings_updated", 0)
    packets = [{k: p.get(k) for k in ("t", "area", "dev", "dname", "dir", "type", "flood", "hops", "via", "src", "dst", "chan", "key", "name", "len", "rssi", "snr")} for p in o["packets"]]
    return {"version": VERSION, "now": now, "title": CONF["title"], "mqtt": {"state": o["mqtt"].get("state", "unknown")}, "devices": devices,
            "packets": packets, "totals": {"packets": sum(d.get("n_pkt", 0) for d in devices)}, "nodes": len(NODES),
            "rates": o["rates"], "types": o["types"], "heard_by": o["heard_by"], "latency": o["latency"]}

def public_network_view():
    n = network_view()
    nodes = [{k: v for k, v in node.items() if k not in ("lat", "lon")} for node in n["nodes"]]
    return {"now": n["now"], "nodes": nodes, "links": n["links"], "journeys": n["journeys"]}

# ----------------------------------------------------------------------------- HTTP
def csv_text(header, rows):
    b = io.StringIO(); w = csv.writer(b); w.writerow(header)
    for r in rows: w.writerow(r)
    return b.getvalue()

class H(BaseHTTPRequestHandler):
    server_version = "umcnet-dash"
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        u = urlparse(self.path)
        try:
            if self.headers.get("X-UMC-Dash") != "1": return self.send(403, '{"error":"missing header"}')
            n = int(self.headers.get("Content-Length", "0") or 0)
            if n > 20000: return self.send(413, '{"error":"too big"}')
            body = json.loads(self.rfile.read(n).decode() or "{}")
            who = (self.headers.get("X-UMC-User") or "admin").strip() or "admin"; p = u.path; role = role_of(who)
            if role != "admin":
                if p not in OWNER_POSTS: return self.send(403, json.dumps({"ok": False, "error": "only the administrator can do that"}))
                if role == "viewer" and p != "/api/password": return self.send(403, json.dumps({"ok": False, "error": "this login can only look"}))
                if p.startswith("/api/control") and not may_control(who, body.get("device")): return self.send(403, json.dumps({"ok": False, "error": "you can only control your own repeater"}))
            if p == "/api/users/save":
                r = users_save(body); audit(who, "user saved", str(body.get("name", "")), r.get("error") or "ok", bool(r.get("ok"))); return self.send(200, json.dumps(r))
            if p == "/api/users/remove":
                r = users_remove(body.get("name")); audit(who, "user removed", str(body.get("name", "")), r.get("error") or "ok", bool(r.get("ok"))); return self.send(200, json.dumps(r))
            if p == "/api/control":
                return self.send(200, json.dumps(send_command(body.get("device"), str(body.get("cmd", "")), who, bool(body.get("confirm")))))
            if p == "/api/control/preload":
                dev = str(body.get("device", "")).upper()
                if dev in DEV: threading.Thread(target=preload_settings, args=(dev, True), daemon=True).start()
                return self.send(200, '{"ok":true}')
            if p == "/api/control/batch":
                cmds = [str(c) for c in (body.get("cmds") or [])][:30]; res = []
                for c in cmds:
                    r = send_command(body.get("device"), c, who, bool(body.get("confirm"))); res.append({"cmd": c, **r})
                    if r.get("error") and "no answer" in str(r["error"]) and len(res) >= 2 and not any(x.get("ok") for x in res): break     # nobody is answering: stop early
                return self.send(200, json.dumps({"results": res}))
            if p == "/api/control/setup":
                dev = str(body.get("device", "")).upper(); name = str(body.get("account", ""))
                if body.get("newkey"): control_key(dev, new=True); audit(who, "control key renewed", dev[:12], "")
                d = DEV.get(dev); text = setup_commands(name or "YOUR-ACCOUNT", body.get("password"), dev, d["area"] if d else "LBA")
                audit(who, "control setup shown", dev[:12], ""); return self.send(200, json.dumps({"ok": True, "text": text}))
            if p == "/api/config":
                err = conf_update(body.get("config", body)); audit(who, "settings changed", "dashboard", ",".join(k for k in (body.get("config", body) or {}))[:100], not err)
                return self.send(200, json.dumps({"ok": not err, "error": err, "config": CONF}))
            if p.startswith("/api/accounts/"):
                op = p.rsplit("/", 1)[-1]; name = str(body.get("name", ""))
                m = {"add": "user_add", "remove": "user_remove", "approve": "user_device", "block": "user_state", "unblock": "user_state", "passwd": "user_passwd", "pending": "user_state"}.get(op)
                if not m: return self.send(404, '{"error":"unknown"}')
                req = {"op": m, "name": name}
                if op == "add": req.update(role=body.get("role", "repeater"), device=body.get("device", ""))
                if op == "approve":
                    dev = str(body.get("device", "")).upper()
                    pend = [x for x in pending_list() if x["name"] == name]
                    if pend and pend[0]["prefix"] and not dev.startswith(pend[0]["prefix"].upper()): return self.send(200, json.dumps({"ok": False, "error": "that device id does not match the repeater that connected (it starts %s)" % pend[0]["prefix"]}))
                    req["device"] = dev
                if op in ("block", "unblock", "pending"): req["state"] = {"block": "blocked", "unblock": "approved", "pending": "pending"}[op]
                r = admin_call(**req); audit(who, "account " + op, name, r.get("error") or "ok", bool(r.get("ok")))
                if r.get("ok"): export_accounts_soon()
                out = {"ok": bool(r.get("ok")), "error": r.get("error") or (None if r.get("ok") else r.get("output")), "password": r.get("password"), "output": r.get("output")}
                if op == "add" and r.get("ok") and r.get("password") and body.get("role", "repeater") == "repeater":
                    dev = str(body.get("device", "")).upper()
                    try: out["join"] = make_join_code(name, r["password"], CONF["join_iata"], control_key(dev, create=True) if re.match(r"^[0-9A-F]{64}$", dev) else None, CONF["join_bridge"])
                    except ValueError as e: out["join_error"] = str(e)
                return self.send(200, json.dumps(out))
            if p == "/api/groups/add":
                nm = str(body.get("name", "")).strip()
                if not re.match(r"^#[a-z0-9][a-z0-9-]{0,30}$", nm): return self.send(200, json.dumps({"ok": False, "error": "a group name starts with # and has letters, digits and dashes"}))
                if any(c.get("name") == nm for c in CONF["messages"]["channels"]): return self.send(200, json.dumps({"ok": True, "note": "already added"}))
                CONF["messages"]["channels"].append({"name": nm}); conf_save(); audit(who, "group added", nm, "public hashtag group found by the scan")
                with LOCK: MSGSTAT.pop("%02X" % MSG.Channel(nm).hash, None)
                return self.send(200, json.dumps({"ok": True}))
            if p == "/api/messages/send":
                own = me_view(who)["sender"] or re.sub(r"[^A-Za-z0-9._-]", "", who.upper())[:24] or "USER"
                sender = (body.get("sender") or None) if role == "admin" else own        # users send under their own name only
                return self.send(200, json.dumps(send_message(who, str(body.get("channel", "")), str(body.get("region", "")), str(body.get("text", "")), sender)))
            if p == "/api/enrol/approve":
                r = enrol_approve(who, body.get("id", ""), body.get("name"), body.get("bridge")); return self.send(200, json.dumps(r))
            if p == "/api/enrol/decline": return self.send(200, json.dumps(enrol_decline(who, body.get("id", ""))))
            if p == "/api/enrol/forget": return self.send(200, json.dumps(enrol_forget(who, body.get("id", ""))))
            if p == "/api/join":
                name = str(body.get("name", "")); acc = next((a for a in accounts() if a["name"] == name), None)
                if not acc or acc["role"] != "repeater" or acc.get("state") == "blocked": return self.send(200, json.dumps({"ok": False, "error": "that is not an active repeater account"}))
                r = admin_call(op="user_passwd", name=name)
                if not r.get("ok") or not r.get("password"): audit(who, "join code", name, r.get("error") or "failed", False); return self.send(200, json.dumps({"ok": False, "error": r.get("error") or r.get("output") or "could not make a new password"}))
                try: code = make_join_code(name, r["password"], CONF["join_iata"], control_key(acc["device"], create=True) if acc["device"] else None, bool(body.get("bridge", CONF["join_bridge"])))
                except ValueError as e: return self.send(200, json.dumps({"ok": False, "error": str(e)}))
                audit(who, "join code", name, "new password; remote control key %s" % ("included" if acc["device"] else "not yet (not approved)"))
                return self.send(200, json.dumps({"ok": True, "join": code, "has_key": bool(acc["device"])}))
            if p == "/api/password":
                r = admin_call(op="dash_password", user=who, current=str(body.get("current", "")), new=str(body.get("new", ""))); audit(who, "dashboard password", who, r.get("error") or "changed", bool(r.get("ok")))
                return self.send(200, json.dumps(r))
            if p == "/api/service":
                r = admin_call(op="service", name=str(body.get("name", "")), action="restart"); audit(who, "service restart", str(body.get("name")), r.get("error") or "ok", bool(r.get("ok")))
                return self.send(200, json.dumps(r))
            if p == "/api/alerts/test":
                err = send_alert("Test alert", "If you can read this, alerts work.", "ok", "test"); return self.send(200, json.dumps({"ok": not err, "error": err}))
            return self.send(404, '{"error":"not found"}')
        except Exception as e:
            return self.send(500, json.dumps({"error": str(e)}))

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        try:
            if u.path in ("/public", "/public/", "/public/index.html"): return self.send(200, open(CFG["public_static"], "rb").read(), "text/html")
            if u.path == "/public/api/overview": return self.send(200, json.dumps(public_overview(), default=str))
            if u.path == "/public/api/network": return self.send(200, json.dumps(public_network_view(), default=str))
            if u.path == "/public/api/health": return self.send(200, json.dumps({"ok": True, "mqtt": MQTT["state"]}))
            if u.path == "/api/network": return self.send(200, json.dumps(network_view(float(parse_qs(u.query).get("hours", [CONF["map_hours"]])[0]))))
            if u.path == "/api/messages":
                q = parse_qs(u.query); g = lambda k, d="": q.get(k, [d])[0]
                try: return self.send(200, json.dumps(messages_view(g("channel"), g("region"), g("dir"), int(g("before", "0") or 0), int(g("limit", "100") or 100), g("q"))))
                except ValueError: return self.send(400, '{"error":"bad request"}')
            if u.path == "/api/audit":
                secs = max(60, min(90 * 86400, int(q.get("range", ["604800"])[0])))
                rows = DB.execute("SELECT ts,who,action,target,detail,ok FROM audit WHERE ts>=? ORDER BY ts DESC LIMIT 500", (int(time.time()) - secs,)).fetchall()
                return self.send(200, json.dumps([dict(zip(("ts", "who", "action", "target", "detail", "ok"), r)) for r in rows]))
            who = (self.headers.get("X-UMC-User") or "admin").strip() or "admin"; role = role_of(who)
            if u.path.startswith("/api/export/") and role != "admin": return self.send(403, '{"error":"only the administrator can export"}')
            if u.path == "/api/export/events.csv":
                rows = DB.execute("SELECT datetime(ts,'unixepoch'),kind,client,user,ip,text FROM events ORDER BY ts DESC LIMIT 20000").fetchall()
                return self.send(200, csv_text(("time (UTC)", "kind", "client", "user", "ip", "text"), rows), "text/csv")
            if u.path == "/api/export/audit.csv":
                rows = DB.execute("SELECT datetime(ts,'unixepoch'),who,action,target,detail,ok FROM audit ORDER BY ts DESC LIMIT 20000").fetchall()
                return self.send(200, csv_text(("time (UTC)", "who", "action", "target", "detail", "ok"), rows), "text/csv")
            if u.path == "/api/export/devices.csv":
                with LOCK: rows = [(d["id"], d["name"], d["area"], d["model"], d["fw"], d["radio"], d["status"], d["n_rx"], d["n_tx"], round(d["last"]), CONF["labels"].get(d["id"], {}).get("label", "")) for d in DEV.values()]
                return self.send(200, csv_text(("device id", "name", "area", "model", "firmware", "radio", "status", "received", "sent", "last data (epoch)", "label"), rows), "text/csv")
            if u.path == "/api/export/config.json": return self.send(200, json.dumps(CONF, indent=1))
            if u.path in ("/", "/index.html"): return self.send(200, open(CFG["static"], "rb").read(), "text/html")
            if u.path == "/api/groups":
                return self.send(200, json.dumps({"scan": scan_public_groups(), "rooms": rooms_heard(), "names": len(SCAN_NAMES), "packets": len(RECENT_GRP)}))
            if u.path == "/metrics":
                return self.send(200, prometheus_text(), ctype="text/plain; version=0.0.4")
            if u.path == "/api/overview":
                o = overview(); o["me"] = me_view(who)
                if role == "admin": o["web_users"] = CONF["web_users"]
                else:                                           # nothing secret leaves for other users
                    c = json.loads(json.dumps(o["config"])); c.get("alerts", {})["url"] = "(set by the administrator)" if c.get("alerts", {}).get("url") else ""; c.pop("web_users", None); o["config"] = c
                return self.send(200, json.dumps(o, default=str))
            if u.path == "/api/history":
                keys = [k for k in (q.get("k", [""])[0]).split(",") if k][:60]; secs = max(60, min(14 * 86400, int(q.get("range", ["3600"])[0])))
                return self.send(200, json.dumps(history(keys, secs)))
            if u.path == "/api/events":
                secs = max(60, min(14 * 86400, int(q.get("range", ["86400"])[0]))); kind = q.get("kind", [""])[0]
                rows = DB.execute("SELECT ts,kind,client,user,ip,text FROM events WHERE ts>=? " + ("AND kind=? " if kind else "") + "ORDER BY ts DESC LIMIT 500", (int(time.time()) - secs,) + ((kind,) if kind else ())).fetchall()
                return self.send(200, json.dumps([dict(zip(("ts", "kind", "client", "user", "ip", "text"), r)) for r in rows]))
            if u.path == "/api/health": return self.send(200, json.dumps({"ok": True, "mqtt": MQTT["state"]}))
            return self.send(404, '{"error":"not found"}')
        except Exception as e:
            return self.send(500, json.dumps({"error": str(e)}))

def export_accounts_soon():
    pass                                         # the account list is re-read from its copy on every request

def main():
    db_init(); conf_load(); keys_load(); nodes_load(); enrol_load(); settings_load(); event("start", "dashboard %s started" % VERSION); cpu_pct()       # the first reading only primes the counter
    for fn in (mqtt_loop, control_loop, journal_loop, sampler_loop, alert_loop, locate_loop, settings_loop, bridge_poll_loop, neighbour_loop, group_scan_loop): threading.Thread(target=fn, daemon=True).start()
    srv = ThreadingHTTPServer((CFG["http_host"], CFG["http_port"]), H); srv.daemon_threads = True
    print("umcnet-dash %s on http://%s:%d" % (VERSION, CFG["http_host"], CFG["http_port"]), flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
