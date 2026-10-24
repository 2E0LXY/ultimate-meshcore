import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProvisionCommands, isDangerousCommand, normaliseCliReplies, RADIO_PRESETS, REGION_PRESETS, redactCommand,
} from "../flasher/provision.mjs";

test("the published radio list matches the firmware's complete preset list", () => {
  assert.equal(RADIO_PRESETS.length, 27);
  assert.deepEqual(RADIO_PRESETS[0], ["EU/UK (Narrow)", 869.618, 62.5, 8, 8, -1]);
});

test("publishes the LocalMesh GB and separate island-of-Ireland region codes", () => {
  assert(REGION_PRESETS.includes("gb-yor"));
  assert(REGION_PRESETS.includes("ioi"));
  assert(REGION_PRESETS.includes("bhd"));
  assert(!REGION_PRESETS.includes("uk"));
  assert(!REGION_PRESETS.includes("yorkshire"));
});

test("builds repeater first-boot commands in a safe order", () => {
  const commands = buildProvisionCommands({
    radio: "5", region: "gb-yor", name: "Home Node", ssid: "Mesh WiFi",
    wifiPassword: "password123", adminPassword: "adminpass",
    latitude: "53.8", longitude: "-1.55", duty: "10", finish: true,
  }, "repeater");
  assert.deepEqual(commands.slice(0, 3), [
    "set radio 869.432,62.5,7,5", "set path.hash.mode 1", "set name Home Node",
  ]);
  assert(commands.includes("set wifi.ssid Mesh WiFi"));
  assert(commands.includes("set wifi.pwd password123"));
  assert.deepEqual(commands.slice(commands.indexOf("region preset gb-yor"), commands.indexOf("region preset gb-yor") + 2),
    ["region preset gb-yor", "region save"]);
  assert(commands.includes("setup done"));
  assert.equal(commands.at(-1), "wifi reconnect");
});

test("builds a multi-region hierarchy and current LetsMesh analyzer setup", () => {
  const commands = buildProvisionCommands({
    regions: [
      {code: "gb", parent: ""},
      {code: "gb-eng", parent: "gb"},
      {code: "gb-eng-nw", parent: "gb-eng"},
    ],
    regionHome: "gb-eng-nw", mqttBroker: "letsmesh-eu", mqttIata: "lba",
  });
  assert.deepEqual(commands.slice(0, 8), [
    "region put gb", "region allowf gb", "region put gb-eng gb", "region allowf gb-eng",
    "region put gb-eng-nw gb-eng", "region allowf gb-eng-nw", "region home gb-eng-nw", "region save",
  ]);
  assert(commands.includes("set mqtt.iata LBA"));
  assert(commands.includes("set mqtt.letsmesh-eu on"));
});

test("redacts all supported password commands without hiding their names", () => {
  assert.equal(redactCommand("password adminpass"), "password ••••••••");
  assert.equal(redactCommand("set wifi.pwd2 password123"), "set wifi.pwd2 ••••••••");
  assert.equal(redactCommand("set ap.password password123"), "set ap.password ••••••••");
  assert.equal(redactCommand("set bridge.peer.secret private"), "set bridge.peer.secret ••••••••");
  assert.equal(redactCommand("set pin 12345678"), "set pin ••••••••");
  assert.equal(redactCommand("set prv.key abcdef"), "set prv.key ••••••••");
  assert.equal(redactCommand("set name Example"), "set name Example");
});

test("normalises full CLI output and identifies disruptive Web Client commands", () => {
  assert.deepEqual(normaliseCliReplies('["line one","line two"]'), ["line one", "line two"]);
  assert.deepEqual(normaliseCliReplies('"OK"'), ["OK"]);
  assert.equal(isDangerousCommand("reboot"), true);
  assert.equal(isDangerousCommand("factory reset"), true);
  assert.equal(isDangerousCommand("get radio"), false);
});

test("rejects destructive commands and ambiguous secrets", () => {
  assert.throws(() => buildProvisionCommands({extra: "factory reset"}), /Blocked destructive command/);
  assert.throws(() => buildProvisionCommands({ssid: "x", wifiPassword: " shortpass "}), /cannot start or end/);
  assert.throws(() => buildProvisionCommands({ssid: "", wifiPassword: "password123"}), /needs a network name/);
  assert.throws(() => buildProvisionCommands({region: "yorkshire"}), /valid LocalMesh region/);
  assert.throws(() => buildProvisionCommands({regions: [{code: "GB", parent: ""}]}), /Invalid MeshCore region code/);
  assert.throws(() => buildProvisionCommands({regions: [{code: "gb-eng", parent: "gb"}]}), /must be configured before/);
  assert.throws(() => buildProvisionCommands({mqttBroker: "letsmesh-eu"}), /three-letter MQTT location/);
});
