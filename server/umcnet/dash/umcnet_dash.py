#!/usr/bin/env python3
"""UMC Net dashboard: everything the broker, the repeaters and this server can tell you, in one page.

Reads the broker as a read-only 'monitor' account (its $SYS statistics and the meshcore/# topics), tails the
broker's log for who connects and who is refused, samples the machine, and serves a JSON API and the page on
127.0.0.1 for Caddy to put behind a login. Python standard library only: no packages to install.
"""
import base64, collections, csv, hashlib, hmac, http.client, io, json, math, os, re, secrets, shutil, socket, sqlite3, ssl, struct, subprocess, sys, threading, time, unicodedata, urllib.error, urllib.request
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
    "backup": os.environ.get("DASH_BACKUP", "1") == "1", "backup_dir": os.environ.get("DASH_BACKUP_DIR", ""),      # empty = a "backups" folder beside the database
}
LOCK = threading.RLock()
START = time.time()
VERSION = "2.40"

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
CTRL_RX = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\u200b-\u200f\ufeff]")
def clean_text(s, n=200):
    """One line of text with no control, line-break or direction-override characters (names and titles that come from the radio or from a catalogue)."""
    return re.sub(r" {2,}", " ", CTRL_RX.sub(" ", str(s))).strip()[:n].strip()

def finite_num(x, lo=None, hi=None):
    """x as a finite float inside [lo, hi], else None. Never raises, whatever x is (strings such as '1e999' or 'nan' give None)."""
    try: f = float(x)
    except (TypeError, ValueError, OverflowError): return None
    if not math.isfinite(f) or (lo is not None and f < lo) or (hi is not None and f > hi): return None
    return f

def finite_int(x, lo=None, hi=None):
    f = finite_num(x, lo, hi)
    if f is None: return None
    try: return int(f)
    except (ValueError, OverflowError): return None

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
            out["key"] = p[:4].hex().upper(); out["fkey"] = p[:32].hex().upper(); out["hdr"] = h; out["advp"] = bytes(p); j = 100; f = p[j]; j += 1
            out["atype"] = f & 0x0F
            if f & 0x10:
                if j + 8 <= len(p):
                    la, lo = struct.unpack("<ii", p[j:j + 8]); la, lo = la / 1e6, lo / 1e6
                    if (la or lo) and abs(la) <= 90 and abs(lo) <= 180: out["lat"], out["lon"] = la, lo
                j += 8
            if f & 0x20: j += 2
            if f & 0x40: j += 2
            if f & 0x80 and j < len(p): out["name"] = clean_text(p[j:].decode("utf-8", "replace").split("\0")[0], 64)
        return out
    except Exception:
        return None

def node_for_hash(h):
    """The one known node whose key starts with this hash, or None when it fits none or several."""
    if not h: return None
    hits = [k for k in list(NODES) if k.startswith(h.upper())]
    return hits[0] if len(hits) == 1 else None

def hop_name(h):
    k = node_for_hash(h)
    return (NODES[k]["name"] or h) if k else h

def note_network(did, info, snr, rssi, now):
    """Called for every packet a connected repeater heard: learn the node behind an advert, and the link to it."""
    if not info: return
    sender = None
    if info.get("flood"):
        try: hop_note(did, info.get("hops"), now)
        except Exception as e: sys.stderr.write("hop histogram: %s\n" % e)
    if info.get("fkey"):
        k = info["fkey"]; n = NODES.get(k); fresh = n is None
        if fresh:
            if len(NODES) >= 3000: return
            try: ok = advert_note(k, info, now, rx=did, fresh=True)
            except Exception as e: sys.stderr.write("advert check: %s\n" % e); ok = False
            if ok is not True: return                      # a node is recorded only once its advert's signature has checked out: forged adverts create nothing
            n = NODES[k] = {"key": k, "name": "", "type": 0, "lat": None, "lon": None, "first": now, "last": 0, "adverts": 0}
        n["last"] = now; n["adverts"] += 1
        if info.get("name"): n["name"] = info["name"]
        if info.get("atype"): n["type"] = info["atype"]
        if info.get("lat") is not None: n["lat"], n["lon"] = info["lat"], info["lon"]
        if fresh:
            try: newnode_seen(k, n, did, now)
            except Exception as e: sys.stderr.write("new node: %s\n" % e)
        sender = k
        if not fresh:
            try: advert_note(k, info, now, rx=did)
            except Exception as e: sys.stderr.write("advert check: %s\n" % e)
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
    if info.get("flood") and info.get("path"):
        try: route_note(info["path"], did, now)
        except Exception as e: sys.stderr.write("route: %s\n" % e)
    if sender and info.get("flood") and info.get("hops") == 0: snr_note(sender, snr, now)       # only then is the signal the sender's own, not a repeater's
    if sender:
        with TRAFFIC_LOCK: TRAFFIC_BUF[(int(now) // 3600 * 3600, sender, did, str(info["type"]), min(int(info.get("hops") or 0), 15))] += 1
    if sender or info.get("path"):
        JOURNEYS.append({"t": now, "pkt": info.get("pkt"), "size": info.get("size"), "route_type": info.get("route_type"), "scope": info.get("scope"), "type": info["type"], "flood": info["flood"], "hops": info["hops"], "from": sender or (info.get("src") or info.get("chan") or ""), "path": [{"h": h, "n": hop_name(h)} for h in info.get("path", [])], "to": did, "snr": snr, "rssi": rssi})

def scope_names():
    """Region names a scoped packet's code can be matched against: the Yorkshire set plus any the operator has added."""
    base = ["yorkshire", "eng-yh", "northwest", "eng-ne", "derbyshire", "lincolnshire", "sheffield", "wakefield", "Sheffield", "Wakefield"]
    extra = [r for r in (CONF.get("messages", {}).get("regions") or []) if r]
    return list(dict.fromkeys(base + extra))

def scope_audit(hours=24):
    """Per repeater: how many floods it heard that were scoped to a region, unscoped, and direct, and which regions."""
    cut = time.time() - hours * 3600
    rows = {}
    for j in list(JOURNEYS):
        if j.get("t", 0) < cut or j.get("route_type") is None: continue
        r = rows.setdefault(j["to"], {"repeater": (DEV.get(j["to"]) or {}).get("name") or j["to"][:8], "scoped": 0, "unscoped": 0, "direct": 0, "regions": collections.Counter()})
        rt = j["route_type"]
        if rt in (0, 3):
            r["scoped"] += 1 if rt == 0 else 0; r["direct"] += 1 if rt == 3 else 0
            if j.get("scope"): r["regions"][j["scope"]] += 1
        elif rt == 1: r["unscoped"] += 1
        else: r["direct"] += 1
    out = []
    for r in rows.values():
        out.append({"repeater": r["repeater"], "scoped": r["scoped"], "unscoped": r["unscoped"], "direct": r["direct"], "regions": dict(r["regions"].most_common(8))})
    return sorted(out, key=lambda x: -(x["unscoped"] + x["scoped"]))

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
        for k, n in list(NODES.items()):
            d = DEV.get(k); seen.add(k)
            conn = bool(d and d["last"] and now - d["last"] < CONF["stale_minutes"] * 60)
            if not conn and n["last"] < cutoff: continue                       # not on the network and not heard lately: not on the map
            nodes.append({"key": k, "name": (d["name"] if d and d["name"] else n["name"]) or k[:8], "type": n["type"], "lat": n["lat"], "lon": n["lon"], "last": n["last"], "first": n.get("first", 0), "adverts": n["adverts"], "connected": conn,
                          "online": conn and (d.get("status") != "offline"), "info": device_info(d, now) if d else None})
        for k, d in list(DEV.items()):
            if k not in seen:
                conn = bool(d["last"] and now - d["last"] < CONF["stale_minutes"] * 60)
                if conn: nodes.append({"key": k, "name": d["name"] or k[:8], "type": 2, "lat": d.get("lat"), "lon": d.get("lon"), "last": d["last"], "first": d.get("first", 0), "adverts": 0, "connected": True, "online": d.get("status") != "offline", "info": device_info(d, now)})
        for n in nodes:                                       # a connected repeater's position may come from the control channel
            d = DEV.get(n["key"])
            if d and n["lat"] is None and d.get("lat") is not None and d.get("lon") is not None: n["lat"], n["lon"] = d["lat"], d["lon"]
            if n["lat"] is None or n["lon"] is None: n["lat"] = n["lon"] = None          # a position is both coordinates or none
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

def valid_position(lat, lon):
    """A position a repeater really has: both coordinates present and in range. An unset repeater reports 0,0, which is not a place; a single zero is fine."""
    if lat is None or lon is None: return False
    if abs(lat) > 90 or abs(lon) > 180: return False
    return not (lat == 0 and lon == 0)

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
                if valid_position(got.get("lat"), got.get("lon")): d["lat"], d["lon"] = got["lat"], got["lon"]
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


# ---- repeater sensor telemetry (Cayenne LPP, published by the repeater as meshcore/<area>/<id>/telemetry) ----
# type -> (name, bytes, divisor, signed, unit); multi-value types are skipped over but not stored
LPP = {0: ("digital in", 1, 1, False, ""), 1: ("digital out", 1, 1, False, ""), 2: ("analog in", 2, 100, True, ""), 3: ("analog out", 2, 100, True, ""),
       100: ("generic", 4, 1, False, ""), 101: ("light", 2, 1, False, "lx"), 102: ("presence", 1, 1, False, ""), 103: ("temperature", 2, 10, True, "°C"),
       104: ("humidity", 1, 2, False, "%"), 115: ("pressure", 2, 10, False, "hPa"), 116: ("voltage", 2, 100, False, "V"), 117: ("current", 2, 1000, True, "A"),
       118: ("frequency", 4, 1, False, "Hz"), 120: ("percent", 1, 1, False, "%"), 121: ("altitude", 2, 1, True, "m"), 125: ("concentration", 2, 1, False, "ppm"),
       128: ("power", 2, 1, False, "W"), 130: ("distance", 4, 1000, False, "m"), 131: ("energy", 4, 1000, False, "kWh"), 132: ("direction", 2, 1, False, "°"),
       133: ("time", 4, 1, False, ""), 142: ("switch", 1, 1, False, "")}
LPP_SKIP = {113: 6, 134: 6, 135: 3, 136: 9}      # accelerometer, gyrometer, colour, GPS: skipped safely
def lpp_decode(b):
    """-> [(channel, type, name, value, unit)]; stops quietly at the first thing it cannot read (never raises)."""
    out, i = [], 0
    while i + 2 <= len(b):
        ch, t = b[i], b[i + 1]
        if ch == 0 and t == 0: break
        if t in LPP_SKIP: n = LPP_SKIP[t]; i += 2 + n; continue
        if t not in LPP: break
        name, n, div, sg, unit = LPP[t]
        if i + 2 + n > len(b): break
        v = int.from_bytes(b[i + 2:i + 2 + n], "big", signed=sg)
        out.append((ch, t, name, round(v / div, 3), unit)); i += 2 + n
    return out

TELEM_LAST = {}; TELEM_MIN_GAP = 20

def telem_store(did, area, lpp_hex, now):
    try: vals = lpp_decode(bytes.fromhex(lpp_hex))
    except (ValueError, TypeError): COUNT["bad_telem"] += 1; return 0
    if not vals: return 0
    with LOCK:
        DB.executemany("INSERT INTO telem VALUES(?,?,?,?,?,?,?)", [(did, area, int(now), ch, t, name, v) for ch, t, name, v, unit in vals])
    COUNT["telem"] += 1
    return len(vals)

def telem_latest(allowed=None):
    """Newest value of every sensor, with 24 h min/max, for the Sensors tab. `allowed` = device ids a restricted user may see."""
    now = int(time.time()); rows = []
    with LOCK:
        for did, area, ts, ch, t, name, v in DB.execute("SELECT did,area,MAX(ts),ch,type,name,v FROM telem GROUP BY did,ch,type").fetchall():
            if allowed is not None and did not in allowed: continue
            lo, hi, n = DB.execute("SELECT MIN(v),MAX(v),COUNT(*) FROM telem WHERE did=? AND ch=? AND type=? AND ts>=?", (did, ch, t, now - 86400)).fetchone()
            rows.append({"id": did, "area": area, "name": (DEV.get(did) or {}).get("name") or did[:8], "ts": ts, "age": now - ts, "ch": ch, "type": t, "sensor": name,
                         "v": v, "unit": LPP.get(t, ("", 0, 1, False, ""))[4], "min": lo, "max": hi, "n": n})
    rows.sort(key=lambda r: (r["name"].lower(), r["ch"], r["type"]))
    return rows

def telem_series(did, ch, t, hours=24):
    with LOCK:
        return [[ts, v] for ts, v in DB.execute("SELECT ts,v FROM telem WHERE did=? AND ch=? AND type=? AND ts>=? ORDER BY ts", (did, int(ch), int(t), int(time.time()) - int(hours * 3600))).fetchall()]


# ---- presence timeline: on / off / no-data stretches from a sensor's presence readings (LPP type 102) ----
PRESENCE_GAP = 25 * 60        # a reading holds for at most this long; the repeater reports at least every 15 minutes

def presence_segments(samples, since, now, gap=PRESENCE_GAP):
    """samples: [(ts, value)] oldest first -> [[t0, t1, state]] covering since..now; state 1 = present, 0 = clear, -1 = no data."""
    segs = []
    def add(t0, t1, st):
        if t1 <= t0: return
        if segs and segs[-1][2] == st and segs[-1][1] == t0: segs[-1][1] = t1
        else: segs.append([t0, t1, st])
    prev = None                                      # the reading in force at the start of the window
    rows = []
    for ts, v in samples:
        if ts <= since: prev = (ts, 1 if v else 0)
        elif ts <= now: rows.append((ts, 1 if v else 0))
    pts = ([prev] if prev else []) + rows
    if not pts: add(since, now, -1); return segs
    if pts[0][0] > since + 0 and not prev: add(since, pts[0][0], -1)
    for i, (ts, st) in enumerate(pts):
        t0 = max(ts, since)
        nxt = pts[i + 1][0] if i + 1 < len(pts) else now
        hold_end = min(nxt, ts + gap, now)
        add(t0, hold_end, st)
        if hold_end < nxt: add(max(hold_end, since), nxt, -1)      # never start a no-data stretch before the window
    return segs

def presence_now(samples, now, gap=PRESENCE_GAP):
    """The state right now: the newest reading at or before `now`, if it is recent enough to still hold."""
    last = None
    for ts, v in samples:
        if ts <= now: last = (ts, 1 if v else 0)
    return last[1] if last and now - last[0] <= gap else -1

def presence_view(hours=24, now=None, allowed=None):
    now = int(now or time.time()); hours = max(1, min(168, float(hours))); since = int(now - hours * 3600); out = []
    with LOCK:
        keys = DB.execute("SELECT DISTINCT did, ch FROM telem WHERE type=102 AND ts>=?", (since - PRESENCE_GAP,)).fetchall()
        for did, ch in keys:
            if allowed is not None and did not in allowed: continue
            samples = DB.execute("SELECT ts, v FROM telem WHERE did=? AND ch=? AND type=102 AND ts>=? ORDER BY ts", (did, ch, since - PRESENCE_GAP)).fetchall()
            segs = presence_segments(samples, since, now)
            known = sum(b - a for a, b, st in segs if st >= 0); on = sum(b - a for a, b, st in segs if st == 1)
            events = sum(1 for i, g in enumerate(segs) if g[2] == 1 and (i == 0 or segs[i - 1][2] != 1) and g[0] > since)
            last_on = max((b for a, b, st in segs if st == 1), default=None)
            mv = [(ts, v) for ts, v in DB.execute("SELECT ts, v FROM telem WHERE did=? AND ch=? AND type=120 AND ts>=? ORDER BY ts", (did, ch + 1, since)).fetchall()]
            if len(mv) > 160: step = len(mv) / 160.0; mv = [mv[int(i * step)] for i in range(160)]
            out.append({"id": did, "name": (DEV.get(did) or {}).get("name") or did[:8], "ch": ch, "since": since, "now": now, "segments": segs,
                        "now_state": presence_now(samples, now), "occupied_pct": round(100.0 * on / known, 1) if known else None,
                        "events": events, "last_on": last_on, "known_pct": round(100.0 * known / (now - since), 1), "movement": mv})
    out.sort(key=lambda r: (r["name"].lower(), r["ch"]))
    return out

def telem_prune(now):
    return prune_batched("telem", "ts", now - max(8, CONF["telem_keep_days"]) * 86400)      # never under 8 days: the presence timeline reaches back 7

def on_publish(topic, payload, retained=False):
    now = time.time()
    if topic.startswith("$SYS/"):
        with LOCK: SYS[topic] = [payload.decode("utf-8", "replace"), now]
        return
    m = re.match(r"^meshcore/([^/]+)/([0-9A-Fa-f]{64})/(raw|packets|status|telemetry)$", topic)
    COUNT["messages"] += 1; note_rate("messages")
    if not m:
        COUNT["other_topics"] += 1; return
    area, did, kind = m.group(1), m.group(2).upper(), m.group(3)
    if did == DASH_ID: return                       # the dashboard's own messages on their way to the repeaters: not a repeater
    try: j = json.loads(payload.decode("utf-8", "replace"))
    except Exception: COUNT["bad_json"] += 1; return
    if not isinstance(j, dict): COUNT["bad_json"] += 1; return
    with LOCK:
        d = device(did, area)
        if not retained: d["last"] = now; d["topics"][kind] += 1
        if isinstance(j.get("origin"), str) and j["origin"]: d["name"] = j["origin"]
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
            if isinstance(j.get("stats"), dict):
                d["stats"] = j["stats"]
                if not retained:
                    boot_note(d, j.get("boot_id", j["stats"].get("boot_id")), now)
                    try: airtime_note(did, j["stats"], now, d.get("boot_id"))
                    except Exception as e: sys.stderr.write("airtime: %s\n" % e)
            return
        if kind == "telemetry":
            if not retained and isinstance(j.get("lpp"), str) and len(j["lpp"]) <= 400 and now - TELEM_LAST.get(did, 0) >= TELEM_MIN_GAP:
                TELEM_LAST[did] = now; telem_store(did, area, j["lpp"], now)         # a repeater cannot fill the table by sending often: one reading set every 20 s at most
            return
        if not retained: d["last_pkt"] = now                      # the moment of the newest radio packet, for the live flow pulses
        if kind == "raw": d["n_raw"] += 1
        else: d["n_pkt"] += 1
        raw_hex = j.get("data") if kind == "raw" else j.get("raw")
        try: raw = bytes.fromhex(raw_hex) if raw_hex else b""
        except ValueError: raw = b""
        info = parse_packet(raw) or {}
        wire = None
        try: wire = MSG.parse_wire(raw) if raw else None
        except Exception: wire = None
        info["pkt"] = hashlib.sha1(wire["payload"]).hexdigest()[:12] if wire else None
        # routing: 0 = scoped flood, 1 = unscoped flood, 2 = direct, 3 = scoped direct (the MeshCore route types)
        info["route_type"] = wire["route"] if wire else None
        info["scope"] = (MSG.find_region(scope_names(), wire) or "?") if wire and wire["route"] in (0, 3) else ""
        info["size"] = len(raw)
        direction = j.get("direction", "rx") if kind == "packets" else "rx"
        # a device that publishes both topics is counted once: count 'packets', and 'raw' only when no packets arrive
        counted = kind == "packets" or d["n_pkt"] == 0
        if counted:
            d["n_tx" if direction == "tx" else "n_rx"] += 1; note_rate("pkt:" + did); note_rate("packets")
            d["types"][info.get("type") or ("T%s" % j.get("packet_type", "?"))] += 1; d["bytes"] += len(raw)
            try: d["rssi"] = int(j["RSSI"]) if "RSSI" in j else d["rssi"]; d["snr"] = float(j["SNR"]) if "SNR" in j else d["snr"]
            except (ValueError, TypeError): pass
            if direction == "tx" and raw:
                try: note_sent(did, raw, now)
                except Exception as e: sys.stderr.write("sent: %s\n" % e)
                if info.get("fkey") == did:                                # the repeater's own advert, as it sent it
                    try: advert_note(did, info, now)
                    except Exception as e: sys.stderr.write("advert check: %s\n" % e)
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
    CTL["conn"] = MqttConn(CFG["ctl_user"], CFG["ctl_pass_file"], ["umcnet/v1/+/dev/+/resp", "umcnet/v1/enrol/hello", "umcnet/v1/+/replay/req/+"], on_control_reply, CTL_STATUS)
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
            online = [c for c in list(CLIENTS.values()) if c.get("user") == n and c.get("state") == "connected"]
            last = max([c.get("last", 0) for c in list(CLIENTS.values()) if c.get("user") == n] or [0])
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
    DB.execute("CREATE TABLE IF NOT EXISTS telem(did TEXT, area TEXT, ts INTEGER, ch INTEGER, type INTEGER, name TEXT, v REAL)"); DB.execute("CREATE INDEX IF NOT EXISTS t_key ON telem(did, ch, type, ts)")
    DB.execute("CREATE TABLE IF NOT EXISTS grp_buf(pkey TEXT, did TEXT, seen INTEGER, dir TEXT, snr REAL, rssi INTEGER, raw TEXT, PRIMARY KEY(pkey, did, dir))"); DB.execute("CREATE INDEX IF NOT EXISTS g_seen ON grp_buf(seen)")
    DB.execute("CREATE TABLE IF NOT EXISTS links(a TEXT, b TEXT, first INTEGER, last INTEGER, snr REAL, rssi INTEGER, PRIMARY KEY(a, b))")
    DB.execute("CREATE TABLE IF NOT EXISTS traffic(h INTEGER, node TEXT, rx TEXT, ptype TEXT, hops INTEGER, n INTEGER, PRIMARY KEY(h, node, rx, ptype, hops))")
    DB.execute("CREATE TABLE IF NOT EXISTS events(ts INTEGER, kind TEXT, client TEXT, user TEXT, ip TEXT, text TEXT)"); DB.execute("CREATE INDEX IF NOT EXISTS e_ts ON events(ts)")
    DB.execute("CREATE INDEX IF NOT EXISTS t_ts ON telem(ts)")
    DB.execute("CREATE TABLE IF NOT EXISTS airtime(did TEXT, ts INTEGER, tx REAL, rx REAL, boot TEXT)"); DB.execute("CREATE INDEX IF NOT EXISTS air_k ON airtime(did, ts)")
    if "boot" not in [r[1] for r in DB.execute("PRAGMA table_info(airtime)")]: DB.execute("ALTER TABLE airtime ADD COLUMN boot TEXT")
    DB.execute("CREATE TABLE IF NOT EXISTS routes(h INTEGER, path TEXT, rx TEXT, n INTEGER, last INTEGER, PRIMARY KEY(h, path, rx))")
    DB.execute("CREATE TABLE IF NOT EXISTS snr(h INTEGER, node TEXT, n INTEGER, s REAL, lo REAL, hi REAL, PRIMARY KEY(h, node))"); DB.execute("CREATE INDEX IF NOT EXISTS snr_n ON snr(node, h)")
    DB.execute("CREATE TABLE IF NOT EXISTS alertstate(key TEXT PRIMARY KEY, state TEXT, ts INTEGER)")
    DB.execute("CREATE TABLE IF NOT EXISTS hophist(h INTEGER, rx TEXT, hops INTEGER, n INTEGER, PRIMARY KEY(h, rx, hops))")
    DB.execute("CREATE TABLE IF NOT EXISTS adverts(key TEXT PRIMARY KEY, ts INTEGER, ats INTEGER, raw TEXT)")
    DB.execute("CREATE TABLE IF NOT EXISTS clockdrift(key TEXT PRIMARY KEY, ts INTEGER, samples TEXT)")
    DB.execute("CREATE TABLE IF NOT EXISTS newnodes(key TEXT PRIMARY KEY, ts INTEGER, name TEXT, kind INTEGER, rx TEXT, state TEXT)"); DB.execute("CREATE INDEX IF NOT EXISTS nn_ts ON newnodes(ts)")
    DB.execute("CREATE TABLE IF NOT EXISTS audit(ts INTEGER, who TEXT, action TEXT, target TEXT, detail TEXT, ok INTEGER)"); DB.execute("CREATE INDEX IF NOT EXISTS a_ts ON audit(ts)")

def sysnum(topic, default=0):
    v = SYS.get(topic)
    try: return float(v[0]) if v else default
    except ValueError: return default

def snapshot_values():
    s = system()
    with LOCK:
        online = [d for d in list(DEV.values()) if time.time() - d["last"] < 900]
        vals = {"clients": sysnum("$SYS/broker/clients/connected"), "subs": sysnum("$SYS/broker/subscriptions/count"), "msgs_pm": rate_per_min("messages", 300), "pkts_pm": rate_per_min("packets", 300), "unique_pm": rate_per_min("unique", 300),
                "repeaters": len(online), "retained": sysnum("$SYS/broker/retained messages/count"), "bytes_rx_1m": sysnum("$SYS/broker/load/bytes/received/1min"), "bytes_tx_1m": sysnum("$SYS/broker/load/bytes/sent/1min"),
                "pub_rx_1m": sysnum("$SYS/broker/load/publish/received/1min"), "pub_tx_1m": sysnum("$SYS/broker/load/publish/sent/1min"), "conn_1m": sysnum("$SYS/broker/load/connections/1min"), "dropped_1m": sysnum("$SYS/broker/load/publish/dropped/1min"),
                "heap": sysnum("$SYS/broker/heap/current"), "load1": s["load"][0] if s["load"] else 0, "mem_pct": 100.0 * (1 - s["mem_avail"] / s["mem_total"]) if s["mem_total"] else 0, "disk_pct": 100.0 * (1 - s["disk_free"] / s["disk_total"]) if s["disk_total"] else 0}
        if s["cpu"] is not None: vals["cpu"] = s["cpu"]
        for did, d in list(DEV.items()): vals["dev:" + did[:16]] = rate_per_min("pkt:" + did, 300)
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
            grp_prune(now)
            if now % 3600 < 60:
                try: retention_run(now)
                except Exception as e: sys.stderr.write("retention: %s\n" % e)
            if CFG["backup"] and backup_due(now, BACKUP["ts"], BACKUP["try"], CONF["backup_hour"]):
                BACKUP["try"] = now; threading.Thread(target=backup_run, daemon=True, name="backup").start()
            DB.executemany("INSERT INTO samples VALUES(?,?,?)", [(now, k, float(v)) for k, v in vals.items()])
            if now % 3600 < 60:
                cut = now - CONF["keep_days"] * 86400; DB.execute("DELETE FROM samples WHERE ts<?", (cut,)); DB.execute("DELETE FROM events WHERE ts<?", (cut,)); DB.execute("DELETE FROM audit WHERE ts<?", (now - max(90, CONF["keep_days"]) * 86400,))
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
            "auth_fail_warn": 1, "auth_fail_bad": 20, "keep_days": 14,
            "conf_rev": 2, "traffic_keep_days": 400, "telem_keep_days": 90, "backup_keep": 7, "backup_hour": 3, "airtime_warn_pct": 10, "airtime_warn_minutes": 15, "newnode_max_per_hour": 6, "newnode_warmup_minutes": 30, "route_live_minutes": 60, "route_silent_minutes": 720, "route_busy_packets": 20, "battery_low_mv": 3500, "silent_overrides": {}, "confirm_risky": True, "control_enabled": True, "map_publish": False, "snr_worse_db": 4, "snr_min_samples": 20, "drift_seconds": 600, "tx_headroom_db": 10,
            "alerts": {"enabled": False, "url": "", "offline": True, "online": True, "pending": True, "auth_fail": True, "cert": True, "disk": True, "control": True, "collision": True, "airtime": True, "newnode": True, "route_silent": False, "snr_worse": True, "clock_drift": False},
            "labels": {},
            "catalogue": {"enabled": True, "url": "https://raw.githubusercontent.com/marcelverdult/meshcore-channels/main/channels-unique.json", "refresh_hours": 24, "keyed": False}}
RANGES = {"map_hours": (1, 8760), "stale_minutes": (2, 1440), "cert_warn_days": (2, 60), "cert_bad_days": (1, 30), "disk_warn_pct": (50, 99), "mem_warn_pct": (50, 99), "flap_count": (2, 50),
          "skew_seconds": (5, 3600), "auth_fail_warn": (1, 1000), "auth_fail_bad": (2, 10000), "keep_days": (1, 90),
          "traffic_keep_days": (7, 1000), "telem_keep_days": (8, 730), "backup_keep": (1, 60), "backup_hour": (0, 23), "airtime_warn_pct": (1, 100), "airtime_warn_minutes": (5, 120), "newnode_max_per_hour": (1, 100), "newnode_warmup_minutes": (0, 1440),
          "route_live_minutes": (5, 1440), "route_silent_minutes": (30, 10080), "route_busy_packets": (1, 100000), "battery_low_mv": (3000, 4000),
          "snr_worse_db": (1, 30), "snr_min_samples": (5, 1000), "drift_seconds": (60, 86400), "tx_headroom_db": (3, 30)}
CONF = json.loads(json.dumps(DEFAULTS))
CONF_LOCK = threading.RLock()      # held across a read-change-save of CONF, so two writers (the settings page, a promoted catalogue channel) cannot lose each other's change

def conf_swap(new):
    """Replace the settings in one step that readers on other threads never see half done (CONF is updated in place, never emptied)."""
    CONF.update(new)
    for k in [k for k in list(CONF) if k not in new]: CONF.pop(k, None)

def conf_redacted(who_is_admin):
    """The settings as one viewer may see them. A non-administrator gets no channel keys, no web users and no alert address."""
    c = json.loads(json.dumps(CONF))
    if who_is_admin: return c
    for ch in (c.get("messages") or {}).get("channels", []):
        if isinstance(ch, dict) and "psk" in ch: ch.pop("psk", None); ch["psk_set"] = True
    a = c.get("alerts") or {}
    if a.get("url"): a["url"] = "(set by the administrator)"
    c.pop("web_users", None)
    return c

def conf_path(): return os.path.join(CFG["data"], "config.json")

def conf_load():
    try: raw = json.load(open(conf_path()))
    except Exception: raw = {}
    merged = json.loads(json.dumps(DEFAULTS))
    for k, v in raw.items():
        if k == "alerts" and isinstance(v, dict): merged["alerts"].update({a: b for a, b in v.items() if a in merged["alerts"]})
        elif k == "messages" and isinstance(v, dict): merged["messages"].update(v)
        elif k == "web_users" and isinstance(v, dict): merged["web_users"] = v
        elif k == "catalogue" and isinstance(v, dict): merged["catalogue"].update({a: b for a, b in v.items() if a in merged["catalogue"]})
        elif k in merged: merged[k] = v
    if not isinstance(raw.get("conf_rev"), int) or raw["conf_rev"] < 2:         # 2.37 saved its 30-day default into every config file: put the 400 days back once (a value the operator chose is left alone)
        if merged.get("traffic_keep_days") == 30: merged["traffic_keep_days"] = 400
        merged["conf_rev"] = 2
    c = merged["catalogue"]; d = DEFAULTS["catalogue"]
    for k in ("enabled", "keyed"):
        if not isinstance(c.get(k), bool): c[k] = d[k]
    rh = c.get("refresh_hours")
    if isinstance(rh, bool) or not isinstance(rh, int) or not 1 <= rh <= 720: c["refresh_hours"] = d["refresh_hours"]
    if not isinstance(c.get("url"), str) or cat_url_error(c["url"]): c["url"] = d["url"]
    with CONF_LOCK: conf_swap(merged)

def conf_save():
    tmp = conf_path() + ".tmp"
    with open(tmp, "w") as f: json.dump(CONF, f, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600); os.replace(tmp, conf_path())

def conf_update(patch):
    """Validate and apply a settings change. Returns an error text or None."""
    with CONF_LOCK: return _conf_update(patch)

def _conf_update(patch):
    if not isinstance(patch, dict): return "not a settings object"
    new = json.loads(json.dumps(CONF))
    for k, v in patch.items():
        if k in RANGES:
            v = finite_int(v) if not isinstance(v, bool) else None
            if v is None: return "%s must be a whole number" % k
            lo, hi = RANGES[k]
            if not lo <= v <= hi: return "%s must be between %d and %d" % (k, lo, hi)
            new[k] = v
        elif k in ("confirm_risky", "control_enabled", "join_bridge", "enrol_enabled", "publish_decoded", "map_publish"): new[k] = bool(v)
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
                    b = finite_int(b) if not isinstance(b, bool) else None
                    if b is None: return "keep_days must be a whole number"
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
                    out = []; prev = {x.get("name", "").lower(): x for x in m.get("channels", [])}
                    for c in b:
                        if not isinstance(c, dict) or not isinstance(c.get("name"), str): return "each channel needs a name"
                        e = {"name": c["name"].strip()}
                        if c.get("psk"): e["psk"] = str(c["psk"]).strip()
                        was = prev.get(e["name"].lower())
                        if was and was.get("source") in ("scan", "catalogue") and "psk" not in e and was["name"] == e["name"]: out.append(dict(was)); continue    # found by the scan or the catalogue: keep its source and label
                        try: MSG.Channel(e["name"], e.get("psk"))
                        except Exception as ex: return "channel %s: %s" % (e["name"], ex)
                        if len(e["name"]) > 31 or not re.match(r"^[A-Za-z0-9#][A-Za-z0-9 #_-]*$", e["name"]): return "channel names are letters, digits, # _ - and spaces"
                        out.append(e)
                    m[a] = out
        elif k == "catalogue":
            if not isinstance(v, dict): return "catalogue must be an object"
            cc = new["catalogue"]
            for a, b in v.items():
                if a in ("enabled", "keyed"):
                    if not isinstance(b, bool): return "catalogue %s must be true or false" % a
                    cc[a] = b
                elif a == "refresh_hours":
                    if isinstance(b, bool) or not isinstance(b, (int, str)): return "refresh_hours must be a whole number"
                    b = finite_int(b)
                    if b is None: return "refresh_hours must be a whole number"
                    if not 1 <= b <= 720: return "refresh_hours must be between 1 and 720"
                    cc[a] = b
                elif a == "url":
                    err = cat_url_error(b)
                    if err: return err
                    cc[a] = b.strip()
        elif k == "silent_overrides":
            if not isinstance(v, dict): return "silent_overrides must be an object"
            so = dict(new["silent_overrides"])
            for dev, m in v.items():
                dev = str(dev).upper()
                if not re.match(r"^[0-9A-F]{64}$", dev): return "silent_overrides: a repeater id is 64 hex characters"
                if m is None or (isinstance(m, str) and not m.strip()): so.pop(dev, None); continue      # empty = back to the global default
                m = finite_int(m) if not isinstance(m, bool) else None
                if m is None: return "the silent limit for a repeater must be a whole number of minutes"
                if not 2 <= m <= 1440: return "the silent limit for a repeater must be between 2 and 1440 minutes"
                so[dev] = m
            new["silent_overrides"] = so
        elif k == "labels":
            if not isinstance(v, dict): return "labels must be an object"
            lab = {}
            for dev, d in v.items():
                if re.match(r"^[0-9A-F]{64}$", dev) and isinstance(d, dict): lab[dev] = {"label": str(d.get("label", ""))[:40], "note": str(d.get("note", ""))[:300]}
            new["labels"] = lab
    if new["cert_bad_days"] >= new["cert_warn_days"]: return "the red certificate limit must be below the amber one"
    if new["route_live_minutes"] >= new["route_silent_minutes"]: return "a route is live for fewer minutes than it takes to be called silent"
    url_changed = new["catalogue"]["url"] != CONF["catalogue"]["url"]
    conf_swap(new); conf_save()
    if url_changed: cat_reset()
    cat_build_index()
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

def make_setup_code(host, user, password, client_id, area):
    """What the phone app reads: umcclient1: + base64url (no padding) of compact JSON (same as umcnet-user)."""
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,23}$", user or ""): raise ValueError("the account name is 2 to 24 lowercase letters, digits and dashes")
    if not (8 <= len(password or "") <= 40) or not all(0x21 <= ord(c) <= 0x7e for c in password): raise ValueError("the password must be 8 to 40 printable characters with no spaces")
    if not re.match(r"^[0-9A-F]{64}$", client_id or ""): raise ValueError("the client id is 64 capital hex characters")
    if not re.match(r"^[A-Z0-9]{3}$", area or ""): raise ValueError("the area code is three capital letters or digits")
    if not re.match(r"^[A-Za-z0-9.-]{3,253}$", host or ""): raise ValueError("the host is not valid")
    j = json.dumps({"h": host, "u": user, "p": password, "i": client_id, "a": area}, separators=(",", ":"))
    return "umcclient1:" + base64.urlsafe_b64encode(j.encode()).decode().rstrip("=")

def client_id_of(output, fallback=""):
    m = re.search(r"client id: ([0-9A-F]{64})", output or "")
    return m.group(1) if m else fallback

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

def chan_obj(c):
    """The Channel for a configured entry, or None. A channel taken from the catalogue keeps no key in the settings: a hashtag one is derived
    from its name, and a keyed one is looked up in the catalogue cache, and only while the 'keyed' switch is on."""
    try:
        if c.get("psk"): return MSG.Channel(c["name"], c["psk"])
        if c.get("source") == "catalogue" and not c["name"].startswith("#"):
            e = CAT_BY_NAME.get(c["name"].lower())
            return MSG.Channel(c["name"], e["key"]) if CONF["catalogue"]["keyed"] and e and e.get("key") else None
        return MSG.Channel(c["name"])
    except Exception: return None

def msg_channels():
    return [ch for ch in (chan_obj(c) for c in CONF["messages"]["channels"]) if ch]

REPLAY_WINDOW = 3600        # catch-up for clients: the last hour of group packets, at most 500, oldest first
REPLAY_MAX = 500
REPLAY_GAP = 20             # seconds between requests from one client id
REPLAY_PACE = 0.015         # seconds between publishes
REPLAY_LAST = {}

def grp_store(pkey, did, raw, snr, rssi, now, direction):
    """Keep a group packet for an hour so a client that was offline can be caught up (see replay_serve)."""
    try: s = float(snr) if snr not in (None, "") else None
    except (TypeError, ValueError): s = None
    try: r = int(rssi) if rssi not in (None, "") else None
    except (TypeError, ValueError): r = None
    DB.execute("INSERT OR IGNORE INTO grp_buf(pkey,did,seen,dir,snr,rssi,raw) VALUES(?,?,?,?,?,?,?)", (pkey, did, int(now), direction, s, r, raw.hex().upper()))

def grp_prune(now=None):
    with LOCK: DB.execute("DELETE FROM grp_buf WHERE seen<?", (int(now or time.time()) - REPLAY_WINDOW - 400,))

def replay_serve(conn, area, cid, since, now=None, pace=None):
    """Publish the buffered packets newer than since (never older than an hour) to umcnet/v1/<area>/replay/<cid>, oldest first, then a done marker.
    Never on meshcore/.../raw: the repeaters' bridges would put them back on the air."""
    now = int(now or time.time()); since = max(int(since), now - REPLAY_WINDOW); pace = REPLAY_PACE if pace is None else pace
    topic = "umcnet/v1/%s/replay/%s" % (area, cid)
    with LOCK:
        grp_prune(now)
        rows = DB.execute("SELECT did,seen,dir,snr,rssi,raw FROM grp_buf WHERE seen>=? ORDER BY seen DESC LIMIT ?", (since, REPLAY_MAX)).fetchall()
    rows.reverse(); n = 0
    try:
        for did, seen, d, snr, rssi, raw in rows:
            conn.publish(topic, json.dumps({"origin_id": did, "timestamp": seen, "type": "RAW", "data": raw, "direction": d, "snr": snr, "rssi": rssi, "replay": 1}, separators=(",", ":")).encode())
            n += 1
            if pace: time.sleep(pace)
        conn.publish(topic, json.dumps({"done": 1, "n": n}, separators=(",", ":")).encode())
    except Exception as e: sys.stderr.write("replay: %s\n" % e)
    return n

def replay_request(topic, payload, retained=False, now=None):
    """A client asks for the catch-up. Its id is taken from the topic (the broker's access list lets it write only its own)."""
    m = re.match(r"^umcnet/v1/([A-Za-z0-9]{1,8})/replay/req/([0-9A-F]{64})$", topic)
    if not m or retained: return False
    try: j = json.loads(payload.decode("utf-8", "replace")); since = j["since"]
    except Exception: return False
    if not isinstance(since, (int, float)) or isinstance(since, bool) or since != since or abs(since) > 1e12: return False
    conn = CTL.get("conn"); now = time.time() if now is None else now
    if conn is None or not DB: return False
    area, cid = m.groups()
    with LOCK:
        if now - REPLAY_LAST.get(cid, 0) < REPLAY_GAP: return False
        REPLAY_LAST[cid] = now
        for k in [k for k, t in REPLAY_LAST.items() if now - t > 3600]: del REPLAY_LAST[k]
    t = threading.Thread(target=replay_serve, args=(conn, area, cid, since, now), daemon=True, name="replay"); t.start()
    return t

def note_sent(did, raw, now):
    """A repeater reports that it transmitted a packet. If that is a message sent from this dashboard, record the repeater
    as having put it on the air (flag "x"): this is the confirmation that it left an antenna, as opposed to being heard back."""
    if did == DASH_ID or not DB: return
    p = MSG.parse_wire(raw)
    if not p or p["ptype"] != 5 or len(p["payload"]) < 19: return
    pkey = hashlib.sha1(p["payload"]).hexdigest()[:20]
    with LOCK:
        grp_store(pkey, did, raw, None, None, now, "tx")
        row = DB.execute("SELECT id, heard FROM messages WHERE pkey=? AND dir='tx'", (pkey,)).fetchone()
        if not row: return
        heard = json.loads(row[1] or "[]")
        if any(e["d"] == did and e.get("x") for e in heard): return
        heard.append({"d": did, "h": 0, "s": None, "r": None, "t": int(now), "x": 1})
        DB.execute("UPDATE messages SET heard=? WHERE id=?", (json.dumps(heard, separators=(",", ":")), row[0]))

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
        grp_store(pkey, did, raw, snr, rssi, now, "rx")         # before the decrypt: the phone has keys the dashboard may not
        row = DB.execute("SELECT id, heard, region, hops, snr FROM messages WHERE pkey=?", (pkey,)).fetchone()
        if row:
            heard = json.loads(row[1] or "[]"); old = next((e for e in heard if e["d"] == did and not e.get("x")), None)
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
            cat_observe(p["payload"], now)
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
                    CONF["messages"]["channels"].append({"name": g["name"], "source": "scan"}); conf_save()
                    h = "%02X" % MSG.Channel(g["name"]).hash
                    with LOCK: MSGSTAT.pop(h, None)
                    audit("system", "group added", g["name"], "public hashtag group opened %d heard packets" % g["packets"])
                    event("info", "public group %s found on the mesh and added" % g["name"])
                cat_promote()
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

# ----------------------------------------------------------------------------- public channel catalogue
# Source: github.com/marcelverdult/meshcore-channels (CC0 1.0, checked in its LICENSE and in the "license" field of each file). It lists public channel names
# with a label. A #hashtag channel carries no key: it is derived from the name exactly as for the group scan (MSG.Channel). Channels with a published key
# are used only when the operator switches "keyed" on (these keys are public in the catalogue). Nothing is ever guessed; a channel is added only after real
# packets authenticate with its key (the hash byte and the MAC both match) GROUP_SCAN_MIN times. Private channels and rooms are never touched.
CAT_MAX_BYTES = 2 * 1024 * 1024; CAT_MAX_ENTRIES = 5000; CAT_TIMEOUT = 15
CAT_DEADLINE = 60                      # seconds for the whole download
CAT_MANUAL_GAP = 300                  # seconds between manual syncs
CAT_TRY_PER_PACKET = 32               # candidate keys tried for one unreadable packet
CAT_TRY_PER_MINUTE = 3000             # candidate keys tried in one minute; over that, packets are skipped and counted
CAT_NAME_RE = re.compile(r"^#?[a-z0-9]{1,29}(-[a-z0-9]{1,29})*$")
CAT_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{22}==$")
CAT_PRIO = {"gb": 0, "sco": 0, "ie": 1, "ioi": 1}      # UK first, then Ireland, then everything else
CAT_HTTP = None                                         # tests put a fake fetch here: fn(url) -> bytes
CAT = {"entries": [], "index": {}, "meta": {}, "hits": {}, "seen": collections.OrderedDict(), "minute": 0, "tries": 0, "skipped": 0, "truncated": 0, "last_manual": 0, "busy": False}
CAT_BY_NAME = {}
CAT_LOCK = threading.RLock()

def cat_url_error(url):
    """None if the address may be fetched: https only, a named host (no IP address, no local name), the standard port."""
    if not isinstance(url, str) or not 12 <= len(url.strip()) <= 300: return "catalogue url: an https:// address"
    try: u = urlparse(url.strip()); port = u.port
    except ValueError: return "catalogue url: not a valid address"
    h = (u.hostname or "").lower()
    if u.scheme != "https" or not h or u.username or u.password or port not in (None, 443): return "catalogue url: https only, standard port, no login in the address"
    if h != "raw.githubusercontent.com" and ("." not in h or ":" in h or re.match(r"^[0-9.]+$", h) or h == "localhost" or h.endswith((".local", ".internal", ".lan"))):
        return "catalogue url: use raw.githubusercontent.com or a public host name (not an IP address or a local name)"
    return None

def cat_entry(it):
    """One validated catalogue entry {name, label, key}, or None. A hashtag channel never keeps a key (it is derived)."""
    if not isinstance(it, dict): return None
    nm, lab, key = it.get("channel"), it.get("description"), it.get("key")
    if not isinstance(nm, str) or not CAT_NAME_RE.match(nm): return None
    if not isinstance(lab, str) or not 1 <= len(lab) <= 200 or any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") for c in lab) or not lab.strip(): return None      # no control, direction-override, zero-width or unassigned characters
    if key is not None:
        if not isinstance(key, str) or not CAT_KEY_RE.match(key): return None
        try:
            if len(base64.b64decode(key, validate=True)) != 16: return None
        except Exception: return None
    if nm.startswith("#"): key = None
    elif key is None: return None                           # a channel without a # must carry its key
    return {"name": nm, "label": lab.strip(), "key": key}

def cat_parse(raw):
    """Validate a catalogue file (channels-unique.json or channels-by-country.json). Raises ValueError. Bad entries are skipped and counted;
    the whole file is refused when it is not CC0-1.0, too big, too long, the wrong shape, or more than a tenth of it is bad."""
    if not isinstance(raw, (bytes, bytearray)): raise ValueError("no data")
    if len(raw) > CAT_MAX_BYTES: raise ValueError("the file is larger than 2 MB")
    try: j = json.loads(raw.decode("utf-8"))
    except Exception: raise ValueError("not valid JSON")
    if not isinstance(j, dict): raise ValueError("not a catalogue file")
    if j.get("license") != "CC0-1.0": raise ValueError("the licence is not CC0-1.0")
    gen = j.get("generated_at"); gen = gen[:40] if isinstance(gen, str) else ""
    if isinstance(j.get("channels"), list): groups = [("", j["channels"])]
    elif isinstance(j.get("countries"), dict):
        groups = []
        for code, items in j["countries"].items():
            if not isinstance(code, str) or not re.match(r"^[a-z0-9]{1,29}$", code) or not isinstance(items, list): raise ValueError("a country list is malformed")
            groups.append((code, items))
    else: raise ValueError("no channel list in the file")
    total = sum(len(i) for _, i in groups)
    if total > CAT_MAX_ENTRIES: raise ValueError("more than %d entries" % CAT_MAX_ENTRIES)
    out = {}; bad = 0
    for code, items in groups:
        pr = CAT_PRIO.get(code, 2)
        for it in items:
            e = cat_entry(it)
            if e is None: bad += 1; continue
            old = out.get(e["name"].lower())
            if old is None or pr < old["prio"]: e["prio"] = pr; out[e["name"].lower()] = e
    if not out: raise ValueError("no usable entries")
    if bad * 10 > total: raise ValueError("%d of %d entries are malformed" % (bad, total))
    return {"entries": sorted(out.values(), key=lambda e: (e["prio"], e["name"])), "generated_at": gen, "rejected": bad, "total": total}

class CatRedirect(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https on the same host as the address that was configured."""
    def __init__(self, host): self.host = host.lower()
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try: n = urlparse(newurl); port = n.port
        except ValueError: raise urllib.error.URLError("a redirect to a bad address was refused")
        if n.scheme != "https" or (n.hostname or "").lower() != self.host or port not in (None, 443) or n.username or n.password: raise urllib.error.URLError("a redirect to another host was refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def cat_http_get(url):
    """The real fetch: TLS verified, 15 s, 2 MB, redirects only within the same host."""
    op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()), CatRedirect(urlparse(url).hostname or ""))
    with op.open(urllib.request.Request(url, headers={"User-Agent": "umcnet-dash/" + VERSION, "Accept": "application/json"}), timeout=CAT_TIMEOUT) as r:
        n = r.headers.get("Content-Length")
        if n and n.isdigit() and int(n) > CAT_MAX_BYTES: raise ValueError("the file is larger than 2 MB")
        data = b""; end = time.time() + CAT_DEADLINE                 # the socket timeout is per read: a server that drips bytes must not hold the thread for ever
        while len(data) <= CAT_MAX_BYTES:
            chunk = r.read(min(65536, CAT_MAX_BYTES + 1 - len(data)))
            if not chunk: break
            data += chunk
            if time.time() > end: raise ValueError("the download took too long")
    if len(data) > CAT_MAX_BYTES: raise ValueError("the file is larger than 2 MB")
    return data

def cat_build_index():
    """Candidates by the protocol's one-byte channel hash (from MSG.Channel). Hashtag entries always; keyed entries only with 'keyed' on."""
    c = CONF["catalogue"]; idx = {}; by = {}
    with CAT_LOCK:
        for e in CAT["entries"]:
            by[e["name"].lower()] = e
            if not c["enabled"]: continue
            try:
                if e["name"].startswith("#"): ch = MSG.Channel(e["name"])
                elif c["keyed"] and e.get("key"): ch = MSG.Channel(e["name"], e["key"])
                else: continue
            except Exception: continue
            idx.setdefault(ch.hash, []).append((e, ch))
        CAT["index"] = idx; CAT_BY_NAME.update(by)
        for k in [k for k in list(CAT_BY_NAME) if k not in by]: CAT_BY_NAME.pop(k, None)           # updated in place: a reader on another thread never sees it empty
        for k in [k for k in list(CAT["hits"]) if k.lower() not in by]: CAT["hits"].pop(k, None)    # a channel the catalogue no longer lists is not being watched

def cat_db_ready():
    if not DB: return False
    DB.execute("CREATE TABLE IF NOT EXISTS catalogue(k TEXT PRIMARY KEY, v TEXT)"); return True

def cat_save():
    with LOCK:
        if not cat_db_ready(): return
        DB.execute("INSERT OR REPLACE INTO catalogue VALUES('entries',?)", (json.dumps(CAT["entries"], separators=(",", ":")),))
        DB.execute("INSERT OR REPLACE INTO catalogue VALUES('meta',?)", (json.dumps(CAT["meta"], separators=(",", ":")),))

def cat_load():
    """Last-known-good cache from the database; every entry is validated again."""
    try:
        with LOCK:
            if not cat_db_ready(): return
            rows = dict(DB.execute("SELECT k, v FROM catalogue").fetchall())
        ents = []
        for x in json.loads(rows.get("entries", "[]")):
            e = cat_entry({"channel": x.get("name"), "description": x.get("label"), "key": x.get("key")})
            if e: e["prio"] = x.get("prio", 2) if x.get("prio") in (0, 1, 2) else 2; ents.append(e)
        meta = json.loads(rows.get("meta", "{}"))
        with CAT_LOCK: CAT["entries"] = ents[:CAT_MAX_ENTRIES]; CAT["meta"] = meta if isinstance(meta, dict) else {}
    except Exception as e: sys.stderr.write("catalogue load: %s\n" % e)
    cat_build_index()

def cat_reset():
    with CAT_LOCK: CAT["entries"] = []; CAT["meta"] = {}; CAT["hits"].clear(); CAT["seen"].clear()
    try:
        with LOCK:
            if cat_db_ready(): DB.execute("DELETE FROM catalogue")
    except Exception: pass
    cat_build_index()

def cat_sync(manual=False, now=None):
    """Fetch, validate and swap in the catalogue. On any failure the cache is kept and the error and its time are recorded."""
    now = time.time() if now is None else now; c = CONF["catalogue"]
    if not c["enabled"]: return {"ok": False, "error": "the catalogue is switched off"}
    err = cat_url_error(c["url"])
    if err: return {"ok": False, "error": err}
    with CAT_LOCK:
        if CAT["busy"]: return {"ok": False, "error": "a sync is already running"}
        if manual and now - CAT["last_manual"] < CAT_MANUAL_GAP: return {"ok": False, "error": "wait %d more seconds before syncing again" % (CAT_MANUAL_GAP - (now - CAT["last_manual"]) + 0.999)}
        if manual: CAT["last_manual"] = now
        CAT["busy"] = True
    get = CAT_HTTP or cat_http_get; meta = dict(CAT["meta"]); meta["attempt"] = int(now); res = {"ok": False}
    try:
        got = cat_parse(get(c["url"])); meta.pop("note", None)
        comp = c["url"].replace("channels-unique.json", "channels-by-country.json") if c["url"].endswith("/channels-unique.json") else ""
        if comp:                                           # the unique list has no country: read it from the by-country file, if that can be had
            try:
                pri = {e["name"]: e["prio"] for e in cat_parse(get(comp))["entries"]}
                for e in got["entries"]: e["prio"] = pri.get(e["name"], e["prio"])
                got["entries"].sort(key=lambda e: (e["prio"], e["name"]))
            except Exception as ex: meta["note"] = "country order not loaded: %s" % str(ex)[:120]
        with CAT_LOCK: CAT["entries"] = got["entries"]
        meta.update({"ok": int(now), "error": "", "error_at": meta.get("error_at", 0), "generated_at": got["generated_at"], "rejected": got["rejected"], "url": c["url"]})
        res = {"ok": True, "entries": len(got["entries"])}
    except Exception as ex:
        meta["error"] = (str(ex) or ex.__class__.__name__)[:200]; meta["error_at"] = int(now); res = {"ok": False, "error": meta["error"]}
    finally:
        with CAT_LOCK: CAT["meta"] = meta; CAT["busy"] = False
    cat_build_index(); cat_save()
    return res

def cat_loop():
    time.sleep(60)
    while True:
        try:
            c = CONF["catalogue"]; m = CAT["meta"]
            if c["enabled"] and time.time() - m.get("attempt", 0) >= (3600 if m.get("error") else c["refresh_hours"] * 3600): cat_sync()
        except Exception as e: sys.stderr.write("catalogue: %s\n" % e)
        time.sleep(300)

def cat_observe(payload, now):
    """Called with a group packet that no configured channel opened. Tries only the catalogue entries whose hash byte matches, within the budget.
    The MAC check (MSG.decrypt_group) decides: the hash byte alone never labels anything. Nothing decoded is kept."""
    if not CONF["catalogue"]["enabled"] or len(payload) < 19: return
    with CAT_LOCK:
        cands = CAT["index"].get(payload[0])
        if not cands: return
        k = hashlib.sha1(payload).digest()[:10]
        if k in CAT["seen"]: return                         # the same packet heard by another repeater
        CAT["seen"][k] = 1
        if len(CAT["seen"]) > 2000: CAT["seen"].popitem(last=False)
        m = int(now // 60)
        if CAT["minute"] != m: CAT["minute"] = m; CAT["tries"] = 0
        taken = {c.get("name", "").lower() for c in CONF["messages"]["channels"]}
        todo = [x for x in cands if x[0]["name"].lower() not in taken]        # a channel the operator already has is not a candidate
        if len(todo) > CAT_TRY_PER_PACKET: CAT["truncated"] += 1; todo = todo[:CAT_TRY_PER_PACKET]
        if CAT["tries"] + len(todo) > CAT_TRY_PER_MINUTE: CAT["skipped"] += 1; return
        CAT["tries"] += len(todo)
        for e, ch in todo:
            if MSG.decrypt_group([ch], payload) is not None:
                h = CAT["hits"].setdefault(e["name"], {"packets": 0, "last": 0}); h["packets"] += 1; h["last"] = int(now); break

def cat_promote():
    """Add the catalogue channels that opened GROUP_SCAN_MIN real packets, labelled and marked source 'catalogue'. Returns the names added."""
    c = CONF["catalogue"]
    if not c["enabled"] or not CONF["messages"].get("auto_groups", True): return []
    with CAT_LOCK: ready = [(n, h["packets"]) for n, h in CAT["hits"].items() if h["packets"] >= GROUP_SCAN_MIN]
    added = []
    for name, n in ready:
        with CAT_LOCK: e = CAT_BY_NAME.get(name)
        if not e or any(x.get("name", "").lower() == name for x in CONF["messages"]["channels"]):
            with CAT_LOCK: CAT["hits"].pop(name, None)
            continue
        if not name.startswith("#") and not (c["keyed"] and e.get("key")): continue
        ent = {"name": name, "source": "catalogue", "label": e["label"]}; ch = chan_obj(ent)
        if not ch: continue
        with CONF_LOCK: CONF["messages"]["channels"].append(ent); conf_save()
        with LOCK: MSGSTAT.pop("%02X" % ch.hash, None)
        with CAT_LOCK: CAT["hits"].pop(name, None)
        audit("system", "group added", name, "catalogue channel %r opened %d heard packets" % (e["label"][:60], n))
        event("info", "catalogue channel %s found on the mesh and added" % name); added.append(name)
    return added

def cat_status():
    """What the Messages page shows. Counts and names only: never a key."""
    c = CONF["catalogue"]; m = CAT["meta"]
    with CAT_LOCK:
        ents = CAT["entries"]
        return {"enabled": c["enabled"], "keyed": c["keyed"], "url": c["url"], "refresh_hours": c["refresh_hours"], "entries": len(ents), "hashtag": sum(1 for e in ents if e["name"].startswith("#")), "keyed_entries": sum(1 for e in ents if e.get("key")),
                "candidates": sum(len(v) for v in CAT["index"].values()), "last_ok": m.get("ok", 0), "last_attempt": m.get("attempt", 0), "error": m.get("error", ""), "error_at": m.get("error_at", 0), "note": m.get("note", ""),
                "generated_at": m.get("generated_at", ""), "rejected": m.get("rejected", 0), "skipped": CAT["skipped"], "truncated": CAT["truncated"], "license": "CC0-1.0",
                "credit": "Channel catalogue: marcelverdult/meshcore-channels, CC0 1.0 (public domain)", "manual_gap": CAT_MANUAL_GAP,
                "watching": [{"name": n, "packets": h["packets"]} for n, h in sorted(CAT["hits"].items(), key=lambda kv: -kv[1]["packets"])[:20]]}

def rooms_heard():
    """Room servers the repeaters have heard in the last month. Joining one needs its password, which is not kept here."""
    now = time.time()
    with LOCK:
        return sorted([{"key": k, "name": n["name"] or k[:8], "last": n["last"], "lat": n["lat"], "lon": n["lon"]}
                       for k, n in list(NODES.items()) if n["type"] == 3 and now - n["last"] < 30 * 86400], key=lambda r: -r["last"])

def chan_rows():
    """Configured channels for display: name, hash, label, source. No keys."""
    out = []
    for c in CONF["messages"]["channels"]:
        ch = chan_obj(c)
        if not ch: continue
        src = c.get("source") if c.get("source") in ("scan", "catalogue") else "operator"
        e = CAT_BY_NAME.get(c["name"].lower())
        out.append({"name": c["name"], "hash": "%02X" % ch.hash, "source": src, "label": c.get("label") or (e["label"] if e and src != "operator" else ""), "status": "decoded"})
    return out

def messages_view(chan="", region="", direction="", before=0, limit=100, q="", source=""):
    where, args = [], []
    if source in ("operator", "scan", "catalogue"):
        names = [c["name"] for c in chan_rows() if c["source"] == source]
        where.append("chan IN (%s)" % ",".join("?" * len(names)) if names else "0"); args += names
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
        for k, v in unread.items(): v["status"] = "unknown/encrypted"; v["candidates"] = len(CAT["index"].get(int(k, 16), ()))       # counts only: never any content
        names = {d["id"]: (d["name"] or d["id"][:8]) for d in list(DEV.values())}
    out = []
    for r in rows:
        heard = json.loads(r[12] or "[]")
        out.append({"id": r[0], "ts": r[1], "seen": r[2], "chan": r[3], "chash": r[4], "region": r[5], "sender": r[6], "text": r[7], "dir": r[8], "hops": r[9], "snr": r[10], "rssi": r[11],
                    "heard": [{"id": h["d"], "name": names.get(h["d"], h["d"][:8]), "hops": h["h"], "snr": h["s"], "rssi": h["r"], "sent": bool(h.get("x"))} for h in sorted(heard, key=lambda x: (not x.get("x"), x["h"]))]})
    c = CONF["messages"]
    return {"messages": out, "channels": chan_rows(), "regions": c["regions"], "counts": counts,
            "unreadable": unread, "catalogue": cat_status(), "tx_enabled": bool(c["tx_enabled"]), "sender": c["sender"]}

def clear_messages(who, chan="", region="", direction="", q=""):
    """Delete stored messages (all, or only those matching the filters). Admin only (enforced by the route)."""
    where, args = [], []
    if chan: where.append("chan=?"); args.append(chan)
    if region == "-": where.append("region=''")
    elif region: where.append("region=?"); args.append(region)
    if direction in ("rx", "tx"): where.append("dir=?"); args.append(direction)
    if q: where.append("(text LIKE ? OR sender LIKE ?)"); args += ["%" + q + "%"] * 2
    with LOCK:
        cur = DB.execute("DELETE FROM messages" + (" WHERE " + " AND ".join(where) if where else ""), args)
        n = cur.rowcount
        if not where: MSGSTAT.clear(); RECENT_GRP.clear()
    audit(who, "messages cleared", chan or "all channels", "%d removed%s" % (n, "" if not where else " (filtered)"))
    return {"ok": True, "removed": n}

def purge_log(who, table, days):
    """Delete audit or event rows older than `days`. The audit log can never be wiped completely (days >= 1)."""
    if table not in ("audit", "events"): return {"ok": False, "error": "unknown log"}
    try: days = int(days or 0)
    except (TypeError, ValueError): return {"ok": False, "error": "days must be a number"}
    if not 0 <= days <= 3650 or (table == "audit" and days < 1): return {"ok": False, "error": "days must be 1 to 3650" if table == "audit" else "days must be 0 to 3650"}
    with LOCK: n = (DB.execute("DELETE FROM %s WHERE ts<?" % table, (int(time.time()) - days * 86400,)) if days else DB.execute("DELETE FROM %s" % table)).rowcount
    audit(who, table + " cleared", ("older than %d days" % days) if days else "everything", "%d removed" % n)
    return {"ok": True, "removed": n}

def send_message(who, chan, region, text, sender=None, via=None):
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
    live = [d for d in list(DEV.values()) if d["last"] and now - d["last"] < CONF["stale_minutes"] * 60]
    if not live: return {"ok": False, "error": "no repeater is online to send it"}
    want = [str(v).upper() for v in (via or []) if v]
    if want:                                                    # send through only these repeaters (the firmware drops it elsewhere)
        live = [d for d in live if d["id"].upper() in want]
        if not live: return {"ok": False, "error": "the repeater you chose is not online"}
    targets = ",".join(d["id"].upper() for d in live) if want else ""
    raw = MSG.build_group_text(ch, sender, text, int(now), region or None)
    area = CONF["join_iata"]
    body = json.dumps({"origin": "UMC Dashboard", "origin_id": DASH_ID, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now)), "type": "RAW", **({"target": targets} if targets else {}), "data": raw.hex().upper()}, separators=(",", ":")).encode()
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
                if b and passed > b.get("passed", passed): d["last_tx"] = now      # the bridge sent something to the radio since the last poll
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

def enrol_approve(who, dev, name=None, bridge=None, role="repeater"):
    dev = str(dev).upper()
    if role not in ("repeater", "client"): return {"ok": False, "error": "role: repeater or client"}
    conn = CTL.get("conn")
    if not conn or not conn.up: return {"ok": False, "error": "the control link to the broker is down, so the answer could not be sent"}
    with LOCK: p = ENROL["pending"].get(dev)
    if not p: return {"ok": False, "error": "that request is no longer waiting"}
    existing = next((a for a in accounts() if a["device"] == dev), None)
    if existing and existing["role"] != role: return {"ok": False, "error": "that id already has a %s account (%s); remove it first to approve it as a %s" % (existing["role"], existing["name"], role)}
    if existing: slug = existing["name"]; r = admin_call(op="user_passwd", name=slug)
    else:
        slug = enrol_slug(name or p.get("name"), dev); r = admin_call(op="user_add", name=slug, role=role, device=dev)
    if not r.get("ok") or not r.get("password"):
        audit(who, "enrol approve", dev[:12], r.get("error") or r.get("output") or "failed", False)
        return {"ok": False, "error": r.get("error") or r.get("output") or "could not make the account"}
    try:
        if role == "client": code = make_setup_code(CFG["host"], slug, r["password"], dev, CONF["join_iata"])       # no control key, no bridge settings
        else: code = make_join_code(slug, r["password"], CONF["join_iata"], control_key(dev, create=True), CONF["join_bridge"] if bridge is None else bool(bridge))
    except ValueError as e: return {"ok": False, "error": str(e)}
    conn.publish("umcnet/v1/enrol/grant/" + dev, ENR.make_grant(dev, code).encode(), retain=True)
    with LOCK:
        ENROL["pending"].pop(dev, None)
        ENROL["approved"][dev] = {"account": slug, "name": p.get("name", ""), "at": time.time(), "delivered": False}
    enrol_save(); export_accounts_soon()
    audit(who, "enrol approve", dev[:12], "account %s as client" % slug if role == "client" else "account %s, remote control key included" % slug)
    return {"ok": True, "account": slug, "role": role}

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
        with LOCK: online = any(c.get("user") == a["account"] and c.get("state") == "connected" for c in list(CLIENTS.values()))
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
        ips = {c.get("client", ""): c.get("ip", "") for c in list(CLIENTS.values())}
    accts = {a["device"]: a["name"] for a in accounts() if a["device"]}
    for p in pend:
        p["ip"] = ips.get("umc-enrol-" + p["id"][:12], ""); p["age"] = int(now - p["last"]); p["existing"] = accts.get(p["id"], "")
    return {"enabled": bool(CONF.get("enrol_enabled", True)), "pending": sorted(pend, key=lambda x: x["first"]), "declined": sorted(dec, key=lambda x: -x["at"]), "approved": app}

def on_control_reply(topic, payload, retained=False):
    if topic == "umcnet/v1/enrol/hello": return enrol_hello(payload, retained)
    if "/replay/req/" in topic: replay_request(topic, payload, retained); return
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

# ----------------------------------------------------------------------------- statistics, link checks, report, export
# Every heard packet with a known sender is counted per hour, per node, per receiving repeater, per type and per hop count.
# Counts are held in memory and written to the traffic table every minute, so the history survives a restart.
TRAFFIC_BUF = collections.Counter(); TRAFFIC_LOCK = threading.Lock()
ROUTE_BUF = {}      # (hour, path, receiving repeater) -> [receptions, newest time]; flood packets only (their path is the one actually travelled)
SNR_BUF = {}        # (hour, node) -> [count, sum, min, max]; only packets heard with no repeater between (flood, 0 hops)
HOP_BUF = collections.Counter()   # (hour, receiving repeater, hop count) -> packets; flood packets only (a direct-routed packet's path is what is left to travel, not what it has travelled)
BUF_CAP = 20000
ROUTES_PER_HOUR = 2000      # new route rows a clock hour may add (an existing row is always counted); beyond that new paths are dropped, and counted
ROUTES_MAX_ROWS = 150000    # the whole table, oldest hours go first
ROUTE_MAX_HOPS = 64

def route_note(path, rx, now):
    if not path or len(path) > ROUTE_MAX_HOPS: return False
    key = (int(now) // 3600 * 3600, ",".join(path), rx)
    with TRAFFIC_LOCK:
        e = ROUTE_BUF.get(key)
        if e is None:
            if len(ROUTE_BUF) >= BUF_CAP: return False
            ROUTE_BUF[key] = [1, int(now)]
        else: e[0] += 1; e[1] = max(e[1], int(now))
    return True

def snr_value(v):
    """A usable SNR in dB or None. A missing or unreadable value is not 0 dB."""
    try: f = float(v)
    except (TypeError, ValueError): return None
    return f if f == f and abs(f) < 200 else None

def snr_note(node, snr, now):
    f = snr_value(snr)
    if f is None: return False
    key = (int(now) // 3600 * 3600, node)
    with TRAFFIC_LOCK:
        e = SNR_BUF.get(key)
        if e is None:
            if len(SNR_BUF) >= BUF_CAP: return False
            SNR_BUF[key] = [1, f, f, f]
        else: e[0] += 1; e[1] += f; e[2] = min(e[2], f); e[3] = max(e[3], f)
    return True

def traffic_flush():
    with TRAFFIC_LOCK:
        items = list(TRAFFIC_BUF.items()); TRAFFIC_BUF.clear()
        routes = list(ROUTE_BUF.items()); ROUTE_BUF.clear(); snrs = list(SNR_BUF.items()); SNR_BUF.clear(); hops = list(HOP_BUF.items()); HOP_BUF.clear()
    if not (items or routes or snrs or hops): return
    with LOCK:
        if hops: DB.executemany("INSERT INTO hophist VALUES(?,?,?,?) ON CONFLICT(h, rx, hops) DO UPDATE SET n = n + excluded.n", [(h, rx, hp, n) for (h, rx, hp), n in hops])
        if items: DB.executemany("INSERT INTO traffic VALUES(?,?,?,?,?,?) ON CONFLICT(h, node, rx, ptype, hops) DO UPDATE SET n = n + excluded.n",
                                 [(h, node, rx, pt, hp, n) for (h, node, rx, pt, hp), n in items])
        if routes:
            room = {}; keep = []
            for (h, p, rx), (n, last) in sorted(routes, key=lambda r: -r[1][0]):       # the busiest paths first, so a flood of one-off paths is what gets dropped
                if h not in room: room[h] = max(0, ROUTES_PER_HOUR - DB.execute("SELECT COUNT(*) FROM routes WHERE h=?", (h,)).fetchone()[0])
                if DB.execute("SELECT 1 FROM routes WHERE h=? AND path=? AND rx=?", (h, p, rx)).fetchone() is None:
                    if room[h] <= 0: COUNT["routes_dropped"] += 1; continue
                    room[h] -= 1
                keep.append((h, p, rx, n, last))
            if keep: DB.executemany("INSERT INTO routes VALUES(?,?,?,?,?) ON CONFLICT(h, path, rx) DO UPDATE SET n = n + excluded.n, last = MAX(last, excluded.last)", keep)
        if snrs: DB.executemany("INSERT INTO snr VALUES(?,?,?,?,?,?) ON CONFLICT(h, node) DO UPDATE SET n = n + excluded.n, s = s + excluded.s, lo = MIN(lo, excluded.lo), hi = MAX(hi, excluded.hi)",
                                [(h, node, n, sm, lo, hi) for (h, node), (n, sm, lo, hi) in snrs])

def traffic_loop():
    time.sleep(30)
    while True:
        try:
            traffic_flush()
        except Exception as e: sys.stderr.write("traffic: %s\n" % e)
        time.sleep(60)

def node_stats(key, days=7):
    """Hour-by-hour activity for one node, with its packet types, hop counts and the repeaters that heard it most."""
    try: days = int(days) if str(days).strip() != "" else 7
    except (TypeError, ValueError): days = 7
    days = max(1, min(30, days))
    now = int(time.time()); start = (now - days * 86400) // 3600 * 3600
    traffic_flush()
    with LOCK: rows = DB.execute("SELECT h, rx, ptype, hops, n FROM traffic WHERE node = ? AND h >= ?", (key, start)).fetchall()
    hourly = collections.Counter(); types = collections.Counter(); hops = collections.Counter(); rxs = collections.Counter()
    for h, rx, pt, hp, n in rows: hourly[h] += n; types[pt] += n; hops[hp] += n; rxs[rx] += n
    names = {}
    for k in set(rxs): names[k] = (DEV.get(k) or {}).get("name") or (NODES.get(k) or {}).get("name") or k[:8]
    total = sum(hourly.values())
    return {"key": key, "name": (NODES.get(key) or {}).get("name") or key[:8], "days": days, "total": total,
            "series": [{"h": h, "n": hourly.get(h, 0)} for h in range(start, now // 3600 * 3600 + 1, 3600)],
            "types": [{"type": t, "n": n} for t, n in types.most_common()],
            "hops": [{"hops": hp, "n": n} for hp, n in sorted(hops.items())],
            "receivers": [{"rx": r, "name": names.get(r, r[:8]), "n": n} for r, n in rxs.most_common(10)]}

def link_checks(hours=48):
    """Links between our own repeaters only: a one-way hearing, and a repeater that transmits well but hears badly."""
    own = {d["id"]: (d["name"] or d["id"][:8]) for d in list(DEV.values())}
    cut = int(time.time()) - hours * 3600
    with LOCK: rows = DB.execute("SELECT a, b, snr FROM links WHERE last > ?", (cut,)).fetchall()
    heard = {}; best_in = {}; best_out = {}
    for a, b, snr in rows:
        if a not in own or b not in own: continue
        heard[(a, b)] = snr
        if snr is not None:
            best_in[a] = max(best_in.get(a, -999), snr); best_out[b] = max(best_out.get(b, -999), snr)
    one_way = [{"hears": own[a], "heard": own[b], "snr": heard[(a, b)]} for (a, b) in heard if (b, a) not in heard]
    deaf = []
    for r in own:
        if r in best_out and r in best_in and best_out[r] - best_in[r] >= 10:
            deaf.append({"name": own[r], "heard_by_others": best_out[r], "hears_best": best_in[r], "gap": round(best_out[r] - best_in[r], 1)})
    return {"hours": hours, "one_way": sorted(one_way, key=lambda x: x["hears"]), "deaf": sorted(deaf, key=lambda x: -x["gap"])}

def weekly_report():
    """A plain-text week: traffic, busiest nodes, repeater state and link problems."""
    now = time.time(); since = int(now) - 7 * 86400
    traffic_flush()
    with LOCK:
        tot = DB.execute("SELECT COALESCE(SUM(n),0) FROM traffic WHERE h >= ?", (since,)).fetchone()[0]
        top = DB.execute("SELECT node, SUM(n) FROM traffic WHERE h >= ? GROUP BY node ORDER BY 2 DESC LIMIT 10", (since,)).fetchall()
        byt = DB.execute("SELECT ptype, SUM(n) FROM traffic WHERE h >= ? GROUP BY ptype ORDER BY 2 DESC", (since,)).fetchall()
    lc = link_checks(168)
    lines = ["UMC weekly report", "Period: %s to %s" % (time.strftime("%d %b %Y", time.localtime(since)), time.strftime("%d %b %Y", time.localtime(now))), "",
             "Packets with a known sender: %d" % tot, "", "By type", *["  %-8s %d" % (t, n) for t, n in byt], "", "Busiest nodes"]
    lines += ["  %-24s %d" % ((NODES.get(k) or {}).get("name") or k[:8], n) for k, n in top] or ["  none"]
    lines += ["", "Own repeaters"]
    for d in list(DEV.values()):
        seen = time.strftime("%d %b %H:%M", time.localtime(d["last"])) if d.get("last") else "never"
        lines.append("  %-24s last heard %s" % (d["name"] or d["id"][:8], seen))
    lines += ["", "One-way hearing (own repeaters, last 7 days)"] + (["  %s hears %s (%s dB), not the other way" % (x["hears"], x["heard"], x["snr"]) for x in lc["one_way"]] or ["  none"])
    lines += ["", "Possible deaf repeaters (transmit well, hear badly)"] + (["  %s: gap about %s dB" % (x["name"], x["gap"]) for x in lc["deaf"]] or ["  none"])
    return "\n".join(lines) + "\n"

def geojson_export(hours=None):
    """Positioned nodes as points and measured links as lines, for GIS tools."""
    net = network_view(hours or CONF["map_hours"])
    pos = {n["key"]: n for n in net["nodes"] if n.get("lat") is not None and n.get("lon") is not None}
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [n["lon"], n["lat"]]},
              "properties": {"key": k, "name": n["name"], "type": n["type"], "online": bool(n.get("online"))}} for k, n in pos.items()]
    for l in net["links"]:
        a, b = pos.get(l["recv"]), pos.get(l["node"])
        if a and b:
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[a["lon"], a["lat"]], [b["lon"], b["lat"]]]},
                          "properties": {"from": a["name"], "to": b["name"], "hops": l["hops"], "packets": l["n"], "snr": l["snr"]}})
    return {"type": "FeatureCollection", "features": feats}

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

# ----------------------------------------------------------------------------- housekeeping: retention, backup, ID collisions, airtime, new nodes
def prune_batched(table, col, cut, batch=5000):
    """Delete rows older than `cut` a few thousand at a time, letting the packet handler in between. Table and column names are ours, never user input."""
    total = 0
    while True:
        with LOCK:
            n = DB.execute("DELETE FROM %s WHERE rowid IN (SELECT rowid FROM %s WHERE %s<? LIMIT ?)" % (table, table, col), (cut, batch)).rowcount
        total += n
        if n < batch: return total
        time.sleep(0.05)

NEWNODES_MAX_ROWS = 50000

def prune_excess(table, col, cap, batch=5000):
    """Keep at most `cap` rows: the oldest by `col` go. Table and column names are ours, never user input."""
    with LOCK: n = DB.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    if n <= cap: return 0
    return prune_batched_rows(table, col, n - cap, batch)

def prune_batched_rows(table, col, count, batch=5000):
    total = 0
    while total < count:
        with LOCK: k = DB.execute("DELETE FROM %s WHERE rowid IN (SELECT rowid FROM %s ORDER BY %s ASC LIMIT ?)" % (table, table, col), (min(batch, count - total),)).rowcount
        total += k
        if k <= 0: break
        time.sleep(0.01)
    return total

def retention_run(now=None):
    """Trim the high-volume tables to their configured age. Presence and history views read telem (kept at least 8 days) and traffic (at least 7)."""
    now = int(now or time.time()); C = CONF
    if CFG["backup"] and not BACKUP["ts"]: return {"skipped": "no database backup has succeeded yet: nothing is deleted until one has"}
    return {"traffic": prune_batched("traffic", "h", now - max(7, C["traffic_keep_days"]) * 86400),
            "telem": telem_prune(now),
            "routes": prune_batched("routes", "h", now - max(8, C["traffic_keep_days"]) * 86400),
            "snr": prune_batched("snr", "h", now - max(8, C["traffic_keep_days"]) * 86400),
            "airtime": prune_batched("airtime", "ts", now - max(8, C["telem_keep_days"]) * 86400),
            "newnodes": prune_batched("newnodes", "ts", now - 365 * 86400),
            "hophist": prune_batched("hophist", "h", now - max(8, C["traffic_keep_days"]) * 86400),
            "clockdrift": prune_batched("clockdrift", "ts", now - 14 * 86400),
            "routes_excess": prune_excess("routes", "h", ROUTES_MAX_ROWS), "newnodes_excess": prune_excess("newnodes", "ts", NEWNODES_MAX_ROWS)}

# --- D1: nightly consistent backup of the database
BACKUP_RX = re.compile(r"^dash-\d{8}-\d{6}\.sqlite$")
BACKUP_TMP_RX = re.compile(r"^\.tmp-dash-\d{8}-\d{6}\.sqlite$")
BACKUP = {"ts": 0, "size": 0, "ok": None, "error": "", "secs": 0.0, "count": 0, "try": 0}
BACKUP_LOCK = threading.Lock()

def db_path(): return os.path.join(CFG["data"], "dash.sqlite")
def backup_dir(): return CFG["backup_dir"] or os.path.join(CFG["data"], "backups")
def backup_name(ts): return time.strftime("dash-%Y%m%d-%H%M%S.sqlite", time.gmtime(ts))

def backup_split(names, keep):
    """(kept, removed): the newest `keep` backup files stay. Names that are not ours are never touched."""
    ours = sorted(n for n in names if BACKUP_RX.match(n))
    keep = max(1, int(keep))
    return ours[-keep:], ours[:-keep]

def backup_space_needed(path):
    """Free space wanted before a backup: twice the database and its WAL."""
    return 2 * sum(os.path.getsize(path + x) for x in ("", "-wal") if os.path.exists(path + x))

def backup_restore_check(path, table="messages"):
    """Open a backup read-only and count rows in `table`: proof that it can be restored. Returns the count."""
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try: return c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally: c.close()

def backup_due(now, last_ok, last_try, hour):
    """One backup a day, at or after `hour` (UTC); the first one as soon as there is none; a failed or fresh try is not repeated for an hour."""
    if now - last_try < 3600: return False
    if not last_ok: return True
    if now - last_ok < 23 * 3600: return False
    return time.gmtime(now).tm_hour >= hour

def backup_run(now=None):
    """Copy the live database with SQLite's online backup (a consistent snapshot, the packet handler keeps writing), check it, then rename it into place."""
    if not BACKUP_LOCK.acquire(blocking=False): return dict(BACKUP)
    t0 = time.time(); now = int(now or t0); d = backup_dir(); tmp = os.path.join(d, ".tmp-" + backup_name(now))
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        for n in os.listdir(d):                                  # half-written copies left by a crash or a kill: ours only, and only while we hold the lock
            if BACKUP_TMP_RX.match(n):
                try: os.remove(os.path.join(d, n))
                except OSError: pass
        need = backup_space_needed(db_path())
        free = shutil.disk_usage(d).free
        if free < need: raise RuntimeError("skipped: %.0f MB free, %.0f MB needed (twice the database)" % (free / 1e6, need / 1e6))
        src = sqlite3.connect(db_path(), timeout=30); dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            chk = dst.execute("PRAGMA integrity_check").fetchone()
            if not chk or chk[0] != "ok": raise RuntimeError("the copy failed its integrity check")
        finally:
            dst.close(); src.close()
        os.chmod(tmp, 0o600)
        with open(tmp, "rb") as f: os.fsync(f.fileno())
        final = os.path.join(d, backup_name(now)); os.replace(tmp, final)
        _kept, gone = backup_split(os.listdir(d), CONF["backup_keep"])
        for n in gone:
            try: os.remove(os.path.join(d, n))
            except OSError: pass
        BACKUP.update({"ts": now, "size": os.path.getsize(final), "ok": True, "error": "", "secs": round(time.time() - t0, 2), "count": len(_kept)})
    except Exception as e:
        try: os.remove(tmp)
        except OSError: pass
        BACKUP.update({"ok": False, "error": str(e)[:200]}); sys.stderr.write("backup: %s\n" % e)
    finally:
        BACKUP_LOCK.release()
    return dict(BACKUP)

def backup_load():
    """After a restart, pick up the newest backup already on disk, so the Checks card does not start from nothing."""
    d = backup_dir()
    try: names = sorted(n for n in os.listdir(d) if BACKUP_RX.match(n))
    except OSError: return
    if names:
        st = os.stat(os.path.join(d, names[-1])); BACKUP.update({"ts": int(st.st_mtime), "size": st.st_size, "ok": True, "error": "", "count": len(names)})

def backup_view(now=None):
    now = now or time.time()
    return {"enabled": CFG["backup"], "dir": backup_dir(), "ts": BACKUP["ts"], "age": int(now - BACKUP["ts"]) if BACKUP["ts"] else None, "size": BACKUP["size"], "ok": BACKUP["ok"],
            "error": BACKUP["error"], "count": BACKUP["count"], "keep": CONF["backup_keep"], "secs": BACKUP["secs"]}

def backup_check(v, uptime):
    """The Checks line for a backup view: (level, title, detail), or None when backups are switched off."""
    if not v["enabled"]: return None
    if v["ok"] is False: return ("bad", "Database backup failed", "%s (last good: %s)" % (v["error"] or "unknown error", time.strftime("%d %b %H:%M", time.localtime(v["ts"])) if v["ts"] else "none"))
    if not v["ts"]: return ("warn", "No database backup yet", "the first one runs shortly after start") if uptime > 7200 else None
    when = time.strftime("%d %b %H:%M", time.localtime(v["ts"])); size = "%.1f MB" % (v["size"] / 1e6)
    if v["age"] > 36 * 3600: return ("warn", "Database backup is old", "last one %s, %s: the nightly run has not worked" % (when, size))
    return ("ok", "Database backup", "%s, %s, %d kept" % (when, size, v["count"]))

# --- D2: repeater ID collisions (the path in a packet names a repeater by the first 1, 2 or 3 bytes of its key)
COLL = {"seen": {}}
def collisions_path(): return os.path.join(CFG["data"], "collisions.json")

def collisions_load():
    try: seen = json.load(open(collisions_path())).get("seen", {})
    except Exception: seen = {}
    COLL["seen"] = {k: v for k, v in seen.items() if isinstance(k, str)} if isinstance(seen, dict) else {}

def collisions_save():
    seen = dict(sorted(COLL["seen"].items(), key=lambda kv: kv[1])[-2000:]); COLL["seen"] = seen
    tmp = collisions_path() + ".tmp"
    with open(tmp, "w") as f: json.dump({"seen": seen}, f)
    os.replace(tmp, collisions_path())

def collisions_find(nodes):
    """nodes: [(full key hex, name)]. Every group of two or more sharing the first 1, 2 or 3 bytes, with a severity: 1 byte info, 2 warn, 3 bad."""
    uniq = {}
    for k, nm in nodes:
        if isinstance(k, str) and len(k) >= 6: uniq[k.upper()] = nm or ""
    out = []
    for nb, level in ((1, "info"), (2, "warn"), (3, "bad")):
        groups = collections.defaultdict(list)
        for k, nm in uniq.items(): groups[k[:2 * nb]].append((k, nm))
        for p, mem in sorted(groups.items()):
            if len(mem) < 2: continue
            mem.sort()
            out.append({"bytes": nb, "prefix": p, "level": level, "nodes": [{"key": k, "name": nm} for k, nm in mem],
                        "id": "%d:%s:%s" % (nb, p, hashlib.sha1(",".join(k for k, _ in mem).encode()).hexdigest()[:10])})
    return out

def collisions_new(found, seen):
    """The collisions worth an alert that we have not alerted about: 2 and 3 byte ones (a 1 byte overlap is normal beyond a few dozen repeaters)."""
    return [c for c in found if c["bytes"] >= 2 and c["id"] not in seen]

def repeater_keys(now=None):
    now = now or time.time(); out = {}
    for k, n in list(NODES.items()):
        if n["type"] == 2 and n["last"] and now - n["last"] < 30 * 86400: out[k] = n["name"]
    for d in list(DEV.values()): out[d["id"]] = d["name"] or out.get(d["id"], "")
    return list(out.items())

def collisions_view(now=None): return collisions_find(repeater_keys(now))

def collision_alerts(now=None):
    now = int(now or time.time()); new = collisions_new(collisions_view(now), COLL["seen"])
    if not new: return 0
    for c in new:
        COLL["seen"][c["id"]] = now
        names = ", ".join((x["name"] or x["key"][:8]) for x in c["nodes"][:6])
        if CONF["alerts"].get("collision", True):
            send_alert("Repeater ID clash (%d byte)" % c["bytes"], "%d repeaters share the ID %s: %s" % (len(c["nodes"]), c["prefix"], names), "bad" if c["bytes"] >= 3 else "warn", "collision")
    try: collisions_save()
    except OSError as e: sys.stderr.write("collisions: %s\n" % e)
    return len(new)

# --- D3: airtime and duty cycle per repeater, from the tx_air_secs / rx_air_secs counters in each status message
AIR_LAST = {}
AIR_MAX_SECS = 1e10          # about 300 years of airtime: a counter past this is not a counter
def airtime_sample(stats):
    """(tx_air_secs, rx_air_secs) from a status block, or None."""
    try:
        tx = finite_num(stats["tx_air_secs"], 0, AIR_MAX_SECS); rx = finite_num(stats.get("rx_air_secs", 0), 0, AIR_MAX_SECS)
    except (KeyError, TypeError, AttributeError): return None
    return (tx, rx) if tx is not None and rx is not None else None

def airtime_note(did, stats, now, boot=None):
    s = airtime_sample(stats)
    if not s or now - AIR_LAST.get(did, 0) < 55: return False
    AIR_LAST[did] = now
    with LOCK: DB.execute("INSERT INTO airtime VALUES(?,?,?,?,?)", (did, int(now), s[0], s[1], boot))
    return True

def boot_note(d, boot, now):
    """Remember the repeater's boot id (a 64-bit hex string in its status). A change means it rebooted; an absent id is unknown, never a reboot."""
    if not isinstance(boot, str) or not re.match(r"^[0-9A-Fa-f]{1,16}$", boot): return False
    boot = boot.upper(); old = d.get("boot_id"); d["boot_id"] = boot
    if old and old != boot:
        d["boot_changed"] = now; d["reboots"] = d.get("reboots", 0) + 1; return True
    return False

def duty_steps(rows, max_gap=3600):
    """rows: [(ts, tx_total, rx_total[, boot_id])] oldest first -> [(ts, seconds, tx_seconds, rx_seconds)] for each pair.
    A counter that went backwards, a changed boot id (both mean a reboot) or a long silence gives no step: that time is missing data, not zero."""
    out = []
    for a, b in zip(rows, rows[1:]):
        t0, x0, r0 = a[:3]; t1, x1, r1 = b[:3]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in (t0, x0, r0, t1, x1, r1)): continue      # NULL, NaN or infinity in the table: missing data, never a number
        dt = t1 - t0
        if len(a) > 3 and len(b) > 3 and a[3] and b[3] and a[3] != b[3]: continue
        if dt <= 0 or dt > max_gap or x1 < x0 or r1 < r0: continue
        out.append((t1, dt, min(x1 - x0, dt), min(r1 - r0, dt)))
    return out

def duty_buckets(steps, since, now, n=120):
    """Steps averaged into at most n buckets: [[time, tx %, rx %]]."""
    width = max(60, (now - since) / float(n)); acc = {}
    for t, dt, tx, rx in steps:
        if t < since: continue
        b = acc.setdefault(min(n - 1, int((t - since) // width)), [0.0, 0.0, 0.0]); b[0] += dt; b[1] += tx; b[2] += rx
    return [[int(since + (i + 0.5) * width), round(100.0 * b[1] / b[0], 2), round(100.0 * b[2] / b[0], 2)] for i, b in sorted(acc.items()) if b[0] > 0]

def duty_window(steps, since):
    """(tx duty % over the window, seconds of the window covered by readings)."""
    dt = sum(s[1] for s in steps if s[0] > since); tx = sum(s[2] for s in steps if s[0] > since)
    return (100.0 * tx / dt if dt else None), dt

AIR_COOLDOWN = 1800
def duty_alert_step(active, avg, covered, thr, minutes, since_recover=None):
    """'fire' when the rolling average reaches thr (with readings for most of the window) and it is not within the cooldown after the last recovery;
    'recover' once it is back under 80 % of thr; else None. No readings is neither: the state is kept."""
    if avg is None or covered < 0.6 * minutes * 60: return None
    if not active and avg >= thr: return None if since_recover is not None and since_recover < AIR_COOLDOWN else "fire"
    if active and avg < thr * 0.8: return "recover"
    return None

def airtime_rows(did, since):
    with LOCK: return DB.execute("SELECT ts,tx,rx,boot FROM airtime WHERE did=? AND ts>=? ORDER BY ts", (did, int(since))).fetchall()

def airtime_view(hours=24, now=None, allowed=None):
    now = int(now or time.time()); hours = max(1, min(168, finite_num(hours) or 24)); since = now - int(hours * 3600); out = []
    with LOCK: ids = [r[0] for r in DB.execute("SELECT DISTINCT did FROM airtime WHERE ts>=?", (since,)).fetchall()]
    for did in ids:
        if allowed is not None and did not in allowed: continue
        pts = duty_buckets(duty_steps(airtime_rows(did, since - 3600)), since, now)
        if not pts: continue
        out.append({"id": did, "name": (DEV.get(did) or {}).get("name") or did[:8], "points": pts, "tx_now": pts[-1][1], "tx_avg": round(sum(p[1] for p in pts) / len(pts), 2), "tx_max": max(p[1] for p in pts), "rx_avg": round(sum(p[2] for p in pts) / len(pts), 2)})
    out.sort(key=lambda r: r["name"].lower())
    return {"hours": hours, "since": since, "now": now, "warn_pct": CONF["airtime_warn_pct"], "warn_minutes": CONF["airtime_warn_minutes"], "devices": out}

def alert_clear_stale(prefix, live, now):
    """Active alert states under `prefix` whose subject is not in `live` (no data in the window, or the alert is off) are cleared, silently:
    an alert about a repeater that has gone quiet must not stay red for ever."""
    n = 0
    for key in alert_keys(prefix):
        if key not in live: alert_put(key, "clear", now); n += 1
    return n

def airtime_alerts(now=None):
    now = int(now or time.time()); thr = CONF["airtime_warn_pct"]; mins = CONF["airtime_warn_minutes"]
    if not CONF["alerts"].get("airtime", True): return {"cleared": alert_clear_stale("air:", set(), now)}
    with LOCK: ids = [r[0] for r in DB.execute("SELECT DISTINCT did FROM airtime WHERE ts>=?", (now - mins * 60 - 300,)).fetchall()]
    live = set()
    for did in ids:
        steps = duty_steps(airtime_rows(did, now - mins * 60 - 300)); avg, cov = duty_window(steps, now - mins * 60)
        key = "air:" + did; state, ts = alert_get(key); act = state == "active"
        if avg is not None and cov >= 0.6 * mins * 60: live.add(key)             # readings for most of the window: the state means something
        step = duty_alert_step(act, avg, cov, thr, mins, now - ts if state == "clear" else None); nm = (DEV.get(did) or {}).get("name") or did[:8]
        if step == "fire":
            alert_put(key, "active", now); send_alert("High airtime: " + nm, "transmitting %.1f%% of the time over %d minutes (limit %d%%)" % (avg, mins, thr), "warn", "airtime")
        elif step == "recover":
            alert_put(key, "clear", now); send_alert("Airtime back to normal: " + nm, "%.1f%% over %d minutes" % (avg, mins), "ok", "airtime")
    return {"cleared": alert_clear_stale("air:", live, now)}

# --- D4: a node never heard before
NEWNODE_ALERTS = collections.deque(maxlen=500)
def newnode_decide(now, started, warm_s, recent, cap):
    """'warmup' for the first minutes after start (the whole mesh looks new then), 'capped' past `cap` alerts in the last hour, else 'alert'."""
    if now - started < warm_s: return "warmup"
    if len([t for t in recent if now - t < 3600]) >= cap: return "capped"
    return "alert"

def newnode_seen(key, n, rx, now):
    state = newnode_decide(now, START, CONF["newnode_warmup_minutes"] * 60, NEWNODE_ALERTS, CONF["newnode_max_per_hour"])
    with LOCK: added = DB.execute("INSERT OR IGNORE INTO newnodes VALUES(?,?,?,?,?,?)", (key, int(now), n["name"], n["type"], rx, state)).rowcount
    if not added: return "known"                      # recorded before (persistent), however NODES came to forget it
    if state == "alert":
        NEWNODE_ALERTS.append(now)
        if CONF["alerts"].get("newnode", True):
            send_alert("New node heard: " + (n["name"] or key[:8]), "%s, id %s, first heard by %s" % (NODE_KIND.get(n["type"], "node"), key[:8], (DEV.get(rx) or {}).get("name") or rx[:8]), "ok", "newnode")
    return state

def newnodes_baseline(now=None):
    """Nodes already known (loaded from nodes.json, or present while the table is empty after a restore) are recorded as the baseline, silently."""
    now = int(now or time.time())
    with LOCK:
        have = {r[0] for r in DB.execute("SELECT key FROM newnodes")}
        rows = [(k, int(n.get("first") or now), n.get("name", ""), n.get("type", 0), "", "baseline") for k, n in list(NODES.items()) if k not in have]
        DB.executemany("INSERT OR IGNORE INTO newnodes VALUES(?,?,?,?,?,?)", rows)
    return len(rows)

def newnodes_recent(limit=20):
    with LOCK: rows = DB.execute("SELECT key,ts,name,kind,rx,state FROM newnodes WHERE state!='baseline' ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [{"key": k, "ts": ts, "name": nm or "", "kind": NODE_KIND.get(kd, "node"), "rx": (DEV.get(rx) or {}).get("name") or (rx or "")[:8], "state": st} for k, ts, nm, kd, rx, st in rows if st != "baseline"]

# --- persistent alert state (survives a restart, so nothing is announced twice and a recovery is not lost)
def alert_get(key):
    with LOCK: r = DB.execute("SELECT state, ts FROM alertstate WHERE key=?", (key,)).fetchone()
    return (r[0], r[1]) if r else (None, 0)

def alert_put(key, state, ts):
    with LOCK: DB.execute("INSERT OR REPLACE INTO alertstate VALUES(?,?,?)", (key, state, int(ts)))

def alert_keys(prefix):
    with LOCK: return [r[0] for r in DB.execute("SELECT key FROM alertstate WHERE key LIKE ? AND state='active'", (prefix.replace("%", "") + "%",)).fetchall()]

def alert_drop(key):
    with LOCK: DB.execute("DELETE FROM alertstate WHERE key=?", (key,))

# --- D7: a repeater silent for longer than its own limit (or the global one)
SILENT_COOLDOWN = 1800
def silent_minutes(did):
    """Minutes of silence before this repeater is called silent: its own override, else the global default."""
    m = (CONF.get("silent_overrides") or {}).get(did)
    return m if isinstance(m, int) and 2 <= m <= 1440 else CONF["stale_minutes"]

def silent_step(active, age, thr, since_recover=None, cooldown=SILENT_COOLDOWN):
    """age and thr in seconds; None age = never heard, which is unknown, not silent. 'fire' once past thr (not within `cooldown` of the last recovery);
    'recover' only when well back under it (half of thr), so a repeater reporting at about the limit does not flap; else None."""
    if age is None: return None
    if not active and age > thr: return None if since_recover is not None and since_recover < cooldown else "fire"
    if active and age <= thr * 0.5: return "recover"
    return None

def silent_alerts(now=None):
    now = int(now or time.time()); a = CONF["alerts"]
    with LOCK: devs = [dict(d) for d in list(DEV.values())]
    link_ok = MQTT["state"] == "connected" and now - MQTT.get("since", 0) >= 60      # a dashboard that cannot hear the broker hears nobody: that is not silence
    out = []
    for d in devs:
        key = "off:" + d["id"]; state, ts = alert_get(key); active = state == "active"
        age = now - d["last"] if d["last"] else None; thr = silent_minutes(d["id"]) * 60
        if not link_ok and not active: continue
        step = silent_step(active, age, thr, now - ts if state == "clear" else None); name = d["name"] or d["id"][:12]
        if step == "fire":
            alert_put(key, "active", now); out.append(("fire", name))
            if a["offline"]: send_alert("Repeater silent: " + name, "nothing heard for %d minutes (limit %d)" % (age // 60, thr // 60), "warn", "offline")
        elif step == "recover":
            alert_put(key, "clear", now); out.append(("recover", name))
            if a["online"]: send_alert("Repeater back: " + name, "it is sending again", "ok", "online")
    return out

# --- D5: route health. A route here is a path a flood packet was heard to have taken, as the last repeater of it received it. This is what our
# repeaters observed, not a measure of link quality, and a route that is quiet may only be unused.
ROUTE_COOLDOWN = 6 * 3600
def route_state(age, live_s, silent_s, rx_ok, watched_s):
    """-> (state, why). 'unknown' when we cannot tell: the receiving repeater is not connected now, or the dashboard has not been watching long enough."""
    if not rx_ok: return "unknown", "the repeater that heard it is not connected now"
    if age <= live_s: return "live", ""
    if age < silent_s: return "stale", ""
    if watched_s < silent_s: return "unknown", "the dashboard has not been watching long enough to call it silent"
    return "silent", ""

def route_view(now=None, full=False):
    """Every observed route with its state. `full` returns all of them (for the alert check); the page gets the busiest 100."""
    now = int(now or time.time()); C = CONF; live_s = C["route_live_minutes"] * 60; silent_s = C["route_silent_minutes"] * 60
    traffic_flush(); cur = now // 3600 * 3600; h24 = cur - 23 * 3600; h7 = cur - 167 * 3600
    with LOCK:
        rows = DB.execute("SELECT path, rx, SUM(CASE WHEN h >= ? THEN n ELSE 0 END), SUM(n), MAX(last) FROM routes WHERE h >= ? GROUP BY path, rx", (h24, h7)).fetchall()
    out = []
    for path, rx, n24, n7, last in rows:
        d = DEV.get(rx); rx_ok = bool(d and d["last"] and now - d["last"] < C["stale_minutes"] * 60)
        st, why = route_state(max(0, now - last), live_s, silent_s, rx_ok, now - START)
        out.append({"key": path + "|" + rx, "path": [{"h": h, "n": hop_name(h)} for h in path.split(",")], "rx": rx, "rx_name": (d["name"] if d and d["name"] else rx[:8]), "last": last, "n24": n24, "n7d": n7,
                    "state": st, "why": why, "busy": n7 >= C["route_busy_packets"]})
    out.sort(key=lambda r: (-r["n7d"], r["key"]))
    return {"now": now, "live_minutes": C["route_live_minutes"], "silent_minutes": C["route_silent_minutes"], "busy_packets": C["route_busy_packets"], "total": len(out), "routes": out if full else out[:100],
            "note": "Observed receptions by our own repeaters. Not a measure of link quality: a quiet route may only be unused. Counts are receptions per whole clock hour."}

def route_alert_step(active, state, busy, since_recover=None, cooldown=ROUTE_COOLDOWN):
    """'fire' when a busy route is silent (not within `cooldown` of its last recovery); 'recover' only when it is live again (stale is not enough); unknown changes nothing."""
    if not active: return ("fire" if not (since_recover is not None and since_recover < cooldown) else None) if state == "silent" and busy else None
    return "recover" if state == "live" else None

def route_alerts(now=None):
    now = int(now or time.time()); v = route_view(now, full=True); seen = set(); fires = []; backs = []      # the whole list: a route below the page's top 100 still has its state kept
    for r in v["routes"]:
        key = "route:" + r["key"]; seen.add(key); state, ts = alert_get(key); active = state == "active"
        step = route_alert_step(active, r["state"], r["busy"], now - ts if state == "clear" else None)
        label = " > ".join((h["n"] or h["h"]) for h in r["path"]) + " > " + r["rx_name"]
        if step == "fire": alert_put(key, "active", now); fires.append("%s (%d packets in 7 days, last %d min ago)" % (label, r["n7d"], (now - r["last"]) // 60))
        elif step == "recover": alert_put(key, "clear", now); backs.append(label)
    for key in alert_keys("route:"):
        if key not in seen: alert_drop(key)          # it has left the 7 day window: nothing more to say about it
    def send(title, items, level, noun):
        if not items: return
        if len(items) <= 3:
            for t in items: send_alert("%s: %s" % (title, t.split(" (")[0]), t, level, "route")
        else: send_alert("%s: %d routes" % (title, len(items)), "; ".join(items[:8]) + ("; and %d more" % (len(items) - 8) if len(items) > 8 else ""), level, "route")
    send("Busy route silent", fires, "warn", "silent"); send("Route back", backs, "ok", "back")
    return {"fired": len(fires), "recovered": len(backs)}

# --- D6: per-node analytics from the traffic history: SNR over time (direct receptions only), hop counts and an hourly heatmap
def node_analytics(key, days=7, now=None):
    try: days = int(days) if str(days).strip() != "" else 7
    except (TypeError, ValueError): days = 7
    days = max(1, min(30, days)); now = int(now or time.time()); cur = now // 3600 * 3600
    start = cur - (days * 24 - 1) * 3600; hstart = cur - 7 * 86400 + 3600
    traffic_flush()
    with LOCK:
        hops = DB.execute("SELECT hops, SUM(n) FROM traffic WHERE node=? AND h>=? GROUP BY hops ORDER BY hops", (key, start)).fetchall()
        hrs = DB.execute("SELECT h, SUM(n) FROM traffic WHERE node=? AND h>=? GROUP BY h", (key, hstart)).fetchall()
        covered = {r[0] for r in DB.execute("SELECT DISTINCT h FROM traffic WHERE h>=?", (hstart,)).fetchall()}      # hours in which anything at all was recorded
        snr = DB.execute("SELECT h, n, s, lo, hi FROM snr WHERE node=? AND h>=? ORDER BY h", (key, start)).fetchall()
    by = dict(hrs); total = sum(n for _, n in hops)
    day0 = (hstart // 86400) * 86400; grid = []
    for di in range(8):
        d0 = day0 + di * 86400; row = []
        for hr in range(24):
            t = d0 + hr * 3600
            row.append(None if t < hstart or t > cur or t not in covered else by.get(t, 0))       # None = nothing was being recorded, which is not the same as quiet
        if any(c is not None for c in row): grid.append({"day": d0, "h": row})
    pts = [[h, round(s / n, 1), round(lo, 1), round(hi, 1), n] for h, n, s, lo, hi in snr if n > 0]
    sn = sum(p[4] for p in pts)
    summary = {"n": sn, "avg": round(sum(r[2] for r in snr if r[1] > 0) / sn, 1), "min": min(p[2] for p in pts), "max": max(p[3] for p in pts)} if sn else None
    nd = NODES.get(key) or {}
    return {"id": key, "name": nd.get("name") or key[:8], "days": days, "since": start, "now": now, "total": total, "hops": [{"hops": h, "n": n} for h, n in hops],
            "heatmap": {"utc": True, "days": grid}, "snr": {"points": pts, "summary": summary, "note": "SNR of packets heard with no repeater between (flood, 0 hops); history starts when this version was installed"} if pts else None}

def node_choices(limit=60, now=None):
    """Nodes with the most traffic in the last 7 days, for the picker."""
    now = int(now or time.time()); traffic_flush()
    with LOCK: rows = DB.execute("SELECT node, SUM(n) FROM traffic WHERE h>=? GROUP BY node ORDER BY 2 DESC LIMIT ?", (now // 3600 * 3600 - 167 * 3600, limit)).fetchall()
    return [{"id": k, "name": (NODES.get(k) or {}).get("name") or k[:8], "n": n} for k, n in rows]

# --- D7: battery voltage trend from the sensor readings (channel 1 = the repeater itself), with a rough time-to-low estimate when the data allows
BATT_CH, BATT_TYPE = 1, 116
def battery_estimate(rows, now, low_v, min_hours=6, jump=0.15, gap=3 * 3600):
    """rows: [(ts, volts)] oldest first -> (estimate dict or None, why). Uses only the readings since the last charge (a rise of `jump` V) or the last
    gap of readings, needs at least `min_hours` of them and a fall that a straight line fits, and says nothing otherwise."""
    rows = [(t, v) for t, v in rows if v is not None and 1.0 <= v <= 30.0]
    if len(rows) < 2: return None, "not enough readings"
    cut = 0
    for i in range(1, len(rows)):
        if rows[i][1] - rows[i - 1][1] >= jump or rows[i][0] - rows[i - 1][0] > gap: cut = i
    seg = rows[cut:]
    if len(seg) < 6 or seg[-1][0] - seg[0][0] < min_hours * 3600:
        return None, "needs at least %d hours of readings since the last charge or gap" % min_hours
    if now - seg[-1][0] > 3600: return None, "no reading in the last hour"
    t0 = seg[0][0]; xs = [(t - t0) / 3600.0 for t, _ in seg]; ys = [v for _, v in seg]; n = len(seg)
    mx = sum(xs) / n; my = sum(ys) / n; sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0: return None, "not enough readings"
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)); slope = sxy / sxx; r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    if slope > -0.002: return None, "not falling"
    if r2 < 0.5: return None, "too uneven to estimate"
    last = ys[-1]; eta = 0.0 if last <= low_v else (last - low_v) / -slope
    return {"slope_v_per_h": round(slope, 4), "eta_hours": round(eta, 1), "low_v": low_v, "basis_hours": round(xs[-1], 1), "n": n, "fit": round(r2, 2)}, ""

def battery_view(hours=24, now=None, allowed=None):
    now = int(now or time.time()); hours = {1: 1, 6: 6, 24: 24, 168: 168}.get(int(hours), 24); since = now - hours * 3600; low_v = CONF["battery_low_mv"] / 1000.0; out = []
    with LOCK:
        ids = [r[0] for r in DB.execute("SELECT DISTINCT did FROM telem WHERE ch=? AND type=? AND ts>=?", (BATT_CH, BATT_TYPE, since)).fetchall()]
        for did in ids:
            if allowed is not None and did not in allowed: continue
            rows = DB.execute("SELECT ts, v FROM telem WHERE did=? AND ch=? AND type=? AND ts>=? ORDER BY ts", (did, BATT_CH, BATT_TYPE, since)).fetchall()
            est, why = battery_estimate(rows, now, low_v) if hours >= 6 else (None, "choose 6 hours or more")
            pts = rows
            if len(pts) > 200: step = len(pts) / 200.0; pts = [pts[int(i * step)] for i in range(200)] + [pts[-1]]
            out.append({"id": did, "name": (DEV.get(did) or {}).get("name") or did[:8], "points": [[t, v] for t, v in pts], "now_v": rows[-1][1], "age": now - rows[-1][0],
                        "min": min(v for _, v in rows), "max": max(v for _, v in rows), "n": len(rows), "est": est, "why": why})
    out.sort(key=lambda r: r["name"].lower())
    return {"hours": hours, "since": since, "now": now, "low_v": low_v, "devices": out,
            "note": "The estimate is a straight line through the readings since the last charge, and only a rough guide: weather, load and temperature change it."}

def extra_diagnostics(now):
    """Checks lines for backup, ID collisions and airtime."""
    out = []
    b = backup_check(backup_view(now), now - START)
    if b: out.append({"level": b[0], "title": b[1], "detail": b[2]})
    cols = collisions_view(now); one = [c for c in cols if c["bytes"] == 1]
    for c in cols:
        if c["bytes"] >= 2: out.append({"level": c["level"], "title": "Repeater ID clash (%d byte): %s" % (c["bytes"], c["prefix"]), "detail": ", ".join(x["name"] or x["key"][:8] for x in c["nodes"]) + (": routes that name them by this prefix cannot tell them apart (a clash of short IDs, not a sign of a stolen key)" if c["bytes"] >= 3 else ": routes that name them by this short prefix can be mixed up (a clash of short IDs, not a sign of a stolen key)")})
    if one: out.append({"level": "ok", "title": "%d shared 1-byte repeater ID%s" % (len(one), "" if len(one) == 1 else "s"), "detail": "informational, normal once a mesh has more than a few dozen repeaters: " + ", ".join("%s (%d)" % (c["prefix"], len(c["nodes"])) for c in one[:12])})
    for d in list(DEV.values()):
        if d.get("boot_changed") and now - d["boot_changed"] < 3600: out.append({"level": "warn", "title": "Rebooted: " + (d["name"] or d["id"][:8]), "detail": "its boot id changed %d min ago (%d reboot%s seen since the dashboard started)" % ((now - d["boot_changed"]) // 60, d["reboots"], "" if d["reboots"] == 1 else "s")})
    try:
        for k in alert_keys("air:"): out.append({"level": "warn", "title": "High airtime: " + ((DEV.get(k[4:]) or {}).get("name") or k[4:12]), "detail": "transmitting over %d%% of the time (sustained %d minutes)" % (CONF["airtime_warn_pct"], CONF["airtime_warn_minutes"])})
    except Exception: pass
    try:
        for k in alert_keys("snrw:"): out.append({"level": "warn", "title": "Signal worse: " + _name_of(k[5:]), "detail": "heard at least %d dB weaker over the last 24 hours than over the 7 days before (see Watchtower below)" % CONF["snr_worse_db"]})
    except Exception: pass
    return out

# ----------------------------------------------------------------------------- 2.36: map publishing, hop advice, SNR trend, clock drift, TX advice
# Everything here is advisory or manual. Nothing changes a repeater, and nothing is sent to the internet map except by an administrator pressing the button.
def _median(v):
    v = sorted(v); n = len(v)
    return None if not n else (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0)

def _name_of(key):
    return (DEV.get(key) or {}).get("name") or (NODES.get(key) or {}).get("name") or key[:8]

def grouped_alert(title, items, level, kind):
    """One alert per item up to three, else a single alert listing them, so a mass event is one message."""
    if not items: return
    if len(items) <= 3:
        for label, text in items: send_alert("%s: %s" % (title, label), text, level, kind)
    else: send_alert("%s: %d nodes" % (title, len(items)), "; ".join("%s (%s)" % x for x in items[:8]) + ("; and %d more" % (len(items) - 8) if len(items) > 8 else ""), level, kind)

# --- adverts: check the signature, keep the newest one for each own repeater, and take clock samples
ADV_MIN_GAP = 1200                 # seconds between signature checks for one node
ADV_LAST = {}; ADV_BUDGET = collections.deque(maxlen=120)
MAX_ADVERT_DATA = 32               # firmware MAX_ADVERT_DATA_SIZE

def advert_parts(payload):
    """(public key, timestamp, signature, app data) of an advert payload, or None when it cannot be one."""
    if not payload or not 100 <= len(payload) <= 184 or len(payload) - 100 > MAX_ADVERT_DATA: return None
    return bytes(payload[:32]), struct.unpack("<I", payload[32:36])[0], bytes(payload[36:100]), bytes(payload[100:])

def small_order_key(pub):
    """True for a public key that is not a point of the prime-order group (one of the few small-order points, or no point at all). With such a key a signature of all
    zeros checks out for a quarter of all messages, so a forger could make 'nodes' out of thin air: these keys are never accepted."""
    try:
        A = ENR._dec(bytes(pub))
        if A is None: return True
        q = ENR._mul(8, A)
        return q[0] % ENR.P == 0 and (q[1] - q[2]) % ENR.P == 0
    except Exception: return True

def advert_verified(payload):
    """The advert's parts when its Ed25519 signature (over key + timestamp + app data) is good, else None."""
    parts = advert_parts(payload)
    if not parts: return None
    pub, ts, sig, app = parts
    if small_order_key(pub): return None
    return parts if ENR.ed_verify(pub, pub + payload[32:36] + app, sig) else None

def advert_packet(hdr, payload):
    """The advert the way a companion exports it: flood route, no transport codes, empty path (the path is not signed)."""
    return bytes([(int(hdr) & 0xFC) | 1, 0]) + bytes(payload)

ADV_FAIL_GAP = 60                  # seconds before a key whose advert failed its check is checked again (a forger cannot lock a genuine node out for long)
ADV_BUDGET_NEW = collections.deque(maxlen=30)      # checks a minute for keys not yet known: forged adverts with made-up keys use only this lane
ADV_BUDGET_RX = {}                 # receiving repeater -> deque of check times: one noisy source cannot use everyone's checks
ADV_RX_PER_MIN = 60

def _budget_take(dq, now, window=60):
    while dq and now - dq[0] > window: dq.popleft()
    if len(dq) >= dq.maxlen: return False
    dq.append(now); return True

def advert_note(key, info, now, rx=None, fresh=False):
    """Called for each advert heard. Verified here, throttled per node, per receiving repeater, per lane (known keys or new keys) and overall, so forged adverts
    neither count nor cost much and cannot use up the checks genuine ones need. True = verified, False = failed, None = not checked."""
    p = info.get("advp")
    if not p or info.get("hdr") is None: return None
    last = ADV_LAST.get(key)
    if last is not None:
        if now - last[0] < (ADV_MIN_GAP if last[1] else ADV_FAIL_GAP) and not (fresh and last[1]): return None
    if rx is not None:
        q = ADV_BUDGET_RX.setdefault(rx, collections.deque(maxlen=ADV_RX_PER_MIN))
        if len(ADV_BUDGET_RX) > 500: ADV_BUDGET_RX.clear()
        if not _budget_take(q, now): return None
    if not _budget_take(ADV_BUDGET_NEW if fresh else ADV_BUDGET, now): return None        # over the limit: skip, not an error
    parts = advert_verified(p)
    while len(ADV_LAST) > 6000: ADV_LAST.pop(next(iter(ADV_LAST)), None)      # drop the oldest, so a flood of made-up keys cannot wipe the failure memory
    if parts is None or parts[0].hex().upper() != key:
        COUNT["advert_badsig"] += 1; ADV_LAST[key] = (now, False); return False
    ADV_LAST[key] = (now, True)
    drift_note(key, parts[1], now)
    if key in DEV: advert_store(key, advert_packet(info["hdr"], p), parts[1], now)
    return True

def advert_store(key, packet, ats, now):
    """The newest verified advert of an own repeater (one row each, so bounded). An older advert never replaces a newer one."""
    with LOCK:
        r = DB.execute("SELECT ats FROM adverts WHERE key=?", (key,)).fetchone()
        if r and r[0] is not None and ats < r[0]: return False
        DB.execute("INSERT OR REPLACE INTO adverts VALUES(?,?,?,?)", (key, int(now), int(ats), packet.hex()))
    return True

# --- publish one repeater to the internet map (manual, administrator, switched on in Settings)
MAP_URL = "https://map.meshcore.dev/api/v1/nodes"
MAP_MAX_AGE = 7 * 86400
MAP_LAST = {}                      # device -> the last attempt: {"ts", "ok", "status", "text"}
MAP_SEND = None                    # tests replace this: a function taking the request and returning (status, body bytes)

def map_uri(packet):
    """meshcore://<hex of the advert packet>, as the apps export a contact. Re-checks the signature; raises ValueError when the packet is not a good advert."""
    packet = bytes(packet)
    info = parse_packet(packet)
    if not info or info.get("type") != "ADVERT" or not info.get("advp") or info["hops"] != 0 or packet[0] & 3 != 1: raise ValueError("that is not a clean advert packet")
    parts = advert_verified(info["advp"])
    if not parts: raise ValueError("the advert's signature does not check out")
    return "meshcore://" + packet.hex()

def map_request(uri):
    """The POST the map's own uploader makes: JSON {"links": [uri]} to the nodes endpoint."""
    if not isinstance(uri, str) or not re.match(r"^meshcore://[0-9a-f]{200,500}$", uri): raise ValueError("not a contact link")
    return urllib.request.Request(MAP_URL, data=json.dumps({"links": [uri]}).encode(), method="POST",
                                  headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "umcnet-dash/" + VERSION})

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None          # a redirect is shown as it is, never followed

def _map_open(req, timeout=15):
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()), _NoRedirect)   # certificate and host name are checked
    try:
        with opener.open(req, timeout=timeout) as r: return r.status, r.read(2048)
    except urllib.error.HTTPError as e:
        try: return e.code, e.read(2048)
        finally: e.close()

def map_summary(row):
    """What the stored advert says (and whether it may be published), from the row (key, ts, ats, raw hex)."""
    key, ts, ats, raw = row; out = {"id": key, "stored": int(ts), "advert_time": ats, "name": "", "lat": None, "lon": None, "age": None, "why_not": ""}
    try: info = parse_packet(bytes.fromhex(raw)) or {}
    except ValueError: info = {}
    out["name"] = info.get("name", ""); out["lat"] = info.get("lat"); out["lon"] = info.get("lon")
    return out

def map_status(now=None):
    now = int(now or time.time())
    with LOCK: rows = {r[0]: r for r in DB.execute("SELECT key, ts, ats, raw FROM adverts").fetchall()}
    out = []
    for d in sorted(list(DEV.values()), key=lambda x: (x["name"] or x["id"]).lower()):
        r = rows.get(d["id"]); last = MAP_LAST.get(d["id"])
        if not r: s = {"id": d["id"], "stored": None, "advert_time": None, "name": "", "lat": None, "lon": None, "age": None, "why_not": "no verified advert has been heard from this repeater yet"}
        else:
            s = map_summary(r); s["age"] = now - s["stored"]
            if s["age"] > MAP_MAX_AGE: s["why_not"] = "the stored advert is older than 7 days: send an advert from the repeater first"
            elif s["lat"] is None: s["why_not"] = "the advert carries no position, so there is nothing to put on the map"
        s["repeater"] = d["name"] or d["id"][:8]; s["last"] = dict(last) if last else None; out.append(s)
    return {"enabled": bool(CONF.get("map_publish")), "url": MAP_URL, "repeaters": out}

MAP_SECRET = secrets.token_bytes(32)      # per process: a confirmation does not survive a restart
MAP_TOKEN_TTL = 120
MAP_LOCK = threading.Lock()

def map_digest(row):
    """A fingerprint of the exact stored advert (key, advert time, packet)."""
    return hashlib.sha256(("%s|%s|%s" % (row[0], row[2], row[3])).encode()).hexdigest()

def map_token(who, dev, digest, name, lat, lon, exp):
    """The confirmation: a MAC over who is publishing, which repeater, the exact advert and what the operator was shown (name, position), valid until `exp`."""
    msg = "\n".join(str(x) for x in (who, dev, digest, name, repr(lat), repr(lon), int(exp))).encode()
    return "%d.%s" % (exp, hmac.new(MAP_SECRET, msg, hashlib.sha256).hexdigest())

def map_token_ok(token, who, dev, digest, name, lat, lon, now):
    if not isinstance(token, str) or len(token) > 120 or "." not in token: return False
    e = token.split(".", 1)[0]
    if not e.isdigit() or int(e) < now or int(e) > now + MAP_TOKEN_TTL + 5: return False
    return hmac.compare_digest(token, map_token(who, dev, digest, name, lat, lon, int(e)))

def map_publish(who, dev, confirm=None, now=None):
    """Publish one repeater's verified advert to the map. Administrator only, switched on in Settings, one repeater per call. Two steps: the first call
    (no `confirm`) returns what would be published and a short-lived token for exactly that advert; the second must present the token, and is refused if the
    advert held for the repeater is no longer the one that was shown."""
    now = int(now or time.time()); dev = str(dev or "").upper()
    def fail(msg, **extra):
        audit(who, "map publish", dev[:12], msg, False); return dict({"ok": False, "error": msg}, **extra)
    if role_of(who) != "admin": return fail("only the administrator can publish to the map")
    if not CONF.get("map_publish"): return fail("publishing to the map is switched off in the settings")
    if not re.match(r"^[0-9A-F]{64}$", dev) or dev not in DEV: return fail("no such repeater")
    with LOCK: row = DB.execute("SELECT key, ts, ats, raw FROM adverts WHERE key=?", (dev,)).fetchone()
    if not row: return fail("no verified advert has been heard from this repeater yet")
    s = map_summary(row)
    if now - s["stored"] > MAP_MAX_AGE: return fail("the stored advert is older than 7 days: send an advert from the repeater first")
    if s["lat"] is None: return fail("the advert carries no position, so there is nothing to put on the map")
    dg = map_digest(row)
    if not confirm or confirm is True or not map_token_ok(confirm, who, dev, dg, s["name"], s["lat"], s["lon"], now):
        exp = now + MAP_TOKEN_TTL
        r = {"ok": False, "needs_confirm": True, "error": "confirm that %s's name and position become public" % (s["name"] or dev[:8]), "name": s["name"], "lat": s["lat"], "lon": s["lon"],
             "token": map_token(who, dev, dg, s["name"], s["lat"], s["lon"], exp), "expires": exp}
        if confirm and confirm is not True: r["error"] = "the confirmation has expired or the repeater's advert has changed since it was shown: check the name and position again"; r["changed"] = True
        return r
    with MAP_LOCK:                                         # claim the slot BEFORE the request goes out: two calls at once cannot both publish
        if now - (MAP_LAST.get(dev) or {}).get("ts", 0) < 60: return fail("published a moment ago: wait a minute")
        MAP_LAST[dev] = {"ts": now, "ok": False, "status": None, "text": "sending"}
    result = {"ts": now, "ok": False, "status": None, "text": "no answer"}
    try:
        uri = map_uri(bytes.fromhex(row[3])); req = map_request(uri)
        status, body = (MAP_SEND or _map_open)(req)
        text = re.sub(r"[^\x20-\x7e]", " ", bytes(body or b"").decode("utf-8", "replace"))[:300].strip()
        ok = 200 <= int(status) < 300
        result = {"ts": now, "ok": ok, "status": int(status), "text": text}
    except (ValueError, OSError, http.client.HTTPException) as e:        # URLError, timeouts and TLS failures are OSError; a broken HTTP reply is HTTPException
        result = {"ts": now, "ok": False, "status": None, "text": str(e)[:200]}
        return fail("could not publish: %s" % e)
    finally:
        with MAP_LOCK: MAP_LAST[dev] = result                                   # whatever happened, the slot shows the outcome
    audit(who, "map publish", dev[:12], "%s: HTTP %s %s" % (s["name"] or dev[:8], status, text[:150]), ok)
    return {"ok": ok, "status": int(status), "response": text, "error": None if ok else "the map answered HTTP %s" % status}

# --- hop histogram advice for flood.max (flood packets only; a direct-routed packet's path is what is left to travel)
HOP_MIN_SAMPLES = 200; HOP_MIN_DAYS = 3; HOP_WINDOW_DAYS = 14

def hop_note(rx, hops, now):
    try: h = int(hops)
    except (TypeError, ValueError): return False
    if not 0 <= h <= 63: return False
    key = (int(now) // 3600 * 3600, rx, h)
    with TRAFFIC_LOCK:
        if key not in HOP_BUF and len(HOP_BUF) >= BUF_CAP: return False
        HOP_BUF[key] += 1
    return True

def hop_advice(counts, first_h, last_h, current=None):
    """counts: {hops: packets}. Advises the smallest flood.max covering the 95th percentile of hop counts plus one, within 2..64, from at least 200 packets over 3 days."""
    n = sum(counts.values()); days = (last_h - first_h + 3600) / 86400.0 if n else 0.0
    out = {"samples": n, "days": round(days, 1), "current": current, "p95": None, "recommended": None, "status": "not enough data", "histogram": sorted(counts.items())}
    if n < HOP_MIN_SAMPLES or days < HOP_MIN_DAYS:
        out["why"] = "needs at least %d flood packets over %d days (has %d over %.1f days)" % (HOP_MIN_SAMPLES, HOP_MIN_DAYS, n, days); return out
    need = 0.95 * n; cum = 0
    for h, c in sorted(counts.items()):
        cum += c
        if cum >= need: out["p95"] = h; break
    out["recommended"] = max(2, min(64, out["p95"] + 1))
    out["status"] = "unknown setting" if current is None else "matches" if current == out["recommended"] else "differs"
    return out

def setting_int(dev, key):
    raw = re.sub(r"^[>\s]+", "", str((SETTINGS.get(dev) or {}).get("values", {}).get(key, ""))).strip()
    return finite_int(raw, -1000, 100000) if raw else None          # a repeater's reply is data: 'nan', '1e999' or a huge number is no setting

def hop_advice_view(now=None):
    now = int(now or time.time()); since = now // 3600 * 3600 - HOP_WINDOW_DAYS * 86400
    traffic_flush()
    with LOCK: rows = DB.execute("SELECT rx, hops, SUM(n), MIN(h), MAX(h) FROM hophist WHERE h>=? GROUP BY rx, hops", (since,)).fetchall()
    acc = {}
    for rx, hp, n, lo, hi in rows:
        e = acc.setdefault(rx, [{}, lo, hi]); e[0][hp] = n; e[1] = min(e[1], lo); e[2] = max(e[2], hi)
    out = []
    for d in sorted(list(DEV.values()), key=lambda x: (x["name"] or x["id"]).lower()):
        c, lo, hi = acc.get(d["id"], [{}, 0, 0]); a = hop_advice(c, lo, hi, setting_int(d["id"], "flood.max")); a["id"] = d["id"]; a["name"] = d["name"] or d["id"][:8]; out.append(a)
    return out

# --- SNR worsening (packets heard with no repeater between, flood, hour by hour, from the snr table)
SNR_COOLDOWN = 12 * 3600

def snr_trend(recent, base, min_samples):
    """recent, base: [(packets, sum of SNR)] per hour. Median of the hourly means, last 24 hours against the 7 days before.
    delta > 0 means worse. None when either window lacks readings: no readings is unknown, never 0 dB or 'unchanged'."""
    r = [(n, s) for n, s in recent if n > 0]; b = [(n, s) for n, s in base if n > 0]
    nr = sum(n for n, s in r); nb = sum(n for n, s in b)
    if nr < min_samples or nb < min_samples or len(r) < 3 or len(b) < 12: return None
    mr = _median([s / n for n, s in r]); mb = _median([s / n for n, s in b])
    return {"recent": round(mr, 2), "base": round(mb, 2), "delta": round(mb - mr, 2), "n_recent": nr, "n_base": nb}

def snr_alert_step(active, delta, thr, since_recover=None, cooldown=SNR_COOLDOWN):
    """'fire' at delta >= thr (not within `cooldown` of the last recovery); 'recover' once it is back under half of thr. No delta changes nothing."""
    if delta is None: return None
    if not active and delta >= thr: return None if since_recover is not None and since_recover < cooldown else "fire"
    if active and delta <= thr / 2.0: return "recover"
    return None

def snr_view(now=None):
    now = int(now or time.time()); cur = now // 3600 * 3600; rstart = cur - 23 * 3600; bstart = rstart - 7 * 86400
    traffic_flush()
    with LOCK: rows = DB.execute("SELECT node, h, n, s FROM snr WHERE h>=? AND h<=?", (bstart, cur)).fetchall()
    acc = {}
    for node, h, n, s in rows: acc.setdefault(node, ([], []))[0 if h >= rstart else 1].append((n, s))
    out = []
    for node, (rec, base) in acc.items():
        nd = NODES.get(node)
        if not (node in DEV or (nd and nd.get("type") in (2, 3))): continue       # repeaters and rooms: a phone that was carried away is not a worse link
        t = snr_trend(rec, base, CONF["snr_min_samples"])
        if t: t.update(key=node, name=_name_of(node), own=node in DEV, alert=alert_get("snrw:" + node)[0] == "active"); out.append(t)
    out.sort(key=lambda r: -r["delta"])
    return out

def snr_alerts(now=None):
    now = int(now or time.time())
    if not CONF["alerts"].get("snr_worse"): return {"cleared": alert_clear_stale("snrw:", set(), now)}
    thr = CONF["snr_worse_db"]; fires = []; backs = []; view = snr_view(now)
    alert_clear_stale("snrw:", {"snrw:" + r["key"] for r in view}, now)             # a node with no readings in the window has no 'worse' to report
    for r in view:
        key = "snrw:" + r["key"]; state, ts = alert_get(key); step = snr_alert_step(state == "active", r["delta"], thr, now - ts if state == "clear" else None)
        if step == "fire": alert_put(key, "active", now); fires.append((r["name"], "%.1f dB worse: median %.1f dB over the last 24 h against %.1f dB over the 7 days before" % (r["delta"], r["recent"], r["base"])))
        elif step == "recover": alert_put(key, "clear", now); backs.append((r["name"], "signal back to %.1f dB (7 day median %.1f dB)" % (r["recent"], r["base"])))
    grouped_alert("Signal worse", fires, "warn", "snr"); grouped_alert("Signal back", backs, "ok", "snr")
    return {"fired": len(fires), "recovered": len(backs)}

# --- clocks: each node's own clock (the time in its signed adverts) against ours
DRIFT_WINDOW = 48 * 3600; DRIFT_COOLDOWN = 12 * 3600

def drift_note(key, ats, now):
    """Keep up to five (our time, node clock minus ours, node time) samples. The same advert heard twice, or a second sample within 20 minutes, adds nothing."""
    with LOCK:
        r = DB.execute("SELECT samples FROM clockdrift WHERE key=?", (key,)).fetchone()
        try: s = json.loads(r[0]) if r else []
        except ValueError: s = []
        if not isinstance(s, list): s = []
        if s and isinstance(s[-1], list) and len(s[-1]) == 3 and (s[-1][2] == ats or now - s[-1][0] < ADV_MIN_GAP): return False
        s = [x for x in s if isinstance(x, list) and len(x) == 3 and now - x[0] < DRIFT_WINDOW] + [[int(now), int(ats - now), int(ats)]]
        DB.execute("INSERT OR REPLACE INTO clockdrift VALUES(?,?,?)", (key, int(now), json.dumps(s[-5:])))
    return True

DRIFT_NEAR = 300           # a timestamp this close to our clock is believed at once; a farther one only when a second sample agrees with it
DRIFT_AGREE = 120

def drift_median(samples, now):
    """Median drift in seconds (positive = the node is ahead of us) from at least two samples in the last 48 hours, else None.
    A sample more than DRIFT_NEAR from our clock counts only when another far sample agrees within DRIFT_AGREE s: a real mis-set clock
    gives the same offset each time, while a replayed old advert gives an offset that grows by the time since it was recorded."""
    v = [x[1] for x in samples if now - x[0] < DRIFT_WINDOW and isinstance(x[1], (int, float))]
    far = [d for d in v if abs(d) > DRIFT_NEAR]
    v = [d for d in v if abs(d) <= DRIFT_NEAR] + [d for d in far if sum(1 for e in far if abs(e - d) <= DRIFT_AGREE) >= 2]
    return _median(v) if len(v) >= 2 else None

def drift_alert_step(active, drift, thr, since_recover=None, cooldown=DRIFT_COOLDOWN):
    if drift is None: return None
    if not active and abs(drift) > thr: return None if since_recover is not None and since_recover < cooldown else "fire"
    if active and abs(drift) <= thr / 2.0: return "recover"
    return None

def drift_covered(key):
    """An own repeater whose clock the existing 'Clock off' check already watches (from its status timestamps) is not alerted on twice."""
    d = DEV.get(key)
    return bool(d and d.get("skew") is not None)

def drift_view(now=None):
    now = int(now or time.time()); thr = CONF["drift_seconds"]
    with LOCK: rows = DB.execute("SELECT key, ts, samples FROM clockdrift").fetchall()
    out = []
    for key, ts, raw in rows:
        try: s = json.loads(raw)
        except ValueError: continue
        if not isinstance(s, list): continue
        s = [x for x in s if isinstance(x, list) and len(x) == 3]
        nd = NODES.get(key) or {}
        if not (key in DEV or nd.get("type") in (2, 3)): continue              # repeaters and rooms; phones and sensors often have no clock source at all
        m = drift_median(s, now)
        out.append({"key": key, "name": _name_of(key), "kind": NODE_KIND.get(nd.get("type"), "node"), "own": key in DEV, "samples": len([x for x in s if now - x[0] < DRIFT_WINDOW]), "last": ts,
                    "drift": None if m is None else round(m), "beyond": m is not None and abs(m) > thr, "covered": drift_covered(key), "alert": alert_get("drift:" + key)[0] == "active"})
    out.sort(key=lambda r: (not r["beyond"], -abs(r["drift"] or 0), r["name"].lower()))
    return out

def drift_alerts(now=None):
    now = int(now or time.time())
    if not CONF["alerts"].get("clock_drift"): return {"cleared": alert_clear_stale("drift:", set(), now)}
    thr = CONF["drift_seconds"]; fires = []; backs = []; view = drift_view(now)
    alert_clear_stale("drift:", {"drift:" + r["key"] for r in view if not r["covered"] and r["drift"] is not None}, now)
    for r in view:
        if r["covered"]: continue
        key = "drift:" + r["key"]; state, ts = alert_get(key); step = drift_alert_step(state == "active", r["drift"], thr, now - ts if state == "clear" else None)
        if step == "fire": alert_put(key, "active", now); fires.append((r["name"], "its clock is %+d s against this server (limit %d s)" % (r["drift"], thr)))
        elif step == "recover": alert_put(key, "clear", now); backs.append((r["name"], "its clock is within %d s again (%+d s)" % (thr, r["drift"])))
    grouped_alert("Clock off", fires, "warn", "drift"); grouped_alert("Clock back", backs, "ok", "drift")
    return {"fired": len(fires), "recovered": len(backs)}

# --- transmit power advice (advisory only: it never suggests raising power and never changes anything)
SF_FLOOR = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}      # standard LoRa demodulator SNR limits, dB
RADIO_RX = re.compile(r"(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d{1,2})\s*,\s*(\d)")
TX_LABEL = "Advisory, test with tryset only after hardware validation."

def radio_sf(text):
    """The spreading factor in a 'frequency,bandwidth,SF,CR' text, or None."""
    m = RADIO_RX.search(str(text or "")); return int(m.group(3)) if m else None

TX_MIN, TX_MAX = 1, 22     # the range `set tx` takes (MANUAL.md); advice never goes under the lowest or is given for a value outside the range
TX_MIN_HOURS_7D = 6; TX_MIN_HOURS_24H = 3; TX_MIN_PACKETS_24H = 5

def tx_advice(sf, neigh, headroom, tx=None, assumed=False):
    """neigh: [(name, SNR dB or None)], the signal between this repeater and each active neighbour, in the direction our transmit power affects. Suggests lowering
    only when the margin over the SF's demodulation limit exceeds `headroom` for every one of at least two neighbours. Unknown SF, a missing reading or a power
    setting outside the supported range gives no advice. Never suggests raising. `assumed`: some neighbours could not be observed hearing us (stated in the text)."""
    out = {"status": "none", "sf": sf, "floor": SF_FLOOR.get(sf), "headroom": headroom, "min_margin": None, "weakest": None, "drop": 0, "label": TX_LABEL, "assumes_symmetric": bool(assumed)}
    if sf not in SF_FLOOR: out["status"] = "skip"; out["text"] = "Spreading factor unknown or outside SF7 to SF12: no advice."; return out
    if tx is not None and not TX_MIN <= tx <= TX_MAX: out["status"] = "skip"; out["text"] = "Transmit power %s dBm is outside the supported %d to %d dBm: no advice." % (tx, TX_MIN, TX_MAX); return out
    if len(neigh) < 2: out["status"] = "skip"; out["text"] = "Needs at least two active neighbours with a measured signal (has %d): no advice." % len(neigh); return out
    if any(s is None or not math.isfinite(s) for _, s in neigh): out["status"] = "skip"; out["text"] = "A neighbour has no recent signal reading in the direction our transmitter reaches it: no advice."; return out
    name, snr = min(neigh, key=lambda x: x[1]); margin = snr - SF_FLOOR[sf]
    out.update(min_margin=round(margin, 1), weakest=name)
    drop = min(6, int(margin - headroom)) if margin - headroom >= 1 else 0
    if tx is not None: drop = max(0, min(drop, tx - TX_MIN))
    if drop < 1:
        out["text"] = "Weakest neighbour %s is %.1f dB above the SF%d limit (%.1f dB), not more than the %g dB headroom%s: no change suggested." % (name, margin, sf, SF_FLOOR[sf], headroom, "" if tx is None or tx > TX_MIN else ", and power is already at the lowest setting"); return out
    out["status"] = "advice"; out["drop"] = drop
    to = (" (to about %g dBm)" % (tx - drop)) if tx is not None else ""
    out["text"] = "Every active neighbour is at least %.1f dB above the SF%d limit (%.1f dB; weakest: %s), more than the %g dB headroom. Transmit power could be lowered by up to %d dB%s.%s %s" % (
        margin, sf, SF_FLOOR[sf], name, headroom, drop, to, (" Neighbours that are not ours could not be observed hearing this repeater: their signal is assumed to be as good in both directions." if assumed else ""), TX_LABEL)
    return out

def snr_recent(now, rows=None):
    """node -> recent SNR in dB: the lower of the median hourly mean over 7 days (needs snr_min_samples packets over 6 hours) and over 24 hours (5 packets over 3 hours),
    from the snr table (packets heard with no repeater between). Nodes without enough readings are absent: no data is never 0 dB."""
    cur = int(now) // 3600 * 3600; r24 = cur - 23 * 3600; ms = CONF["snr_min_samples"]
    if rows is None:
        with LOCK: rows = DB.execute("SELECT node, h, n, s FROM snr WHERE h>=? AND h<=?", (cur - 167 * 3600, cur)).fetchall()
    acc = {}
    for node, h, n, sm in rows:
        if not n or n <= 0 or sm is None or not math.isfinite(sm): continue
        e = acc.setdefault(node, ([], []))
        e[0].append((n, sm / n))
        if h >= r24: e[1].append((n, sm / n))
    out = {}
    for node, (w7, w1) in acc.items():
        c = []
        if sum(n for n, _ in w7) >= ms and len(w7) >= TX_MIN_HOURS_7D: c.append(_median([v for _, v in w7]))
        if sum(n for n, _ in w1) >= TX_MIN_PACKETS_24H and len(w1) >= TX_MIN_HOURS_24H: c.append(_median([v for _, v in w1]))
        if c: out[node] = min(c)
    return out

def tx_view(now=None, hours=48):
    now = int(now or time.time())
    with LOCK: pairs = {(a, b) for a, b in DB.execute("SELECT a, b FROM links WHERE last>?", (now - hours * 3600,)).fetchall()}
    sn = snr_recent(now); out = []
    for d in sorted(list(DEV.values()), key=lambda x: (x["name"] or x["id"]).lower()):
        r = d["id"]; peers = {}                                 # neighbour -> {"in": this repeater hears it, "out": it was heard hearing this repeater}
        for a, b in pairs:
            if a == r and b != r: peers.setdefault(b, {})["in"] = True
            elif b == r and a in DEV and a != r: peers.setdefault(a, {})["out"] = True
        neigh = []; assumed = False
        for k, f in peers.items():
            nd = NODES.get(k) or {}
            if not (k in DEV or nd.get("type") in (2, 3)): continue                      # repeaters and rooms only: a phone or a sensor is no reason to keep power up
            if k in DEV:                                                                 # ours: the direction our power affects must itself have been observed
                vals = [x for x in (sn.get(r), sn.get(k) if f.get("in") else None) if x is not None]
                sig = min(vals) if sn.get(r) is not None and f.get("out") else None
            else:                                                                        # not ours: we only ever hear it, so its signal is assumed to hold both ways
                sig = sn.get(k) if f.get("in") else None; assumed = True
            neigh.append((_name_of(k), sig))
        radio = (SETTINGS.get(r) or {}).get("values", {}).get("radio") or d.get("radio")
        tx = setting_int(r, "tx"); a = tx_advice(radio_sf(radio), neigh, CONF["tx_headroom_db"], tx, assumed)
        a.update(id=r, name=d["name"] or r[:8], neighbours=len(neigh), tx=tx, radio=str(radio or ""), assumed=assumed); out.append(a)
    return out

def watchtower_view(now=None):
    now = int(now or time.time()); C = CONF
    return {"now": now, "snr": {"rows": snr_view(now)[:40], "thr": C["snr_worse_db"], "min_samples": C["snr_min_samples"], "alerts": bool(C["alerts"].get("snr_worse"))},
            "drift": {"rows": drift_view(now)[:60], "thr": C["drift_seconds"], "alerts": bool(C["alerts"].get("clock_drift"))},
            "hops": hop_advice_view(now), "tx": tx_view(now), "tx_label": TX_LABEL}

# ----------------------------------------------------------------------------- alerts
ALERT_STATE = {}
def build_alert_request(url, title, text, level="warn"):
    """The HTTP request for one alert. A ntfy address (the word 'ntfy' in it) gets ntfy's headers; an address of the form
    https://user:password@host/topic is sent with that login (HTTP basic), so a private ntfy server can be used."""
    u = urlparse(url); headers = {}; title = clean_text(title, 120); text = str(text).replace("\r", " ")[:2000]      # a name from the radio must not carry a line break into a header
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
    a = CONF["alerts"]; title = clean_text(title, 120); text = "".join(c if c == "\n" or ord(c) >= 32 and ord(c) != 127 else " " for c in str(text))[:2000]
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
            try: silent_alerts(now)
            except Exception as e: sys.stderr.write("silent: %s\n" % e)
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
            if now - st.get("slow", 0) > 60:
                st["slow"] = now; airtime_alerts(now)
                if a.get("route_silent"): route_alerts(now)
                if now - st.get("coll", 0) > 300: st["coll"] = now; collision_alerts(now)
            if now - st.get("watch", 0) > 600:
                st["watch"] = now
                for fn in (snr_alerts, drift_alerts):
                    try: fn(now)
                    except Exception as e: sys.stderr.write("%s: %s\n" % (fn.__name__, e))
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
            cl = [c for c in list(CLIENTS.values()) if c.get("user") == a["name"] and c.get("state") == "connected"]
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

def quiet_mesh_nodes(now):
    """Previously heard repeaters and room servers outside the managed repeater set."""
    own = set(DEV)
    return [{"name": n["name"] or k[:8], "last": n["last"]}
            for k, n in list(NODES.items())
            if k not in own and n["type"] in (2, 3) and n["last"] and 86400 < now - n["last"] < 30 * 86400]


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
    for c in list(CLIENTS.values()):
        h = [t for t in c.get("history", []) if now - t < 600]
        if len(h) >= C["flap_count"]: add("warn", "Reconnecting often: " + (c.get("user") or c["client"]), "%d connections in 10 minutes (%s): a weak WiFi link or two devices sharing one account" % (len(h), c.get("ip", "")))
    for pnd in pending_list():
        add("warn", "Waiting for approval: " + pnd["name"], "connected from %s as device %s... : approve it on the Accounts tab" % (pnd["ip"] or "?", pnd["prefix"] or "?") if pnd["online"] else "created, nobody has used it yet")
    by_user = {}
    for c in list(CLIENTS.values()):
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
    for d in list(DEV.values()):
        age = now - d["last"] if d["last"] else None; nm = d["name"] or d["id"][:12]
        if age is None: add("warn", "No data yet from %s" % nm, "known only from its saved status message; nothing live since the dashboard started")
        elif age > silent_minutes(d["id"]) * 60: add("warn", "No data from %s" % nm, "last heard %d min ago (limit %d)" % (age // 60, silent_minutes(d["id"])))
        if d["skew"] is not None and abs(d["skew"]) > C["skew_seconds"]: add("warn", "Clock off on %s" % nm, "%+.0f s against this server (its NTP may be down)" % d["skew"])
        if d["status"] == "offline" and (age is None or age > 300): add("warn", "%s reports itself offline" % nm, "its last status message said offline and nothing has arrived since")
    dr = sysnum("$SYS/broker/load/publish/dropped/1min")
    if dr > 0: add("warn", "Broker is dropping messages", "%.1f a minute (a slow subscriber or full queues)" % dr)
    # mesh issues: nodes gone quiet for a day, repeaters with no position, low batteries, a bridge that holds packets back
    # Our own repeaters are checked one by one (and they are not "stale" while they report). Other nodes heard
    # across the mesh are summarised in one line, so the list stays readable.
    own = {d["id"] for d in list(DEV.values()) if d["last"] and now - d["last"] < CONF["stale_minutes"] * 60}
    quiet = quiet_mesh_nodes(now)
    if quiet:
        names = sorted((n["name"] for n in quiet), key=str.lower)
        add("warn", "%d mesh node%s quiet for over a day" % (len(quiet), "" if len(quiet) == 1 else "s"), ", ".join(names[:15]) + (" …" if len(names) > 15 else ""))
        out[-1]["kind"] = "quiet_nodes"
    for d in list(DEV.values()):
        sv = (SETTINGS.get(d["id"]) or {}).get("values", {})          # the position the repeater reports for itself (read over the control link)
        def _set(v): return str(v).strip(" >") not in ("", "0", "0.0", "(not set)")
        has_pos = (d.get("lat") is not None and d.get("lon") is not None) or (_set(sv.get("lat", "")) and _set(sv.get("lon", "")))
        if d["id"] in own and not has_pos and not (CONF.get("locations") or {}).get(d["id"]):
            add("warn", "No position: %s" % (d["name"] or d["id"][:8]), "this repeater has no position, so it cannot be placed on the map")
    for d in list(DEV.values()):
        nm = d["name"] or d["id"][:12]; mv = (d.get("stats") or {}).get("battery_mv")
        if mv and mv < CONF["battery_low_mv"] and now - d["last"] < 900: add("warn", "Low battery: %s" % nm, "%.2f V" % (mv / 1000))
        b = d.get("bridge") or {}
        if b.get("heard") and b.get("dropped") and b["dropped"] / max(1, b["heard"]) > 0.10:
            add("warn", "Bridge holding back packets: %s" % nm, "%d of %d heard were held back by the rate limit" % (b["dropped"], b["heard"]))
    out.extend(extra_diagnostics(now))
    return out

def prometheus_text():
    """Node and traffic numbers in the Prometheus text format (behind the dashboard's login)."""
    now = time.time(); out = []
    def g(name, help_, samples):
        out.append("# HELP umcnet_%s %s" % (name, help_)); out.append("# TYPE umcnet_%s gauge" % name)
        for labels, v in samples: out.append("umcnet_%s%s %s" % (name, ("{%s}" % labels) if labels else "", v))
    reps = [d for d in list(DEV.values()) if d["last"] and now - d["last"] < CONF["stale_minutes"] * 60]
    g("repeaters_online", "Repeaters reporting now", [("", len(reps))])
    g("packets_per_minute", "Packets heard per minute by each repeater", [('repeater="%s"' % (d["name"] or d["id"][:8]), round(rate_per_min("pkt:" + d["id"], 300), 2)) for d in reps])
    g("bridge_passed_total", "Packets each bridge has passed on to its radio", [('repeater="%s"' % (d["name"] or d["id"][:8]), (d.get("bridge") or {}).get("passed", 0)) for d in reps])
    g("bridge_held_total", "Packets each bridge held back by its rate limit", [('repeater="%s"' % (d["name"] or d["id"][:8]), (d.get("bridge") or {}).get("dropped", 0)) for d in reps])
    g("clock_skew_seconds", "Each repeater's clock against this server", [('repeater="%s"' % (d["name"] or d["id"][:8]), round(d["skew"] or 0, 3)) for d in reps if d.get("skew") is not None])
    g("nodes_known", "Nodes heard in the last 30 days", [("", sum(1 for n in list(NODES.values()) if n["last"] and now - n["last"] < 30 * 86400))])
    g("confirmed_links", "Neighbour links confirmed in the last 48 hours", [("", len(confirmed_links()))])
    ck = CLOCK.get("v") or {}
    g("server_clock_offset_seconds", "This server's clock against its time source", [("", ck.get("offset", 0))])
    g("broker_up", "1 when the dashboard's link to the broker is up", [("", 1 if MQTT.get("state") == "connected" else 0)])
    return "\n".join(out) + "\n"

def overview():
    sysinfo = system(); cert = certificate(); accs = accounts(); now = time.time()
    with LOCK:
        devs = []
        for d in list(DEV.values()):
            x = dict(d); x["types"] = dict(d["types"]); x["topics"] = dict(d["topics"]); x["pm"] = round(rate_per_min("pkt:" + d["id"], 300), 2); x["has_key"] = d["id"] in KEYS; x["label"] = CONF["labels"].get(d["id"], {}); x["last_cmd"] = CTL["last"].get(d["id"]); x["age"] = round(now - d["last"], 1) if d["last"] else 10 ** 9
            x["silent_minutes"] = silent_minutes(d["id"])
            cached = SETTINGS.get(d["id"], {}); x["settings"] = dict(cached.get("values", {})); x["settings_updated"] = cached.get("updated", 0); x["settings_loading"] = bool(cached.get("loading")); x["settings_error"] = cached.get("error", ""); devs.append(x)
        devs.sort(key=lambda d: -d["last"])
        clients = []
        for c in list(CLIENTS.values()):
            x = {k: v for k, v in c.items() if k != "history"}; x["age"] = round(now - c.get("since", now)); x["recent"] = len([t for t in c.get("history", []) if now - t < 3600]); clients.append(x)
        clients.sort(key=lambda c: (c.get("state") != "connected", -c.get("last", c.get("since", 0))))
        clients = [c for i, c in enumerate(clients) if c.get("state") == "connected" or i < 60]       # all that are connected, then the most recent that left
        for cid in [k for k, c in list(CLIENTS.items()) if c.get("state") != "connected" and now - c.get("last", now) > 86400]: del CLIENTS[cid]
        overlap = []
        ids = [d["id"] for d in devs[:12]]
        for a in ids:
            overlap.append([PAIRS.get(tuple(sorted((a, b))), 0) if a != b else None for b in ids])
        multi = collections.Counter(len(e["devs"]) for e in HEARD.values())
        types = collections.Counter()
        for d in list(DEV.values()): types.update(d["types"])
        sysd = {k: v[0] for k, v in SYS.items()}
        try: msg_last = (DB.execute("SELECT MAX(id) FROM messages").fetchone() or [0])[0] or 0
        except Exception: msg_last = 0
        res = {"sensors": telem_latest(), "routes": packet_routes(), "scope": scope_audit(24), "scope_names": scope_names(), "msg_last": msg_last, "version": VERSION, "now": now, "started": START, "mqtt": dict(MQTT), "sys": sysd, "system": sysinfo, "cert": cert, "devices": devs, "clients": clients, "accounts": accs,
               "packets": [dict(p) for p in list(PKTS)[-60:]][::-1], "events": [dict(e) for e in list(EVENTS)[-80:]][::-1], "log": [dict(l) for l in list(LOG)[-60:]][::-1], "count": dict(COUNT),
               "rates": {"messages": rate_per_min("messages"), "packets": rate_per_min("packets"), "unique": rate_per_min("unique")},
               "overlap": {"ids": ids, "names": [DEV[i]["name"] or i[:8] for i in ids], "m": overlap}, "heard_by": dict(sorted(multi.items())), "types": dict(types),
               "latency": {"n": len(LATENCY), "avg": round(sum(LATENCY) / len(LATENCY), 2) if LATENCY else None, "max": round(max(LATENCY), 2) if LATENCY else None},
               "ev_hour": dict(collections.Counter(e["kind"] for e in EVENTS if now - e["t"] < 3600)), "host": CFG["host"], "config": conf_redacted(False), "control": {"state": CTL_STATUS.get("state", "idle"), "error": CTL_STATUS.get("error", ""), "keys": sorted(KEYS)}}
    res["pending"] = pending_list()
    res["enrol"] = enrol_view()
    res["diagnostics"] = diagnostics(sysinfo, accs, cert)
    res["backup"] = backup_view(); res["collisions"] = collisions_view(); res["new_nodes"] = newnodes_recent()
    return res

PUBLIC_HIDE_STATS = ("boot_id", "boot_changed", "reboots")

def overview_for(admin, who=None):
    """The overview as one signed-in viewer may see it: only the administrator gets channel keys, the web users, the alert address and the backup folder and its errors."""
    o = overview(); o["me"] = me_view(who) if who is not None else None
    if admin:
        o["config"] = conf_redacted(True); o["web_users"] = CONF["web_users"]; return o
    b = dict(o.get("backup") or {}); b.pop("dir", None); b["error"] = "see the administrator" if b.get("error") else ""; o["backup"] = b
    for d in o.get("diagnostics", []):
        if d.get("title", "").startswith("Database backup"): d["detail"] = "see the administrator" if d["level"] != "ok" else d["detail"]
    return o

def public_overview():
    """Operational data safe to publish: no accounts, addresses, logs, keys or write state."""
    o = overview(); now = o["now"]; devices = []
    for d in o["devices"]:
        devices.append({k: d.get(k) for k in ("id", "area", "name", "first", "last", "last_status", "status", "model", "fw", "radio", "client", "repeat", "stats", "n_raw", "n_pkt", "n_rx", "n_tx", "types", "rssi", "snr", "bytes", "skew", "topics", "pm", "label", "age", "last_pkt", "last_tx")})
        br = d.get("bridge") or {}
        devices[-1]["pm"] = d.get("pm"); devices[-1]["age"] = d.get("age")
        devices[-1]["bridge"] = {k: br.get(k) for k in ("heard_pm", "passed_pm", "dropped_pm")} if br else None      # rates only: how much each bridge passes on
        devices[-1]["label"] = {"label": d.get("label", {}).get("label", "")}
        devices[-1]["settings"] = {k: d.get("settings", {}).get(k) for k in PUBLIC_SETTING_KEYS if k in d.get("settings", {})}
        devices[-1]["settings_updated"] = d.get("settings_updated", 0)
        st = devices[-1].get("stats")
        if isinstance(st, dict): devices[-1]["stats"] = {k: v for k, v in st.items() if k not in PUBLIC_HIDE_STATS}      # a boot id is a device fingerprint: not for the public page
    # Public activity contains packet metadata only: never publish message endpoints,
    # channel names, packet keys or payloads. Device identities are already broadcast.
    packets = [{k: p.get(k) for k in ("t", "area", "dev", "dname", "dir", "type", "flood", "hops", "len", "rssi", "snr")} for p in o["packets"]]
    return {"version": VERSION, "now": now, "title": CONF["title"], "mqtt": {"state": o["mqtt"].get("state", "unknown")}, "devices": devices,
            "packets": packets, "totals": {"packets": sum(d.get("n_pkt", 0) for d in devices)}, "nodes": len(NODES),
            "rates": o["rates"], "types": o["types"], "heard_by": o["heard_by"], "latency": o["latency"]}

def public_network_view():
    n = network_view()
    # Explicit public schema, not a blacklist. device_info() contains control and
    # configuration state that must not become public through a future new field.
    fields = ("key", "name", "type", "last", "first", "adverts", "connected", "online")
    nodes = [{k: node.get(k) for k in fields} for node in n["nodes"]]
    known = {node["key"] for node in nodes if node.get("key")}
    public_names = {node.get("name") for node in nodes if node.get("name")}
    links = [{k: link.get(k) for k in ("recv", "node", "hops", "n", "snr", "rssi", "last")}
             for link in n["links"] if link.get("recv") in known and link.get("node") in known]
    journeys = []
    for j in n["journeys"]:
        # A route is an observation, not proof of a bidirectional RF link.
        # Only name nodes already publicly discovered; mask unknown endpoint IDs.
        path = [{"n": hop.get("n") if hop.get("n") in public_names else "unidentified hop"}
                for hop in j.get("path", []) if isinstance(hop, dict)]
        journeys.append({"t": j.get("t"), "type": j.get("type"), "hops": j.get("hops"),
                         "from": j.get("from") if j.get("from") in known else "",
                         "to": j.get("to") if j.get("to") in known else "", "path": path,
                         "snr": j.get("snr")})
    return {"now": n["now"], "nodes": nodes, "links": links, "journeys": journeys}

# ----------------------------------------------------------------------------- HTTP
def csv_text(header, rows):
    b = io.StringIO(); w = csv.writer(b); w.writerow(header)
    for r in rows: w.writerow(r)
    return b.getvalue()

def content_length(raw):
    """The request body length from the header: (n, None) or (0, error). Rejects negative or malformed values."""
    try: n = int(raw or 0)
    except (TypeError, ValueError): return 0, "bad content length"
    if n < 0: return 0, "bad content length"
    return n, None

def parse_body(raw):
    """The JSON object a POST carries: (dict, None) or ({}, error). Anything but an object is refused."""
    try: body = json.loads(raw.decode() or "{}")
    except (UnicodeDecodeError, ValueError): return {}, "body is not valid JSON"
    if not isinstance(body, dict): return {}, "body must be a JSON object"
    return body, None

class BadQuery(ValueError):
    """A query-string value that is not a usable number: the caller gets HTTP 400, never a 500 or a NaN in the reply."""

def qnum(q, name, default, lo, hi, integer=False):
    """A number from the query string, finite and clamped to [lo, hi]. Text, 'nan', 'inf' and '1e999' raise BadQuery."""
    v = finite_num((q.get(name) or [default])[0])
    if v is None: raise BadQuery("bad %s" % name)
    v = max(lo, min(hi, v))
    return int(v) if integer else v

VIEW_CACHE = {}; VIEW_LOCK = threading.Lock(); VIEW_TTL = 15
def cached_view(key, fn, ttl=None):
    """A heavy view for the page's polling: recomputed at most every VIEW_TTL seconds however many pages ask, so polling cannot keep flushing the traffic buffers and holding the database lock."""
    ttl = VIEW_TTL if ttl is None else ttl; now = time.time()
    with VIEW_LOCK:
        hit = VIEW_CACHE.get(key)
        if hit and now - hit[0] < ttl: return hit[1]
    v = fn()
    with VIEW_LOCK:
        if len(VIEW_CACHE) > 64: VIEW_CACHE.clear()
        VIEW_CACHE[key] = (now, v)
    return v

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
            n, err = content_length(self.headers.get("Content-Length"))
            if err: return self.send(400, json.dumps({"error": err}))
            if n > 20000: return self.send(413, '{"error":"too big"}')
            body, err = parse_body(self.rfile.read(n))
            if err: return self.send(400, json.dumps({"error": err}))
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
                return self.send(200, json.dumps({"ok": not err, "error": err, "config": conf_redacted(role == "admin")}))
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
                if op in ("add", "passwd") and r.get("ok") and r.get("password"):
                    acc = next((a for a in accounts() if a["name"] == name), None)
                    if (op == "add" and body.get("role") == "client") or (op == "passwd" and acc and acc["role"] == "client"):
                        cid = client_id_of(r.get("output"), acc["device"] if acc else "")
                        out["client_id"] = cid
                        try: out["setup"] = make_setup_code(CFG["host"], name, r["password"], cid, CONF["join_iata"])
                        except ValueError as e: out["setup_error"] = str(e)
                return self.send(200, json.dumps(out))
            if p == "/api/groups/add":
                nm = str(body.get("name", "")).strip()
                if not re.match(r"^#[a-z0-9][a-z0-9-]{0,30}$", nm): return self.send(200, json.dumps({"ok": False, "error": "a group name starts with # and has letters, digits and dashes"}))
                if any(c.get("name") == nm for c in CONF["messages"]["channels"]): return self.send(200, json.dumps({"ok": True, "note": "already added"}))
                with CONF_LOCK: CONF["messages"]["channels"].append({"name": nm, "source": "scan"}); conf_save()
                audit(who, "group added", nm, "public hashtag group found by the scan")
                with LOCK: MSGSTAT.pop("%02X" % MSG.Channel(nm).hash, None)
                return self.send(200, json.dumps({"ok": True}))
            if p == "/api/catalogue/sync":
                r = cat_sync(manual=True); audit(who, "catalogue sync", "meshcore-channels", r.get("error") or "%d entries" % r.get("entries", 0), bool(r.get("ok")))
                return self.send(200, json.dumps(dict(r, status=cat_status())))
            if p in ("/api/audit/clear", "/api/events/clear"):
                return self.send(200, json.dumps(purge_log(who, "audit" if "audit" in p else "events", body.get("older_than_days"))))
            if p == "/api/messages/clear":
                return self.send(200, json.dumps(clear_messages(who, str(body.get("channel", "")), str(body.get("region", "")), str(body.get("dir", "")), str(body.get("q", "")))))
            if p == "/api/messages/send":
                own = me_view(who)["sender"] or re.sub(r"[^A-Za-z0-9._-]", "", who.upper())[:24] or "USER"
                sender = (body.get("sender") or None) if role == "admin" else own        # users send under their own name only
                return self.send(200, json.dumps(send_message(who, str(body.get("channel", "")), str(body.get("region", "")), str(body.get("text", "")), sender, body.get("via") if isinstance(body.get("via"), list) else None)))
            if p == "/api/enrol/approve":
                r = enrol_approve(who, body.get("id", ""), body.get("name"), body.get("bridge"), str(body.get("role", "repeater"))); return self.send(200, json.dumps(r))
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
            if p == "/api/mappublish":
                return self.send(200, json.dumps(map_publish(who, body.get("device"), body.get("confirm") if isinstance(body.get("confirm"), str) else None)))
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
            if u.path == "/api/network": return self.send(200, json.dumps(network_view(qnum(q, "hours", CONF["map_hours"], 1, 8760))))
            if u.path == "/api/node/stats":
                q = parse_qs(u.query); return self.send(200, json.dumps(node_stats(str(q.get("key", [""])[0]).upper(), q.get("days", ["7"])[0])))
            if u.path == "/api/node":
                key = str(q.get("id", [""])[0]).upper()
                if not key: return self.send(200, json.dumps({"nodes": node_choices()}))
                if not re.match(r"^[0-9A-F]{64}$", key): return self.send(400, '{"error":"id is the node\'s 64 character key"}')
                return self.send(200, json.dumps(node_analytics(key, q.get("days", ["7"])[0])))
            if u.path == "/api/watchtower": return self.send(200, json.dumps(cached_view("watchtower", watchtower_view)))
            if u.path == "/api/routes": return self.send(200, json.dumps(cached_view("routes", route_view)))
            if u.path == "/api/battery": return self.send(200, json.dumps(battery_view(qnum(q, "hours", 24, 1, 168, True))))
            if u.path == "/api/links/checks": return self.send(200, json.dumps(link_checks(qnum(q, "hours", 48, 1, 8760, True))))
            if u.path == "/api/report/weekly": return self.send(200, weekly_report(), "text/plain")
            if u.path == "/api/export/geojson": return self.send(200, json.dumps(geojson_export(), default=str), "application/geo+json")
            if u.path == "/api/messages":
                q = parse_qs(u.query); g = lambda k, d="": q.get(k, [d])[0]
                try: return self.send(200, json.dumps(messages_view(g("channel"), g("region"), g("dir"), qnum(q, "before", 0, 0, 2 ** 62, True), qnum(q, "limit", 100, 1, 500, True), g("q"), g("source"))))
                except ValueError: return self.send(400, '{"error":"bad request"}')
            if u.path == "/api/audit":
                secs = qnum(q, "range", 604800, 60, 90 * 86400, True)
                rows = DB.execute("SELECT ts,who,action,target,detail,ok FROM audit WHERE ts>=? ORDER BY ts DESC LIMIT 500", (int(time.time()) - secs,)).fetchall()
                return self.send(200, json.dumps([dict(zip(("ts", "who", "action", "target", "detail", "ok"), r)) for r in rows]))
            who = (self.headers.get("X-UMC-User") or "admin").strip() or "admin"; role = role_of(who)
            if u.path == "/api/mappublish":
                if role != "admin": return self.send(403, '{"error":"only the administrator can see this"}')
                return self.send(200, json.dumps(map_status()))
            if u.path.startswith("/api/export/") and role != "admin": return self.send(403, '{"error":"only the administrator can export"}')
            if u.path == "/api/export/events.csv":
                rows = DB.execute("SELECT datetime(ts,'unixepoch'),kind,client,user,ip,text FROM events ORDER BY ts DESC LIMIT 20000").fetchall()
                return self.send(200, csv_text(("time (UTC)", "kind", "client", "user", "ip", "text"), rows), "text/csv")
            if u.path == "/api/export/audit.csv":
                rows = DB.execute("SELECT datetime(ts,'unixepoch'),who,action,target,detail,ok FROM audit ORDER BY ts DESC LIMIT 20000").fetchall()
                return self.send(200, csv_text(("time (UTC)", "who", "action", "target", "detail", "ok"), rows), "text/csv")
            if u.path == "/api/export/devices.csv":
                with LOCK: rows = [(d["id"], d["name"], d["area"], d["model"], d["fw"], d["radio"], d["status"], d["n_rx"], d["n_tx"], round(d["last"]), CONF["labels"].get(d["id"], {}).get("label", "")) for d in list(DEV.values())]
                return self.send(200, csv_text(("device id", "name", "area", "model", "firmware", "radio", "status", "received", "sent", "last data (epoch)", "label"), rows), "text/csv")
            if u.path == "/api/export/config.json": return self.send(200, json.dumps(conf_redacted(role == "admin"), indent=1))
            if u.path in ("/", "/index.html"): return self.send(200, open(CFG["static"], "rb").read(), "text/html")
            if u.path == "/api/catalogue": return self.send(200, json.dumps(cat_status()))
            if u.path == "/api/groups":
                return self.send(200, json.dumps({"scan": scan_public_groups(), "rooms": rooms_heard(), "names": len(SCAN_NAMES), "packets": len(RECENT_GRP)}))
            if u.path == "/api/scope":
                return self.send(200, json.dumps({"audit": scope_audit(24), "names": scope_names()}))
            if u.path == "/metrics":
                return self.send(200, prometheus_text(), ctype="text/plain; version=0.0.4")
            if u.path == "/api/quiet-nodes":
                nodes = sorted(quiet_mesh_nodes(time.time()), key=lambda n: (n["last"], n["name"].lower()), reverse=True)
                return self.send(200, json.dumps({"nodes": nodes}))
            if u.path == "/api/overview":
                return self.send(200, json.dumps(overview_for(role == "admin", who), default=str))
            if u.path == "/api/airtime":
                h = qnum(q, "hours", 24, 1, 168); return self.send(200, json.dumps(cached_view(("airtime", round(h, 2)), lambda: airtime_view(h))))
            if u.path == "/api/presence":
                try: return self.send(200, json.dumps(presence_view(qnum(q, "hours", 24, 1, 168))))
                except ValueError: return self.send(400, '{"error":"bad request"}')
            if u.path == "/api/telemetry":
                try: return self.send(200, json.dumps(telem_series(str(q.get("id", [""])[0]).upper(), qnum(q, "ch", 0, 0, 255, True), qnum(q, "type", 0, 0, 255, True), qnum(q, "hours", 24, 1, 168))))
                except ValueError: return self.send(400, '{"error":"bad request"}')
            if u.path == "/api/history":
                keys = [k for k in (q.get("k", [""])[0]).split(",") if k][:60]; secs = qnum(q, "range", 3600, 60, 14 * 86400, True)
                return self.send(200, json.dumps(history(keys, secs)))
            if u.path == "/api/events":
                secs = qnum(q, "range", 86400, 60, 14 * 86400, True); kind = q.get("kind", [""])[0]
                rows = DB.execute("SELECT ts,kind,client,user,ip,text FROM events WHERE ts>=? " + ("AND kind=? " if kind else "") + "ORDER BY ts DESC LIMIT 500", (int(time.time()) - secs,) + ((kind,) if kind else ())).fetchall()
                return self.send(200, json.dumps([dict(zip(("ts", "kind", "client", "user", "ip", "text"), r)) for r in rows]))
            if u.path == "/api/health": return self.send(200, json.dumps({"ok": True, "mqtt": MQTT["state"]}))
            return self.send(404, '{"error":"not found"}')
        except BadQuery as e:
            return self.send(400, json.dumps({"error": str(e)}))
        except Exception as e:
            return self.send(500, json.dumps({"error": str(e)}))

def export_accounts_soon():
    pass                                         # the account list is re-read from its copy on every request

def main():
    db_init(); conf_load(); keys_load(); nodes_load(); enrol_load(); settings_load(); cat_load(); collisions_load(); backup_load(); newnodes_baseline(); event("start", "dashboard %s started" % VERSION); cpu_pct()       # the first reading only primes the counter
    for fn in (mqtt_loop, control_loop, journal_loop, sampler_loop, alert_loop, locate_loop, settings_loop, bridge_poll_loop, neighbour_loop, group_scan_loop, cat_loop, traffic_loop): threading.Thread(target=fn, daemon=True).start()
    srv = ThreadingHTTPServer((CFG["http_host"], CFG["http_port"]), H); srv.daemon_threads = True
    print("umcnet-dash %s on http://%s:%d" % (VERSION, CFG["http_host"], CFG["http_port"]), flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
