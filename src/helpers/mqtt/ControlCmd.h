#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

// Remote control of a repeater through its UMC Net broker (mqtt.control). Everything here is plain
// code with no hardware in it, so it is tested on a computer (test/test_control_cmd):
//   - SHA-256 and HMAC-SHA-256, so a command can be proved to come from whoever holds the key
//   - reading the few fields of a command message
//   - structural checks for the single CLI command carried in each control message
// A command message is {"id":"..","ts":<epoch seconds>,"n":<counter>,"cmd":"..","sig":"<64 hex>"}
// where sig = HMAC-SHA256(key, "<device id>|<ts>|<n>|<cmd>").
namespace umcctl {

struct Sha256 {
  uint32_t h[8];
  uint8_t buf[64];
  uint64_t total;
  size_t fill;
  static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
  void init() {
    static const uint32_t iv[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(h, iv, sizeof(h));
    total = 0;
    fill = 0;
  }
  void block(const uint8_t* p) {
    static const uint32_t k[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be,
        0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa,
        0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85,
        0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
        0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
        0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
    uint32_t w[64];
    for (int i = 0; i < 16; i++) w[i] = ((uint32_t)p[i * 4] << 24) | ((uint32_t)p[i * 4 + 1] << 16) | ((uint32_t)p[i * 4 + 2] << 8) | p[i * 4 + 3];
    for (int i = 16; i < 64; i++) {
      const uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
      const uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; i++) {
      const uint32_t t1 = hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + k[i] + w[i];
      const uint32_t t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
      hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
  }
  void update(const uint8_t* p, size_t n) {
    total += n;
    while (n > 0) {
      const size_t take = (64 - fill) < n ? (64 - fill) : n;
      memcpy(buf + fill, p, take);
      fill += take; p += take; n -= take;
      if (fill == 64) { block(buf); fill = 0; }
    }
  }
  void final(uint8_t out[32]) {
    const uint64_t bits = total * 8;
    const uint8_t one = 0x80, zero = 0;
    update(&one, 1);
    while (fill != 56) update(&zero, 1);
    uint8_t len[8];
    for (int i = 0; i < 8; i++) len[i] = (uint8_t)(bits >> (56 - 8 * i));
    update(len, 8);
    for (int i = 0; i < 8; i++) { out[i * 4] = h[i] >> 24; out[i * 4 + 1] = h[i] >> 16; out[i * 4 + 2] = h[i] >> 8; out[i * 4 + 3] = h[i]; }
  }
};

inline void hmacSha256(const uint8_t* key, size_t klen, const uint8_t* msg, size_t mlen, uint8_t out[32]) {
  uint8_t k[64] = {0};
  if (klen > 64) { Sha256 s; s.init(); s.update(key, klen); s.final(k); } else memcpy(k, key, klen);
  uint8_t ipad[64], opad[64];
  for (int i = 0; i < 64; i++) { ipad[i] = k[i] ^ 0x36; opad[i] = k[i] ^ 0x5c; }
  uint8_t inner[32];
  Sha256 a; a.init(); a.update(ipad, 64); a.update(msg, mlen); a.final(inner);
  Sha256 b; b.init(); b.update(opad, 64); b.update(inner, 32); b.final(out);
}

inline int nibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}
// 64 hex characters -> 32 bytes; false for anything else
inline bool keyFromHex(const char* hex, uint8_t out[32]) {
  if (hex == nullptr || strlen(hex) != 64) return false;
  for (int i = 0; i < 32; i++) {
    const int a = nibble(hex[i * 2]), b = nibble(hex[i * 2 + 1]);
    if (a < 0 || b < 0) return false;
    out[i] = (uint8_t)(a * 16 + b);
  }
  return true;
}
inline void toHex(const uint8_t* in, size_t n, char* out) {
  static const char d[] = "0123456789abcdef";
  for (size_t i = 0; i < n; i++) { out[i * 2] = d[in[i] >> 4]; out[i * 2 + 1] = d[in[i] & 15]; }
  out[n * 2] = 0;
}

// The signature a command must carry, as 64 lowercase hex characters.
inline void signature(const uint8_t key[32], const char* device_id, uint64_t ts, uint64_t n, const char* cmd, char out[65]) {
  char msg[300];
  const int len = snprintf(msg, sizeof(msg), "%s|%llu|%llu|%s", device_id, (unsigned long long)ts, (unsigned long long)n, cmd);
  uint8_t mac[32];
  hmacSha256(key, 32, (const uint8_t*)msg, len > 0 ? (size_t)len : 0, mac);
  toHex(mac, 32, out);
}
// Same length, no early exit
inline bool sameSignature(const char* a, const char* b) {
  if (a == nullptr || b == nullptr || strlen(a) != 64 || strlen(b) != 64) return false;
  uint8_t diff = 0;
  for (int i = 0; i < 64; i++) diff |= (uint8_t)(a[i] ^ b[i]);
  return diff == 0;
}

// "key":"value" with no escapes (a value with a backslash is refused rather than guessed at)
inline bool jsonString(const char* json, int len, const char* key, char* out, size_t out_max) {
  char pat[24];
  const int pl = snprintf(pat, sizeof(pat), "\"%s\":\"", key);
  if (json == nullptr || out == nullptr || out_max == 0 || pl <= 0) return false;
  for (int i = 0; i + pl < len; i++) {
    if (memcmp(json + i, pat, pl) != 0) continue;
    size_t o = 0;
    for (int j = i + pl; j < len; j++) {
      if (json[j] == '"') { out[o] = 0; return true; }
      if (json[j] == '\\' || (uint8_t)json[j] < 0x20 || o + 1 >= out_max) return false;
      out[o++] = json[j];
    }
    return false;
  }
  return false;
}
// "key":123
inline bool jsonNumber(const char* json, int len, const char* key, uint64_t* out) {
  char pat[24];
  const int pl = snprintf(pat, sizeof(pat), "\"%s\":", key);
  if (json == nullptr || out == nullptr || pl <= 0) return false;
  for (int i = 0; i + pl < len; i++) {
    if (memcmp(json + i, pat, pl) != 0) continue;
    uint64_t v = 0;
    int digits = 0;
    for (int j = i + pl; j < len && json[j] >= '0' && json[j] <= '9' && digits < 19; j++, digits++) v = v * 10 + (uint64_t)(json[j] - '0');
    if (digits == 0) return false;
    *out = v;
    return true;
  }
  return false;
}

// A signed UMC Net administrator may run the full device CLI.  This function is therefore a
// transport-shape check, not an allow-list: signatures, freshness, replay protection and the
// per-device rate limit are still enforced before a command reaches the CLI.  Keep line breaks,
// JSON quoting tricks and overlong input out of the single-command control message.
inline bool commandAllowed(const char* cmd) {
  if (cmd == nullptr || cmd[0] == 0) return false;
  const size_t n = strlen(cmd);
  if (n > 140 || cmd[0] == ' ' || cmd[n - 1] == ' ') return false;
  for (size_t i = 0; i < n; i++) {
    const uint8_t c = (uint8_t)cmd[i];
    if (c < 0x20 || c == 0x7f || c == '"' || c == '\\') return false;     // no line breaks, no quoting tricks
  }
  return true;
}

}  // namespace umcctl
