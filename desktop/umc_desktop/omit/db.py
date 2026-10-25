"""The SQLite store: everything the bot hears and does, queryable while it runs (WAL mode)."""
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sender_ts REAL, channel_idx INTEGER, channel_name TEXT,
  sender TEXT, text TEXT, hops INTEGER, snr REAL, rssi REAL, path TEXT, copies INTEGER DEFAULT 1,
  kind TEXT, is_trigger INTEGER DEFAULT 0, reply_to INTEGER, beacon_id INTEGER);
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
CREATE TABLE IF NOT EXISTS beacons(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, channel_idx INTEGER, text TEXT, replies INTEGER DEFAULT 0,
  message_id INTEGER);
CREATE TABLE IF NOT EXISTS rx_packets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, payload_type INTEGER, route_type INTEGER, snr REAL, rssi REAL,
  hash_size INTEGER, hops INTEGER, path TEXT, last_hop TEXT, channel_name TEXT, sender_ts REAL, text TEXT);
CREATE TABLE IF NOT EXISTS repeater_status(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, name TEXT, pubkey TEXT, ok INTEGER, bat_mv INTEGER,
  uptime_s INTEGER, noise_floor INTEGER, last_rssi INTEGER, n_recv INTEGER, n_sent INTEGER, airtime_s INTEGER,
  tx_queue INTEGER, trace_there REAL, trace_back REAL, note TEXT);
CREATE INDEX IF NOT EXISTS repeater_status_ts ON repeater_status(name, ts);
CREATE TABLE IF NOT EXISTS repeater_neighbors(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, repeater TEXT, neighbor TEXT, neighbor_name TEXT,
  secs_ago INTEGER, snr REAL);
CREATE TABLE IF NOT EXISTS reply_history(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sender TEXT, template TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, text TEXT);
"""

MESSAGE_FIELDS = ("ts", "sender_ts", "channel_idx", "channel_name", "sender", "text", "hops", "snr", "rssi",
                  "path", "copies", "kind", "is_trigger", "reply_to", "beacon_id")


class Db:
    def __init__(self, path=":memory:"):
        self._lock = threading.Lock()
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.c.row_factory = sqlite3.Row
        if path != ":memory:":
            self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)

    def close(self):
        with self._lock:
            self.c.close()

    # ---- writing
    def _insert(self, table, row):
        keys = list(row)
        with self._lock:
            cur = self.c.execute(f"INSERT INTO {table}({','.join(keys)}) VALUES({','.join('?' * len(keys))})",
                                 [row[k] for k in keys])
            self.c.commit()
            return cur.lastrowid

    def add_message(self, rec):
        row = {k: rec.get(k) for k in MESSAGE_FIELDS if k in rec}
        row.setdefault("ts", time.time())
        if isinstance(row.get("path"), (list, tuple)):
            row["path"] = ">".join(row["path"])
        return self._insert("messages", row)

    def add_beacon(self, ts, channel_idx, text, message_id=None):
        return self._insert("beacons", {"ts": ts, "channel_idx": channel_idx, "text": text, "message_id": message_id})

    def count_beacon_reply(self, beacon_id):
        with self._lock:
            self.c.execute("UPDATE beacons SET replies = replies + 1 WHERE id = ?", (beacon_id,))
            self.c.commit()

    def add_rx_packet(self, row):
        row = dict(row)
        row.setdefault("ts", time.time())
        return self._insert("rx_packets", row)

    def add_repeater_status(self, row):
        row = dict(row)
        row.setdefault("ts", time.time())
        return self._insert("repeater_status", row)

    def add_neighbor(self, row):
        row = dict(row)
        row.setdefault("ts", time.time())
        return self._insert("repeater_neighbors", row)

    def add_reply_history(self, sender, template, ts=None):
        return self._insert("reply_history", {"ts": ts or time.time(), "sender": sender, "template": str(template)})

    def clear_reply_history(self, sender):
        with self._lock:
            self.c.execute("DELETE FROM reply_history WHERE sender = ?", (sender,))
            self.c.commit()

    def add_event(self, level, text, ts=None):
        return self._insert("events", {"ts": ts or time.time(), "level": level, "text": text})

    # ---- reading
    def _all(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self.c.execute(sql, args).fetchall()]

    def _one(self, sql, args=()):
        rows = self._all(sql, args)
        return rows[0] if rows else {}

    def reply_history(self, sender):
        return [r["template"] for r in self._all("SELECT template FROM reply_history WHERE sender = ?", (sender,))]

    def recent_messages(self, limit=200, channel_idx=None, since_id=0):
        sql, args = "SELECT * FROM messages WHERE id > ?", [since_id]
        if channel_idx is not None:
            sql += " AND channel_idx = ?"
            args.append(channel_idx)
        rows = self._all(sql + " ORDER BY id DESC LIMIT ?", args + [limit])
        return list(reversed(rows))

    def recent_events(self, limit=100):
        return list(reversed(self._all("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))))

    # ---- what the dashboard shows (the last `hours` hours)
    def stats(self, now, hours=24):
        since = now - hours * 3600
        return self._one(
            "SELECT COUNT(*) AS messages,"
            " SUM(CASE WHEN is_trigger = 1 AND kind IN ('rx','beacon_reply') THEN 1 ELSE 0 END) AS tests,"
            " SUM(CASE WHEN kind = 'bot_reply' THEN 1 ELSE 0 END) AS answers,"
            " COUNT(DISTINCT CASE WHEN kind IN ('rx','beacon_reply','backlog') THEN sender END) AS stations"
            " FROM messages WHERE ts >= ?", (since,))

    def hourly(self, now, hours=24):
        """One row per hour, oldest first: messages and tests heard."""
        since = now - hours * 3600
        rows = self._all(
            "SELECT CAST((ts - ?) / 3600 AS INTEGER) AS h, COUNT(*) AS messages,"
            " SUM(CASE WHEN is_trigger = 1 THEN 1 ELSE 0 END) AS tests"
            " FROM messages WHERE ts >= ? AND kind IN ('rx','beacon_reply') GROUP BY h", (since, since))
        by = {r["h"]: r for r in rows}
        return [{"hour": i, "messages": (by.get(i) or {}).get("messages", 0), "tests": (by.get(i) or {}).get("tests") or 0}
                for i in range(hours)]

    def top_senders(self, now, hours=24, limit=10):
        return self._all(
            "SELECT sender, COUNT(*) AS n FROM messages WHERE ts >= ? AND kind IN ('rx','beacon_reply')"
            " GROUP BY sender ORDER BY n DESC LIMIT ?", (now - hours * 3600, limit))

    def hops_histogram(self, now, hours=24):
        return self._all(
            "SELECT hops, COUNT(*) AS n FROM messages WHERE ts >= ? AND hops IS NOT NULL AND kind IN ('rx','beacon_reply')"
            " GROUP BY hops ORDER BY hops", (now - hours * 3600,))

    def relay_counts(self, now, hours=24, limit=10):
        """Which repeaters carried the traffic: counted from the path of each message."""
        counts = {}
        for r in self._all("SELECT path FROM messages WHERE ts >= ? AND path IS NOT NULL AND path != ''",
                           (now - hours * 3600,)):
            for hop in r["path"].split(">"):
                counts[hop] = counts.get(hop, 0) + 1
        return sorted(({"repeater": k, "n": v} for k, v in counts.items()), key=lambda x: -x["n"])[:limit]

    def beacon_summary(self, now, hours=24):
        return self._one(
            "SELECT COUNT(*) AS sent, COALESCE(SUM(CASE WHEN replies > 0 THEN 1 ELSE 0 END), 0) AS answered,"
            " COALESCE(SUM(replies), 0) AS replies FROM beacons WHERE ts >= ?", (now - hours * 3600,))

    def last_repeater_status(self):
        return self._all(
            "SELECT s.* FROM repeater_status s JOIN (SELECT name, MAX(ts) AS t FROM repeater_status GROUP BY name) m"
            " ON s.name = m.name AND s.ts = m.t ORDER BY s.name")

    def repeater_history(self, name, now, hours=24):
        return self._all("SELECT * FROM repeater_status WHERE name = ? AND ts >= ? ORDER BY ts",
                         (name, now - hours * 3600))

    def recent_replies(self, limit=20):
        return self._all("SELECT * FROM messages WHERE kind = 'bot_reply' ORDER BY id DESC LIMIT ?", (limit,))
