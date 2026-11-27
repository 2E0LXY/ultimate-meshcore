#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(ESP_PLATFORM)
  #include "freertos/FreeRTOS.h"
  #include "freertos/semphr.h"
#elif defined(UMC_TRIAL_STD_MUTEX)
  #include <mutex>
#endif

// `tryset <secs> <key> <value>`: a timed trial of one setting (see docs/umc/MANUAL.md). The value is
// applied live but never saved; unless it is kept before the timer ends it goes back to what it was,
// and a reboot loses it anyway because it was never written. While a trial runs, `set` of any setting
// in the snapshot is refused and any other save of the preferences writes the original values, so the
// trial value cannot reach flash. Every state change is made under one lock (Controller::lock), because
// commands arrive on the web server task while the loop task expires trials. Plain code with no hardware
// in it, so it is tested on a computer (test/test_trial).
namespace umctrial {

constexpr uint32_t kMinSecs = 30;
constexpr uint32_t kMaxSecs = 3600;

enum Result : uint8_t { TR_OK = 0, TR_BUSY, TR_NONE, TR_KEY, TR_SECS, TR_FORMAT, TR_RANGE, TR_APPLY, TR_LOCK };

// Only settings chosen to be recoverable by the timer: each has a range limit below, and none touches
// the radio parameters the admin link depends on. That is a judgement, not a guarantee: a bad value can
// still cost airtime or reach until the timer ends or `tryset revert` is heard. Deliberately NOT here
// until a hardware rollback is proven: radio frequency, bandwidth, spreading factor, coding rate,
// presets, regions, tx power, the interference threshold, and anything else connectivity-critical.
// Never add credentials, keys, passwords, access control, broker endpoints or WiFi.
inline size_t keyTable(const char* const** out) {
  static const char* const kKeys[] = {
      "dutycycle",       "af",                "advert.interval",  "flood.advert.interval",
      "flood.max",       "flood.max.advert",  "flood.max.unscoped", "rxdelay",
      "txdelay",         "direct.txdelay",    "agc.reset.interval", "multi.acks"};
  *out = kKeys;
  return sizeof(kKeys) / sizeof(kKeys[0]);
}

inline bool keyAllowed(const char* key) {
  if (key == nullptr || key[0] == 0) return false;
  const char* const* t;
  const size_t n = keyTable(&t);
  for (size_t i = 0; i < n; i++) {
    if (strcmp(t[i], key) == 0) return true;
  }
  return false;
}

// `tryset keys [n]`: the whitelist in pieces that each fit a reply (157 characters, with room to spare).
// `page` is 1-based; `out` gets "Keys 1/2: a, b, c (tryset keys 2)". Returns the number of pages, or 0
// (out untouched) if `page` is out of range or `cap` is too small (it needs 140).
constexpr size_t kKeyChunk = 90;
inline unsigned keyChunk(unsigned page, char* out, size_t cap) {
  if (cap < kKeyChunk + 50) return 0;
  const char* const* t;
  const size_t n = keyTable(&t);
  char buf[kKeyChunk + 1];
  buf[0] = 0;
  size_t used = 0;
  unsigned cur = 1;
  for (size_t i = 0; i < n; i++) {
    const size_t len = strlen(t[i]);
    if (used && used + 2 + len > kKeyChunk) { cur++; used = 0; }
    const size_t at = used ? used + 2 : 0;
    if (cur == page) {
      if (used) memcpy(buf + used, ", ", 2);
      memcpy(buf + at, t[i], len);
      buf[at + len] = 0;
    }
    used = at + len;
  }
  const unsigned pages = cur;
  if (page < 1 || page > pages) return 0;
  if (page < pages) snprintf(out, cap, "Keys %u/%u: %s (tryset keys %u)", page, pages, buf, page + 1);
  else snprintf(out, cap, "Keys %u/%u: %s", page, pages, buf);
  return pages;
}

inline const char* errText(Result r) {
  switch (r) {
    case TR_BUSY: return "Err - a trial is already running: tryset keep or tryset revert first";
    case TR_NONE: return "Err - no trial running";
    case TR_KEY: return "Err - cannot trial that setting; tryset keys lists the ones you can";
    case TR_SECS: return "Err - seconds must be 30 to 3600";
    case TR_FORMAT: return "Err - use: tryset <secs> <key> <value> | keep | revert | status | keys";
    case TR_RANGE: return "Err - value outside the trial limit";
    case TR_APPLY: return "Err - not applied";
    case TR_LOCK: return "Err - busy, try again";
    default: return "OK";
  }
}

// Limits for the trial path only (plain `set` is unchanged). They stop a trial silencing the node
// (flood.max 0), cutting airtime to a crawl (dutycycle 1 is an airtime factor of 99) or wrapping a byte
// (multi.acks 300). The preference loader clamps the airtime factor to 0-9 (so dutycycle >= 10) and
// multi.acks to 0-1, so a value the next boot would clamp is refused here too. Keys with no entry
// (advert.interval, flood.advert.interval) are checked only by the ordinary `set` code.
inline bool parseNumber(const char* v, double& out) {
  if (v == nullptr || *v == 0) return false;
  char* end = nullptr;
  const double d = strtod(v, &end);
  if (end == v) return false;
  while (*end == ' ') end++;
  if (*end != 0) return false;
  if (!(d == d) || d > 1e9 || d < -1e9) return false;   // NaN or absurd
  out = d;
  return true;
}

inline const char* rangeText(const char* key) {
  if (strcmp(key, "dutycycle") == 0) return "Err - dutycycle must be 10 to 100 for a trial";
  if (strcmp(key, "af") == 0) return "Err - af must be 0 to 9";
  if (strcmp(key, "multi.acks") == 0) return "Err - multi.acks must be 0 or 1";
  if (strncmp(key, "flood.max", 9) == 0) return "Err - flood.max values must be 1 to 64 for a trial (0 stops forwarding)";
  if (strcmp(key, "rxdelay") == 0) return "Err - rxdelay must be 0 to 10 for a trial";
  if (strcmp(key, "txdelay") == 0 || strcmp(key, "direct.txdelay") == 0) return "Err - txdelay values must be 0 to 1 for a trial";
  if (strcmp(key, "agc.reset.interval") == 0) return "Err - agc.reset.interval must be 0 to 1020";
  return errText(TR_RANGE);
}

inline Result checkValue(const char* key, const char* value) {
  double d = 0;
  const bool num = parseNumber(value, d);
  const bool whole = num && d == (double)(long)d;
  if (strcmp(key, "dutycycle") == 0) return (num && d >= 10 && d <= 100) ? TR_OK : TR_RANGE;
  if (strcmp(key, "af") == 0) return (num && d >= 0 && d <= 9) ? TR_OK : TR_RANGE;
  if (strcmp(key, "multi.acks") == 0) return (whole && d >= 0 && d <= 1) ? TR_OK : TR_RANGE;
  if (strcmp(key, "flood.max") == 0 || strcmp(key, "flood.max.advert") == 0 || strcmp(key, "flood.max.unscoped") == 0)
    return (whole && d >= 1 && d <= 64) ? TR_OK : TR_RANGE;
  if (strcmp(key, "rxdelay") == 0) return (num && d >= 0 && d <= 10) ? TR_OK : TR_RANGE;
  if (strcmp(key, "txdelay") == 0 || strcmp(key, "direct.txdelay") == 0) return (num && d >= 0 && d <= 1) ? TR_OK : TR_RANGE;
  if (strcmp(key, "agc.reset.interval") == 0) return (whole && d >= 0 && d <= 1020) ? TR_OK : TR_RANGE;
  return TR_OK;
}

struct Args {
  uint32_t secs;
  char key[28];
  char value[64];
};

// "<secs> <key> <value...>" (the text after "tryset "). Checks shape, the seconds range, the key
// whitelist and the trial limit for the value. The ordinary `set` code still checks the value when it
// is applied. On TR_RANGE `out.key` is set, so rangeText(out.key) names the limit.
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
  if (checkValue(out.key, out.value) != TR_OK) return TR_RANGE;
  out.secs = (uint32_t)secs;
  return TR_OK;
}

// Which `tryset` form this is (the text after "tryset "). Trailing spaces are ignored, so "keep " is
// "keep". Anything else (including "keep now") is SUB_START and is left to parse(), which refuses it.
enum Sub : uint8_t { SUB_STATUS, SUB_KEYS, SUB_KEEP, SUB_REVERT, SUB_START };
inline Sub subcommand(const char* args, unsigned* page) {
  if (page) *page = 1;
  if (args == nullptr) return SUB_STATUS;
  while (*args == ' ') args++;
  size_t n = 0;
  while (args[n] != 0 && args[n] != ' ') n++;
  const char* rest = args + n;
  while (*rest == ' ') rest++;
  if (n == 0 || (n == 6 && strncmp(args, "status", 6) == 0 && *rest == 0)) return SUB_STATUS;
  if (n == 4 && strncmp(args, "keys", 4) == 0) {
    if (page && *rest) { const long v = atol(rest); *page = v < 1 ? 0 : (unsigned)v; }
    return SUB_KEYS;
  }
  if (n == 4 && strncmp(args, "keep", 4) == 0 && *rest == 0) return SUB_KEEP;
  if (n == 6 && strncmp(args, "revert", 6) == 0 && *rest == 0) return SUB_REVERT;
  return SUB_START;
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

// Copy back only the one field `key` names (from `from`). With restore() this puts everything else
// back and leaves the trialled value in place: side effects of the ordinary `set` code (the CLI's save
// zeroes advert_interval when it is under an hour) never stay in the live values.
template <class P> inline void copyKeyField(P& p, const Snapshot& from, const char* key) {
  if (strcmp(key, "dutycycle") == 0 || strcmp(key, "af") == 0) p.airtime_factor = from.airtime_factor;
  else if (strcmp(key, "advert.interval") == 0) p.advert_interval = from.advert_interval;
  else if (strcmp(key, "flood.advert.interval") == 0) p.flood_advert_interval = from.flood_advert_interval;
  else if (strcmp(key, "flood.max") == 0) p.flood_max = from.flood_max;
  else if (strcmp(key, "flood.max.advert") == 0) p.flood_max_advert = from.flood_max_advert;
  else if (strcmp(key, "flood.max.unscoped") == 0) p.flood_max_unscoped = from.flood_max_unscoped;
  else if (strcmp(key, "rxdelay") == 0) p.rx_delay_base = from.rx_delay_base;
  else if (strcmp(key, "txdelay") == 0) p.tx_delay_factor = from.tx_delay_factor;
  else if (strcmp(key, "direct.txdelay") == 0) p.direct_tx_delay_factor = from.direct_tx_delay_factor;
  else if (strcmp(key, "agc.reset.interval") == 0) p.agc_reset_interval = from.agc_reset_interval;
  else if (strcmp(key, "multi.acks") == 0) p.multi_acks = from.multi_acks;
}

// Read back after a restore: every field exactly as it was.
inline bool same(const Snapshot& a, const Snapshot& b) {
  return a.airtime_factor == b.airtime_factor && a.rx_delay_base == b.rx_delay_base && a.tx_delay_factor == b.tx_delay_factor &&
         a.direct_tx_delay_factor == b.direct_tx_delay_factor && a.advert_interval == b.advert_interval &&
         a.flood_advert_interval == b.flood_advert_interval && a.flood_max == b.flood_max &&
         a.flood_max_unscoped == b.flood_max_unscoped && a.flood_max_advert == b.flood_max_advert &&
         a.agc_reset_interval == b.agc_reset_interval && a.multi_acks == b.multi_acks;
}

// A recursive lock: ESP32 uses a FreeRTOS recursive mutex (not a spinlock, because the section can
// include a flash write). Elsewhere it does nothing, unless a test defines UMC_TRIAL_STD_MUTEX.
class Lock {
public:
#if defined(ESP_PLATFORM)
  Lock() { _h = xSemaphoreCreateRecursiveMutex(); }
  void lock() { if (_h) xSemaphoreTakeRecursive(_h, portMAX_DELAY); }
  bool tryLock() { return _h == nullptr || xSemaphoreTakeRecursive(_h, 0) == pdTRUE; }
  void unlock() { if (_h) xSemaphoreGiveRecursive(_h); }
private:
  SemaphoreHandle_t _h = nullptr;
#elif defined(UMC_TRIAL_STD_MUTEX)
  void lock() { _m.lock(); }
  bool tryLock() { return _m.try_lock(); }
  void unlock() { _m.unlock(); }
private:
  std::recursive_mutex _m;
#else
  void lock() {}
  bool tryLock() { return true; }
  void unlock() {}
#endif
  Lock(const Lock&) = delete;
  Lock& operator=(const Lock&) = delete;
#if !defined(ESP_PLATFORM)
public:
  Lock() {}
#endif
};

class Guard {
public:
  explicit Guard(Lock& l) : _l(l) { _l.lock(); }
  ~Guard() { _l.unlock(); }
  Guard(const Guard&) = delete;
  Guard& operator=(const Guard&) = delete;
private:
  Lock& _l;
};

// Everything one node needs for trials: the lock, the timer, the originals and the "applying" flag
// (true while the trial value is being applied: the CLI's own save is skipped). All of it is touched
// only with `lock` held, by the free functions below.
struct Controller {
  Lock lock;
  Trial trial;
  Snapshot snap;
  bool applying = false;
};

// `rearm(local, flood)` is the node's updateAdvertTimer()/updateFloodAdvertTimer(); it is called after
// values have changed under the advert timers.
template <class P, class Rearm> inline bool undoLocked(Controller& c, P& p, Rearm rearm) {
  if (!c.trial.active()) return true;
  char key[28];
  strncpy(key, c.trial.key(), sizeof(key) - 1);
  key[sizeof(key) - 1] = 0;
  Snapshot live;
  capture(p, live);
  restore(p, c.snap);
  const bool timers = live.advert_interval != c.snap.advert_interval || live.flood_advert_interval != c.snap.flood_advert_interval ||
                      strcmp(key, "advert.interval") == 0 || strcmp(key, "flood.advert.interval") == 0;
  if (timers) rearm(true, true);   // both: the CLI's side effects may have moved either
  Snapshot back;
  capture(p, back);
  const bool ok = same(back, c.snap);
  c.trial.finish();
  return ok;
}

// Put the old values back (live only), read them back, end the trial. false: the read-back differed.
template <class P, class Rearm> inline bool undo(Controller& c, P& p, Rearm rearm) {
  Guard g(c.lock);
  return undoLocked(c, p, rearm);
}

// Timer check from the loop task. Never waits for the lock (a web command may hold it across a flash
// write): if it is busy this returns false and the next loop pass tries again. true: a trial was
// ended by the timer; *ok says whether the read-back matched.
template <class P, class Rearm> inline bool expire(Controller& c, P& p, uint32_t now_ms, Rearm rearm, bool* ok = nullptr) {
  if (!c.lock.tryLock()) return false;
  bool did = false;
  if (c.trial.expired(now_ms)) {
    const bool r = undoLocked(c, p, rearm);
    if (ok) *ok = r;
    did = true;
  }
  c.lock.unlock();
  return did;
}

// Start a trial. `apply()` runs the ordinary `set <key> <value>` code and returns true if it said OK; it
// is called with c.applying set so its save is skipped. On any failure everything is put back.
template <class P, class Apply, class Rearm>
inline Result start(Controller& c, P& p, uint32_t now_ms, const Args& a, Apply apply, Rearm rearm) {
  Guard g(c.lock);
  if (c.trial.active()) return TR_BUSY;
  capture(p, c.snap);
  c.applying = true;
  const bool ok = apply();
  c.applying = false;
  Snapshot live;
  capture(p, live);
  restore(p, c.snap);                 // everything back ...
  if (!ok) return TR_APPLY;
  copyKeyField(p, live, a.key);       // ... except the trialled value (the CLI's save-time tidying never sticks)
  const Result r = c.trial.begin(now_ms, a.secs, a.key);
  if (r != TR_OK) {                   // could not start the timer: nothing may stay changed
    Snapshot after;
    capture(p, after);
    restore(p, c.snap);
    if (after.advert_interval != c.snap.advert_interval || after.flood_advert_interval != c.snap.flood_advert_interval ||
        strcmp(a.key, "advert.interval") == 0 || strcmp(a.key, "flood.advert.interval") == 0)
      rearm(true, true);
    return r;
  }
  return TR_OK;
}

// `tryset keep`: end the trial, then `save()` writes the live values the way a plain `set` does.
template <class Save> inline Result keep(Controller& c, Save save) {
  Guard g(c.lock);
  if (!c.trial.active()) return TR_NONE;
  c.trial.finish();   // ended first, so the save below writes the live (trial) values
  save();
  return TR_OK;
}

// MyMesh::savePrefs: while a trial runs, write the original values and put the trial value back.
template <class P, class Write> inline void save(Controller& c, P& p, Write write) {
  Guard g(c.lock);
  if (c.applying) return;                       // a trial value is live only: never written
  if (!c.trial.active()) { write(); return; }
  Snapshot live;
  capture(p, live);
  restore(p, c.snap);
  write();
  restore(p, live);
}

inline bool startsWith(const char* s, const char* prefix) { return strncmp(s, prefix, strlen(prefix)) == 0; }
inline bool isTryset(const char* cmd) { return strcmp(cmd, "tryset") == 0 || startsWith(cmd, "tryset "); }
inline bool isSet(const char* cmd) { return startsWith(cmd, "set "); }

// The key of a `set <key> <value>` command, as a trial would name it ("" if none)
inline void setKey(const char* cmd, char* out, size_t cap) {
  out[0] = 0;
  if (!isSet(cmd) || cap == 0) return;
  const char* s = cmd + 4;
  while (*s == ' ') s++;
  size_t n = 0;
  while (s[n] != 0 && s[n] != ' ' && n + 1 < cap) { out[n] = s[n]; n++; }
  out[n] = 0;
}

// Around the start of `handleCommand` for `set ...` and `tryset ...`: takes the lock for the whole
// command, so a keep, revert, expiry or second tryset cannot run between the checks and the work.
// While a trial runs, `set` is refused for the settings in the snapshot (the whitelist) and allowed for
// anything else; after an allowed `set` the snapshot fields are put back as they were, so the CLI's
// save-time tidying of advert_interval cannot leak into the trial's live values.
template <class P> class SetScope {
public:
  SetScope(Controller& c, P& p, const char* cmd) : _c(c), _p(p) {
    _held = isSet(cmd) || isTryset(cmd);
    if (!_held) return;
    _c.lock.lock();
    if (isSet(cmd) && !_c.applying && _c.trial.active()) {
      char key[28];
      setKey(cmd, key, sizeof(key));
      // a key that is too long for the buffer cannot be one of ours; anything starting like one is refused
      if (keyAllowed(key)) { _refused = true; return; }
      capture(_p, _before);
      _restore = true;
    }
  }
  ~SetScope() {
    if (!_held) return;
    if (_restore) umctrial::restore(_p, _before);
    _c.lock.unlock();
  }
  bool refused() const { return _refused; }
  SetScope(const SetScope&) = delete;
  SetScope& operator=(const SetScope&) = delete;
private:
  Controller& _c;
  P& _p;
  Snapshot _before;
  bool _held = false, _refused = false, _restore = false;
};

}  // namespace umctrial
