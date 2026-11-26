#pragma once
// UMC telemetry subscribe/push -- pure logic (no Arduino, no radio), host-testable.
//
// Idea taken from ripplebiz/MeshCore-sensor-playground (branch repeater-telem-push, 7df63ae):
// a client subscribes to a repeater's telemetry with per-value minimum deltas, and the
// repeater pushes a telemetry reply only when a watched value moves by more than the delta.
// Differences from upstream: every length is validated, entries are parsed once at subscribe
// time (no re-parsing of client bytes in the sensor loop), previous values are kept as floats,
// and the region scope is optional (UMC hides regions).
//
// Subscribe request body (after the 0x08 request type byte):
//   [0..3]  push_tag      u32, echoed in every push so the client can match it
//   [4..5]  timeout_secs  u16 LE, capped by TELEM_SUBSCRIBE_MAX_SECS
//   [6]     reserved
//   [7]     deltas_len    bytes that follow; 0 = not allowed (use UNSUBSCRIBE)
//   [8..]   deltas        repeated: channel u8, LPP type u8, min-delta in that type's encoding
// Subscribe reply: [4..5] granted secs LE (0 = refused), [6..7] reserved 0.

#include <stdint.h>
#include <string.h>
#include <math.h>
#include <helpers/sensors/LPPDataHelpers.h>

#ifndef TELEM_SUB_MAX_ENTRIES
  #define TELEM_SUB_MAX_ENTRIES 8
#endif
#ifndef TELEM_SUBSCRIBE_MAX_SECS
  #define TELEM_SUBSCRIBE_MAX_SECS 3600
#endif

namespace umc {

struct LppInfo {
  uint8_t  size;      // bytes of the value; 0 = unknown type
  uint32_t mult;      // divisor
  bool     is_signed;
  bool     scalar;    // single number we can compare
};

inline LppInfo lppInfo(uint8_t t) {
  switch (t) {
    case LPP_DIGITAL_INPUT:      return {1, LPP_DIGITAL_INPUT_MULT, false, true};
    case LPP_DIGITAL_OUTPUT:     return {1, LPP_DIGITAL_OUTPUT_MULT, false, true};
    case LPP_ANALOG_INPUT:       return {2, LPP_ANALOG_INPUT_MULT, true, true};
    case LPP_ANALOG_OUTPUT:      return {2, LPP_ANALOG_OUTPUT_MULT, true, true};
    case LPP_GENERIC_SENSOR:     return {4, LPP_GENERIC_SENSOR_MULT, false, true};
    case LPP_LUMINOSITY:         return {2, LPP_LUMINOSITY_MULT, false, true};
    case LPP_PRESENCE:           return {1, LPP_PRESENCE_MULT, false, true};
    case LPP_TEMPERATURE:        return {2, LPP_TEMPERATURE_MULT, true, true};
    case LPP_RELATIVE_HUMIDITY:  return {1, LPP_RELATIVE_HUMIDITY_MULT, false, true};
    case LPP_BAROMETRIC_PRESSURE:return {2, LPP_BAROMETRIC_PRESSURE_MULT, false, true};
    case LPP_VOLTAGE:            return {2, LPP_VOLTAGE_MULT, false, true};
    case LPP_CURRENT:            return {2, LPP_CURRENT_MULT, true, true};
    case LPP_FREQUENCY:          return {4, LPP_FREQUENCY_MULT, false, true};
    case LPP_PERCENTAGE:         return {1, LPP_PERCENTAGE_MULT, false, true};
    case LPP_ALTITUDE:           return {2, LPP_ALTITUDE_MULT, true, true};
    case LPP_CONCENTRATION:      return {2, LPP_CONCENTRATION_MULT, false, true};
    case LPP_POWER:              return {2, LPP_POWER_MULT, false, true};
    case LPP_DISTANCE:           return {4, LPP_DISTANCE_MULT, false, true};
    case LPP_ENERGY:             return {4, LPP_ENERGY_MULT, false, true};
    case LPP_DIRECTION:          return {2, LPP_DIRECTION_MULT, false, true};
    case LPP_UNIXTIME:           return {4, LPP_UNIXTIME_MULT, false, false};
    case LPP_SWITCH:             return {1, LPP_SWITCH_MULT, false, true};
    // multi-value types: only needed so a telemetry buffer can be skipped over safely
    case LPP_ACCELEROMETER:      return {6, LPP_ACCELEROMETER_MULT, true, false};
    case LPP_GYROMETER:          return {6, LPP_GYROMETER_MULT, true, false};
    case LPP_COLOUR:             return {3, LPP_COLOUR_MULT, false, false};
    case LPP_GPS:                return {9, LPP_GPS_LAT_LON_MULT, true, false};
    default:                     return {0, 1, false, false};
  }
}

inline float lppDecode(const uint8_t* p, const LppInfo& li) {
  uint32_t v = 0;
  for (uint8_t i = 0; i < li.size; i++) v = (v << 8) | p[i];
  if (li.is_signed) {
    uint32_t sign_bit = 1ul << (li.size * 8 - 1);
    int32_t sv = (v & sign_bit) ? (int32_t)(v | ~((sign_bit << 1) - 1)) : (int32_t)v;
    return (float)sv / (float)li.mult;
  }
  return (float)v / (float)li.mult;
}

// Find a scalar value in a Cayenne LPP buffer. Never reads past `size`. Returns false if absent.
inline bool lppFind(const uint8_t* buf, uint8_t size, uint8_t channel, uint8_t type, float& out) {
  uint8_t i = 0;
  while (i + 2 <= size) {
    uint8_t ch = buf[i], t = buf[i + 1];
    if (ch == 0 && t == 0) break;          // end-of-data marker
    LppInfo li = lppInfo(t);
    if (li.size == 0) return false;        // unknown type: cannot skip safely
    if ((uint16_t)i + 2 + li.size > size) return false;
    if (ch == channel && t == type && li.scalar) { out = lppDecode(&buf[i + 2], li); return true; }
    i += 2 + li.size;
  }
  return false;
}

struct TelemSubEntry {
  uint8_t channel;
  uint8_t type;
  bool    have_prev;
  float   min_delta;
  float   prev;
};

struct TelemSub {
  uint32_t push_tag;
  uint32_t expiry;       // millis() deadline (monotonic: an RTC correction must neither extend nor cut a subscription)
  uint16_t region_id;    // 0 = use default scope / unscoped
  uint8_t  count;        // 0 = not subscribed
  TelemSubEntry e[TELEM_SUB_MAX_ENTRIES];

  void clear() { memset(this, 0, sizeof(*this)); }
  bool active(uint32_t now_ms) const { return count > 0 && (int32_t)(expiry - now_ms) >= 0; }   // wrap-safe
};

// Parse the deltas block. All-or-nothing: returns false (and leaves `s` cleared) on any defect.
inline bool telemSubParse(TelemSub& s, const uint8_t* deltas, uint8_t len) {
  s.clear();
  uint8_t i = 0, n = 0;
  while (i < len) {
    if (i + 2 > len || n >= TELEM_SUB_MAX_ENTRIES) { s.clear(); return false; }
    uint8_t ch = deltas[i], t = deltas[i + 1];
    LppInfo li = lppInfo(t);
    if (ch == 0 || li.size == 0 || !li.scalar || (uint16_t)i + 2 + li.size > len) { s.clear(); return false; }
    float d = lppDecode(&deltas[i + 2], li);
    if (!(d >= 0.0f) || isnan(d)) { s.clear(); return false; }
    for (uint8_t k = 0; k < n; k++)
      if (s.e[k].channel == ch && s.e[k].type == t) { s.clear(); return false; }   // duplicate
    s.e[n].channel = ch; s.e[n].type = t; s.e[n].min_delta = d; s.e[n].have_prev = false; s.e[n].prev = 0;
    n++;
    i += 2 + li.size;
  }
  if (n == 0) { s.clear(); return false; }
  s.count = n;
  return true;
}

// True if any watched value is new or has moved by more than its min-delta since it was last pushed.
// Peek does not touch the snapshot; call telemSubCommit only once the push has really been queued,
// so a failed send is retried on the next cycle.
inline bool telemSubPeek(const TelemSub& s, const uint8_t* telem, uint8_t tlen) {
  float cur;
  for (uint8_t k = 0; k < s.count; k++) {
    if (!lppFind(telem, tlen, s.e[k].channel, s.e[k].type, cur)) continue;     // sensor absent this cycle: not a change
    if (!s.e[k].have_prev || fabsf(cur - s.e[k].prev) > s.e[k].min_delta) return true;
  }
  return false;
}

// Record every watched value that is present as the new baseline.
inline void telemSubCommit(TelemSub& s, const uint8_t* telem, uint8_t tlen) {
  float cur;
  for (uint8_t k = 0; k < s.count; k++)
    if (lppFind(telem, tlen, s.e[k].channel, s.e[k].type, cur)) { s.e[k].prev = cur; s.e[k].have_prev = true; }
}

// Peek and, on a change, commit in one step (for callers that cannot fail after the decision).
inline bool telemSubChanged(TelemSub& s, const uint8_t* telem, uint8_t tlen) {
  if (!telemSubPeek(s, telem, tlen)) return false;
  telemSubCommit(s, telem, tlen);
  return true;
}

// ---- built-in subscription for the MQTT uplink -------------------------------------------------
// The repeater watches its own sensors for the broker: every scalar value present in the telemetry
// buffer, with a sensible default delta per type (first TELEM_SUB_MAX_ENTRIES values).
inline float telemDefaultDelta(uint8_t t) {
  switch (t) {
    case LPP_VOLTAGE:             return 0.05f;   // V
    case LPP_CURRENT:             return 0.05f;   // A
    case LPP_TEMPERATURE:         return 0.5f;    // C
    case LPP_RELATIVE_HUMIDITY:   return 2.0f;    // %
    case LPP_BAROMETRIC_PRESSURE: return 1.0f;    // hPa
    case LPP_LUMINOSITY:          return 20.0f;   // lux
    case LPP_ALTITUDE:            return 5.0f;    // m
    case LPP_PERCENTAGE:          return 2.0f;
    case LPP_POWER:               return 1.0f;
    case LPP_DISTANCE:            return 0.1f;    // m
    case LPP_CONCENTRATION:       return 10.0f;   // ppm
    default:                      return 0.0f;    // any change counts (switches, presence, digital)
  }
}

inline void telemSubAuto(TelemSub& s, const uint8_t* telem, uint8_t tlen) {
  uint8_t i = 0;
  while (i + 2 <= tlen && s.count < TELEM_SUB_MAX_ENTRIES) {
    uint8_t ch = telem[i], t = telem[i + 1];
    if (ch == 0 && t == 0) break;
    LppInfo li = lppInfo(t);
    if (li.size == 0 || (uint16_t)i + 2 + li.size > tlen) break;
    if (ch != 0 && li.scalar) {
      bool known = false;
      for (uint8_t k = 0; k < s.count; k++) if (s.e[k].channel == ch && s.e[k].type == t) { known = true; break; }
      if (!known) {
        TelemSubEntry& e = s.e[s.count++];
        e.channel = ch; e.type = t; e.min_delta = telemDefaultDelta(t); e.have_prev = false; e.prev = 0;
      }
    }
    i += 2 + li.size;
  }
}

}  // namespace umc
