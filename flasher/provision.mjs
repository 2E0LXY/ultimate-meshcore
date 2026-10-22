"use strict";

// First-boot provisioning over the firmware's existing USB bridge. The form is
// intentionally kept in page memory: credentials are never put in a URL,
// localStorage, a firmware image, or a downloaded file.

export const RADIO_PRESETS = [
  ["EU/UK (Narrow)", 869.618, 62.5, 8, 8, -1],
  ["EU/UK narrow, CR5", 869.618, 62.5, 8, 5, -1],
  ["EU/UK (Deprecated)", 869.525, 250, 11, 5, -1],
  ["EU 433 (Long Range)", 433.65, 250, 11, 5, -1],
  ["EU 433 (Narrow)", 433.65, 62.5, 8, 8, -1],
  ["Czech Republic", 869.432, 62.5, 7, 5, 1],
  ["Hungary", 869.618, 62.5, 7, 5, 1],
  ["Netherlands", 869.618, 62.5, 7, 5, -1],
  ["Netherlands (Limburg)", 869.618, 62.5, 8, 8, 1],
  ["Portugal 868", 869.618, 62.5, 7, 6, -1],
  ["Portugal 433", 433.375, 62.5, 9, 6, -1],
  ["Slovakia", 869.618, 62.5, 7, 5, 1],
  ["Switzerland", 869.618, 62.5, 8, 8, -1],
  ["USA", 910.525, 62.5, 7, 5, -1],
  ["USA – Southern California", 927.875, 62.5, 7, 5, 2],
  ["Canada", 910.525, 62.5, 7, 5, 2],
  ["Costa Rica", 910.525, 125, 11, 5, -1],
  ["Brazil", 923.125, 62.5, 8, 8, -1],
  ["Australia", 915.8, 250, 10, 5, -1],
  ["Australia (Narrow)", 916.575, 62.5, 7, 7, -1],
  ["Australia (Mid)", 915.075, 125, 9, 5, -1],
  ["Australia – SA, WA", 923.125, 62.5, 8, 8, -1],
  ["Australia – QLD", 923.125, 62.5, 8, 5, -1],
  ["New Zealand (Narrow)", 917.375, 62.5, 7, 5, 1],
  ["New Zealand (Gisborne)", 917.375, 250, 11, 5, 0],
  ["Vietnam (Narrow)", 920.25, 62.5, 8, 5, -1],
  ["Vietnam (Deprecated)", 920.25, 250, 11, 5, -1],
];

export const TIMEZONES = [
  ["Europe/London", "GMT0BST,M3.5.0/1,M10.5.0"],
  ["Europe/Dublin", "IST-1GMT0,M10.5.0,M3.5.0/1"],
  ["Central Europe", "CET-1CEST,M3.5.0,M10.5.0/3"],
  ["Eastern Europe", "EET-2EEST,M3.5.0/3,M10.5.0/4"],
  ["US Eastern", "EST5EDT,M3.2.0,M11.1.0"],
  ["US Central", "CST6CDT,M3.2.0,M11.1.0"],
  ["US Mountain", "MST7MDT,M3.2.0,M11.1.0"],
  ["US Pacific", "PST8PDT,M3.2.0,M11.1.0"],
  ["Australia Eastern", "AEST-10AEDT,M10.1.0,M4.1.0/3"],
  ["New Zealand", "NZST-12NZDT,M9.5.0,M4.1.0/3"],
  ["UTC", "UTC0"],
];

const utf8 = new TextEncoder();
const textDecoder = new TextDecoder();
const blocked = /^(?:factory\s+reset|erase|reboot|poweroff|start\s+ota|setup\s+start|update\s+install)(?:\s|$)/i;
const dangerous = /^(?:factory\s+reset|erase|reboot|poweroff|start\s+ota|setup\s+start|setup\s+done|update\s+install|ota\s+(?:rollback|install)|region\s+(?:remove|clear))(?:\s|$)/i;

function oneLine(value, label, maxBytes = 140) {
  const v = String(value ?? "").trim();
  if (/\r|\n|\0/.test(v)) throw new Error(`${label} must be one line`);
  if (utf8.encode(v).length > maxBytes) throw new Error(`${label} is too long`);
  return v;
}

function secretLine(value, label, maxBytes) {
  const v = String(value ?? "");
  if (/\r|\n|\0/.test(v)) throw new Error(`${label} must be one line`);
  if (v !== v.trim()) throw new Error(`${label} cannot start or end with a space`);
  if (utf8.encode(v).length > maxBytes) throw new Error(`${label} is too long`);
  return v;
}

function boundedNumber(value, label, min, max) {
  if (value === "" || value == null) return "";
  const number = Number(value);
  if (!Number.isFinite(number) || number < min || number > max) {
    throw new Error(`${label} must be between ${min} and ${max}`);
  }
  return String(number);
}

function wifiCommands(commands, slot, ssidValue, passwordValue) {
  const ssid = secretLine(ssidValue, `WiFi ${slot} name`, 32);
  const password = secretLine(passwordValue, `WiFi ${slot} password`, 63);
  if (!ssid && password) throw new Error(`WiFi ${slot} needs a network name`);
  if (password && password.length < 8) throw new Error(`WiFi ${slot} password must be 8–63 characters, or blank for an open network`);
  if (!ssid) return;
  const suffix = slot === 1 ? "" : String(slot);
  commands.push(`set wifi.ssid${suffix} ${ssid}`);
  if (password) commands.push(`set wifi.pwd${suffix} ${password}`);
}

export function buildProvisionCommands(config, role = "repeater") {
  const c = config || {};
  const commands = [];
  const presetIndex = c.radio === "" || c.radio == null ? -1 : Number(c.radio);
  if (presetIndex >= 0) {
    const p = RADIO_PRESETS[presetIndex];
    if (!p) throw new Error("Choose a valid radio preset");
    commands.push(`set radio ${p[1]},${p[2]},${p[3]},${p[4]}`);
    if (p[5] >= 0) commands.push(`set path.hash.mode ${p[5]}`);
  }

  const name = oneLine(c.name, "Node name", 31);
  if (name) commands.push(`set name ${name}`);

  const latitude = boundedNumber(c.latitude, "Latitude", -90, 90);
  const longitude = boundedNumber(c.longitude, "Longitude", -180, 180);
  if ((latitude === "") !== (longitude === "")) throw new Error("Enter both latitude and longitude, or leave both blank");
  if (latitude !== "") commands.push(`set lat ${Number(latitude).toFixed(6)}`, `set lon ${Number(longitude).toFixed(6)}`);

  const timezone = oneLine(c.timezone, "Timezone", 80);
  if (timezone) commands.push(`set timezone ${timezone}`);

  const pin = oneLine(c.pin, "Device PIN", 8);
  if (pin && !/^\d{8}$/.test(pin)) throw new Error("Device PIN must contain exactly 8 digits");
  if (pin) commands.push(`set pin ${pin}`);

  const hostname = oneLine(c.hostname, "Hostname", 32);
  if (hostname && !/^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/i.test(hostname)) {
    throw new Error("Hostname may contain letters, numbers and internal hyphens only");
  }
  if (hostname) commands.push(`set net.hostname ${hostname}`);

  const tx = boundedNumber(c.tx, "TX power", -9, 22);
  if (tx !== "") commands.push(`set tx ${tx}`);
  if (role === "client") {
    const airtime = boundedNumber(c.airtime, "Airtime factor", 0, 9);
    if (airtime !== "") commands.push(`set af ${airtime}`);
  } else {
    const duty = boundedNumber(c.duty, "Duty-cycle limit", 1, 100);
    if (duty !== "") commands.push(`set dutycycle ${duty}`);
  }

  const region = oneLine(c.region, "Region preset", 20);
  if (region) commands.push(`region preset ${region}`, "region save");

  wifiCommands(commands, 1, c.ssid, c.wifiPassword);
  wifiCommands(commands, 2, c.ssid2, c.wifiPassword2);
  wifiCommands(commands, 3, c.ssid3, c.wifiPassword3);

  const adminPassword = secretLine(c.adminPassword, "Admin password", 32);
  if (adminPassword && (adminPassword.length < 8 || adminPassword.length > 32)) {
    throw new Error("Admin password must be 8–32 characters");
  }
  if (adminPassword) commands.push(`password ${adminPassword}`);

  for (const raw of String(c.extra ?? "").split(/\r?\n/)) {
    const command = oneLine(raw, "Extra command", role === "client" ? 165 : 140);
    if (!command || command.startsWith("#")) continue;
    if (blocked.test(command)) throw new Error(`Blocked destructive command: ${command}`);
    commands.push(command);
  }

  if (c.finish) commands.push("setup done");
  if (c.ssid) commands.push("wifi reconnect");
  if (!commands.length) throw new Error("Enter at least one setting to apply");
  return commands;
}

export function redactCommand(command) {
  return command.replace(
    /^((?:password|login|set\s+(?:pin|prv\.key|private\.key|\S*(?:password|pwd|secret)\S*)))\s+.*/i,
    "$1 ••••••••",
  );
}

export function isDangerousCommand(command) {
  return dangerous.test(String(command ?? "").trim());
}

export function normaliseCliReplies(raw) {
  const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  return (Array.isArray(parsed) ? parsed : [parsed]).map(value => String(value ?? ""));
}

class ProvisionLink {
  constructor(port) {
    this.port = port;
    this.reader = null;
    this.writer = null;
    this.closed = false;
    this.text = "";
    this.frames = new Uint8Array();
    this.textWaiters = [];
    this.frameWaiters = [];
  }

  async open() {
    await this.port.open({baudRate: 115200, bufferSize: 4096});
    try { await this.port.setSignals({dataTerminalReady: false, requestToSend: false}); } catch (_) {}
    this.reader = this.port.readable.getReader();
    this.writer = this.port.writable.getWriter();
    this.pump();
  }

  async pump() {
    try {
      while (!this.closed) {
        const {value, done} = await this.reader.read();
        if (done) break;
        if (!value?.length) continue;
        this.text += textDecoder.decode(value, {stream: true});
        let newline;
        while ((newline = this.text.indexOf("\n")) >= 0) {
          const line = this.text.slice(0, newline).replace(/\r$/, "");
          this.text = this.text.slice(newline + 1);
          this.emit(this.textWaiters, line);
        }
        const joined = new Uint8Array(this.frames.length + value.length);
        joined.set(this.frames); joined.set(value, this.frames.length); this.frames = joined;
        this.parseFrames();
      }
    } catch (error) {
      if (!this.closed) this.rejectAll(error);
    }
  }

  parseFrames() {
    while (this.frames.length) {
      const start = this.frames.indexOf(0x3e); // '>'
      if (start < 0) { this.frames = new Uint8Array(); return; }
      if (start) this.frames = this.frames.slice(start);
      if (this.frames.length < 3) return;
      const length = this.frames[1] | (this.frames[2] << 8);
      if (!length || length > 176) { this.frames = this.frames.slice(1); continue; }
      if (this.frames.length < length + 3) return;
      const frame = this.frames.slice(3, length + 3);
      this.frames = this.frames.slice(length + 3);
      this.emit(this.frameWaiters, frame);
    }
  }

  emit(waiters, value) {
    const index = waiters.findIndex(w => w.match(value));
    if (index < 0) return;
    const [waiter] = waiters.splice(index, 1);
    clearTimeout(waiter.timer);
    waiter.resolve(value);
  }

  waitFor(waiters, match, ms, message) {
    return new Promise((resolve, reject) => {
      const waiter = {match, resolve, reject, timer: null};
      waiter.timer = setTimeout(() => {
        const index = waiters.indexOf(waiter);
        if (index >= 0) waiters.splice(index, 1);
        reject(new Error(message));
      }, ms);
      waiters.push(waiter);
    });
  }

  rejectAll(error) {
    for (const waiters of [this.textWaiters, this.frameWaiters]) {
      for (const waiter of waiters.splice(0)) { clearTimeout(waiter.timer); waiter.reject(error); }
    }
  }

  async write(data) { await this.writer.write(data); }

  async textRequest(request, ms = 2500) {
    const answer = this.waitFor(this.textWaiters, line => {
      const marker = line.indexOf("@umc ");
      if (marker < 0) return false;
      const json = line.slice(marker + 5).trim();
      return json.startsWith("{") || json.startsWith("[");
    }, ms, "waiting for repeater USB bridge");
    await this.write(utf8.encode(`@umc ${request}\r`));
    const line = await answer;
    return line.slice(line.indexOf("@umc ") + 5).trim();
  }

  async frameRequest(payload, expectedCode, ms = 3000, message = "waiting for client USB reply") {
    const answer = this.waitFor(this.frameWaiters, frame => frame[0] === expectedCode, ms, message);
    const packet = new Uint8Array(payload.length + 3);
    packet[0] = 0x3c; packet[1] = payload.length & 255; packet[2] = payload.length >> 8; packet.set(payload, 3);
    await this.write(packet);
    return answer;
  }

  async clientHandshake(ms = 3000) {
    await this.frameRequest(new Uint8Array([22, 8]), 13, ms, "waiting for client device information");
    const name = utf8.encode("Ultimate MeshCore Flasher");
    const start = new Uint8Array(name.length + 8);
    start.set([1, 3, 0, 0, 0, 0, 0, 0]);
    start.set(name, 8);
    await this.frameRequest(start, 5, ms, "waiting for client app handshake");
  }

  async clientRequest(request, ms = 3000) {
    const requestBytes = utf8.encode(request);
    if (requestBytes.length > 165) throw new Error("Client USB request is too long");
    const first = new Uint8Array(requestBytes.length + 2);
    first[0] = 112; first[1] = 0; first.set(requestBytes, 2);
    let frame = await this.frameRequest(first, 112, ms, "waiting for client USB bridge");
    if (frame.length < 5) throw new Error("Client returned an invalid bridge reply");
    const total = frame[1] | (frame[2] << 8);
    const output = new Uint8Array(total);
    const filled = new Uint8Array(total);
    const place = value => {
      if (value.length < 5) return;
      const offset = value[3] | (value[4] << 8);
      const chunk = value.slice(5, Math.min(value.length, total - offset + 5));
      if (offset >= total) return;
      output.set(chunk, offset); filled.fill(1, offset, offset + chunk.length);
    };
    place(frame);
    for (let guard = 0; guard < Math.ceil(total / 8) + 8 && filled.includes(0); guard++) {
      const offset = filled.indexOf(0);
      frame = await this.frameRequest(new Uint8Array([112, 1, offset & 255, offset >> 8]), 112, ms, "waiting for client USB bridge chunk");
      place(frame);
    }
    if (filled.includes(0)) throw new Error("Client USB bridge reply was incomplete");
    return textDecoder.decode(output);
  }

  async request(role, request, ms = 3000) {
    return role === "client" ? this.clientRequest(request, ms) : this.textRequest(request, ms);
  }

  async waitUntilReady(role, status, attempts = 12) {
    let lastError;
    for (let attempt = 1; attempt <= attempts; attempt++) {
      status(`Waiting for ${role} USB bridge… attempt ${attempt}/${attempts}`);
      try {
        if (role === "client") await this.clientHandshake(2200);
        const raw = await this.request(role, "info", 2200);
        const info = JSON.parse(raw);
        if (info && info.umc) return info;
      } catch (error) { lastError = error; }
      await new Promise(resolve => setTimeout(resolve, 800));
    }
    throw new Error(`The firmware did not answer over USB. Wait for it to finish booting and try again${lastError ? ` (${lastError.message})` : ""}.`);
  }

  async runCommand(role, command) {
    return (await this.runCommands(role, command))[0] ?? "";
  }

  async runCommands(role, command) {
    const raw = await this.request(role, `cli ${command}`, 6000);
    return normaliseCliReplies(raw);
  }

  async close() {
    this.closed = true;
    this.rejectAll(new Error("USB connection closed"));
    try { await this.reader?.cancel(); } catch (_) {}
    try { this.reader?.releaseLock(); } catch (_) {}
    try { this.writer?.releaseLock(); } catch (_) {}
    try { await this.port.close(); } catch (_) {}
  }
}

function formValue(id) { return document.getElementById(id)?.value ?? ""; }
function selectedRole() { return document.querySelector('input[name="role"]:checked')?.value || "repeater"; }
function configFromForm() {
  return {
    ssid: formValue("cfgSsid"), wifiPassword: formValue("cfgWifiPassword"),
    ssid2: formValue("cfgSsid2"), wifiPassword2: formValue("cfgWifiPassword2"),
    ssid3: formValue("cfgSsid3"), wifiPassword3: formValue("cfgWifiPassword3"),
    radio: formValue("cfgRadio"), region: formValue("cfgRegion"), name: formValue("cfgName"),
    adminPassword: formValue("cfgAdminPassword"), timezone: formValue("cfgTimezone"),
    hostname: formValue("cfgHostname"), latitude: formValue("cfgLatitude"), longitude: formValue("cfgLongitude"),
    pin: formValue("cfgPin"), tx: formValue("cfgTx"), duty: formValue("cfgDuty"),
    airtime: formValue("cfgAirtime"), extra: formValue("cfgExtra"),
    finish: document.getElementById("cfgFinish")?.checked,
  };
}

function setStatus(message, kind = "") {
  const element = document.getElementById("setupStatus");
  element.textContent = message; element.className = `status ${kind}`;
}

let clientLink = null;
let clientRole = null;
let clientInfo = null;
let clientBusy = false;
const clientHistory = [];
let clientHistoryIndex = 0;

function setClientState(message, kind = "") {
  const state = document.getElementById("clientState");
  state.textContent = message;
  state.className = `pill ${kind}`;
}

function setClientControls(connected, busy = false) {
  clientBusy = busy;
  document.getElementById("clientConnect").disabled = connected || busy || !("serial" in navigator);
  document.getElementById("clientDisconnect").disabled = !connected || busy;
  document.getElementById("clientRefresh").disabled = !connected || busy;
  document.getElementById("clientQuick").disabled = !connected || busy;
  document.getElementById("clientQuickRun").disabled = !connected || busy;
  document.getElementById("clientCommand").disabled = !connected || busy;
  document.getElementById("clientRun").disabled = !connected || busy;
  document.getElementById("applySetup").disabled = busy || !("serial" in navigator);
}

function appendClientLog(prefix, value) {
  const log = document.getElementById("clientLog");
  const time = new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
  const text = `${time}  ${prefix}${String(value ?? "")}\n`;
  log.textContent = log.textContent.startsWith("USB Web Client ready.") ? text : log.textContent + text;
  if (log.textContent.length > 50000) log.textContent = log.textContent.slice(-40000);
  log.scrollTop = log.scrollHeight;
}

function renderClientInfo(info, role) {
  const details = document.getElementById("clientDetails");
  details.replaceChildren();
  const entries = [
    info?.name || "Unnamed node",
    info?.board || "Unknown board",
    role === "client" ? "Ultimate MeshCore Client" : "Repeater",
    `UMC ${info?.umc || "unknown"}`,
    info?.setup ? "Setup incomplete" : "Setup complete",
  ];
  for (const value of entries) {
    const item = document.createElement("span");
    item.className = "pill"; item.textContent = value; details.appendChild(item);
  }
  details.hidden = false;
}

async function detectClient(link) {
  const preferred = selectedRole();
  const roles = preferred === "client" ? ["client", "repeater"] : ["repeater", "client"];
  let lastError;
  for (const role of roles) {
    try {
      const info = await link.waitUntilReady(role, message => setClientState(message), role === preferred ? 4 : 8);
      return {role, info};
    } catch (error) { lastError = error; }
  }
  throw lastError || new Error("This device did not answer as an Ultimate MeshCore repeater or client.");
}

async function connectClient() {
  if (clientLink || clientBusy) return;
  let link;
  try {
    setClientControls(false, true);
    setClientState("Choose the installed device's serial port…");
    const port = await navigator.serial.requestPort();
    link = new ProvisionLink(port);
    await link.open();
    const detected = await detectClient(link);
    clientLink = link; clientRole = detected.role; clientInfo = detected.info;
    renderClientInfo(clientInfo, clientRole);
    setClientState(`Connected: ${clientInfo.name || clientRole}`, "ok");
    appendClientLog("● ", `Connected to ${clientInfo.name || "device"} (${clientRole}, UMC ${clientInfo.umc || "unknown"})`);
    setClientControls(true, false);
    document.getElementById("clientCommand").focus();
  } catch (error) {
    await link?.close();
    setClientState(error?.message || String(error), "bad");
    appendClientLog("! ", error?.message || String(error));
    setClientControls(false, false);
  }
}

async function disconnectClient(message = "Disconnected") {
  const link = clientLink;
  clientLink = null; clientRole = null; clientInfo = null;
  await link?.close();
  document.getElementById("clientDetails").hidden = true;
  setClientState(message);
  appendClientLog("● ", message);
  setClientControls(false, false);
}

async function refreshClient() {
  if (!clientLink || clientBusy) return;
  try {
    setClientControls(true, true);
    setClientState("Refreshing device…");
    clientInfo = JSON.parse(await clientLink.request(clientRole, "info", 4000));
    renderClientInfo(clientInfo, clientRole);
    setClientState(`Connected: ${clientInfo.name || clientRole}`, "ok");
    appendClientLog("● ", "Device information refreshed");
  } catch (error) {
    appendClientLog("! ", error?.message || String(error));
    await disconnectClient("Connection lost");
  } finally {
    if (clientLink) setClientControls(true, false);
  }
}

async function runClientCommand(value) {
  if (!clientLink || clientBusy) return;
  const command = oneLine(value, "Command", clientRole === "client" ? 165 : 140);
  if (!command) return;
  if (isDangerousCommand(command) && !window.confirm(`Run this potentially disruptive command?\n\n${redactCommand(command)}`)) return;
  clientHistory.push(command); clientHistoryIndex = clientHistory.length;
  document.getElementById("clientCommand").value = "";
  appendClientLog("> ", redactCommand(command));
  try {
    setClientControls(true, true);
    setClientState(`Running: ${redactCommand(command)}`);
    const replies = await clientLink.runCommands(clientRole, command);
    for (const reply of replies) appendClientLog("  ", reply || "(no output)");
    setClientState(`Connected: ${clientInfo?.name || clientRole}`, "ok");
    if (/^(?:reboot|poweroff|start\s+ota|update\s+install|ota\s+(?:rollback|install))(?:\s|$)/i.test(command)) {
      await disconnectClient("Device is restarting");
    }
  } catch (error) {
    appendClientLog("! ", error?.message || String(error));
    setClientState(error?.message || String(error), "bad");
  } finally {
    if (clientLink) {
      setClientControls(true, false);
      document.getElementById("clientCommand").focus();
    }
  }
}

function refreshRoleFields() {
  const client = selectedRole() === "client";
  document.getElementById("cfgRepeaterLimit").hidden = client;
  document.getElementById("cfgClientLimit").hidden = !client;
}

function preview(role = selectedRole()) {
  const commands = buildProvisionCommands(configFromForm(), role);
  const plan = document.getElementById("setupPlan");
  plan.textContent = commands.map(redactCommand).join("\n"); plan.hidden = false;
  setStatus(`${commands.length} setting command${commands.length === 1 ? "" : "s"} prepared.`, "ok");
  return commands;
}

async function applySetup() {
  const button = document.getElementById("applySetup");
  let link;
  let keepOpen = false;
  try {
    const role = clientLink ? clientRole : selectedRole();
    const commands = preview(role);
    button.disabled = true;
    let info = clientInfo;
    if (clientLink) {
      link = clientLink; keepOpen = true; setClientControls(true, true);
      setStatus(`Using connected ${info?.name || role}…`);
    } else {
      setStatus("Choose the newly flashed device's serial port…");
      const port = await navigator.serial.requestPort();
      link = new ProvisionLink(port);
      await link.open();
      info = await link.waitUntilReady(role, message => setStatus(message));
    }
    for (let index = 0; index < commands.length; index++) {
      const command = commands[index];
      setStatus(`Applying ${index + 1}/${commands.length}: ${redactCommand(command)}`);
      const reply = await link.runCommand(role, command);
      if (/^(?:err|error)/i.test(reply.trim())) throw new Error(`${redactCommand(command)} — ${reply}`);
    }
    setStatus(`Setup applied successfully to ${info.name || "the device"}. Passwords and advanced commands have been cleared from this page.`, "ok");
    document.getElementById("cfgWifiPassword").value = "";
    document.getElementById("cfgWifiPassword2").value = "";
    document.getElementById("cfgWifiPassword3").value = "";
    document.getElementById("cfgAdminPassword").value = "";
    document.getElementById("cfgExtra").value = "";
    if (keepOpen) {
      setClientControls(true, false);
      await refreshClient();
    }
  } catch (error) {
    setStatus(error?.message || String(error), "bad");
  } finally {
    if (!keepOpen) await link?.close();
    if (clientLink) setClientControls(true, false);
    button.disabled = clientBusy || !("serial" in navigator);
  }
}

function initialise() {
  if (!("serial" in navigator)) {
    document.getElementById("applySetup").disabled = true;
    setStatus("USB setup needs Web Serial in Chrome or Edge. Flashing is still available.");
  }
  const radio = document.getElementById("cfgRadio");
  RADIO_PRESETS.forEach((preset, index) => radio.add(new Option(`${preset[0]} — ${preset[1]} MHz · ${preset[2]} kHz · SF${preset[3]}`, String(index))));
  const timezone = document.getElementById("cfgTimezone");
  TIMEZONES.forEach(item => timezone.add(new Option(item[0], item[1])));
  document.getElementById("previewSetup").addEventListener("click", () => { try { preview(); } catch (error) { setStatus(error.message, "bad"); } });
  document.getElementById("applySetup").addEventListener("click", applySetup);
  document.getElementById("clientConnect").addEventListener("click", connectClient);
  document.getElementById("clientDisconnect").addEventListener("click", () => disconnectClient());
  document.getElementById("clientRefresh").addEventListener("click", refreshClient);
  document.getElementById("clientRun").addEventListener("click", () => {
    runClientCommand(formValue("clientCommand")).catch(error => appendClientLog("! ", error.message));
  });
  document.getElementById("clientQuickRun").addEventListener("click", () => {
    const command = formValue("clientQuick");
    if (command) runClientCommand(command).catch(error => appendClientLog("! ", error.message));
  });
  document.getElementById("clientCommand").addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      runClientCommand(event.currentTarget.value).catch(error => appendClientLog("! ", error.message));
    } else if (event.key === "ArrowUp" && clientHistory.length) {
      event.preventDefault(); clientHistoryIndex = Math.max(0, clientHistoryIndex - 1);
      event.currentTarget.value = clientHistory[clientHistoryIndex];
    } else if (event.key === "ArrowDown" && clientHistory.length) {
      event.preventDefault(); clientHistoryIndex = Math.min(clientHistory.length, clientHistoryIndex + 1);
      event.currentTarget.value = clientHistory[clientHistoryIndex] || "";
    }
  });
  document.getElementById("clientClear").addEventListener("click", () => {
    document.getElementById("clientLog").textContent = "Transcript cleared.\n";
  });
  document.getElementById("clearSecrets").addEventListener("click", () => {
    for (const id of ["cfgWifiPassword", "cfgWifiPassword2", "cfgWifiPassword3", "cfgAdminPassword"]) document.getElementById(id).value = "";
    const extra = document.getElementById("cfgExtra");
    extra.value = extra.value.split(/\r?\n/).filter(line => redactCommand(line) === line).join("\n");
    setStatus("Passwords and advanced secret commands cleared from this page.", "ok");
  });
  document.addEventListener("change", event => { if (event.target?.name === "role") refreshRoleFields(); });
  navigator.serial?.addEventListener("disconnect", event => {
    if (clientLink?.port === event.target) disconnectClient("USB device disconnected");
  });
  setClientControls(false, false);
  refreshRoleFields();
}

if (typeof document !== "undefined") initialise();
