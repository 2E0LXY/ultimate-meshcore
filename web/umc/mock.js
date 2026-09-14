// Development-only fake device so the UI can be exercised from a plain file/browser.
// Enabled when the page is opened with ?mock (never embedded in firmware).
(function () {
  if (!/[?&]mock\b/.test(location.search)) return;
  const setup = /[?&]mock=setup\b/.test(location.search);
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
  const info = () => ({fw: "UMC", umc: "0.1.0", api: 1, name: state.name, role: "repeater", ver: "v1.17.1", build: "14 Sep 2026", board: "Heltec V3",
    setup: !setupDone, default_pw: false, features: ["wifi", "ota", "telnet", "mqtt", "espnow", "bridge", "display", "webstats"],
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
    if (c === "neighbors") return "A1B2C3D4:" + (Math.floor(Date.now() / 1000) - 340) + ":24\n9F00AB12:" + (Math.floor(Date.now() / 1000) - 5400) + ":-18";
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
    if (c === "setup done") { setupDone = true; return "OK - setup complete"; }
    if (/^get wifi\.pwd/.test(c)) return "> -";
    let m = c.match(/^get (\S+)$/); if (m) return m[1] in state ? "> " + state[m[1]] : "??: " + m[1];
    m = c.match(/^set (\S+) ?(.*)$/); if (m) { state[m[1]] = m[2]; return "OK"; }
    if (/^password /.test(c)) return "password now: ********";
    if (/^time /.test(c)) return "OK - clock set";
    return "OK";
  };
  window.UMC_MOCK = async (method, url, body) => {
    await new Promise(r => setTimeout(r, 120));
    if (url === "/api/info") return info();
    if (url === "/api/login") { if (body === "wrong") throw new Error("Wrong password"); return {token: "mocktoken"}; }
    if (url === "/api/logout") return {ok: true};
    if (url.startsWith("/api/scan")) return [{ssid: "HomeNetwork 2.4G", rssi: -48, ch: 6, auth: "wpa2"}, {ssid: "BT-Hub", rssi: -71, ch: 11, auth: "wpa2"}, {ssid: "Guest", rssi: -80, ch: 1, auth: "open"}];
    if (url === "/api/cli") return body.split("\n").map(cmd);
    throw new Error("mock: unknown " + url);
  };
})();
