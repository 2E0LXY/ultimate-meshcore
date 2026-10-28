#include <gtest/gtest.h>
#include <helpers/mqtt/ControlCmd.h>

using namespace umcctl;

static std::string hex(const uint8_t* p, size_t n) { char o[200]; toHex(p, n, o); return o; }

TEST(Sha256, KnownVectors) {
  uint8_t out[32];
  Sha256 s; s.init(); s.update((const uint8_t*)"abc", 3); s.final(out);
  EXPECT_EQ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", hex(out, 32));
  Sha256 e; e.init(); e.final(out);
  EXPECT_EQ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", hex(out, 32));
  const char* two = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
  Sha256 t; t.init(); t.update((const uint8_t*)two, strlen(two)); t.final(out);
  EXPECT_EQ("248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1", hex(out, 32));
}

TEST(Hmac, Rfc4231Vectors) {
  uint8_t key[20]; memset(key, 0x0b, 20); uint8_t out[32];
  hmacSha256(key, 20, (const uint8_t*)"Hi There", 8, out);
  EXPECT_EQ("b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7", hex(out, 32));
  hmacSha256((const uint8_t*)"Jefe", 4, (const uint8_t*)"what do ya want for nothing?", 28, out);
  EXPECT_EQ("5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843", hex(out, 32));
}

TEST(Signature, MatchesTheServersFormat) {
  // the same string is produced by the dashboard in Python: hmac.new(key, "ID|ts|n|cmd", sha256)
  uint8_t key[32];
  ASSERT_TRUE(keyFromHex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", key));
  char sig[65];
  signature(key, "756C3D39", 1760000000ULL, 1760000000123ULL, "get radio", sig);
  EXPECT_EQ(64u, strlen(sig));
  char again[65];
  signature(key, "756C3D39", 1760000000ULL, 1760000000123ULL, "get radio", again);
  EXPECT_TRUE(sameSignature(sig, again));
  signature(key, "756C3D39", 1760000000ULL, 1760000000123ULL, "get tx", again);
  EXPECT_FALSE(sameSignature(sig, again));
  signature(key, "756C3D3A", 1760000000ULL, 1760000000123ULL, "get radio", again);
  EXPECT_FALSE(sameSignature(sig, again));
  signature(key, "756C3D39", 1760000001ULL, 1760000000123ULL, "get radio", again);
  EXPECT_FALSE(sameSignature(sig, again));
  // computed independently with Python's hmac module: the dashboard signs the same way
  EXPECT_STREQ("0ff5cfafea5254364a79e937d3c60436f646b719874ad461c0be4ff6cab7a983", sig);
}

TEST(Key, MustBeSixtyFourHexCharacters) {
  uint8_t k[32];
  EXPECT_FALSE(keyFromHex(nullptr, k));
  EXPECT_FALSE(keyFromHex("abcd", k));
  EXPECT_FALSE(keyFromHex("zz0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", k));
  EXPECT_TRUE(keyFromHex("AA0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", k));
  EXPECT_EQ(0xAA, k[0]);
}

TEST(Json, ReadsTheFieldsOfACommand) {
  const char* j = "{\"id\":\"c1\",\"ts\":1760000000,\"n\":1760000000123,\"cmd\":\"get radio\",\"sig\":\"abc\"}";
  const int n = (int)strlen(j);
  char s[40]; uint64_t v;
  ASSERT_TRUE(jsonString(j, n, "cmd", s, sizeof(s))); EXPECT_STREQ("get radio", s);
  ASSERT_TRUE(jsonString(j, n, "id", s, sizeof(s))); EXPECT_STREQ("c1", s);
  ASSERT_TRUE(jsonNumber(j, n, "ts", &v)); EXPECT_EQ(1760000000ULL, v);
  ASSERT_TRUE(jsonNumber(j, n, "n", &v)); EXPECT_EQ(1760000000123ULL, v);
  EXPECT_FALSE(jsonString(j, n, "missing", s, sizeof(s)));
  EXPECT_FALSE(jsonNumber(j, n, "missing", &v));
}

TEST(Json, RefusesEscapesAndOverlongValues) {
  const char* j = "{\"cmd\":\"get \\\"x\\\"\"}";
  char s[40];
  EXPECT_FALSE(jsonString(j, (int)strlen(j), "cmd", s, sizeof(s)));
  const char* longv = "{\"cmd\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}";
  char small[10];
  EXPECT_FALSE(jsonString(longv, (int)strlen(longv), "cmd", small, sizeof(small)));
  const char* unfinished = "{\"cmd\":\"get radio";
  EXPECT_FALSE(jsonString(unfinished, (int)strlen(unfinished), "cmd", s, sizeof(s)));
}

TEST(Policy, AllowsTheEverydayCommands) {
  for (const char* c : {"get radio", "get tx", "set tx 20", "set radio 869.618,62.5,8,8", "advert", "advert.zerohop", "reboot", "ver", "neighbors",
                        "set flood.max 20", "set loop.detect minimal", "set mqtt.custom.bridge on", "set mqtt.custom.rate 20", "set mqtt.raw on",
                        "region put gb-yor gb", "region save", "stats-core", "set name 2E0LXY-REPEATER", "set advert.interval 60", "time 1760000000",
                        "clear stats", "tempradio 869.618,62.5,8,8,10", "set repeat on", "get traffic", "route find leeds", "trace route abc"})
    EXPECT_TRUE(commandAllowed(c)) << c;
}

TEST(Policy, AllowsTheFullSignedAdminCli) {
  for (const char* c : {"password hunter22", "set guest.password x", "get guest.password", "set prv.key aa", "get prv.key", "set wifi.ssid x", "set wifi.pwd y",
                        "wifi clear 1", "get wifi.pwd", "set ap.mode on", "set ap.password z", "set net.ip dhcp", "set pin 12345678", "setperm abc 3", "set http off",
                        "set telnet on", "set mqtt.custom.password p", "get mqtt.custom.password", "set mqtt.custom.host evil.example", "set mqtt.custom.port 1",
                        "set mqtt.custom.transport tcp", "set mqtt.custom.username u", "set mqtt.control off", "set mqtt.control.key aa", "get mqtt.control.key",
                        "set bridge.secret s", "get bridge.secret", "start ota", "ota install", "erase", "format", "poweroff", "set ble.pin 1", "set mqtt.meshmapper on",
                        "SET PASSWORD x", "Set Prv.Key aa", "GET PRV.KEY"})
    EXPECT_TRUE(commandAllowed(c)) << c;
}

TEST(Policy, RefusesAnythingOddlyShaped) {
  EXPECT_FALSE(commandAllowed(nullptr));
  EXPECT_FALSE(commandAllowed(""));
  EXPECT_FALSE(commandAllowed("get radio\nset tx 1"));
  EXPECT_FALSE(commandAllowed("get radio\rpassword x"));
  EXPECT_FALSE(commandAllowed("get \"radio\""));
  EXPECT_FALSE(commandAllowed("get radio\\"));
  EXPECT_FALSE(commandAllowed(" get radio"));
  EXPECT_FALSE(commandAllowed("get radio "));
  EXPECT_TRUE(commandAllowed("frobnicate"));       // the device CLI reports whether it knows it
  EXPECT_TRUE(commandAllowed("set unknown.thing 1"));
  EXPECT_FALSE(commandAllowed(std::string(141, 'a').c_str()));
  EXPECT_FALSE(commandAllowed((std::string("get ") + std::string(200, 'a')).c_str()));
}

int main(int argc, char **argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
