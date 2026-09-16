// Development-only fake device so the UI can be exercised from a plain file/browser.
// Enabled when the page is opened with ?mock (never embedded in firmware).
(function () {
  if (!/[?&]mock\b/.test(location.search)) return;
  const setup = /[?&]mock=setup\b/.test(location.search);
  const client = /[?&]mock=client\b/.test(location.search);   // Ultimate MeshCore Client with a simulated radio
  const state = {
    name: "Demo Repeater", radio: "869.6179809,62.5,8,8", tx: "22", dutycycle: "50.0%", "radio.rxgain": "on", "agc.reset.interval": "0",
    cad: "off", "int.thresh": "0", repeat: "on", "loop.detect": "minimal", "path.hash.mode": "0", "flood.max": "64", "flood.max.unscoped": "64",
    "flood.max.advert": "8", "multi.acks": "1", txdelay: "0.5", "direct.txdelay": "0.3", rxdelay: "0.0", "advert.interval": "120",
    "flood.advert.interval": "47", lat: "53.800", lon: "-1.550", "owner.info": "Demo owner", "public.key": "0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF",
    role: "repeater", "guest.password": "", "mqtt.iata": "UNSET", "mqtt.packets": "on", "mqtt.raw": "off", "mqtt.tx": "off", "mqtt.meshmapper": "off",
    "wifi.ssid": "-", "wifi.ssid2": "-", "wifi.ssid3": "-", "wifi.powersaving": "none", "net.ip": "dhcp", "net.hostname": "umc-demo-repeater", "net.mdns": "on",
    "ap.mode": "auto", "ap.rescue": "60", pin: "48213377", "http.timeout": "30", telnet: "off", "ntp.server1": "uk.pool.ntp.org", "ntp.server2": "time.cloudflare.com",
    "ntp.server3": "time.google.com", timezone: "GMT0BST,M3.5.0/1,M10.5.0", "bridge.type": "espnow", "bridge.enabled": "off", "bridge.source": "logTx", "bridge.delay": "500",
    "bridge.channel": "1", "bridge.secret": "LVSITKE", "adc.multiplier": "0.000",
  };
  let setupDone = !setup;
  if (client) {
    Object.assign(state, {name: "Demo Client", scope: "-", "contacts.manual": "off", "autoadd.chat": "on", "autoadd.repeater": "on", "autoadd.room": "on",
      "autoadd.sensor": "off", "autoadd.overwrite": "on", "autoadd.maxhops": "0", "telemetry.base": "contacts", "telemetry.loc": "deny", "telemetry.env": "deny",
      "advert.loc": "share", ble: "on", "ble.pin": "0", "ble.activepin": "482913", "app.tcp": "on", af: "1.0", repeat: "off", "path.hash.mode": "0",
      "contacts.count": JSON.stringify({contacts: 5, max_contacts: 350, channels: 2, max_channels: 40, queued: 0}),
      "app.links": JSON.stringify({ble: {present: true, on: true, connected: true}, tcp: {on: true, port: 5000, clients: 1}, web: true, queued: 0}),
      "update.status": "up-to-date running:0.1.0 build:43dc510", "update.auto": "check", "update.interval": "24", "update.url": "https://2e0lxy.github.io/ultimate-meshcore/"});
  }
  const info = () => ({fw: "UMC", umc: "0.1.0", api: 1, name: state.name, role: client ? "companion" : "repeater", ver: "v1.17.1", build: "14 Sep 2026", board: "Heltec V3",
    env: client ? "umc_heltec_v3_client" : "umc_heltec_v3_repeater", commit: "43dc510", reset: "power-on", heap: {free: 38996, max_block: 29684, min_free: 21504},
    setup: !setupDone, default_pw: false,
    features: client ? ["wifi", "ota", "telnet", "display", "ble", "webapp"] : ["wifi", "ota", "telnet", "mqtt", "espnow", "bridge", "display", "webstats"],
    net: {sta: {connected: !setup, ssid: "HomeNet", ip: "192.168.1.77", gw: "192.168.1.1", rssi: -58, ch: 6, mac: "AA:BB:CC:DD:EE:FF"},
      ap: {active: setup, ssid: "UMC-Setup-D9C4", ip: "192.168.4.1", clients: 1, mode: "auto"}, hostname: state["net.hostname"], mdns: true, networks: 1, setup, time_sync: true, wifi: true},
    auth_required: !setup && !sessionStorage.getItem("umc_token")});
  const cmd = c => {
    if (c === "ver") return "v1.17.1 (Build: 14-Aug-2026)";
    if (c === "board") return "Heltec V3";
    if (c === "clock") return new Date().toISOString().slice(11, 16) + " - " + new Date().toLocaleDateString("en-GB") + " UTC";
    if (c === "stats-core") return JSON.stringify({battery_mv: 4052, uptime_secs: 93712, errors: 0, queue_len: 0});
    if (c === "stats-radio") return JSON.stringify({noise_floor: -103, last_rssi: -97, last_snr: 6.25, tx_air_secs: 48, rx_air_secs: 311});
    if (c === "stats-packets") return JSON.stringify({recv: 1204, sent: 377, flood_tx: 201, direct_tx: 176, flood_rx: 950, direct_rx: 254, recv_errors: 3});
    if (c === "memory") return JSON.stringify({heap_free: 128400, heap_min: 98112, heap_max: 65524, psram_free: 0, psram_min: 0, psram_max: 0});
    if (c === "neighbors") return "A1B2C3D4:340:50\n9F00AB12:5400:-18";
    if (c === "region") return "* F\n Yorkshire^ F\n Sheffield F\n Wakefield F\n uk F\n  yorkshire F\n  northwest F";
    if (c === "get wifi.status") return "> ssid:HomeNet status:connected code:3 state:connected ip:192.168.1.77 channel:6 rssi:-58 quality:84% signal:excellent gw:ok wd:0";
    if (c === "get ap.status") return "> down mode:auto";
    if (c === "get net.status") return "> " + JSON.stringify(info().net);
    if (c === "get mqtt.status") return "> wifi:up ntp:ok iata:UNSET p:- s:-";
    if (c === "get mqtt.statuscfg") return "> on";
    if (c === "get mqtt.client_version") return "> umc-0.1.0";
    if (c === "powersaving") return "off";
    if (c === "get web.stats.status") return "> enabled:on history:active";
    if (c === "get umc.version") return "> Ultimate MeshCore 0.1.0";
    if (/^trace /.test(c)) { window.__trace = Date.now(); return "OK - trace sent via 3 hop(s); then: get trace"; }
    if (c === "get trace") return !window.__trace ? "> idle" : Date.now() - window.__trace < 2500 ? "> waiting 1s path:27,da,27" : "> done 2.3s path:27,da,27 snr:9.5,4.2,8.8 final:11.0";
    if (/^route /.test(c)) return "OK";
    if (c === "setup done") { setupDone = true; return "OK - setup complete"; }
    if (/^get wifi\.pwd/.test(c)) return "> -";
    let m = c.match(/^get (\S+)$/); if (m) return m[1] in state ? "> " + state[m[1]] : "??: " + m[1];
    m = c.match(/^set (\S+) ?(.*)$/); if (m) { state[m[1]] = m[2]; return "OK"; }
    if (/^password /.test(c)) return "password now: ********";
    if (/^time /.test(c)) return "OK - clock set";
    return "OK";
  };
  // ---- simulated companion radio for ?mock=client (MeshCore companion protocol frames) ----
  const radio = (() => {
    const frames = []; let seq = 0;
    const push = f => frames.push({seq: ++seq, hex: [...f].map(b => b.toString(16).padStart(2, "0")).join("")});
    const le32 = n => [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255];
    const i32 = n => le32(n >>> 0);
    const str = (s, n) => { const b = [...new TextEncoder().encode(s)].slice(0, n - 1); while (b.length < n) b.push(0); return b; };
    const key = h => Array.from({length: 32}, (_, i) => parseInt(h[i % h.length] + h[(i + 1) % h.length], 16) & 255);
    const now = () => Math.floor(Date.now() / 1000);
    const contacts = [
      {k: "a1", name: "Ilkley Moor RPT", type: 2, hops: 0, path: [], lat: 53.915, lon: -1.822, age: 240},
      {k: "b2", name: "Leeds Central RPT", type: 2, hops: 1, path: [0xa1], lat: 53.799, lon: -1.549, age: 900},
      {k: "c3", name: "Otley Chat Room", type: 3, hops: 1, path: [0xa1], lat: 53.905, lon: -1.692, age: 3600},
      {k: "d4", name: "Alice", type: 1, hops: 2, path: [0xa1, 0xb2], lat: 53.84, lon: -1.62, age: 60},
      {k: "e5", name: "Bob", type: 1, hops: -1, path: [], lat: 53.76, lon: -1.50, age: 7200},
    ];
    const channels = [{name: "Public", secret: Array(16).fill(0x8b)}, {name: "#Yorkshire", secret: Array(16).fill(0x5b)}];
    const contactFrame = (code, c) => {
      const f = [code, ...key(c.k + "7f3e"), c.type, 0, c.hops < 0 ? 0xFF : c.hops];
      const p = c.path.slice(); while (p.length < 64) p.push(0);
      return [...f, ...p, ...str(c.name, 32), ...le32(now() - c.age), ...i32(Math.round(c.lat * 1e6)), ...i32(Math.round(c.lon * 1e6)), ...le32(now())];
    };
    const byPrefix = b => contacts.find(c => key(c.k + "7f3e").slice(0, 6).every((x, i) => x === b[i]));
    // messages already in the conversation when the page opens
    const history = [
      [17, 22, 0, 0, 1, 2, 0, ...le32(now() - 3400), ...new TextEncoder().encode("Leeds Central RPT: Net tonight 8pm on #Yorkshire, all welcome")],
      [16, 30, 0, 0, ...key("d47f3e").slice(0, 6), 2, 0, ...le32(now() - 600), ...new TextEncoder().encode("Morning! Heard you via Ilkley, signal is great today")],
      [17, 18, 0, 0, 1, 3, 0, ...le32(now() - 240), ...new TextEncoder().encode("Bob: Anyone near Otley with a spare antenna?")],
    ];
    history.forEach(push);
    const handle = f => {
      const c = f[0];
      if (c === 1) return push([5, 1, 22, 22, ...key("f00d"), ...i32(53800000), ...i32(-1550000), 1, 1, 0, 0, ...le32(869618), ...le32(62500), 8, 8, ...new TextEncoder().encode("Demo Client")]);
      if (c === 4) { push([2, ...le32(contacts.length)]); contacts.forEach(x => push(contactFrame(3, x))); return push([4, ...le32(now())]); }
      if (c === 31) return f[1] < channels.length ? push([18, f[1], ...str(channels[f[1]].name, 32), ...channels[f[1]].secret]) : push([1, 2]);
      if (c === 5) return push([9, ...le32(now())]);
      if (c === 2) {
        const ack = [9, 8, 7, f[3]];
        push([6, 0, ...ack, ...le32(2500)]);
        if (f[1] === 0) setTimeout(() => push([0x82, ...ack, ...le32(2300)]), 1800);
        if (f[1] === 1) setTimeout(() => push([16, 40, 0, 0, ...f.slice(7, 13), 0, 1, ...le32(now()), ...new TextEncoder().encode("v1.17.1 UMC0.1.0 (Build: 14-Aug-2026)")]), 1500);
        return;
      }
      if (c === 36) {
        const tag = f.slice(1, 5); push([6, 0, ...tag, ...le32(3000)]);
        const path = f.slice(10);
        return setTimeout(() => push([0x89, 0, path.length, 0, ...tag, 0, 0, 0, 0, ...path, ...path.map((_, i) => [46, 38, 30][i % 3]), 44]), 1500);
      }
      if (c === 27 || c === 26 || c === 39) {
        const target = f.slice(c === 39 ? 4 : 1, c === 39 ? 10 : 7);
        push([6, 0, 1, 2, 3, 4, ...le32(2500)]);
        if (c === 26) return setTimeout(() => push([0x85, 1, ...target, ...le32(now()), 3, 13]), 1200);
        if (c === 27) return setTimeout(() => push([0x87, 0, ...target, ...[4, 16], ...[0, 0], ...[141, 255], ...[160, 255],
          ...le32(15230), ...le32(4211), ...le32(1320), ...le32(604800), ...le32(2801), ...le32(1410), ...le32(11020), ...le32(4210), 0, 0, ...[40, 0], ...[12, 0], ...[88, 1], ...le32(9120)]), 1200);
        return setTimeout(() => push([0x8B, 0, ...target, 1, 116, 0x01, 0x98, 1, 103, 0x00, 0xC3, 1, 104, 0x7E]), 1200);
      }
      if (c === 52) { push([6, 0, 5, 6, 7, 8, ...le32(3000)]); return setTimeout(() => push([0x8D, 0, ...f.slice(2, 8), 2, 0xa1, 0xb2, 2, 0xb2, 0xa1]), 1500); }
      if (c === 17) return push([11, ...Array.from({length: 120}, (_, i) => (i * 37) & 255)]);
      push([0]);
    };
    return {
      post: body => { body.split("\n").filter(Boolean).forEach(h => handle((h.match(/../g) || []).map(x => parseInt(x, 16)))); return {accepted: 1}; },
      poll: url => {
        const since = +(url.match(/since=(\d+)/) || [0, 0])[1];
        const out = frames.filter(x => x.seq > since).slice(0, 24);
        return {frames: out.map(x => x.hex), boot: 1, seq: out.length ? out[out.length - 1].seq : seq, first: frames.length ? frames[0].seq : 1, more: frames.filter(x => x.seq > since).length > 24};
      },
    };
  })();

  window.UMC_MOCK = async (method, url, body) => {
    await new Promise(r => setTimeout(r, 120));
    if (url === "/api/info") return info();
    if (url === "/api/login") { if (body === "wrong") throw new Error("Wrong password"); return {token: "mocktoken"}; }
    if (url === "/api/logout") return {ok: true};
    if (url.startsWith("/api/scan")) return [{ssid: "HomeNetwork 2.4G", rssi: -48, ch: 6, auth: "wpa2"}, {ssid: "BT-Hub", rssi: -71, ch: 11, auth: "wpa2"}, {ssid: "Guest", rssi: -80, ch: 1, auth: "open"}];
    if (url === "/api/traffic") return {rx_total: 1204, tx_total: 377, packets: [
      {age: 2, tx: false, type: "CHAN", flood: true, hops: 3, rssi: -97, snr: 6.25, len: 58}, {age: 3, tx: true, type: "CHAN", flood: true, hops: 0, rssi: 0, snr: 0, len: 59},
      {age: 20, tx: false, type: "ADVERT", flood: true, hops: 1, rssi: -88, snr: 9.5, len: 140}, {age: 75, tx: false, type: "ACK", flood: false, hops: 2, rssi: -103, snr: -2.25, len: 12}]};
    if (url === "/api/routes") return {routes: [
      {key: "271e2ee5a1b2", name: "Leeds Hill", type: "repeater", hops: 0, hash: 1, path: "", pin: "", snr: 12.5, ago: 95, adverts: 4},
      {key: "da8f72dfcc34", name: "Wakefield Roof", type: "repeater", hops: 1, hash: 1, path: "27", pin: "", snr: 11.8, ago: 320, adverts: 2},
      {key: "9f00ab120011", name: "Bob phone", type: "client", hops: 2, hash: 1, path: "da,27", pin: "27,da,27", snr: 6.0, ago: 4000, adverts: 1}]};
    if (url === "/api/cli") return body.split("\n").map(cmd);
    if (client && url.startsWith("/api/app")) return method === "POST" ? radio.post(body) : radio.poll(url);
    throw new Error("mock: unknown " + url);
  };
})();
