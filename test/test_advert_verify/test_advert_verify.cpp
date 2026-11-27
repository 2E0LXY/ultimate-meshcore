#include <gtest/gtest.h>
#include <ed_25519.h>
#include <helpers/umc/UmcAdvertVerify.h>
#include <vector>

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

TEST(AdvertVerify, DecisionCountsDrops) {
  Node n(7);
  auto good = n.advert(1, app("node"));
  auto bad = good;
  bad[40] ^= 0xFF;
  Counters c;
  Budget b;
  EXPECT_TRUE(shouldPublish(c, b, 1000, good.data(), (int)good.size(), realVerify));
  EXPECT_FALSE(shouldPublish(c, b, 1000, bad.data(), (int)bad.size(), realVerify));
  EXPECT_FALSE(shouldPublish(c, b, 1000, good.data(), 10, realVerify));
  EXPECT_EQ(3u, c.checked);
  EXPECT_EQ(1u, c.dropped_sig);
  EXPECT_EQ(1u, c.dropped_short);
  EXPECT_EQ(2u, c.dropped());
  EXPECT_EQ(0u, c.skipped);
}

TEST(AdvertVerify, BudgetBoundsTheCostAndNeverPublishesUnchecked) {
  Node n(7);
  auto good = n.advert(1, app("node"));
  Counters c;
  Budget b;
  int published = 0;
  for (int i = 0; i < 20; i++) published += shouldPublish(c, b, 5000, good.data(), (int)good.size(), realVerify);
  EXPECT_EQ(8, published);                    // the burst
  EXPECT_EQ(12u, c.skipped);
  EXPECT_EQ(8u, c.checked);
  EXPECT_TRUE(shouldPublish(c, b, 5250, good.data(), (int)good.size(), realVerify));   // a second's worth of refill: 4 a second
  EXPECT_EQ(0u, c.dropped());                 // skipped is not dropped for a bad advert
}

TEST(AdvertVerify, BudgetSurvivesMillisWrap) {
  Budget b;
  const uint32_t t0 = 0xFFFFFFFFu - 100u;
  for (int i = 0; i < 8; i++) EXPECT_TRUE(b.take(t0));
  EXPECT_FALSE(b.take(t0));
  EXPECT_TRUE(b.take(t0 + 300u));             // 300 ms later, across the wrap: 1.2 tokens
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
