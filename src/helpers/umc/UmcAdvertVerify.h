#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// Before an ADVERT packet heard on the radio is published to MQTT, check that it is well formed and
// that its signature is valid, using the same rule as Mesh::onRecvPacket (the signature covers
// public key + timestamp + app data, with the app data cut to 32 bytes). Corrupted adverts are dropped
// and counted (`mqtt.advert_drop`). A valid signature only shows that whoever holds that key sent it:
// it is NOT a statement that the node is trusted, wanted or genuine. Plain code, tested on a computer
// (test/test_advert_verify). The verify function is the caller's (mesh::Identity::verify on the device).
namespace umcadv {

constexpr int kPubKey = 32;       // PUB_KEY_SIZE
constexpr int kSig = 64;          // SIGNATURE_SIZE
constexpr int kMaxAppData = 32;   // MAX_ADVERT_DATA_SIZE
constexpr int kMinPayload = kPubKey + 4 + kSig;

enum Verdict : uint8_t { V_VALID = 0, V_SHORT, V_BAD_SIG };

// verify(pub_key, signature, message, message_len) -> true if the signature is good
template <class Verify>
inline Verdict check(const uint8_t* payload, int payload_len, Verify verify) {
  if (payload == nullptr || payload_len < kMinPayload) return V_SHORT;
  const uint8_t* pub = payload;
  const uint8_t* ts = payload + kPubKey;
  const uint8_t* sig = payload + kPubKey + 4;
  const uint8_t* app = payload + kMinPayload;
  int app_len = payload_len - kMinPayload;
  if (app_len > kMaxAppData) app_len = kMaxAppData;   // the same cut the mesh makes
  uint8_t msg[kPubKey + 4 + kMaxAppData];
  int n = 0;
  memcpy(msg + n, pub, kPubKey); n += kPubKey;
  memcpy(msg + n, ts, 4); n += 4;
  if (app_len > 0) { memcpy(msg + n, app, app_len); n += app_len; }
  return verify(pub, sig, msg, n) ? V_VALID : V_BAD_SIG;
}

// Keeps the cost low: at most `kBurst` checks at once, refilled at `kPerSec` a second. An advert
// that arrives with the budget empty is not published (counted as skipped), never published unchecked.
class Budget {
public:
  static constexpr uint32_t kBurst = 8;
  static constexpr uint32_t kPerSec = 4;
  bool take(uint32_t now_ms) {
    if (!_started) { _started = true; _last = now_ms; _tokens_milli = kBurst * 1000UL; }
    const uint32_t dt = now_ms - _last;       // unsigned: correct across a millis() wrap
    _last = now_ms;
    uint64_t t = (uint64_t)_tokens_milli + (uint64_t)dt * kPerSec;
    if (t > kBurst * 1000UL) t = kBurst * 1000UL;
    _tokens_milli = (uint32_t)t;
    if (_tokens_milli < 1000) return false;
    _tokens_milli -= 1000;
    return true;
  }

private:
  bool _started = false;
  uint32_t _last = 0;
  uint32_t _tokens_milli = 0;
};

struct Counters {
  uint32_t checked = 0;
  uint32_t dropped_sig = 0;     // well formed, signature wrong
  uint32_t dropped_short = 0;   // too short to be an advert
  uint32_t skipped = 0;         // not checked (budget empty), so not published
  uint32_t dropped() const { return dropped_sig + dropped_short; }   // `mqtt.advert_drop`
};

// The whole decision for one advert about to be published. true = publish it.
template <class Verify>
inline bool shouldPublish(Counters& c, Budget& b, uint32_t now_ms, const uint8_t* payload, int payload_len, Verify verify) {
  if (!b.take(now_ms)) { c.skipped++; return false; }
  c.checked++;
  switch (check(payload, payload_len, verify)) {
    case V_VALID: return true;
    case V_SHORT: c.dropped_short++; return false;
    default: c.dropped_sig++; return false;
  }
}

}  // namespace umcadv
