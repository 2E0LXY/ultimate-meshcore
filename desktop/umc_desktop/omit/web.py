"""The chat page and its small JSON interface, added to the Desktop app's web server."""
import json
from pathlib import Path

from aiohttp import web

STATIC = Path(__file__).resolve().parent.parent / "static"          # the Desktop app's static folder
GUARD = "X-UMC"          # a custom header: another website cannot add it to a request without our permission


def setup(app, state):
    """state.omit is the Runtime; it is None until the Desktop app has made one."""

    def js(data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    def engine():
        rt = getattr(state, "omit", None)
        return rt.engine if rt is not None else None

    async def need_engine(request):
        if engine() is None:
            raise web.HTTPServiceUnavailable(text=json.dumps({"error": "connect a companion radio first"}),
                                             content_type="application/json")

    async def body(request):
        if request.headers.get(GUARD) != "1":
            raise web.HTTPForbidden(text=json.dumps({"error": "missing header"}), content_type="application/json")
        try:
            return await request.json()
        except Exception:
            raise web.HTTPBadRequest(text=json.dumps({"error": "bad JSON"}), content_type="application/json")

    async def page(request):
        return web.FileResponse(STATIC / "omit.html", headers={"Cache-Control": "no-store"})

    async def api_state(request):
        e = engine()
        if e is None:
            return js({"connected": False})
        return js({"connected": True, **e.state()})

    async def api_feed(request):
        await need_engine(request)
        e = engine()
        since = int(request.query.get("since", "0") or 0)
        rows = [{k: v for k, v in r.items() if k != "path_names"} for r in e.feed(since)]
        return js({"rows": rows, "seq": e._seq, "nicks": e.nicks(), "events": list(e.events)[-30:],
                   "state": e.state()})

    async def api_mode(request):
        await need_engine(request)
        d = await body(request)
        e = engine()
        if "mode" in d:
            try:
                e.set_mode(d["mode"])
            except ValueError as err:
                return js({"error": str(err)}, 400)
        if "paused" in d:
            e.bot.paused = bool(d["paused"])
            e.event("info", "paused" if e.bot.paused else "resumed")
        return js(e.state())

    async def api_send(request):
        await need_engine(request)
        d = await body(request)
        text = str(d.get("text", "")).strip()
        if not text:
            return js({"error": "nothing to send"}, 400)
        if len(text) > 160:
            return js({"error": "a message is at most 160 characters"}, 400)
        ok = await engine().send_channel(int(d.get("channel", 0)), text)
        return js({"ok": ok}) if ok else js({"error": "the radio did not take it"}, 502)

    async def api_beacon(request):
        await need_engine(request)
        await body(request)
        await engine().send_beacon()
        return js({"ok": True})

    async def api_dashboard(request):
        await need_engine(request)
        e, hours = engine(), min(168, max(1, int(request.query.get("hours", "24") or 24)))
        now, db = e.now(), e.db
        return js({"hours": hours, "stats": db.stats(now, hours), "hourly": db.hourly(now, hours),
                   "top": db.top_senders(now, hours), "hops": db.hops_histogram(now, hours),
                   "relays": db.relay_counts(now, hours), "beacons": db.beacon_summary(now, hours),
                   "repeaters": db.last_repeater_status(), "replies": db.recent_replies(10)})

    async def api_repeaters(request):
        await need_engine(request)
        m = engine().monitor
        return js({"table": m.table(), "known": m.known_repeaters(), "polling": m.running})

    async def api_repeaters_poll(request):
        await need_engine(request)
        await body(request)
        import asyncio
        asyncio.ensure_future(engine().monitor.poll_all())
        return js({"ok": True})

    async def api_settings_get(request):
        rt = getattr(state, "omit", None)
        return js(rt.settings())

    async def api_settings_post(request):
        d = await body(request)
        problems = state.omit.save_settings(d.get("config"), d.get("texts"))
        return js({"error": "; ".join(problems), "problems": problems}, 400) if problems else js({"ok": True})

    app.router.add_get("/omit", page)
    app.router.add_get("/omit/api/state", api_state)
    app.router.add_get("/omit/api/feed", api_feed)
    app.router.add_post("/omit/api/mode", api_mode)
    app.router.add_post("/omit/api/send", api_send)
    app.router.add_post("/omit/api/beacon", api_beacon)
    app.router.add_get("/omit/api/dashboard", api_dashboard)
    app.router.add_get("/omit/api/repeaters", api_repeaters)
    app.router.add_post("/omit/api/repeaters/poll", api_repeaters_poll)
    app.router.add_get("/omit/api/settings", api_settings_get)
    app.router.add_post("/omit/api/settings", api_settings_post)
