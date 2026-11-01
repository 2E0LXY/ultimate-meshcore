#!/usr/bin/env python3
"""Screenshots of the UMC Net dashboard for the README and the manual, from a real broker and dashboard fed by simulated
repeaters with demo names (nothing real is published). Needs mosquitto and Playwright.
    python3 shots_dashboard.py <output folder>"""
import base64, hashlib, importlib.util, json, os, shutil, socket, socketserver, struct, subprocess, sys, tempfile, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
ENR = load("umcnet_enrol", os.path.join(HERE, "umcnet_enrol.py"))
D = tempfile.mkdtemp(prefix="shots"); os.chmod(D, 0o755)
PORT, HTTP = 18857, 19257
def sh(*a): return subprocess.run(list(a), capture_output=True, text=True)

# ---- the same rules umcnet-user writes for these three roles
for u, p in (("dash", "dashpw"), ("controller", "ctlpw"), ("enrol", "enrol-open-door-v1"), ("rep1", "pw1"), ("rep2", "pw2")): sh("mosquitto_passwd", "-b", "-c" if u == "dash" else "-b", D + "/passwd", u, p)
open(D + "/acl", "w").write("""user dash
topic read $SYS/#
topic read meshcore/#

user controller
topic write umcnet/v1/+/dev/+/cmd
topic read umcnet/v1/+/dev/+/resp
topic read umcnet/v1/enrol/hello
topic write umcnet/v1/enrol/grant/#
topic write meshcore/+/DADADADADADADADADADADADADADADADADADADADADADADADADADADADADADADADA/raw

user rep1
topic readwrite meshcore/#
topic readwrite umcnet/#

user rep2
topic readwrite meshcore/#
topic readwrite umcnet/#

user enrol
topic write umcnet/v1/enrol/hello
topic read umcnet/v1/enrol/grant/#
""")
open(D + "/m.conf", "w").write(f"per_listener_settings true\nlistener {PORT} 127.0.0.1\nallow_anonymous false\npassword_file {D}/passwd\nacl_file {D}/acl\npersistence false\nlog_dest file {D}/mosq.log\nlog_type notice\nconnection_messages true\n")
open(D + "/mosq.log", "w").close(); sh("chown", "-R", "mosquitto:mosquitto", D)
broker = subprocess.Popen(["mosquitto", "-c", D + "/m.conf"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(1.5)

# ---- a stand-in for the root helper that makes accounts
made = []
class H(socketserver.StreamRequestHandler):
    def handle(self):
        req = json.loads(self.rfile.readline()); made.append(req)
        out = {"ok": True, "output": "ok"}
        if req["op"] in ("user_add", "user_passwd"): out["password"] = "Pw" + hashlib.sha1(json.dumps(req).encode()).hexdigest()[:18]
        self.wfile.write((json.dumps(out) + "\n").encode())
class S(socketserver.ThreadingMixIn, socketserver.UnixStreamServer): daemon_threads = True
srv = S(D + "/admin.sock", H); threading.Thread(target=srv.serve_forever, daemon=True).start()
open(D + "/dash.pass", "w").write("dashpw"); open(D + "/ctl.pass", "w").write("ctlpw"); os.makedirs(D + "/data", exist_ok=True); open(D + "/users.json", "w").write("{}")
env = dict(os.environ, DASH_MQTT_PORT=str(PORT), DASH_MQTT_PASS_FILE=D + "/dash.pass", DASH_CTL_PASS_FILE=D + "/ctl.pass", DASH_DATA=D + "/data", DASH_USERS=D + "/users.json", DASH_LOGFILE=D + "/mosq.log", DASH_HTTP_PORT=str(HTTP), DASH_SERVICES="mosquitto", DASH_STATIC=os.path.join(HERE, "dash.html"), DASH_ADMIN_SOCK=D + "/admin.sock")
dash = subprocess.Popen([sys.executable, os.path.join(HERE, "umcnet_dash.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(3.5)

# ---- a minimal MQTT client for the simulated repeater
def rl(n):
    o = bytearray()
    while True:
        b = n % 128; n //= 128
        if n: b |= 128
        o.append(b)
        if not n: return bytes(o)
def st(x): x = x.encode() if isinstance(x, str) else x; return struct.pack(">H", len(x)) + x
class Dev:
    def __init__(self, user, pw, cid):
        self.s = socket.create_connection(("127.0.0.1", PORT)); self.s.settimeout(0.5)
        body = st("MQTT") + bytes([4, 0xC2]) + struct.pack(">H", 60) + st(cid) + st(user) + st(pw)
        self.s.sendall(bytes([0x10]) + rl(len(body)) + body); self.ack = self.s.recv(4)
    def sub(self, topic):
        body = struct.pack(">H", 1) + st(topic) + bytes([0]); self.s.sendall(bytes([0x82]) + rl(len(body)) + body)
    def pub(self, topic, payload, retain=0):
        b = st(topic) + (payload if isinstance(payload, bytes) else payload.encode()); self.s.sendall(bytes([0x30 | retain]) + rl(len(b)) + b)
    def read(self, secs=4):
        end = time.time() + secs; buf = b""; got = []
        while time.time() < end:
            try: c = self.s.recv(65536)
            except socket.timeout: c = b""
            buf += c
            while len(buf) >= 2:
                t = buf[0]; i = 1; ln = 0; m = 1
                while i < len(buf):
                    ln += (buf[i] & 127) * m; m *= 128
                    if not buf[i] & 128: break
                    i += 1
                i += 1
                if len(buf) < i + ln: break
                body = buf[i:i + ln]; buf = buf[i + ln:]
                if t >> 4 == 3:
                    tl = struct.unpack(">H", body[:2])[0]; got.append((body[2:2 + tl].decode(), body[2 + tl:]))
            if got: break
        return got
    def close(self):
        try: self.s.close()
        except Exception: pass
def api(path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (HTTP, path), data=json.dumps(body).encode() if body is not None else None, headers={"X-UMC-Dash": "1", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())
res = []
def check(name, cond, extra=""): res.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name, extra)


MSG = load("umcnet_msgs", os.path.join(HERE, "umcnet_msgs.py"))
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))
def J(x): return json.dumps(x, separators=(",", ":"))
REPS = [("rep1", "pw1", "A7" * 32, "Hill-Top-RPT", 53.6431, -1.6513), ("rep2", "pw2", "B8" * 32, "Valley-RPT", 53.4120, -1.4800)]
import struct as _st, random, threading as _th
random.seed(7)
def advert(pubkey, name, lat, lon, now, kind=2):
    pl = pubkey + _st.pack("<I", now) + bytes(64) + bytes([kind | 0x10 | 0x80]) + _st.pack("<ii", int(lat * 1e6), int(lon * 1e6)) + name.encode()
    return bytes([(4 << 2) | 1, 0]) + pl
def with_hops(raw, hops):
    p = MSG.parse_wire(raw); i = 5 if p["codes"] else 1
    return raw[:i] + bytes([len(hops)]) + bytes(hops) + raw[i + 1:]
try:
    now = int(time.time()); cl = {}
    for u, pw, did, name, la, lo in REPS:
        c = Dev(u, pw, "c-" + u); cl[did] = c
        c.pub("meshcore/LBA/%s/status" % did, J({"status": "online", "origin": name, "model": "Heltec V4 OLED" if u == "rep2" else "Heltec V3", "firmware_version": "v1.17.1", "radio": "869.618,62.5,8,8", "timestamp": iso(now), "stats": {"battery_mv": 4120, "uptime_secs": 186000, "noise_floor": -113, "tx_air_secs": 1450, "rx_air_secs": 5200, "queue_len": 0, "errors": 0}}), retain=1)
    # the simulated repeaters answer remote commands the way real ones do
    replies = {"get mqtt.custom.bridge": lambda did: "> on, heard %d, passed on %d, dropped 2, up to 20 a minute" % (int(time.time()) // 7 % 5000, int(time.time()) // 9 % 4000),
               "neighbors": lambda did: "\n".join("%s:%d:%d" % (keys[n][:4].hex().upper(), a, q) for n, a, q in (("Emley Moor", 83, 22), ("Ossett Solar", 125, -24), ("Holme Moss", 302, -13))) + "\n%s:40:46" % ("B8B8B8B8" if did.startswith("A7") else "A7A7A7A7")}
    SETTINGS = {"get build": "> 0.1.29 umc_heltec_v3_repeater commit:5d77add", "get update.status": "> up-to-date running:0.1.29 build:5d77add", "get tx": "> 22", "get advert.interval": "> 3",
                "get flood.advert.interval": "> 12", "get flood.max": "> 8", "get mqtt.tx": "> off", "get radio": "> 869.618,62.5,8,8", "get repeat": "> on", "get mqtt.raw": "> on", "get update.auto": "> install", "get ota.state": "> running:app1 (valid) other:app0 (valid)"}
    def responder(did, c):
        c.sub("umcnet/v1/LBA/dev/%s/cmd" % did)
        while not STOP:
            for topic, payload in c.read(1):
                try: m = json.loads(payload)
                except Exception: continue
                cmd = m.get("cmd", ""); f = replies.get(cmd)
                rep = f(did) if f else ("> " + dict((r[2], r[3]) for r in REPS)[did]) if cmd == "get name" else SETTINGS.get(cmd, "> OK")
                c.pub("umcnet/v1/LBA/dev/%s/resp" % did, J({"id": m.get("id"), "ok": True, "reply": rep}))
    keys = {}
    STOP = False
    ctl = {did: Dev(u, pw, "ctl-" + u) for u, pw, did, *_ in REPS}
    for did, c in ctl.items(): _th.Thread(target=responder, args=(did, c), daemon=True).start()
    for did in ctl: api("/api/control/setup", {"device": did})
    # adverts: the repeaters themselves and the nodes around them
    others = [("Emley Moor", 53.6125, -1.6640, 2), ("Holme Moss", 53.5333, -1.8578, 2), ("City Room", 53.3811, -1.4701, 3), ("Wakefield Node", 53.6830, -1.4977, 1), ("Ossett Solar", 53.6800, -1.5800, 2), ("Barnsley West", 53.5526, -1.4797, 2)]
    for u, pw, did, name, la, lo in REPS: cl[did].pub("meshcore/LBA/%s/raw" % did, J({"origin": name, "data": advert(bytes.fromhex(did), name, la, lo, now).hex().upper(), "SNR": "9"}))
    for i, (nm, la, lo, kind) in enumerate(others):
        k = os.urandom(32); keys[nm] = k; did = REPS[i % 2][2]
        cl[did].pub("meshcore/LBA/%s/raw" % did, J({"origin": dict((r[2], r[3]) for r in REPS)[did], "data": with_hops(advert(k, nm, la, lo, now, kind), [] if i < 3 else [0x44]).hex().upper(), "SNR": str(random.choice([-6, 3, 7.5, 11])), "RSSI": "-95"}))
    # channel traffic in a few channels and regions
    chats = [("#yorkshire", "yorkshire", "Sam", "Anyone on the Yorkshire repeaters this evening?"), ("Public", "", "Pat", "Good morning all, testing from the car"),
             ("#yorkshire", "eng-yh", "G4ABC", "Net tonight at 8 on #yorkshire, all welcome"), ("#sheffield", "sheffield", "Jo", "Valley repeater is loud and clear from Hillsborough"),
             ("#wakefield", "", "M7XYZ", "Just put a solar node up near Ossett"), ("Public", "", "Chris", "Heard Holme Moss direct at -12 dB")]
    for i, (ch, reg, who, text) in enumerate(chats):
        c = MSG.Channel(ch, MSG.PUBLIC_PSK if ch == "Public" else None); raw = MSG.build_group_text(c, who, text, now - 600 + i * 60, region=reg or None)
        cl[REPS[0][2]].pub("meshcore/LBA/%s/raw" % REPS[0][2], J({"origin": REPS[0][3], "data": raw.hex().upper(), "SNR": "6.5", "RSSI": "-90"}))
        if i % 2 == 0: cl[REPS[1][2]].pub("meshcore/LBA/%s/raw" % REPS[1][2], J({"origin": REPS[1][3], "data": with_hops(raw, [0x44]).hex().upper(), "SNR": "9", "RSSI": "-82"}))
        time.sleep(0.2)
    api("/api/users/save", {"name": "g4abc", "password": "Correct-Horse-9", "role": "owner", "devices": [REPS[0][2]], "sender": "G4ABC"})
    api("/api/users/save", {"name": "m7xyz", "password": "Correct-Horse-9", "role": "viewer", "sender": "M7XYZ"})
    print("waiting for the dashboard's once-a-minute bridge reading…"); time.sleep(155)
    def keep_alive():                                  # keep the repeaters "live" (packets per minute) while the pictures are taken
        while not STOP:
            for u, pw, did, name, la, lo in REPS:
                cl[did].pub("meshcore/LBA/%s/raw" % did, J({"origin": name, "data": advert(os.urandom(32), "", 0, 0, now).hex().upper(), "SNR": "5"}))
            time.sleep(4)
    _th.Thread(target=keep_alive, daemon=True).start(); time.sleep(10)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1); pg.on("dialog", lambda d: d.accept())
        def go(tab, wait=2500): pg.click('[data-t="%s"]' % tab); pg.wait_for_timeout(wait)
        def shot(name, sel=None, clip_h=None):
            path = os.path.join(OUT, name)
            if sel: pg.locator(sel).first.screenshot(path=path)
            else: pg.screenshot(path=path, full_page=False, clip={"x": 0, "y": 0, "width": 1440, "height": clip_h} if clip_h else None)
            print("saved", path)
        hide = "#live{visibility:hidden!important}"                           # the problems badge reflects this test machine, not a real server
        pg.goto("http://127.0.0.1:%d/" % HTTP); pg.add_style_tag(content=hide); pg.wait_for_timeout(3500)
        flow = pg.locator(".pn", has=pg.locator(".flow")); flow.first.screenshot(path=os.path.join(OUT, "umcnet-flow.png")); print("saved flow")
        go("messages"); shot("umcnet-messages.png", clip_h=640)
        go("network", 5000); pg.locator('path[stroke="#f2c14e"]').first.click(force=True); pg.wait_for_timeout(1500); shot("umcnet-network.png", clip_h=820)
        go("control", 5000); shot("umcnet-control.png", clip_h=1000)
        neigh = pg.locator(".pn", has=pg.locator("#ctlNeigh")); neigh.first.screenshot(path=os.path.join(OUT, "umcnet-neighbours.png")); print("saved neighbours")
        go("users"); shot("umcnet-users.png", clip_h=640)
        go("settings"); msgp = pg.locator(".pn", has=pg.locator("#mcChans")); msgp.first.screenshot(path=os.path.join(OUT, "umcnet-settings-messaging.png")); print("saved settings")
        ctx = br.new_context(viewport={"width": 1440, "height": 760}, extra_http_headers={"X-UMC-User": "g4abc"}); up = ctx.new_page()
        up.goto("http://127.0.0.1:%d/" % HTTP); up.add_style_tag(content=hide); up.wait_for_timeout(3000); up.click('[data-t="control"]'); up.wait_for_timeout(3500); up.screenshot(path=os.path.join(OUT, "umcnet-owner.png")); print("saved owner")
        br.close()
    STOP = True
finally:
    dash.terminate(); broker.terminate(); srv.shutdown(); shutil.rmtree(D, ignore_errors=True)
