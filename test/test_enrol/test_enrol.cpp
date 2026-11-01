#include <gtest/gtest.h>
#include <ed_25519.h>
#include <helpers/mqtt/Enrol.h>

using namespace umcenrol;

// made by umcnet_enrol.py (the dashboard's half) from fixed inputs: see server/umcnet/dash/test_dash.py
static const char* kPrv = "70788f1a0cea001a2631dae5d05dbd062008d5b30f50b9e29beb2a7822289044573dfc9b6ffeb1c786a16349e70f9836876a743c31c0a7a2a70727a852eec372";
static const char* kPub = "79B5562E8FE654F94078B112E8A98BA7901F853AE695BED7E0E3910BAD049664";
static const char* kCode = "UMC1.AQNMQkEIaGlsbC10b3AUWnE5Xy1BYThCYjdDYzZEZDVFZTQAAQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eH4KlzA";
static const char* kGrant = "AYGXSqjH4HB4bCSNDOfnEGHUyrUQ-h8D4IEpXIxXqkkkyMnKy8zNzs_Q0dLTkLlTDu9GOrXSFCR4eoSo1LE9QxSS4VgdMySwS4vu5NQwH_9fs_dW2-CEHHuZA-83jFG-NLhFjHwTj0EkUclC5hhcWzOxmkQncD_lTLC_sjfHCnfx4Ie2gozlH86YTK17l6KKP53kHMQhAVQTw2NHhF4u4Q";

static void unhex(const char* hex, uint8_t* out, size_t n) {
  for (size_t i = 0; i < n; i++) out[i] = (uint8_t)((umcctl::nibble(hex[2 * i]) << 4) | umcctl::nibble(hex[2 * i + 1]));
}

TEST(Enrol, TheRepeaterOpensAGrantTheServerMade) {
  uint8_t prv[64], pub[32], shared[32];
  unhex(kPrv, prv, 64);
  unhex(kPub, pub, 32);
  Grant g;
  ASSERT_TRUE(parseGrant(kGrant, &g));
  ed25519_key_exchange(shared, g.eph, prv);            // the call LocalIdentity::calcSharedSecret makes
  char out[200];
  ASSERT_TRUE(openGrant(g, shared, pub, out, sizeof(out)));
  EXPECT_STREQ(kCode, out);
  umcjoin::Join j;
  ASSERT_TRUE(umcjoin::parse(out, &j));                // and what it opens is a valid join code
  EXPECT_STREQ("hill-top", j.user);
  EXPECT_TRUE(j.has_key);
}

TEST(Enrol, AnotherRepeaterCannotOpenIt) {
  uint8_t pub[32], other_prv[64], shared[32];
  unhex(kPub, pub, 32);
  memset(other_prv, 7, sizeof(other_prv));
  Grant g;
  ASSERT_TRUE(parseGrant(kGrant, &g));
  ed25519_key_exchange(shared, g.eph, other_prv);
  char out[200];
  EXPECT_FALSE(openGrant(g, shared, pub, out, sizeof(out)));
}

TEST(Enrol, AnyDamagedCharacterIsRefused) {
  uint8_t prv[64], pub[32], shared[32];
  unhex(kPrv, prv, 64);
  unhex(kPub, pub, 32);
  const std::string good = kGrant;
  int refused = 0, tried = 0;
  for (size_t i = 0; i < good.size(); i++) {
    std::string bad = good;
    bad[i] = bad[i] == 'A' ? 'B' : 'A';
    Grant g;
    tried++;
    if (!parseGrant(bad.c_str(), &g)) { refused++; continue; }
    ed25519_key_exchange(shared, g.eph, prv);
    char out[200];
    if (!openGrant(g, shared, pub, out, sizeof(out))) refused++;
  }
  EXPECT_EQ(tried, refused);
}

TEST(Enrol, TruncatedOrEmptyGrantsAreRefused) {
  Grant g;
  EXPECT_FALSE(parseGrant(nullptr, &g));
  EXPECT_FALSE(parseGrant("", &g));
  EXPECT_FALSE(parseGrant("AAAA", &g));
  const std::string good = kGrant;
  EXPECT_FALSE(parseGrant(good.substr(0, 60).c_str(), &g));
}

TEST(Enrol, TheSignedTextMatchesTheServer) {
  char msg[160];
  ASSERT_GT(helloMessage(kPub, 1790000000, "a1b2c3d4e5f60718", msg, sizeof(msg)), 0u);
  EXPECT_STREQ("UMC-ENROL1|79B5562E8FE654F94078B112E8A98BA7901F853AE695BED7E0E3910BAD049664|1790000000|a1b2c3d4e5f60718", msg);
}

TEST(Enrol, TheRequestIsValidJsonWithACleanName) {
  char js[400];
  const size_t n = helloJson(kPub, "Hill \"Top\"\\\x01", "0.2.0", "Heltec V3", 1790000000, "a1b2c3d4e5f60718", "ab", js, sizeof(js));
  ASSERT_GT(n, 0u);
  EXPECT_NE(nullptr, strstr(js, "\"name\":\"Hill Top\""));
  EXPECT_NE(nullptr, strstr(js, "\"v\":1"));
  char tiny[20];
  EXPECT_EQ(0u, helloJson(kPub, "x", "0.2.0", "b", 1, "n", "s", tiny, sizeof(tiny)));
}

int main(int argc, char **argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
