"""Polling repeaters against a pretend repeater that answers the way the firmware does."""
import asyncio
import os
import random
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from umc_desktop.omit import config as C                      # noqa: E402
from umc_desktop.omit import frames as F                      # noqa: E402
from umc_desktop.omit.db import Db                            # noqa: E402
from umc_desktop.omit.engine import Engine                    # noqa: E402
from umc_desktop.omit.repeaters import battery_percent, parse_neighbors   # noqa: E402

NOW = 1_760_000_000.0
KEY = "381f2a0b" + "11" * 28
OWN = "55667788" + "22" * 28


class FakeRepeaterRadio:
    """A companion radio with one repeater behind it, which answers login, status, trace and `neighbors`."""

    def __init__(self, password="secret"):
        self.listeners, self.sent, self.me = [], [], {"name": "MyNode"}
        self.password, self.silent, self.refuse = password, set(), False

    def push(self, frame):
        asyncio.get_running_loop().call_soon(lambda: [fn(frame) for fn in list(self.listeners)])

    async def cmd(self, frame, timeout=10, expect=None):
        frame = bytes(frame)
        self.sent.append(frame)
        if self.refuse:
            return bytes([1, 2])
        code, prefix = frame[0], KEY[:12]
        if code == F.CMD_SEND_LOGIN and "login" not in self.silent:
            ok = frame[33:].decode() == self.password
            self.push(F.build_login_push(prefix, ok))
        elif code == F.CMD_SEND_STATUS_REQ and "status" not in self.silent:
            self.push(F.build_status_push(prefix, F.build_stats(bat_mv=3900, noise_floor=-110, uptime_s=200_000,
                                                                last_rssi=-95, n_recv=500, n_sent=300, airtime_s=900, last_snr=5.0)))
        elif code == F.CMD_SEND_TRACE and "trace" not in self.silent:
            tag = struct.unpack_from("<I", frame, 1)[0]
            hashes = frame[10:]
            n = len(hashes)
            self.push(F.build_trace_push(tag, [bytes([h]).hex() for h in hashes], [4.0 + i for i in range(n)], 2.5))
        elif code == F.CMD_SEND_TXT and frame[1] == F.TXT_CLI and "cli" not in self.silent:
            self.push(F.build_cli_reply(prefix, "55667788:120:22\n99aabbcc:300:-8"))
        return bytes([F.RESP_SENT, 0]) + b"\0" * 8


def make(radio=None, repeaters=None, route=None):
    cfg = C.merge(C.DEFAULTS, {"node_name": "MyNode", "repeaters": repeaters if repeaters is not None else
                               [{"name": "Hilltop", "pubkey": KEY, "password": "secret"},
                                {"name": "Ridge", "pubkey": OWN, "password": "x"}]})
    radio, db = radio or FakeRepeaterRadio(), Db()

    async def no_sleep(_):
        await asyncio.sleep(0)

    eng = Engine(radio, cfg, db, now=lambda: NOW, rng=random.Random(2), sleep=no_sleep)
    eng.monitor.timeout = 0.3
    radio.listeners[0](F.build_contact(KEY, "Hilltop", ctype=2, route=route))
    radio.listeners[0](F.build_contact(OWN, "Ridge", ctype=2))
    return eng, radio, db


class HelperTests(unittest.TestCase):
    def test_battery_percent_is_a_rough_single_cell_curve(self):
        self.assertEqual(50, battery_percent(3700))
        self.assertEqual(100, battery_percent(4300))
        self.assertEqual(0, battery_percent(3000))
        self.assertIsNone(battery_percent(0))

    def test_neighbours_are_read_and_junk_is_skipped(self):
        got = parse_neighbors("55667788:120:22\n99AABBCC:300:-8\nnot a line\n1:2")
        self.assertEqual([("55667788", 120, 5.5), ("99aabbcc", 300, -2.0)], [(n["id"], n["secs_ago"], n["snr"]) for n in got])
        self.assertEqual([], parse_neighbors("-none-"))
        self.assertEqual([], parse_neighbors(None))

    def test_the_trace_command_has_the_firmware_layout(self):
        c = F.trace(7, ["38", "1f", "38"], 1)
        self.assertEqual((36, 7, 0, 0), (c[0], struct.unpack_from("<I", c, 1)[0], struct.unpack_from("<I", c, 5)[0], c[9]))
        self.assertEqual(b"\x38\x1f\x38", c[10:])
        self.assertEqual(1, F.trace(7, ["381f"], 2)[9])                      # two-byte hashes: flags 1

    def test_frames_round_trip(self):
        self.assertEqual("login_ok", F.parse(F.build_login_push("ab" * 6, True))["kind"])
        self.assertEqual("login_fail", F.parse(F.build_login_push("ab" * 6, False))["kind"])
        # a repeater on older firmware sends fewer statistics: what is there is read
        short = F.build_stats(bat_mv=4000, noise_floor=-100)[:12]
        self.assertEqual({"bat_mv": 4000, "tx_queue": 0, "noise_floor": -100, "last_rssi": 0, "n_recv": 0},
                         F.parse(F.build_status_push("ab" * 6, short))["stats"])


class PollTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_full_poll_logs_status_trace_and_neighbours(self):
        eng, radio, db = make(route=["aa", "bb"])
        row = await eng.monitor.poll_one(eng.cfg["repeaters"][0])
        self.assertEqual((1, 3900, -110, 200_000), (row["ok"], row["bat_mv"], row["noise_floor"], row["uptime_s"]))
        # route aa,bb to the repeater: the trace goes there and back, and the SNR "there" is read at the repeater itself
        trace_cmd = [f for f in radio.sent if f[0] == F.CMD_SEND_TRACE][0]
        self.assertEqual(bytes.fromhex("aabb" + "38" + "bbaa"), trace_cmd[10:])
        self.assertEqual((6.0, 2.5), (row["trace_there"], row["trace_back"]))
        saved = db.last_repeater_status()[0]
        self.assertEqual(("Hilltop", 1, 3900), (saved["name"], saved["ok"], saved["bat_mv"]))
        info = eng.monitor.latest["Hilltop"]
        self.assertEqual(2, len(info["neighbors"]))
        self.assertEqual("99aabbcc", info["best"]["id"])
        self.assertNotEqual("55667788", info["best"]["id"], "our own other repeater is not the interesting neighbour")

    async def test_a_direct_repeater_is_traced_with_just_its_own_hash(self):
        eng, radio, _ = make(route=[])
        row = await eng.monitor.poll_one(eng.cfg["repeaters"][0])
        self.assertEqual(b"\x38", [f for f in radio.sent if f[0] == F.CMD_SEND_TRACE][0][10:])
        self.assertEqual((4.0, 2.5), (row["trace_there"], row["trace_back"]))

    async def test_wrong_password_is_reported_and_nothing_else_is_tried(self):
        eng, radio, db = make(radio=FakeRepeaterRadio(password="different"))
        row = await eng.monitor.poll_one(eng.cfg["repeaters"][0])
        self.assertEqual(0, row["ok"])
        self.assertIn("wrong admin password", row["note"])
        self.assertEqual([F.CMD_SEND_LOGIN], [f[0] for f in radio.sent if f[0] in (26, 27, 36)])
        self.assertIn("wrong admin password", db.last_repeater_status()[0]["note"])

    async def test_a_repeater_the_radio_does_not_know_is_explained(self):
        eng, radio, db = make()
        row = await eng.monitor.poll_one({"name": "Far", "pubkey": "ab" * 32, "password": "p"})
        self.assertIn("advert", row["note"])
        self.assertEqual([], [f for f in radio.sent if f[0] == F.CMD_SEND_LOGIN])

    async def test_silence_is_reported_not_fatal(self):
        radio = FakeRepeaterRadio()
        radio.silent = {"trace", "cli"}
        eng, _, _ = make(radio=radio, route=[])
        row = await eng.monitor.poll_one(eng.cfg["repeaters"][0])
        self.assertEqual(1, row["ok"])                                       # the status still came back
        self.assertIn("trace: no answer", row["note"])
        self.assertIn("neighbours: no answer", row["note"])
        radio.silent = {"login"}
        row = await eng.monitor.poll_one(eng.cfg["repeaters"][0])
        self.assertEqual((0, True), (row["ok"], "login: no answer" in row["note"]))

    async def test_a_refusal_from_the_radio_is_reported(self):
        radio = FakeRepeaterRadio()
        radio.refuse = True
        eng, _, _ = make(radio=radio)
        row = await eng.monitor.poll_one(eng.cfg["repeaters"][0])
        self.assertIn("refused", row["note"])

    async def test_poll_all_goes_through_every_repeater_once_at_a_time(self):
        eng, radio, db = make()
        await eng.monitor.poll_all()
        names = sorted(r["name"] for r in db.last_repeater_status())
        self.assertEqual(["Hilltop", "Ridge"], names)

    async def test_a_cli_answer_is_not_shown_as_a_chat_message(self):
        eng, radio, db = make()
        radio.listeners[0](F.build_cli_reply(KEY[:12], "55667788:120:22"))
        self.assertEqual([], eng.feed())
        self.assertEqual([], db.recent_messages())

    async def test_the_table_for_the_page(self):
        eng, radio, _ = make(route=[])
        await eng.monitor.poll_one(eng.cfg["repeaters"][0])
        t = {r["name"]: r for r in eng.monitor.table()}
        self.assertEqual(70, t["Hilltop"]["battery_pct"])
        self.assertEqual("99aabbcc", t["Hilltop"]["best"]["id"])
        self.assertEqual("not polled yet", t["Ridge"]["note"])
        self.assertEqual(["Hilltop", "Ridge"], [k["name"] for k in eng.monitor.known_repeaters()])


if __name__ == "__main__":
    unittest.main()
