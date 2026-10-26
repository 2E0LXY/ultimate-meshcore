#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "ControlCmd.h"

// A UMC Net join code: everything a repeater needs to join your network, in one short line the
// dashboard makes and `set mqtt.join <code>` applies. Plain code with no hardware in it, so it is
// tested on a computer (test/test_join_code).
//
//   "UMC1." + base64url( version(1)=1  flags(1)  area(3)  user_len user  pass_len pass
//                        [host_len host port(2, big endian)]  [control key(32)]  check(3) )
//   flags: 1 = has a control key, 2 = switch the bridge on, 4 = has a host and port
//   check: the first 3 bytes of SHA-256 of everything before it, so a damaged copy is refused
namespace umcjoin {

struct Join {
  char iata[4];
  char user[25];
  char pass[41];
  char host[64];
  uint16_t port;
  bool has_host;
  bool has_key;
  uint8_t key[32];
  bool bridge;
};

inline int b64val(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '-') return 62;
  if (c == '_') return 63;
  return -1;
}

// base64url without padding
inline bool b64urlDecode(const char* s, uint8_t* out, size_t max, size_t* n) {
  size_t o = 0;
  uint32_t acc = 0;
  int bits = 0;
  for (; *s; s++) {
    const int v = b64val(*s);
    if (v < 0) return false;
    acc = (acc << 6) | (uint32_t)v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      if (o >= max) return false;
      out[o++] = (uint8_t)(acc >> bits);
      acc &= (1u << bits) - 1;
    }
  }
  if (bits >= 6) return false;      // a stray character left over
  *n = o;
  return true;
}

inline bool printableNoSpace(const char* s, size_t n) {
  for (size_t i = 0; i < n; i++)
    if ((uint8_t)s[i] < 0x21 || (uint8_t)s[i] > 0x7e) return false;
  return true;
}

// false for anything that is not a complete, undamaged code
inline bool parse(const char* code, Join* j) {
  if (code == nullptr || j == nullptr || strncmp(code, "UMC1.", 5) != 0) return false;
  uint8_t b[140];
  size_t n = 0;
  if (!b64urlDecode(code + 5, b, sizeof(b), &n) || n < 2 + 3 + 1 + 1 + 1 + 1 + 3) return false;
  uint8_t sum[32];
  umcctl::Sha256 h;
  h.init();
  h.update(b, n - 3);
  h.final(sum);
  uint8_t diff = 0;
  for (int i = 0; i < 3; i++) diff |= (uint8_t)(sum[i] ^ b[n - 3 + i]);
  if (diff != 0) return false;
  const size_t end = n - 3;
  if (b[0] != 1) return false;
  const uint8_t flags = b[1];
  memset(j, 0, sizeof(*j));
  size_t i = 2;
  if (i + 3 > end) return false;
  memcpy(j->iata, &b[i], 3);
  j->iata[3] = 0;
  for (int k = 0; k < 3; k++)
    if (!((j->iata[k] >= 'A' && j->iata[k] <= 'Z') || (j->iata[k] >= '0' && j->iata[k] <= '9'))) return false;
  i += 3;
  if (i >= end) return false;
  const size_t ul = b[i++];
  if (ul < 2 || ul > 24 || i + ul > end) return false;
  memcpy(j->user, &b[i], ul);
  i += ul;
  if (i >= end) return false;
  const size_t pl = b[i++];
  if (pl < 8 || pl > 40 || i + pl > end) return false;
  memcpy(j->pass, &b[i], pl);
  i += pl;
  if (!printableNoSpace(j->user, ul) || !printableNoSpace(j->pass, pl)) return false;
  if (flags & 4) {
    if (i >= end) return false;
    const size_t hl = b[i++];
    if (hl < 3 || hl > 63 || i + hl + 2 > end) return false;
    memcpy(j->host, &b[i], hl);
    i += hl;
    if (!printableNoSpace(j->host, hl)) return false;
    j->port = (uint16_t)((b[i] << 8) | b[i + 1]);
    i += 2;
    if (j->port == 0) return false;
    j->has_host = true;
  }
  if (flags & 1) {
    if (i + 32 > end) return false;
    memcpy(j->key, &b[i], 32);
    i += 32;
    j->has_key = true;
  }
  if (i != end) return false;       // nothing may be left over
  j->bridge = (flags & 2) != 0;
  return true;
}

}  // namespace umcjoin
