#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// `tryset <secs> <key> <value>`: a timed trial of one setting (see docs/umc/MANUAL.md). The value is
// applied live but never saved; unless it is kept before the timer ends it goes back to what it was,
// and a reboot loses it anyway because it was never written. While a trial runs, `set` is refused and
// any other save of the preferences writes the original values, so the trial value cannot reach flash. Plain code with no hardware in it, so it
// is tested on a computer (test/test_trial).
namespace umctrial {

constexpr uint32_t kMinSecs = 30;
constexpr uint32_t kMaxSecs = 3600;

// Only settings that cannot lock the operator out or strand the node. Deliberately NOT here until a
// hardware rollback is proven: radio frequency, bandwidth, spreading factor, coding rate, presets,
// regions, tx power, the interference threshold, and anything else connectivity-critical. Never add
// credentials, keys, passwords, access control, broker endpoints or WiFi.
inline bool keyAllowed(const char* key) {
  static const char* const kKeys[] = {
      "dutycycle",       "af",                "advert.interval",  "flood.advert.interval",
      "flood.max",       "flood.max.advert",  "flood.max.unscoped", "rxdelay",
      "txdelay",         "direct.txdelay",    "agc.reset.interval", "multi.acks"};
  if (key == nullptr || key[0] == 0) return false;
  for (const char* k : kKeys) {
    if (strcmp(k, key) == 0) return true;
  }
  return false;
}

inline const char* keyList() {
  return "dutycycle, af, advert.interval, flood.advert.interval, flood.max, flood.max.advert, "
         "flood.max.unscoped, rxdelay, txdelay, direct.txdelay, agc.reset.interval, multi.acks";
}

enum Result : uint8_t { TR_OK = 0, TR_BUSY, TR_NONE, TR_KEY, TR_SECS, TR_FORMAT };

inline const char* errText(Result r) {
  switch (r) {
    case TR_BUSY: return "Err - a trial is already running: tryset keep or tryset revert first";
    case TR_NONE: return "Err - no trial running";
    case TR_KEY: return "Err - that setting cannot be trialled";
    case TR_SECS: return "Err - seconds must be 30 to 3600";
    case TR_FORMAT: return "Err - use: tryset <secs> <key> <value> | keep | revert | status";
    default: return "OK";
  }
}

struct Args {
  uint32_t secs;
  char key[28];
  char value[64];
};

// "<secs> <key> <value...>" (the text after "tryset "). Checks shape, the seconds range and the key
// whitelist, not the value (the ordinary `set` code does that when the value is applied).
inline Result parse(const char* s, Args& out) {
  memset(&out, 0, sizeof(out));
  if (s == nullptr) return TR_FORMAT;
  while (*s == ' ') s++;
  if (*s < '0' || *s > '9') return TR_FORMAT;
  char* end = nullptr;
  const unsigned long secs = strtoul(s, &end, 10);
  if (end == s || (*end != ' ' && *end != 0)) return TR_FORMAT;
  while (*end == ' ') end++;
  const char* k = end;
  while (*end != 0 && *end != ' ') end++;
  const size_t klen = (size_t)(end - k);
  if (klen == 0) return TR_FORMAT;
  if (klen >= sizeof(out.key)) return TR_KEY;
  memcpy(out.key, k, klen);
  out.key[klen] = 0;
  while (*end == ' ') end++;
  const size_t vlen = strlen(end);
  if (vlen == 0) return TR_FORMAT;
  if (vlen >= sizeof(out.value)) return TR_FORMAT;
  for (size_t i = 0; i < vlen; i++) {
    if ((uint8_t)end[i] < 0x20 || end[i] == 0x7f) return TR_FORMAT;
  }
  memcpy(out.value, end, vlen);
  out.value[vlen] = 0;
  if (!keyAllowed(out.key)) return TR_KEY;
  if (secs < kMinSecs || secs > kMaxSecs) return TR_SECS;
  out.secs = (uint32_t)secs;
  return TR_OK;
}

// The timer. One trial at a time; the deadline is compared as a signed difference so it survives
// millis() wrapping (a trial is at most an hour, far inside the 24 days a signed difference covers).
class Trial {
public:
  bool active() const { return _active; }
  const char* key() const { return _key; }

  Result begin(uint32_t now_ms, uint32_t secs, const char* key) {
    if (_active) return TR_BUSY;
    if (!keyAllowed(key)) return TR_KEY;
    if (secs < kMinSecs || secs > kMaxSecs) return TR_SECS;
    strncpy(_key, key, sizeof(_key) - 1);
    _key[sizeof(_key) - 1] = 0;
    _deadline = now_ms + secs * 1000UL;
    _active = true;
    return TR_OK;
  }
  // true once the timer has run out (the caller then restores the old value and calls finish())
  bool expired(uint32_t now_ms) const { return _active && (int32_t)(now_ms - _deadline) >= 0; }
  uint32_t remainingSecs(uint32_t now_ms) const {
    if (!_active) return 0;
    const int32_t left = (int32_t)(_deadline - now_ms);
    return left <= 0 ? 0 : (uint32_t)(left + 999) / 1000;
  }
  // the trial is over (kept, reverted or expired): the caller has already done what that means
  Result finish() {
    if (!_active) return TR_NONE;
    _active = false;
    _key[0] = 0;
    return TR_OK;
  }

private:
  bool _active = false;
  uint32_t _deadline = 0;
  char _key[28] = {0};
};

// The values a trial can change, copied before it starts and put back to undo it. `P` is the node's
// preferences (NodePrefs); a template so a test can use a stand-in with the same field names.
struct Snapshot {
  float airtime_factor, rx_delay_base, tx_delay_factor, direct_tx_delay_factor;
  uint8_t advert_interval, flood_advert_interval, flood_max, flood_max_unscoped, flood_max_advert;
  uint8_t agc_reset_interval, multi_acks;
};

template <class P> inline void capture(const P& p, Snapshot& s) {
  s.airtime_factor = p.airtime_factor;
  s.rx_delay_base = p.rx_delay_base;
  s.tx_delay_factor = p.tx_delay_factor;
  s.direct_tx_delay_factor = p.direct_tx_delay_factor;
  s.advert_interval = p.advert_interval;
  s.flood_advert_interval = p.flood_advert_interval;
  s.flood_max = p.flood_max;
  s.flood_max_unscoped = p.flood_max_unscoped;
  s.flood_max_advert = p.flood_max_advert;
  s.agc_reset_interval = p.agc_reset_interval;
  s.multi_acks = p.multi_acks;
}

template <class P> inline void restore(P& p, const Snapshot& s) {
  p.airtime_factor = s.airtime_factor;
  p.rx_delay_base = s.rx_delay_base;
  p.tx_delay_factor = s.tx_delay_factor;
  p.direct_tx_delay_factor = s.direct_tx_delay_factor;
  p.advert_interval = s.advert_interval;
  p.flood_advert_interval = s.flood_advert_interval;
  p.flood_max = s.flood_max;
  p.flood_max_unscoped = s.flood_max_unscoped;
  p.flood_max_advert = s.flood_max_advert;
  p.agc_reset_interval = s.agc_reset_interval;
  p.multi_acks = s.multi_acks;
}

// Read back after a restore: every field exactly as it was.
inline bool same(const Snapshot& a, const Snapshot& b) {
  return a.airtime_factor == b.airtime_factor && a.rx_delay_base == b.rx_delay_base && a.tx_delay_factor == b.tx_delay_factor &&
         a.direct_tx_delay_factor == b.direct_tx_delay_factor && a.advert_interval == b.advert_interval &&
         a.flood_advert_interval == b.flood_advert_interval && a.flood_max == b.flood_max &&
         a.flood_max_unscoped == b.flood_max_unscoped && a.flood_max_advert == b.flood_max_advert &&
         a.agc_reset_interval == b.agc_reset_interval && a.multi_acks == b.multi_acks;
}

}  // namespace umctrial
