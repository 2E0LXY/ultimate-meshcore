#include <gtest/gtest.h>
#include <helpers/umc/UmcTrial.h>

using namespace umctrial;

TEST(TrialParse, GoodAndBad) {
  Args a;
  EXPECT_EQ(R_OK, parse("60 advert.interval 120", a));
  EXPECT_EQ(60u, a.secs);
  EXPECT_STREQ("advert.interval", a.key);
  EXPECT_STREQ("120", a.value);
  EXPECT_EQ(R_OK, parse("  30   txdelay   0.5", a));
  EXPECT_STREQ("0.5", a.value);
  EXPECT_EQ(R_SECS, parse("29 af 1", a));
  EXPECT_EQ(R_SECS, parse("3601 af 1", a));
  EXPECT_EQ(R_OK, parse("3600 af 1", a));
  EXPECT_EQ(R_FORMAT, parse("", a));
  EXPECT_EQ(R_FORMAT, parse("abc af 1", a));
  EXPECT_EQ(R_FORMAT, parse("60x af 1", a));
  EXPECT_EQ(R_FORMAT, parse("60", a));
  EXPECT_EQ(R_FORMAT, parse("60 af", a));
  EXPECT_EQ(R_FORMAT, parse("-5 af 1", a));
  EXPECT_EQ(R_FORMAT, parse(nullptr, a));
}

TEST(TrialParse, RejectsUnsafeKeys) {
  Args a;
  for (const char* k : {"wifi.pwd", "wifi.ssid", "password", "guest.password", "prv.key", "mqtt.custom.password", "mqtt.control.key",
                        "name", "repeat", "bridge.secret", "ap.password", "pin", "setperm", "radio.fem.rxgain", "freq", "radio", "tx", "bw", "sf", "cr", "int.thresh", "region", "mqtt.custom.host", "mqtt.custom.password", "mqtt.owner", "set", "ap.mode"}) {
    char buf[100];
    snprintf(buf, sizeof(buf), "60 %s x", k);
    EXPECT_EQ(R_KEY, parse(buf, a)) << k;
  }
  EXPECT_EQ(R_KEY, parse("60 flood.maxx 1", a));   // exact match only
  EXPECT_EQ(R_KEY, parse("60 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1", a));
}

TEST(TrialParse, ValueMustBePrintableAndFit) {
  Args a;
  EXPECT_EQ(R_FORMAT, parse("60 af 1\n", a));
  EXPECT_EQ(R_FORMAT, parse((std::string("60 af ") + std::string(70, '1')).c_str(), a));
}

TEST(Trial, StartKeepRevert) {
  Trial t;
  EXPECT_FALSE(t.active());
  EXPECT_EQ(R_OK, t.begin(1000, 60, "af"));
  EXPECT_TRUE(t.active());
  EXPECT_STREQ("af", t.key());
  EXPECT_EQ(60u, t.remainingSecs(1000));
  EXPECT_EQ(30u, t.remainingSecs(31000));
  EXPECT_EQ(R_OK, t.finish());     // keep or revert
  EXPECT_FALSE(t.active());
  EXPECT_EQ(R_NONE, t.finish());
  EXPECT_EQ(0u, t.remainingSecs(1000));
  EXPECT_FALSE(t.expired(10000000));
}

TEST(Trial, Timeout) {
  Trial t;
  t.begin(5000, 30, "advert.interval");
  EXPECT_FALSE(t.expired(5000));
  EXPECT_FALSE(t.expired(34999));
  EXPECT_TRUE(t.expired(35000));
  EXPECT_TRUE(t.expired(99999));
  EXPECT_EQ(0u, t.remainingSecs(40000));
}

TEST(Trial, MillisWrap) {
  Trial t;
  const uint32_t start = 0xFFFFFFFFu - 10000u;      // 10 s before millis() wraps
  EXPECT_EQ(R_OK, t.begin(start, 60, "advert.interval"));     // deadline wraps to 50 s past zero
  EXPECT_FALSE(t.expired(start + 5000));
  EXPECT_FALSE(t.expired(0));                       // just wrapped
  EXPECT_FALSE(t.expired(49000));
  EXPECT_TRUE(t.expired(50000));
  EXPECT_EQ(50u, t.remainingSecs(0));
}

TEST(Trial, RejectsSecondUnknownAndBadSecs) {
  Trial t;
  EXPECT_EQ(R_KEY, t.begin(0, 60, "wifi.pwd"));
  EXPECT_EQ(R_KEY, t.begin(0, 60, nullptr));
  EXPECT_EQ(R_SECS, t.begin(0, 10, "af"));
  EXPECT_EQ(R_SECS, t.begin(0, 4000, "af"));
  EXPECT_FALSE(t.active());
  EXPECT_EQ(R_OK, t.begin(0, 60, "af"));
  EXPECT_EQ(R_BUSY, t.begin(0, 60, "advert.interval"));
  EXPECT_STREQ("af", t.key());                       // the first trial is untouched
}

struct FakePrefs {
  float airtime_factor = 0.5f, rx_delay_base = 1, tx_delay_factor = 0.5f, direct_tx_delay_factor = 0.3f;
  uint8_t advert_interval = 60, flood_advert_interval = 12, flood_max = 64, flood_max_unscoped = 8, flood_max_advert = 8;
  uint8_t agc_reset_interval = 10, multi_acks = 1;
};

TEST(Snapshot, RestoresExactlyAndReadsBack) {
  FakePrefs p;
  Snapshot s;
  capture(p, s);
  p.airtime_factor = 9.1f; p.advert_interval = 0; p.flood_max = 1; p.multi_acks = 0; p.agc_reset_interval = 0; p.rx_delay_base = 7;
  Snapshot mid;
  capture(p, mid);
  EXPECT_FALSE(same(mid, s));
  restore(p, s);
  Snapshot back;
  capture(p, back);
  EXPECT_TRUE(same(back, s));
  FakePrefs q;
  EXPECT_EQ(q.airtime_factor, p.airtime_factor);   // exact, no round trip through text
  EXPECT_EQ(q.advert_interval, p.advert_interval);
  EXPECT_EQ(q.flood_max, p.flood_max);
}

TEST(Snapshot, SaveWhileOnTrialWritesOriginals) {
  // what MyMesh::savePrefs does while a trial runs: swap the originals in, save, swap the trial back
  FakePrefs p;
  Snapshot orig;
  capture(p, orig);
  p.flood_max = 3;                     // the trial value
  Snapshot live;
  capture(p, live);
  restore(p, orig);
  FakePrefs written = p;               // "saved"
  restore(p, live);
  EXPECT_EQ(64, written.flood_max);
  EXPECT_EQ(3, p.flood_max);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
