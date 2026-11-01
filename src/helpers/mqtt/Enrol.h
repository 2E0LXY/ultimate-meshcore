#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ControlCmd.h"
#include "JoinCode.h"

// Zero-touch enrolment, the repeater's half (see docs/umc/ENROL.md; the server half is umcnet_enrol.py).
//
// A repeater switched to "join UMC Net" without an account connects to the broker as the public `enrol`
// account, sends a request signed with its own identity key, and waits. When the owner approves it on the
// dashboard, a grant arrives on umcnet/v1/enrol/grant/<ID>: a join code encrypted to this repeater's key,
// so nobody else can read it. Pure code with no hardware in it, so it is tested on a computer.
//
//   grant text = base64url( 0x01 | eph(32) | nonce(12) | ciphertext | tag(16) )
//   shared     = X25519 between this repeater's identity key and the server's one-time key `eph`
//                (the firmware's ed25519_key_exchange(shared, eph, private_key) gives exactly this)
//   key        = HMAC-SHA256(shared, "UMC-ENROL1 key" | device public key | eph)
//   keystream  = HMAC-SHA256(key, "ks" | nonce | counter u32 big endian) blocks, XORed with the plaintext
//   tag        = first 16 bytes of HMAC-SHA256(key, "mac" | nonce | ciphertext)
namespace umcenrol {

static const char kTopicHello[] = "umcnet/v1/enrol/hello";

struct Grant {
  uint8_t eph[32];
  uint8_t nonce[12];
  uint8_t ct[160];
  size_t ct_len;
  uint8_t tag[16];
};

// "UMC-ENROL1|<ID>|<ts>|<nonce>": what the repeater signs
inline size_t helloMessage(const char* id_hex, uint32_t ts, const char* nonce, char* out, size_t max) {
  const int n = snprintf(out, max, "UMC-ENROL1|%s|%lu|%s", id_hex, (unsigned long)ts, nonce);
  return (n < 0 || (size_t)n >= max) ? 0 : (size_t)n;
}

// the request published on kTopicHello (name and board are cleaned so the JSON stays valid)
inline size_t helloJson(const char* id_hex, const char* name, const char* fw, const char* board, uint32_t ts, const char* nonce,
                        const char* sig_hex, char* out, size_t max) {
  char nm[40], bd[40];
  size_t j = 0;
  for (const char* p = name; *p && j + 1 < sizeof(nm); p++)
    if ((uint8_t)*p >= 0x20 && (uint8_t)*p < 0x7f && *p != '"' && *p != '\\') nm[j++] = *p;
  nm[j] = 0;
  j = 0;
  for (const char* p = board; *p && j + 1 < sizeof(bd); p++)
    if ((uint8_t)*p >= 0x20 && (uint8_t)*p < 0x7f && *p != '"' && *p != '\\') bd[j++] = *p;
  bd[j] = 0;
  const int n = snprintf(out, max, "{\"v\":1,\"id\":\"%s\",\"name\":\"%s\",\"fw\":\"%s\",\"bd\":\"%s\",\"ts\":%lu,\"nc\":\"%s\",\"sig\":\"%s\"}", id_hex, nm, fw,
                         bd, (unsigned long)ts, nonce, sig_hex);
  return (n < 0 || (size_t)n >= max) ? 0 : (size_t)n;
}

inline bool parseGrant(const char* text, Grant* g) {
  if (text == nullptr || g == nullptr) return false;
  uint8_t raw[1 + 32 + 12 + sizeof(g->ct) + 16];
  size_t n = 0;
  if (!umcjoin::b64urlDecode(text, raw, sizeof(raw), &n) || n < 1 + 32 + 12 + 16 + 1 || raw[0] != 1) return false;
  g->ct_len = n - (1 + 32 + 12 + 16);
  memcpy(g->eph, &raw[1], 32);
  memcpy(g->nonce, &raw[33], 12);
  memcpy(g->ct, &raw[45], g->ct_len);
  memcpy(g->tag, &raw[45 + g->ct_len], 16);
  return true;
}

// Checks the tag and decrypts. `out` is NUL-terminated; false (and nothing written) if the tag does not match.
inline bool openGrant(const Grant& g, const uint8_t shared[32], const uint8_t dev_pub[32], char* out, size_t out_max) {
  if (g.ct_len + 1 > out_max) return false;
  uint8_t msg[14 + 32 + 32];
  memcpy(msg, "UMC-ENROL1 key", 14);
  memcpy(&msg[14], dev_pub, 32);
  memcpy(&msg[46], g.eph, 32);
  uint8_t key[32];
  umcctl::hmacSha256(shared, 32, msg, sizeof(msg), key);

  uint8_t macmsg[3 + 12 + sizeof(g.ct)];
  memcpy(macmsg, "mac", 3);
  memcpy(&macmsg[3], g.nonce, 12);
  memcpy(&macmsg[15], g.ct, g.ct_len);
  uint8_t mac[32];
  umcctl::hmacSha256(key, 32, macmsg, 15 + g.ct_len, mac);
  uint8_t diff = 0;
  for (int i = 0; i < 16; i++) diff |= (uint8_t)(mac[i] ^ g.tag[i]);
  if (diff != 0) return false;

  for (size_t off = 0, ctr = 0; off < g.ct_len; off += 32, ctr++) {
    uint8_t ks_msg[2 + 12 + 4];
    memcpy(ks_msg, "ks", 2);
    memcpy(&ks_msg[2], g.nonce, 12);
    ks_msg[14] = (uint8_t)(ctr >> 24);
    ks_msg[15] = (uint8_t)(ctr >> 16);
    ks_msg[16] = (uint8_t)(ctr >> 8);
    ks_msg[17] = (uint8_t)ctr;
    uint8_t ks[32];
    umcctl::hmacSha256(key, 32, ks_msg, sizeof(ks_msg), ks);
    for (size_t i = 0; i < 32 && off + i < g.ct_len; i++) out[off + i] = (char)(g.ct[off + i] ^ ks[i]);
  }
  out[g.ct_len] = 0;
  return true;
}

}  // namespace umcenrol
