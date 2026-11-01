#!/usr/bin/env python3
"""End-to-end test of zero-touch enrolment against a real Mosquitto: needs `mosquitto` and `mosquitto_passwd`
installed. It starts a private broker with the same permission rules umcnet-user writes, the dashboard service with a
stand-in for the root helper, and a simulated repeater that knocks, is approved and opens its grant.
    python3 e2e_enrol.py"""
import base64, hashlib, importlib.util, json, os, shutil, socket, socketserver, struct, subprocess, sys, tempfile, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
ENR = load("umcnet_enrol", os.path.join(HERE, "umcnet_enrol.py"))
D = tempfile.mkdtemp(prefix="enrole2e"); os.chmod(D, 0o755)
PORT, HTTP = 18851, 19251
def sh(*a): return subprocess.run(list(a), capture_output=True, text=True)

# ---- the same rules umcnet-user writes for these three roles
for u, p in (("dash", "dashpw"), ("controller", "ctlpw"), ("enrol", "enrol-open-door-v1")): sh("mosquitto_passwd", "-b", "-c" if u == "dash" else "-b", D + "/passwd", u, p)
open(D + "/acl", "w").write("""user dash
topic read $SYS/#
topic read meshcore/#

user controller
topic write umcnet/v1/+/dev/+/cmd
topic read umcnet/v1/+/dev/+/resp
topic read umcnet/v1/enrol/hello
topic write umcnet/v1/enrol/grant/#

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
def hello(prv, pub, name="Hill Top", ts=None, bad=False):
    dev = pub.hex().upper(); ts = int(ts or time.time()); nc = os.urandom(8).hex()
    sig = ENR.ed_sign(prv, pub, ENR.hello_message(dev, ts, nc)).hex()
    if bad: sig = ("00" if sig[:2] != "00" else "11") + sig[2:]
    return json.dumps({"v": 1, "id": dev, "name": name, "fw": "0.2.0", "bd": "Heltec V3", "ts": ts, "nc": nc, "sig": sig})
def join_decode(code):
    raw = code[5:]; b = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)); assert hashlib.sha256(b[:-3]).digest()[:3] == b[-3:]
    flags = b[1]; i = 2; iata = b[i:i + 3].decode(); i += 3; ul = b[i]; i += 1; user = b[i:i + ul].decode(); i += ul; pl = b[i]; i += 1; pw = b[i:i + pl].decode(); i += pl
    return {"iata": iata, "user": user, "pass": pw, "key": b[i:i + 32].hex() if flags & 1 else None, "bridge": bool(flags & 2)}
try:
    prv, pub = ENR.ed_keypair(os.urandom(32)); dev = pub.hex().upper()
    knock = Dev("enrol", "enrol-open-door-v1", "umc-enrol-" + dev[:12]); check("the public enrol account can connect", knock.ack[3:4] == b"\x00", knock.ack.hex())
    knock.sub("umcnet/v1/enrol/grant/" + dev); time.sleep(0.5)
    knock.pub("umcnet/v1/enrol/hello", hello(prv, pub)); time.sleep(1.5)
    e = api("/api/overview")["enrol"]; check("a signed request appears as waiting", len(e["pending"]) == 1 and e["pending"][0]["id"] == dev and e["pending"][0]["name"] == "Hill Top", e["pending"][0]["name"] if e["pending"] else "")
    # refused requests
    knock.pub("umcnet/v1/enrol/hello", hello(prv, pub, bad=True)); other_prv, other_pub = ENR.ed_keypair(os.urandom(32))
    bad = json.loads(hello(other_prv, other_pub)); bad["id"] = dev[:-2] + ("00" if dev[-2:] != "00" else "11"); knock.pub("umcnet/v1/enrol/hello", json.dumps(bad))
    knock.pub("umcnet/v1/enrol/hello", hello(prv, pub, ts=time.time() - 3 * 86400)); knock.pub("umcnet/v1/enrol/hello", "not json at all"); time.sleep(1.5)
    e = api("/api/overview")["enrol"]; check("forged, stale and garbled requests are ignored", len(e["pending"]) == 1)
    # the enrol account cannot do anything else
    knock.pub("meshcore/LBA/%s/status" % dev, "{}"); knock.pub("umcnet/v1/LBA/dev/%s/cmd" % dev, "{}"); knock.pub("umcnet/v1/enrol/grant/" + dev, b"forged", retain=1); time.sleep(1)
    check("the enrol account cannot publish anything but a request", knock.read(1.5) == [])
    # approval
    r = api("/api/enrol/approve", {"id": dev, "name": "Hill Top"}); check("approving works", r["ok"] and r["account"] == "hill-top", r)
    got = knock.read(5); check("the repeater receives a grant", len(got) == 1 and got[0][0] == "umcnet/v1/enrol/grant/" + dev)
    code = ENR.open_grant(prv, dev, got[0][1].decode()) if got else None; d = join_decode(code) if code else {}
    check("only it can open it, and it holds the account, the area, the bridge and the control key", d.get("user") == "hill-top" and d.get("iata") == "LBA" and d.get("bridge") and d.get("key") and len(d["pass"]) >= 8, {k: v for k, v in d.items() if k != "pass"})
    check("another key cannot open it", got and ENR.open_grant(other_prv, dev, got[0][1].decode()) is None)
    check("the account was made bound to this device", any(r["op"] == "user_add" and r["device"] == dev and r["role"] == "repeater" for r in made))
    e = api("/api/overview")["enrol"]; check("it is no longer waiting", not e["pending"] and e["approved"] and e["approved"][0]["account"] == "hill-top")
    late = Dev("enrol", "enrol-open-door-v1", "umc-enrol-late"); late.sub("umcnet/v1/enrol/grant/" + dev); lg = late.read(3)
    check("a repeater that connects later still gets the (retained) grant", len(lg) == 1); late.close()
    # the grant is taken off the broker once the repeater uses its own account
    import re
    time.sleep(0.2); chk = Dev("controller", "ctlpw", "cleanup-check")
    api("/api/overview")
    # simulate the broker log line the dashboard reads when the repeater connects as its account
    with open(D + "/mosq.log", "a") as f: f.write("%d: New client connected from 127.0.0.1:5555 as mqtt_custom-%s (p2, c1, k30, u'hill-top').\n" % (int(time.time()), dev[:6]))
    time.sleep(3); chk.close()
    late2 = Dev("enrol", "enrol-open-door-v1", "umc-enrol-late2"); late2.sub("umcnet/v1/enrol/grant/" + dev)
    # housekeeping runs once a minute: ask the service to run it now by waiting for its next tick
    waited = 0; gone = False
    while waited < 75 and not gone:
        time.sleep(5); waited += 5; late3 = Dev("enrol", "enrol-open-door-v1", "umc-enrol-l%d" % waited); late3.sub("umcnet/v1/enrol/grant/" + dev); gone = late3.read(1.5) == []; late3.close()
    check("the grant is cleared from the broker after the repeater joins", gone, "after %d s" % waited); late2.close()
    # decline, forget, switch off
    p2, q2 = ENR.ed_keypair(os.urandom(32)); d2 = q2.hex().upper(); knock.pub("umcnet/v1/enrol/hello", hello(p2, q2, "Stranger")); time.sleep(1.5)
    e = api("/api/overview")["enrol"]; check("a second repeater waits", len(e["pending"]) == 1)
    r = api("/api/enrol/decline", {"id": d2}); e = api("/api/overview")["enrol"]; check("declining removes it and remembers it", r["ok"] and not e["pending"] and e["declined"] and e["declined"][0]["id"] == d2)
    knock.pub("umcnet/v1/enrol/hello", hello(p2, q2, "Stranger")); time.sleep(1.5)
    check("a declined repeater that knocks again is not shown again", not api("/api/overview")["enrol"]["pending"])
    r = api("/api/enrol/forget", {"id": d2}); knock.pub("umcnet/v1/enrol/hello", hello(p2, q2, "Stranger")); time.sleep(1.5)
    check("forgetting lets it ask again", r["ok"] and len(api("/api/overview")["enrol"]["pending"]) == 1)
    api("/api/enrol/decline", {"id": d2}); api("/api/enrol/forget", {"id": d2})
    api("/api/config", {"enrol_enabled": False}); knock.pub("umcnet/v1/enrol/hello", hello(p2, q2, "Stranger")); time.sleep(1.5)
    check("with enrolment switched off, requests are ignored", not api("/api/overview")["enrol"]["pending"])
    api("/api/config", {"enrol_enabled": True})
    if "--ui" in sys.argv:                                    # the dashboard screens, in a real browser
        from playwright.sync_api import sync_playwright
        k1 = ENR.ed_keypair(os.urandom(32)); keep = ENR.ed_keypair(os.urandom(32))
        knock.pub("umcnet/v1/enrol/hello", hello(k1[0], k1[1], "Hill Top")); knock.pub("umcnet/v1/enrol/hello", hello(keep[0], keep[1], "Mast Two"))
        time.sleep(2)
        with sync_playwright() as p:
            br = p.chromium.launch(); pg = br.new_page(viewport={"width": 1400, "height": 900}); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: d.accept())
            pg.goto("http://127.0.0.1:%d/#overview" % HTTP); pg.wait_for_timeout(2500)
            check("the bar says repeaters are asking to join, on every tab", "asking to join" in pg.inner_text("#enrolBar"), pg.inner_text("#enrolBar")[:60].replace(chr(10), " "))
            check("the Accounts tab carries a count", pg.inner_text('[data-t="accounts"]').strip().endswith("2"))
            pg.click('#enrolBar [data-t="accounts"]'); pg.wait_for_timeout(1200)
            pg.screenshot(path="/tmp/enrol_ui.png", full_page=False)
            ev = keep[1].hex().upper()[:12]; pg.fill("#en-" + ev, "mast-two-a"); pg.click('[data-enrol="approve"][data-id^="%s"]' % ev); pg.wait_for_timeout(2500)
            check("approving in the page shows a confirmation", "Approved" in pg.inner_text("body"), "")
            pg.click('[data-t="settings"]'); pg.wait_for_timeout(600); check("settings has the switch", "ask to join" in pg.inner_text("body"))
            check("no script errors", not errs, errs); br.close()
        api("/api/enrol/decline", {"id": k1[1].hex().upper()})
    # flood guard
    for i in range(60):
        a, b = ENR.ed_keypair(os.urandom(32)); knock.pub("umcnet/v1/enrol/hello", hello(a, b, "Spam %d" % i))
    time.sleep(4); n = len(api("/api/overview")["enrol"]["pending"]); check("a flood of requests is capped", n <= 50, str(n) + " waiting")
    au = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/audit" % HTTP, timeout=10).read()); check("approve and decline are in the audit log", any(a["action"] == "enrol approve" for a in au) and any(a["action"] == "enrol decline" for a in au))
    knock.close()
finally:
    dash.terminate(); broker.terminate(); srv.shutdown(); shutil.rmtree(D, ignore_errors=True)
print("\n%d checks, %d failed" % (len(res), res.count(False)))
sys.exit(0 if all(res) else 1)
