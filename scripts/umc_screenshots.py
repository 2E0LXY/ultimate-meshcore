#!/usr/bin/env python3
"""Regenerate the README screenshots of the web interface from the built-in demo mode.

    python -m http.server 8099 --directory web/umc      # in one terminal
    python scripts/umc_screenshots.py                  # writes docs/images/*.png

Needs: pip install playwright && python -m playwright install chromium
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("UMC_UI", "http://localhost:8099/index.html")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "images")


def open_ui(browser, mode, width=1280, height=820):
    page = browser.new_page(viewport={"width": width, "height": height}, color_scheme="dark")
    page.add_init_script("sessionStorage.setItem('umc_token', 'demo')")
    page.goto(f"{BASE}?mock={mode}")
    page.wait_for_timeout(2500)
    if page.is_visible("#login"):
        page.fill("#pw", "demo-password")
        page.click("#loginBtn")
        page.wait_for_timeout(2500)
    return page


def shot(page, name, js=None, wait=2500, full=False):
    if js:
        page.evaluate(js)
    page.wait_for_timeout(wait)
    path = os.path.join(OUT, name)
    page.screenshot(path=path, full_page=full)
    print("wrote", path)


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---- repeater
        page = open_ui(browser, "1")
        shot(page, "repeater-dashboard.png", "go('dash')")
        shot(page, "repeater-radio.png", "go('radio')")
        shot(page, "repeater-mesh.png", "go('mesh')")
        shot(page, "repeater-regions.png", "go('regions')")
        shot(page, "repeater-network.png", "go('net')")
        shot(page, "repeater-routes.png", "go('routes')")
        shot(page, "repeater-traffic.png", "go('traffic')")
        shot(page, "repeater-map.png", "go('map')", wait=6000)
        shot(page, "firmware-update.png", "go('fw')")
        page.close()

        # ---- first-time setup
        page = open_ui(browser, "setup")
        shot(page, "setup-wizard.png", "document.querySelector('#wNext') && document.querySelector('#wNext').click()")
        page.close()

        # ---- Ultimate MeshCore Client
        page = open_ui(browser, "client")
        page.wait_for_timeout(3000)
        shot(page, "client-dashboard.png", "go('dash')")
        shot(page, "client-messages.png", "MC.activeConv = 'ch:1'; go('chat')")
        shot(page, "client-dm.png", "MC.activeConv = [...MC.contacts.values()].find(c => c.name === 'Alice') ? 'c:' + [...MC.contacts.values()].find(c => c.name === 'Alice').prefix : 'ch:1'; go('chat')")
        page.evaluate("""(async () => {
            await go('contacts');
            const c = [...MC.contacts.values()].find(x => x.name === 'Leeds Central RPT');
            document.querySelector(`[data-open="${c.key}"]`).click();
            await new Promise(r => setTimeout(r, 400));
            document.querySelector('[data-d="status"]').click();
        })()""")
        page.set_viewport_size({"width": 1280, "height": 1300})
        shot(page, "client-contacts.png", wait=4000)
        page.set_viewport_size({"width": 1280, "height": 820})
        shot(page, "client-channels.png", "go('channels')")
        page.evaluate("""(async () => {
            await go('clroutes');
            document.querySelector('#rtPath').value = 'a1,b2,a1';
            document.querySelector('#rtTrace').click();
        })()""")
        shot(page, "client-routes.png", wait=4000)
        shot(page, "client-region.png", "go('clregion')")
        shot(page, "client-map.png", "go('map')", wait=6000)
        shot(page, "client-apps.png", "go('apps')")
        shot(page, "client-messaging-settings.png", "go('msgset')")
        page.close()

        # ---- phone-sized browser
        page = open_ui(browser, "client", 390, 844)
        page.wait_for_timeout(3000)
        shot(page, "client-mobile.png", "MC.activeConv = 'ch:1'; go('chat')")
        page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
