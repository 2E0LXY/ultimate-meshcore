#include <gtest/gtest.h>
#include <helpers/mqtt/NetPacket.h>

using namespace umcnet;

TEST(NetPacket, ReadsThePacketFromTheObserverJson) {
  const char* json =
      "{\"origin\":\"2E0LXY Repeater v4\",\"origin_id\":\"6C65C8D8\",\"timestamp\":\"2026-10-24T18:00:00Z\","
      "\"type\":\"RAW\",\"data\":\"110A8DFF00\"}";
  uint8_t out[255];
  const int n = packetFromRawJson(json, (int)strlen(json), out, sizeof(out));
  ASSERT_EQ(5, n);
  const uint8_t want[] = {0x11, 0x0A, 0x8D, 0xFF, 0x00};
  EXPECT_EQ(0, memcmp(want, out, 5));
}

TEST(NetPacket, AcceptsLowerCaseHex) {
  const char* json = "{\"data\":\"aBcDeF01\"}";
  uint8_t out[8];
  ASSERT_EQ(4, packetFromRawJson(json, (int)strlen(json), out, sizeof(out)));
  EXPECT_EQ(0xAB, out[0]);
  EXPECT_EQ(0xCD, out[1]);
  EXPECT_EQ(0xEF, out[2]);
  EXPECT_EQ(0x01, out[3]);
}

TEST(NetPacket, RejectsWhatIsNotAPacket) {
  uint8_t out[255];
  const char* none = "{\"origin\":\"x\"}";
  EXPECT_EQ(0, packetFromRawJson(none, (int)strlen(none), out, sizeof(out)));            // no data field
  const char* bad = "{\"data\":\"ZZZZ\"}";
  EXPECT_EQ(0, packetFromRawJson(bad, (int)strlen(bad), out, sizeof(out)));              // not hex
  const char* one = "{\"data\":\"AB\"}";
  EXPECT_EQ(0, packetFromRawJson(one, (int)strlen(one), out, sizeof(out)));              // under two bytes
  EXPECT_EQ(0, packetFromRawJson(nullptr, 0, out, sizeof(out)));
  EXPECT_EQ(0, packetFromRawJson("", 0, out, sizeof(out)));
}

TEST(NetPacket, StopsAtTheEndOfTheHexAndNeverOverruns) {
  // a long packet: 255 bytes is the most a LoRa packet can be
  char json[700];
  int pos = snprintf(json, sizeof(json), "{\"data\":\"");
  for (int i = 0; i < 300; i++) pos += snprintf(json + pos, sizeof(json) - pos, "%02X", i & 0xFF);
  pos += snprintf(json + pos, sizeof(json) - pos, "\"}");
  uint8_t out[255];
  EXPECT_EQ(255, packetFromRawJson(json, pos, out, sizeof(out)));
  uint8_t small[10];
  EXPECT_EQ(10, packetFromRawJson(json, pos, small, sizeof(small)));
}

TEST(NetPacket, HalfAByteAtTheEndIsIgnored) {
  const char* json = "{\"data\":\"AABBC\"}";
  uint8_t out[8];
  EXPECT_EQ(2, packetFromRawJson(json, (int)strlen(json), out, sizeof(out)));
}

TEST(NetPacket, KnowsRawTopics) {
  const char* t = "meshcore/LBA/6C65C8D87AE4BA76/raw";
  EXPECT_TRUE(topicIsRaw(t, (int)strlen(t)));
  const char* s = "meshcore/LBA/6C65C8D87AE4BA76/status";
  EXPECT_FALSE(topicIsRaw(s, (int)strlen(s)));
  EXPECT_FALSE(topicIsRaw("raw", 3));
  EXPECT_FALSE(topicIsRaw(nullptr, 0));
}

TEST(NetPacket, RecognisesItsOwnId) {
  const char* t = "meshcore/LBA/6C65C8D87AE4BA767A4248B5414E54469B2EE59A8CD49932515AB120A61E30B3/raw";
  const char* me = "6C65C8D87AE4BA767A4248B5414E54469B2EE59A8CD49932515AB120A61E30B3";
  EXPECT_TRUE(topicHasId(t, (int)strlen(t), me));
  EXPECT_TRUE(topicHasId(t, (int)strlen(t), "6c65c8d87ae4ba767a4248b5414e54469b2ee59a8cd49932515ab120a61e30b3"));
  const char* other = "meshcore/LBA/11111111111111111111111111111111111111111111111111111111111111111/raw";
  EXPECT_FALSE(topicHasId(other, (int)strlen(other), me));
  EXPECT_FALSE(topicHasId(t, (int)strlen(t), ""));
  EXPECT_FALSE(topicHasId(t, (int)strlen(t), nullptr));
}
