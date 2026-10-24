"""Joins the bot to a companion radio: reads its frames, keeps the feed, answers, beacons.

It talks to the radio through a small backend object (`listeners`, `cmd`) so a test can stand in
for the radio. Nothing here draws anything: the Desktop app's web page reads `state()` and `feed()`.
"""
import asyncio
import collections
import time

from . import frames as F
from .bot import Bot
from .repeaters import Monitor


class Engine:
    FEED_MAX = 500

    def __init__(self, backend, cfg, db, texts=None, now=time.time, rng=None, sleep=asyncio.sleep):
        self.backend, self.cfg, self.db, self.now, self.sleep = backend, cfg, db, now, sleep
        self.bot = Bot(cfg, texts, db=db, now=now, rng=rng)
        self.channels = {int(k): v for k, v in cfg.get("channels", {}).items()}
        self.contacts = {}                                    # pubkey hex -> contact dict
        self.feed_rows = collections.deque(maxlen=self.FEED_MAX)
        self.rx_memory = collections.deque(maxlen=60)         # recent raw packets, to find the path of a message
        self.counters = {"heard": 0, "tests": 0, "answers": 0, "beacons": 0, "beacon_replies": 0}
        self.events = collections.deque(maxlen=100)
        self.started_at = now()
        self.tasks = []
        self.waiters = []                                     # (match function, future): answers someone is waiting for
        self._seq = 0
        self.monitor = Monitor(self)
        if self.bot.node_name == "" and getattr(backend, "me", None):
            self.bot.node_name = backend.me.get("name", "")
        backend.listeners.append(self.on_frame)

    # ---------------------------------------------------------------- events and the feed
    def event(self, level, text):
        self.events.append({"ts": self.now(), "level": level, "text": text})
        self.db.add_event(level, text, self.now())

    def _push(self, rec):
        self._seq += 1
        rec = dict(rec, seq=self._seq)
        self.feed_rows.append(rec)
        return rec

    def preload(self, rows):
        """Put the last rows from the database into the feed, so the page is not empty after a restart."""
        for r in sorted(rows, key=lambda x: x.get("ts") or 0):
            r = dict(r)
            r["path_names"] = [x for x in (r.get("path") or "").split(">") if x]
            self._push(r)

    def feed(self, since=0):
        return [r for r in self.feed_rows if r["seq"] > since]

    # ---------------------------------------------------------------- reading the radio
    def on_frame(self, frame):
        """Called for every frame the radio sends. Must not raise or block."""
        try:
            f = F.parse(bytes(frame))
            if f is None:
                return
            for entry in list(self.waiters):
                if not entry[1].done() and entry[0](f):
                    entry[1].set_result(f)
            kind = f["kind"]
            if kind == "log_rx":
                self._on_log_rx(f)
            elif kind == "channel_msg":
                self._on_channel_msg(f)
            elif kind == "contact_msg":
                self._on_contact_msg(f)
            elif kind == "contact":
                self.contacts[f["pubkey"]] = f
            elif kind == "channel_info":
                self.channels[f["idx"]] = f["name"] or self.channels.get(f["idx"], f"slot {f['idx']}")
        except Exception as err:                                # one bad frame must not stop the bot
            self.event("warn", f"could not read a frame: {err}")

    def _name_for_hash(self, h):
        h = h.lower()
        known = self.cfg.get("known_prefixes", {})
        if h in known:
            return known[h]
        for pk, c in self.contacts.items():
            if c.get("type") == 2 and pk.startswith(h):
                return c["name"] or h
        return h

    def _on_log_rx(self, f):
        pkt = f["packet"]
        if pkt is None:
            return
        self.rx_memory.append({"ts": self.now(), "snr": f["snr"], "rssi": f["rssi"], "packet": pkt})
        self.db.add_rx_packet({"ts": self.now(), "payload_type": pkt["type"], "route_type": pkt["route"],
                               "snr": f["snr"], "rssi": f["rssi"], "hash_size": pkt["hash_size"], "hops": pkt["hops"],
                               "path": ">".join(pkt["path"]), "last_hop": pkt["path"][-1] if pkt["path"] else ""})

    def _copy_for(self, snr):
        """The raw packet the radio delivered: a recent group text with the same SNR."""
        now = self.now()
        for m in reversed(self.rx_memory):
            if now - m["ts"] > 6:
                break
            if m["packet"]["type"] == F.GRP_TXT and abs(m["snr"] - snr) < 0.01:
                return m
        return None

    def _on_channel_msg(self, f):
        sender, text = F.split_sender(f["text"])
        now = self.now()
        copy = self._copy_for(f["snr"])
        hops = f["hops"]
        rssi, path = None, []
        if copy:
            rssi = copy["rssi"]
            path = [self._name_for_hash(h) for h in copy["packet"]["path"]]
            if hops is None:
                hops = copy["packet"]["hops"]
        backlog = now - f["timestamp"] > 120 if f["timestamp"] else False
        rec = {"ts": now, "sender_ts": f["timestamp"], "channel_idx": f["channel_idx"],
               "channel_name": self.channels.get(f["channel_idx"], f"slot {f['channel_idx']}"), "sender": sender,
               "text": text, "hops": hops, "snr": f["snr"], "rssi": rssi, "path": ">".join(path), "path_names": path,
               "kind": "backlog" if backlog else "rx"}
        mine = sender == self.bot.node_name and sender != ""
        if mine:
            return                                              # our own message echoed back by a repeater
        rec["is_trigger"] = 1 if self.bot.is_trigger(text) else 0
        beacon_id = self.bot.note_message(rec)
        if beacon_id is not None:
            rec["kind"], rec["beacon_id"] = "beacon_reply", beacon_id
            self.db.count_beacon_reply(beacon_id)
            self.counters["beacon_replies"] += 1
        rec["id"] = self.db.add_message(rec)
        self.counters["heard"] += 1
        self.counters["tests"] += rec["is_trigger"]
        self._push(rec)
        decision = self.bot.decide(rec)
        if decision.action == "quiet":
            self.event("info", f"not answering {sender}: {decision.reason}")
        elif decision.action == "reply":
            self.tasks.append(asyncio.ensure_future(self._answer(rec, decision)))

    def _on_contact_msg(self, f):
        if f["txt_type"] == F.TXT_CLI:
            return                                              # a repeater answering a command: not a chat message
        pk = next((k for k in self.contacts if k.startswith(f["prefix"])), None)
        sender = self.contacts[pk]["name"] if pk else f["prefix"]
        rec = {"ts": self.now(), "sender_ts": f["timestamp"], "channel_idx": -1, "channel_name": "DM", "sender": sender,
               "text": f["text"], "hops": f["hops"], "snr": f["snr"], "kind": "dm", "path": ""}
        rec["id"] = self.db.add_message(rec)
        self._push(rec)

    # ---------------------------------------------------------------- answering and sending
    async def _answer(self, rec, decision):
        await self.sleep(decision.delay)
        if self.bot.mode != "bot" or self.bot.paused:                      # changed our mind while waiting
            self.event("info", f"not answering {rec['sender']}: mode changed")
            return
        text, idx = self.bot.build_reply(rec, decision.kind)
        if await self.send_channel(rec["channel_idx"], text, kind="bot_reply", reply_to=rec.get("id")):
            self.bot.commit_reply(rec, idx, decision.kind)
            self.counters["answers"] += 1

    async def send_channel(self, channel_idx, text, kind="tx", reply_to=None, beacon_id=None):
        """Send a message to a channel and record it. Returns True when the radio took it."""
        try:
            await self.backend.cmd(F.send_channel(channel_idx, text, self.now()), expect=0)
        except Exception as err:
            self.event("warn", f"could not send: {err}")
            return False
        row = {"ts": self.now(), "channel_idx": channel_idx, "channel_name": self.channels.get(channel_idx, ""),
               "sender": self.bot.node_name or "me", "text": text, "kind": kind, "reply_to": reply_to,
               "beacon_id": beacon_id, "path": ""}
        row["id"] = self.db.add_message(row)
        self._push(row)
        return True

    async def send_beacon(self):
        text = self.bot.next_beacon_text()
        ch = self.cfg["beacon"]["channel"]
        bid = self.db.add_beacon(self.now(), ch, text)
        if await self.send_channel(ch, text, kind="beacon", beacon_id=bid):
            self.bot.commit_beacon(text, bid)
            self.counters["beacons"] += 1
            self.event("ok", "beacon sent")

    async def beacon_loop(self):
        self.bot.schedule_first_beacon()
        while True:
            await self.sleep(5)
            if self.bot.beacon_due():
                await self.send_beacon()

    # ---------------------------------------------------------------- start up, control, state
    async def load_channels(self):
        for idx in range(8):
            try:
                r = await self.backend.cmd(F.get_channel(idx), expect=F.RESP_CHANNEL_INFO)
            except Exception:
                break
            self.on_frame(r)

    async def start(self):
        await self.load_channels()
        try:
            await self.backend.cmd(F.get_contacts(), timeout=25)
        except Exception:
            self.event("warn", "contacts did not load yet")
        self.tasks.append(asyncio.ensure_future(self.beacon_loop()))
        self.tasks.append(asyncio.ensure_future(self.monitor.loop()))
        self.event("ok", "chat bot started in " + self.bot.mode + " mode")

    def stop(self):
        for t in self.tasks:
            t.cancel()
        if self.on_frame in self.backend.listeners:
            self.backend.listeners.remove(self.on_frame)

    def reconfigure(self, cfg, texts=None):
        """New settings, applied in place: the feed, counters, contacts and mode are kept."""
        import copy
        self.cfg = cfg
        self.bot.cfg = cfg
        if texts is not None:
            self.bot.texts = copy.deepcopy(texts)
        if cfg.get("node_name"):
            self.bot.node_name = cfg["node_name"]
        self.channels.update({int(k): v for k, v in cfg.get("channels", {}).items() if int(k) not in self.channels})
        self.event("ok", "settings applied")

    def set_mode(self, mode):
        self.bot.set_mode(mode)
        self.event("ok", f"mode: {mode}")

    def nicks(self, hours=3):
        """Who spoke lately in each window, most recent first."""
        cutoff, seen = self.now() - hours * 3600, {}
        for r in self.feed_rows:
            if r["ts"] >= cutoff and r["kind"] in ("rx", "beacon_reply", "backlog") and r["sender"]:
                n = seen.setdefault(r["sender"], {"nick": r["sender"], "last": r["ts"], "n": 0, "hops": r.get("hops")})
                n["last"], n["hops"], n["n"] = r["ts"], r.get("hops"), n["n"] + 1
        return sorted(seen.values(), key=lambda n: -n["last"])

    def state(self):
        b = self.bot
        return {"mode": b.mode, "paused": b.paused, "node": b.node_name, "uptime": int(self.now() - self.started_at),
                "channels": {str(k): v for k, v in sorted(self.channels.items())}, "contacts": len(self.contacts),
                "counters": dict(self.counters), "next_beacon": b.seconds_to_beacon(),
                "beacon_enabled": b.beacon_enabled(), "reply_channels": self.cfg["bot"]["reply_channels"]}
