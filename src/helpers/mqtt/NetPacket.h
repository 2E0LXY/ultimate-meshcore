#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <strings.h>

// Reading what other repeaters publish on a UMC Net broker (see mqtt.custom.bridge). Plain
// functions with no hardware in them, so they are tested on a computer (test/test_net_packet).
namespace umcnet {

inline int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// The packet bytes from the observer JSON {"origin":..,"data":"<hex>"}. Returns the length in
// bytes, or 0 when there is no usable "data" (missing, not hex, shorter than two bytes).
inline int packetFromRawJson(const char* json, int json_len, uint8_t* out, int out_max) {
  static const char kKey[] = "\"data\":\"";
  const int klen = (int)sizeof(kKey) - 1;
  if (json == nullptr || out == nullptr || json_len <= klen) return 0;
  const char* p = nullptr;
  for (int i = 0; i + klen < json_len; i++) {
    if (memcmp(json + i, kKey, klen) == 0) {
      p = json + i + klen;
      break;
    }
  }
  if (p == nullptr) return 0;
  const char* end = json + json_len;
  int n = 0;
  while (p + 1 < end && n < out_max) {
    const int hi = hexNibble(p[0]), lo = hexNibble(p[1]);
    if (hi < 0 || lo < 0) break;
    out[n++] = (uint8_t)((hi << 4) | lo);
    p += 2;
  }
  return n >= 2 ? n : 0;
}

// meshcore/<area>/<id>/raw ?
inline bool topicIsRaw(const char* topic, int topic_len) {
  return topic != nullptr && topic_len >= 5 && memcmp(topic + topic_len - 4, "/raw", 4) == 0;
}

// Does the topic carry this device's own id? (Our own packets come back on the subscription.)
inline bool topicHasId(const char* topic, int topic_len, const char* device_id) {
  if (topic == nullptr || device_id == nullptr) return false;
  const int id_len = (int)strlen(device_id);
  if (id_len == 0) return false;
  for (int i = 0; i + id_len <= topic_len; i++) {
    if (strncasecmp(topic + i, device_id, id_len) == 0) return true;
  }
  return false;
}

}  // namespace umcnet
