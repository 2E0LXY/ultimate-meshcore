#include "UmcHealth.h"

#include <Arduino.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "UmcVersion.h"

#if defined(ESP_PLATFORM)
  #include <Preferences.h>
  #include <esp_attr.h>
  #include <esp_system.h>
#endif

UmcHealth umc_health;

extern "C" void umc_health_note(const char* text) { umc_health.note(text); }

namespace {

constexpr size_t kLogMax = 1400;                 // bytes of log kept
constexpr unsigned long kSaveEveryMs = 600000UL;  // ten minutes
constexpr unsigned long kCrumbEveryMs = 5000UL;
constexpr uint32_t kMagic = 0x554D4331;           // "UMC1"

#if defined(ESP_PLATFORM)
// Survives a reset (a crash, a watchdog, a software restart) but not a power cut: what the
// last run looked like just before it ended.
struct Crumb {
  uint32_t magic;
  uint32_t uptime_s;
  uint32_t free_heap;
  uint32_t min_heap;
};
RTC_NOINIT_ATTR Crumb s_crumb;

const char* reasonName(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "power-on";
    case ESP_RST_EXT: return "reset pin";
    case ESP_RST_SW: return "software";
    case ESP_RST_PANIC: return "crash";
    case ESP_RST_INT_WDT: return "interrupt watchdog";
    case ESP_RST_TASK_WDT: return "task watchdog";
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_DEEPSLEEP: return "deep sleep";
    case ESP_RST_BROWNOUT: return "brown-out";
    default: return "unknown";
  }
}

bool abnormal(esp_reset_reason_t r) {
  return r == ESP_RST_PANIC || r == ESP_RST_INT_WDT || r == ESP_RST_TASK_WDT || r == ESP_RST_WDT ||
         r == ESP_RST_BROWNOUT;
}
#endif

void duration(uint32_t s, char* b, size_t n) {
  if (s >= 86400UL) snprintf(b, n, "%lud %luh", (unsigned long)(s / 86400UL), (unsigned long)((s % 86400UL) / 3600UL));
  else if (s >= 3600UL) snprintf(b, n, "%luh %lum", (unsigned long)(s / 3600UL), (unsigned long)((s % 3600UL) / 60UL));
  else snprintf(b, n, "%lum %lus", (unsigned long)(s / 60UL), (unsigned long)(s % 60UL));
}

void count(uint32_t v, char* b, size_t n) {
  if (v >= 10000000UL) snprintf(b, n, "%luM", (unsigned long)(v / 1000000UL));
  else if (v >= 1000000UL) snprintf(b, n, "%.1fM", v / 1000000.0f);
  else if (v >= 10000UL) snprintf(b, n, "%luk", (unsigned long)(v / 1000UL));
  else if (v >= 1000UL) snprintf(b, n, "%.1fk", v / 1000.0f);
  else snprintf(b, n, "%lu", (unsigned long)v);
}

}  // namespace

// ---------------------------------------------------------------- storage

void UmcHealth::load() {
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (!nvs.begin("umchealth", true)) return;
  _boots = nvs.getUInt("boots", 0);
  _crashes = nvs.getUInt("crashes", 0);
  _first_epoch = nvs.getUInt("first", 0);
  _longest = nvs.getUInt("longest", 0);
  _base_uptime = nvs.getUInt("uptime", 0);
  _base_rx = nvs.getUInt("rx", 0);
  _base_tx = nvs.getUInt("tx", 0);
  _saved_run_up = nvs.getUInt("runup", 0);
  nvs.end();
#endif
}

void UmcHealth::save(uint32_t rx, uint32_t tx) {
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (!nvs.begin("umchealth", false)) return;
  const uint32_t run_up = millis() / 1000UL;
  nvs.putUInt("boots", _boots);
  nvs.putUInt("crashes", _crashes);
  if (_first_epoch) nvs.putUInt("first", _first_epoch);
  if (run_up > _longest) _longest = run_up;
  nvs.putUInt("longest", _longest);
  nvs.putUInt("uptime", _base_uptime + run_up);
  nvs.putUInt("rx", _base_rx + rx);
  nvs.putUInt("tx", _base_tx + tx);
  nvs.putUInt("runup", run_up);
  nvs.end();
#else
  (void)rx;
  (void)tx;
#endif
}

void UmcHealth::readLog(char* out, size_t out_size) {
  out[0] = 0;
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (!nvs.begin("umchealth", true)) return;
  nvs.getString("log", out, out_size);
  nvs.end();
#else
  (void)out_size;
#endif
}

void UmcHealth::appendLog(const char* text) {
#if defined(ESP_PLATFORM)
  char line[120];
  if (_epoch > 1700000000UL) {
    time_t t = (time_t)_epoch;
    struct tm tm;
    gmtime_r(&t, &tm);
    snprintf(line, sizeof(line), "%02d-%02d %02d:%02d %s", tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, text);
  } else {
    snprintf(line, sizeof(line), "+%lus %s", (unsigned long)(millis() / 1000UL), text);
  }
  char all[kLogMax + 130];
  readLog(all, kLogMax + 1);
  size_t len = strlen(all);
  if (len + strlen(line) + 2 > kLogMax) {              // drop the oldest lines to make room
    size_t drop = len + strlen(line) + 2 - kLogMax;
    const char* nl = strchr(all + (drop < len ? drop : len), '\n');
    const char* keep = nl ? nl + 1 : all + len;
    memmove(all, keep, strlen(keep) + 1);
    len = strlen(all);
  }
  snprintf(all + len, sizeof(all) - len, "%s\n", line);
  Preferences nvs;
  if (nvs.begin("umchealth", false)) {
    nvs.putString("log", all);
    nvs.end();
  }
#else
  (void)text;
#endif
}

void UmcHealth::note(const char* text) {
  if (text == nullptr || text[0] == 0) return;
  appendLog(text);
}

// ---------------------------------------------------------------- life cycle

void UmcHealth::begin() {
  if (_begun) return;
  _begun = true;
#if defined(ESP_PLATFORM)
  const esp_reset_reason_t reason = esp_reset_reason();
  snprintf(_reason, sizeof(_reason), "%s", reasonName(reason));
  load();

  // What the run before this one looked like, if the reset kept RTC memory.
  const bool have_prev = s_crumb.magic == kMagic && reason != ESP_RST_POWERON;
  uint32_t prev_up = 0, prev_min = 0;
  if (have_prev) {
    prev_up = s_crumb.uptime_s;
    prev_min = s_crumb.min_heap;
    if (prev_up > _saved_run_up) _base_uptime += prev_up - _saved_run_up;   // the unsaved tail of that run
    if (prev_up > _longest) _longest = prev_up;
  }
  _boots++;
  if (abnormal(reason)) _crashes++;
  _saved_run_up = 0;

  char line[100];
  if (have_prev) {
    char d[16];
    duration(prev_up, d, sizeof(d));
    snprintf(line, sizeof(line), "boot v%s after %s, ran %s, min heap %luk%s", UMC_VERSION, _reason, d,
             (unsigned long)(prev_min / 1024UL), abnormal(reason) ? " !" : "");
  } else {
    snprintf(line, sizeof(line), "boot v%s after %s", UMC_VERSION, _reason);
  }
  appendLog(line);
  save(0, 0);

  s_crumb.magic = kMagic;
  s_crumb.uptime_s = 0;
  s_crumb.free_heap = ESP.getFreeHeap();
  s_crumb.min_heap = ESP.getMinFreeHeap();
#endif
  _last_save = millis();
  _last_crumb = millis();
}

void UmcHealth::breadcrumb(unsigned long now_ms) {
#if defined(ESP_PLATFORM)
  s_crumb.magic = kMagic;
  s_crumb.uptime_s = now_ms / 1000UL;
  s_crumb.free_heap = ESP.getFreeHeap();
  s_crumb.min_heap = ESP.getMinFreeHeap();
#else
  (void)now_ms;
#endif
}

void UmcHealth::loop(unsigned long now_ms, uint32_t rx, uint32_t tx) {
  if (!_begun) return;
  _last_rx = rx;
  _last_tx = tx;
  if (now_ms - _last_crumb >= kCrumbEveryMs) {
    _last_crumb = now_ms;
    breadcrumb(now_ms);
  }
  if (now_ms - _last_save >= kSaveEveryMs) {
    _last_save = now_ms;
    if (_first_epoch == 0 && _epoch > 1700000000UL) _first_epoch = _epoch;
    save(rx, tx);
  }
}

// ---------------------------------------------------------------- commands

bool UmcHealth::command(const char* command, char* reply, size_t reply_size) {
  if (command == nullptr || reply == nullptr || reply_size == 0) return false;

  if (strcmp(command, "stats-life") == 0) {
#if defined(ESP_PLATFORM)
    const uint32_t run_up = millis() / 1000UL;
    char up[16], best[16], rx[12], tx[12], since[40] = "";
    duration(_base_uptime + run_up, up, sizeof(up));
    duration(_longest > run_up ? _longest : run_up, best, sizeof(best));
    count(_base_rx + _last_rx, rx, sizeof(rx));
    count(_base_tx + _last_tx, tx, sizeof(tx));
    if (_first_epoch) {
      time_t t = (time_t)_first_epoch;
      struct tm tm;
      gmtime_r(&t, &tm);
      snprintf(since, sizeof(since), ", since %04d-%02d-%02d", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday);
    }
    snprintf(reply, reply_size, "Lifetime: %lu boots, %lu abnormal, up %s (best run %s), rx %s tx %s%s",
             (unsigned long)_boots, (unsigned long)_crashes, up, best, rx, tx, since);
#else
    snprintf(reply, reply_size, "not available on this build");
#endif
    return true;
  }
  if (strcmp(command, "stats-life clear") == 0) {
#if defined(ESP_PLATFORM)
    _boots = 1;
    _crashes = 0;
    _longest = 0;
    _first_epoch = _epoch > 1700000000UL ? _epoch : 0;
    _base_uptime = 0;
    _base_rx = 0;
    _base_tx = 0;
    _saved_run_up = 0;
    _last_save = millis();
    // the counters now run from this moment
    _base_uptime = (uint32_t)0 - millis() / 1000UL;
    _base_rx = (uint32_t)0 - _last_rx;
    _base_tx = (uint32_t)0 - _last_tx;
    save(_last_rx, _last_tx);
#endif
    snprintf(reply, reply_size, "OK - lifetime statistics cleared");
    return true;
  }

  if (strncmp(command, "safety", 6) != 0 || (command[6] != 0 && command[6] != ' ')) return false;
  const char* arg = command + 6;
  while (*arg == ' ') arg++;

  if (strcmp(arg, "clear") == 0) {
#if defined(ESP_PLATFORM)
    Preferences nvs;
    if (nvs.begin("umchealth", false)) {
      nvs.remove("log");
      nvs.end();
    }
#endif
    snprintf(reply, reply_size, "OK - safety log cleared");
    return true;
  }
  if (strcmp(arg, "state") == 0) {
#if defined(ESP_PLATFORM)
    char d[16];
    duration(millis() / 1000UL, d, sizeof(d));
    snprintf(reply, reply_size, "reset: %s | heap %luk free, %luk lowest | up %s | boots %lu", _reason,
             (unsigned long)(ESP.getFreeHeap() / 1024UL), (unsigned long)(ESP.getMinFreeHeap() / 1024UL), d,
             (unsigned long)_boots);
#else
    snprintf(reply, reply_size, "not available on this build");
#endif
    return true;
  }

  // safety, safety log [N], safety tail
  int want = 3;
  if (strcmp(arg, "tail") == 0) want = 1;
  else if (strncmp(arg, "log", 3) == 0 && arg[3] == ' ') want = atoi(arg + 4) > 0 ? atoi(arg + 4) : 3;
  else if (arg[0] != 0 && strcmp(arg, "log") != 0) return false;
  if (want > 12) want = 12;

  char all[kLogMax + 8];
  readLog(all, sizeof(all));
  if (all[0] == 0) {
    snprintf(reply, reply_size, "safety log is empty");
    return true;
  }
  // the last `want` lines, oldest first, separated by " | "
  int lines = 0;
  for (const char* p = all; *p; p++) if (*p == '\n') lines++;
  int skip = lines > want ? lines - want : 0;
  const char* start = all;
  while (skip > 0 && *start) {
    const char* nl = strchr(start, '\n');
    if (!nl) break;
    start = nl + 1;
    skip--;
  }
  size_t o = 0;
  for (const char* p = start; *p && o + 4 < reply_size; p++) {
    if (*p == '\n') {
      if (*(p + 1) == 0) break;
      if (o + 4 < reply_size) { reply[o++] = ' '; reply[o++] = '|'; reply[o++] = ' '; }
    } else {
      reply[o++] = *p;
    }
  }
  reply[o] = 0;
  if (o + 4 >= reply_size && o >= 3) { reply[o - 3] = '.'; reply[o - 2] = '.'; reply[o - 1] = '.'; }
  return true;
}
