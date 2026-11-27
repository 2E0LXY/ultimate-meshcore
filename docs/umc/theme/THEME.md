# UMC themes

Two dark themes, switchable at runtime on every surface. Tokens live in `tokens.json` (one source of truth); the reference screenshots are `ref-overview.png` and `ref-analytics.png`.

| Theme | Look | Source |
|---|---|---|
| `overview` (default) | near-black page, navy gradient main area, blue (`#2563eb`) active nav and primary button, indigo/blue/cyan chart series, green/red delta badges | ref-overview.png |
| `analytics` | graphite surfaces, soft-grey card borders, multi-colour series (blue, cyan, green, orange, purple, pink, amber, teal), subtle active-nav fill, light outer page on wide screens | ref-analytics.png |

## Shared design rules (both themes)
- Cards: `card` fill, 1 px `border`, radius `radius` (14/16 px), generous padding (16-20 px). Card header = small icon + title (`ink`, 600) + optional info icon at the right.
- KPI card: muted label, large number (28-32 px, 700), delta badge (pill, `okBg`/`ok` or `badBg`/`bad`, 12 px, arrow glyph).
- Sidebar: `sidebar` fill, section labels in `faint` uppercase 11 px, nav rows 36-40 px, active row = `navActive` fill, `navActiveInk` text, radius 8. Nested items indented with a thin guide line.
- Top bar: title + muted subtitle (overview) or breadcrumb (analytics); range selector and primary action button right-aligned.
- Buttons: primary = `accent`; secondary = `chip` fill with `border`; pills for range toggles (1W/1M...), active pill = `chip`/`navActive`.
- Tables: header row in `faint` uppercase 11 px, row separators `border`, no zebra.
- Progress/track bars: `track` background, `series[n]` fill, 4-6 px, rounded.
- Charts: series colours from `series` in order; grid lines `border`; labels `muted` 11-12 px; no chart-junk.
- Status colours are `ok`/`warn`/`bad` only; never use series colours for status.
- Contrast: all text/background pairs must meet WCAG AA (4.5:1 body, 3:1 large). `muted` on `card` is the tightest pair: check it.
- Motion: respect reduced-motion; no animation longer than 200 ms except the existing live-flow pulses.

## Switching
- Dash and repeater web panel: a theme switch in the header (and Settings) sets `data-theme="overview|analytics"` on `<html>`, stored in `localStorage["umc-theme"]` (try/catch; fall back to default), applied before first paint to avoid a flash. Public viewer follows the same switch.
- Android: Settings > Appearance, stored in app prefs, applied through the Compose theme.
- T-Deck: Settings screen entry and CLI `set theme overview|analytics` (stored in prefs).
