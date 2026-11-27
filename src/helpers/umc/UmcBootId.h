#pragma once
#include <stdint.h>
#include <stdio.h>

#if defined(ESP_PLATFORM)
  #include <esp_system.h>
#elif defined(__unix__) || defined(__APPLE__)
  #include <random>
#endif

// A random 64-bit number chosen once each time the node starts, sent as "boot_id" (a 16-character hex string, never a JSON number) in the
// MQTT status and telemetry. The dashboard uses a change of boot_id to tell a reboot from a gap in the
// reports. Not stored, not derived from the device identity or any address, so it says nothing about who
// or where the node is. Plain code, tested on a computer (test/test_boot_id).
namespace umcboot {

typedef uint32_t (*RngFn)();   // 32 random bits a call; two calls make the 64-bit id

inline uint32_t defaultRng() {
#if defined(ESP_PLATFORM)
  return esp_random();
#elif defined(__unix__) || defined(__APPLE__)
  static std::random_device rd;
  return (uint32_t)rd();
#else
  static uint32_t x = 0x9E3779B9u;   // no hardware RNG known: a fixed-seed sequence, still different each call
  x ^= x << 13; x ^= x >> 17; x ^= x << 5;
  return x;
#endif
}

struct State {
  uint64_t id = 0;
  bool have = false;
};
inline State& state() { static State s; return s; }

// The id for this run: made on first use, the same afterwards. `rng` is for tests.
inline uint64_t bootId(RngFn rng = nullptr) {
  State& s = state();
  if (!s.have) {
    RngFn f = rng ? rng : defaultRng;
    const uint64_t hi = f();
    s.id = (hi << 32) | f();
    s.have = true;
  }
  return s.id;
}

inline void resetForTest() { state() = State(); }

// out needs 17 bytes
inline void toHex(uint64_t id, char* out) { snprintf(out, 17, "%08X%08X", (unsigned)(id >> 32), (unsigned)(id & 0xFFFFFFFFu)); }

}  // namespace umcboot
