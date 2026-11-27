"""Tests for the dashboard service and its admin helper. Run: python3 -m unittest -v test_dash   (no broker needed)"""
import importlib.util, json, os, re, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file)); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
os.environ["DASH_DATA"] = tempfile.mkdtemp()
dash = load("umcnet_dash", "umcnet_dash.py")
adm = load("umcnet_admin", "umcnet_admin.py")
import base64, importlib.machinery
_ldr = importlib.machinery.SourceFileLoader("umcnet_user", os.path.join(HERE, "..", "umcnet-user"))
_spec = importlib.util.spec_from_loader("umcnet_user", _ldr); usr = importlib.util.module_from_spec(_spec); _ldr.exec_module(usr)


class ClientAccount(unittest.TestCase):
    ID = "0123456789ABCDEF" * 4

    def decode(self, code):
        self.assertTrue(code.startswith("umcclient1:"))
        b = code[len("umcclient1:"):]
        self.assertNotIn("=", b)
        return json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))

    def test_client_id_is_64_uppercase_hex_and_random(self):
        a, b = usr.new_client_id(), usr.new_client_id()
        self.assertRegex(a, r"^[0-9A-F]{64}$"); self.assertNotEqual(a, b)

    def test_acl_writes_only_under_its_own_id(self):
        acl = usr.acl_for("phone", {"role": "client", "device": self.ID}).splitlines()
        self.assertEqual("user phone", acl[0])
        self.assertEqual(["topic write meshcore/+/%s/raw" % self.ID, "topic write meshcore/+/%s/status" % self.ID, "topic write umcnet/v1/+/replay/req/%s" % self.ID], [l for l in acl if l.startswith("topic write")])
        self.assertIn("topic read umcnet/v1/+/replay/%s" % self.ID, acl)
        self.assertFalse([l for l in acl if "readwrite" in l or "umcnet/v1" in l and "write" in l and "replay/req/%s" % self.ID not in l])
        ctl = usr.acl_for("controller", {"role": "controller"}).splitlines()
        self.assertIn("topic read umcnet/v1/+/replay/req/+", ctl); self.assertIn("topic write umcnet/v1/+/replay/#", ctl)
        for l in ("topic read meshcore/+/+/raw", "topic read meshcore/+/+/packets", "topic read meshcore/+/+/status"): self.assertIn(l, acl)

    def test_blocked_client_gets_nothing_and_viewer_stays_read_only(self):
        self.assertEqual("user phone", usr.acl_for("phone", {"role": "client", "device": self.ID, "state": "blocked"}))
        self.assertNotIn("topic write", usr.acl_for("v", {"role": "viewer", "device": self.ID}))
        self.assertNotIn("topic write", usr.acl_for("phone", {"role": "client"}))      # no id, no writing

    def test_setup_code_round_trip_in_both_implementations(self):
        for fn in (usr.setup_code, dash.make_setup_code):
            c = fn("net.2e0lxy.uk", "phone-1", "Zq9_-Aa8Bb7Cc6Dd5Ee4", self.ID, "LBA")
            self.assertEqual({"h": "net.2e0lxy.uk", "u": "phone-1", "p": "Zq9_-Aa8Bb7Cc6Dd5Ee4", "i": self.ID, "a": "LBA"}, self.decode(c))
        self.assertEqual(usr.setup_code("net.2e0lxy.uk", "phone-1", "Zq9_-Aa8Bb7Cc6Dd5Ee4", self.ID, "LBA"), dash.make_setup_code("net.2e0lxy.uk", "phone-1", "Zq9_-Aa8Bb7Cc6Dd5Ee4", self.ID, "LBA"))

    def test_dash_refuses_bad_setup_inputs(self):
        for args in (("net.2e0lxy.uk", "phone-1", "short", self.ID, "LBA"), ("net.2e0lxy.uk", "phone-1", "longenough1", self.ID.lower(), "LBA"),
                     ("net.2e0lxy.uk", "phone-1", "longenough1", self.ID, "lba"), ("bad host", "phone-1", "longenough1", self.ID, "LBA")):
            with self.assertRaises(ValueError): dash.make_setup_code(*args)

    def test_client_id_is_read_from_the_tool_output(self):
        self.assertEqual(self.ID, dash.client_id_of("phone (client) password: abc\nphone client id: %s\nphone setup code: umcclient1:x" % self.ID))
        self.assertEqual("", dash.client_id_of("nothing"))

    def test_password_is_still_found_in_the_tool_output(self):
        out = "phone (client) password: Abc_123xyz\nphone client id: %s\n" % self.ID
        self.assertEqual("Abc_123xyz", re.search(r"password: (\S+)", out)[1])


class EnrolAsClient(unittest.TestCase):
    """Approving a pending request as a client: a client account bound to the id, and a grant that opens to the setup code."""
    def setUp(self):
        sp = importlib.util.spec_from_file_location("umcnet_enrol2", os.path.join(HERE, "umcnet_enrol.py"))
        self.E = importlib.util.module_from_spec(sp); sp.loader.exec_module(self.E)
        self.prv, self.pub = self.E.ed_keypair(os.urandom(32)); self.dev = self.pub.hex().upper()
        self.pub_msgs = []; self.calls = []; self.accts = []
        class Conn:
            up = True
            def publish(s, t, p, retain=False): outer.pub_msgs.append((t, p, retain))
        outer = self
        self._ck = dash.control_key
        self._saved = (dash.admin_call, dash.accounts, dash.CTL.get("conn"), dash.enrol_save, dash.export_accounts_soon, dash.audit)
        def fake_admin(**req):
            self.calls.append(req); return {"ok": True, "password": "Zq9_-Aa8Bb7Cc6Dd5Ee4", "output": ""}
        dash.admin_call = fake_admin; dash.accounts = lambda: self.accts; dash.CTL["conn"] = Conn()
        dash.enrol_save = lambda: None; dash.export_accounts_soon = lambda: None; dash.audit = lambda *a, **k: None
        dash.ENROL["pending"][self.dev] = {"id": self.dev, "name": "My Phone", "first": 1, "last": 1, "count": 1}

    def tearDown(self):
        dash.admin_call, dash.accounts, conn, dash.enrol_save, dash.export_accounts_soon, dash.audit = self._saved
        dash.control_key = self._ck; dash.CTL["conn"] = conn; dash.ENROL["pending"].pop(self.dev, None); dash.ENROL["approved"].pop(self.dev, None)

    def test_client_approval_makes_a_client_account_and_a_setup_code_grant(self):
        r = dash.enrol_approve("admin", self.dev, role="client")
        self.assertTrue(r["ok"]); self.assertEqual("client", r["role"])
        self.assertEqual([{"op": "user_add", "name": r["account"], "role": "client", "device": self.dev}], self.calls)
        (topic, payload, retain), = self.pub_msgs
        self.assertEqual("umcnet/v1/enrol/grant/" + self.dev, topic); self.assertTrue(retain)
        code = self.E.open_grant(self.prv, self.dev, payload.decode())
        self.assertTrue(code.startswith("umcclient1:"))
        b = code[len("umcclient1:"):]
        self.assertEqual({"h": dash.CFG["host"], "u": r["account"], "p": "Zq9_-Aa8Bb7Cc6Dd5Ee4", "i": self.dev, "a": dash.CONF["join_iata"]}, json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))))
        self.assertNotIn(self.dev, dash.ENROL["pending"]); self.assertEqual(r["account"], dash.ENROL["approved"][self.dev]["account"])
        acl = usr.acl_for(r["account"], {"role": "client", "device": self.dev})
        self.assertIn("topic write meshcore/+/%s/raw" % self.dev, acl)

    def test_repeater_approval_is_unchanged(self):
        dash.control_key = lambda dev, create=False: "00" * 32
        r = dash.enrol_approve("admin", self.dev)
        self.assertTrue(r["ok"]); self.assertEqual("repeater", self.calls[0]["role"])
        self.assertTrue(self.E.open_grant(self.prv, self.dev, self.pub_msgs[0][1].decode()).startswith("UMC1."))

    def test_an_existing_account_of_the_other_role_is_not_overwritten(self):
        self.accts.append({"name": "hill", "role": "repeater", "device": self.dev})
        self.assertFalse(dash.enrol_approve("admin", self.dev, role="client")["ok"]); self.assertEqual([], self.calls)
        self.assertFalse(dash.enrol_approve("admin", self.dev, role="admin")["ok"])


class Signing(unittest.TestCase):
    def test_matches_the_firmware_vector(self):
        # the same key and message as test/test_control_cmd: computed there in C++ and here in Python
        self.assertEqual("0ff5cfafea5254364a79e937d3c60436f646b719874ad461c0be4ff6cab7a983", dash.sign(bytes(range(32)).hex(), "756C3D39", 1760000000, 1760000000123, "get radio"))

    def test_any_change_changes_the_signature(self):
        k = "ab" * 32; base = dash.sign(k, "AA", 1, 2, "get tx")
        for other in (dash.sign(k, "AB", 1, 2, "get tx"), dash.sign(k, "AA", 2, 2, "get tx"), dash.sign(k, "AA", 1, 3, "get tx"), dash.sign(k, "AA", 1, 2, "get tx "), dash.sign("cd" * 32, "AA", 1, 2, "get tx")):
            self.assertNotEqual(base, other)


class CommandList(unittest.TestCase):
    ALLOWED = ["get radio", "get tx", "set tx 20", "set radio 869.618,62.5,8,8", "advert", "advert.zerohop", "reboot", "ver", "neighbors", "set flood.max 20", "set loop.detect minimal",
               "set mqtt.custom.bridge on", "set mqtt.custom.rate 20", "set mqtt.raw on", "region put gb-yor gb", "region save", "stats-core", "set name 2E0LXY-REPEATER", "set advert.interval 60",
               "time 1760000000", "clear stats", "tempradio 869.618,62.5,8,8,10", "set repeat on", "get traffic", "route find leeds", "trace route abc"]
    FULL_ADMIN = ["password hunter22", "set guest.password x", "get guest.password", "set prv.key aa", "get prv.key", "set wifi.ssid x", "set wifi.pwd y", "wifi clear 1", "get wifi.pwd", "set ap.mode on",
              "set ap.password z", "set net.ip dhcp", "set pin 12345678", "setperm abc 3", "set http off", "set telnet on", "set mqtt.custom.password p", "get mqtt.custom.password",
              "set mqtt.custom.host evil.example", "set mqtt.custom.port 1", "set mqtt.custom.transport tcp", "set mqtt.custom.username u", "set mqtt.control off", "set mqtt.control.key aa",
              "get mqtt.control.key", "set bridge.secret s", "get bridge.secret", "start ota", "ota install", "erase", "format", "poweroff", "set ble.pin 1", "set mqtt.meshmapper on", "set mqtt.join UMC1.abc", "set mqtt.umcnet off",
              "SET PASSWORD x", "Set Prv.Key aa", "GET PRV.KEY", "frobnicate", "set unknown.thing 1"]
    DENIED = ["", " get radio", "get radio ", "get radio\nset tx 1", 'get "radio"', "get radio\\", "a" * 141]

    def test_allowed(self):
        for c in self.ALLOWED + self.FULL_ADMIN: self.assertTrue(dash.command_allowed(c), c)

    def test_denied(self):
        for c in self.DENIED: self.assertFalse(dash.command_allowed(c), repr(c))

    def test_risky_ones_need_confirming(self):
        for c in ("reboot", "set tx 10", "set radio 1,2,3,4", "region put x", "set name x", "set mqtt.raw off", "set flood.max 5", "clear stats", "time 1", "update install", "set wifi.pwd secret"): self.assertTrue(dash.command_risky(c), c)
        for c in ("get radio", "stats-core", "neighbors", "ver"): self.assertFalse(dash.command_risky(c), c)

    def test_secret_commands_are_redacted_from_the_audit_text(self):
        self.assertEqual("set wifi.pwd [secret redacted] -> [reply redacted]", dash.audit_command("set wifi.pwd super-secret", "OK"))
        self.assertNotIn("super-secret", dash.audit_command("set wifi.pwd super-secret", "OK"))

    def test_read_replies_warm_the_settings_cache(self):
        dev = "AB" * 32; dash.SETTINGS.clear()
        dash.remember_setting(dev, "get radio", "> 869.618,62.5,8,8")
        dash.remember_setting(dev, "get update.status", "> up to date")
        self.assertEqual("> 869.618,62.5,8,8", dash.SETTINGS[dev]["values"]["radio"])
        self.assertEqual("> up to date", dash.SETTINGS[dev]["values"]["update.status"])


class PublicViewer(unittest.TestCase):
    def test_public_response_excludes_private_admin_state(self):
        dev = "CD" * 32
        original = dash.overview
        dash.overview = lambda: {"now": 1, "mqtt": {"state": "connected", "password": "no"}, "devices": [{"id": dev, "name": "Hill", "n_pkt": 4, "label": {"label": "North", "note": "private note"}, "settings": {"radio": "x", "lat": "53.1", "owner.info": "private"}}], "packets": [], "rates": {}, "types": {}, "heard_by": {}, "latency": {}}
        try: out = dash.public_overview()
        finally: dash.overview = original
        raw = repr(out)
        self.assertEqual({"state": "connected"}, out["mqtt"])
        self.assertNotIn("accounts", out); self.assertNotIn("control", out)
        self.assertNotIn("lat", out["devices"][0]["settings"]); self.assertNotIn("owner.info", out["devices"][0]["settings"])
        self.assertNotIn("password", raw); self.assertNotIn("private note", raw); self.assertEqual(4, out["totals"]["packets"])

    def test_public_network_strips_coordinates(self):
        original = dash.network_view
        dash.network_view = lambda: {"now": 1, "nodes": [{"key": "A", "name": "Hill", "lat": 53.1, "lon": -1.5}], "links": [], "journeys": []}
        try: out = dash.public_network_view()
        finally: dash.network_view = original
        self.assertNotIn("lat", out["nodes"][0]); self.assertNotIn("lon", out["nodes"][0])


class Settings(unittest.TestCase):
    def setUp(self): dash.conf_load()

    def test_a_good_change_is_kept(self):
        self.assertIsNone(dash.conf_update({"stale_minutes": 30, "title": "My net", "alerts": {"enabled": True, "url": "https://ntfy.sh/mytopic"}}))
        self.assertEqual(30, dash.CONF["stale_minutes"]); self.assertEqual("https://ntfy.sh/mytopic", dash.CONF["alerts"]["url"])

    def test_bad_values_are_refused_and_nothing_changes(self):
        before = dash.CONF["stale_minutes"]
        for patch in ({"stale_minutes": 0}, {"stale_minutes": "x"}, {"keep_days": 500}, {"title": ""}, {"alerts": {"url": "javascript:alert(1)"}}, {"cert_bad_days": 20, "cert_warn_days": 10}):
            self.assertIsNotNone(dash.conf_update(patch), patch)
        self.assertEqual(before, dash.CONF["stale_minutes"])

    def test_unknown_keys_are_ignored(self):
        self.assertIsNone(dash.conf_update({"surprise": 1})); self.assertNotIn("surprise", dash.CONF)

    def test_labels_only_for_real_device_ids(self):
        dash.conf_update({"labels": {"AB" * 32: {"label": "Hill", "note": "n"}, "nonsense": {"label": "x"}}})
        self.assertEqual(["AB" * 32], list(dash.CONF["labels"]))


class BrokerLog(unittest.TestCase):
    def setUp(self):
        dash.db_init(); dash.CLIENTS.clear(); dash.EVENTS.clear()

    def test_a_connection_is_recorded_with_its_account_and_address(self):
        dash.handle_log("1792951649: New client connected from 86.1.2.3:5555 as mqtt_custom-756C3D (p2, c1, k60, u'v3-repeater').")
        c = dash.CLIENTS["mqtt_custom-756C3D"]
        self.assertEqual(("v3-repeater", "86.1.2.3", "connected"), (c["user"], c["ip"], c["state"]))

    def test_a_refused_login_remembers_where_it_came_from(self):
        dash.handle_log("1792951649: New connection from 5.6.7.8:41000 on port 9101.")
        dash.handle_log("1792951649: Client auto-AFE7 disconnected, not authorised.")
        e = [x for x in dash.EVENTS if x["kind"] == "auth_fail"]
        self.assertEqual(1, len(e)); self.assertEqual("5.6.7.8", e[0]["ip"])

    def test_a_reconnect_with_the_same_client_id_stays_connected(self):
        # the broker logs the new connection first, then closes the old stale one
        dash.handle_log("1: New client connected from 1.1.1.1:1 as c9 (p2, c1, k60, u'rep').")
        dash.handle_log("2: Client c9 already connected, closing old connection.")      # the order a real broker logs it in
        dash.handle_log("2: New client connected from 1.1.1.1:2 as c9 (p2, c1, k60, u'rep').")
        dash.handle_log("2: Client c9 closed its connection.")
        self.assertEqual("connected", dash.CLIENTS["c9"]["state"])
        dash.handle_log("9: Client c9 closed its connection.")                       # a real, later disconnect still counts
        self.assertEqual("disconnected", dash.CLIENTS["c9"]["state"])

    def test_a_disconnect_marks_the_client(self):
        dash.handle_log("1: New client connected from 1.1.1.1:1 as c1 (p2, c1, k60, u'x').")
        dash.handle_log("2: Client c1 has exceeded timeout, disconnecting.")
        self.assertEqual("disconnected", dash.CLIENTS["c1"]["state"])
        self.assertTrue(any(x["kind"] == "timeout" for x in dash.EVENTS))


class Packets(unittest.TestCase):
    def advert(self, name):
        body = bytes(range(32)) + bytes(4) + bytes(64) + bytes([0x81]) + name.encode()
        return (bytes([(4 << 2) | 1, 1, 0xD5]) + body)

    def test_an_advert_gives_its_name_and_the_repeater_that_passed_it_on(self):
        i = dash.parse_packet(self.advert("MRLM-HA"))
        self.assertEqual(("ADVERT", "MRLM-HA", "D5", 1), (i["type"], i["name"], i["via"], i["hops"]))

    def test_a_response_gives_sender_and_destination(self):
        i = dash.parse_packet(bytes([(1 << 2) | 1, 0, 0xA1, 0xB0, 9, 9]))
        self.assertEqual(("RESP", "B0", "A1"), (i["type"], i["src"], i["dst"]))

    def test_rubbish_is_refused(self):
        for raw in (b"", b"\x05", bytes([(5 << 2) | 1, 5, 1])): self.assertIsNone(dash.parse_packet(raw))


class Network(unittest.TestCase):
    KEY_A = "11" * 32
    KEY_B = "22" * 32

    def advert(self, key_hex, name, lat=None, lon=None, hops=(), atype=2):
        import struct
        flags = 0x80 | atype | (0x10 if lat is not None else 0)
        loc = struct.pack("<ii", int(lat * 1e6), int(lon * 1e6)) if lat is not None else b""
        body = bytes.fromhex(key_hex) + bytes(4) + bytes(64) + bytes([flags]) + loc + name.encode()
        return bytes([(4 << 2) | 1, len(hops)]) + bytes(hops) + body

    def setUp(self):
        dash.NODES.clear(); dash.LINKS.clear(); dash.JOURNEYS.clear(); dash.DEV.clear()

    def test_an_advert_gives_its_position_and_kind(self):
        i = dash.parse_packet(self.advert(self.KEY_A, "Hill", 53.7012, -1.5534))
        self.assertEqual((self.KEY_A.upper(), 2, "Hill"), (i["fkey"], i["atype"], i["name"]))
        self.assertAlmostEqual(53.7012, i["lat"], 4); self.assertAlmostEqual(-1.5534, i["lon"], 4)

    def test_an_advert_without_a_position_has_none_and_nonsense_is_ignored(self):
        self.assertNotIn("lat", dash.parse_packet(self.advert(self.KEY_A, "Hill")))
        self.assertNotIn("lat", dash.parse_packet(self.advert(self.KEY_A, "Hill", 0.0, 0.0)))     # 0,0 means "not set"
        self.assertNotIn("lat", dash.parse_packet(self.advert(self.KEY_A, "Hill", 91.0, 10.0)))

    def test_a_link_records_the_nearest_hop_count_and_the_best_signal(self):
        recv = "AA" * 32
        for hops, snr in ((2, 3.0), (0, 8.5), (1, 5.0)):
            dash.note_network(recv, dash.parse_packet(self.advert(self.KEY_A, "Hill", 53.7, -1.5, hops=[7] * hops)), snr, -100, time.time())
        l = dash.LINKS[(recv, self.KEY_A.upper())]
        self.assertEqual((3, 0, 8.5), (l["n"], l["hops_min"], l["snr"]))
        self.assertEqual("Hill", dash.NODES[self.KEY_A.upper()]["name"])

    def test_a_repeater_does_not_link_to_itself(self):
        dash.note_network(self.KEY_A.upper(), dash.parse_packet(self.advert(self.KEY_A, "Me", hops=[1])), 1, -90, time.time())
        self.assertEqual({}, dash.LINKS)

    def test_a_hash_names_a_node_only_when_exactly_one_fits(self):
        dash.NODES.update({"1A" + "00" * 31: {"name": "One"}, "1B" + "00" * 31: {"name": "Two"}, "1A" + "FF" * 31: {"name": "Three"}})
        self.assertEqual("1B" + "00" * 31, dash.node_for_hash("1b"))
        self.assertIsNone(dash.node_for_hash("1A"))          # two nodes start 1A
        self.assertIsNone(dash.node_for_hash("EE"))
        self.assertEqual("One", dash.hop_name("1B") and "One")  # an unresolved hash is shown as itself
        self.assertEqual("1A", dash.hop_name("1A"))

    def test_a_response_links_to_the_node_its_sender_hash_names(self):
        recv = "AA" * 32
        dash.NODES[self.KEY_B.upper()] = {"key": self.KEY_B.upper(), "name": "B", "type": 2, "lat": None, "lon": None, "first": 0, "last": time.time(), "adverts": 1}
        raw = bytes([(1 << 2) | 1, 1, 0x33, 0xAA, 0x22, 9, 9])               # RESP: destination AA, sender 22, via 33
        dash.note_network(recv, dash.parse_packet(raw), 4.0, -95, time.time())
        self.assertIn((recv, self.KEY_B.upper()), dash.LINKS)
        self.assertEqual("B", dash.network_view()["nodes"][0]["name"])

    def test_the_view_lists_nodes_links_and_journeys(self):
        d = dash.device("AA" * 32, "LBA"); d["last"] = time.time(); d["name"] = "Rep"
        dash.note_network("AA" * 32, dash.parse_packet(self.advert(self.KEY_A, "Hill", 53.7, -1.5, hops=[0x44])), 6.0, -97, time.time())
        v = dash.network_view()
        self.assertEqual((2, 1, 1), (len(v["nodes"]), len(v["links"]), len(v["journeys"])))                      # the repeater, the node it heard, their link
        self.assertEqual(1, v["links"][0]["hops"]); self.assertEqual("44", v["journeys"][0]["path"][0]["h"])
        rep = next(n for n in v["nodes"] if n["key"] == "AA" * 32); self.assertTrue(rep["online"] and rep["info"]["name"] == "Rep")
        self.assertEqual(1, len(dash.network_view(hours=1)["nodes"][:1])); d["last"] = 0; dash.NODES[self.KEY_A.upper()]["last"] = time.time() - 3 * 86400
        self.assertEqual(0, len(dash.network_view(hours=24)["nodes"]))                                           # not on the network and not heard lately: not on the map

    def test_a_reflashed_station_shows_once_under_its_newest_key(self):
        now = time.time(); d = dash.device("CC" * 32, "LBA"); d["last"] = now; d["name"] = "Hill"
        for k, nm, last in (("CC" * 32, "Hill", now), ("DD" * 32, "Hill", now - 7200), ("EE" * 32, "Mast", now - 600), ("FF" * 32, "Mast", now - 60), ("11" * 32, "", now)):
            dash.NODES[k] = {"key": k, "name": nm, "type": 2, "lat": None, "lon": None, "first": 0, "last": last, "adverts": 1}
        v = dash.network_view(hours=24); keys = sorted(n["key"][:2] for n in v["nodes"])
        self.assertEqual(["11", "CC", "FF"], keys)


class History(unittest.TestCase):
    def test_many_series_can_be_asked_for_at_once(self):
        # the page asks for 13 fixed series plus one per repeater; an old limit of 12 silently dropped the rest
        dash.db_init(); now = int(time.time())
        dash.DB.executemany("INSERT INTO samples VALUES(?,?,?)", [(now - 60, "k%d" % i, float(i)) for i in range(30)])
        got = dash.history(["k%d" % i for i in range(30)], 3600)
        self.assertEqual(30, len(got))
        src = open(os.path.join(HERE, "umcnet_dash.py")).read()
        self.assertIn('split(",") if k][:60]', src)


class JoinCode(unittest.TestCase):
    KEY = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"

    def test_codes_match_the_firmware_vectors(self):
        # the same three codes are decoded by test/test_join_code in C++
        self.assertEqual("UMC1.AQNMQkEPYmxha2Utc2hlZmZpZWxkFEhtY21yenFsclZNVUFjdGpZendOAAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8LJuo", dash.make_join_code("blake-sheffield", "HmcmrzqlrVMUActjYzwN", "LBA", self.KEY, True))
        self.assertEqual("UMC1.AQBMQkELdjMtcmVwZWF0ZXIQYWJjZGVmZ2gxMjM0NTY3OPUrdA", dash.make_join_code("v3-repeater", "abcdefgh12345678", "LBA", None, False))
        self.assertEqual("UMC1.AQdHQlIIaGlsbC10b3AUWnE5Xy1BYThCYjdDYzZEZDVFZTQQbWVzaC5leGFtcGxlLm9yZyKzAAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8XT_s", dash.make_join_code("hill-top", "Zq9_-Aa8Bb7Cc6Dd5Ee4", "GBR", self.KEY, True, "mesh.example.org", 8883))

    def test_a_code_fits_the_repeaters_console(self):
        c = dash.make_join_code("a-very-long-name-here-24", "x" * 24, "LBA", self.KEY, True)       # the longest realistic one
        self.assertLessEqual(len("set mqtt.join " + c), 159)
        with self.assertRaises(ValueError): dash.make_join_code("a-very-long-name-here-24", "x" * 40, "LBA", self.KEY, True, "mesh.example.org", 8883)   # too long: refused, not cut

    def test_bad_inputs_are_refused(self):
        for args in (("Bad Name", "abcdefgh12"), ("ok-name", "short"), ("ok-name", "has space in it"), ("ok-name", "x" * 41), ("ok-name", "abcdefgh12", "lba"), ("ok-name", "abcdefgh12", "LBA", "zz")):
            with self.assertRaises(ValueError): dash.make_join_code(*args)

    def test_the_settings_accept_a_good_area_and_refuse_a_bad_one(self):
        dash.conf_load(); self.assertIsNone(dash.conf_update({"join_iata": "lba", "join_bridge": False})); self.assertEqual("LBA", dash.CONF["join_iata"])
        self.assertIsNotNone(dash.conf_update({"join_iata": "TOOLONG"})); dash.conf_update({"join_bridge": True})



class AlertRequest(unittest.TestCase):
    def test_a_ntfy_address_with_a_login_is_sent_with_basic_auth_and_without_the_login_in_the_url(self):
        r = dash.build_alert_request("https://umc-dash:p%40ss@net.example:8443/umc-ntfy-abc", "Repeater offline", "V3 has been silent", "bad")
        self.assertEqual("https://net.example:8443/umc-ntfy-abc", r.full_url)
        import base64
        self.assertEqual("Basic " + base64.b64encode(b"umc-dash:p@ss").decode(), r.get_header("Authorization"))
        self.assertEqual("high", r.get_header("Priority")); self.assertEqual(b"V3 has been silent", r.data)

    def test_an_open_ntfy_address_has_no_login_and_other_addresses_get_json(self):
        r = dash.build_alert_request("https://ntfy.sh/topic", "T", "x", "ok"); self.assertIsNone(r.get_header("Authorization")); self.assertEqual("white_check_mark", r.get_header("Tags"))
        j = dash.build_alert_request("https://hooks.example/x", "T", "x", "warn"); self.assertEqual("application/json", j.get_header("Content-type")); self.assertEqual("T", json.loads(j.data)["title"])


class Enrol(unittest.TestCase):
    """The server half of zero-touch enrolment (the full flow against a real broker is e2e_enrol.py)."""
    @classmethod
    def setUpClass(cls):
        import importlib.util
        sp = importlib.util.spec_from_file_location("umcnet_enrol", os.path.join(HERE, "umcnet_enrol.py"))
        cls.E = importlib.util.module_from_spec(sp); sp.loader.exec_module(cls.E)

    def test_curve25519_matches_rfc_7748(self):
        k = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
        u = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
        self.assertEqual("c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552", self.E.x25519(k, u).hex())

    def test_ed25519_matches_rfc_8032(self):
        prv, pub = self.E.ed_keypair(bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))
        self.assertEqual("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", pub.hex())
        sig = self.E.ed_sign(prv, pub, b"")
        self.assertEqual("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b", sig.hex())
        self.assertTrue(self.E.ed_verify(pub, b"", sig)); self.assertFalse(self.E.ed_verify(pub, b"x", sig))

    def hello(self, prv, pub, ts=None, name="Hill", **over):
        dev = pub.hex().upper(); ts = int(ts or time.time()); nc = "a1b2c3d4e5f60718"
        j = {"v": 1, "id": dev, "name": name, "fw": "0.2.0", "bd": "Heltec V3", "ts": ts, "nc": nc, "sig": self.E.ed_sign(prv, pub, self.E.hello_message(dev, ts, nc)).hex()}
        j.update(over); return json.dumps(j)

    def test_a_signed_request_is_accepted_and_others_are_refused(self):
        prv, pub = self.E.ed_keypair(os.urandom(32)); other = self.E.ed_keypair(os.urandom(32))
        info, why = self.E.verify_hello(self.hello(prv, pub)); self.assertIsNone(why); self.assertEqual(pub.hex().upper(), info["id"])
        self.assertIsNotNone(self.E.verify_hello(self.hello(prv, pub, id=other[1].hex().upper()))[1])      # someone else's id
        self.assertIsNotNone(self.E.verify_hello(self.hello(prv, pub, ts=time.time() - 3 * 86400))[1])      # too old
        self.assertIsNotNone(self.E.verify_hello(self.hello(prv, pub, name="Other"))[1] if False else self.E.verify_hello(self.hello(prv, pub, ts=1))[1])
        for bad in ("", "nope", "[]", '{"v":2}', json.dumps({"v": 1, "id": "zz"}), self.hello(prv, pub, sig="00" * 64), self.hello(prv, pub, nc="xx")):
            self.assertIsNone(self.E.verify_hello(bad)[0], bad[:40])

    def test_a_grant_opens_only_for_its_repeater_and_any_damage_is_refused(self):
        prv, pub = self.E.ed_keypair(os.urandom(32)); dev = pub.hex().upper(); other = self.E.ed_keypair(os.urandom(32))[0]
        g = self.E.make_grant(dev, "UMC1.example")
        self.assertEqual("UMC1.example", self.E.open_grant(prv, dev, g)); self.assertIsNone(self.E.open_grant(other, dev, g))
        for i in range(0, len(g), 7):
            bad = g[:i] + ("A" if g[i] != "A" else "B") + g[i + 1:]
            try: self.assertIsNone(self.E.open_grant(prv, dev, bad))
            except Exception: pass

    def test_the_firmware_test_vector_opens(self):
        cpp = open(os.path.join(HERE, "..", "..", "..", "test", "test_enrol", "test_enrol.cpp")).read()
        pick = lambda n: re.search(r'k%s = "([^"]*)"' % n, cpp).group(1)
        prv, dev, code, grant = bytes.fromhex(pick("Prv")), pick("Pub"), pick("Code"), pick("Grant")
        self.assertEqual(code, self.E.open_grant(prv, dev, grant))
        self.assertEqual(self.E.ed_keypair(bytes(range(1, 33)))[1].hex().upper(), dev)

    def test_slugs_are_valid_account_names(self):
        dash.ENROL["pending"].clear()
        for raw, dev in (("Hill Top", "AB" * 32), ("  Ünïcode!! ", "CD" * 32), ("x", "EF" * 32), ("", "12" * 32), ("A" * 60, "34" * 32)):
            slug = dash.enrol_slug(raw, dev); self.assertRegex(slug, r"^[a-z0-9][a-z0-9-]{1,23}$", raw)


class RiskyCommands(unittest.TestCase):
    def test_the_settings_the_page_reads_are_not_risky_but_secrets_still_are(self):
        for k in dash.DEVICE_SETTING_KEYS + dash.STATUS_SETTING_KEYS: self.assertFalse(dash.command_risky("get " + k), k)   # preload and Read settings must not be refused
        for c in ("get mqtt.custom.password", "get mqtt.custom.username", "get wifi.pwd", "get mqtt.control.key", "get guest.password", "get pin"):
            self.assertTrue(dash.command_risky(c), c)
        for c in ("set lat 53.1", "set mqtt.custom.rate 20", "set mqtt.custom.bridge on", "reboot", "update install"):
            self.assertTrue(dash.command_risky(c), c)                      # changing anything still asks

    def test_the_secret_words_still_redact_the_audit_log(self):
        self.assertIn("[secret redacted]", dash.audit_command("set wifi.pwd hunter2"))
        self.assertIn("[secret redacted]", dash.audit_command("get lat", "53.1"))


class Messages(unittest.TestCase):
    """Channel messages: the crypto matches the firmware's own code, and the dashboard's engine reads, dedupes and sends."""
    @classmethod
    def setUpClass(cls):
        import importlib.util
        sp = importlib.util.spec_from_file_location("umcnet_msgs", os.path.join(HERE, "umcnet_msgs.py"))
        cls.M = importlib.util.module_from_spec(sp); sp.loader.exec_module(cls.M)

    def setUp(self):                      # the defaults, whatever an earlier test saved
        dash.CONF.clear(); dash.CONF.update(json.loads(json.dumps(dash.DEFAULTS)))

    def test_aes_matches_fips_197(self):
        key = bytes(range(16)); pt = bytes.fromhex("00112233445566778899aabbccddeeff"); ct = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        self.assertEqual(ct, self.M.aes_encrypt_block(key, pt)); self.assertEqual(pt, self.M.aes_decrypt_block(key, ct))

    def test_message_bytes_match_the_firmwares_own_code(self):
        # produced by src/Utils.cpp encryptThenMAC (built from the firmware sources) for key i*7+3, ts 1790000000, "2E0LXY-TEST: hello yorkshire"
        import base64, hashlib, hmac, struct
        key = bytes((i * 7 + 3) & 255 for i in range(16)); ch = self.M.Channel("t", base64.b64encode(key).decode())
        cipher = self.M.aes_ecb(ch.key, struct.pack("<I", 1790000000) + b"\x00" + b"2E0LXY-TEST: hello yorkshire", True)
        self.assertEqual("7b740379decd3c1c7f5bd690655bf7eb88e2a7cafbe721ed2b2a92921a4b2652337d54969b82137a1eeb0fdcd5ba4a1c9153", (hmac.new(ch.secret, cipher, hashlib.sha256).digest()[:2] + cipher).hex())

    def test_hashtag_and_public_channels(self):
        import base64
        self.assertEqual("6hnpVn7sGxSMF08MudBN1w==", base64.b64encode(self.M.Channel("#yorkshire").key).decode())      # UMC's built-in key for #yorkshire
        self.assertEqual(0x11, self.M.Channel("Public", self.M.PUBLIC_PSK).hash)                                       # MeshCore's Public channel hash
        with self.assertRaises(ValueError): self.M.Channel("secret-room")

    def test_a_scoped_message_names_its_region_and_only_the_right_channel_reads_it(self):
        yk = self.M.Channel("#yorkshire"); raw = self.M.build_group_text(yk, "Daren", "hello", 1790000000, region="eng-yh"); p = self.M.parse_wire(raw)
        self.assertEqual(0, p["route"]); self.assertEqual("eng-yh", self.M.find_region(["yorkshire", "eng-yh"], p)); self.assertEqual("", self.M.find_region(["yorkshire"], p))
        ch, ts, flags, text = self.M.decrypt_group([self.M.Channel("#other"), yk], p["payload"]); self.assertEqual(("#yorkshire", "Daren: hello"), (ch.name, text))
        self.assertIsNone(self.M.decrypt_group([self.M.Channel("#other")], p["payload"]))
        u = self.M.parse_wire(self.M.build_group_text(yk, "A", "x", 1790000000)); self.assertEqual((1, None), (u["route"], u["codes"]))

    def test_damage_is_refused(self):
        yk = self.M.Channel("#yorkshire"); p = self.M.parse_wire(self.M.build_group_text(yk, "A", "x", 1790000000))["payload"]
        for i in range(len(p)):
            bad = bytearray(p); bad[i] ^= 0x40
            self.assertIsNone(self.M.decrypt_group([yk], bytes(bad)), i)

    def test_the_engine_records_a_message_once_with_every_repeater_that_heard_it(self):
        dash.db_init(); dash.DB.execute("DELETE FROM messages"); dash.DEV.clear()
        for i, n in enumerate(("A", "B")): dash.device("%02X" % (i + 1) * 32, "LBA")["name"] = "Repeater " + n
        yk = self.M.Channel("#yorkshire"); raw = self.M.build_group_text(yk, "Sam", "anyone on?", int(time.time()), region="yorkshire")
        now = time.time(); dash.note_message("01" * 32, raw, "5.5", "-90", now); dash.note_message("02" * 32, raw, "9.0", "-80", now + 1); dash.note_message("01" * 32, raw, "5.5", "-90", now + 2)
        v = dash.messages_view(); self.assertEqual(1, len(v["messages"])); m = v["messages"][0]
        self.assertEqual(("#yorkshire", "yorkshire", "Sam", "anyone on?", "rx"), (m["chan"], m["region"], m["sender"], m["text"], m["dir"])); self.assertEqual(["Repeater A", "Repeater B"], sorted(h["name"] for h in m["heard"]))
        self.assertEqual(1, len(dash.messages_view(region="yorkshire")["messages"])); self.assertEqual(0, len(dash.messages_view(region="eng-yh")["messages"])); self.assertEqual(1, len(dash.messages_view(q="anyone")["messages"]))
        other = self.M.build_group_text(self.M.Channel("#nobody-knows"), "X", "secret", int(now)); dash.note_message("01" * 32, other, "1", "-100", now)
        self.assertEqual(1, len(dash.messages_view()["messages"])); self.assertEqual(1, sum(x["n"] for x in dash.messages_view()["unreadable"].values()))   # counted, not shown

    def test_clear_messages_removes_all_or_only_the_filtered_ones(self):
        dash.db_init(); dash.DB.execute("DELETE FROM messages"); dash.DEV.clear(); now = int(time.time())
        saved = list(dash.CONF["messages"]["channels"]); self.addCleanup(lambda: (dash.CONF["messages"].__setitem__("channels", saved), dash.DB.execute("DELETE FROM messages")))
        dash.CONF["messages"]["channels"] = saved + [{"name": "#yorkshire"}, {"name": "#test"}]
        for i, ch in enumerate(("#yorkshire", "#test")):
            dash.note_message("01" * 32, self.M.build_group_text(self.M.Channel(ch), "S", "hi %d" % i, now + i), "1", "-90", now + i)
        self.assertEqual(2, len(dash.messages_view()["messages"]))
        self.assertEqual(1, dash.clear_messages("admin", chan="#test")["removed"]); self.assertEqual(1, len(dash.messages_view()["messages"]))
        self.assertEqual(1, dash.clear_messages("admin")["removed"]); self.assertEqual(0, len(dash.messages_view()["messages"]))

    def test_a_repeaters_transmit_report_confirms_a_dashboard_message_was_sent(self):
        dash.db_init(); dash.DB.execute("DELETE FROM messages"); dash.DEV.clear(); now = int(time.time())
        saved = list(dash.CONF["messages"]["channels"]); self.addCleanup(lambda: (dash.CONF["messages"].__setitem__("channels", saved), dash.DB.execute("DELETE FROM messages")))
        dash.CONF["messages"]["channels"] = saved + [{"name": "#yorkshire"}]
        raw = self.M.build_group_text(self.M.Channel("#yorkshire"), "UMC-DASH", "out", now)
        pkey = __import__("hashlib").sha1(self.M.parse_wire(raw)["payload"]).hexdigest()[:20]
        dash.DB.execute("INSERT INTO messages(ts,seen,chan,chash,region,sender,text,pkey,dir,hops,snr,rssi,heard) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (now, now, "#yorkshire", "00", "", "UMC-DASH", "out", pkey, "tx", 0, None, None, "[]"))
        dash.device("01" * 32, "LBA")["name"] = "Repeater A"
        dash.note_sent("01" * 32, raw, now); dash.note_sent("01" * 32, raw, now + 1)          # twice: recorded once
        h = dash.messages_view()["messages"][0]["heard"]; self.assertEqual([("Repeater A", True)], [(x["name"], x["sent"]) for x in h])
        dash.note_message("02" * 32, raw, "4.0", "-90", now + 2)                                 # a second repeater hears it back
        h = dash.messages_view()["messages"][0]["heard"]; self.assertEqual([True, False], [x["sent"] for x in h])
        other = self.M.build_group_text(self.M.Channel("#yorkshire"), "Sam", "not ours", now); dash.note_sent("01" * 32, other, now)   # an unrelated packet is ignored
        self.assertEqual(1, len(dash.messages_view()["messages"]))

    def test_clients_are_caught_up_with_the_last_hour(self):
        class Conn:
            up = True
            def __init__(s): s.out = []
            def publish(s, topic, body, *a, **k): s.out.append((topic, json.loads(body)))
        dash.db_init(); dash.DB.execute("DELETE FROM grp_buf"); dash.DB.execute("DELETE FROM messages"); dash.DEV.clear(); dash.REPLAY_LAST.clear(); now = int(time.time())
        old = dash.CTL.get("conn"); c = Conn(); dash.CTL["conn"] = c; pace = dash.REPLAY_PACE; dash.REPLAY_PACE = 0
        def undo(): dash.CTL["conn"] = old; dash.REPLAY_PACE = pace; dash.MSGSTAT.clear(); dash.RECENT_GRP.clear(); dash.DB.execute("DELETE FROM grp_buf"); dash.REPLAY_LAST.clear()
        self.addCleanup(undo)
        cid = "AB" * 32; req = "umcnet/v1/LBA/replay/req/" + cid; rtopic = "umcnet/v1/LBA/replay/" + cid
        def ask(since, t=None, topic=req, body=None):
            th = dash.replay_request(topic, body if body is not None else json.dumps({"since": since}).encode(), now=t or now)
            if th: th.join(5)
            return th
        # fill: an rx packet for a channel the dash has no key for, and a tx report
        other = self.M.build_group_text(self.M.Channel("#nobody-knows"), "X", "secret", now)
        dash.note_message("01" * 32, other, "4.5", "-91", now - 30)
        mine = self.M.build_group_text(self.M.Channel("#yorkshire"), "UMC-DASH", "out", now)
        dash.note_sent("02" * 32, mine, now - 20)
        rows = dash.DB.execute("SELECT did,dir,snr,rssi,raw FROM grp_buf ORDER BY seen").fetchall()
        self.assertEqual([("01" * 32, "rx", 4.5, -91, other.hex().upper()), ("02" * 32, "tx", None, None, mine.hex().upper())], rows)
        dash.note_message("01" * 32, other, "4.5", "-91", now - 10)                      # the same packet again: kept once, earliest time
        self.assertEqual(2, dash.DB.execute("SELECT COUNT(*) FROM grp_buf").fetchone()[0])
        self.assertEqual(now - 30, dash.DB.execute("SELECT seen FROM grp_buf WHERE dir='rx'").fetchone()[0])
        # an old row is excluded even when since asks for more, and pruned
        dash.DB.execute("INSERT INTO grp_buf VALUES('old','03',?, 'rx', NULL, NULL, 'AA')", (now - 3700,)); dash.DB.execute("INSERT INTO grp_buf VALUES('older','03',?, 'rx', NULL, NULL, 'AA')", (now - 4100,))
        self.assertTrue(ask(0))
        self.assertEqual([rtopic] * 3, [t for t, _ in c.out]); self.assertTrue(all("/raw" not in t and not t.startswith("meshcore") for t, _ in c.out))
        a, b, done = [m for _, m in c.out]
        self.assertEqual({"origin_id": "01" * 32, "timestamp": now - 30, "type": "RAW", "data": other.hex().upper(), "direction": "rx", "snr": 4.5, "rssi": -91, "replay": 1}, a)
        self.assertEqual(("02" * 32, "tx", None, None), (b["origin_id"], b["direction"], b["snr"], b["rssi"])); self.assertEqual({"done": 1, "n": 2}, done)
        self.assertEqual(0, dash.DB.execute("SELECT COUNT(*) FROM grp_buf WHERE pkey='older'").fetchone()[0])
        # rate limit: a second request inside 20 s is ignored, after 20 s it is served
        c.out.clear(); self.assertFalse(ask(0, now + 5)); self.assertEqual([], c.out)
        self.assertTrue(ask(now - 25, now + 21)); self.assertEqual({"done": 1, "n": 1}, c.out[-1][1]); self.assertEqual(2, len(c.out))     # since filters; only the tx one is newer
        # another client is not limited by this one
        c.out.clear(); other_id = "CD" * 32; self.assertTrue(ask(0, now + 22, "umcnet/v1/LBA/replay/req/" + other_id)); self.assertEqual("umcnet/v1/LBA/replay/" + other_id, c.out[0][0])

    def test_the_catch_up_serves_the_newest_500_oldest_first(self):
        class Conn:
            up = True
            def __init__(s): s.out = []
            def publish(s, topic, body, *a, **k): s.out.append(json.loads(body))
        dash.db_init(); dash.DB.execute("DELETE FROM grp_buf"); now = int(time.time()); c = Conn()
        dash.DB.executemany("INSERT INTO grp_buf VALUES(?,?,?,?,?,?,?)", [("p%d" % i, "01" * 32, now - 3000 + i, "rx", None, None, "AA") for i in range(600)])
        self.addCleanup(lambda: dash.DB.execute("DELETE FROM grp_buf"))
        self.assertEqual(500, dash.replay_serve(c, "LBA", "AB" * 32, now - 99999, now, pace=0))
        ts = [m["timestamp"] for m in c.out[:-1]]; self.assertEqual(ts, sorted(ts)); self.assertEqual((now - 3000 + 100, now - 3000 + 599), (ts[0], ts[-1])); self.assertEqual({"done": 1, "n": 500}, c.out[-1])

    def test_bad_catch_up_requests_are_ignored(self):
        dash.db_init(); dash.REPLAY_LAST.clear(); old = dash.CTL.get("conn")
        class Conn:
            up = True
            def publish(s, *a, **k): raise AssertionError("nothing should be sent")
        dash.CTL["conn"] = Conn(); self.addCleanup(lambda: (dash.CTL.__setitem__("conn", old), dash.REPLAY_LAST.clear()))
        cid = "AB" * 32; good = json.dumps({"since": 1}).encode()
        for topic, body in (("umcnet/v1/LBA/replay/req/" + cid.lower(), good), ("umcnet/v1/LBA/replay/req/ABCD", good), ("umcnet/v1/L/BA/replay/req/" + cid, good), ("umcnet/v1/LBA/replay/req/" + cid + "/x", good),
                            ("umcnet/v1/LBA/replay/req/" + cid, b"not json"), ("umcnet/v1/LBA/replay/req/" + cid, b"[1]"), ("umcnet/v1/LBA/replay/req/" + cid, b"{}"),
                            ("umcnet/v1/LBA/replay/req/" + cid, b'{"since":"1"}'), ("umcnet/v1/LBA/replay/req/" + cid, b'{"since":true}'), ("umcnet/v1/LBA/replay/req/" + cid, b"\xff\xfe")):
            self.assertFalse(dash.replay_request(topic, body), (topic, body))
        self.assertFalse(dash.replay_request("umcnet/v1/LBA/replay/req/" + cid, good, retained=True)); self.assertEqual({}, dash.REPLAY_LAST)
        dash.on_control_reply("umcnet/v1/LBA/replay/req/" + cid, b"junk")                 # through the dispatcher too: no error

    def test_a_message_can_be_sent_through_chosen_repeaters_only(self):
        class Conn:
            up = True
            def __init__(s): s.out = []
            def publish(s, topic, body, *a, **k): s.out.append((topic, body))
        dash.db_init(); dash.DB.execute("DELETE FROM messages"); dash.DEV.clear(); now = time.time(); old = dash.CTL.get("conn"); c = Conn(); dash.CTL["conn"] = c
        saved = list(dash.CONF["messages"]["channels"]); tx = dash.CONF["messages"]["tx_enabled"]
        def undo(): dash.CTL["conn"] = old; dash.CONF["messages"].update(channels=saved, tx_enabled=tx); dash.DB.execute("DELETE FROM messages")
        self.addCleanup(undo); dash.CONF["messages"]["tx_enabled"] = True; dash.CONF["messages"]["channels"] = saved + [{"name": "#yorkshire"}]
        for i, n in enumerate(("A", "B")): d = dash.device(("%02X" % (i + 1)) * 32, "LBA"); d["name"] = "Repeater " + n; d["last"] = now
        a = "01" * 32
        raws = lambda: [x[1] for x in c.out if x[0].endswith("/raw")]
        r = dash.send_message("admin", "#yorkshire", "", "hello", "TEST"); self.assertTrue(r["ok"]); self.assertEqual(2, len(r["repeaters"])); self.assertNotIn(b"target", raws()[-1])
        r = dash.send_message("admin", "#yorkshire", "", "hello2", "TEST", [a.lower()]); self.assertEqual(["Repeater A"], r["repeaters"])
        self.assertEqual(a, json.loads(raws()[-1])["target"])
        r = dash.send_message("admin", "#yorkshire", "", "hello3", "TEST", ["ff" * 32]); self.assertFalse(r["ok"])

    def test_purging_logs_keeps_recent_rows_and_never_wipes_the_audit_log(self):
        dash.db_init(); now = int(time.time()); dash.DB.execute("DELETE FROM events"); dash.DB.execute("DELETE FROM audit")
        dash.DB.executemany("INSERT INTO events VALUES(?,?,?,?,?,?)", [(now - 40 * 86400, "info", "", "", "", "old"), (now, "info", "", "", "", "new")])
        dash.DB.execute("INSERT INTO audit VALUES(?,?,?,?,?,1)", (now - 40 * 86400, "x", "old", "", ""))
        self.assertEqual({"ok": True, "removed": 1}, dash.purge_log("admin", "events", 30)); self.assertEqual(1, dash.DB.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        self.assertEqual(1, dash.purge_log("admin", "audit", 30)["removed"])
        for bad in (0, -1, "x", 99999): self.assertFalse(dash.purge_log("admin", "audit", bad)["ok"], bad)
        self.assertFalse(dash.purge_log("admin", "samples", 5)["ok"])
        self.assertEqual(1, dash.purge_log("admin", "events", 0)["removed"])

    def test_settings_for_channels_and_regions_are_validated(self):
        self.assertIsNone(dash.conf_update({"messages": {"channels": [{"name": "Public", "psk": self.M.PUBLIC_PSK}, {"name": "#sheffield"}], "regions": ["yorkshire", "#derbyshire"], "sender": "2E0LXY-DASH"}}))
        self.assertEqual(["yorkshire", "derbyshire"], dash.CONF["messages"]["regions"])
        for bad in ({"channels": [{"name": "no-key"}]}, {"channels": [{"name": "#x", "psk": "AAAA"}]}, {"regions": ["bad name"]}, {"sender": "x" * 40}, {"keep_days": 0}):
            self.assertIsNotNone(dash.conf_update({"messages": bad}), bad)

    def test_a_sent_message_is_built_for_the_bridge_and_limited(self):
        class Conn:
            up = True
            def __init__(self): self.sent = []
            def publish(self, topic, payload, retain=False): self.sent.append((topic, payload))
        dash.db_init(); dash.DB.execute("DELETE FROM messages"); dash.DEV.clear(); d = dash.device("01" * 32, "LBA"); d["last"] = time.time(); d["name"] = "Rep"
        c = Conn(); dash.CTL["conn"] = c; dash.TX_TIMES.clear()
        r = dash.send_message("t", "#yorkshire", "yorkshire", "hello from the dashboard"); self.assertTrue(r["ok"], r)
        topic, body = c.sent[0]; self.assertEqual("meshcore/LBA/%s/raw" % dash.DASH_ID, topic); self.assertIn(b'"data":"', body)          # the exact form a repeater's bridge parses
        j = json.loads(body); p = self.M.parse_wire(bytes.fromhex(j["data"])); ch, ts, fl, text = self.M.decrypt_group([self.M.Channel("#yorkshire")], p["payload"]); self.assertEqual("UMC-DASH: hello from the dashboard", text)
        self.assertEqual("yorkshire", self.M.find_region(["yorkshire"], p)); v = dash.messages_view(); self.assertEqual(("tx", "UMC-DASH"), (v["messages"][0]["dir"], v["messages"][0]["sender"]))
        for _ in range(5): dash.send_message("t", "#yorkshire", "", "x")
        self.assertIn("6 messages", dash.send_message("t", "#yorkshire", "", "x")["error"])
        dash.TX_TIMES.clear()
        for bad in (("#nope", "", "x"), ("#yorkshire", "mars", "x"), ("#yorkshire", "", ""), ("#yorkshire", "", "x" * 200), ("#yorkshire", "", "a\nb")): self.assertFalse(dash.send_message("t", *bad)["ok"], bad)
        dash.CTL["conn"] = None


class SettingsCache(unittest.TestCase):
    def test_settings_read_from_a_repeater_survive_a_restart(self):
        dash.SETTINGS.clear(); dash.SETTINGS["AB" * 32] = {"values": {"build": "> 0.1.33", "ota.state": "> running:app0"}, "updated": 1234.0, "loading": False, "error": ""}
        dash.settings_save(); dash.SETTINGS.clear(); dash.settings_load()
        self.assertEqual("> 0.1.33", dash.SETTINGS["AB" * 32]["values"]["build"]); self.assertEqual(1234.0, dash.SETTINGS["AB" * 32]["updated"]); self.assertFalse(dash.SETTINGS["AB" * 32]["loading"])


class Batch2(unittest.TestCase):
    """Confirmed neighbour links, the mesh issues check and the Prometheus endpoint."""
    def setUp(self):
        dash.db_init(); dash.DEV.clear(); dash.NODES.clear(); dash.KEYS.clear(); dash.DB.execute("DELETE FROM links")
        dash.CONF.clear(); dash.CONF.update(json.loads(json.dumps(dash.DEFAULTS)))

    def test_neighbour_reply_is_parsed_and_confirmed_with_the_repeater_own_snr(self):
        d = dash.device("AA" * 32, "LBA"); d["last"] = time.time(); d["name"] = "Rep"; dash.KEYS["AA" * 32] = {"k": 1}
        dash.send_command = lambda dev, cmd, *a, **k: {"ok": True, "reply": "E616B12A:1083:-44 52906E2B:1085:-24"}
        dash.neighbour_poll_once()
        rows = {r["b"]: r for r in dash.confirmed_links()}
        self.assertEqual({"E616B12A", "52906E2B"}, set(rows)); self.assertEqual(-11.0, rows["E616B12A"]["snr"])
        dash.send_command = lambda dev, cmd, *a, **k: {"ok": True, "reply": "E616B12A:1083:-40"}
        dash.neighbour_poll_once(); self.assertEqual(1, len([r for r in dash.confirmed_links() if r["b"] == "E616B12A"]))

    def test_mesh_issues_are_listed_in_diagnostics(self):
        now = time.time(); n = {"key": "CC" * 32, "name": "Quiet", "type": 2, "lat": None, "lon": None, "first": 0, "last": now - 3 * 86400, "adverts": 1}
        dash.NODES[n["key"]] = n
        d = dash.device("DD" * 32, "LBA"); d["last"] = now; d["name"] = "Tired"; d["stats"] = {"battery_mv": 3300}; d["bridge"] = {"heard": 100, "dropped": 30, "passed": 70}
        sysinfo = {"services": {}, "clock": None, "disk_total": 100, "disk_free": 50, "swap_total": 0, "swap_free": 0, "mem_total": 1, "mem_avail": 1, "load": [0, 0, 0], "cores": 1, "uptime": 1, "temp": None, "cert_days": None}
        titles = [x["title"] for x in dash.diagnostics(sysinfo, [], None)]
        self.assertIn("1 mesh node quiet for over a day", titles); self.assertIn("Low battery: Tired", titles); self.assertIn("Bridge holding back packets: Tired", titles)
        self.assertNotIn("Stale: Quiet", titles)

    def test_prometheus_text_has_the_numbers_and_the_names(self):
        d = dash.device("EE" * 32, "LBA"); d["last"] = time.time(); d["name"] = "TINGLEY"; d["pm"] = 2.5
        text = dash.prometheus_text()
        self.assertIn("umcnet_repeaters_online 1", text); self.assertIn('umcnet_packets_per_minute{repeater="TINGLEY"}', text)
        self.assertIn("# TYPE umcnet_broker_up gauge", text)


class PacketRoutes(unittest.TestCase):
    def test_copies_of_one_packet_become_one_route_heard_by_several(self):
        dash.JOURNEYS.clear(); dash.DEV.clear(); now = time.time()
        d1 = dash.device("11" * 32, "LBA"); d1["name"] = "TINGLEY"; d2 = dash.device("22" * 32, "LBA"); d2["name"] = "BlakeUK"
        for dev, t in (("11" * 32, now), ("22" * 32, now + 1)):
            dash.JOURNEYS.append({"t": t, "pkt": "ab12cd34ef56", "size": 30, "type": "REQ", "flood": True, "hops": 2, "from": "4B",
                                  "path": [{"h": "1A2B", "n": "1A2B"}, {"h": "330D", "n": "330D"}], "to": dev, "snr": 4, "rssi": -90})
        rows = dash.packet_routes()
        self.assertEqual(1, len(rows)); self.assertEqual(2, rows[0]["heard"]); self.assertEqual("TINGLEY", rows[0]["first"])
        self.assertEqual(["1A2B", "330D"], [h["n"] for h in rows[0]["route"]]); self.assertEqual(30, rows[0]["size"])


class GroupScan(unittest.TestCase):
    """The scan finds public hashtag groups by their names, and never reads a private channel."""
    def setUp(self):
        dash.RECENT_GRP.clear(); dash.CONF.clear(); dash.CONF.update(json.loads(json.dumps(dash.DEFAULTS)))

    def _payload(self, ch, text):
        raw = dash.MSG.build_group_text(ch, "Sam", text, int(time.time()))
        return dash.MSG.parse_wire(raw)["payload"]

    def test_a_public_group_heard_is_found_by_its_name_and_a_private_one_is_not(self):
        import base64, os as _os
        pub = dash.MSG.Channel("#leeds"); priv = dash.MSG.Channel("secret-room", base64.b64encode(_os.urandom(16)).decode())   # a random key: no name leads to it
        for i in range(3): dash.RECENT_GRP.append((int(time.time()), self._payload(pub, "hi %d" % i)))
        dash.RECENT_GRP.append((int(time.time()), self._payload(priv, "secret")))
        found = dash.scan_public_groups(["leeds", "sheffield", "secret-room"])
        self.assertEqual(["#leeds"], [g["name"] for g in found]); self.assertEqual(3, found[0]["packets"])

    def test_a_group_already_set_up_is_not_listed_again(self):
        dash.CONF["messages"]["channels"].append({"name": "#leeds"})
        dash.RECENT_GRP.append((int(time.time()), self._payload(dash.MSG.Channel("#leeds"), "x")))
        self.assertEqual([], dash.scan_public_groups(["leeds"]))


class ScopeAudit(unittest.TestCase):
    def test_floods_are_counted_by_scope_per_repeater(self):
        dash.JOURNEYS.clear(); dash.DEV.clear(); now = time.time()
        dash.DEV["11" * 32] = {"id": "11" * 32, "name": "TINGLEY", "last": now}
        for rt, sc in ((0, "yorkshire"), (0, "yorkshire"), (1, ""), (1, ""), (1, ""), (2, "")):
            dash.JOURNEYS.append({"t": now, "pkt": "x", "route_type": rt, "scope": sc, "to": "11" * 32, "from": "aa", "path": [], "hops": 0, "type": "T"})
        a = dash.scope_audit(24)
        self.assertEqual(1, len(a)); r = a[0]
        self.assertEqual((2, 3, 1), (r["scoped"], r["unscoped"], r["direct"])); self.assertEqual({"yorkshire": 2}, r["regions"])


class AdminHelper(unittest.TestCase):
    def test_password_hash_round_trip(self):
        h = adm.pbkdf2("Correct-horse-9"); self.assertTrue(adm.check_password("Correct-horse-9", h)); self.assertFalse(adm.check_password("Correct-horse-8", h)); self.assertFalse(adm.check_password("x", "garbage"))

    def test_weak_new_passwords_are_refused_before_anything_is_touched(self):
        for bad in ("short1A", "alllowercase123456", "NoDigitsHereAtAll"):
            r = adm.change_dash_password("whatever", bad); self.assertFalse(r["ok"]); self.assertIn("12 or more", r["error"])

    def test_the_hash_is_picked_out_of_whatever_caddy_prints(self):
        h = "$2a$14$" + "abcdefghijklmnopqrstuv" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ01234"
        self.assertEqual(h, adm.bcrypt_from(h + "\n"))
        self.assertEqual(h, adm.bcrypt_from("2026/10/25 notice: something\n" + h + "\nmore text\n"))
        self.assertIsNone(adm.bcrypt_from("no hash here"))
        self.assertIsNone(adm.bcrypt_from(None))

    def test_names_and_devices_are_checked(self):
        self.assertFalse(adm.handle({"op": "user_add", "name": "Bad Name"})["ok"])
        self.assertFalse(adm.handle({"op": "user_add", "name": "good-name", "role": "admin"})["ok"])
        self.assertFalse(adm.handle({"op": "user_add", "name": "good-name", "role": "repeater", "device": "XYZ"})["ok"])
        self.assertFalse(adm.handle({"op": "user_remove", "name": "dash"})["ok"])
        self.assertFalse(adm.handle({"op": "user_state", "name": "good-name", "state": "weird"})["ok"])
        self.assertFalse(adm.handle({"op": "service", "name": "ssh", "action": "restart"})["ok"])
        self.assertFalse(adm.handle({"op": "nonsense"})["ok"])



class Telemetry(unittest.TestCase):
    DID = "AB" * 32
    # ch1 voltage 4.10 V, ch2 temperature -5.5 C, ch3 humidity 50 %
    LPP = bytes([1, 116, 0x01, 0x9A, 2, 103]) + (-55).to_bytes(2, "big", signed=True) + bytes([3, 104, 100])
    def setUp(self):
        dash.db_init(); dash.DB.execute("DELETE FROM telem"); dash.DEV.clear()
    def test_decodes_values_with_units_and_signs(self):
        v = {x[2]: (x[3], x[4]) for x in dash.lpp_decode(self.LPP)}
        self.assertEqual({"voltage": (4.1, "V"), "temperature": (-5.5, "°C"), "humidity": (50.0, "%")}, v)
    def test_truncated_or_unknown_never_raises(self):
        self.assertEqual([], dash.lpp_decode(b"\x01"))
        self.assertEqual(1, len(dash.lpp_decode(self.LPP[:4] + b"\x02\xfa\x00")))      # unknown type: keep what was read
        self.assertEqual(1, len(dash.lpp_decode(self.LPP[:4] + bytes([2, 103, 0]))))    # cut mid-value
    def test_skips_multi_value_types(self):
        gps = bytes([9, 136]) + bytes(9)
        self.assertEqual(["voltage"], [x[2] for x in dash.lpp_decode(gps + self.LPP[:4])])
    def test_topic_is_accepted_and_stored(self):
        body = json.dumps({"timestamp": "2026-11-26T13:00:00Z", "origin": "Tingley", "lpp": self.LPP.hex().upper()}).encode()
        dash.on_publish("meshcore/LBA/%s/telemetry" % self.DID, body)
        rows = dash.telem_latest()
        self.assertEqual(3, len(rows)); self.assertEqual({"voltage", "temperature", "humidity"}, {r["sensor"] for r in rows})
        self.assertEqual(self.DID, rows[0]["id"])
    def test_latest_has_min_max_and_series(self):
        now = int(time.time())
        for i, tv in enumerate((10.0, 14.5, 12.0)):
            dash.DB.execute("INSERT INTO telem VALUES(?,?,?,?,?,?,?)", (self.DID, "LBA", now - 600 + i * 60, 2, 103, "temperature", tv))
        r = [x for x in dash.telem_latest() if x["type"] == 103][0]
        self.assertEqual((12.0, 10.0, 14.5, 3), (r["v"], r["min"], r["max"], r["n"]))
        self.assertEqual([10.0, 14.5, 12.0], [v for _, v in dash.telem_series(self.DID, 2, 103, 1)])
    def test_junk_payloads_are_counted_not_fatal(self):
        dash.on_publish("meshcore/LBA/%s/telemetry" % self.DID, b"not json")
        dash.on_publish("meshcore/LBA/%s/telemetry" % self.DID, json.dumps({"lpp": "ZZ"}).encode())
        dash.on_publish("meshcore/LBA/%s/telemetry" % self.DID, json.dumps({"lpp": "00" * 500}).encode())
        self.assertEqual([], dash.telem_latest())
    def test_hostile_json_shapes_are_ignored_not_fatal(self):
        topic = "meshcore/LBA/%s/telemetry" % self.DID
        for body in (b"[1,2]", b"7", b"null", b'"x"', json.dumps({"origin": 12345, "lpp": "0167" + "0110"}).encode()):
            dash.on_publish(topic, body)
        dash.telem_latest(); dash.presence_view(1)                  # must not raise on a numeric origin

    def test_viewers_may_read_telemetry_and_clients_may_not_write_it(self):
        acl = usr.acl_for("phone", {"role": "client", "device": self.DID})
        self.assertIn("topic read meshcore/+/+/telemetry", acl); self.assertNotIn("telemetry", "".join(l for l in acl.splitlines() if "write" in l))


class PresenceTimeline(unittest.TestCase):
    DID = "CD" * 32
    def setUp(self):
        dash.db_init(); dash.DB.execute("DELETE FROM telem"); dash.DEV.clear()
    def seg(self, samples, since=1000, now=5000): return dash.presence_segments(samples, since, now)
    def test_no_readings_is_all_no_data(self):
        self.assertEqual([[1000, 5000, -1]], self.seg([]))
    def test_a_reading_holds_until_the_next_one(self):
        self.assertEqual([[1000, 1100, -1], [1100, 1500, 1], [1500, 2000, 0], [2000, 3000, 1]],
                         [[a, b, s] for a, b, s in self.seg([(1100, 1), (1500, 0), (2000, 1)], 1000, 3000)])
    def test_a_silent_repeater_becomes_no_data_not_a_long_presence(self):
        s = self.seg([(1100, 1)], 1000, 1100 + dash.PRESENCE_GAP + 600)
        self.assertEqual([[1000, 1100, -1], [1100, 1100 + dash.PRESENCE_GAP, 1], [1100 + dash.PRESENCE_GAP, 1100 + dash.PRESENCE_GAP + 600, -1]], s)
    def test_the_reading_before_the_window_carries_in(self):
        self.assertEqual([[1000, 1200, 1], [1200, 1500, 0]], self.seg([(900, 1), (1200, 0)], 1000, 1500))
    def test_segments_tile_the_window_without_gaps_or_overlap(self):
        s = self.seg([(1100, 1), (1600, 0), (1700, 0), (4000, 1), (4100, 1)], 1000, 5000)
        self.assertEqual(1000, s[0][0]); self.assertEqual(5000, s[-1][1])
        for a, b in zip(s, s[1:]): self.assertEqual(a[1], b[0]); self.assertNotEqual(a[2], b[2])
    def test_no_data_never_starts_before_the_window(self):
        s = dash.presence_segments([(100, 1)], 2000, 3000, 1500)
        self.assertEqual(2000, s[0][0]); self.assertEqual(3000, s[-1][1])
        for a, b in zip(s, s[1:]): self.assertEqual(a[1], b[0])
    def test_now_state_follows_a_sample_exactly_at_now(self):
        self.assertEqual(0, dash.presence_now([(100, 1), (5000, 0)], 5000))
        self.assertEqual(1, dash.presence_now([(100, 1)], 150))
        self.assertEqual(-1, dash.presence_now([(100, 1)], 100 + dash.PRESENCE_GAP + 1))
        self.assertEqual(-1, dash.presence_now([], 100))

    def test_view_has_stats_and_movement(self):
        now = 10000
        for ts, v in ((now - 3000, 0), (now - 2400, 1), (now - 1800, 1), (now - 1200, 0), (now - 600, 1)):
            dash.DB.execute("INSERT INTO telem VALUES(?,?,?,?,?,?,?)", (self.DID, "LBA", ts, 20, 102, "presence", v))
        for ts, v in ((now - 2400, 60.0), (now - 600, 40.0)):
            dash.DB.execute("INSERT INTO telem VALUES(?,?,?,?,?,?,?)", (self.DID, "LBA", ts, 21, 120, "percent", v))
        r = dash.presence_view(1, now)[0]
        self.assertEqual(1, r["now_state"]); self.assertEqual(2, r["events"]); self.assertEqual(now, r["last_on"])
        self.assertEqual([[now - 2400, 60.0], [now - 600, 40.0]], [list(x) for x in r["movement"]])
        self.assertTrue(0 < r["occupied_pct"] < 100)

class FlowPulse(unittest.TestCase):
    DID = "EF" * 32
    def test_last_packet_time_is_set_by_a_live_packet_not_a_retained_one(self):
        dash.db_init(); dash.DEV.pop(self.DID, None)
        topic = "meshcore/LBA/%s/packets" % self.DID
        dash.on_publish(topic, json.dumps({"raw": "00", "origin": "R"}).encode(), True)
        self.assertFalse((dash.DEV.get(self.DID) or {}).get("last_pkt"))
        dash.on_publish(topic, json.dumps({"raw": "00", "origin": "R"}).encode())
        self.assertTrue(dash.DEV[self.DID].get("last_pkt"))
        dash.DEV.pop(self.DID, None)

if __name__ == "__main__":
    unittest.main()


class RequestParsing(unittest.TestCase):
    def test_content_length_refuses_negative_and_malformed(self):
        self.assertEqual((0, "bad content length"), dash.content_length("-1"))
        self.assertEqual((0, "bad content length"), dash.content_length("abc"))
        self.assertEqual((0, None), dash.content_length(None))
        self.assertEqual((42, None), dash.content_length("42"))

    def test_body_must_be_a_json_object(self):
        self.assertEqual(({}, "body must be a JSON object"), dash.parse_body(b"[]"))
        self.assertEqual(({}, "body must be a JSON object"), dash.parse_body(b"7"))
        self.assertEqual(({}, "body is not valid JSON"), dash.parse_body(b"{bad"))
        self.assertEqual(({"a": 1}, None), dash.parse_body(b'{"a":1}'))
        self.assertEqual(({}, None), dash.parse_body(b""))



class TrafficStats(unittest.TestCase):
    NODE = "AA" * 32; RX1 = "11" * 32; RX2 = "22" * 32

    def setUp(self):
        dash.DB.execute("DELETE FROM traffic"); dash.DB.execute("DELETE FROM links")
        with dash.TRAFFIC_LOCK: dash.TRAFFIC_BUF.clear()

    def test_counts_are_kept_per_hour_node_receiver_type_and_hops(self):
        now = int(time.time())
        with dash.TRAFFIC_LOCK:
            dash.TRAFFIC_BUF[(now // 3600 * 3600, self.NODE, self.RX1, "ADVERT", 1)] += 2
            dash.TRAFFIC_BUF[(now // 3600 * 3600, self.NODE, self.RX2, "MSG", 3)] += 1
        dash.traffic_flush()
        s = dash.node_stats(self.NODE, 1)
        self.assertEqual(3, s["total"])
        self.assertEqual({"ADVERT": 2, "MSG": 1}, {t["type"]: t["n"] for t in s["types"]})
        self.assertEqual([1, 3], [h["hops"] for h in s["hops"]])
        self.assertEqual(2, s["receivers"][0]["n"])

    def test_repeated_flushes_add_up(self):
        now = int(time.time()); h = now // 3600 * 3600
        for _ in range(2):
            with dash.TRAFFIC_LOCK: dash.TRAFFIC_BUF[(h, self.NODE, self.RX1, "ADVERT", 0)] += 1
            dash.traffic_flush()
        self.assertEqual(2, dash.node_stats(self.NODE, 1)["total"])

    def test_the_series_has_one_point_per_hour(self):
        s = dash.node_stats(self.NODE, 7)
        self.assertEqual(7 * 24 + 1, len(s["series"]))

    def test_days_are_clamped(self):
        self.assertEqual(30, dash.node_stats(self.NODE, 999)["days"])
        self.assertEqual(1, dash.node_stats(self.NODE, 0)["days"])

    def test_one_way_and_deaf_use_only_our_repeaters(self):
        own = {"A": {"id": "A", "name": "Alpha", "last": 0}, "B": {"id": "B", "name": "Bravo", "last": 0}}
        saved = dict(dash.DEV); dash.DEV.clear(); dash.DEV.update(own)
        try:
            now = int(time.time())
            dash.DB.executemany("INSERT INTO links VALUES(?,?,?,?,?,?)", [("A", "B", now, now, -5.0, -90), ("B", "A", now, now, -18.0, -100), ("A", "Z", now, now, 3.0, -60)])
            c = dash.link_checks(48)
            self.assertEqual([], c["one_way"])                       # both directions heard; Z is not ours and is ignored
            self.assertEqual(["Bravo"], [x["name"] for x in c["deaf"]])  # B is heard at -5 dB but hears at best -18 dB: a 13 dB gap
            dash.DB.execute("DELETE FROM links WHERE a='B' AND b='A'")
            c = dash.link_checks(48)
            self.assertEqual([("Alpha", "Bravo")], [(x["hears"], x["heard"]) for x in c["one_way"]])
            self.assertEqual([], c["deaf"])                          # B now hears nothing of ours, so there is no gap to measure
        finally:
            dash.DEV.clear(); dash.DEV.update(saved)

    def test_weekly_report_has_its_sections(self):
        text = dash.weekly_report()
        for head in ("UMC weekly report", "Busiest nodes", "Own repeaters", "One-way hearing", "Possible deaf repeaters"):
            self.assertIn(head, text)


class ValidPosition(unittest.TestCase):
    def test_unset_zero_pair_is_not_a_position(self):
        self.assertFalse(dash.valid_position(0.0, 0.0))

    def test_one_zero_coordinate_is_a_position(self):
        self.assertTrue(dash.valid_position(0.0, -1.5))
        self.assertTrue(dash.valid_position(53.6, 0.0))

    def test_missing_or_out_of_range_is_refused(self):
        self.assertFalse(dash.valid_position(None, -1.5))
        self.assertFalse(dash.valid_position(91, 0))
        self.assertFalse(dash.valid_position(53.6, 181))
        self.assertTrue(dash.valid_position(53.6, -1.5))


class Retention(unittest.TestCase):
    def setUp(self): dash.db_init(); [dash.DB.execute("DELETE FROM " + t) for t in ("traffic", "telem", "airtime", "newnodes")]
    def test_old_rows_go_recent_stay_in_batches(self):
        now = int(time.time()); old = now - 40 * 86400
        dash.DB.executemany("INSERT INTO traffic VALUES(?,?,?,?,?,?)", [(old, "N%d" % i, "R", "ADVERT", 0, 1) for i in range(30)] + [(now // 3600 * 3600, "X", "R", "ADVERT", 0, 1)])
        self.assertEqual(30, dash.prune_batched("traffic", "h", now - 30 * 86400, batch=7))
        self.assertEqual(1, dash.DB.execute("SELECT COUNT(*) FROM traffic").fetchone()[0])
    def test_retention_keeps_what_presence_needs(self):
        now = int(time.time()); dash.CONF["telem_keep_days"] = 8
        dash.DB.execute("INSERT INTO telem VALUES('A','x',?,1,102,'presence',1)", (now - 7 * 86400,)); dash.DB.execute("INSERT INTO telem VALUES('A','x',?,1,102,'presence',1)", (now - 9 * 86400,))
        r = dash.retention_run(now); self.assertEqual(1, r["telem"]); self.assertEqual(1, dash.DB.execute("SELECT COUNT(*) FROM telem").fetchone()[0])
        dash.CONF["telem_keep_days"] = 90
    def test_config_ranges(self):
        self.assertIsNone(dash.conf_update({"traffic_keep_days": 45, "backup_keep": 5})); self.assertIsNotNone(dash.conf_update({"telem_keep_days": 3}))
        dash.conf_update({"traffic_keep_days": 30, "backup_keep": 7})


class Backup(unittest.TestCase):
    def setUp(self):
        dash.db_init(); self.d = tempfile.mkdtemp(); dash.CFG["backup_dir"] = self.d; dash.BACKUP.update({"ts": 0, "ok": None, "error": "", "try": 0, "count": 0})
        dash.DB.execute("DELETE FROM messages"); dash.DB.executemany("INSERT INTO messages(ts,seen,chan,pkey) VALUES(1,1,'c',?)", [("k%d" % i,) for i in range(5)])
    def tearDown(self): dash.CFG["backup_dir"] = ""
    def test_backup_is_atomic_private_and_restorable(self):
        r = dash.backup_run(1700000000)
        self.assertTrue(r["ok"], r["error"]); names = os.listdir(self.d); self.assertEqual(["dash-20231114-221320.sqlite"], names)
        p = os.path.join(self.d, names[0]); self.assertEqual(0o600, os.stat(p).st_mode & 0o777)
        self.assertEqual(5, dash.backup_restore_check(p))
        self.assertFalse([n for n in os.listdir(self.d) if n.startswith(".tmp")])
    def test_keeps_only_the_newest_n_and_ignores_foreign_files(self):
        dash.CONF["backup_keep"] = 3; open(os.path.join(self.d, "notes.txt"), "w").close()
        for i in range(5): dash.backup_run(1700000000 + i * 86400)
        self.assertEqual(3, len([n for n in os.listdir(self.d) if n.startswith("dash-")])); self.assertIn("notes.txt", os.listdir(self.d)); dash.CONF["backup_keep"] = 7
    def test_split_pure(self):
        k, g = dash.backup_split(["dash-20240101-000000.sqlite", "dash-20240103-000000.sqlite", "dash-20240102-000000.sqlite", "x"], 2)
        self.assertEqual(["dash-20240102-000000.sqlite", "dash-20240103-000000.sqlite"], k); self.assertEqual(["dash-20240101-000000.sqlite"], g)
    def test_due_rules(self):
        t = 1700000000; h = time.gmtime(t).tm_hour
        self.assertTrue(dash.backup_due(t, 0, 0, 3)); self.assertFalse(dash.backup_due(t, 0, t - 60, 3))
        self.assertFalse(dash.backup_due(t, t - 3600, 0, h)); self.assertTrue(dash.backup_due(t, t - 25 * 3600, 0, h)); self.assertFalse(dash.backup_due(t, t - 25 * 3600, 0, (h + 1) % 24 if h < 23 else 24))
    def test_low_disk_skips_and_flags(self):
        real = dash.shutil.disk_usage
        class U: free = 10
        dash.shutil.disk_usage = lambda p: U
        try: r = dash.backup_run(1700000000)
        finally: dash.shutil.disk_usage = real
        self.assertFalse(r["ok"]); self.assertIn("skipped", r["error"]); self.assertEqual([], os.listdir(self.d))
    def test_checks_line(self):
        v = {"enabled": True, "ok": True, "ts": int(time.time()), "age": 60, "size": 2e6, "count": 3, "error": ""}
        self.assertEqual("ok", dash.backup_check(v, 10)[0]); self.assertEqual("warn", dash.backup_check(dict(v, age=40 * 3600), 10)[0])
        self.assertEqual("bad", dash.backup_check(dict(v, ok=False, error="x"), 10)[0]); self.assertIsNone(dash.backup_check(dict(v, enabled=False), 10))
        self.assertIsNone(dash.backup_check(dict(v, ts=0, age=None), 10)); self.assertEqual("warn", dash.backup_check(dict(v, ts=0, age=None), 9999)[0])
    def test_overview_exposes_backup(self):
        dash.backup_run(); self.assertTrue(dash.backup_view()["ok"])


class Collisions(unittest.TestCase):
    A = "AB12CD" + "00" * 29; B = "AB12CD" + "11" * 29; C = "AB34EE" + "22" * 29; D = "CC" + "33" * 31
    def test_groups_by_prefix_length_with_severity(self):
        f = dash.collisions_find([(self.A, "a"), (self.B, "b"), (self.C, "c"), (self.D, "d")])
        by = {(c["bytes"], c["prefix"]): c for c in f}
        self.assertEqual("bad", by[(3, "AB12CD")]["level"]); self.assertEqual("warn", by[(2, "AB12")]["level"]); self.assertEqual("info", by[(1, "AB")]["level"])
        self.assertEqual(3, len(by[(1, "AB")]["nodes"])); self.assertNotIn((1, "CC"), by)
    def test_same_key_twice_is_not_a_collision(self): self.assertEqual([], dash.collisions_find([(self.A, "a"), (self.A.lower(), "a")]))
    def test_alerts_only_for_new_2_and_3_byte(self):
        f = dash.collisions_find([(self.A, "a"), (self.B, "b"), (self.C, "c")]); new = dash.collisions_new(f, {})
        self.assertEqual({2, 3}, {c["bytes"] for c in new}); self.assertEqual([], dash.collisions_new(f, {c["id"]: 1 for c in f}))
    def test_id_changes_when_membership_changes(self):
        a = dash.collisions_find([(self.A, ""), (self.B, "")]); b = dash.collisions_find([(self.A, ""), (self.B, ""), ("AB12CD" + "44" * 29, "")])
        self.assertNotEqual({c["id"] for c in a}, {c["id"] for c in b})
    def test_alert_once_and_survives_restart(self):
        dash.NODES.clear(); dash.DEV.clear(); dash.COLL["seen"] = {}; sent = []
        dash.NODES[self.A] = {"name": "a", "type": 2, "last": time.time()}; dash.NODES[self.B] = {"name": "b", "type": 2, "last": time.time()}
        real = dash.send_alert; dash.send_alert = lambda *a, **k: sent.append(a[0])
        try:
            self.assertEqual(2, dash.collision_alerts()); self.assertEqual(0, dash.collision_alerts())
            dash.COLL["seen"] = {}; dash.collisions_load(); self.assertEqual(0, dash.collision_alerts())
        finally: dash.send_alert = real; dash.NODES.clear()
        self.assertEqual(2, len(sent))
    def test_stale_repeaters_expire(self):
        dash.NODES.clear(); dash.DEV.clear()
        dash.NODES[self.A] = {"name": "a", "type": 2, "last": time.time()}; dash.NODES[self.B] = {"name": "b", "type": 2, "last": time.time() - 40 * 86400}
        self.assertEqual([], dash.collisions_view()); dash.NODES.clear()
    def test_checks_wording_is_not_an_accusation(self):
        dash.NODES.clear(); dash.DEV.clear(); dash.NODES[self.A] = {"name": "a", "type": 2, "last": time.time()}; dash.NODES[self.B] = {"name": "b", "type": 2, "last": time.time()}
        txt = json.dumps(dash.extra_diagnostics(time.time())); dash.NODES.clear()
        self.assertIn("not a sign of a stolen key", txt)


class Airtime(unittest.TestCase):
    DID = "EE" * 32
    def setUp(self): dash.db_init(); dash.DB.execute("DELETE FROM airtime"); dash.AIR_LAST.clear(); dash.ALERT_STATE.clear(); dash.DEV.clear()
    def test_steps_skip_resets_boot_changes_and_gaps(self):
        rows = [(0, 0, 0, "A"), (60, 6, 3, "A"), (120, 1, 0, "A"), (180, 7, 1, "A"), (240, 9, 2, "B"), (300, 12, 3, "B"), (5000, 20, 4, "B")]
        st = dash.duty_steps(rows)
        self.assertEqual([(60, 60, 6, 3), (180, 60, 6, 1), (300, 60, 3, 1)], st)
    def test_missing_data_is_not_zero(self):
        self.assertEqual([], dash.duty_buckets([], 0, 1000)); self.assertEqual((None, 0), dash.duty_window([], 0))
    def test_buckets_and_window(self):
        st = [(t, 60, 6, 3) for t in range(60, 1860, 60)]
        self.assertAlmostEqual(10.0, dash.duty_window(st, 0)[0]); self.assertEqual(1800, dash.duty_window(st, 0)[1])
        b = dash.duty_buckets(st, 0, 1800, n=3); self.assertEqual(3, len(b)); self.assertTrue(all(abs(x[1] - 10) < 0.01 and abs(x[2] - 5) < 0.01 for x in b))
    def test_alert_hysteresis_cooldown_and_gaps(self):
        f = dash.duty_alert_step
        self.assertEqual("fire", f(False, 12, 900, 10, 15)); self.assertIsNone(f(True, 12, 900, 10, 15)); self.assertIsNone(f(True, 9, 900, 10, 15))
        self.assertEqual("recover", f(True, 7, 900, 10, 15)); self.assertIsNone(f(False, 12, 100, 10, 15)); self.assertIsNone(f(True, None, 0, 10, 15))
        self.assertIsNone(f(False, 12, 900, 10, 15, since_recover=60)); self.assertEqual("fire", f(False, 12, 900, 10, 15, since_recover=7200))
    def test_status_is_stored_throttled_and_viewed(self):
        now = time.time() - 1800
        for i in range(30):
            dash.airtime_note(self.DID, {"tx_air_secs": 6 * i, "rx_air_secs": 3 * i}, now + i * 60, "AA")
        self.assertEqual(30, dash.DB.execute("SELECT COUNT(*) FROM airtime").fetchone()[0])
        self.assertFalse(dash.airtime_note(self.DID, {"tx_air_secs": 1}, now + 29 * 60 + 10))
        v = dash.airtime_view(1); self.assertEqual(1, len(v["devices"])); self.assertAlmostEqual(10.0, v["devices"][0]["tx_avg"], 1)
        self.assertFalse(dash.airtime_note("x", {"tx_air_secs": "nope"}, now))
    def test_alert_fires_once_then_recovers(self):
        sent = []; real = dash.send_alert; dash.send_alert = lambda t, *a, **k: sent.append(t); now = int(time.time()); dash.CONF["airtime_warn_pct"] = 10; dash.CONF["airtime_warn_minutes"] = 15
        try:
            for i in range(20): dash.DB.execute("INSERT INTO airtime VALUES(?,?,?,?,?)", (self.DID, now - 1200 + i * 60, i * 9.0, 0, "A"))
            dash.airtime_alerts(now); dash.airtime_alerts(now + 1); self.assertEqual(1, len(sent))
            dash.DB.execute("DELETE FROM airtime")
            for i in range(20): dash.DB.execute("INSERT INTO airtime VALUES(?,?,?,?,?)", (self.DID, now + 1 + i * 60, 200 + i * 1.0, 0, "A"))
            dash.airtime_alerts(now + 1200); self.assertEqual(2, len(sent)); self.assertTrue(sent[1].startswith("Airtime back"))
        finally: dash.send_alert = real
    def test_boot_id(self):
        d = {}
        self.assertFalse(dash.boot_note(d, None, 1)); self.assertNotIn("boot_id", d)
        self.assertFalse(dash.boot_note(d, "00AB00AB00AB00AB", 1)); self.assertFalse(dash.boot_note(d, "00ab00ab00ab00ab", 2))
        self.assertTrue(dash.boot_note(d, "1122334455667788", 3)); self.assertEqual((3, 1), (d["boot_changed"], d["reboots"]))
        self.assertFalse(dash.boot_note(d, 12345, 4)); self.assertEqual("1122334455667788", d["boot_id"])


class NewNodes(unittest.TestCase):
    def setUp(self): dash.db_init(); dash.DB.execute("DELETE FROM newnodes"); dash.NEWNODE_ALERTS.clear(); dash.NODES.clear(); dash.DEV.clear()
    def test_decide(self):
        d = dash.newnode_decide
        self.assertEqual("warmup", d(100, 90, 60, [], 6)); self.assertEqual("alert", d(200, 90, 60, [], 6)); self.assertEqual("capped", d(200, 0, 60, [150] * 6, 6)); self.assertEqual("alert", d(5000, 0, 60, [150] * 6, 6))
    def test_alert_listed_deduped_and_capped(self):
        sent = []; real = dash.send_alert; dash.send_alert = lambda t, *a, **k: sent.append(t); dash.CONF["newnode_warmup_minutes"] = 0; dash.CONF["newnode_max_per_hour"] = 2
        try:
            for i in range(4): dash.newnode_seen("%02X" % i * 32, {"name": "n%d" % i, "type": 2}, "R" * 64, time.time())
            self.assertEqual("known", dash.newnode_seen("00" * 32, {"name": "n0", "type": 2}, "R", time.time()))
        finally: dash.send_alert = real; dash.CONF["newnode_warmup_minutes"] = 30; dash.CONF["newnode_max_per_hour"] = 6
        self.assertEqual(2, len(sent)); self.assertEqual(["capped", "capped", "alert", "alert"], [n["state"] for n in dash.newnodes_recent()])
    def test_warmup_is_silent_but_listed(self):
        sent = []; real = dash.send_alert; dash.send_alert = lambda t, *a, **k: sent.append(t)
        try: self.assertEqual("warmup", dash.newnode_seen("AA" * 32, {"name": "n", "type": 1}, "R" * 64, dash.START + 1))
        finally: dash.send_alert = real
        self.assertEqual([], sent); self.assertEqual(1, len(dash.newnodes_recent()))
    def test_baseline_is_silent_hidden_and_persistent(self):
        dash.NODES["AA" * 32] = {"name": "old", "type": 2, "first": 5}
        self.assertEqual(1, dash.newnodes_baseline()); self.assertEqual(0, dash.newnodes_baseline()); self.assertEqual([], dash.newnodes_recent())
        dash.NODES.clear(); sent = []; real = dash.send_alert; dash.send_alert = lambda t, *a, **k: sent.append(t); dash.CONF["newnode_warmup_minutes"] = 0
        try: self.assertEqual("known", dash.newnode_seen("AA" * 32, {"name": "old", "type": 2}, "R", time.time()))     # NODES forgot it, the table did not
        finally: dash.send_alert = real; dash.CONF["newnode_warmup_minutes"] = 30
        self.assertEqual([], sent)
    def test_note_network_hook(self):
        key = "77" * 32; body = bytes.fromhex(key) + bytes(4) + bytes(64) + bytes([0x82]) + b"Hill"
        raw = bytes([(4 << 2) | 1, 0]) + body
        dash.note_network("R" * 64, dash.parse_packet(raw), 1, -90, time.time())
        self.assertEqual([key.upper()], [n["key"] for n in dash.newnodes_recent()])


class RouteHealth(unittest.TestCase):
    RX = "AA" * 32
    def setUp(self):
        dash.db_init(); [dash.DB.execute("DELETE FROM " + t) for t in ("routes", "snr", "traffic", "alertstate")]
        dash.ROUTE_BUF.clear(); dash.SNR_BUF.clear(); dash.TRAFFIC_BUF.clear(); dash.DEV.clear(); dash.NODES.clear()
        self.now = int(time.time()); dash.DEV[self.RX] = {"id": self.RX, "name": "Hilltop", "last": self.now, "first": 0}
        self.start = dash.START; dash.START = self.now - 10 * 86400
    def tearDown(self): dash.START = self.start; dash.CONF["alerts"]["route_silent"] = False
    def put(self, path, ago_s, n=1, rx=None):
        t = self.now - ago_s
        dash.DB.execute("INSERT INTO routes VALUES(?,?,?,?,?) ON CONFLICT(h,path,rx) DO UPDATE SET n=n+excluded.n, last=MAX(last,excluded.last)", (t // 3600 * 3600, path, rx or self.RX, n, t))
    def test_state_rules(self):
        s = dash.route_state
        self.assertEqual(("live", ""), s(60, 3600, 43200, True, 10 ** 6)); self.assertEqual("stale", s(7200, 3600, 43200, True, 10 ** 6)[0])
        self.assertEqual("silent", s(50000, 3600, 43200, True, 10 ** 6)[0])
        self.assertEqual("unknown", s(50000, 3600, 43200, False, 10 ** 6)[0]); self.assertEqual("unknown", s(50000, 3600, 43200, True, 600)[0])
        self.assertEqual("live", s(60, 3600, 43200, True, 5)[0])             # fresh evidence needs no long watching
    def test_note_records_flood_paths_only(self):
        info = {"type": "CHAN", "flood": True, "hops": 2, "path": ["A1", "B2"], "pkt": None}
        dash.note_network(self.RX, info, 5.5, -90, self.now); dash.note_network(self.RX, dict(info), 5.5, -90, self.now + 1)
        dash.note_network(self.RX, {"type": "REQ", "flood": False, "hops": 2, "path": ["A1", "B2"], "src": "", "pkt": None}, 5, -90, self.now)
        dash.note_network(self.RX, {"type": "CHAN", "flood": True, "hops": 0, "path": [], "src": "", "pkt": None}, 5, -90, self.now)
        dash.traffic_flush()
        self.assertEqual([("A1,B2", self.RX, 2)], dash.DB.execute("SELECT path, rx, n FROM routes").fetchall())
    def test_view_counts_windows_and_labels(self):
        self.put("A1,B2", 600, 5); self.put("A1,B2", 30 * 3600, 7); self.put("C3", 8 * 86400, 9)
        v = dash.route_view(self.now); self.assertEqual(1, v["total"]); r = v["routes"][0]
        self.assertEqual((5, 12, "live"), (r["n24"], r["n7d"], r["state"])); self.assertEqual(["A1", "B2"], [h["h"] for h in r["path"]]); self.assertEqual("Hilltop", r["rx_name"])
        self.assertIn("Not a measure of link quality", v["note"])
    def test_silent_needs_connected_receiver_and_a_long_enough_watch(self):
        self.put("A1", 2 * 86400, 30); self.assertEqual("silent", dash.route_view(self.now)["routes"][0]["state"])
        dash.DEV[self.RX]["last"] = self.now - 7200; self.assertEqual("unknown", dash.route_view(self.now)["routes"][0]["state"])
        dash.DEV[self.RX]["last"] = self.now; dash.START = self.now - 600; self.assertEqual("unknown", dash.route_view(self.now)["routes"][0]["state"])
        dash.DEV.clear(); dash.START = self.now - 10 * 86400; self.assertEqual("unknown", dash.route_view(self.now)["routes"][0]["state"])
    def test_alert_step_hysteresis_and_cooldown(self):
        f = dash.route_alert_step
        self.assertEqual("fire", f(False, "silent", True)); self.assertIsNone(f(False, "silent", False)); self.assertIsNone(f(False, "unknown", True)); self.assertIsNone(f(True, "silent", True))
        self.assertIsNone(f(True, "stale", True)); self.assertIsNone(f(True, "unknown", True)); self.assertEqual("recover", f(True, "live", True))
        self.assertIsNone(f(False, "silent", True, since_recover=60)); self.assertEqual("fire", f(False, "silent", True, since_recover=10 ** 6))
    def test_alert_off_by_default_once_persistent_and_grouped(self):
        sent = []; real = dash.send_alert; dash.send_alert = lambda t, *a, **k: sent.append(t)
        try:
            self.assertFalse(dash.CONF["alerts"]["route_silent"])
            self.put("A1", 2 * 86400, 30); dash.route_alerts(self.now); dash.route_alerts(self.now + 60); self.assertEqual(1, len(sent))
            dash.ALERT_STATE.clear(); dash.route_alerts(self.now + 120); self.assertEqual(1, len(sent))          # a restart changes nothing: the state is in the database
            self.put("A1", 60, 1); dash.route_alerts(self.now); self.assertEqual(2, len(sent)); self.assertTrue(sent[1].startswith("Route back"))
            self.put("A1", 3 * 86400, 0); dash.DB.execute("DELETE FROM routes"); dash.route_alerts(self.now); self.assertEqual([], dash.alert_keys("route:"))
            for i in range(5): self.put("B%d" % i, 2 * 86400, 30)
            sent.clear(); dash.route_alerts(self.now); self.assertEqual(1, len(sent)); self.assertIn("5 routes", sent[0])
        finally: dash.send_alert = real
    def test_busy_threshold_blocks_quiet_routes(self):
        sent = []; real = dash.send_alert; dash.send_alert = lambda t, *a, **k: sent.append(t)
        try: self.put("Q1", 2 * 86400, 3); dash.route_alerts(self.now); self.assertEqual([], sent)
        finally: dash.send_alert = real
    def test_live_must_be_below_silent(self):
        self.assertIsNotNone(dash.conf_update({"route_live_minutes": 900, "route_silent_minutes": 600})); self.assertEqual(60, dash.CONF["route_live_minutes"])
        self.assertIsNone(dash.conf_update({"route_live_minutes": 30, "route_silent_minutes": 600, "alerts": {"route_silent": True}})); self.assertTrue(dash.CONF["alerts"]["route_silent"])
        dash.conf_update({"route_live_minutes": 60, "route_silent_minutes": 720, "alerts": {"route_silent": False}})
    def test_retention_trims_routes_and_snr(self):
        self.put("A1", 40 * 86400); dash.DB.execute("INSERT INTO snr VALUES(?,?,?,?,?,?)", (self.now - 40 * 86400, "N", 1, 1.0, 1.0, 1.0)); self.put("A1", 60)
        r = dash.retention_run(self.now); self.assertEqual((1, 1), (r["routes"], r["snr"])); self.assertEqual(1, dash.DB.execute("SELECT COUNT(*) FROM routes").fetchone()[0])


class NodeAnalytics(unittest.TestCase):
    RX = "AA" * 32; N = "BB" * 32
    def setUp(self):
        dash.db_init(); [dash.DB.execute("DELETE FROM " + t) for t in ("routes", "snr", "traffic")]
        dash.ROUTE_BUF.clear(); dash.SNR_BUF.clear(); dash.TRAFFIC_BUF.clear(); dash.NODES.clear()
        self.now = (int(time.time()) // 3600) * 3600 + 120
    def traffic(self, ago_h, node=None, hops=0, n=1): dash.DB.execute("INSERT INTO traffic VALUES(?,?,?,?,?,?) ON CONFLICT(h,node,rx,ptype,hops) DO UPDATE SET n=n+excluded.n", (self.now // 3600 * 3600 - ago_h * 3600, node or self.N, self.RX, "ADVERT", hops, n))
    def test_snr_only_for_direct_flood_and_missing_is_not_zero(self):
        for hops, flood, snr in ((0, True, 6.5), (0, True, None), (0, True, "bad"), (0, True, float("nan")), (2, True, 3.0), (0, False, 4.0)):
            dash.note_network(self.RX, {"type": "ADVERT", "flood": flood, "hops": hops, "path": ["A1"] * hops, "fkey": self.N, "name": "n", "atype": 2, "pkt": None}, snr, -90, self.now)
        dash.traffic_flush(); r = dash.DB.execute("SELECT n, s, lo, hi FROM snr").fetchall()
        self.assertEqual([(1, 6.5, 6.5, 6.5)], r)
    def test_snr_aggregates_per_hour(self):
        for v in (4, 8, 6): dash.snr_note(self.N, v, self.now)
        dash.snr_note(self.N, -2, self.now - 3600); dash.traffic_flush(); dash.snr_note(self.N, 10, self.now); dash.traffic_flush()
        a = dash.node_analytics(self.N, 1, self.now)["snr"]; self.assertEqual(2, len(a["points"]))
        self.assertEqual([-2.0, -2.0, -2.0, 1], a["points"][0][1:]); self.assertEqual([7.0, 4, 10, 4], a["points"][1][1:])
        self.assertEqual({"n": 5, "avg": 5.2, "min": -2.0, "max": 10.0}, {k: a["summary"][k] for k in ("n", "avg", "min", "max")})
    def test_no_snr_data_is_none_not_zero(self):
        self.traffic(1); a = dash.node_analytics(self.N, 7, self.now); self.assertIsNone(a["snr"]); self.assertEqual(1, a["total"])
        self.assertIsNone(dash.node_analytics("CC" * 32, 7, self.now)["snr"])
    def test_hops_distribution_and_window(self):
        self.traffic(1, hops=0, n=3); self.traffic(2, hops=2, n=5); self.traffic(24 * 10, hops=1, n=9)
        a = dash.node_analytics(self.N, 7, self.now); self.assertEqual([{"hops": 0, "n": 3}, {"hops": 2, "n": 5}], a["hops"]); self.assertEqual(8, a["total"])
        self.assertEqual(8 + 9, dash.node_analytics(self.N, 30, self.now)["total"])
    def test_heatmap_distinguishes_no_data_from_zero(self):
        self.traffic(1, n=4); self.traffic(5, node="CC" * 32, n=2)           # hour -1 has our node; hour -5 only another node (so it was being recorded)
        a = dash.node_analytics(self.N, 7, self.now); cells = {d["day"] + i * 3600: c for d in a["heatmap"]["days"] for i, c in enumerate(d["h"])}
        cur = self.now // 3600 * 3600
        self.assertEqual(4, cells[cur - 3600]); self.assertEqual(0, cells[cur - 5 * 3600]); self.assertIsNone(cells[cur - 7 * 3600]); self.assertNotIn(cur + 3600, [k for k, c in cells.items() if c is not None])
        self.assertTrue(a["heatmap"]["utc"]); self.assertTrue(all(len(d["h"]) == 24 for d in a["heatmap"]["days"]))
        self.assertEqual([], [d for d in dash.node_analytics(self.N, 7, self.now - 20 * 86400)["heatmap"]["days"] if any(c is not None for c in d["h"])])
    def test_picker_and_name(self):
        dash.NODES[self.N] = {"name": "Hill"}; self.traffic(1, n=2); c = dash.node_choices(now=self.now); self.assertEqual([(self.N, "Hill", 2)], [(x["id"], x["name"], x["n"]) for x in c])
        self.assertEqual("Hill", dash.node_analytics(self.N, 7, self.now)["name"])


class BatteryTrend(unittest.TestCase):
    D = "DD" * 32
    def setUp(self): dash.db_init(); dash.DB.execute("DELETE FROM telem"); dash.DEV.clear(); self.now = int(time.time())
    def rows(self, hours, v0, slope, every=900, end_ago=0):
        n = int(hours * 3600 / every); t1 = self.now - end_ago
        return [(t1 - (n - i) * every, v0 + slope * (i * every / 3600.0)) for i in range(n + 1)]
    def test_falling_gives_an_estimate(self):
        r = self.rows(10, 4.0, -0.02); est, why = dash.battery_estimate(r, self.now, 3.5)
        self.assertEqual("", why); self.assertAlmostEqual(-0.02, est["slope_v_per_h"], 3); last = r[-1][1]; self.assertAlmostEqual((last - 3.5) / 0.02, est["eta_hours"], 0)
    def test_needs_six_hours_and_recent_data(self):
        self.assertIn("6 hours", dash.battery_estimate(self.rows(5, 4.0, -0.02), self.now, 3.5)[1])
        self.assertIn("last hour", dash.battery_estimate(self.rows(10, 4.0, -0.02, end_ago=7200), self.now, 3.5)[1])
        self.assertEqual((None, "not enough readings"), dash.battery_estimate([], self.now, 3.5)); self.assertEqual((None, "not enough readings"), dash.battery_estimate([(self.now, 4.0)], self.now, 3.5))
    def test_flat_or_rising_gives_none(self):
        self.assertEqual("not falling", dash.battery_estimate(self.rows(10, 3.9, 0.0), self.now, 3.5)[1]); self.assertEqual("not falling", dash.battery_estimate(self.rows(10, 3.6, 0.02), self.now, 3.5)[1])
    def test_charge_or_gap_restarts_the_basis(self):
        r = self.rows(12, 4.0, -0.02); r = [(t, v + (0.4 if t > r[len(r) // 2][0] else 0)) for t, v in r]        # a step up in the middle: a charge
        est, why = dash.battery_estimate(r, self.now, 3.5)
        self.assertTrue(est is None or est["basis_hours"] < 7)
        g = [(self.now - 10 * 3600 + i * 900, 4.0 - 0.02 * i * 0.25) for i in range(20)] + [(self.now - 2 * 3600 + i * 900, 3.9 - 0.005 * i) for i in range(9)]       # a 3.25 h hole in the readings
        est, why = dash.battery_estimate(g, self.now, 3.5); self.assertIsNone(est); self.assertIn("6 hours", why)
    def test_noisy_sawtooth_is_not_estimated(self):
        r = [(self.now - (40 - i) * 900, 3.8 + (0.1 if i % 2 else -0.1) + (i % 10) * 0.0) for i in range(41)]
        self.assertIsNone(dash.battery_estimate(r, self.now, 3.5)[0])
        w = [(self.now - (40 - i) * 900, 3.8 + (0.04 if i % 2 else -0.04)) for i in range(41)]; self.assertEqual("not falling", dash.battery_estimate(w, self.now, 3.5)[1])
    def test_already_low_is_zero_hours(self):
        est, _ = dash.battery_estimate(self.rows(10, 3.55, -0.02), self.now, 3.5); self.assertEqual(0.0, est["eta_hours"])
    def test_view_ranges_and_missing_devices(self):
        for t, v in self.rows(10, 4.0, -0.02): dash.DB.execute("INSERT INTO telem VALUES(?,?,?,?,?,?,?)", (self.D, "x", t, 1, 116, "voltage", v))
        dash.DB.execute("INSERT INTO telem VALUES(?,?,?,?,?,?,?)", ("EE" * 32, "x", self.now, 2, 116, "voltage", 3.9))        # not channel 1: not the repeater's own battery
        v = dash.battery_view(24, self.now); self.assertEqual([self.D], [d["id"] for d in v["devices"]]); self.assertIsNotNone(v["devices"][0]["est"]); self.assertIn("rough guide", v["note"])
        v1 = dash.battery_view(1, self.now); self.assertIsNone(v1["devices"][0]["est"]); self.assertIn("6 hours", v1["devices"][0]["why"])
        self.assertEqual(24, dash.battery_view(7, self.now)["hours"]); self.assertEqual([], dash.battery_view(24, self.now, allowed=set())["devices"])
        self.assertEqual([], dash.battery_view(1, self.now + 5 * 3600)["devices"])           # no readings in the range: absent, not zero
    def test_low_limit_is_configurable(self):
        self.assertIsNone(dash.conf_update({"battery_low_mv": 3600})); self.assertEqual(3.6, dash.battery_view(24, self.now)["low_v"]); self.assertIsNotNone(dash.conf_update({"battery_low_mv": 2000})); dash.conf_update({"battery_low_mv": 3500})


class SilentThreshold(unittest.TestCase):
    D = "DD" * 32
    def setUp(self):
        dash.db_init(); dash.DB.execute("DELETE FROM alertstate"); dash.DEV.clear(); dash.CONF["silent_overrides"] = {}; dash.CONF["stale_minutes"] = 15; self.now = int(time.time())
        dash.DEV[self.D] = {"id": self.D, "name": "Hill", "last": self.now, "first": 0}; self.m = dict(dash.MQTT); dash.MQTT.update(state="connected", since=self.now - 3600)
    def tearDown(self): dash.MQTT.clear(); dash.MQTT.update(self.m); dash.CONF["silent_overrides"] = {}
    def test_threshold_override_and_default(self):
        self.assertEqual(15, dash.silent_minutes(self.D)); dash.CONF["silent_overrides"] = {self.D: 45}; self.assertEqual(45, dash.silent_minutes(self.D)); self.assertEqual(15, dash.silent_minutes("EE" * 32))
    def test_config_validation_merge_and_clear(self):
        self.assertIsNone(dash.conf_update({"silent_overrides": {self.D: "30"}})); self.assertEqual({self.D: 30}, dash.CONF["silent_overrides"])
        self.assertIsNone(dash.conf_update({"silent_overrides": {("ee" * 32): 60}})); self.assertEqual(2, len(dash.CONF["silent_overrides"]))     # merged, lower case accepted
        for bad in ({"x": 5}, {self.D: 1}, {self.D: 5000}, {self.D: "abc"}, [1]): self.assertIsNotNone(dash.conf_update({"silent_overrides": bad}))
        self.assertEqual(2, len(dash.CONF["silent_overrides"]))
        self.assertIsNone(dash.conf_update({"silent_overrides": {self.D: ""}, "alerts": {}})); self.assertNotIn(self.D, dash.CONF["silent_overrides"])
    def test_step_cooldown_hysteresis_unknown(self):
        f = dash.silent_step
        self.assertEqual("fire", f(False, 1000, 900)); self.assertIsNone(f(False, 800, 900)); self.assertIsNone(f(True, 1000, 900)); self.assertIsNone(f(True, 600, 900)); self.assertEqual("recover", f(True, 100, 900))
        self.assertIsNone(f(False, None, 900)); self.assertIsNone(f(True, None, 900))
        self.assertIsNone(f(False, 1000, 900, since_recover=100)); self.assertEqual("fire", f(False, 1000, 900, since_recover=7200))
    def test_alerts_fire_once_use_override_recover_and_persist(self):
        sent = []; real = dash.send_alert; dash.send_alert = lambda t, *a, **k: sent.append(t); dash.CONF["alerts"].update(offline=True, online=True)
        try:
            dash.DEV[self.D]["last"] = self.now - 20 * 60
            dash.CONF["silent_overrides"] = {self.D: 30}; self.assertEqual([], dash.silent_alerts(self.now)); self.assertEqual([], sent)           # 20 min is fine under its own 30
            dash.CONF["silent_overrides"] = {}; self.assertEqual([("fire", "Hill")], dash.silent_alerts(self.now)); dash.silent_alerts(self.now + 30); self.assertEqual(1, len(sent))
            self.assertEqual("active", dash.alert_get("off:" + self.D)[0])
            dash.DEV[self.D]["last"] = self.now + 60; self.assertEqual([("recover", "Hill")], dash.silent_alerts(self.now + 61)); self.assertTrue(sent[1].startswith("Repeater back"))
            dash.DEV[self.D]["last"] = self.now - 3600 + 100; self.assertEqual([], dash.silent_alerts(self.now + 1000))             # silent again inside the cooldown: held back
            self.assertEqual([("fire", "Hill")], dash.silent_alerts(self.now + 61 + dash.SILENT_COOLDOWN + 5))
        finally: dash.send_alert = real
    def test_never_heard_and_dead_broker_link_are_not_silence(self):
        dash.DEV[self.D]["last"] = 0; self.assertEqual([], dash.silent_alerts(self.now))
        dash.DEV[self.D]["last"] = self.now - 3600; dash.MQTT["state"] = "connecting"; self.assertEqual([], dash.silent_alerts(self.now))
        dash.MQTT.update(state="connected", since=self.now - 5); self.assertEqual([], dash.silent_alerts(self.now))
        dash.MQTT["since"] = self.now - 600; self.assertEqual(1, len(dash.silent_alerts(self.now)))
    def test_checks_line_uses_the_override(self):
        dash.DEV[self.D].update(last=self.now - 20 * 60, skew=None, status="online"); dash.CONF["silent_overrides"] = {self.D: 60}
        titles = [d["title"] for d in dash.diagnostics(dash.system(), [], None) if "No data from Hill" in d["title"]]; self.assertEqual([], titles)
        dash.CONF["silent_overrides"] = {}; self.assertTrue([d for d in dash.diagnostics(dash.system(), [], None) if "No data from Hill" in d["title"]])


class OneByteClashStaysAQuietLine(unittest.TestCase):
    def test_single_ok_line_not_a_warning(self):
        dash.NODES.clear(); dash.DEV.clear(); now = time.time()
        for i in range(3): dash.NODES[("%02X" % 0xA1) + "%062X" % i] = {"name": "r%d" % i, "type": 2, "last": now}
        out = [d for d in dash.extra_diagnostics(now) if "1-byte" in d["title"]]; self.assertEqual(1, len(out)); self.assertEqual("ok", out[0]["level"]); dash.NODES.clear()


# ----------------------------------------------------------------------------- 2.36: map publishing, hop advice, SNR trend, clock drift, TX advice
import struct as _st

def make_advert(seed=b"\x01" * 32, ts=1760000000, name="Hill", lat=53.5, lon=-1.4, path=(), atype=2, tamper=False):
    prv, pub = dash.ENR.ed_keypair(seed)
    app = bytes([atype | (0x10 if lat is not None else 0) | 0x80]) + (_st.pack("<ii", int(lat * 1e6), int(lon * 1e6)) if lat is not None else b"") + name.encode()
    t4 = _st.pack("<I", ts); sig = dash.ENR.ed_sign(prv, pub, pub + t4 + app)
    payload = pub + t4 + sig + app
    if tamper: payload = payload[:-1] + bytes([payload[-1] ^ 1])
    return pub.hex().upper(), bytes([(4 << 2) | 1, len(path)]) + bytes(path) + payload


class MapPublish(unittest.TestCase):
    def setUp(self):
        dash.db_init(); [dash.DB.execute("DELETE FROM " + t) for t in ("adverts", "clockdrift", "audit")]
        dash.DEV.clear(); dash.NODES.clear(); dash.ADV_LAST.clear(); dash.ADV_BUDGET.clear(); dash.MAP_LAST.clear()
        self.now = int(time.time()); self.key, self.pkt = make_advert(path=(0xAA, 0xBB), ts=self.now)
        dash.DEV[self.key] = {"id": self.key, "name": "Hill", "last": self.now, "first": 0, "skew": None}
        dash.CONF["map_publish"] = True; dash.CONF["web_users"] = {"bob": {"role": "owner", "devices": [self.key]}}
        self.sent = []; dash.MAP_SEND = lambda req: (self.sent.append(req) or (200, b'{"ok":true}'))
    def tearDown(self): dash.MAP_SEND = None; dash.CONF["map_publish"] = False; dash.CONF["web_users"] = {}
    def hear(self, pkt=None):
        info = dash.parse_packet(pkt or self.pkt); dash.note_network("BB" * 32, info, 5.0, -90, self.now); return info
    def audit_rows(self): return dash.DB.execute("SELECT who, action, ok, detail FROM audit WHERE action='map publish'").fetchall()

    def test_signature_checked_and_path_stripped_before_storing(self):
        self.hear()
        raw = dash.DB.execute("SELECT raw FROM adverts WHERE key=?", (self.key,)).fetchone()[0]
        self.assertEqual(bytes([(4 << 2) | 1, 0]), bytes.fromhex(raw)[:2]); self.assertEqual(self.pkt[2 + 2:], bytes.fromhex(raw)[2:])
        self.assertEqual("meshcore://" + raw, dash.map_uri(bytes.fromhex(raw)))
    def test_forged_or_foreign_adverts_are_not_stored(self):
        k2, bad = make_advert(tamper=True, ts=self.now); dash.DEV[k2] = {"id": k2, "name": "x", "last": 1, "first": 0}
        n = dash.COUNT["advert_badsig"]; self.hear(bad); self.assertEqual(n + 1, dash.COUNT["advert_badsig"]); self.assertEqual(0, dash.DB.execute("SELECT COUNT(*) FROM adverts").fetchone()[0])
        k3, other = make_advert(seed=b"\x07" * 32, ts=self.now); self.hear(other)              # verified, but not one of ours: no advert kept
        self.assertEqual(0, dash.DB.execute("SELECT COUNT(*) FROM adverts").fetchone()[0])
        self.assertEqual(1, dash.DB.execute("SELECT COUNT(*) FROM clockdrift WHERE key=?", (k3,)).fetchone()[0])
    def test_an_older_advert_never_replaces_a_newer_one_and_checks_are_throttled(self):
        self.hear(); _, older = make_advert(ts=self.now - 500); dash.ADV_LAST.clear(); self.hear(older)
        self.assertEqual(self.now, dash.DB.execute("SELECT ats FROM adverts").fetchone()[0])
        dash.ADV_LAST.clear(); _, newer = make_advert(ts=self.now + 5); self.hear(newer); self.assertEqual(self.now + 5, dash.DB.execute("SELECT ats FROM adverts").fetchone()[0])
        before = dash.ADV_BUDGET.copy(); _, again = make_advert(ts=self.now + 9); self.hear(again); self.assertEqual(before, dash.ADV_BUDGET)       # inside the gap: not even checked
    def test_own_transmitted_advert_is_kept_too(self):
        info = dash.parse_packet(make_advert(ts=self.now)[1]); self.assertTrue(dash.advert_note(self.key, info, self.now)); self.assertEqual(1, dash.DB.execute("SELECT COUNT(*) FROM adverts").fetchone()[0])
    def test_map_uri_refuses_anything_not_a_clean_signed_advert(self):
        _, bad = make_advert(tamper=True)
        for pkt in (bad, self.pkt, b"", b"\x11\x00" + b"\x00" * 120): self.assertRaises(ValueError, dash.map_uri, pkt)      # forged, still has a path, empty, garbage
    def test_request_builder(self):
        self.hear(); uri = dash.map_uri(bytes.fromhex(dash.DB.execute("SELECT raw FROM adverts").fetchone()[0])); r = dash.map_request(uri)
        self.assertEqual("https://map.meshcore.dev/api/v1/nodes", r.full_url); self.assertEqual("POST", r.get_method()); self.assertEqual({"links": [uri]}, json.loads(r.data))
        self.assertEqual("application/json", r.get_header("Content-type"))
        for bad in ("http://x", "meshcore://zz", "", None, "meshcore://" + "a" * 10): self.assertRaises(ValueError, dash.map_request, bad)
    def test_never_follows_a_redirect(self):
        self.assertIsNone(dash._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))
    def test_gates_in_order_and_audit(self):
        self.hear(); p = dash.map_publish
        self.assertIn("only the administrator", p("bob", self.key, True)["error"])
        dash.CONF["map_publish"] = False; self.assertIn("switched off", p("admin", self.key, True)["error"]); dash.CONF["map_publish"] = True
        self.assertIn("no such repeater", p("admin", "00" * 32, True)["error"]); self.assertIn("no such repeater", p("admin", "zz", True)["error"])
        r = p("admin", self.key, False); self.assertTrue(r["needs_confirm"]); self.assertFalse(r["ok"]); self.assertEqual([], self.sent)              # no confirmation, no request
        self.assertEqual(4, len([a for a in self.audit_rows() if not a[2]]))             # every refusal is audited; the confirmation request is not an action
    def test_publish_sends_once_shows_the_status_and_rate_limits(self):
        self.hear(); r = dash.map_publish("admin", self.key, True, self.now)
        self.assertTrue(r["ok"]); self.assertEqual(200, r["status"]); self.assertEqual(1, len(self.sent)); self.assertEqual("POST", self.sent[0].get_method())
        r2 = dash.map_publish("admin", self.key, True, self.now + 5); self.assertFalse(r2["ok"]); self.assertEqual(1, len(self.sent))
        self.assertTrue(dash.map_publish("admin", self.key, True, self.now + 70)["ok"]); self.assertEqual(2, len(self.sent))
        a = self.audit_rows(); self.assertTrue(any(x[0] == "admin" and x[2] == 1 and "HTTP 200" in x[3] for x in a)); self.assertFalse(any("meshcore://" in x[3] for x in a))
    def test_error_replies_and_network_failures_are_reported_not_hidden(self):
        self.hear(); dash.MAP_SEND = lambda req: (429, b"slow\x00 down\n")
        r = dash.map_publish("admin", self.key, True, self.now); self.assertFalse(r["ok"]); self.assertEqual(429, r["status"]); self.assertEqual("slow  down", r["response"]); self.assertIn("429", r["error"])
        def boom(req): raise OSError("timed out")
        dash.MAP_SEND = boom; r = dash.map_publish("admin", self.key, True, self.now + 100); self.assertFalse(r["ok"]); self.assertIn("timed out", r["error"])
        dash.MAP_SEND = lambda req: (302, b""); self.assertFalse(dash.map_publish("admin", self.key, True, self.now + 200)["ok"])     # a redirect is a failure, not success
    def test_old_advert_and_no_position_refused(self):
        self.hear(); dash.DB.execute("UPDATE adverts SET ts=?", (self.now - 8 * 86400,))
        self.assertIn("older than 7 days", dash.map_publish("admin", self.key, True, self.now)["error"])
        k2, nopos = make_advert(seed=b"\x02" * 32, lat=None, lon=None, ts=self.now); dash.DEV[k2] = {"id": k2, "name": "Flat", "last": 1, "first": 0}; self.hear(nopos)
        self.assertIn("no position", dash.map_publish("admin", k2, True, self.now)["error"]); self.assertEqual([], self.sent)
        st = {r["id"]: r for r in dash.map_status(self.now)["repeaters"]}; self.assertTrue(st[k2]["why_not"]); self.assertTrue(st[self.key]["why_not"])
    def test_status_lists_every_repeater_and_nothing_publishes_by_itself(self):
        self.assertEqual("no verified advert", dash.map_status()["repeaters"][0]["why_not"][:18]); self.hear()
        s = dash.map_status(self.now)["repeaters"][0]; self.assertEqual("", s["why_not"]); self.assertAlmostEqual(53.5, s["lat"], 3); self.assertEqual("Hill", s["name"]); self.assertEqual([], self.sent)
    def test_post_is_admin_only_by_route(self):
        self.assertNotIn("/api/mappublish", dash.OWNER_POSTS)
    def test_off_by_default_and_validated(self):
        self.assertFalse(dash.DEFAULTS["map_publish"]); self.assertIsNone(dash.conf_update({"map_publish": True})); self.assertTrue(dash.CONF["map_publish"])


class HopAdvice(unittest.TestCase):
    RX = "AA" * 32
    def setUp(self):
        dash.db_init(); dash.DB.execute("DELETE FROM hophist"); dash.HOP_BUF.clear(); dash.DEV.clear(); dash.SETTINGS.clear(); self.now = int(time.time())
        dash.DEV[self.RX] = {"id": self.RX, "name": "Hill", "last": self.now, "first": 0}
    def test_percentile_margin_and_bounds(self):
        a = dash.hop_advice({0: 100, 1: 100, 2: 50, 3: 30, 4: 19, 9: 1}, 0, 3 * 86400); self.assertEqual((4, 5), (a["p95"], a["recommended"])); self.assertEqual("unknown setting", a["status"])
        self.assertEqual(2, dash.hop_advice({0: 300}, 0, 3 * 86400)["recommended"])                 # never below 2
        self.assertEqual(64, dash.hop_advice({63: 300}, 0, 3 * 86400)["recommended"])               # never above 64
        self.assertEqual("matches", dash.hop_advice({1: 300}, 0, 3 * 86400, 2)["status"]); self.assertEqual("differs", dash.hop_advice({1: 300}, 0, 3 * 86400, 8)["status"])
    def test_needs_200_samples_over_3_days(self):
        a = dash.hop_advice({1: 199}, 0, 5 * 86400); self.assertEqual("not enough data", a["status"]); self.assertIsNone(a["recommended"])
        b = dash.hop_advice({1: 5000}, 0, 2 * 86400); self.assertEqual("not enough data", b["status"])           # 49 hours of data, not 3 days
        self.assertEqual("not enough data", dash.hop_advice({}, 0, 0)["status"]); self.assertEqual("unknown setting", dash.hop_advice({1: 200}, 0, 3 * 86400 - 3600)["status"])   # exactly 200 packets over exactly 3 days is enough
    def test_only_flood_packets_count_and_hops_are_bounded(self):
        fl = dash.parse_packet(bytes([(2 << 2) | 1, 2, 0xAA, 0xBB]) + b"\x00" * 20); dr = dash.parse_packet(bytes([(2 << 2) | 2, 2, 0xAA, 0xBB]) + b"\x00" * 20)
        dash.note_network(self.RX, fl, 5, -90, self.now); dash.note_network(self.RX, dr, 5, -90, self.now)
        self.assertEqual({(self.now // 3600 * 3600, self.RX, 2): 1}, dict(dash.HOP_BUF))
        self.assertFalse(dash.hop_note(self.RX, 64, self.now)); self.assertFalse(dash.hop_note(self.RX, None, self.now)); self.assertFalse(dash.hop_note(self.RX, -1, self.now))
    def test_view_from_the_database_with_current_setting(self):
        h0 = self.now // 3600 * 3600 - 4 * 86400
        for i, (hp, n) in enumerate(((0, 120), (1, 90), (2, 40), (3, 5))): dash.DB.execute("INSERT INTO hophist VALUES(?,?,?,?)", (h0 + i * 3600, self.RX, hp, n)); dash.DB.execute("INSERT INTO hophist VALUES(?,?,?,?)", (h0 + 4 * 86400 - 3600, self.RX, hp, 1))
        dash.SETTINGS[self.RX] = {"values": {"flood.max": "> 8"}}
        v = dash.hop_advice_view(self.now)[0]; self.assertEqual((8, 3), (v["current"], v["recommended"])); self.assertEqual("differs", v["status"]); self.assertGreaterEqual(v["days"], 3)
        dash.DEV["CC" * 32] = {"id": "CC" * 32, "name": "Quiet", "last": 0, "first": 0}
        self.assertEqual("not enough data", [x for x in dash.hop_advice_view(self.now) if x["name"] == "Quiet"][0]["status"])      # no data is not 0 hops
    def test_flush_adds_up_and_retention_prunes(self):
        for _ in range(3): dash.hop_note(self.RX, 1, self.now)
        dash.traffic_flush(); dash.hop_note(self.RX, 1, self.now); dash.traffic_flush(); self.assertEqual(4, dash.DB.execute("SELECT SUM(n) FROM hophist").fetchone()[0])
        dash.DB.execute("INSERT INTO hophist VALUES(?,?,?,?)", (self.now - 400 * 86400, self.RX, 1, 5)); r = dash.retention_run(self.now); self.assertEqual(1, r["hophist"]); self.assertEqual(4, dash.DB.execute("SELECT SUM(n) FROM hophist").fetchone()[0])


class SnrWorse(unittest.TestCase):
    N = "BB" * 32
    def setUp(self):
        dash.db_init(); [dash.DB.execute("DELETE FROM " + t) for t in ("snr", "alertstate", "traffic")]; dash.DEV.clear(); dash.NODES.clear(); dash.SNR_BUF.clear()
        self.now = (int(time.time()) // 3600) * 3600 + 1800; dash.NODES[self.N] = {"key": self.N, "name": "Far", "type": 2, "last": self.now}
        self.c = dict(dash.CONF["alerts"]); dash.CONF["alerts"].update(snr_worse=True); self.sent = []; self.real = dash.send_alert; dash.send_alert = lambda t, *a, **k: self.sent.append(t)
    def tearDown(self): dash.send_alert = self.real; dash.CONF["alerts"].clear(); dash.CONF["alerts"].update(self.c)
    def fill(self, recent, base, node=None, n=5):
        cur = self.now // 3600 * 3600
        for i in range(24): dash.DB.execute("INSERT OR REPLACE INTO snr VALUES(?,?,?,?,?,?)", (cur - i * 3600, node or self.N, n, recent * n, recent, recent))
        for i in range(24, 24 + 7 * 24): dash.DB.execute("INSERT OR REPLACE INTO snr VALUES(?,?,?,?,?,?)", (cur - i * 3600, node or self.N, n, base * n, base, base))
    def test_trend_math_and_missing_data(self):
        hr = lambda v, k, n=5: [(n, v * n)] * k
        t = dash.snr_trend(hr(2.0, 24), hr(8.0, 150), 20); self.assertEqual((2.0, 8.0, 6.0), (t["recent"], t["base"], t["delta"]))
        self.assertIsNone(dash.snr_trend([], hr(8.0, 150), 20)); self.assertIsNone(dash.snr_trend(hr(2.0, 2), hr(8.0, 150), 20)); self.assertIsNone(dash.snr_trend(hr(2.0, 24), hr(8.0, 5), 20))
        self.assertIsNone(dash.snr_trend(hr(2.0, 24, 0), hr(8.0, 150), 20)); self.assertIsNone(dash.snr_trend(hr(2.0, 24, 1), hr(8.0, 150), 100))
        r = dash.snr_trend(hr(9.0, 24), hr(8.0, 150), 20); self.assertEqual(-1.0, r["delta"])          # better is a negative delta, not an alert
    def test_median_ignores_one_odd_hour(self):
        rec = [(5, 10.0)] * 23 + [(5, -100.0)]; t = dash.snr_trend(rec, [(5, 40.0)] * 150, 20); self.assertEqual(2.0, t["recent"])
    def test_step_hysteresis_and_cooldown(self):
        f = dash.snr_alert_step
        self.assertEqual("fire", f(False, 4.0, 4)); self.assertIsNone(f(False, 3.9, 4)); self.assertIsNone(f(True, 6, 4)); self.assertIsNone(f(True, 3, 4)); self.assertEqual("recover", f(True, 2.0, 4))
        self.assertIsNone(f(True, None, 4)); self.assertIsNone(f(False, None, 4)); self.assertIsNone(f(False, 9, 4, since_recover=3600)); self.assertEqual("fire", f(False, 9, 4, since_recover=13 * 3600))
    def test_alert_fires_once_persists_recovers_and_respects_cooldown(self):
        self.fill(2.0, 8.0); self.assertEqual(1, dash.snr_alerts(self.now)["fired"]); dash.snr_alerts(self.now + 600); self.assertEqual(1, len(self.sent)); self.assertTrue(self.sent[0].startswith("Signal worse: Far"))
        self.assertEqual("active", dash.alert_get("snrw:" + self.N)[0]); self.assertTrue(dash.snr_view(self.now)[0]["alert"])
        dash.DB.execute("DELETE FROM snr"); self.assertEqual({"fired": 0, "recovered": 0}, dash.snr_alerts(self.now)); self.assertEqual("active", dash.alert_get("snrw:" + self.N)[0])   # no readings: state kept
        self.fill(7.0, 8.0); self.assertEqual(1, dash.snr_alerts(self.now + 700)["recovered"]); self.assertTrue(self.sent[1].startswith("Signal back"))
        self.fill(2.0, 8.0); self.assertEqual(0, dash.snr_alerts(self.now + 800)["fired"])                                                           # inside the 12 h cooldown
        self.assertEqual(1, dash.snr_alerts(self.now + 700 + 12 * 3600 + 5)["fired"])
    def test_switch_off_and_node_kinds(self):
        self.fill(2.0, 8.0); dash.CONF["alerts"]["snr_worse"] = False; self.assertEqual({}, dash.snr_alerts(self.now)); self.assertEqual([], self.sent); self.assertEqual((None, 0), dash.alert_get("snrw:" + self.N))
        dash.CONF["alerts"]["snr_worse"] = True; dash.NODES[self.N]["type"] = 1; self.assertEqual([], dash.snr_view(self.now))                    # a companion that moves about is not a link
        dash.DEV[self.N] = {"id": self.N, "name": "Own", "last": 1, "first": 0}; self.assertEqual(1, len(dash.snr_view(self.now)))
    def test_a_burst_is_one_alert(self):
        for i in range(5):
            k = ("%02X" % (0xC0 + i)) * 32; dash.NODES[k] = {"key": k, "name": "n%d" % i, "type": 2, "last": 1}; self.fill(1.0, 9.0, k)
        dash.snr_alerts(self.now); self.assertEqual(1, len(self.sent)); self.assertIn("5 nodes", self.sent[0])
    def test_settings_validation(self):
        self.assertIsNone(dash.conf_update({"snr_worse_db": 6, "snr_min_samples": 50})); self.assertEqual(6, dash.CONF["snr_worse_db"])
        for k, v in (("snr_worse_db", 0), ("snr_worse_db", 31), ("snr_min_samples", 4), ("snr_min_samples", "x")): self.assertTrue(dash.conf_update({k: v}), (k, v))
        dash.conf_update({"snr_worse_db": 4, "snr_min_samples": 20}); self.assertTrue(dash.DEFAULTS["alerts"]["snr_worse"]); self.assertFalse(dash.DEFAULTS["alerts"]["clock_drift"])


class ClockDrift(unittest.TestCase):
    K = "DD" * 32
    def setUp(self):
        dash.db_init(); [dash.DB.execute("DELETE FROM " + t) for t in ("clockdrift", "alertstate")]; dash.DEV.clear(); dash.NODES.clear(); self.now = int(time.time())
        dash.NODES[self.K] = {"key": self.K, "name": "Tower", "type": 2, "last": self.now}
        self.c = dict(dash.CONF["alerts"]); dash.CONF["alerts"].update(clock_drift=True); dash.CONF["drift_seconds"] = 600; self.sent = []; self.real = dash.send_alert; dash.send_alert = lambda t, *a, **k: self.sent.append(t)
    def tearDown(self): dash.send_alert = self.real; dash.CONF["alerts"].clear(); dash.CONF["alerts"].update(self.c)
    def samples(self, drifts, key=None):
        for i, d in enumerate(drifts): t = self.now - (len(drifts) - i) * 1500; self.assertTrue(dash.drift_note(key or self.K, t + d, t))
    def test_sample_rules(self):
        self.assertTrue(dash.drift_note(self.K, self.now + 30, self.now)); self.assertFalse(dash.drift_note(self.K, self.now + 40, self.now + 60))   # too soon
        self.assertFalse(dash.drift_note(self.K, self.now + 30, self.now + 5000)); self.assertTrue(dash.drift_note(self.K, self.now + 5030 + 7, self.now + 5000))
        for i in range(10): dash.drift_note(self.K, self.now + 9000 + i * 2000, self.now + 9000 + i * 2000 - 1)
        self.assertEqual(5, len(json.loads(dash.DB.execute("SELECT samples FROM clockdrift").fetchone()[0])))
    def test_median_needs_two_recent_samples(self):
        self.assertIsNone(dash.drift_median([], self.now)); self.assertIsNone(dash.drift_median([[self.now, 5, 0]], self.now)); self.assertIsNone(dash.drift_median([[self.now - 3 * 86400, 5, 0], [self.now, 7, 0]], self.now))
        self.assertEqual(7, dash.drift_median([[self.now - 90, 5, 0], [self.now, 9, 0], [self.now, 7, 0]], self.now))
    def test_view_reports_without_alerting_when_the_switch_is_off(self):
        self.samples([900, 905, 910]); dash.CONF["alerts"]["clock_drift"] = False
        v = dash.drift_view(self.now); self.assertEqual(1, len(v)); self.assertTrue(v[0]["beyond"]); self.assertEqual(905, v[0]["drift"]); self.assertEqual({}, dash.drift_alerts(self.now)); self.assertEqual([], self.sent)
    def test_alert_hysteresis_cooldown_and_persistence(self):
        f = dash.drift_alert_step; self.assertEqual("fire", f(False, 601, 600)); self.assertEqual("fire", f(False, -601, 600)); self.assertIsNone(f(False, 600, 600)); self.assertIsNone(f(True, 400, 600)); self.assertEqual("recover", f(True, -300, 600))
        self.assertIsNone(f(True, None, 600)); self.assertIsNone(f(False, 900, 600, since_recover=100))
        self.samples([900, 905]); self.assertEqual(1, dash.drift_alerts(self.now)["fired"]); dash.drift_alerts(self.now + 900); self.assertEqual(1, len(self.sent)); self.assertEqual("active", dash.alert_get("drift:" + self.K)[0])
        dash.DB.execute("DELETE FROM clockdrift"); self.assertEqual({"fired": 0, "recovered": 0}, dash.drift_alerts(self.now + 60)); self.assertEqual("active", dash.alert_get("drift:" + self.K)[0])    # no samples: state kept
        self.samples([20, 25]); self.assertEqual(1, dash.drift_alerts(self.now + 100)["recovered"])
    def test_own_repeater_with_mqtt_skew_is_not_alerted_twice(self):
        dash.DEV[self.K] = {"id": self.K, "name": "Tower", "last": 1, "first": 0, "skew": 1000.0}; self.samples([900, 905]); v = dash.drift_view(self.now)[0]
        self.assertTrue(v["own"]); self.assertTrue(v["covered"]); self.assertEqual({"fired": 0, "recovered": 0}, dash.drift_alerts(self.now)); self.assertEqual([], self.sent)
        dash.DEV[self.K]["skew"] = None; self.assertEqual(1, dash.drift_alerts(self.now)["fired"])      # no status timestamps: the advert clock is all we have
    def test_companions_are_left_out(self):
        k = "EE" * 32; dash.NODES[k] = {"key": k, "name": "Phone", "type": 1, "last": 1}; self.samples([5000, 5000], k); self.assertEqual([], dash.drift_view(self.now))
    def test_threshold_validation(self):
        self.assertIsNone(dash.conf_update({"drift_seconds": 900})); self.assertEqual(900, dash.CONF["drift_seconds"])
        for v in (59, 86401, "x"): self.assertTrue(dash.conf_update({"drift_seconds": v}))
        dash.conf_update({"drift_seconds": 600})


class TxAdvice(unittest.TestCase):
    A = "AA" * 32; B = "BB" * 32; C = "CC" * 32
    def test_floors_are_the_standard_limits(self):
        self.assertEqual({7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}, dash.SF_FLOOR)
    def test_sf_parsing(self):
        self.assertEqual(8, dash.radio_sf("> 869.618,62.5,8,8")); self.assertEqual(7, dash.radio_sf("910.525, 62.5, 7, 5")); self.assertIsNone(dash.radio_sf("")); self.assertIsNone(dash.radio_sf(None)); self.assertIsNone(dash.radio_sf("garbage"))
    def test_suggests_lowering_only_with_headroom_for_every_neighbour(self):
        t = dash.tx_advice(8, [("a", 5.0), ("b", 8.0)], 10, 20); self.assertEqual("advice", t["status"]); self.assertEqual((15.0, 5), (t["min_margin"], t["drop"])); self.assertIn("to about 15 dBm", t["text"]); self.assertIn("test with tryset only after hardware validation", t["text"])
        self.assertEqual(6, dash.tx_advice(8, [("a", 20.0), ("b", 20.0)], 10)["drop"])                    # one step is capped
        n = dash.tx_advice(8, [("a", -1.0), ("b", 8.0)], 10); self.assertEqual("none", n["status"]); self.assertEqual(0, n["drop"]); self.assertNotIn("raise", n["text"].lower())
        self.assertEqual("none", dash.tx_advice(8, [("a", 0.0), ("b", 9.0)], 10)["status"])             # margin exactly the headroom: nothing
        self.assertEqual("none", dash.tx_advice(7, [("a", 2.5), ("b", 9.0)], 10)["status"]); self.assertEqual("advice", dash.tx_advice(12, [("a", -9.0), ("b", 0.0)], 10)["status"])
    def test_missing_data_gives_no_advice_never_zero(self):
        for sf, ne in ((None, [("a", 9), ("b", 9)]), (6, [("a", 9), ("b", 9)]), (8, [("a", 9)]), (8, []), (8, [("a", 9), ("b", None)])):
            t = dash.tx_advice(sf, ne, 10); self.assertEqual("skip", t["status"], (sf, ne)); self.assertEqual(0, t["drop"])
    def setup_links(self, rows):
        dash.db_init(); dash.DB.execute("DELETE FROM links"); dash.DEV.clear(); dash.SETTINGS.clear(); dash.NODES.clear(); now = int(time.time())
        for k, nm in ((self.A, "A"), (self.B, "B")): dash.DEV[k] = {"id": k, "name": nm, "last": now, "first": 0, "radio": "869.618,62.5,8,8"}
        dash.NODES[self.C] = {"key": self.C, "name": "Far", "type": 2, "last": now}
        for a, b, s, t in rows: dash.DB.execute("INSERT INTO links VALUES(?,?,?,?,?,NULL)", (a, b, t or now, t or now, s))
        return now
    def test_view_uses_both_directions_and_ignores_stale_links(self):
        now = self.setup_links([(self.A, self.C, 6.0, None), (self.A, self.B, 12.0, None), (self.B, self.A, -3.0, None), (self.A, "DD" * 32, -15.0, int(time.time()) - 5 * 86400)])
        a = {x["id"]: x for x in dash.tx_view(now)}[self.A]
        self.assertEqual(2, a["neighbours"]); self.assertEqual(8, a["sf"]); self.assertEqual("none", a["status"]); self.assertEqual(7.0, a["min_margin"]); self.assertEqual("B", a["weakest"])   # C: 16 dB; B: the worse of 12 and -3 is -3, 7 dB
        self.assertTrue(a["assumed"])                                  # C is not ours: we only know how we hear it
    def test_view_gives_advice_with_the_repeaters_own_sf_and_tx(self):
        now = self.setup_links([(self.A, self.C, 12.0, None), (self.A, self.B, 14.0, None), (self.B, self.A, 9.0, None)])
        dash.SETTINGS[self.A] = {"values": {"radio": "> 869.618,62.5,7,5", "tx": "> 20"}}
        a = {x["id"]: x for x in dash.tx_view(now)}[self.A]
        self.assertEqual((7, 20, "advice", 6), (a["sf"], a["tx"], a["status"], a["drop"])); self.assertEqual(16.5, a["min_margin"]); self.assertIn("to about 14 dBm", a["text"])
        b = {x["id"]: x for x in dash.tx_view(now)}[self.B]; self.assertEqual(("skip", 1), (b["status"], b["neighbours"]))          # one neighbour is not enough to judge
    def test_view_skips_when_the_sf_is_unknown(self):
        now = self.setup_links([(self.A, self.C, 12.0, None), (self.A, self.B, 14.0, None)]); dash.DEV[self.A]["radio"] = ""
        self.assertEqual("skip", {x["id"]: x for x in dash.tx_view(now)}[self.A]["status"])
    def test_headroom_validation(self):
        self.assertIsNone(dash.conf_update({"tx_headroom_db": 12})); self.assertEqual(12, dash.CONF["tx_headroom_db"])
        for v in (2, 31, "x"): self.assertTrue(dash.conf_update({"tx_headroom_db": v}))
        dash.conf_update({"tx_headroom_db": 10})


class Watchtower(unittest.TestCase):
    def test_view_has_all_four_parts_and_survives_empty_data(self):
        dash.db_init(); dash.DEV.clear(); dash.NODES.clear(); v = dash.watchtower_view(); self.assertEqual({"now", "snr", "drift", "hops", "tx", "tx_label"}, set(v)); json.dumps(v)
        self.assertEqual("2.36", dash.VERSION)
    def test_advert_parse_still_reports_what_it_did(self):
        k, pkt = make_advert(ts=1); i = dash.parse_packet(pkt); self.assertEqual((k, "Hill"), (i["fkey"], i["name"])); self.assertEqual(2, i["atype"])
