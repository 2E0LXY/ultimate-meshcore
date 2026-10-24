"""Watching your repeaters: log in, ask for their statistics, trace the path there and back, read their
neighbours, and keep every reading. Runs on a timer, in Operator mode too (it only listens and asks)."""
import asyncio
import random

from . import frames as F

BAT_EMPTY_MV, BAT_FULL_MV = 3200, 4200          # a rough single-cell curve: good for "about how full", not for gauges


def battery_percent(mv):
    if not mv:
        return None
    return max(0, min(100, round(100 * (mv - BAT_EMPTY_MV) / (BAT_FULL_MV - BAT_EMPTY_MV))))


def parse_neighbors(text):
    """The repeater's `neighbors` reply: lines of "<8 hex>:<seconds ago>:<snr x4>", or "-none-"."""
    out = []
    for line in (text or "").splitlines():
        parts = line.strip().split(":")
        if len(parts) != 3:
            continue
        try:
            out.append({"id": parts[0].lower(), "secs_ago": int(parts[1]), "snr": int(parts[2]) / 4.0})
        except ValueError:
            continue
    return out


class Monitor:
    def __init__(self, engine, timeout=15.0, rng=None):
        self.e = engine
        self.timeout = timeout
        self.rng = rng or random.Random()
        self.latest = {}                    # name -> {"neighbors": [...], "best": {...}}
        self.running = False

    # ---------------------------------------------------------------- asking the radio
    async def _ask(self, frame, match, what):
        """Send a command, then wait for the radio's push that answers it. -> (frame, error text)."""
        fut = asyncio.get_running_loop().create_future()
        entry = (match, fut)
        self.e.waiters.append(entry)
        try:
            try:
                r = await self.e.backend.cmd(frame, expect=F.RESP_SENT)
            except Exception as err:
                return None, f"{what}: {err}"
            if r and r[0] == 1:
                return None, f"{what}: the radio refused it (error {r[1] if len(r) > 1 else '?'})"
            try:
                return await asyncio.wait_for(fut, self.timeout), ""
            except asyncio.TimeoutError:
                return None, f"{what}: no answer"
        finally:
            if entry in self.e.waiters:
                self.e.waiters.remove(entry)

    async def _trace(self, contact, key):
        size = contact.get("hash_size", 1)
        route = contact.get("route") or []
        target = key[:2 * size]
        path = route + [target] + list(reversed(route))
        tag = self.rng.getrandbits(32)
        f, err = await self._ask(F.trace(tag, path, size), lambda x: x["kind"] == "trace" and x["tag"] == tag, "trace")
        if f is None:
            return None, None, err
        snrs = f["snrs"]
        return (snrs[len(route)] if len(snrs) > len(route) else None), f["final_snr"], ""

    async def _neighbors(self, prefix):
        f, err = await self._ask(F.cli_command(prefix, "neighbors", int(self.e.now())),
                                 lambda x: x["kind"] == "contact_msg" and x["txt_type"] == F.TXT_CLI and x["prefix"] == prefix,
                                 "neighbours")
        return (parse_neighbors(f["text"]) if f else None), err

    # ---------------------------------------------------------------- one repeater
    async def poll_one(self, rep):
        name, key, pw = rep["name"], rep["pubkey"].lower(), rep.get("password", "")
        now = self.e.now()
        row = {"ts": now, "name": name, "pubkey": key, "ok": 0}
        notes = []
        contact = self.e.contacts.get(key)
        if contact is None:
            row["note"] = "not in the radio's contacts yet: it has to hear this repeater's advert first"
            self.e.db.add_repeater_status(row)
            self.e.event("warn", f"{name}: {row['note']}")
            return row
        prefix = key[:12]
        f, err = await self._ask(F.login(key, pw), lambda x: x["kind"] in ("login_ok", "login_fail") and x["prefix"] == prefix, "login")
        if f is None or f["kind"] == "login_fail":
            row["note"] = err or "login refused: wrong admin password"
            self.e.db.add_repeater_status(row)
            self.e.event("warn", f"{name}: {row['note']}")
            return row
        f, err = await self._ask(F.status_request(key), lambda x: x["kind"] == "status" and x["prefix"] == prefix, "status")
        if f is None:
            notes.append(err)
        else:
            s = f["stats"]
            row.update({"ok": 1, "bat_mv": s.get("bat_mv"), "uptime_s": s.get("uptime_s"), "noise_floor": s.get("noise_floor"),
                        "last_rssi": s.get("last_rssi"), "n_recv": s.get("n_recv"), "n_sent": s.get("n_sent"),
                        "airtime_s": s.get("airtime_s"), "tx_queue": s.get("tx_queue")})
        there, back, err = await self._trace(contact, key)
        if err:
            notes.append(err)
        row["trace_there"], row["trace_back"] = there, back
        neighbors, err = await self._neighbors(prefix)
        if err:
            notes.append(err)
        info = {"neighbors": [], "best": None}
        own = {r["pubkey"].lower()[:8] for r in self.e.cfg.get("repeaters", [])}
        for n in neighbors or []:
            n["name"] = self.e._name_for_hash(n["id"])
            info["neighbors"].append(n)
            self.e.db.add_neighbor({"ts": now, "repeater": name, "neighbor": n["id"], "neighbor_name": n["name"],
                                    "secs_ago": n["secs_ago"], "snr": n["snr"]})
        others = [n for n in info["neighbors"] if n["id"] not in own]
        info["best"] = max(others, key=lambda n: n["snr"]) if others else None
        self.latest[name] = info
        row["note"] = "; ".join(notes)
        self.e.db.add_repeater_status(row)
        self.e.event("ok" if row["ok"] else "warn", f"{name}: " + ("polled" if row["ok"] else row["note"] or "no data"))
        return row

    async def poll_all(self):
        if self.running:
            return
        self.running = True
        try:
            for rep in list(self.e.cfg.get("repeaters", [])):
                await self.poll_one(rep)
        finally:
            self.running = False

    async def loop(self, first_after=20):
        await self.e.sleep(first_after)
        while True:
            if self.e.cfg.get("repeaters"):
                await self.poll_all()
            await self.e.sleep(max(60, self.e.cfg.get("repeater_poll_minutes", 30) * 60))

    # ---------------------------------------------------------------- for the page
    def table(self):
        rows = []
        configured = {r["name"]: r for r in self.e.cfg.get("repeaters", [])}
        for s in self.e.db.last_repeater_status():
            if s["name"] not in configured:
                continue
            info = self.latest.get(s["name"], {})
            rows.append({**s, "battery_pct": battery_percent(s.get("bat_mv")), "best": info.get("best"),
                         "neighbors": info.get("neighbors", [])})
        seen = {r["name"] for r in rows}
        rows += [{"name": n, "note": "not polled yet"} for n in configured if n not in seen]
        return rows

    def known_repeaters(self):
        """Repeaters the radio has heard (contact type 2): what the page offers to add."""
        return sorted(({"name": c["name"], "pubkey": k} for k, c in self.e.contacts.items() if c.get("type") == 2),
                      key=lambda r: r["name"].lower())
