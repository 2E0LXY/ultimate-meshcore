#!/usr/bin/env python3
"""Screenshots of the repeater and client web pages (their built-in demo data, ?mock) and of the web flasher, for the README
and the manual.   python3 shots_web.py <output folder>"""
import os, subprocess, sys, time
from playwright.sync_api import sync_playwright
OUT = sys.argv[1] if len(sys.argv) > 1 else "."
HERE = os.path.dirname(os.path.abspath(__file__))
srv = subprocess.Popen([sys.executable, "-m", "http.server", "18779", "--directory", HERE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(1)
try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        def page(variant, sec, w=1440, h=1000):
            pg = b.new_page(viewport={"width": w, "height": h}); pg.add_init_script("sessionStorage.setItem('umc_token','x')")
            pg.goto("http://127.0.0.1:18779/index.html?%s#%s" % (variant, sec)); pg.wait_for_timeout(3500); return pg
        def save(pg, name, **kw): pg.screenshot(path=os.path.join(OUT, name), **kw); print("saved", name)
        pg = page("mock", "dash"); save(pg, "repeater-dashboard.png"); pg.close()
        pg = page("mock=client", "dash"); save(pg, "client-dashboard.png"); pg.close()
        pg = page("mock", "mqtt"); save(pg, "repeater-umcnet-join.png", clip={"x": 0, "y": 0, "width": 1440, "height": 760})
        q = pg.locator('.q[data-hv="mqtt.tx"]')
        if q.count():                                       # the help for one setting, with "How it works"
            q.first.scroll_into_view_if_needed(); q.first.click(); pg.wait_for_timeout(700)
            card = pg.locator("text=How it works").first.locator("xpath=ancestor::*[contains(@class,'card') or contains(@class,'grp') or self::section or self::fieldset][1]")
            (card if card.count() else pg.locator("text=How it works").first.locator("xpath=../..")).screenshot(path=os.path.join(OUT, "repeater-help.png")); print("saved repeater-help.png")
        pg.close()
        pg = page("mock", "net"); save(pg, "repeater-network.png"); pg.close()
        pg = b.new_page(viewport={"width": 1280, "height": 900}); pg.goto("https://2e0lxy.github.io/ultimate-meshcore/"); pg.wait_for_timeout(4000); save(pg, "web-flasher.png"); pg.close()
        b.close()
finally:
    srv.terminate()
