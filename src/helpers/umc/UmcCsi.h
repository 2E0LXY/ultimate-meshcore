#pragma once
// Wi-Fi motion sensing (CSI) as an optional switch, alongside everything else the node does.
// Uses the ESPectre library (francescopace/espectre, GPLv3 or commercial). It is compiled in ONLY when the build
// defines UMC_WIFI_CSI; those builds (the `*_csi` environments) are therefore GPLv3. Normal UMC builds contain none of it.
// Needs: an ESP32 with Wi-Fi, Arduino-ESP32 core 3.3 or later, and the node joined to a 2.4 GHz access point.
// The switch is `set csi on|off` (saved); sensing starts when Wi-Fi is up and stops when it drops or the switch is off.
#include <Arduino.h>
#include <stdio.h>

#ifdef UMC_WIFI_CSI
  #include <WiFi.h>
  #include <ESPectre.h>
#endif

class UmcCsi {
public:
  static bool built() {
#ifdef UMC_WIFI_CSI
    return true;
#else
    return false;
#endif
  }

  void setEnabled(bool on) { _want = on; }
  bool enabled() const { return _want; }
  bool running() const { return _running; }

  // The newest reading, only while sensing is running and calibrated.
  bool reading(bool& motion, float& movement) const {
#ifdef UMC_WIFI_CSI
    if (!_running || !_sensor.ready()) return false;
    motion = _sensor.motion();
    movement = _sensor.movement();
    return true;
#else
    (void)motion; (void)movement;
    return false;
#endif
  }

  void loop() {
#ifdef UMC_WIFI_CSI
    bool up = WiFi.status() == WL_CONNECTED;
    if (_running && (!_want || !up)) { _sensor.end(); _running = false; }
    if (!_running && _want && up && (_last_try == 0 || millis() - _last_try > 15000UL)) {
      _last_try = millis() ? millis() : 1;
      _running = _sensor.begin();                 // after WiFi.begin(); it calibrates for a few seconds, keep the room still
    }
    if (_running) {
      // ESPectre switches Wi-Fi power save off on each connection, but the node's own power-save setting can switch it
      // back on (a settings change), which starves CSI. Re-assert every few seconds while sensing.
      if (millis() - _last_ps > 5000UL) { _last_ps = millis(); if (WiFi.getSleep()) WiFi.setSleep(false); }
      _sensor.loop();
    }
#endif
  }

  void status(char* out, size_t n) const {
    if (!built()) { snprintf(out, n, "not in this build"); return; }
    if (!_want) { snprintf(out, n, "off"); return; }
    if (!_running) { snprintf(out, n, "on, waiting for Wi-Fi"); return; }
    bool m = false; float mv = 0;
    if (!reading(m, mv)) { snprintf(out, n, "on, calibrating (keep the room still)"); return; }
    snprintf(out, n, "on, %s, movement %.2f", m ? "motion" : "idle", (double)mv);
  }

private:
  bool _want = false;
  bool _running = false;
  unsigned long _last_try = 0;
  unsigned long _last_ps = 0;
#ifdef UMC_WIFI_CSI
  mutable ESPectre _sensor;
#endif
};
