#!/usr/bin/env python3
"""UMC Net dashboard: everything the broker, the repeaters and this server can tell you, in one page.

Reads the broker as a read-only 'monitor' account (its $SYS statistics and the meshcore/# topics), tails the
broker's log for who connects and who is refused, samples the machine, and serves a JSON API and the page on
127.0.0.1 for Caddy to put behind a login. Python standard library only: no packages to install.
"""
import collections, csv, hashlib, hmac, io, json, os, re, secrets, select, shutil, socket, sqlite3, ssl, struct, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CFG = {
    "mqtt_host": os.environ.get("DASH_MQTT_HOST", "127.0.0.1"), "mqtt_port": int(os.environ.get("DASH_MQTT_PORT", "1884")),
    "mqtt_user": os.environ.get("DASH_MQTT_USER", "dash"), "mqtt_pass_file": os.environ.get("DASH_MQTT_PASS_FILE", "/opt/umcnet-dash/mqtt.pass"),
    "http_host": os.environ.get("DASH_HTTP_HOST", "127.0.0.1"), "http_port": int(os.environ.get("DASH_HTTP_PORT", "9102")),
    "data": os.environ.get("DASH_DATA", "/var/lib/umcnet-dash"), "users": os.environ.get("DASH_USERS", "/var/lib/umcnet-dash/accounts.json"),
    "unit": os.environ.get("DASH_UNIT", "umcnet-mosquitto"), "host": os.environ.get("DASH_HOST", "net.2e0lxy.uk"),
    "services": os.environ.get("DASH_SERVICES", "umcnet-mosquitto,caddy,umcnet-dash,umcnet-admin").split(","),
    "static": os.environ.get("DASH_STATIC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dash.html")),
    "logfile": os.environ.get("DASH_LOGFILE", ""), "ctl_pass_file": os.environ.get("DASH_CTL_PASS_FILE", "/opt/umcnet-dash/ctl.pass"),
    "ctl_user": os.environ.get("DASH_CTL_USER", "controller"), "admin_sock": os.environ.get("DASH_ADMIN_SOCK", "/run/umcnet-admin/admin.sock"),
    "keep_days": int(os.environ.get("DASH_KEEP_DAYS", "14")), "journal": os.environ.get("DASH_JOURNAL", "1") == "1",
}
LOCK = threading.RLock()
START = time.time()
VERSION = "2.0"

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

class MqttConn:
    """A minimal MQTT 3.1.1 client (QoS 0): enough to listen to some topics and publish a few messages."""
    def __init__(self, user, pass_file, subs, on_msg, status):
        self.user, self.pass_file, self.subs, self.on_msg, self.status = user, pass_file, subs, on_msg, status
        self.sock = None; self.lock = threading.Lock(); self.up = False; self.error = ""
        status.update(state="starting", since=0, reconnects=0, error="")

    def publish(self, topic, payload):
        body = _s(topic) + payload
        with self.lock: self.sock.sendall(bytes([0x30]) + _rl(len(body)) + body)

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
    CTL["conn"] = MqttConn(CFG["ctl_user"], CFG["ctl_pass_file"], ["umcnet/v1/+/dev/+/resp"], on_control_reply, CTL_STATUS)
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
            if c and c.pop("takeover", False) and why == "disconnected": return
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
        out.append({"name": n, "role": v.get("role", ""), "state": v.get("state", "approved"), "device": dev, "online": len(online), "last": last, "ip": online[0]["ip"] if online else "", "device_name": d["name"] if d else "", "device_seen": d["last"] if d else 0})
    return out

# ----------------------------------------------------------------------------- history
def db_init():
    global DB
    os.makedirs(CFG["data"], exist_ok=True)
    DB = sqlite3.connect(os.path.join(CFG["data"], "dash.sqlite"), check_same_thread=False, isolation_level=None)
    DB.execute("PRAGMA journal_mode=WAL"); DB.execute("PRAGMA synchronous=NORMAL")
    DB.execute("CREATE TABLE IF NOT EXISTS samples(ts INTEGER, k TEXT, v REAL)"); DB.execute("CREATE INDEX IF NOT EXISTS s_k ON samples(k, ts)")
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
DEFAULTS = {"title": "UMC Net", "stale_minutes": 15, "cert_warn_days": 14, "cert_bad_days": 5, "disk_warn_pct": 85, "mem_warn_pct": 85, "flap_count": 5, "skew_seconds": 120,
            "auth_fail_warn": 1, "auth_fail_bad": 20, "keep_days": 14, "confirm_risky": True, "control_enabled": True,
            "alerts": {"enabled": False, "url": "", "offline": True, "online": True, "pending": True, "auth_fail": True, "cert": True, "disk": True, "control": True},
            "labels": {}}
RANGES = {"stale_minutes": (2, 1440), "cert_warn_days": (2, 60), "cert_bad_days": (1, 30), "disk_warn_pct": (50, 99), "mem_warn_pct": (50, 99), "flap_count": (2, 50),
          "skew_seconds": (5, 3600), "auth_fail_warn": (1, 1000), "auth_fail_bad": (2, 10000), "keep_days": (1, 90)}
CONF = json.loads(json.dumps(DEFAULTS))

def conf_path(): return os.path.join(CFG["data"], "config.json")

def conf_load():
    try: raw = json.load(open(conf_path()))
    except Exception: raw = {}
    merged = json.loads(json.dumps(DEFAULTS))
    for k, v in raw.items():
        if k == "alerts" and isinstance(v, dict): merged["alerts"].update({a: b for a, b in v.items() if a in merged["alerts"]})
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
        elif k in ("confirm_risky", "control_enabled"): new[k] = bool(v)
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
        elif k == "labels":
            if not isinstance(v, dict): return "labels must be an object"
            lab = {}
            for dev, d in v.items():
                if re.match(r"^[0-9A-F]{64}$", dev) and isinstance(d, dict): lab[dev] = {"label": str(d.get("label", ""))[:40], "note": str(d.get("note", ""))[:300]}
            new["labels"] = lab
    if new["cert_bad_days"] >= new["cert_warn_days"]: return "the red certificate limit must be below the amber one"
    CONF.clear(); CONF.update(new); conf_save()
    return None

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
NEVER = ("password", "set password", "set guest", "get guest", "set prv", "get prv", "set wifi", "get wifi.pwd", "wifi ", "set ap", "get ap.password", "set net", "set pin", "get pin", "setperm",
         "set http", "set telnet", "set web", "set ble", "get ble.pin", "set mqtt.custom.host", "set mqtt.custom.port", "set mqtt.custom.transport", "set mqtt.custom.username",
         "set mqtt.custom.password", "get mqtt.custom.password", "set mqtt.control", "get mqtt.control.key", "set bridge.secret", "get bridge.secret", "set app", "start ota", "ota", "erase",
         "format", "poweroff", "set telemetry", "set mqtt.custom ", "set mqtt.meshmapper", "set mqtt.waev", "set mqtt.eastmesh", "set mqtt.letsmesh")
EXACT = ("advert", "advert.zerohop", "discover.neighbors", "clock", "reboot", "ver", "neighbors", "routes", "board", "clear stats", "stats-core", "stats-radio", "stats-packets", "stats-rf",
         "stats-life", "region", "region save", "safety state", "radio watchdog", "memory")
PREFIX = ("get ", "time ", "route ", "trace ", "region ", "tempradio ", "safety log", "gps ", "radio watchdog ", "set radio", "set tx", "set dutycycle", "set af", "set agc.reset.interval", "set cad",
          "set int.thresh", "set rxdelay", "set repeat", "set loop.detect", "set path.hash.mode", "set flood.", "set group.hops.max", "set multi.acks", "set txdelay", "set direct.txdelay",
          "set advert.", "set name", "set lat", "set lon", "set owner.info", "set mqtt.iata", "set mqtt.packets", "set mqtt.raw", "set mqtt.tx", "set mqtt.status", "set mqtt.custom.bridge",
          "set mqtt.custom.rate", "set mqtt.owner", "set mqtt.email", "set powersaving", "set display.", "set bridge.enabled", "set bridge.source", "set bridge.delay", "set bridge.channel",
          "set allow.read.only")
RISKY = ("reboot", "set radio", "set tx", "region", "set name", "tempradio", "set repeat", "set mqtt.", "set bridge.", "set loop.detect", "set flood.", "set dutycycle", "clear stats", "time ")

def command_allowed(cmd):
    """The same list the repeater enforces (src/helpers/mqtt/ControlCmd.h); here it only saves a round trip."""
    if not isinstance(cmd, str) or not cmd or len(cmd) > 140 or cmd != cmd.strip(): return False
    if any(ord(c) < 32 or ord(c) == 127 or c in '"\\' for c in cmd): return False
    low = cmd.lower()
    if any(low.startswith(n) for n in NEVER): return False
    return low in EXACT or any(low.startswith(p) for p in PREFIX)

def command_risky(cmd):
    low = cmd.lower()
    return low in RISKY or any(low.startswith(r) for r in RISKY)

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

def on_control_reply(topic, payload, retained=False):
    m = re.match(r"^umcnet/v1/[^/]+/dev/([0-9A-Fa-f]{64})/resp$", topic)
    if not m or retained: return
    try: j = json.loads(payload.decode("utf-8", "replace"))
    except Exception: return
    w = CTL["waiting"].get(j.get("id"))
    if w and w["dev"] == m.group(1).upper(): w["reply"] = j; w["event"].set()

def send_command(dev, cmd, who="dashboard", confirm=False, timeout=14):
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
        audit(who, "command", dev[:12], "%s -> no answer" % cmd, False)
        return {"ok": False, "error": "no answer in %d s: control may be off on the repeater, the key may not match, or its clock may be wrong" % timeout}
    r = w["reply"]; ok = bool(r.get("ok")); text = str(r.get("reply", ""))
    audit(who, "command", dev[:12], "%s -> %s" % (cmd, text), ok)
    CTL["last"][dev] = {"cmd": cmd, "reply": text, "ok": ok, "t": time.time()}
    return {"ok": ok, "reply": text, "error": None if ok else text}

def setup_commands(name, password, dev, area):
    key = control_key(dev, create=True) if dev else None
    lines = ["set mqtt.iata %s" % (area or "LBA"), "set mqtt.custom.host %s" % CFG["host"], "set mqtt.custom.port 443", "set mqtt.custom.transport wss", "set mqtt.custom.username %s" % name]
    if password: lines.append("set mqtt.custom.password %s" % password)
    lines += ["set mqtt.custom on", "set mqtt.raw on", "set mqtt.tx off"]
    if key: lines += ["set mqtt.control.key %s" % key, "set mqtt.control on"]
    return "\n".join(lines)

# ----------------------------------------------------------------------------- alerts
ALERT_STATE = {}
def send_alert(title, text, level="warn", kind="x"):
    a = CONF["alerts"]
    event("alert", "%s: %s" % (title, text))
    try: DB.execute("INSERT INTO audit(ts,who,action,target,detail,ok) VALUES(?,?,?,?,?,?)", (int(time.time()), "alerts", "alert", kind, "%s - %s" % (title, text), 1))
    except Exception: pass
    if not a["enabled"] or not a["url"]: return "alerts are switched off or no address is set"
    def go():
        try:
            if "ntfy" in a["url"]:
                req = urllib.request.Request(a["url"], data=text.encode(), headers={"Title": title.encode("ascii", "replace").decode(), "Priority": "high" if level == "bad" else "default", "Tags": "warning" if level != "ok" else "white_check_mark"})
            else:
                req = urllib.request.Request(a["url"], data=json.dumps({"title": title, "message": text, "level": level, "host": CFG["host"], "time": int(time.time())}).encode(), headers={"Content-Type": "application/json"})
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
def diagnostics(sysinfo, accs, cert):
    out = []; now = time.time(); C = CONF
    def add(level, title, detail): out.append({"level": level, "title": title, "detail": detail})
    add("ok" if MQTT["state"] == "connected" else "bad", "Dashboard link to the broker", "connected since %s" % time.strftime("%H:%M:%S", time.localtime(MQTT["since"])) if MQTT["state"] == "connected" else "not connected: %s" % MQTT["error"])
    add("ok" if CTL_STATUS.get("state") == "connected" else "warn", "Control link to the broker", "ready" if CTL_STATUS.get("state") == "connected" else "not ready (%s)" % CTL_STATUS.get("error", CTL_STATUS.get("state", "")))
    for u, st in sysinfo["services"].items(): add("ok" if st == "active" else "bad", "Service " + u, st)
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
    return out

def overview():
    sysinfo = system(); cert = certificate(); accs = accounts(); now = time.time()
    with LOCK:
        devs = []
        for d in DEV.values():
            x = dict(d); x["types"] = dict(d["types"]); x["topics"] = dict(d["topics"]); x["pm"] = round(rate_per_min("pkt:" + d["id"], 300), 2); x["has_key"] = d["id"] in KEYS; x["label"] = CONF["labels"].get(d["id"], {}); x["last_cmd"] = CTL["last"].get(d["id"]); x["age"] = round(now - d["last"], 1) if d["last"] else 10 ** 9; devs.append(x)
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
               "ev_hour": dict(collections.Counter(e["kind"] for e in EVENTS if now - e["t"] < 3600)), "host": CFG["host"], "config": CONF, "control": {"state": CTL_STATUS.get("state", "idle"), "error": CTL_STATUS.get("error", ""), "keys": sorted(KEYS)}}
    res["pending"] = pending_list()
    res["diagnostics"] = diagnostics(sysinfo, accs, cert)
    return res

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
            who = "admin"; p = u.path
            if p == "/api/control":
                return self.send(200, json.dumps(send_command(body.get("device"), str(body.get("cmd", "")), who, bool(body.get("confirm")))))
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
                return self.send(200, json.dumps({"ok": bool(r.get("ok")), "error": r.get("error") or (None if r.get("ok") else r.get("output")), "password": r.get("password"), "output": r.get("output")}))
            if p == "/api/password":
                r = admin_call(op="dash_password", current=str(body.get("current", "")), new=str(body.get("new", ""))); audit(who, "dashboard password", "admin", r.get("error") or "changed", bool(r.get("ok")))
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
            if u.path == "/api/audit":
                secs = max(60, min(90 * 86400, int(q.get("range", ["604800"])[0])))
                rows = DB.execute("SELECT ts,who,action,target,detail,ok FROM audit WHERE ts>=? ORDER BY ts DESC LIMIT 500", (int(time.time()) - secs,)).fetchall()
                return self.send(200, json.dumps([dict(zip(("ts", "who", "action", "target", "detail", "ok"), r)) for r in rows]))
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

def export_accounts_soon():
    pass                                         # the account list is re-read from its copy on every request

def main():
    db_init(); conf_load(); keys_load(); event("start", "dashboard %s started" % VERSION); cpu_pct()       # the first reading only primes the counter
    for fn in (mqtt_loop, control_loop, journal_loop, sampler_loop, alert_loop): threading.Thread(target=fn, daemon=True).start()
    srv = ThreadingHTTPServer((CFG["http_host"], CFG["http_port"]), H); srv.daemon_threads = True
    print("umcnet-dash %s on http://%s:%d" % (VERSION, CFG["http_host"], CFG["http_port"]), flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
