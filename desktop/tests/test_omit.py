"""Headless tests for the chat-bot engine: no radio, no screen, a fake clock."""
import copy
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from umc_desktop.omit import config as C                      # noqa: E402
from umc_desktop.omit import texts as T                       # noqa: E402
from umc_desktop.omit.bot import Bot, normalise               # noqa: E402
from umc_desktop.omit.db import Db                            # noqa: E402


class Clock:
    def __init__(self, t=1_760_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(mode="bot", db=None, **over):
    cfg = C.merge(C.DEFAULTS, {"node_name": "MyNode", "start_mode": mode, "locations": ["Wakefield"], **over})
    clock = Clock()
    return Bot(cfg, db=db, now=clock, rng=random.Random(1)), clock


def msg(text="test", sender="Alice", channel=1, kind="rx", **kw):
    return {"ts": 0, "channel_idx": channel, "sender": sender, "text": text, "kind": kind, "hops": 2,
            "snr": 5.5, "rssi": -90, "path_names": ["Hilltop", "Ridge"], **kw}


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual([], C.check(C.DEFAULTS))

    def test_merge_overlays_key_by_key_and_leaves_the_base_alone(self):
        base = copy.deepcopy(C.DEFAULTS)
        out = C.merge(base, {"bot": {"max_per_hour": 2}, "channels": {"3": "#x"}})
        self.assertEqual(2, out["bot"]["max_per_hour"])
        self.assertEqual(10, out["bot"]["per_sender_minutes"])           # untouched keys survive
        self.assertEqual({"3": "#x"}, out["channels"])                   # channels are replaced, not merged
        self.assertEqual(6, base["bot"]["max_per_hour"])

    def test_check_names_each_problem(self):
        bad = C.merge(C.DEFAULTS, {"bot": {"triggers": [], "delay_s": [9, 2], "max_per_hour": 500},
                                   "beacon": {"interval_minutes": 1}, "locations": [],
                                   "repeaters": [{"name": "R", "pubkey": "xyz"}]})
        problems = " | ".join(C.check(bad))
        for word in ("triggers", "delay_s", "max_per_hour", "interval_minutes", "locations", "pubkey"):
            self.assertIn(word, problems)

    def test_beacons_are_off_by_default(self):
        self.assertFalse(C.DEFAULTS["beacon"]["enabled"])


class TriggerTests(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual("radio check", normalise("  Radio   CHECK?! "))

    def test_whole_message_must_be_a_trigger(self):
        bot, _ = make()
        for ok in ("test", "Test!", "PING", "radio check?"):
            self.assertTrue(bot.is_trigger(ok), ok)
        for no in ("testing", "this is a test", "", "tes t"):
            self.assertFalse(bot.is_trigger(no), no)

    def test_mentions(self):
        bot, _ = make()
        self.assertTrue(bot.mentions_me("hello @[MyNode] there"))
        self.assertTrue(bot.mentions_me("@[ mynode ]"))
        self.assertFalse(bot.mentions_me("MyNode without the brackets"))
        self.assertFalse(bot.mentions_me("@[Other]"))


class DecisionTests(unittest.TestCase):
    def test_not_a_trigger_is_ignored(self):
        bot, _ = make()
        self.assertEqual("ignore", bot.decide(msg("good morning")).action)

    def test_a_test_call_gets_an_answer_after_a_short_delay(self):
        bot, _ = make()
        d = bot.decide(msg())
        self.assertEqual("reply", d.action)
        self.assertTrue(2 <= d.delay <= 6)

    def test_each_rule_has_its_own_reason(self):
        cases = [
            (dict(mode="operator"), msg(), "operator mode"),
            (dict(bot={"enabled": False}), msg(), "switched off"),
            (dict(), msg(kind="backlog"), "before the program started"),
            (dict(), msg(channel=0), "not a reply channel"),
            (dict(), msg(sender="WeatherBot"), "looks like a bot"),
        ]
        for over, rec, reason in cases:
            bot, _ = make(**over)
            d = bot.decide(rec)
            self.assertEqual("quiet", d.action, reason)
            self.assertIn(reason, d.reason)

    def test_paused_stays_quiet_in_bot_mode(self):
        bot, _ = make()
        bot.paused = True
        self.assertEqual("paused", bot.decide(msg()).reason)

    def test_one_answer_per_station_per_interval(self):
        bot, clock = make()
        rec = msg()
        _, idx = bot.build_reply(rec)
        bot.commit_reply(rec, idx)
        self.assertEqual("quiet", bot.decide(rec).action)
        self.assertEqual("reply", bot.decide(msg(sender="Bob")).action)    # someone else is fine
        clock.t += 10 * 60 + 1
        self.assertEqual("reply", bot.decide(rec).action)                  # and Alice again after ten minutes

    def test_hourly_limit_is_a_rolling_hour(self):
        bot, clock = make(bot={"max_per_hour": 2, "per_sender_minutes": 0})
        for who in ("A1", "A2"):
            rec = msg(sender=who)
            bot.commit_reply(rec, 0)
        d = bot.decide(msg(sender="A3"))
        self.assertEqual("quiet", d.action)
        self.assertIn("hourly limit", d.reason)
        clock.t += 3601
        self.assertEqual("reply", bot.decide(msg(sender="A3")).action)

    def test_mentions_are_answered_only_when_asked_for(self):
        bot, _ = make()
        self.assertEqual("ignore", bot.decide(msg("hi @[MyNode] how are you")).action)
        bot, _ = make(bot={"answer_mentions": True})
        d = bot.decide(msg("hi @[MyNode] how are you"))
        self.assertEqual(("reply", "mention"), (d.action, d.kind))


class ReplyTests(unittest.TestCase):
    def test_placeholders_are_filled_and_the_answer_says_it_is_automatic(self):
        bot, _ = make()
        text, _ = bot.build_reply(msg())
        self.assertNotIn("{", text)
        self.assertTrue(text.endswith("[auto]"), text)
        self.assertIn("@[Alice]", text)

    def test_callsign_is_added(self):
        bot, _ = make(callsign="2E0LXY")
        text, _ = bot.build_reply(msg())
        self.assertTrue(text.endswith("[auto] 2E0LXY"), text)

    def test_no_line_repeats_for_a_station_until_all_have_been_given(self):
        for db in (None, Db()):
            bot, clock = make(db=db, bot={"per_sender_minutes": 0, "max_per_hour": 100})
            n = len(bot.texts["replies"])
            seen = []
            for _ in range(n):
                rec = msg()
                text, idx = bot.build_reply(rec)
                bot.commit_reply(rec, idx)
                seen.append(idx)
            self.assertEqual(n, len(set(seen)), "a line repeated before the round was over")
            text, idx = bot.build_reply(msg())                                # a new round starts
            self.assertIn(idx, range(n))

    def test_lines_quoting_snr_are_skipped_when_it_is_unknown(self):
        bot, _ = make()
        for i in range(30):
            text, idx = bot.build_reply(msg(snr=None, rssi=None, sender=f"S{i}"))
            self.assertFalse(T.uses(bot.texts["replies"][idx], "snr", "rssi"), text)

    def test_an_answer_never_exceeds_one_message(self):
        bot, _ = make(callsign="2E0LXY")
        bot.texts["replies"] = ["@[{name}] " + "x" * 400]
        text, _ = bot.build_reply(msg())
        self.assertLessEqual(len(text), C.MAX_REPLY)
        self.assertTrue(text.endswith("[auto] 2E0LXY"), "the tag must survive the cut")

    def test_hops_wording(self):
        self.assertEqual("direct, no repeater", T.hops_text(0))
        self.assertEqual("1 hop", T.hops_text(1))
        self.assertEqual("3 hops", T.hops_text(3))
        self.assertEqual("a few hops", T.hops_text(None))

    def test_unknown_fields_are_left_visible(self):
        self.assertEqual("hi {nope} x", T.fill("hi {nope} {a}", {"a": "x"}))


class BeaconTests(unittest.TestCase):
    def test_a_beacon_is_due_only_in_bot_mode_when_switched_on_and_after_the_first_delay(self):
        bot, clock = make(beacon={"enabled": True, "first_after_s": 60})
        bot.schedule_first_beacon()
        self.assertFalse(bot.beacon_due())
        clock.t += 61
        self.assertTrue(bot.beacon_due())
        bot.paused = True
        self.assertFalse(bot.beacon_due())
        bot.paused = False
        bot.set_mode("operator")
        self.assertFalse(bot.beacon_due())

    def test_off_means_off(self):
        bot, clock = make()
        bot.schedule_first_beacon()
        clock.t += 10_000
        self.assertFalse(bot.beacon_due())

    def test_never_the_same_line_twice_in_a_row(self):
        bot, _ = make(beacon={"enabled": True})
        last = None
        for _ in range(50):
            text = bot.next_beacon_text()
            self.assertNotEqual(last, text)
            last = text

    def test_sending_one_schedules_the_next(self):
        bot, clock = make(beacon={"enabled": True, "interval_minutes": 30, "first_after_s": 1})
        bot.schedule_first_beacon()
        clock.t += 2
        bot.commit_beacon("hi", beacon_id=7)
        clock.t += 29 * 60
        self.assertFalse(bot.beacon_due())
        clock.t += 61
        self.assertTrue(bot.beacon_due())

    def test_a_message_naming_the_node_inside_the_window_counts_as_a_reply(self):
        bot, clock = make(beacon={"enabled": True, "reply_window_minutes": 10})
        bot.commit_beacon("hi all", beacon_id=3)
        clock.t += 120
        self.assertEqual(3, bot.note_message(msg("@[MyNode] hello!", sender="Bob")))
        self.assertIsNone(bot.note_message(msg("nothing to do with you")))
        self.assertIsNone(bot.note_message(msg("@[MyNode] hi", kind="backlog")))
        clock.t += 11 * 60
        self.assertIsNone(bot.note_message(msg("@[MyNode] too late")))


class DbTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_760_000_000.0
        self.db = Db()

    def add(self, minutes_ago, **kw):
        rec = {"ts": self.now - minutes_ago * 60, "channel_idx": 1, "channel_name": "#test", "sender": "Alice",
               "text": "test", "kind": "rx", "is_trigger": 1, "hops": 1, "path": ["Hilltop"]}
        rec.update(kw)
        return self.db.add_message(rec)

    def test_stats_count_what_the_dashboard_shows(self):
        self.add(10)
        self.add(20, sender="Bob")
        self.add(5, kind="bot_reply", is_trigger=0, sender="MyNode")
        self.add(60 * 30)                                                   # older than a day: not counted
        s = self.db.stats(self.now)
        self.assertEqual(3, s["messages"])
        self.assertEqual(2, s["tests"])
        self.assertEqual(1, s["answers"])
        self.assertEqual(2, s["stations"])

    def test_hourly_has_one_row_per_hour_oldest_first(self):
        self.add(30)                       # the last hour: two messages, both tests
        self.add(30)
        self.add(90, is_trigger=0)         # the hour before: one message, not a test
        rows = self.db.hourly(self.now, hours=3)
        self.assertEqual([0, 1, 2], [r["hour"] for r in rows])
        self.assertEqual([0, 1, 2], [r["messages"] for r in rows])
        self.assertEqual([0, 0, 2], [r["tests"] for r in rows])

    def test_top_senders_hops_and_relays(self):
        for _ in range(3):
            self.add(10, sender="Alice", hops=2, path=["Hilltop", "Ridge"])
        self.add(10, sender="Bob", hops=0, path=[])
        self.assertEqual([("Alice", 3), ("Bob", 1)], [(r["sender"], r["n"]) for r in self.db.top_senders(self.now)])
        self.assertEqual({0: 1, 2: 3}, {r["hops"]: r["n"] for r in self.db.hops_histogram(self.now)})
        relays = {r["repeater"]: r["n"] for r in self.db.relay_counts(self.now)}
        self.assertEqual({"Hilltop": 3, "Ridge": 3}, relays)

    def test_reply_history_round_trip(self):
        self.db.add_reply_history("Alice", "2")
        self.db.add_reply_history("Alice", "5")
        self.db.add_reply_history("Bob", "2")
        self.assertEqual({"2", "5"}, set(self.db.reply_history("Alice")))
        self.db.clear_reply_history("Alice")
        self.assertEqual([], self.db.reply_history("Alice"))
        self.assertEqual(["2"], self.db.reply_history("Bob"))

    def test_beacon_summary(self):
        a = self.db.add_beacon(self.now - 600, 1, "hi")
        self.db.add_beacon(self.now - 300, 1, "hi again")
        self.db.count_beacon_reply(a)
        self.db.count_beacon_reply(a)
        s = self.db.beacon_summary(self.now)
        self.assertEqual((2, 1, 2), (s["sent"], s["answered"], s["replies"]))

    def test_repeater_status_keeps_the_latest_per_repeater_and_a_history(self):
        for minutes, mv in ((90, 4100), (60, 4050), (30, 4000)):
            self.db.add_repeater_status({"ts": self.now - minutes * 60, "name": "Hilltop", "ok": 1, "bat_mv": mv})
        self.db.add_repeater_status({"ts": self.now - 30 * 60, "name": "Ridge", "ok": 0, "note": "no answer"})
        last = {r["name"]: r for r in self.db.last_repeater_status()}
        self.assertEqual(4000, last["Hilltop"]["bat_mv"])
        self.assertEqual("no answer", last["Ridge"]["note"])
        self.assertEqual([4100, 4050, 4000], [r["bat_mv"] for r in self.db.repeater_history("Hilltop", self.now)])

    def test_recent_messages_are_oldest_first_and_can_continue_from_an_id(self):
        ids = [self.add(m, text=f"m{m}") for m in (5, 4, 3)]
        got = self.db.recent_messages(limit=10)
        self.assertEqual(["m5", "m4", "m3"], [r["text"] for r in got])
        self.assertEqual(["m3"], [r["text"] for r in self.db.recent_messages(since_id=ids[1])])

    def test_events(self):
        self.db.add_event("info", "connected")
        self.db.add_event("warn", "no answer")
        self.assertEqual(["connected", "no answer"], [e["text"] for e in self.db.recent_events()])


if __name__ == "__main__":
    unittest.main()
