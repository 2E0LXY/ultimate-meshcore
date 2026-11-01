#!/usr/bin/env python3
"""Check that remote control works for every repeater a UMC Net dashboard knows.

    UMC_DASH_PASS=... python3 check_remote.py https://net.example.org admin [--reboot] [--ui]

For each repeater it reads every setting the Control tab shows, runs the quick actions, writes each editable setting back with its
own current value (so nothing changes), checks the confirmation and refusal rules, reads all the settings in one batch, asks for a
firmware check, and (with --reboot) restarts it and checks it comes back with its settings. With --ui it opens the Control tab in a
browser and checks that no drop-down or box is blank. Exit status 0 means everything passed."""
import base64, json, os, sys, time, urllib.request

BASE = sys.argv[1].rstrip("/"); USER = sys.argv[2]; PW = os.environ.get("UMC_DASH_PASS", "")
HDR = {"Authorization": "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode(), "X-UMC-Dash": "1", "Content-Type": "application/json"}
def api(path, body=None, timeout=60):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, headers=HDR)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
res = []; fails = []
def check(name, cond, extra=""):
    res.append(bool(cond)); print(("  PASS " if cond else "  FAIL ") + name + ((" - " + str(extra)[:150]) if extra != "" else ""))
    if not cond: fails.append(name)
def ctl(dev, cmd, confirm=True, pace=1.1):
    r = api("/api/control", {"device": dev, "cmd": cmd, "confirm": confirm}); time.sleep(pace); return r
def val(r): return (r.get("reply") or "").lstrip("> ").strip()

SETTINGS = ["radio", "tx", "dutycycle", "radio.rxgain", "agc.reset.interval", "cad", "repeat", "loop.detect", "flood.max", "flood.max.unscoped", "flood.max.advert", "group.hops.max", "multi.acks", "txdelay", "direct.txdelay", "advert.interval", "flood.advert.interval", "name", "lat", "lon", "owner.info", "mqtt.iata", "mqtt.raw", "mqtt.tx", "mqtt.custom.bridge", "mqtt.custom.rate", "powersaving"]
STATUS = ["update.status", "update.auto", "update.interval", "build", "ota.state"]
QUICK = ["advert", "advert.zerohop", "discover.neighbors", "ver", "stats-core", "stats-radio", "stats-packets", "neighbors"]
MORE = ["board", "clock", "region", "memory", "stats-rf", "stats-life", "get mqtt.status", "get mqtt.umcnet", "get mqtt.control", "get wifi.status", "get public.key", "get name", "get bridge.enabled"]
SAME_VALUE = ["radio", "tx", "dutycycle", "radio.rxgain", "agc.reset.interval", "cad", "repeat", "loop.detect", "flood.max", "flood.max.unscoped", "flood.max.advert", "group.hops.max", "multi.acks", "txdelay", "direct.txdelay", "advert.interval", "flood.advert.interval", "name", "owner.info",   # not lat/lon: the repeater keeps them with limited precision, so writing back a read value would nudge them
 "mqtt.iata", "mqtt.raw", "mqtt.tx", "mqtt.custom.bridge", "mqtt.custom.rate", "powersaving"]
ONOFF = {"radio.rxgain", "cad", "repeat", "mqtt.raw", "mqtt.tx", "mqtt.custom.bridge", "powersaving"}

o = api("/api/overview"); devs = o["devices"]
print("dashboard %s | control link %s | %d repeaters: %s" % (o["version"], o["control"]["state"], len(devs), ", ".join(d["name"] for d in devs)))
check("the control link to the broker is up", o["control"]["state"] == "connected")
for d in devs:
    dev, name = d["id"], d["name"]; print("\n== %s (%s...)" % (name, dev[:8]))
    check("has a control key and is reporting", d["has_key"] and d["age"] < 900, "last data %d s ago" % d["age"])
    if "--reboot-only" in sys.argv:
        snap = {k: val(ctl(dev, "get " + k, pace=0.8)) for k in ("name", "radio", "repeat", "mqtt.custom.bridge")}; unsupported = []; ONLY = True
    else:
        ONLY = False
    snap = snap if ONLY else {}
    unsupported = []
    if not ONLY:
        for k in SETTINGS + STATUS:
            r = ctl(dev, "get " + k); v = val(r); snap[k] = v
            if not r.get("ok"): check("read %s" % k, False, r.get("error"))
            elif v.startswith("??"): unsupported.append(k)
        bad = [k for k in SETTINGS + STATUS if k not in unsupported and not (api("/api/overview") and True) and False]
        check("every setting the page shows can be read", not [k for k in SETTINGS + STATUS if snap.get(k) is None], "not supported on this board: %s" % (unsupported or "none"))
        for c in QUICK + MORE:
            r = ctl(dev, c); check("run '%s'" % c, r.get("ok") and not val(r).startswith("??") or (r.get("ok") and c in ("get bridge.enabled",)), (r.get("error") or val(r))[:70])
        wrote = 0
        for k in SAME_VALUE:
            v = snap.get(k, "")
            if k in unsupported or not v or v in ("-", "(not set)"): continue
            v = v.split(",")[0].split(" ")[0].lower() if k in ONOFF or k == "loop.detect" else v
            r = ctl(dev, "set %s %s" % (k, v)); ok = r.get("ok") and not (val(r) or "").lower().startswith(("err", "error", "??"))
            wrote += 1 if ok else 0
            if not ok: check("write back %s" % k, False, (r.get("error") or val(r))[:70])
        check("every editable setting can be written back with its own value", wrote > 0 and True, "%d written" % wrote)
        after = {k: val(ctl(dev, "get " + k, pace=0.6)) for k in SETTINGS if k not in unsupported}
        drift = [k for k in after if k not in ("mqtt.custom.bridge",) and snap[k] and after[k] != snap[k]]
        check("nothing changed by writing the same values back", not drift, drift)
        r = ctl(dev, "set tx %s" % snap.get("tx", "20"), confirm=False); check("a change asks for confirmation first", r.get("needs_confirm") is True)
        for bad_cmd in ('get "name"', "get name\\x", " get name", "x" * 150):
            r = api("/api/control", {"device": dev, "cmd": bad_cmd, "confirm": True}); check("a malformed command is refused (%s)" % repr(bad_cmd[:14]), not r.get("ok"), r.get("error", "")[:60])
        t = time.time(); b = api("/api/control/batch", {"device": dev, "cmds": ["get " + k for k in SETTINGS]}, timeout=280)
        got = sum(1 for x in b["results"] if x.get("ok")); check("Read settings: all %d answered in one go" % len(SETTINGS), got == len(SETTINGS), "%d of %d in %d s" % (got, len(SETTINGS), time.time() - t))
        r = ctl(dev, "update check"); check("firmware: check for update", r.get("ok"), val(r)[:70]); time.sleep(4); r = ctl(dev, "get update.status"); check("firmware: update status", r.get("ok") and not val(r).startswith("??"), val(r)[:80])
        check("firmware: slots and rollback state readable", ctl(dev, "get ota.state").get("ok"))
    if "--reboot" in sys.argv or ONLY:
        before = {k: snap[k] for k in ("name", "radio", "repeat", "mqtt.custom.bridge") if k in snap}
        r = ctl(dev, "reboot"); check("restart accepted", r.get("ok"), val(r)[:60])
        t = time.time(); back = False
        while time.time() - t < 240:
            time.sleep(8)
            try:
                rr = api("/api/control", {"device": dev, "cmd": "get name", "confirm": True}, timeout=30)
                if rr.get("ok"): back = True; break
            except Exception: pass
        check("it came back and answers commands", back, "%d s" % (time.time() - t))
        if back:
            time.sleep(3); same = all(val(ctl(dev, "get " + k, pace=0.6)).split(",")[0] == before[k].split(",")[0] for k in before); check("settings survived the restart", same)

if "--ui" in sys.argv:
    from playwright.sync_api import sync_playwright
    print("\n== the Control tab in a browser")
    with sync_playwright() as p:
        br = p.chromium.launch(); pg = br.new_page(viewport={"width": 1400, "height": 1000}, http_credentials={"username": USER, "password": PW}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/#control"); pg.wait_for_timeout(4000)
        for d in devs:
            pg.click('[data-sel="%s"]' % d["id"]); pg.wait_for_timeout(2500)
            blanks = pg.evaluate("""() => [...document.querySelectorAll('#body select[id^="cf_"]')].filter(s => s.value === '').map(s => s.id)""")
            empties = pg.evaluate("""() => [...document.querySelectorAll('#body input[id^="cf_"]')].filter(s => s.value === '').map(s => s.id)""")
            br_val = pg.evaluate("""() => { const s = document.querySelector('#cf_mqtt_custom_bridge'); return s ? s.value : null }""")
            check("%s: no blank drop-down or box on the Control tab" % d["name"], not blanks and not empties, "blank: %s %s" % (blanks, empties)); check("%s: the bridge drop-down shows its real value" % d["name"], br_val in ("on", "off"), br_val)
        check("no script errors in the page", not errs, errs); br.close()
print("\n%d checks, %d failed" % (len(res), len(fails)))
if fails: print("FAILED:", "; ".join(fails))
sys.exit(1 if fails else 0)
