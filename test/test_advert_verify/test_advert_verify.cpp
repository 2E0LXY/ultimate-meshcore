#include <gtest/gtest.h>
#include <ed_25519.h>
#include <helpers/umc/UmcAdvertVerify.h>
#include <vector>
#include <stddef.h>

using namespace umcadv;

// real Ed25519 vectors, built the way Mesh::createAdvert builds them
struct Node {
  uint8_t pub[32], prv[64];
  Node(uint8_t seed_byte) {
    uint8_t seed[32];
    memset(seed, seed_byte, 32);
    ed25519_create_keypair(pub, prv, seed);
  }
  std::vector<uint8_t> advert(uint32_t ts, const std::vector<uint8_t>& app) const {
    std::vector<uint8_t> msg(pub, pub + 32);
    msg.insert(msg.end(), (uint8_t*)&ts, (uint8_t*)&ts + 4);
    size_t used = app.size() > 32 ? 32 : app.size();
    msg.insert(msg.end(), app.begin(), app.begin() + used);
    uint8_t sig[64];
    ed25519_sign(sig, msg.data(), msg.size(), pub, prv);
    std::vector<uint8_t> p(pub, pub + 32);
    p.insert(p.end(), (uint8_t*)&ts, (uint8_t*)&ts + 4);
    p.insert(p.end(), sig, sig + 64);
    p.insert(p.end(), app.begin(), app.end());
    return p;
  }
};

static bool realVerify(const uint8_t* pub, const uint8_t* sig, const uint8_t* msg, int n) {
  return ed25519_verify(sig, msg, n, pub) != 0;
}

static std::vector<uint8_t> app(const char* name) {
  std::vector<uint8_t> a = {0x82};   // flags: repeater, has name
  for (const char* p = name; *p; p++) a.push_back((uint8_t)*p);
  return a;
}

TEST(AdvertVerify, ValidAdvert) {
  Node n(7);
  auto p = n.advert(1760000000, app("2E0LXY-REPEATER"));
  EXPECT_EQ(V_VALID, check(p.data(), (int)p.size(), realVerify));
}

TEST(AdvertVerify, ValidWithNoAppDataAndWithOverlongAppData) {
  Node n(9);
  auto a = n.advert(5, {});
  EXPECT_EQ(V_VALID, check(a.data(), (int)a.size(), realVerify));
  std::vector<uint8_t> big(40, 'x');           // signed over the first 32 bytes, as the mesh does
  auto b = n.advert(5, big);
  EXPECT_EQ(V_VALID, check(b.data(), (int)b.size(), realVerify));
}

TEST(AdvertVerify, CorruptedBitsAreDropped) {
  Node n(7);
  auto good = n.advert(1760000000, app("node"));
  for (size_t i : {size_t(0), size_t(31), size_t(32), size_t(35), size_t(36), size_t(99), size_t(100), good.size() - 1}) {
    auto p = good;
    p[i] ^= 0x01;
    EXPECT_EQ(V_BAD_SIG, check(p.data(), (int)p.size(), realVerify)) << i;
  }
}

TEST(AdvertVerify, TruncatedOrEmptyIsMalformed) {
  Node n(7);
  auto good = n.advert(1, app("node"));
  EXPECT_EQ(V_SHORT, check(good.data(), 99, realVerify));
  EXPECT_EQ(V_SHORT, check(good.data(), 0, realVerify));
  EXPECT_EQ(V_SHORT, check(nullptr, 120, realVerify));
  EXPECT_EQ(V_VALID, check(good.data(), 100 + 5, [](const uint8_t*, const uint8_t*, const uint8_t*, int) { return true; }));
}

TEST(AdvertVerify, AppDataCutShortAfterSigningFails) {
  Node n(7);
  auto p = n.advert(1, app("a-long-node-name"));
  p.resize(p.size() - 3);                     // lost its tail on the way
  EXPECT_EQ(V_BAD_SIG, check(p.data(), (int)p.size(), realVerify));
}

TEST(AdvertVerify, ValidSignatureIsNotTrust) {
  // someone else's perfectly valid advert passes: this check says "well formed and signed", nothing more
  Node stranger(200);
  auto p = stranger.advert(1, app("anyone"));
  EXPECT_EQ(V_VALID, check(p.data(), (int)p.size(), realVerify));
}

// a distinct 8-byte "packet hash" per advert, as the mesh's hash is distinct per payload
static void hashOf(const std::vector<uint8_t>& p, uint8_t out[8]) {
  uint64_t h = 1469598103934665603ull;
  for (uint8_t b : p) { h ^= b; h *= 1099511628211ull; }
  memcpy(out, &h, 8);
}

static bool decide(Counters& c, Budget& b, VerdictCache& k, uint32_t now, const std::vector<uint8_t>& p, int len = -1) {
  uint8_t h[8];
  hashOf(p, h);
  return shouldPublish(c, b, k, now, h, p.data(), len < 0 ? (int)p.size() : len, realVerify);
}

static int g_verifies = 0;
static bool countingVerify(const uint8_t* pub, const uint8_t* sig, const uint8_t* msg, int n) {
  g_verifies++;
  return realVerify(pub, sig, msg, n);
}

TEST(AdvertVerify, DecisionCountsDrops) {
  Node n(7);
  auto good = n.advert(1, app("node"));
  auto bad = good;
  bad[40] ^= 0xFF;
  Counters c;
  Budget b;
  VerdictCache k;
  EXPECT_TRUE(decide(c, b, k, 1000, good));
  EXPECT_FALSE(decide(c, b, k, 1600, bad));
  EXPECT_FALSE(decide(c, b, k, 2200, std::vector<uint8_t>(good.begin(), good.begin() + 10)));   // too short
  EXPECT_EQ(3u, c.checked);
  EXPECT_EQ(1u, c.dropped_sig);
  EXPECT_EQ(1u, c.dropped_short);
  EXPECT_EQ(2u, c.dropped());
  EXPECT_EQ(0u, c.skipped);
}

TEST(AdvertVerify, BudgetIsTwoBurstTwoPerSecondAndNeverPublishesUnchecked) {
  Counters c;
  Budget b;
  VerdictCache k;
  int published = 0;
  for (int i = 0; i < 20; i++) {
    Node n((uint8_t)(10 + i));                 // 20 different adverts
    published += decide(c, b, k, 5000, n.advert(1, app("x")));
  }
  EXPECT_EQ(2, published);                    // the burst
  EXPECT_EQ(18u, c.skipped);
  EXPECT_EQ(2u, c.checked);
  Node m(99);
  EXPECT_FALSE(decide(c, b, k, 5250, m.advert(1, app("y"))));   // 0.5 token: not yet
  EXPECT_TRUE(decide(c, b, k, 5500, m.advert(2, app("y"))));    // 1 token after 500 ms at 2 a second
  EXPECT_EQ(0u, c.dropped());                 // skipped is not dropped
}

TEST(AdvertVerify, BudgetSurvivesMillisWrap) {
  Budget b;
  const uint32_t t0 = 0xFFFFFFFFu - 100u;
  EXPECT_TRUE(b.take(t0));
  EXPECT_TRUE(b.take(t0));
  EXPECT_FALSE(b.take(t0));
  EXPECT_TRUE(b.take(t0 + 600u));             // 600 ms later, across the wrap: 1.2 tokens
}

TEST(AdvertVerify, RepeatsAreNotCheckedAgainAndCostNoBudget) {
  Node n(7);
  auto good = n.advert(1, app("node"));
  Counters c;
  Budget b;
  VerdictCache k;
  g_verifies = 0;
  uint8_t h[8];
  hashOf(good, h);
  int published = 0;
  for (int i = 0; i < 50; i++)                // the same flood advert heard 50 times in a second
    published += shouldPublish(c, b, k, 1000 + i * 10, h, good.data(), (int)good.size(), countingVerify);
  EXPECT_EQ(50, published);                   // duplicates are still published, as before
  EXPECT_EQ(1, g_verifies);                   // but only one signature check
  EXPECT_EQ(1u, c.checked);
  EXPECT_EQ(49u, c.repeats);
  EXPECT_EQ(0u, c.skipped);                   // and no budget used: others still get through
  Node o(8);
  EXPECT_TRUE(decide(c, b, k, 1500, o.advert(1, app("o"))));
  EXPECT_TRUE(decide(c, b, k, 1500, Node(9).advert(1, app("p"))));
}

TEST(AdvertVerify, RepeatOfBadAdvertStaysDroppedAndIsNotRecounted) {
  Node n(7);
  auto bad = n.advert(1, app("node"));
  bad[50] ^= 1;
  Counters c;
  Budget b;
  VerdictCache k;
  for (int i = 0; i < 10; i++) EXPECT_FALSE(decide(c, b, k, 1000 + i, bad));
  EXPECT_EQ(1u, c.dropped_sig);
  EXPECT_EQ(1u, c.checked);
  EXPECT_EQ(9u, c.repeats);
}

TEST(AdvertVerify, VerdictExpiresAndTheCacheIsBounded) {
  Node n(7);
  auto good = n.advert(1, app("node"));
  Counters c;
  Budget b;
  VerdictCache k;
  EXPECT_TRUE(decide(c, b, k, 1000, good));
  EXPECT_TRUE(decide(c, b, k, 1000 + VerdictCache::kTtlMs - 1, good));
  EXPECT_EQ(1u, c.repeats);
  EXPECT_TRUE(decide(c, b, k, 1000 + VerdictCache::kTtlMs + 10, good));   // expired: checked afresh
  EXPECT_EQ(2u, c.checked);
  // more distinct adverts than slots: the oldest is forgotten, not a crash or a wrong verdict
  VerdictCache k2;
  for (int i = 0; i < VerdictCache::kSlots + 5; i++) {
    uint8_t h[8] = {(uint8_t)i, 1, 2, 3, 4, 5, 6, 7};
    k2.put(h, 100, V_VALID);
  }
  Verdict v;
  uint8_t first[8] = {0, 1, 2, 3, 4, 5, 6, 7}, last[8] = {(uint8_t)(VerdictCache::kSlots + 4), 1, 2, 3, 4, 5, 6, 7};
  EXPECT_FALSE(k2.find(first, 100, v));
  EXPECT_TRUE(k2.find(last, 100, v));
}

TEST(AdvertVerify, PrefsMigrationKeepsVerifyOnForOldFilesWithGarbagePadding) {
  // an older file: no tag (it reads as 0 beyond the old size), and the padding byte holds junk
  for (int junk : {0, 1, 2, 0x7f, 0xff}) EXPECT_EQ(0, migrateVerifyOff(0, (uint8_t)junk));
  EXPECT_EQ(0, migrateVerifyOff(0x12345678u, 1));          // a wrong tag is not trusted either
  // a file written by this build: the saved choice is honoured
  EXPECT_EQ(1, migrateVerifyOff(kPrefsTag, 1));
  EXPECT_EQ(0, migrateVerifyOff(kPrefsTag, 0));
  EXPECT_EQ(1, migrateVerifyOff(kPrefsTag, 0x55));         // any nonzero is "off", normalised to 1
}

TEST(AdvertVerify, OldSizedFileReadsTagAsZero) {
  // the layout argument in code: the tag is a 4-byte-aligned member appended after the old last byte, so
  // it starts at or beyond the old end of struct and an old file never reaches it
  struct OldTail { uint32_t magic; char data[7]; uint8_t custom_enrol; };           // old shape: ends in padding
  struct NewTail { uint32_t magic; char data[7]; uint8_t custom_enrol; uint8_t verify_off; uint32_t tag; };
  EXPECT_TRUE(offsetof(NewTail, tag) >= sizeof(OldTail));
  alignas(4) uint8_t file[sizeof(OldTail)];
  memset(file, 0xFF, sizeof(file));                         // junk everywhere, including padding
  NewTail persisted{};
  memcpy(&persisted, file, sizeof(file));                   // what load() does with a short file
  EXPECT_EQ(0, migrateVerifyOff(persisted.tag, persisted.verify_off));
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
