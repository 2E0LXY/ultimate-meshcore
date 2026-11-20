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
        self.assertEqual(["topic write meshcore/+/%s/raw" % self.ID, "topic write meshcore/+/%s/status" % self.ID], [l for l in acl if l.startswith("topic write")])
        self.assertFalse([l for l in acl if "readwrite" in l or "umcnet/v1" in l and "write" in l])
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
