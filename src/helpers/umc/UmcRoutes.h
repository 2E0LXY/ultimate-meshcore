#pragma once

#include <Arduino.h>
#include <Mesh.h>
#include <helpers/AdvertDataHelpers.h>
#include <string.h>

#if defined(ESP_PLATFORM)
  #include <freertos/FreeRTOS.h>
#endif

// Route table learned from received adverts: for every node heard, the chain of
// repeaters its advert travelled through to reach us (reverse it for a route to the node),
// plus an optional pinned (manually added) route. Also holds the state of the last trace.
//
// Written on the mesh loop task; the web server copies entries under a spinlock.
class UmcRoutes {
public:
  static constexpr int kMaxRoutes = 48;
  static constexpr int kMaxPathBytes = 24;   // up to 24 hops at 1-byte hashes
  static constexpr int kKeyBytes = 6;

  struct Route {
    uint8_t key[kKeyBytes];
    char name[24];
    uint8_t type;            // ADV_TYPE_*
    uint8_t hash_size;       // bytes per hop in path
    uint8_t path_len;        // bytes in path
    uint8_t path[kMaxPathBytes];
    uint8_t pin_len;         // bytes in pinned path (0 = none), uses hash_size 1
    uint8_t pin[kMaxPathBytes];
    int8_t snr4;
    int16_t rssi;
    uint32_t heard_ms;
    uint32_t heard_epoch;    // RTC time heard (survives reboots via save/load)
    uint32_t adverts;
    bool has_loc;
    float lat, lon;
    bool used;
  };

  struct Trace {
    enum State : uint8_t { Idle, Waiting, Done, Timeout } state;
    uint32_t tag;
    uint32_t sent_ms;
    uint32_t done_ms;
    uint8_t hash_size;
    uint8_t path_len;                 // bytes
    uint8_t path[kMaxPathBytes];
    uint8_t snr_count;
    int8_t snr4[kMaxPathBytes + 1];   // per hop, then final (to us)
  };

  void onAdvert(const mesh::Packet* pkt, const mesh::Identity& id, const uint8_t* app_data, size_t app_len, uint32_t epoch) {
    AdvertDataParser parser(app_data, app_len);
    lock();
    Route* r = find(id.pub_key, kKeyBytes);
    if (r == nullptr) r = allocate();
    memcpy(r->key, id.pub_key, kKeyBytes);
    if (parser.isValid()) {
      if (parser.hasName()) {
        strncpy(r->name, parser.getName(), sizeof(r->name) - 1);
        r->name[sizeof(r->name) - 1] = 0;
      }
      r->type = parser.getType();
      r->has_loc = parser.hasLatLon();
      if (r->has_loc) {
        r->lat = static_cast<float>(parser.getLat());
        r->lon = static_cast<float>(parser.getLon());
      }
    }
    uint8_t bytes = pkt->getPathByteLen();
    if (bytes > kMaxPathBytes) bytes = kMaxPathBytes;
    r->hash_size = pkt->getPathHashSize();
    r->path_len = bytes;
    memcpy(r->path, pkt->path, bytes);
    r->snr4 = static_cast<int8_t>(constrain(pkt->getSNR() * 4.0f, -128.0f, 127.0f));
    r->heard_ms = millis();
    r->heard_epoch = epoch;
    r->adverts++;
    r->used = true;
    _dirty = true;
    unlock();
  }

  // copy entry i (0..kMaxRoutes-1); returns false when unused
  bool copy(int i, Route& out) {
    lock();
    bool ok = i >= 0 && i < kMaxRoutes && _routes[i].used;
    if (ok) out = _routes[i];
    unlock();
    return ok;
  }

  int count() const {
    int n = 0;
    for (const auto& r : _routes) n += r.used ? 1 : 0;
    return n;
  }

  // prefix = hex string (2..12 chars)
  Route* findHex(const char* hex) {
    uint8_t key[kKeyBytes];
    int n = parseHex(hex, key, kKeyBytes);
    return n > 0 ? find(key, n) : nullptr;
  }

  // case-insensitive name search or key prefix; returns index or -1, starting after `after`
  int search(const char* text, int after = -1) {
    uint8_t key[kKeyBytes];
    int n = parseHex(text, key, kKeyBytes);
    for (int i = after + 1; i < kMaxRoutes; i++) {
      const Route& r = _routes[i];
      if (!r.used) continue;
      if (n > 0 && memcmp(r.key, key, n) == 0) return i;
      if (containsNoCase(r.name, text)) return i;
    }
    return -1;
  }

  bool setPin(Route* r, const uint8_t* path, uint8_t len) {
    if (r == nullptr || len > kMaxPathBytes) return false;
    lock();
    if (len) memcpy(r->pin, path, len);
    r->pin_len = len;
    _dirty = true;
    unlock();
    return true;
  }

  void forget(Route* r) {
    if (r == nullptr) return;
    lock();
    memset(r, 0, sizeof(*r));
    _dirty = true;
    unlock();
  }

  bool dirty() const { return _dirty; }

  // Persist the table (names, routes, pins) so it survives reboots.
  template <typename FS_T>
  bool save(FS_T* fs) {
    if (fs == nullptr) return false;
    auto file = fs->open(kFile, "w", true);
    if (!file) return false;
    const uint32_t magic = kMagic;
    const uint16_t entry_size = sizeof(Route);
    file.write(static_cast<const uint8_t*>(static_cast<const void*>(&magic)), 4);
    file.write(static_cast<const uint8_t*>(static_cast<const void*>(&entry_size)), 2);
    Route r;
    for (int i = 0; i < kMaxRoutes; i++) {
      if (!copy(i, r)) continue;
      file.write(static_cast<const uint8_t*>(static_cast<const void*>(&r)), sizeof(r));
    }
    file.close();
    _dirty = false;
    return true;
  }

  template <typename FS_T>
  bool load(FS_T* fs) {
    if (fs == nullptr || !fs->exists(kFile)) return false;
    auto file = fs->open(kFile, "r");
    if (!file) return false;
    uint32_t magic = 0;
    uint16_t entry_size = 0;
    bool ok = file.read(static_cast<uint8_t*>(static_cast<void*>(&magic)), 4) == 4 &&
              file.read(static_cast<uint8_t*>(static_cast<void*>(&entry_size)), 2) == 2 && magic == kMagic &&
              entry_size == sizeof(Route);
    int n = 0;
    while (ok && n < kMaxRoutes && file.available() >= static_cast<int>(sizeof(Route))) {
      Route r;
      if (file.read(static_cast<uint8_t*>(static_cast<void*>(&r)), sizeof(r)) != sizeof(r)) break;
      if (!r.used) continue;
      r.heard_ms = 0;  // unknown this session: age comes from heard_epoch
      _routes[n++] = r;
    }
    file.close();
    return n > 0;
  }
  Trace& trace() { return _trace; }

  void traceResult(uint32_t tag, const uint8_t* snrs, uint8_t count, int8_t final_snr4) {
    if (_trace.state != Trace::Waiting || tag != _trace.tag) return;
    lock();
    _trace.snr_count = count > kMaxPathBytes ? kMaxPathBytes : count;
    memcpy(_trace.snr4, snrs, _trace.snr_count);
    _trace.snr4[_trace.snr_count] = final_snr4;
    _trace.done_ms = millis();
    _trace.state = Trace::Done;
    unlock();
  }

  void loop() {
    if (_trace.state == Trace::Waiting && millis() - _trace.sent_ms > 30000) _trace.state = Trace::Timeout;
  }

  static int parseHex(const char* s, uint8_t* out, int max_bytes) {
    int n = 0;
    while (*s == ' ') s++;
    while (s[0] && s[1] && n < max_bytes) {
      int hi = hexVal(s[0]), lo = hexVal(s[1]);
      if (hi < 0 || lo < 0) break;
      out[n++] = static_cast<uint8_t>((hi << 4) | lo);
      s += 2;
    }
    if (*s && *s != ' ') return 0;  // not purely hex
    return n;
  }

  // "a1,b2,c3" or "a1b2 c3" -> bytes; returns byte count (0 on error)
  static int parsePath(const char* s, uint8_t* out, int max_bytes, int hash_size) {
    int n = 0;
    while (*s && n < max_bytes) {
      while (*s == ' ' || *s == ',' || *s == '-' || *s == '>') s++;
      if (!*s) break;
      for (int b = 0; b < hash_size; b++) {
        int hi = hexVal(s[0]), lo = s[0] ? hexVal(s[1]) : -1;
        if (hi < 0 || lo < 0 || n >= max_bytes) return 0;
        out[n++] = static_cast<uint8_t>((hi << 4) | lo);
        s += 2;
      }
    }
    return n;
  }

  static const char* typeName(uint8_t t) {
    switch (t) {
      case ADV_TYPE_CHAT: return "client";
      case ADV_TYPE_REPEATER: return "repeater";
      case ADV_TYPE_ROOM: return "room";
      case ADV_TYPE_SENSOR: return "sensor";
      default: return "node";
    }
  }

private:
  static int hexVal(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  }
  static bool containsNoCase(const char* hay, const char* needle) {
    if (!*needle) return false;
    for (; *hay; hay++) {
      const char* h = hay;
      const char* n = needle;
      while (*h && *n && tolower(static_cast<unsigned char>(*h)) == tolower(static_cast<unsigned char>(*n))) {
        h++;
        n++;
      }
      if (!*n) return true;
    }
    return false;
  }
  Route* find(const uint8_t* key, int n) {
    for (auto& r : _routes) {
      if (r.used && memcmp(r.key, key, n) == 0) return &r;
    }
    return nullptr;
  }
  Route* allocate() {
    Route* oldest = &_routes[0];
    for (auto& r : _routes) {
      if (!r.used) {
        memset(&r, 0, sizeof(r));
        return &r;
      }
      if (r.pin_len == 0 && (oldest->pin_len != 0 || r.heard_ms < oldest->heard_ms)) oldest = &r;
    }
    memset(oldest, 0, sizeof(*oldest));  // evict least recently heard unpinned route
    return oldest;
  }
#if defined(ESP_PLATFORM)
  void lock() { portENTER_CRITICAL(&_mux); }
  void unlock() { portEXIT_CRITICAL(&_mux); }
  portMUX_TYPE _mux = portMUX_INITIALIZER_UNLOCKED;
#else
  void lock() {}
  void unlock() {}
#endif

  static constexpr const char* kFile = "/umc_routes";
  static constexpr uint32_t kMagic = 0x31524D55;  // "UMR1"
  bool _dirty = false;
  Route _routes[kMaxRoutes] = {};
  Trace _trace = {};
};

extern UmcRoutes umc_routes;
