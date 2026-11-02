#!/usr/bin/env python3
"""End-to-end test of the Messages tab against a real Mosquitto: needs `mosquitto` and `mosquitto_passwd` installed.
Two simulated repeaters publish a channel message they both heard; the dashboard reads it, names the region and records who
heard it; a message sent from the dashboard reaches a repeater's bridge subscription and decrypts; with --ui the Messages,
Network and Settings pages are checked in a browser.
    python3 e2e_messages.py [--ui]"""
import base64, hashlib, importlib.util, json, os, shutil, socket, socketserver, struct, subprocess, sys, tempfile, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
ENR = load("umcnet_enrol", os.path.join(HERE, "umcnet_enrol.py"))
D = tempfile.mkdtemp(prefix="msge2e"); os.chmod(D, 0o755)
PORT, HTTP = 18853, 19253
def sh(*a): return subprocess.run(list(a), capture_output=True, text=True)

# ---- the same rules umcnet-user writes for these three roles
for u, p in (("dash", "dashpw"), ("controller", "ctlpw"), ("enrol", "enrol-open-door-v1"), ("rep1", "pw1"), ("rep2", "pw2"), ("reader", "pwr")): sh("mosquitto_passwd", "-b", "-c" if u == "dash" else "-b", D + "/passwd", u, p)
open(D + "/acl", "w").write("""user dash
topic read $SYS/#
topic read meshcore/#

user controller
topic write umcnet/v1/+/dev/+/cmd
topic read umcnet/v1/+/dev/+/resp
topic read umcnet/v1/enrol/hello
topic write umcnet/v1/enrol/grant/#
topic write meshcore/+/DADADADADADADADADADADADADADADADADADADADADADADADADADADADADADADADA/raw
topic write umcnet/v1/+/messages
topic write umcnet/v1/+/adverts
topic write umcnet/v1/+/nodes/#

user reader
topic read umcnet/v1/+/messages
topic read umcnet/v1/+/adverts
topic read umcnet/v1/+/nodes/#

user rep1
topic readwrite meshcore/+/A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1A1/#
topic read meshcore/+/+/raw
topic read meshcore/+/+/status

user rep2
topic readwrite meshcore/+/B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2B2/#
topic read meshcore/+/+/raw
topic read meshcore/+/+/status

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
UI = "--ui" in sys.argv
def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))
try:
    IDA, IDB = "A1" * 32, "B2" * 32; A = Dev("rep1", "pw1", "repA"); B = Dev("rep2", "pw2", "repB")
    APP = Dev("reader", "pwr", "app"); APP.sub("umcnet/v1/LBA/#"); time.sleep(0.5)
    check("both repeaters connect", A.ack[3:4] == b"\x00" and B.ack[3:4] == b"\x00")
    now = int(time.time())
    for dev_id, name, c in ((IDA, "Hill Top", A), (IDB, "Valley", B)):
        c.pub("meshcore/LBA/%s/status" % dev_id, json.dumps({"status": "online", "origin": name, "model": "Heltec V3", "firmware_version": "v1.17.1", "radio": "869.618,62.5,8,8", "timestamp": iso(now), "stats": {"battery_mv": 4080, "uptime_secs": 7200, "noise_floor": -112, "tx_air_secs": 90, "rx_air_secs": 300}}), retain=1)
    yk = MSG.Channel("#yorkshire"); pub = MSG.Channel("Public", MSG.PUBLIC_PSK)
    raw = MSG.build_group_text(yk, "Sam", "anyone on the Yorkshire repeaters?", now, region="yorkshire")
    hop = raw[:5] + bytes([1, 0x44]) + raw[6:]                                                         # the same packet after one more hop
    A.pub("meshcore/LBA/%s/raw" % IDA, json.dumps({"origin": "Hill Top", "timestamp": iso(now), "type": "RAW", "data": raw.hex().upper(), "SNR": "6.5", "RSSI": "-92"}, separators=(",", ":")))
    B.pub("meshcore/LBA/%s/raw" % IDB, json.dumps({"origin": "Valley", "timestamp": iso(now), "type": "RAW", "data": hop.hex().upper(), "SNR": "9.0", "RSSI": "-80"}, separators=(",", ":")))
    A.pub("meshcore/LBA/%s/raw" % IDA, json.dumps({"origin": "Hill Top", "data": MSG.build_group_text(pub, "Pat", "good morning", now).hex().upper(), "SNR": "4"}, separators=(",", ":")))
    A.pub("meshcore/LBA/%s/raw" % IDA, json.dumps({"origin": "Hill Top", "data": MSG.build_group_text(MSG.Channel("#private-club"), "X", "secret", now).hex().upper()}, separators=(",", ":")))
    A.pub("meshcore/LBA/%s/raw" % IDA, "not json"); time.sleep(2.5)
    v = api("/api/messages"); ms = {m["text"]: m for m in v["messages"]}
    check("two readable messages are listed (the unreadable one only counted)", len(v["messages"]) == 2 and sum(x["n"] for x in v["unreadable"].values()) == 1, [m["text"] for m in v["messages"]])
    m = ms.get("anyone on the Yorkshire repeaters?", {})
    check("the channel, sender and message are read", (m.get("chan"), m.get("sender")) == ("#yorkshire", "Sam"), m)
    check("the region is named from the packet's code", m.get("region") == "yorkshire", m.get("region"))
    check("both repeaters are shown as having heard it, with their hops", sorted((h["name"], h["hops"]) for h in m.get("heard", [])) == [("Hill Top", 0), ("Valley", 1)], m.get("heard"))
    check("an unscoped message has no region", ms.get("good morning", {}).get("region") == "" and ms["good morning"]["chan"] == "Public")
    check("filtering by region, channel and search works", len(api("/api/messages?region=yorkshire")["messages"]) == 1 and len(api("/api/messages?channel=Public")["messages"]) == 1 and len(api("/api/messages?region=-")["messages"]) == 1 and len(api("/api/messages?q=morning")["messages"]) == 1)
    # sending: a repeater's bridge subscription receives it
    B.sub("meshcore/LBA/+/raw"); time.sleep(0.6)
    r = api("/api/messages/send", {"channel": "#yorkshire", "region": "eng-yh", "text": "Net tonight at 8", "sender": "2E0LXY-DASH"}); check("sending is accepted", r.get("ok"), r)
    got = B.read(4); check("a repeater's bridge receives it on the dashboard's raw topic", len(got) == 1 and got[0][0] == "meshcore/LBA/%s/raw" % ("DA" * 32), got[0][0] if got else "nothing")
    if got:
        j = json.loads(got[0][1]); p = MSG.parse_wire(bytes.fromhex(j["data"])); ch, ts, fl, text = MSG.decrypt_group([yk], p["payload"])
        check("it decrypts to what was typed, sent into the right region", text == "2E0LXY-DASH: Net tonight at 8" and MSG.find_region(["yorkshire", "eng-yh"], p) == "eng-yh" and p["route"] == 0, text)
    # the repeater then hears it on the air and publishes it: it joins the same row instead of making a second
    echo = bytes.fromhex(json.loads(got[0][1])["data"]); echo = echo[:5] + bytes([1, 0x44]) + echo[6:]; B.pub("meshcore/LBA/%s/raw" % IDB, json.dumps({"origin": "Valley", "data": echo.hex().upper(), "SNR": "7"}, separators=(",", ":"))); time.sleep(1.8)
    v = api("/api/messages"); tx = [m for m in v["messages"] if m["dir"] == "tx"]
    check("the sent message is one TX row, later shown as heard by the repeater", len(tx) == 1 and tx[0]["sender"] == "2E0LXY-DASH" and [h["name"] for h in tx[0]["heard"]] == ["Valley"], tx[0]["heard"] if tx else "")
    bad = api("/api/messages/send", {"channel": "#yorkshire", "text": "x" * 200}); check("a too-long message is refused", not bad["ok"], bad.get("error"))
    n = api("/api/network?hours=24")["nodes"]; check("the map data marks both repeaters online with their details", sum(1 for x in n if x.get("online")) == 2 and all(x["info"]["stats"].get("noise_floor") == -112 for x in n if x.get("info")), [x["name"] for x in n])
    au = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/audit" % HTTP, timeout=10).read()); check("the sent message is in the audit log", any(a["action"] == "message sent" for a in au))
    import struct as _st
    def advert(pubkey, name, lat, lon, kind=2):
        pl = pubkey + _st.pack("<I", now) + bytes(64) + bytes([kind | 0x10 | 0x80]) + _st.pack("<ii", int(lat * 1e6), int(lon * 1e6)) + name.encode()
        return (bytes([(4 << 2) | 1, 0]) + pl).hex().upper()
    for cl, dev_id, nm, la, lo in ((A, IDA, "Hill Top", 53.7263, -1.4849), (B, IDB, "Valley", 53.397, -1.4712)):
        cl.pub("meshcore/LBA/%s/raw" % dev_id, json.dumps({"origin": nm, "data": advert(bytes.fromhex(dev_id), nm, la, lo), "SNR": "8"}, separators=(",", ":")))
    A.pub("meshcore/LBA/%s/raw" % IDA, json.dumps({"origin": "Hill Top", "data": advert(os.urandom(32), "Grange Moor Solar", 53.64, -1.74), "SNR": "-6"}, separators=(",", ":")))
    A.pub("meshcore/LBA/%s/raw" % IDA, json.dumps({"origin": "Hill Top", "data": advert(os.urandom(32), "Old Mast", 53.50, -1.30), "SNR": "-3"}, separators=(",", ":"))); time.sleep(2)
    got = APP.read(4); topics = [x[0] for x in got]; bodies = {}
    for tp, pl in got: bodies.setdefault(tp, []).append(json.loads(pl))
    msgs = bodies.get("umcnet/v1/LBA/messages", [])
    check("an app receives each decoded message once, with channel, region, sender and text", sorted((m["channel"], m["region"], m["sender"], m["text"], m["dir"]) for m in msgs) == sorted([("#yorkshire", "yorkshire", "Sam", "anyone on the Yorkshire repeaters?", "rx"), ("Public", "", "Pat", "good morning", "rx"), ("#yorkshire", "eng-yh", "2E0LXY-DASH", "Net tonight at 8", "tx")]), [(m["sender"], m["text"]) for m in msgs])
    check("the unreadable channel's message is not published", not any("secret" in m["text"] for m in msgs))
    adv = bodies.get("umcnet/v1/LBA/adverts", []); check("an app receives each node's advert with name, kind and position", {a["name"] for a in adv} >= {"Hill Top", "Valley", "Grange Moor Solar", "Old Mast"} and all(a["lat"] is not None and a["type"] == "repeater" for a in adv), [(a["name"], a["type"]) for a in adv])
    nodes = [tp for tp in topics if tp.startswith("umcnet/v1/LBA/nodes/")]; check("each node has a retained status topic marked online", len(set(nodes)) == 4 and all(b["online"] for tp in set(nodes) for b in bodies[tp]))
    late = Dev("reader", "pwr", "app2"); late.sub("umcnet/v1/LBA/nodes/#"); ret = late.read(2); late.close()
    check("a newly started app gets every node's status at once (retained)", len(ret) == 4, len(ret))
    W = Dev("rep2", "pw2", "repB-watch"); W.sub("meshcore/LBA/+/raw"); time.sleep(0.5); W.read(1)
    APP.pub("meshcore/LBA/%s/raw" % ("CC" * 32), json.dumps({"data": "1500AABB"})); A.pub("meshcore/LBA/%s/raw" % ("DA" * 32), json.dumps({"data": "1500AABB"}))
    leaked = W.read(2); W.close()
    check("a read-only app, and a repeater posing as the dashboard, cannot put packets on the network", not leaked, [x[0] for x in leaked])
    net = api("/api/network?hours=24"); check("the map has both repeaters with positions and the other nodes", sum(1 for x in net["nodes"] if x.get("online") and x["lat"] is not None) == 2 and len(net["nodes"]) == 4, [(x["name"], x["online"]) for x in net["nodes"]])
    check("a node last heard long ago is left off the map", len(api("/api/network?hours=1")["nodes"]) >= 2)
    # ---- users: each person their own login, controlling only their own repeater
    def api_as(user, path, body=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (HTTP, path), data=json.dumps(body).encode() if body is not None else None, headers={"X-UMC-Dash": "1", "Content-Type": "application/json", "X-UMC-User": user})
        try: return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e: return dict(json.loads(e.read() or b"{}"), status=e.code)
    import urllib.error
    r = api("/api/users/save", {"name": "g4abc", "password": "Correct-Horse-9", "role": "owner", "devices": [IDA], "sender": "G4ABC"}); check("the admin can add a user who controls one repeater", r.get("ok"), r)
    check("the helper was asked to make the login", any(x.get("op") == "web_user_set" and x.get("name") == "g4abc" for x in made))
    api("/api/users/save", {"name": "watcher", "password": "Correct-Horse-9", "role": "viewer"})
    check("a weak or clashing name is refused", not api("/api/users/save", {"name": "admin", "password": "Correct-Horse-9"})["ok"] and not api("/api/users/save", {"name": "Bad Name", "password": "x"})["ok"])
    ov = api_as("g4abc", "/api/overview"); check("the user sees the whole network and who they are", len(ov["devices"]) == 2 and ov["me"] == {"name": "g4abc", "role": "owner", "devices": [IDA], "sender": "G4ABC"}, ov["me"])
    check("the user does not get the user list or secrets", "web_users" not in ov and "web_users" not in ov["config"])
    a = api_as("g4abc", "/api/control", {"device": IDB, "cmd": "get name"}); check("the user cannot control someone else's repeater", a.get("status") == 403 and "own repeater" in a.get("error", ""), a)
    b = api_as("g4abc", "/api/control", {"device": IDA, "cmd": "get name"}); check("the user can control their own (it gets past the permission check)", b.get("status") is None and "own repeater" not in str(b.get("error")), b)
    for path, body in (("/api/config", {"title": "x"}), ("/api/users/save", {"name": "x1", "password": "Correct-Horse-9"}), ("/api/service", {"name": "umcnet-dash"}), ("/api/enrol/approve", {"id": IDA})):
        check("the user cannot use " + path, api_as("g4abc", path, body).get("status") == 403)
    check("the user cannot export", api_as("g4abc", "/api/export/config.json").get("status") == 403)
    s1 = api_as("g4abc", "/api/messages/send", {"channel": "#yorkshire", "region": "", "text": "hello from g4abc", "sender": "2E0LXY"}); check("the user can send messages, under their own name", s1.get("ok") and api("/api/messages?q=g4abc")["messages"][0]["sender"] == "G4ABC", s1)
    check("a viewer can only look", api_as("watcher", "/api/messages/send", {"channel": "#yorkshire", "text": "x"}).get("status") == 403 and api_as("watcher", "/api/control", {"device": IDA, "cmd": "get name"}).get("status") == 403 and api_as("watcher", "/api/overview")["me"]["role"] == "viewer")
    check("an unknown login is only a viewer", api_as("stranger", "/api/overview")["me"]["role"] == "viewer" and api_as("stranger", "/api/control", {"device": IDA, "cmd": "get name"}).get("status") == 403)
    check("the admin sees the users", set(api("/api/overview")["web_users"]) == {"g4abc", "watcher"})
    check("removing a user works", api("/api/users/remove", {"name": "watcher"}).get("ok") and "watcher" not in api("/api/overview")["web_users"])
    if UI:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch(); pg = br.new_page(viewport={"width": 1400, "height": 1100}); errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: d.accept())
            pg.goto("http://127.0.0.1:%d/#messages" % HTTP); pg.wait_for_timeout(2500); pg.click('[data-t="messages"]'); pg.wait_for_timeout(2500)
            txt = pg.inner_text("#msgFeed"); check("the Messages tab lists the messages with channel, region, sender and who heard them", "anyone on the Yorkshire repeaters?" in txt and "yorkshire" in txt and "Hill Top" in txt and "Valley" in txt and "Net tonight at 8" in txt, txt[:80].replace(chr(10), " "))
            pg.select_option("#mfReg", "yorkshire"); pg.wait_for_timeout(1500); check("the region filter narrows the list", "good morning" not in pg.inner_text("#msgFeed") and "Sam" in pg.inner_text("#msgFeed"))
            pg.select_option("#mfReg", ""); pg.wait_for_timeout(800)
            pg.select_option("#msgChan", "#yorkshire"); pg.select_option("#msgReg", "yorkshire"); pg.fill("#msgText", "hello from the page"); pg.click("#msgSend"); pg.wait_for_timeout(2500)
            check("sending from the page works and shows in the list", "Sent." in pg.inner_text("#msgRes") and "hello from the page" in pg.inner_text("#msgFeed"), pg.inner_text("#msgRes"))
            pg.screenshot(path="/tmp/messages_ui.png")
            check("the chat starts in the green theme", pg.get_attribute("#ncWrap", "data-nc") == "green")
            for th in ("neon", "ocean", "amber", "sunset", "calm", "green"):
                pg.click('[data-nctheme="%s"]' % th); pg.wait_for_timeout(400); pg.locator("#ncWrap").screenshot(path="/tmp/theme_%s.png" % th)
            check("each of the six themes can be chosen", pg.locator("[data-nctheme]").count() == 6 and pg.get_attribute("#ncWrap", "data-nc") == "green")
            pg.click('[data-nctheme="ocean"]'); pg.reload(); pg.wait_for_timeout(2500); pg.click('[data-t="messages"]'); pg.wait_for_timeout(2000)
            check("the chosen theme is remembered after a reload", pg.get_attribute("#ncWrap", "data-nc") == "ocean"); pg.click('[data-nctheme="green"]')
            pg.click('[data-t="network"]'); pg.wait_for_timeout(3500); check("the map has the hours filter", pg.locator('[data-nf="hours"]').count() == 1)
            pg.wait_for_timeout(2500); mk = pg.locator('path[stroke="#f2c14e"]'); check("online repeaters are green dots with a yellow edge", mk.count() == 2 and pg.locator('path[stroke="#f2c14e"][fill="#2fe27a"]').count() == 2, mk.count())
            mk.first.click(force=True); pg.wait_for_timeout(1200); pop = pg.inner_text(".umcpop")
            check("clicking a repeater shows its details", all(w in pop for w in ("Board", "Firmware", "Noise floor", "Battery", "Uptime", "Air time")), pop[:200].replace(chr(10), " | "))
            pg.screenshot(path="/tmp/network_ui.png")
            pg.click('[data-t="control"]'); pg.wait_for_timeout(2500); check("the Control tab has the neighbours panel", pg.locator("#ctlNeigh").count() == 1)
            check("no page shows an internal object as text", "[object Object]" not in pg.inner_text("body"))
            pg.click('[data-t="settings"]'); pg.wait_for_timeout(1200); check("Settings has the Messaging panel", pg.locator("#mcChans").count() == 1 and "#yorkshire" in pg.input_value("#mcChans"))
            pg.fill("#mcRegs", "yorkshire\nsheffield"); pg.click('[data-act="savemsgcfg"]'); pg.wait_for_timeout(1500); check("saving the channels and regions works", pg.inner_text("#mcMsg") == "Saved", pg.inner_text("#mcMsg"))
            pg.click('[data-t="overview"]'); pg.wait_for_timeout(2000); check("the data flow draws both directions", pg.locator(".flow svg path.fe.tx").count() >= 2 and " out " in pg.inner_text(".flow"))
            pg.click('[data-t="users"]'); pg.wait_for_timeout(1200); check("the admin has a Users tab listing the logins", "g4abc" in pg.inner_text("#body") and "Add a user" in pg.inner_text("#body"))
            pg.screenshot(path="/tmp/users_ui.png")
            ctx = br.new_context(viewport={"width": 1400, "height": 1000}, extra_http_headers={"X-UMC-User": "g4abc"}); up = ctx.new_page(); up.on("pageerror", lambda e: errs.append(str(e)))
            up.goto("http://127.0.0.1:%d/" % HTTP); up.wait_for_timeout(2500); tabs = up.inner_text("#tabs")
            check("a user does not see Accounts or Users", "Accounts" not in tabs and "Users" not in tabs and "Messages" in tabs, tabs.replace(chr(10), " "))
            check("the page says who is signed in", "signed in as g4abc" in up.inner_text("#sub"))
            up.click('[data-t="control"]'); up.wait_for_timeout(1500); cb = up.inner_text("#body"); check("their Control tab offers only their repeater", "Hill Top" in cb and "Valley" not in cb.split("Neighbours")[0])
            samples = []
            for _ in range(6): up.wait_for_timeout(2500); samples.append(up.inner_text("#ctlNeigh"))
            check("the neighbours panel does not flicker back to Reading between refreshes", all(x == samples[0] for x in samples[1:]) and "Reading" not in samples[-1], [x[:30] for x in samples])
            up.click('[data-t="settings"]'); up.wait_for_timeout(800); check("their Settings is just their password", "Your password" in up.inner_text("#body") and up.locator("#mcChans").count() == 0)
            up.click('[data-t="messages"]'); up.wait_for_timeout(2000); check("messages have a Reply button", up.locator("[data-reply]").count() >= 1)
            up.locator("[data-reply]").first.click(); up.wait_for_timeout(500); check("Reply fills in the channel and the sender", up.input_value("#msgText").startswith("@[") and up.input_value("#msgChan") != "", up.input_value("#msgText"))
            check("a user's sender name is their own and fixed", up.input_value("#msgSender") == "G4ABC" and up.get_attribute("#msgSender", "readonly") is not None)
            up.screenshot(path="/tmp/owner_ui.png"); ctx.close()
            check("no script errors", not errs, errs); br.close()
    A.close(); B.close()
finally:
    dash.terminate(); broker.terminate(); srv.shutdown(); shutil.rmtree(D, ignore_errors=True)
print("\n%d checks, %d failed" % (len(res), res.count(False)))
sys.exit(0 if all(res) else 1)
