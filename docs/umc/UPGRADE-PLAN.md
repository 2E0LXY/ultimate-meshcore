# Ultimate MeshCore — Upgrade plan (feature gaps and phased delivery)

Audit date: 2026-11-01. Baseline: UMC firmware 0.1.26 (MeshCore base v1.17.1), Android app 0.1.13, Desktop 0.1.26, UMC Net dashboard 2.3.
This plan sits beside [ROADMAP.md](ROADMAP.md) (what is done and the earlier gap list). It re-checks every gap against the newest upstream release,
the official MeshCore apps and the community forks and apps, adds what the apps and the network side lack, and puts it all in delivery order.

**How to read it.** Priority: **P0** security, interoperability or blocks other work · **P1** high value · **P2** worthwhile · **P3** later or idea.
Effort (one focused agent-session of build + test + release): **S** under a day · **M** 2–4 days · **L** 1–2 weeks · **XL** more than 2 weeks.
Source tags: `UP` upstream MeshCore · `APP` official MeshCore app · `FORK` community firmware · `CLI` community apps and tools · `RM` our roadmap · `NEW` identified in this audit.

## 1. What changed upstream since our base

| Release | Date | Relevant content | In UMC? |
|---|---|---|---|
| 1.14 | Feb 2026 | multi-byte path hashes (`path.hash.mode`), GPS auto-sync, token-bucket duty cycle, LNA toggle | ✅ |
| 1.15 | early 2026 | `GROUP_DATA` binary packet type, extended frequency range, rxgain default, duty-cycle CLI, nRF OTA, WiFi companion fixes | ✅ (nRF n/a) |
| 1.17.0 / 1.17.1 | 9 and 14 Aug 2026 | listen-before-talk rewrite, JSON config, MCU temperature in telemetry, `room.post`, long-press power-off, `radio.fem.rxgain/txgain`, KISS roles, multi-interface BLE+WiFi companion (`MultiSerialInterface`) | ✅ base |
| **1.18.0** | **15 Oct 2026** | **Companion CLI** (`TXT_TYPE_CLI_COMMAND` 3, `CMD_RUN_CLI_COMMAND` 66) and **Remote CLI permission** on contacts (flag 0x10); **Node Discover UI** on companions; **telemetry push** (sensor subscribe/unsubscribe lease); `tz.offset`; `wifi.*` and `wifi.pwd` CLI; reboot/poweroff/shutdown CLI; `gps diag`; `power`; **hidden repeater** (no discovery reply when adverts are off); transport-code 0 = unscoped; direct-mode ACK now honours the retransmit delay; system time kept across reboots; `MACThenDecrypt` rejects unaligned blocks (**security**); BLE+WiFi companion on Heltec V3/V4/V4 R8/Wireless Paper/RAK3112/XIAO S3; new boards (ThinkNode M4/M8, Wio Tracker L1 1W, Muzi Base, Waveshare LR1121) | ❌ |
| Official app 1.50.0 | Sep 2026 | Command Line screen, WiFi settings (set credentials over BLE), onboarding, discover list with filters and quick-add, regions discovery (fw 1.16+), hop count under channel messages, faster "delivered", channel ordering, neighbours map, forget position, position from telemetry | partly |

## 2. Gaps by component

### 2.1 Repeater and room firmware

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| R1 | **Merge upstream 1.18.0** (hidden repeater, transport-code 0, ACK retransmit delay, time kept across reboots, aligned-MAC rejection, `gps diag`, `power`, bug fixes, new board targets); re-test every UMC feature after the merge | UP | **P0** | L | 0 |
| R2 | Hardware-test the untested targets: Heltec V4 OLED / TFT / R8, V4 Bluetooth (roadmap 1.1, 3.2) | RM | **P0** | M (needs boards) | 0 |
| R3 | Crash and safety log as a web page, core-dump download, last-reset reason on the dashboard (4.3) | RM, FORK | P1 | M | 3 |
| R4 | Heap monitor with automatic recovery restart (4.7) | RM, FORK | P1 | S | 3 |
| R5 | Rate limiting of mesh logins, requests and forwards (5.9) | RM, FORK | P1 | M | 3 |
| R6 | Fault alerts: `alert.*` to a mesh channel, MQTT topic or webhook (WiFi/MQTT down, battery, OTA) (5.4) | RM, FORK | P1 | M | 3 |
| R7 | SafeBoot low-battery boot guard (4.2) | RM, FORK | P2 | M | 3 |
| R8 | RX duty cycle for solar repeaters (`rx.duty`) (5.2) | RM, FORK | P2 | L (power testing) | 3 |
| R9 | Packet policy rules in the web UI: drop by hops, type, region, rate (5.8) | RM | P2 | L | 3 |
| R10 | Private `$` region keys editor (5.11) | RM, UP | P2 | M | 3 |
| R11 | Repeater discover screen on the OLED/TFT (2.3) | RM, UP | P2 | M | 3 |
| R12 | Upload this repeater to map.meshcore.dev and the community maps from the UI (5.10) | RM, FORK | P2 | M (check their API) | 5 |
| R13 | Home Assistant MQTT discovery for repeater sensors (3.5) | RM, CLI | P2 | M | 5 |
| R14 | Room server firmware with the UMC web UI (1.3) | RM | P2 | L | 5 |
| R15 | Persistent statistics history ring (battery, noise, airtime, packets) for boards without PSRAM (6.2) | RM | P2 | M | 3 |
| R16 | UDP syslog forward window (4.4); SNMP agent (6.5); optional HTTPS on PSRAM boards (6.6) | RM, FORK | P3 | M each | 3 |
| R17 | Adaptive contention window (5.3); store-and-forward mailbox (5.6); scheduled status report (5.5); mesh health monitor (5.7) | RM, FORK | P3 | L each, research first | later |
| R18 | GPS power-save commands (`gps saver/hold/interval`) | FORK | P3 | S | later |
| R19 | MQTT broker presets for UK networks once endpoints are confirmed (6.4); LetsMesh/MeshMapper observer presets | RM, CLI | P2 | S | 5 |
| R20 | Config migration test (UMC binary prefs to and from upstream JSON config) with a tested downgrade path | UP | P1 | M | 0 |

### 2.2 Client firmware (Heltec client and T-Deck)

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| C1 | **Companion CLI** (`CMD_RUN_CLI_COMMAND`, `TXT_TYPE_CLI_COMMAND`, `handleCommand` registry, `tz.offset`, `wifi.*`, reboot/poweroff) so the official app's Command Line screen and other clients work | UP | **P0** | L | 1 |
| C2 | **Remote CLI permission** on contacts (flag 0x10, off by default), refused-inbound logging; a very sensitive permission, so default off, warn on enable, audit entry | UP | **P0** | M | 1 |
| C3 | Node Discover UI on the T-Deck and a discover list in the web messenger (path-hash-size filter, hide already-added, quick-add, regions from non-contacts) | UP, APP | P1 | M | 1 |
| C4 | Telemetry push client side (subscribe to a sensor node, lease renewal, reconnect) | UP | P2 | M | 1 |
| C5 | Delete messages on the device; per-channel message priority; default channel for Quick Send | FORK | P1 | M | 1 |
| C6 | T-Deck Sensors screen; T-Deck lock screen; on-screen notes | FORK | P2 | M | 4 |
| C7 | Repeater mode inside the client (opt-in relaying with skip-advert, max-hops, yield, min-SNR filters and a separate radio profile) | FORK | P3 | L | later |
| C8 | Clients on UMC Net (message bridge over the broker) — needs an identity and loop design first | NEW | P3 | XL | 5 |
| C9 | More client targets: T-Deck Pro, T5S3 e-paper, Wireless Paper; boards whose WiFi web UI fits ESP32 only (nRF boards are out of scope) | FORK | P3 | L each | later |
| C10 | WebSocket 8765 on the client (1.2) | RM | P2 | S | 1 |

### 2.3 Android app (0.1.13)

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| A1 | **Command Line screen**: local companion CLI and per-contact Remote CLI, with secret redaction (WiFi password, BLE PIN) | APP, CLI | **P0** | M (after C1) | 1 |
| A2 | **WiFi settings**: set the companion's WiFi over Bluetooth | APP | P1 | S (after C1) | 1 |
| A3 | Discover list with filters, quick-add and "regions from non-contacts" | APP | P1 | M | 1 |
| A4 | **Neighbours map** and telemetry history (graphs and map) for repeaters | APP, CLI | P1 | M | 1 |
| A5 | Backup and restore of contacts, channels, drafts and the discover list; contact export/import | CLI | P1 | M | 1 |
| A6 | Message features: hop count under channel messages, faster "delivered", channel ordering, "new messages" divider, quoted replies, delete, nicknames (contacts and channels), forget position, position from telemetry | APP, CLI | P1 | L | 4 |
| A7 | **Offline maps** (tile cache) | CLI | P1 | M | 4 |
| A8 | Link previews (optional, off by default for privacy) and images/GIFs the way other MeshCore clients show them | CLI | P3 | M | later |
| A9 | Onboarding for first run; localisation (translations); accessibility (TalkBack, contrast, font scale); tablet and foldable layout | APP | P2 | L | 4 |
| A10 | Background reliability: foreground service for Bluetooth, reconnect after reboot, battery-optimisation guidance (verify current behaviour first) | CLI | P1 | M | 1 |
| A11 | UMC device screen aligned with the new dashboard design; UMC Net view (network map, alerts) inside the app | NEW | P2 | L | 4 |
| A12 | Distribution: signed release build, Play Store and F-Droid listings, in-app update check | NEW | P2 | M | 4 |
| A13 | Contact groups/folders; QR scan through the system camera (`meshcore://` links) | CLI | P2 | M | 4 |
| A14 | Push alerts from UMC Net (ntfy or FCM) | NEW | P2 | M | 4 |
| A15 | Telemetry push subscriptions UI | UP | P3 | M | later |
| A16 | Widgets, share target, notification reply actions, Wear OS | NEW | P3 | L | later |

### 2.4 iOS and other platforms

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| I1 | **No iOS app.** Options: (a) installable web app over WebSocket 8765 to a UMC device on WiFi (iOS Safari has no Web Bluetooth); (b) a native iOS app (large; needs a Mac and an Apple developer account); (c) rely on the official app for BLE. Recommendation: (a) first, decide (b) later | NEW | P2 | (a) M, (b) XL | 4 |
| I2 | Web messenger as a PWA with web push (as the community PWA companion does) | CLI | P2 | M | 4 |

### 2.5 Desktop app (Windows and Linux)

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| D1 | Companion CLI console and per-contact Remote CLI (same as A1) | APP | P0 | S (after C1) | 1 |
| D2 | **macOS build** | NEW | P2 | L | 4 |
| D3 | Signed Windows installer, tray icon, notifications, auto-update, Linux AppImage/deb (verify what exists first) | NEW | P2 | L | 4 |
| D4 | Desktop Chat page dashboard (`omit.html`) still has the old look | RM | P2 | M | 4 |
| D5 | Feature parity with Android: offline maps, backup/restore, discover list, neighbours map | NEW | P2 | M | 4 |

### 2.6 Web interface (repeater and client)

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| W1 | Web Bluetooth / Web Serial "UMC Config" page that needs no WiFi (3.3) | RM | P2 | L | 4 |
| W2 | Translations and accessibility audit | APP | P3 | L | later |
| W3 | Persisted stats history (R15) shown in the web dashboard instead of browser-only history | NEW | P2 | M | 3 |

### 2.7 UMC Net server and dashboard

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| S1 | **Fleet management**: groups, templates (for example the Yorkshire region set), apply to many repeaters with a dry run, a per-repeater result table, a rollback, and scheduled commands. Triggered by "run these four commands on every repeater" | NEW | **P0** | L | 2 |
| S2 | **Server hardening**: key-only SSH, no root password login, fail2ban, firewall rules, backup and restore of server state, rotating the credentials that were shared in chat | NEW | **P0** | M | 0 |
| S3 | ✅ *done in 0.1.27* **Zero-touch enrolment**: a new repeater proves its identity with a signed handshake, appears for approval, and is given its account and control key encrypted to it, so no code or pasting is needed | NEW | P1 | L | 2 |
| S4 | **Staged firmware rollout**: canary repeater, health check, then the rest, with automatic rollback if a repeater does not come back | NEW | P1 | L | 2 |
| S5 | Roles (viewer, operator, admin), two-factor sign-in, API tokens, audit export | NEW | P1 | L | 2 |
| S6 | Alert rules per metric, quiet hours, escalation; email, Telegram, Discord and ntfy templates | NEW | P2 | M | 2 |
| S7 | Metrics for Prometheus/Grafana and Home Assistant | NEW | P2 | M | 5 |
| S8 | Packet archive with search, export and an analyzer view | CLI | P2 | L | 5 |
| S9 | Multi-network (several areas or sites) views and per-site policy | NEW | P2 | L | 5 |
| S10 | Mobile layout and installable dashboard with push | NEW | P2 | M | 4 |

### 2.8 Ecosystem and integrations

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| E1 | **Interoperability test suite**: `meshcore-cli`, `meshcore.js`, `meshcore_py` and the official app against the TCP 5000 interface in CI | NEW | **P0** | L | 0 |
| E2 | BitChat `#mesh` bridge (3.4) | RM | P3 | L | later |
| E3 | Community map and observer uploaders (R12, R19) | RM | P2 | M | 5 |

### 2.9 Quality, security and release process

| ID | Gap | Source | Pri | Effort | Phase |
|---|---|---|---|---|---|
| Q1 | **Hardware release gate**: a written checklist run on real V3, V3.2, V4, T-Deck and client boards before a build is marked stable; dev / release-candidate / stable channels | FORK | **P0** | M | 0 |
| Q2 | Browser UI tests (Playwright) and server end-to-end tests in CI, not only on a developer machine | NEW | P1 | M | 0 |
| Q3 | Fuzz tests for the packet parser, join-code parser, control-command parser and CLI buffers; static analysis (clang-tidy, cppcheck) in CI | NEW | P1 | M | 0 |
| Q4 | **OTA image signature verification** and secrets at rest (encrypted NVS); a short threat model | NEW | P1 | L | 3 |
| Q5 | Upgrade and downgrade matrix tests (config migration, region tree, UMC Net settings) | NEW | P1 | M | 0 |
| Q6 | Release automation (notes, version bump, SBOM, checksums); per-board guides and troubleshooting docs | NEW | P2 | M | 0 and ongoing |
| Q7 | Optional, opt-in crash reporting | NEW | P3 | M | later |

### 2.10 Hardware targets

New upstream boards in 1.18 (ThinkNode M4/M8, Wio Tracker L1 1W, Muzi Base, Waveshare ESP32-S3 LR1121, T-Beam 1W thermal fan control, Station G3 FEM gain) are added **on demand** after R1, each needing a board in hand to test. nRF52 and RP2040 boards are out of scope: the UMC web interface needs WiFi and an ESP32.

## 3. Delivery phases

| Phase | Release | Theme | Contents | Exit criteria |
|---|---|---|---|---|
| **0 Foundations** | 0.1.27 to 0.1.30 | Safety first | R1 upstream 1.18.0 merge, R2 V4 hardware tests, R20/Q5 migration tests, S2 server hardening, E1 interop suite, Q1 hardware gate, Q2/Q3 CI tests and fuzzing | merge builds for every board; all CI suites green; V3, V4, T-Deck pass the hardware checklist; the server has key-only SSH |
| **1 Parity** | **0.2.0** | Match the official apps | C1/C2 companion CLI and Remote CLI, C3 discover, C4 telemetry push, C5 delete and priority, C10 WebSocket; Android A1–A5, A10; Desktop D1 | the official app's Command Line screen works against a UMC client; Android and Desktop show the same discover list, neighbours map and CLI |
| **2 Fleet** | **0.3.0** | Run many repeaters | S1 fleet management, S3 zero-touch enrolment, S4 staged rollout, S5 roles and two-factor, S6 alert rules | a region template applied to all repeaters with per-repeater results; a bad firmware rolls back by itself; a new repeater joins with no pasting |
| **3 Reliability** | **0.4.0** | Stay up, stay safe | R3–R11, R15–R16, W3, Q4 signed OTA | crash log and alerts work; solar repeater runs with RX duty cycle; OTA refuses unsigned images |
| **4 Apps everywhere** | **0.5.0** | Polish and reach | Android A6–A9, A11–A14; I1/I2 iOS-ready web app and push; Desktop D2–D5; W1; S10; C6 | Play Store and F-Droid builds; macOS build; translations in two languages; accessibility pass |
| **5 Ecosystem** | **0.6.0** | Connect outward | R12–R14, R19, S7–S9, E3, C8 | Home Assistant and Prometheus work; map upload works; clients can join UMC Net |
| **1.0** | 1.0.0 | Stable | all P0 and P1 done; two releases with no regression found by the hardware gate | — |

Later (no phase): R17, R18, C7, C9, A8, A15, A16, W2, E2, Q7.

## 4. Counts

Counted from the tables above (a few rows group several related items).

| Area | P0 | P1 | P2 | P3 | Total |
|---|---|---|---|---|---|
| Repeater/room firmware | 2 | 5 | 10 | 3 | 20 |
| Client firmware | 2 | 2 | 3 | 3 | 10 |
| Android | 1 | 7 | 5 | 3 | 16 |
| iOS and web app | 0 | 0 | 2 | 0 | 2 |
| Desktop | 1 | 0 | 4 | 0 | 5 |
| Web interface | 0 | 0 | 2 | 1 | 3 |
| Server | 2 | 3 | 5 | 0 | 10 |
| Ecosystem | 1 | 0 | 1 | 1 | 3 |
| Quality and security | 1 | 4 | 1 | 1 | 7 |
| **All** | **10** | **21** | **33** | **12** | **76** |

## 5. Risks and working rules

- **Parallel work.** The repository is being changed by more than one session (0.1.23 to 0.1.26 landed while this audit was written). Work on feature branches, require green CI to merge, and keep one owner per area to avoid conflicting edits.
- **The 1.18.0 merge is the riskiest step** (UMC touches the repeater, client, prefs and web server). Do it on a branch with the Phase 0 tests in place first, and keep a rollback image.
- **Remote CLI on clients** lets a contact reboot or reconfigure a radio. It must stay **off by default**, per contact, with a warning and an audit entry.
- **Anything that changes how repeaters join, update or are controlled** (S3, S4, Q4) needs a staged rollout across your own repeaters first.
- **Hardware availability limits what can be verified.** Items marked "needs boards" are not done until tested on a real board.

## 6. Decisions needed

1. **iOS**: web app first (I1a), native app later, or native now? Native needs a Mac and an Apple developer account.
2. **Distribution**: Play Store and F-Droid listings (needs a developer account and signing key) or keep side-loaded APKs?
3. **Which boards do you own** and can test on (V3, V3.2, V4 OLED/TFT/R8, T-Deck, the V5 shown on the dashboard)? This decides which hardware targets enter Phase 0.
4. **Fleet scope**: manage only your own repeaters, or also other people's (affects roles and approval)?
5. **Server hosting**: stay on the single VPS or also offer a Docker image for other operators?

## 7. Sources

MeshCore v1.18.0 release notes (blog.meshcore.io, 15 Oct 2026) · MeshCore release index and companion CLI guide (nodakmesh.org) · MeshCore App Store version history (1.50.0) · v1.14, v1.15, v1.17 notes (nodakmesh.org) ·
Offband firmware and client, MeshCore Low Power firmware, SlunseCore, MeshCore-Solo, Meck (T-Deck Pro / T5S3), MeshCore Open, MeshCore One, MeshCore TEAM, edleeman17/meshcore-companion, Colorado-Mesh mesh-client, MeshMonitor, DeskOS (GitHub release pages).
