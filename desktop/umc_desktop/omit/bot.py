"""The decisions: when to answer a test call, what to say, when to beacon. No radio, no screen,
no clock of its own (the time and the dice are passed in), so every rule can be tested."""
import copy
import random
import re
import time
from collections import deque
from dataclasses import dataclass

from . import texts as T
from .config import MAX_REPLY

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalise(text):
    """Lower case, punctuation ignored, spaces collapsed: "Radio  check?" -> "radio check"."""
    return _SPACES.sub(" ", _PUNCT.sub("", (text or "").lower())).strip()


@dataclass
class Decision:
    action: str            # "reply": answer after `delay`; "quiet": a trigger we chose not to answer; "ignore": not for us
    reason: str = ""
    delay: float = 0.0
    kind: str = "reply"    # "reply" (a test call) or "mention"


class Bot:
    def __init__(self, cfg, texts=None, db=None, now=time.time, rng=None):
        self.cfg = cfg
        self.texts = copy.deepcopy(texts or T.DEFAULT_TEXTS)
        self.db = db
        self.now = now
        self.rng = rng or random.Random()
        self.mode = cfg.get("start_mode", "operator")
        self.paused = False
        self.node_name = cfg.get("node_name", "")
        self._last_by_sender = {}
        self._answers = deque()
        self._history = {}                    # sender -> template indexes already given (used without a database)
        self._last_beacon = None
        self.current_beacon = None            # {"id", "ts", "text"}
        self._next_beacon = None

    # ---------------------------------------------------------------- what a message is
    def is_trigger(self, text):
        return normalise(text) in {normalise(t) for t in self.cfg["bot"]["triggers"]}

    def mentions_me(self, text):
        name = (self.node_name or "").strip().lower()
        if not name:
            return False
        return re.search(r"@\[\s*" + re.escape(name) + r"\s*\]", (text or "").lower()) is not None

    def set_mode(self, mode):
        if mode not in ("operator", "bot"):
            raise ValueError("mode is operator or bot")
        self.mode = mode

    # ---------------------------------------------------------------- should we answer?
    def _prune(self, now):
        while self._answers and now - self._answers[0] > 3600:
            self._answers.popleft()

    def decide(self, rec):
        """rec: ts, channel_idx, sender, text, kind ("rx" or "backlog") ... -> a Decision."""
        b = self.cfg["bot"]
        trigger = self.is_trigger(rec.get("text", ""))
        mention = b.get("answer_mentions") and not trigger and self.mentions_me(rec.get("text", ""))
        if not (trigger or mention):
            return Decision("ignore")
        kind = "mention" if mention else "reply"
        sender = rec.get("sender", "")
        now = self.now()
        if not b.get("enabled", True):
            return Decision("quiet", "the bot is switched off in the settings", kind=kind)
        if self.mode != "bot":
            return Decision("quiet", "operator mode: only answering in bot mode", kind=kind)
        if self.paused:
            return Decision("quiet", "paused", kind=kind)
        if rec.get("kind") == "backlog":
            return Decision("quiet", "queued on the node before the program started", kind=kind)
        if rec.get("channel_idx") not in b.get("reply_channels", []):
            return Decision("quiet", "not a reply channel", kind=kind)
        low = sender.lower()
        if any(w.lower() in low for w in b.get("ignore_senders_containing", []) if w):
            return Decision("quiet", f"{sender} looks like a bot", kind=kind)
        last = self._last_by_sender.get(sender)
        if last is not None and now - last < b.get("per_sender_minutes", 10) * 60:
            return Decision("quiet", f"answered {sender} less than {b.get('per_sender_minutes', 10)} minutes ago", kind=kind)
        self._prune(now)
        if len(self._answers) >= b.get("max_per_hour", 6):
            return Decision("quiet", "the hourly limit is reached", kind=kind)
        lo, hi = b.get("delay_s", [2, 6])
        return Decision("reply", "", delay=self.rng.uniform(lo, hi), kind=kind)

    # ---------------------------------------------------------------- what to say
    def _values(self, rec):
        snr, rssi = rec.get("snr"), rec.get("rssi")
        path = rec.get("path_names") or rec.get("path")
        if isinstance(path, str):
            path = [p for p in path.split(">") if p]
        return {
            "name": rec.get("sender", ""), "me": self.node_name or "this node",
            "callsign": self.cfg.get("callsign", ""),
            "location": self.rng.choice(self.cfg["locations"]),
            "hops": T.hops_text(rec.get("hops")),
            "snr": "?" if snr is None else f"{snr:.1f}", "rssi": "?" if rssi is None else f"{int(rssi)}",
            "path": ">".join(path) if path else "?", "greeting": T.pick_greeting(self.rng),
            "daypart": T.daypart(time.localtime(self.now()).tm_hour),
        }

    def _tail(self):
        tail = self.cfg["bot"].get("signature", "")
        cs = self.cfg.get("callsign", "")
        return tail + (f" {cs}" if cs and cs not in tail else "")

    def _finish(self, body):
        tail = self._tail()
        body = body[:MAX_REPLY - len(tail)].rstrip()
        return body + tail

    def _given(self, sender):
        return set(self.db.reply_history(sender)) if self.db is not None else {str(i) for i in self._history.get(sender, ())}

    def build_reply(self, rec, kind="reply"):
        """-> (text, template index). Each station gets every line once before any line repeats; lines
        that quote the SNR or RSSI are skipped when the message did not say."""
        pool = self.texts["mentions" if kind == "mention" else "replies"]
        key = ("mentions:" if kind == "mention" else "")
        known = rec.get("snr") is not None and rec.get("rssi") is not None
        usable = [i for i, t in enumerate(pool) if known or not T.uses(t, "snr", "rssi")]
        if not usable:
            usable = list(range(len(pool)))
        sender = rec.get("sender", "")
        given = self._given(sender)
        fresh = [i for i in usable if f"{key}{i}" not in given]
        if not fresh:                                                  # all given: start the round again
            if self.db is not None:
                self.db.clear_reply_history(sender)
            self._history.pop(sender, None)
            fresh = usable
        idx = self.rng.choice(fresh)
        return self._finish(T.fill(pool[idx], self._values(rec))), idx

    def commit_reply(self, rec, idx, kind="reply"):
        """Call when the answer has really been sent: starts the per-station wait and the hourly count."""
        sender, now = rec.get("sender", ""), self.now()
        self._last_by_sender[sender] = now
        self._answers.append(now)
        key = ("mentions:" if kind == "mention" else "") + str(idx)
        if self.db is not None:
            self.db.add_reply_history(sender, key, now)
        else:
            self._history.setdefault(sender, set()).add(key)

    # ---------------------------------------------------------------- beacons
    def beacon_enabled(self):
        return bool(self.cfg["beacon"].get("enabled"))

    def schedule_first_beacon(self):
        self._next_beacon = self.now() + self.cfg["beacon"].get("first_after_s", 60)

    def seconds_to_beacon(self):
        return None if self._next_beacon is None else max(0.0, self._next_beacon - self.now())

    def beacon_due(self):
        """True when a beacon should be sent now: bot mode, switched on, not paused, time reached."""
        return (self.beacon_enabled() and self.mode == "bot" and not self.paused
                and self._next_beacon is not None and self.now() >= self._next_beacon)

    def next_beacon_text(self):
        """A beacon line, never the same as the last one when there is a choice."""
        pool = self.texts["beacons"]
        idxs = [i for i in range(len(pool)) if i != self._last_beacon] or list(range(len(pool)))
        idx = self.rng.choice(idxs)
        self._last_beacon = idx
        rec = {"sender": "", "snr": None, "rssi": None, "hops": None}
        return self._finish(T.fill(pool[idx], self._values(rec)))

    def commit_beacon(self, text, beacon_id=None):
        now = self.now()
        self.current_beacon = {"id": beacon_id, "ts": now, "text": text}
        self._next_beacon = now + self.cfg["beacon"].get("interval_minutes", 30) * 60

    def note_message(self, rec):
        """Does this message answer the last beacon (it names this node inside the reply window)?
        Returns the beacon id when it does, else None."""
        cb = self.current_beacon
        if cb is None or rec.get("kind") not in ("rx", "beacon_reply"):
            return None
        window = self.cfg["beacon"].get("reply_window_minutes", 10) * 60
        if self.now() - cb["ts"] > window:
            return None
        return cb["id"] if self.mentions_me(rec.get("text", "")) else None
