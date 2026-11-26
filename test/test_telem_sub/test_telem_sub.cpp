#include <gtest/gtest.h>
#include <helpers/umc/UmcTelemSub.h>

using namespace umc;

// LPP: ch1 voltage 4.10 V (410=0x019A), ch2 temp 21.5 C (215=0x00D7), ch3 humidity 50% (100=0x64)
static const uint8_t kTelem[] = {1, LPP_VOLTAGE, 0x01, 0x9A, 2, LPP_TEMPERATURE, 0x00, 0xD7, 3, LPP_RELATIVE_HUMIDITY, 0x64};
// deltas: ch1 voltage 0.10 V (10=0x000A), ch2 temp 1.0 C (10=0x000A)
static const uint8_t kDeltas[] = {1, LPP_VOLTAGE, 0x00, 0x0A, 2, LPP_TEMPERATURE, 0x00, 0x0A};

static void put16(uint8_t* p, uint16_t v) { p[0] = v >> 8; p[1] = v & 0xFF; }

TEST(TelemSub, FindsValuesAndNegatives) {
  float v;
  ASSERT_TRUE(lppFind(kTelem, sizeof(kTelem), 2, LPP_TEMPERATURE, v));
  EXPECT_NEAR(v, 21.5f, 0.01f);
  ASSERT_TRUE(lppFind(kTelem, sizeof(kTelem), 3, LPP_RELATIVE_HUMIDITY, v));
  EXPECT_NEAR(v, 50.0f, 0.01f);
  uint8_t neg[4] = {1, LPP_TEMPERATURE, 0, 0}; put16(&neg[2], (uint16_t)(int16_t)-55);
  ASSERT_TRUE(lppFind(neg, 4, 1, LPP_TEMPERATURE, v));
  EXPECT_NEAR(v, -5.5f, 0.01f);
  EXPECT_FALSE(lppFind(kTelem, sizeof(kTelem), 9, LPP_TEMPERATURE, v));
}

TEST(TelemSub, TruncatedBufferNeverReadsPastEnd) {
  float v;
  EXPECT_FALSE(lppFind(kTelem, 3, 1, LPP_VOLTAGE, v));    // header but value cut off
  EXPECT_FALSE(lppFind(kTelem, 1, 1, LPP_VOLTAGE, v));
  uint8_t unk[] = {1, 250, 1, 2};                          // unknown type: stop, don't guess
  EXPECT_FALSE(lppFind(unk, sizeof(unk), 1, LPP_VOLTAGE, v));
}

TEST(TelemSub, ParseAcceptsGood) {
  TelemSub s;
  ASSERT_TRUE(telemSubParse(s, kDeltas, sizeof(kDeltas)));
  EXPECT_EQ(s.count, 2);
  EXPECT_NEAR(s.e[0].min_delta, 0.10f, 0.001f);
  EXPECT_NEAR(s.e[1].min_delta, 1.0f, 0.001f);
}

TEST(TelemSub, ParseRejectsBadInput) {
  TelemSub s;
  EXPECT_FALSE(telemSubParse(s, kDeltas, 0));                       // empty
  EXPECT_FALSE(telemSubParse(s, kDeltas, 3));                       // cut mid-entry
  EXPECT_FALSE(telemSubParse(s, kDeltas, 5));                       // cut mid-entry
  uint8_t unk[] = {1, 250, 0, 0};  EXPECT_FALSE(telemSubParse(s, unk, 4));      // unknown type
  uint8_t gps[] = {1, LPP_GPS, 0,0,0,0,0,0,0,0,0}; EXPECT_FALSE(telemSubParse(s, gps, 11));  // non-scalar
  uint8_t ch0[] = {0, LPP_VOLTAGE, 0, 1};  EXPECT_FALSE(telemSubParse(s, ch0, 4));  // channel 0
  uint8_t dup[] = {1, LPP_VOLTAGE, 0, 1, 1, LPP_VOLTAGE, 0, 2};  EXPECT_FALSE(telemSubParse(s, dup, 8));
  uint8_t many[TELEM_SUB_MAX_ENTRIES * 4 + 4];
  for (int i = 0; i < TELEM_SUB_MAX_ENTRIES + 1; i++) { many[i*4]=i+1; many[i*4+1]=LPP_VOLTAGE; many[i*4+2]=0; many[i*4+3]=1; }
  EXPECT_FALSE(telemSubParse(s, many, (TELEM_SUB_MAX_ENTRIES + 1) * 4));        // too many
  EXPECT_EQ(s.count, 0);                                           // failure leaves it cleared
}

TEST(TelemSub, FirstCycleAlwaysPushes_ThenOnlyOnDelta) {
  TelemSub s; ASSERT_TRUE(telemSubParse(s, kDeltas, sizeof(kDeltas)));
  EXPECT_TRUE(telemSubChanged(s, kTelem, sizeof(kTelem)));          // first: no previous
  EXPECT_FALSE(telemSubChanged(s, kTelem, sizeof(kTelem)));         // same values
  uint8_t t2[sizeof(kTelem)]; memcpy(t2, kTelem, sizeof(t2));
  put16(&t2[6], 220);                                               // temp 22.0: +0.5 < 1.0
  EXPECT_FALSE(telemSubChanged(s, t2, sizeof(t2)));
  put16(&t2[6], 230);                                               // temp 23.0: +1.5 from 21.5 > 1.0
  EXPECT_TRUE(telemSubChanged(s, t2, sizeof(t2)));
  EXPECT_FALSE(telemSubChanged(s, t2, sizeof(t2)));                 // snapshot moved on
}

TEST(TelemSub, SmallDriftDoesNotAccumulateSilently) {
  TelemSub s; ASSERT_TRUE(telemSubParse(s, kDeltas, sizeof(kDeltas)));
  uint8_t t[sizeof(kTelem)]; memcpy(t, kTelem, sizeof(t));
  EXPECT_TRUE(telemSubChanged(s, t, sizeof(t)));
  for (int temp = 216; temp <= 225; temp++) { put16(&t[6], temp); EXPECT_FALSE(telemSubChanged(s, t, sizeof(t))); }
  put16(&t[6], 226);                                                // 22.6 vs 21.5 = 1.1 > 1.0
  EXPECT_TRUE(telemSubChanged(s, t, sizeof(t)));
}

TEST(TelemSub, AbsentSensorIsNotAChange) {
  TelemSub s; ASSERT_TRUE(telemSubParse(s, kDeltas, sizeof(kDeltas)));
  uint8_t only_v[] = {1, LPP_VOLTAGE, 0x01, 0x9A};
  EXPECT_TRUE(telemSubChanged(s, only_v, sizeof(only_v)));          // voltage is new
  EXPECT_FALSE(telemSubChanged(s, only_v, sizeof(only_v)));
  EXPECT_FALSE(telemSubChanged(s, nullptr, 0));
}

TEST(TelemSub, ExpiryWindow) {
  TelemSub s; ASSERT_TRUE(telemSubParse(s, kDeltas, sizeof(kDeltas)));
  s.expiry = 1000;
  EXPECT_TRUE(s.active(1000));
  EXPECT_FALSE(s.active(1001));
  s.clear();
  EXPECT_FALSE(s.active(0));
}

TEST(TelemSub, AutoWatchesWhatIsThere) {
  TelemSub s; s.clear();
  telemSubAuto(s, kTelem, sizeof(kTelem));
  EXPECT_EQ(s.count, 3);
  EXPECT_TRUE(telemSubChanged(s, kTelem, sizeof(kTelem)));
  EXPECT_FALSE(telemSubChanged(s, kTelem, sizeof(kTelem)));
  telemSubAuto(s, kTelem, sizeof(kTelem));                           // idempotent
  EXPECT_EQ(s.count, 3);
  uint8_t t[sizeof(kTelem)]; memcpy(t, kTelem, sizeof(t));
  put16(&t[6], 218);                                                 // +0.3 C < 0.5 default
  EXPECT_FALSE(telemSubChanged(s, t, sizeof(t)));
  put16(&t[6], 222);                                                 // +0.7 C from 21.5
  EXPECT_TRUE(telemSubChanged(s, t, sizeof(t)));
}

TEST(TelemSub, AutoStopsAtTheCapAndOnGarbage) {
  TelemSub s; s.clear();
  uint8_t big[TELEM_SUB_MAX_ENTRIES * 4 + 8];
  for (int i = 0; i < TELEM_SUB_MAX_ENTRIES + 2; i++) { big[i*4]=i+1; big[i*4+1]=LPP_VOLTAGE; big[i*4+2]=1; big[i*4+3]=0; }
  telemSubAuto(s, big, sizeof(big));
  EXPECT_EQ(s.count, TELEM_SUB_MAX_ENTRIES);
  TelemSub g; g.clear();
  uint8_t junk[] = {1, 250, 1, 2, 3};
  telemSubAuto(g, junk, sizeof(junk));
  EXPECT_EQ(g.count, 0);
}

int main(int argc, char **argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
