"""Keeps the UMC themes in step: docs/umc/theme/tokens.json is the source of truth.

Checks the repeater web panel (web/umc/index.html) and the on-device palette header
(src/helpers/ui/UmcTheme.h) against it, and that the page has no stray colour literals
outside the two theme blocks. Run: python3 scripts/test_umc_theme.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ["page", "surface", "surface2", "sidebar", "card", "border", "chip", "track", "ink", "muted", "faint",
        "accent", "accentInk", "navActive", "navActiveInk", "ok", "okBg", "warn", "warnBg", "bad", "badBg"]
tokens = json.load(open(os.path.join(ROOT, "docs/umc/theme/tokens.json")))["themes"]
html = open(os.path.join(ROOT, "web/umc/index.html"), encoding="utf-8").read()
hdr = open(os.path.join(ROOT, "src/helpers/ui/UmcTheme.h"), encoding="utf-8").read()
errors = []


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


for name, t in tokens.items():
    m = re.search(r"html\[data-theme=%s\]\{([^}]*)\}" % name, html)
    if not m:
        errors.append("web: no block for " + name)
        continue
    got = dict(re.findall(r"--(\w+):([^;]+)", m.group(1)))
    want = {k: t[k] for k in KEYS}
    want.update({"s%d" % i: c for i, c in enumerate(t["series"])})
    want.update({"radius": "%dpx" % t["radius"], "radiusSm": "%dpx" % t["radiusSm"]})
    for k, v in want.items():
        if got.get(k) != v:
            errors.append("web %s --%s: %r != %r" % (name, k, got.get(k), v))
    extra = set(got) - set(want)
    if extra:
        errors.append("web %s has extra vars %s" % (name, sorted(extra)))
    m = re.search(r'\{"%s", ([^}]*), \{([^}]*)\}, (\d+)\}' % name, hdr)
    if not m:
        errors.append("header: no row for " + name)
        continue
    vals = [x.strip() for x in m.group(1).split(",")]
    for k, v in zip(KEYS, vals):
        if int(v, 16) != int(t[k][1:], 16):
            errors.append("header %s %s: %s != %s" % (name, k, v, t[k]))
    ser = [int(x, 16) for x in m.group(2).split(",")]
    if ser[:len(t["series"])] != [int(c[1:], 16) for c in t["series"]] or int(m.group(3)) != len(t["series"]):
        errors.append("header %s series mismatch" % name)
    # WCAG AA on the pairs the UI actually draws
    for fg, bg, need in (("ink", "card", 4.5), ("muted", "card", 4.5), ("muted", "surface", 4.5),
                         ("accentInk", "accent", 4.5), ("navActiveInk", "navActive", 4.5),
                         ("ok", "okBg", 4.5), ("warn", "warnBg", 4.5), ("bad", "badBg", 4.5)):
        c = contrast(t[fg], t[bg])
        if c < need:
            errors.append("contrast %s %s on %s = %.2f < %s" % (name, fg, bg, c, need))

# No colour literals in the page outside the two theme blocks (shadows are black with alpha).
body = re.sub(r"html\[data-theme=\w+\]\{[^}]*\}", "", html)
stray = sorted(set(x for x in re.findall(r"#[0-9a-fA-F]{3,8}\b", body) if len(x) in (4, 7, 9) and x not in ("#000", "#fff")))
stray = [x for x in stray if not re.fullmatch(r"#0{3,5}[0-9a-f]", x)]   # #0003..#000a shadows
if stray:
    errors.append("stray colour literals in index.html: %s" % stray)
if 'localStorage.getItem("umc-theme")' not in html or 'data-theme="overview"' not in html:
    errors.append("page does not apply umc-theme before first paint")

for e in errors:
    print("FAIL", e)
print("umc theme: %s" % ("FAILED" if errors else "ok"))
sys.exit(1 if errors else 0)
