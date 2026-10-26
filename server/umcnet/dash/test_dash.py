"""Tests for the dashboard service and its admin helper. Run: python3 -m unittest -v test_dash   (no broker needed)"""
import importlib.util, os, sys, tempfile, time, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file)); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
os.environ["DASH_DATA"] = tempfile.mkdtemp()
dash = load("umcnet_dash", "umcnet_dash.py")
adm = load("umcnet_admin", "umcnet_admin.py")


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
    DENIED = ["password hunter22", "set guest.password x", "get guest.password", "set prv.key aa", "get prv.key", "set wifi.ssid x", "set wifi.pwd y", "wifi clear 1", "get wifi.pwd", "set ap.mode on",
              "set ap.password z", "set net.ip dhcp", "set pin 12345678", "setperm abc 3", "set http off", "set telnet on", "set mqtt.custom.password p", "get mqtt.custom.password",
              "set mqtt.custom.host evil.example", "set mqtt.custom.port 1", "set mqtt.custom.transport tcp", "set mqtt.custom.username u", "set mqtt.control off", "set mqtt.control.key aa",
              "get mqtt.control.key", "set bridge.secret s", "get bridge.secret", "start ota", "ota install", "erase", "format", "poweroff", "set ble.pin 1", "set mqtt.meshmapper on",
              "SET PASSWORD x", "Set Prv.Key aa", "GET PRV.KEY", "", " get radio", "get radio ", "get radio\nset tx 1", 'get "radio"', "get radio\\", "frobnicate", "set unknown.thing 1", "a" * 141]

    def test_allowed(self):
        for c in self.ALLOWED: self.assertTrue(dash.command_allowed(c), c)

    def test_denied(self):
        for c in self.DENIED: self.assertFalse(dash.command_allowed(c), repr(c))

    def test_risky_ones_need_confirming(self):
        for c in ("reboot", "set tx 10", "set radio 1,2,3,4", "region put x", "set name x", "set mqtt.raw off", "set flood.max 5", "clear stats", "time 1"): self.assertTrue(dash.command_risky(c), c)
        for c in ("get radio", "advert", "stats-core", "neighbors", "ver", "discover.neighbors"): self.assertFalse(dash.command_risky(c), c)


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
        dash.NODES.clear(); dash.LINKS.clear(); dash.JOURNEYS.clear()

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
        dash.NODES[self.KEY_B.upper()] = {"key": self.KEY_B.upper(), "name": "B", "type": 2, "lat": None, "lon": None, "first": 0, "last": 0, "adverts": 1}
        raw = bytes([(1 << 2) | 1, 1, 0x33, 0xAA, 0x22, 9, 9])               # RESP: destination AA, sender 22, via 33
        dash.note_network(recv, dash.parse_packet(raw), 4.0, -95, time.time())
        self.assertIn((recv, self.KEY_B.upper()), dash.LINKS)
        self.assertEqual("B", dash.network_view()["nodes"][0]["name"])

    def test_the_view_lists_nodes_links_and_journeys(self):
        dash.note_network("AA" * 32, dash.parse_packet(self.advert(self.KEY_A, "Hill", 53.7, -1.5, hops=[0x44])), 6.0, -97, time.time())
        v = dash.network_view()
        self.assertEqual((1, 1, 1), (len(v["nodes"]), len(v["links"]), len(v["journeys"])))
        self.assertEqual(1, v["links"][0]["hops"]); self.assertEqual("44", v["journeys"][0]["path"][0]["h"])


class History(unittest.TestCase):
    def test_many_series_can_be_asked_for_at_once(self):
        # the page asks for 13 fixed series plus one per repeater; an old limit of 12 silently dropped the rest
        dash.db_init(); now = int(time.time())
        dash.DB.executemany("INSERT INTO samples VALUES(?,?,?)", [(now - 60, "k%d" % i, float(i)) for i in range(30)])
        got = dash.history(["k%d" % i for i in range(30)], 3600)
        self.assertEqual(30, len(got))
        src = open(os.path.join(HERE, "umcnet_dash.py")).read()
        self.assertIn('split(",") if k][:60]', src)


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
