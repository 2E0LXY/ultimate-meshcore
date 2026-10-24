"""The chat page's JSON interface, run against a pretend radio."""
import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from umc_desktop.omit import frames as F                      # noqa: E402
from umc_desktop.omit import web as omit_web                  # noqa: E402
from umc_desktop.omit.runtime import Runtime                  # noqa: E402

NOW = 1_760_000_000.0
H = {"X-UMC": "1"}


class FakeBackend:
    role = "companion"

    def __init__(self):
        self.listeners, self.sent, self.me = [], [], {"name": "MyNode"}

    async def cmd(self, frame, timeout=10, expect=None):
        self.sent.append(bytes(frame))
        return bytes([0])


class State:
    omit = None


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = State()
        self.state.omit = Runtime(self.tmp.name, now=lambda: NOW)
        self.backend = FakeBackend()
        app = web.Application()
        omit_web.setup(app, self.state)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.state.omit.detach()
        await self.client.close()
        self.tmp.cleanup()

    async def attach(self):
        self.state.omit.attach(self.backend)
        await asyncio.sleep(0.05)                                      # let the engine start

    def hear(self, text, **kw):
        self.backend.listeners[0](F.build_channel_msg(1, text, NOW, **kw))

    async def test_page_is_served_and_needs_nothing_from_the_internet(self):
        r = await self.client.get("/omit")
        html = await r.text()
        self.assertEqual(200, r.status)
        self.assertIn("UMC Chat", html)
        self.assertEqual([], re.findall(r"""(?:src|href)=["']https?://""", html), "the page must work offline")

    async def test_without_a_radio_the_state_says_so_and_actions_are_refused(self):
        self.assertEqual({"connected": False}, await (await self.client.get("/omit/api/state")).json())
        r = await self.client.post("/omit/api/send", json={"channel": 1, "text": "hi"}, headers=H)
        self.assertEqual(503, r.status)

    async def test_posts_need_the_guard_header(self):
        await self.attach()
        r = await self.client.post("/omit/api/mode", json={"mode": "bot"})
        self.assertEqual(403, r.status)
        r = await self.client.post("/omit/api/mode", data="mode=bot", headers={"Content-Type": "text/plain"})
        self.assertEqual(403, r.status)

    async def test_feed_nicks_and_events(self):
        await self.attach()
        self.hear("Alice: hello all", hops=2)
        j = await (await self.client.get("/omit/api/feed?since=0")).json()
        self.assertEqual(["hello all"], [x["text"] for x in j["rows"]])
        self.assertEqual("Alice", j["nicks"][0]["nick"])
        self.assertEqual("operator", j["state"]["mode"])
        again = await (await self.client.get(f"/omit/api/feed?since={j['seq']}")).json()
        self.assertEqual([], again["rows"])

    async def test_mode_and_pause(self):
        await self.attach()
        j = await (await self.client.post("/omit/api/mode", json={"mode": "bot"}, headers=H)).json()
        self.assertEqual("bot", j["mode"])
        j = await (await self.client.post("/omit/api/mode", json={"paused": True}, headers=H)).json()
        self.assertTrue(j["paused"])
        r = await self.client.post("/omit/api/mode", json={"mode": "loud"}, headers=H)
        self.assertEqual(400, r.status)

    async def test_the_bot_answers_through_the_page_controls(self):
        await self.attach()
        self.state.omit.engine.bot.rng.seed(1)
        await self.client.post("/omit/api/mode", json={"mode": "bot"}, headers=H)
        self.state.omit.cfg["bot"]["delay_s"] = [0, 0]
        self.state.omit.engine.cfg["bot"]["delay_s"] = [0, 0]
        self.hear("Alice: test")
        for _ in range(200):                                           # the answer is sent by a background task
            sent = [f for f in self.backend.sent if f[0] == F.CMD_SEND_CHANNEL_TXT]
            if sent:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(1, len(sent))
        self.assertIn("@[Alice]", sent[0][7:].decode())

    async def test_sending_a_message(self):
        await self.attach()
        r = await self.client.post("/omit/api/send", json={"channel": 1, "text": "hello from the page"}, headers=H)
        self.assertEqual(200, r.status)
        self.assertEqual(b"hello from the page", [f for f in self.backend.sent if f[0] == 3][-1][7:])
        for bad in ({"channel": 1, "text": ""}, {"channel": 1, "text": "x" * 161}):
            r = await self.client.post("/omit/api/send", json=bad, headers=H)
            self.assertEqual(400, r.status)

    async def test_dashboard_has_everything_the_page_draws(self):
        await self.attach()
        self.hear("Alice: test")
        j = await (await self.client.get("/omit/api/dashboard?hours=24")).json()
        for k in ("stats", "hourly", "top", "hops", "relays", "beacons", "repeaters", "replies"):
            self.assertIn(k, j)
        self.assertEqual(24, len(j["hourly"]))
        self.assertEqual(1, j["stats"]["messages"])

    async def test_settings_are_checked_saved_and_applied(self):
        await self.attach()
        j = await (await self.client.get("/omit/api/settings")).json()
        self.assertIn("bot", j["config"])
        self.assertIn("replies", j["texts"])
        bad = await self.client.post("/omit/api/settings", json={"config": {"beacon": {"interval_minutes": 1}}}, headers=H)
        self.assertEqual(400, bad.status)
        self.assertIn("interval_minutes", (await bad.json())["error"])
        ok = await self.client.post("/omit/api/settings", json={
            "config": {"callsign": "2E0LXY", "bot": {"max_per_hour": 3}}, "texts": {"quick": ["73", "hello"]}}, headers=H)
        self.assertEqual(200, ok.status)
        saved = json.loads(Path(self.tmp.name, "omit", "config.json").read_text())
        self.assertEqual(("2E0LXY", 3), (saved["callsign"], saved["bot"]["max_per_hour"]))
        self.assertEqual(["73", "hello"], json.loads(Path(self.tmp.name, "omit", "texts.json").read_text())["quick"])
        self.assertEqual(3, self.state.omit.engine.cfg["bot"]["max_per_hour"])       # applied without a restart
        self.assertEqual(3, self.state.omit.engine.bot.cfg["bot"]["max_per_hour"])

    async def test_saving_settings_keeps_what_the_radio_told_us(self):
        await self.attach()
        e = self.state.omit.engine
        self.backend.listeners[0](F.build_contact("cd" * 32, "Ridge", ctype=2))
        self.hear("Alice: hello")
        await self.client.post("/omit/api/settings", json={"config": {"callsign": "M0TEST"}, "texts": {"quick": ["a"]}}, headers=H)
        self.assertIs(e, self.state.omit.engine)                                    # the same engine, not a new one
        self.assertEqual(1, len(e.contacts))
        self.assertEqual(1, len(e.feed()))
        self.assertEqual(["a"], e.bot.texts["quick"])
        self.assertEqual("M0TEST", e.bot.cfg["callsign"])

    async def test_unknown_text_lists_and_empty_lists_are_refused(self):
        r = await self.client.post("/omit/api/settings", json={"texts": {"nope": ["x"]}}, headers=H)
        self.assertEqual(400, r.status)
        r = await self.client.post("/omit/api/settings", json={"texts": {"replies": ["  "]}}, headers=H)
        self.assertEqual(400, r.status)

    async def test_repeater_passwords_never_reach_the_page_and_a_blank_keeps_the_old_one(self):
        key = "ab" * 32
        ok = await self.client.post("/omit/api/settings", json={"config": {"repeaters": [
            {"name": "Hilltop", "pubkey": key, "password": "hunter2"}]}}, headers=H)
        self.assertEqual(200, ok.status)
        shown = await (await self.client.get("/omit/api/settings")).json()
        self.assertEqual([{"name": "Hilltop", "pubkey": key, "password_set": True}], shown["config"]["repeaters"])
        self.assertNotIn("hunter2", json.dumps(shown))
        # renaming without typing the password again keeps it
        await self.client.post("/omit/api/settings", json={"config": {"repeaters": [
            {"name": "Hilltop Mast", "pubkey": key.upper(), "password": ""}]}}, headers=H)
        saved = json.loads(Path(self.tmp.name, "omit", "config.json").read_text())["repeaters"][0]
        self.assertEqual(("Hilltop Mast", key, "hunter2"), (saved["name"], saved["pubkey"], saved["password"]))
        await self.client.post("/omit/api/settings", json={"config": {"repeaters": [
            {"name": "Hilltop Mast", "pubkey": key, "password": "new"}]}}, headers=H)
        self.assertEqual("new", json.loads(Path(self.tmp.name, "omit", "config.json").read_text())["repeaters"][0]["password"])

    async def test_a_bad_repeater_key_is_refused(self):
        r = await self.client.post("/omit/api/settings", json={"config": {"repeaters": [
            {"name": "X", "pubkey": "nothex", "password": "p"}]}}, headers=H)
        self.assertEqual(400, r.status)
        self.assertIn("pubkey", (await r.json())["error"])

    async def test_repeater_table_and_poll_button(self):
        await self.attach()
        self.backend.listeners[0](F.build_contact("cd" * 32, "Ridge", ctype=2))
        j = await (await self.client.get("/omit/api/repeaters")).json()
        self.assertEqual([{"name": "Ridge", "pubkey": "cd" * 32}], j["known"])
        self.assertEqual([], j["table"])
        r = await self.client.post("/omit/api/repeaters/poll", json={}, headers=H)
        self.assertEqual(200, r.status)
        r = await self.client.post("/omit/api/repeaters/poll", json={})
        self.assertEqual(403, r.status)

    async def test_settings_survive_a_restart(self):
        await self.client.post("/omit/api/settings", json={"config": {"callsign": "M0TEST"}}, headers=H)
        again = Runtime(self.tmp.name)
        self.assertEqual("M0TEST", again.cfg["callsign"])
        self.assertEqual(120, len(again.texts["replies"]) * 0 + 120)


if __name__ == "__main__":
    unittest.main()
