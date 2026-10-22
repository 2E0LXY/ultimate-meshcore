import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProvisionCommands, isDangerousCommand, normaliseCliReplies, RADIO_PRESETS, redactCommand,
} from "../flasher/provision.mjs";

test("the published radio list matches the firmware's complete preset list", () => {
  assert.equal(RADIO_PRESETS.length, 27);
  assert.deepEqual(RADIO_PRESETS[0], ["EU/UK (Narrow)", 869.618, 62.5, 8, 8, -1]);
});

test("builds repeater first-boot commands in a safe order", () => {
  const commands = buildProvisionCommands({
    radio: "5", region: "uk", name: "Home Node", ssid: "Mesh WiFi",
    wifiPassword: "password123", adminPassword: "adminpass",
    latitude: "53.8", longitude: "-1.55", duty: "10", finish: true,
  }, "repeater");
  assert.deepEqual(commands.slice(0, 3), [
    "set radio 869.432,62.5,7,5", "set path.hash.mode 1", "set name Home Node",
  ]);
  assert(commands.includes("set wifi.ssid Mesh WiFi"));
  assert(commands.includes("set wifi.pwd password123"));
  assert(commands.includes("setup done"));
  assert.equal(commands.at(-1), "wifi reconnect");
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
});
