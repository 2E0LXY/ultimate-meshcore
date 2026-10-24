"""The engine against a pretend radio: frames in, commands out, no hardware."""
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

NOW = 1_760_000_000.0
KEY = "ab" * 32


class FakeBackend:
    def __init__(self):
        self.listeners, self.sent, self.me, self.fail = [], [], {"name": "MyNode"}, False

    async def cmd(self, frame, timeout=10, expect=None):
        if self.fail:
            raise TimeoutError("no reply from the radio")
        self.sent.append(bytes(frame))
        return bytes([0])


def make(mode="bot", **over):
    cfg = C.merge(C.DEFAULTS, {"node_name": "MyNode", "start_mode": mode, "locations": ["Wakefield"], **over})
    be, db = FakeBackend(), Db()

    async def no_sleep(_):
        await asyncio.sleep(0)

    eng = Engine(be, cfg, db, now=lambda: NOW, rng=random.Random(3), sleep=no_sleep)
    return eng, be, db


def chan(text, idx=1, ts=NOW, snr=5.5, hops=1):
    return F.build_channel_msg(idx, text, ts, snr, hops)


def sent_text(frame):
    return frame[7:].decode()


class FrameTests(unittest.TestCase):
    def test_channel_message_round_trip(self):
        f = F.parse(chan("Alice: test", idx=1, snr=5.5, hops=2))
        self.assertEqual(("channel_msg", 1, 2, 5.5, "Alice: test"),
                         (f["kind"], f["channel_idx"], f["hops"], f["snr"], f["text"]))
        self.assertEqual(("Alice", "test"), F.split_sender(f["text"]))
        self.assertEqual(("", "no name here"), F.split_sender("no name here"))

    def test_negative_snr_and_direct_routed(self):
        f = F.parse(chan("Bob: ping", snr=-7.25, hops=None))
        self.assertEqual(-7.25, f["snr"])
        self.assertIsNone(f["hops"])

    def test_log_rx_reads_the_packet_header(self):
        raw = bytes([(5 << 2) | 1, 2, 0x38, 0x1F]) + b"\x01payload"          # flood group text, two 1-byte hops
        f = F.parse(F.build_log_rx(raw, snr=3.0, rssi=-101))
        p = f["packet"]
        self.assertEqual((3.0, -101, "grp_txt", "flood", ["38", "1f"], 8),
                         (f["snr"], f["rssi"], p["type_name"], p["route"], p["path"], p["payload_len"]))

    def test_two_byte_hashes_and_transport_codes(self):
        raw = bytes([(5 << 2) | 0]) + b"\x01\x02\x03\x04" + bytes([0x42]) + b"\x38\x1f\xaa\xbb" + b"data"
        p = F.parse_packet(raw)
        self.assertEqual((2, 2, ["381f", "aabb"], "transport-flood"), (p["hash_size"], p["hops"], p["path"], p["route"]))

    def test_truncated_or_odd_packets_are_refused(self):
        self.assertIsNone(F.parse_packet(b"\x15"))
        self.assertIsNone(F.parse_packet(bytes([0x15, 5, 1, 2])))            # says five hops, has two bytes
        self.assertIsNone(F.parse(b""))
        self.assertIsNone(F.parse(bytes([0x99, 1, 2, 3])))

    def test_contact_frame(self):
        f = F.parse(F.build_contact(KEY, "Hilltop", ctype=2, lat=53.7, lon=-1.5))
        self.assertEqual(("contact", KEY, "Hilltop", 2), (f["kind"], f["pubkey"], f["name"], f["type"]))
        self.assertAlmostEqual(53.7, f["lat"], 4)

    def test_commands_match_the_firmware_layout(self):
        c = F.send_channel(1, "hello", NOW)
        self.assertEqual((3, 0, 1), tuple(c[:3]))
        self.assertEqual(int(NOW), struct.unpack("<I", c[3:7])[0])
        self.assertEqual(b"hello", c[7:])
        self.assertEqual(bytes([31, 4]), F.get_channel(4))


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def settle(self, eng):
        await asyncio.gather(*eng.tasks, return_exceptions=True)

    async def test_a_test_call_in_bot_mode_is_answered_and_recorded(self):
        eng, be, db = make()
        be.listeners[0](chan("Alice: test"))
        await self.settle(eng)
        self.assertEqual(1, len(be.sent))
        text = sent_text(be.sent[0])
        self.assertIn("@[Alice]", text)
        self.assertTrue(text.endswith("[auto]"), text)
        kinds = [r["kind"] for r in db.recent_messages()]
        self.assertEqual(["rx", "bot_reply"], kinds)
        self.assertEqual({"heard": 1, "tests": 1, "answers": 1}, {k: eng.counters[k] for k in ("heard", "tests", "answers")})

    async def test_operator_mode_listens_but_never_speaks(self):
        eng, be, db = make(mode="operator")
        be.listeners[0](chan("Alice: test"))
        await self.settle(eng)
        self.assertEqual([], be.sent)
        self.assertEqual(1, eng.counters["heard"])
        self.assertTrue(any("operator mode" in e["text"] for e in eng.events))

    async def test_messages_on_other_channels_are_heard_not_answered(self):
        eng, be, _ = make()
        be.listeners[0](chan("Alice: test", idx=0))
        await self.settle(eng)
        self.assertEqual([], be.sent)

    async def test_our_own_message_coming_back_is_ignored(self):
        eng, be, db = make()
        be.listeners[0](chan("MyNode: test"))
        await self.settle(eng)
        self.assertEqual([], be.sent)
        self.assertEqual([], db.recent_messages())

    async def test_a_queued_old_message_is_not_answered(self):
        eng, be, db = make()
        be.listeners[0](chan("Alice: test", ts=NOW - 600))
        await self.settle(eng)
        self.assertEqual([], be.sent)
        self.assertEqual("backlog", db.recent_messages()[0]["kind"])

    async def test_one_answer_per_station_in_the_interval(self):
        eng, be, _ = make()
        be.listeners[0](chan("Alice: test"))
        await self.settle(eng)
        be.listeners[0](chan("Alice: ping"))
        await self.settle(eng)
        self.assertEqual(1, len(be.sent))
        self.assertTrue(any("less than" in e["text"] for e in eng.events))

    async def test_changing_to_operator_mode_while_waiting_cancels_the_answer(self):
        eng, be, _ = make()
        be.listeners[0](chan("Alice: test"))
        eng.set_mode("operator")
        await self.settle(eng)
        self.assertEqual([], be.sent)

    async def test_a_failed_send_is_reported_and_does_not_count(self):
        eng, be, db = make()
        be.fail = True
        be.listeners[0](chan("Alice: test"))
        await self.settle(eng)
        self.assertEqual(0, eng.counters["answers"])
        self.assertTrue(any("could not send" in e["text"] for e in eng.events))
        be.fail = False
        be.listeners[0](chan("Alice: test"))
        await self.settle(eng)
        self.assertEqual(1, len(be.sent))                  # not locked out by the failed attempt

    async def test_the_path_comes_from_the_raw_copy_with_the_same_snr(self):
        eng, be, db = make(known_prefixes={"38": "Hilltop"})
        raw = bytes([(5 << 2) | 1, 2, 0x38, 0x1F]) + b"\x01payload"
        be.listeners[0](F.build_log_rx(raw, snr=5.5, rssi=-97))
        be.listeners[0](chan("Alice: hello all", snr=5.5, hops=2))
        row = db.recent_messages()[-1]
        self.assertEqual(("Hilltop>1f", -97.0), (row["path"], row["rssi"]))
        self.assertEqual({"Hilltop": 1, "1f": 1}, {r["repeater"]: r["n"] for r in db.relay_counts(NOW)})

    async def test_a_repeater_contact_names_its_hash(self):
        eng, be, db = make()
        be.listeners[0](F.build_contact("1f" + "00" * 31, "Ridge", ctype=2))
        raw = bytes([(5 << 2) | 1, 1, 0x1F]) + b"\x01payload"
        be.listeners[0](F.build_log_rx(raw, snr=4.0))
        be.listeners[0](chan("Alice: hello", snr=4.0, hops=1))
        self.assertEqual("Ridge", db.recent_messages()[-1]["path"])

    async def test_beacons_are_recorded_and_replies_counted(self):
        eng, be, db = make(beacon={"enabled": True, "channel": 1, "interval_minutes": 30})
        await eng.send_beacon()
        self.assertEqual(1, eng.counters["beacons"])
        be.listeners[0](chan("Bob: @[MyNode] hello!"))
        await self.settle(eng)
        self.assertEqual(1, eng.counters["beacon_replies"])
        s = db.beacon_summary(NOW)
        self.assertEqual((1, 1, 1), (s["sent"], s["answered"], s["replies"]))

    async def test_a_bad_frame_does_not_stop_the_bot(self):
        eng, be, _ = make()
        be.listeners[0](bytes([F.RESP_CHANNEL_MSG_V3, 1, 2]))          # cut short
        be.listeners[0](b"\xff")
        be.listeners[0](chan("Alice: test"))
        await self.settle(eng)
        self.assertEqual(1, len(be.sent))

    async def test_nicks_and_state(self):
        eng, be, _ = make(mode="operator")
        be.listeners[0](chan("Alice: hi", hops=1))
        be.listeners[0](chan("Bob: hello", hops=3))
        be.listeners[0](chan("Alice: again", hops=1))
        nicks = eng.nicks()
        self.assertEqual({"Alice": 2, "Bob": 1}, {n["nick"]: n["n"] for n in nicks})
        st = eng.state()
        self.assertEqual(("operator", "MyNode"), (st["mode"], st["node"]))
        self.assertEqual(3, st["counters"]["heard"])

    async def test_the_feed_can_be_read_from_a_point(self):
        eng, be, _ = make(mode="operator")
        be.listeners[0](chan("Alice: one"))
        first = eng.feed()[-1]["seq"]
        be.listeners[0](chan("Bob: two"))
        self.assertEqual(["two"], [r["text"] for r in eng.feed(since=first)])


if __name__ == "__main__":
    unittest.main()
