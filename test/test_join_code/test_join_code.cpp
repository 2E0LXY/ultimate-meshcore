#include <gtest/gtest.h>
#include <helpers/mqtt/JoinCode.h>

using namespace umcjoin;

// made by the dashboard's Python (server/umcnet/dash/umcnet_dash.py: make_join_code) from these inputs
static const char* kKeyHex = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
static const char* kFull = "UMC1.AQNMQkEPYmxha2Utc2hlZmZpZWxkFEhtY21yenFsclZNVUFjdGpZendOAAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8LJuo";      // blake-sheffield / HmcmrzqlrVMUActjYzwN / LBA / key / bridge on
static const char* kPlain = "UMC1.AQBMQkELdjMtcmVwZWF0ZXIQYWJjZGVmZ2gxMjM0NTY3OPUrdA";     // v3-repeater / abcdefgh12345678 / LBA / no key / bridge off
static const char* kOwnHost = "UMC1.AQdHQlIIaGlsbC10b3AUWnE5Xy1BYThCYjdDYzZEZDVFZTQQbWVzaC5leGFtcGxlLm9yZyKzAAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8XT_s";   // hill-top / Zq9_-Aa8Bb7Cc6Dd5Ee4 / GBR / key / bridge on / mesh.example.org:8883

TEST(Join, ReadsEverythingInACodeWithAKey) {
  Join j;
  ASSERT_TRUE(parse(kFull, &j));
  EXPECT_STREQ("LBA", j.iata);
  EXPECT_STREQ("blake-sheffield", j.user);
  EXPECT_STREQ("HmcmrzqlrVMUActjYzwN", j.pass);
  EXPECT_TRUE(j.has_key);
  EXPECT_TRUE(j.bridge);
  EXPECT_FALSE(j.has_host);
  uint8_t want[32];
  ASSERT_TRUE(umcctl::keyFromHex(kKeyHex, want));
  EXPECT_EQ(0, memcmp(want, j.key, 32));
}

TEST(Join, ReadsACodeWithoutAKeyOrBridge) {
  Join j;
  ASSERT_TRUE(parse(kPlain, &j));
  EXPECT_STREQ("v3-repeater", j.user);
  EXPECT_FALSE(j.has_key);
  EXPECT_FALSE(j.bridge);
}

TEST(Join, ReadsAnOwnHostAndPort) {
  Join j;
  ASSERT_TRUE(parse(kOwnHost, &j));
  EXPECT_TRUE(j.has_host);
  EXPECT_STREQ("mesh.example.org", j.host);
  EXPECT_EQ(8883, j.port);
  EXPECT_STREQ("GBR", j.iata);
  EXPECT_STREQ("Zq9_-Aa8Bb7Cc6Dd5Ee4", j.pass);
}

TEST(Join, AnyDamagedCharacterIsRefused) {
  const std::string good = kFull;
  for (size_t i = 5; i < good.size(); i++) {
    std::string bad = good;
    bad[i] = bad[i] == 'A' ? 'B' : 'A';
    Join j;
    if (bad != good) EXPECT_FALSE(parse(bad.c_str(), &j)) << "position " << i;
  }
}

TEST(Join, ATruncatedOrPaddedCodeIsRefused) {
  Join j;
  const std::string good = kFull;
  EXPECT_FALSE(parse(good.substr(0, good.size() - 1).c_str(), &j));
  EXPECT_FALSE(parse(good.substr(0, 20).c_str(), &j));
  EXPECT_FALSE(parse((good + "A").c_str(), &j));
  EXPECT_FALSE(parse((good + "=").c_str(), &j));
  EXPECT_FALSE(parse((good + " ").c_str(), &j));
}

TEST(Join, WrongPrefixesAndEmptyInputAreRefused) {
  Join j;
  EXPECT_FALSE(parse(nullptr, &j));
  EXPECT_FALSE(parse("", &j));
  EXPECT_FALSE(parse("UMC2.AAAA", &j));
  EXPECT_FALSE(parse("umc1.AAAA", &j));
  EXPECT_FALSE(parse((std::string("UMC2") + (kFull + 4)).c_str(), &j));
}

TEST(Base64, DecodesTheUrlSafeAlphabetWithoutPadding) {
  uint8_t o[8];
  size_t n = 0;
  ASSERT_TRUE(b64urlDecode("-_8", o, sizeof(o), &n));          // 0xFB 0xFF
  ASSERT_EQ(2u, n);
  EXPECT_EQ(0xFB, o[0]);
  EXPECT_EQ(0xFF, o[1]);
  EXPECT_FALSE(b64urlDecode("ab+/", o, sizeof(o), &n));        // the other alphabet
  EXPECT_FALSE(b64urlDecode("a", o, sizeof(o), &n));           // a single stray character
}

TEST(ControlList, FullSignedAdminCliIncludesNetworkCommands) {
  EXPECT_TRUE(umcctl::commandAllowed("set mqtt.join UMC1.abc"));
  EXPECT_TRUE(umcctl::commandAllowed("set mqtt.umcnet off"));
  EXPECT_TRUE(umcctl::commandAllowed("get mqtt.umcnet"));
}

int main(int argc, char **argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
