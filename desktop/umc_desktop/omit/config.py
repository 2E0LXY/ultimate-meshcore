"""Settings for the chat bot, with defaults, merging and checking. JSON on disk, a form in the UI."""
import copy

DEFAULTS = {
    "node_name": "",                      # taken from the node when empty
    "callsign": "",                       # added to replies and beacons when set (station identification)
    "locations": ["Wakefield"],           # place names for {location}; one at random each time
    "channels": {"0": "Public", "1": "#test"},
    "start_mode": "operator",             # "bot" answers and beacons at once
    "bot": {
        "enabled": True,
        "reply_channels": [1],            # the bot listens everywhere, answers only here
        "triggers": ["test", "ping", "radio check"],
        "per_sender_minutes": 10,         # one answer per station per this many minutes
        "max_per_hour": 6,                # never more than this in a rolling hour
        "delay_s": [2, 6],                # wait a random time in this range before answering
        "ignore_senders_containing": ["bot"],
        "answer_mentions": False,
        "signature": " [auto]",           # says the reply is automatic; empty it only if your rules allow
    },
    "beacon": {
        "enabled": False,                 # a beacon is a message to everyone: switched on deliberately
        "channel": 1,
        "interval_minutes": 30,
        "first_after_s": 60,
        "reply_window_minutes": 10,
    },
    "repeaters": [],                      # [{"name": ..., "pubkey": 64 hex, "password": ...}]
    "repeater_poll_minutes": 30,
    "known_prefixes": {},                 # {"381f": "Hilltop"}: names for repeater hashes in packet paths
}

MAX_REPLY = 160                           # characters; one LoRa message


def merge(base, over):
    """Return base with over laid on top, key by key, without changing either."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("channels", "known_prefixes"):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def check(cfg):
    """A list of problems in a settings dict; empty means it is usable."""
    bad = []
    b, bc = cfg.get("bot", {}), cfg.get("beacon", {})
    if not isinstance(b.get("triggers"), list) or not b.get("triggers"):
        bad.append("bot.triggers must be a list with at least one word")
    d = b.get("delay_s")
    if not (isinstance(d, list) and len(d) == 2 and 0 <= d[0] <= d[1] <= 60):
        bad.append("bot.delay_s must be [low, high] seconds, 0 to 60")
    if not (isinstance(b.get("per_sender_minutes"), (int, float)) and b["per_sender_minutes"] >= 0):
        bad.append("bot.per_sender_minutes must be 0 or more")
    if not (isinstance(b.get("max_per_hour"), int) and 0 <= b["max_per_hour"] <= 120):
        bad.append("bot.max_per_hour must be 0 to 120")
    if not (isinstance(bc.get("interval_minutes"), (int, float)) and bc["interval_minutes"] >= 5):
        bad.append("beacon.interval_minutes must be at least 5: a beacon is a message to everyone")
    if not cfg.get("locations"):
        bad.append("locations needs at least one place name")
    for r in cfg.get("repeaters", []):
        key = str(r.get("pubkey", ""))
        if len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key):
            bad.append(f"repeater {r.get('name', '?')}: pubkey must be 64 hex digits")
    return bad
