#!/usr/bin/env python3
"""UMC Net dashboard: everything the broker, the repeaters and this server can tell you, in one page.

Reads the broker as a read-only 'monitor' account (its $SYS statistics and the meshcore/# topics), tails the
broker's log for who connects and who is refused, samples the machine, and serves a JSON API and the page on
127.0.0.1 for Caddy to put behind a login. Python standard library only: no packages to install.
"""
import collections, hashlib, json, os, re, select, shutil, socket, sqlite3, ssl, struct, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CFG = {
    "mqtt_host": os.environ.get("DASH_MQTT_HOST", "127.0.0.1"), "mqtt_port": int(os.environ.get("DASH_MQTT_PORT", "1884")),
    "mqtt_user": os.environ.get("DASH_MQTT_USER", "dash"), "mqtt_pass_file": os.environ.get("DASH_MQTT_PASS_FILE", "/opt/umcnet-dash/mqtt.pass"),
    "http_host": os.environ.get("DASH_HTTP_HOST", "127.0.0.1"), "http_port": int(os.environ.get("DASH_HTTP_PORT", "9102")),
    "data": os.environ.get("DASH_DATA", "/var/lib/umcnet-dash"), "users": os.environ.get("DASH_USERS", "/var/lib/umcnet-dash/accounts.json"),
    "unit": os.environ.get("DASH_UNIT", "umcnet-mosquitto"), "host": os.environ.get("DASH_HOST", "net.2e0lxy.uk"),
    "services": os.environ.get("DASH_SERVICES", "umcnet-mosquitto,caddy,umcnet-dash").split(","),
    "static": os.environ.get("DASH_STATIC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dash.html")),
    "logfile": os.environ.get("DASH_LOGFILE", ""),
    "keep_days": int(os.environ.get("DASH_KEEP_DAYS", "14")), "journal": os.environ.get("DASH_JOURNAL", "1") == "1",
}
LOCK = threading.RLock()
START = time.time()
VERSION = "1.0"

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

PTYPES = {0: "REQ", 1: "RESP", 2: "MSG", 3: "ACK", 4: "ADVERT", 5: "CHAN", 6: "CHDATA", 7: "ANON", 8: "PATH", 9: "TRACE", 10: "MULTI", 11: "CTRL"}

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
            out["key"] = p[:4].hex().upper(); j = 100; f = p[j]; j += 1
            if f & 0x10: j += 8
            if f & 0x20: j += 2
            if f & 0x40: j += 2
            if f & 0x80 and j < len(p): out["name"] = p[j:].decode("utf-8", "replace").rstrip("\0").strip()
        return out
    except Exception:
        return None

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
        direction = j.get("direction", "rx") if kind == "packets" else "rx"
        # a device that publishes both topics is counted once: count 'packets', and 'raw' only when no packets arrive
        counted = kind == "packets" or d["n_pkt"] == 0
        if counted:
            d["n_tx" if direction == "tx" else "n_rx"] += 1; note_rate("pkt:" + did); note_rate("packets")
            d["types"][info.get("type") or ("T%s" % j.get("packet_type", "?"))] += 1; d["bytes"] += len(raw)
            try: d["rssi"] = int(j["RSSI"]) if "RSSI" in j else d["rssi"]; d["snr"] = float(j["SNR"]) if "SNR" in j else d["snr"]
            except (ValueError, TypeError): pass
            if direction == "rx" and raw:
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

def mqtt_loop():
    backoff = 2
    while True:
        try:
            pw = open(CFG["mqtt_pass_file"]).read().strip()
            s = socket.create_connection((CFG["mqtt_host"], CFG["mqtt_port"]), timeout=10); s.settimeout(40)
            vh = _s("MQTT") + bytes([4, 0xC2]) + struct.pack(">H", 60)
            body = vh + _s("umcnet-dash-%d" % os.getpid()) + _s(CFG["mqtt_user"]) + _s(pw)
            s.sendall(bytes([0x10]) + _rl(len(body)) + body)
            ack = s.recv(4)
            if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0: raise RuntimeError("broker refused the dashboard account (code %s)" % (ack[3] if len(ack) >= 4 else "?"))
            subs = b"".join(_s(t) + b"\x00" for t in ("$SYS/#", "meshcore/#"))
            s.sendall(bytes([0x82]) + _rl(2 + len(subs)) + b"\x00\x01" + subs)
            MQTT.update(state="connected", since=time.time(), error=""); backoff = 2
            buf = b""; last_ping = time.time()
            while True:
                if time.time() - last_ping > 30: s.sendall(b"\xc0\x00"); last_ping = time.time()
                try: chunk = s.recv(65536)
                except socket.timeout: continue
                if not chunk: raise RuntimeError("broker closed the connection")
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
                        tl = struct.unpack(">H", pkt[:2])[0]; topic = pkt[2:2 + tl].decode("utf-8", "replace"); on_publish(topic, pkt[2 + tl:], bool(first & 1))
        except Exception as e:
            MQTT.update(state="disconnected", error=str(e)); MQTT["reconnects"] += 1
            time.sleep(backoff); backoff = min(60, backoff * 2)

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
            "swap_total": mem.get("SwapTotal", 0) * 1024, "swap_free": mem.get("SwapFree", 0) * 1024, "disk_total": st.total, "disk_free": st.free, "net": net, "services": svc, "broker_rss": mrss, "broker_fds": mfd,
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
        out.append({"name": n, "role": v.get("role", ""), "device": dev, "online": len(online), "last": last, "ip": online[0]["ip"] if online else "", "device_name": d["name"] if d else "", "device_seen": d["last"] if d else 0})
    return out

# ----------------------------------------------------------------------------- history
def db_init():
    global DB
    os.makedirs(CFG["data"], exist_ok=True)
    DB = sqlite3.connect(os.path.join(CFG["data"], "dash.sqlite"), check_same_thread=False, isolation_level=None)
    DB.execute("PRAGMA journal_mode=WAL"); DB.execute("PRAGMA synchronous=NORMAL")
    DB.execute("CREATE TABLE IF NOT EXISTS samples(ts INTEGER, k TEXT, v REAL)"); DB.execute("CREATE INDEX IF NOT EXISTS s_k ON samples(k, ts)")
    DB.execute("CREATE TABLE IF NOT EXISTS events(ts INTEGER, kind TEXT, client TEXT, user TEXT, ip TEXT, text TEXT)"); DB.execute("CREATE INDEX IF NOT EXISTS e_ts ON events(ts)")

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
            now = int(time.time()); vals = snapshot_values()
            DB.executemany("INSERT INTO samples VALUES(?,?,?)", [(now, k, float(v)) for k, v in vals.items()])
            if now % 3600 < 60:
                cut = now - CFG["keep_days"] * 86400; DB.execute("DELETE FROM samples WHERE ts<?", (cut,)); DB.execute("DELETE FROM events WHERE ts<?", (cut,))
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

# ----------------------------------------------------------------------------- the overview the page draws
def diagnostics(sysinfo, accs, cert):
    out = []; now = time.time()
    def add(level, title, detail): out.append({"level": level, "title": title, "detail": detail})
    add("ok" if MQTT["state"] == "connected" else "bad", "Dashboard link to the broker", "connected since %s" % time.strftime("%H:%M:%S", time.localtime(MQTT["since"])) if MQTT["state"] == "connected" else "not connected: %s" % MQTT["error"])
    for u, st in sysinfo["services"].items(): add("ok" if st == "active" else "bad", "Service " + u, st)
    up = sysnum("$SYS/broker/uptime", -1)
    if up >= 0: add("warn" if up < 300 else "ok", "Broker uptime", "%d min%s" % (up // 60, " (it restarted recently)" if up < 300 else ""))
    if cert and "days" in cert: add("bad" if cert["days"] < 5 else "warn" if cert["days"] < 14 else "ok", "TLS certificate for %s" % cert["host"], "%.0f days left (%s)" % (cert["days"], cert.get("issuer", "")))
    elif cert: add("bad", "TLS certificate", cert.get("error", "cannot read it"))
    free = 100.0 * sysinfo["disk_free"] / sysinfo["disk_total"] if sysinfo["disk_total"] else 100
    add("bad" if free < 8 else "warn" if free < 15 else "ok", "Disk space", "%.0f%% free" % free)
    ma = 100.0 * sysinfo["mem_avail"] / sysinfo["mem_total"] if sysinfo["mem_total"] else 100
    add("bad" if ma < 8 else "warn" if ma < 15 else "ok", "Memory", "%.0f%% available" % ma)
    if sysinfo["load"]: add("warn" if sysinfo["load"][0] > (sysinfo["cores"] or 1) * 1.5 else "ok", "Load", "%.2f %.2f %.2f on %d core(s)" % (*sysinfo["load"], sysinfo["cores"] or 1))
    hour = [e for e in EVENTS if now - e["t"] < 3600]
    fails = [e for e in hour if e["kind"] == "auth_fail"]
    ips = collections.Counter(e["ip"] or "?" for e in fails)
    add("bad" if len(fails) > 20 else "warn" if fails else "ok", "Refused logins, last hour", "%d%s" % (len(fails), " from " + ", ".join("%s ×%d" % x for x in ips.most_common(4)) if fails else ""))
    for c in CLIENTS.values():
        h = [t for t in c.get("history", []) if now - t < 600]
        if len(h) >= 5: add("warn", "Reconnecting often: " + (c.get("user") or c["client"]), "%d connections in 10 minutes (%s): a weak WiFi link or two devices sharing one account" % (len(h), c.get("ip", "")))
    for a in accs:
        if a["role"] == "repeater":
            if not a["device"]: add("warn", "Repeater account without a device id: " + a["name"], "bind it with: umcnet-user device %s <64 hex>" % a["name"])
            elif not a["online"]: add("warn", "Repeater offline: " + a["name"], "last connected %s" % (time.strftime("%d %b %H:%M", time.localtime(a["last"])) if a["last"] else "never since this dashboard started"))
    for d in DEV.values():
        age = now - d["last"]
        if age > 900: add("warn", "No data from %s" % (d["name"] or d["id"][:12]), "last heard %d min ago" % (age // 60))
        if d["skew"] is not None and abs(d["skew"]) > 120: add("warn", "Clock off on %s" % (d["name"] or d["id"][:12]), "%+.0f s against this server (its NTP may be down)" % d["skew"])
        if d["status"] == "offline" and age > 300: add("warn", "%s reports itself offline" % (d["name"] or d["id"][:12]), "its last status message said offline and nothing has arrived since")
    dr = sysnum("$SYS/broker/load/publish/dropped/1min")
    if dr > 0: add("warn", "Broker is dropping messages", "%.1f a minute (a slow subscriber or full queues)" % dr)
    return out

def overview():
    sysinfo = system(); cert = certificate(); accs = accounts(); now = time.time()
    with LOCK:
        devs = []
        for d in DEV.values():
            x = dict(d); x["types"] = dict(d["types"]); x["topics"] = dict(d["topics"]); x["pm"] = round(rate_per_min("pkt:" + d["id"], 300), 2); x["age"] = round(now - d["last"], 1); devs.append(x)
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
        res = {"version": VERSION, "now": now, "started": START, "mqtt": dict(MQTT), "sys": sysd, "system": sysinfo, "cert": cert, "devices": devs, "clients": clients, "accounts": accs,
               "packets": [dict(p) for p in list(PKTS)[-60:]][::-1], "events": [dict(e) for e in list(EVENTS)[-80:]][::-1], "log": [dict(l) for l in list(LOG)[-60:]][::-1], "count": dict(COUNT),
               "rates": {"messages": rate_per_min("messages"), "packets": rate_per_min("packets"), "unique": rate_per_min("unique")},
               "overlap": {"ids": ids, "names": [DEV[i]["name"] or i[:8] for i in ids], "m": overlap}, "heard_by": dict(sorted(multi.items())), "types": dict(types),
               "latency": {"n": len(LATENCY), "avg": round(sum(LATENCY) / len(LATENCY), 2) if LATENCY else None, "max": round(max(LATENCY), 2) if LATENCY else None},
               "ev_hour": dict(collections.Counter(e["kind"] for e in EVENTS if now - e["t"] < 3600)), "host": CFG["host"]}
    res["diagnostics"] = diagnostics(sysinfo, accs, cert)
    return res

# ----------------------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "umcnet-dash"
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"): return self.send(200, open(CFG["static"], "rb").read(), "text/html")
            if u.path == "/api/overview": return self.send(200, json.dumps(overview(), default=str))
            if u.path == "/api/history":
                keys = [k for k in (q.get("k", [""])[0]).split(",") if k][:12]; secs = max(60, min(14 * 86400, int(q.get("range", ["3600"])[0])))
                return self.send(200, json.dumps(history(keys, secs)))
            if u.path == "/api/events":
                secs = max(60, min(14 * 86400, int(q.get("range", ["86400"])[0]))); kind = q.get("kind", [""])[0]
                rows = DB.execute("SELECT ts,kind,client,user,ip,text FROM events WHERE ts>=? " + ("AND kind=? " if kind else "") + "ORDER BY ts DESC LIMIT 500", (int(time.time()) - secs,) + ((kind,) if kind else ())).fetchall()
                return self.send(200, json.dumps([dict(zip(("ts", "kind", "client", "user", "ip", "text"), r)) for r in rows]))
            if u.path == "/api/health": return self.send(200, json.dumps({"ok": True, "mqtt": MQTT["state"]}))
            return self.send(404, '{"error":"not found"}')
        except Exception as e:
            return self.send(500, json.dumps({"error": str(e)}))

def main():
    db_init(); event("start", "dashboard %s started" % VERSION); cpu_pct()       # the first reading only primes the counter
    for fn in (mqtt_loop, journal_loop, sampler_loop): threading.Thread(target=fn, daemon=True).start()
    srv = ThreadingHTTPServer((CFG["http_host"], CFG["http_port"]), H); srv.daemon_threads = True
    print("umcnet-dash %s on http://%s:%d" % (VERSION, CFG["http_host"], CFG["http_port"]), flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
