#pragma once
// Wi-Fi motion sensing (CSI) as an optional switch, alongside everything else the node does.
// Uses the ESPectre library (francescopace/espectre, GPLv3 or commercial). It is compiled in ONLY when the build
// defines UMC_WIFI_CSI; those builds (the `*_csi` environments) are therefore GPLv3. Normal UMC builds contain none of it.
// Needs: an ESP32 with Wi-Fi, Arduino-ESP32 core 3.3 or later, and the node joined to a 2.4 GHz access point.
// The switch is `set csi on|off` (saved); sensing starts when Wi-Fi is up and stops when it drops or the switch is off.
#include <Arduino.h>
#include <stdio.h>
#if defined(ESP_PLATFORM)
  #include "freertos/FreeRTOS.h"
  #include "freertos/portmacro.h"
  #define UMC_CSI_LOCK(m)   portENTER_CRITICAL(&(m))
  #define UMC_CSI_UNLOCK(m) portEXIT_CRITICAL(&(m))
#else
  #define UMC_CSI_LOCK(m)   ((void)0)
  #define UMC_CSI_UNLOCK(m) ((void)0)
  typedef int portMUX_TYPE;
  #define portMUX_INITIALIZER_UNLOCKED 0
#endif

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

  // `setEnabled`/`enabled` are written and read on the loop task only (UmcService::loop); other tasks use snapshot().
  void setEnabled(bool on) { _want = on; }
  bool enabled() const { return _want; }
  bool running() const { return snap().running; }

  struct Snap { bool running; bool failed; bool ready; bool motion; float movement; bool want; };
  // One coherent copy, taken under a short critical section; never held across SDK or Wi-Fi calls.
  Snap snap() const { Snap c; UMC_CSI_LOCK(_mux); c = _snap; UMC_CSI_UNLOCK(_mux); return c; }

  // The newest reading, only while sensing is running and calibrated. The ESPectre SDK wants every call on one owner
  // task, and this is also called from the web panel's HTTP task (get csi) and the push tick, so it reads the snapshot.
  bool reading(bool& motion, float& movement) const {
    Snap c = snap();
    if (!c.running || !c.ready) return false;
    motion = c.motion; movement = c.movement;
    return true;
  }

  // True once after sensing stopped or a start failed: the caller restores the node's own Wi-Fi power-save setting.
  bool takePowerSaveDirty() { bool d = _ps_dirty; _ps_dirty = false; return d; }

  void loop() {
#ifdef UMC_WIFI_CSI
    bool up = WiFi.status() == WL_CONNECTED;
    bool running = _snap.running, failed = _snap.failed;
    if (running && (!_want || !up)) { publish(false, false, false); _sensor.end(); running = false; _ps_dirty = true; }   // clear the snapshot first: end() may block
    if (!running && _want && up && (_last_try == 0 || millis() - _last_try > 15000UL)) {
      _last_try = millis() ? millis() : 1;
      publish(false, false, false);                // begin() may block: never leave a stale reading visible meanwhile
      running = _sensor.begin();                  // after WiFi.begin(); it calibrates for a few seconds, keep the room still
      failed = !running;
      if (failed) _ps_dirty = true;               // a failed start may still have touched Wi-Fi power save
    }
    if (!_want) failed = false;
    Snap n = {running, failed, false, false, 0.0f, _want};
    if (running) {
      // ESPectre switches Wi-Fi power save off on each connection, but the node's own power-save setting can switch it
      // back on (a settings change), which starves CSI. Re-assert every few seconds while sensing.
      if (millis() - _last_ps > 5000UL) { _last_ps = millis(); if (WiFi.getSleep()) WiFi.setSleep(false); }
      _sensor.loop();
      n.ready = _sensor.ready();
      n.motion = n.ready && _sensor.motion();
      n.movement = n.ready ? _sensor.movement() : 0.0f;
    }
    UMC_CSI_LOCK(_mux); _snap = n; UMC_CSI_UNLOCK(_mux);
#endif
  }

  void publish(bool running, bool failed, bool ready) {
    Snap n = {running, failed, ready, false, 0.0f, _want};
    UMC_CSI_LOCK(_mux); _snap = n; UMC_CSI_UNLOCK(_mux);
  }

  void status(char* out, size_t n) const {
    if (!built()) { snprintf(out, n, "not in this build"); return; }
    Snap c = snap();
    if (!c.want) { snprintf(out, n, "off"); return; }
    if (!c.running) { snprintf(out, n, c.failed ? "on, sensor failed to start (retrying every 15 s)" : "on, waiting for Wi-Fi"); return; }
    if (!c.ready) { snprintf(out, n, "on, calibrating (keep the room still)"); return; }
    snprintf(out, n, "on, %s, movement %.2f", c.motion ? "motion" : "idle", (double)c.movement);
  }

private:
  bool _want = false;                      // loop task only
  bool _ps_dirty = false;                  // loop task only
  unsigned long _last_try = 0;
  unsigned long _last_ps = 0;
  Snap _snap = {false, false, false, false, 0.0f, false};
  mutable portMUX_TYPE _mux = portMUX_INITIALIZER_UNLOCKED;
#ifdef UMC_WIFI_CSI
  ESPectre _sensor;
#endif
};
