#include <gtest/gtest.h>
#define UMC_TRIAL_STD_MUTEX 1   // a real lock on the computer, so the threaded test means something
#include <helpers/umc/UmcTrial.h>
#include <atomic>
#include <thread>

using namespace umctrial;

TEST(TrialParse, GoodAndBad) {
  Args a;
  EXPECT_EQ(TR_OK, parse("60 advert.interval 120", a));
  EXPECT_EQ(60u, a.secs);
  EXPECT_STREQ("advert.interval", a.key);
  EXPECT_STREQ("120", a.value);
  EXPECT_EQ(TR_OK, parse("  30   txdelay   0.5", a));
  EXPECT_STREQ("0.5", a.value);
  EXPECT_EQ(TR_SECS, parse("29 af 1", a));
  EXPECT_EQ(TR_SECS, parse("3601 af 1", a));
  EXPECT_EQ(TR_OK, parse("3600 af 1", a));
  EXPECT_EQ(TR_FORMAT, parse("", a));
  EXPECT_EQ(TR_FORMAT, parse("abc af 1", a));
  EXPECT_EQ(TR_FORMAT, parse("60x af 1", a));
  EXPECT_EQ(TR_FORMAT, parse("60", a));
  EXPECT_EQ(TR_FORMAT, parse("60 af", a));
  EXPECT_EQ(TR_FORMAT, parse("-5 af 1", a));
  EXPECT_EQ(TR_FORMAT, parse(nullptr, a));
}

TEST(TrialParse, RejectsUnsafeKeys) {
  Args a;
  for (const char* k : {"wifi.pwd", "wifi.ssid", "password", "guest.password", "prv.key", "mqtt.custom.password", "mqtt.control.key",
                        "name", "repeat", "bridge.secret", "ap.password", "pin", "setperm", "radio.fem.rxgain", "freq", "radio", "tx", "bw", "sf", "cr", "int.thresh", "region", "mqtt.custom.host", "mqtt.custom.password", "mqtt.owner", "set", "ap.mode"}) {
    char buf[100];
    snprintf(buf, sizeof(buf), "60 %s x", k);
    EXPECT_EQ(TR_KEY, parse(buf, a)) << k;
  }
  EXPECT_EQ(TR_KEY, parse("60 flood.maxx 1", a));   // exact match only
  EXPECT_EQ(TR_KEY, parse("60 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1", a));
}

TEST(TrialParse, ValueMustBePrintableAndFit) {
  Args a;
  EXPECT_EQ(TR_FORMAT, parse("60 af 1\n", a));
  EXPECT_EQ(TR_FORMAT, parse((std::string("60 af ") + std::string(70, '1')).c_str(), a));
}

TEST(Trial, StartKeepRevert) {
  Trial t;
  EXPECT_FALSE(t.active());
  EXPECT_EQ(TR_OK, t.begin(1000, 60, "af"));
  EXPECT_TRUE(t.active());
  EXPECT_STREQ("af", t.key());
  EXPECT_EQ(60u, t.remainingSecs(1000));
  EXPECT_EQ(30u, t.remainingSecs(31000));
  EXPECT_EQ(TR_OK, t.finish());     // keep or revert
  EXPECT_FALSE(t.active());
  EXPECT_EQ(TR_NONE, t.finish());
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
  EXPECT_EQ(TR_OK, t.begin(start, 60, "advert.interval"));     // deadline wraps to 50 s past zero
  EXPECT_FALSE(t.expired(start + 5000));
  EXPECT_FALSE(t.expired(0));                       // just wrapped
  EXPECT_FALSE(t.expired(49000));
  EXPECT_TRUE(t.expired(50000));
  EXPECT_EQ(50u, t.remainingSecs(0));
}

TEST(Trial, RejectsSecondUnknownAndBadSecs) {
  Trial t;
  EXPECT_EQ(TR_KEY, t.begin(0, 60, "wifi.pwd"));
  EXPECT_EQ(TR_KEY, t.begin(0, 60, nullptr));
  EXPECT_EQ(TR_SECS, t.begin(0, 10, "af"));
  EXPECT_EQ(TR_SECS, t.begin(0, 4000, "af"));
  EXPECT_FALSE(t.active());
  EXPECT_EQ(TR_OK, t.begin(0, 60, "af"));
  EXPECT_EQ(TR_BUSY, t.begin(0, 60, "advert.interval"));
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

TEST(Snapshot, ReadBackDetectsAnyFieldMismatch) {
  // a restore that did not take (one field differs) must be reported, not assumed good
  FakePrefs p;
  Snapshot orig;
  capture(p, orig);
  FakePrefs bad = p;
  bad.multi_acks = 0;
  Snapshot b1;
  capture(bad, b1);
  EXPECT_FALSE(same(b1, orig));
  bad = p; bad.rx_delay_base = 1.0001f;
  capture(bad, b1);
  EXPECT_FALSE(same(b1, orig));
  bad = p; bad.flood_max_advert = 9;
  capture(bad, b1);
  EXPECT_FALSE(same(b1, orig));
}

// ---- a stand-in for MyMesh + CommonCLI: same shape as the device code, so the state machine is exercised
// as it is wired (SetScope around the command, savePrefs through umctrial::save, normalisation on save) ----
struct Node {
  FakePrefs p;                 // live
  FakePrefs flash;             // what the file holds
  Controller c;
  int local_rearm = 0, flood_rearm = 0;
  int writes = 0;

  // CommonCLI::savePrefs(): tidy advert_interval, then the callback
  void cliSave() {
    if (p.advert_interval * 2 < 60) p.advert_interval = 0;
    save(c, p, [this]() { flash = p; writes++; });
  }
  // CommonCLI::handleSetCmd for the keys we need
  const char* setCmd(const char* key, const char* val) {
    if (strcmp(key, "af") == 0) { p.airtime_factor = (float)atof(val); cliSave(); return "OK"; }
    if (strcmp(key, "flood.max") == 0) { p.flood_max = (uint8_t)atoi(val); cliSave(); return "OK"; }
    if (strcmp(key, "multi.acks") == 0) { p.multi_acks = (uint8_t)atoi(val); cliSave(); return "OK"; }
    if (strcmp(key, "advert.interval") == 0) {
      int m = atoi(val);
      if ((m > 0 && m < 60) || m > 240) return "Error: interval range is 60-240 minutes";
      p.advert_interval = (uint8_t)(m / 2); local_rearm++; cliSave(); return "OK";
    }
    if (strcmp(key, "name") == 0) { cliSave(); return "OK"; }   // not a trial key: saves, so tidies advert_interval
    return "Unknown config";
  }
  // MyMesh::handleCommand for `set`
  std::string command(const char* cmd) {
    SetScope<FakePrefs> scope(c, p, cmd);
    if (scope.refused()) return "REFUSED";
    char k[28], v[64] = "";
    setKey(cmd, k, sizeof(k));
    const char* sp = strchr(cmd + 4, ' ');
    if (sp) { while (*sp == ' ') sp++; snprintf(v, sizeof(v), "%s", sp); }
    return setCmd(k, v);
  }
  auto rearm() { return [this](bool l, bool f) { if (l) local_rearm++; if (f) flood_rearm++; }; }
  Result tryset(uint32_t now, const char* args) {
    Args a;
    Result r = parse(args, a);
    if (r != TR_OK) return r;
    char cmd[100];
    snprintf(cmd, sizeof(cmd), "set %s %s", a.key, a.value);
    SetScope<FakePrefs> scope(c, p, "tryset x");
    return start(c, p, now, a, [&]() { return command(cmd) == "OK"; }, rearm());
  }
  Result keepIt() {
    SetScope<FakePrefs> scope(c, p, "tryset keep");
    return keep(c, [this]() { cliSave(); });
  }
  bool revert() { SetScope<FakePrefs> scope(c, p, "tryset revert"); return undo(c, p, rearm()); }
  bool expireAt(uint32_t now) { return expire(c, p, now, rearm()); }
};

TEST(TrialFlow, AfTrialDoesNotLeaveAdvertIntervalZeroed) {
  // finding 1: `set af` tidies advert_interval (< 1 h -> 0); that must not stick live during or after the trial
  Node n;
  n.p.advert_interval = 20;            // 40 minutes: the tidy would zero it
  n.flash = n.p;
  EXPECT_EQ(TR_OK, n.tryset(0, "60 af 3"));
  EXPECT_EQ(3.0f, n.p.airtime_factor);
  EXPECT_EQ(20, n.p.advert_interval);  // live value untouched by the tidy
  EXPECT_EQ(0, n.writes);              // nothing written
  EXPECT_TRUE(n.revert());
  EXPECT_EQ(20, n.p.advert_interval);
  EXPECT_EQ(0.5f, n.p.airtime_factor);
  EXPECT_EQ(0, n.writes);
  EXPECT_EQ(20, n.flash.advert_interval);
}

TEST(TrialFlow, ExpiryAndRevertRearmBothAdvertTimersWhenIntervalsMove) {
  Node n;
  EXPECT_EQ(TR_OK, n.tryset(0, "60 advert.interval 120"));
  EXPECT_EQ(60, n.p.advert_interval);
  const int l0 = n.local_rearm, f0 = n.flood_rearm;
  EXPECT_FALSE(n.expireAt(59999));
  EXPECT_TRUE(n.expireAt(60000));
  EXPECT_EQ(60, n.p.advert_interval);               // 60 was the original (FakePrefs default)
  EXPECT_EQ(l0 + 1, n.local_rearm);
  EXPECT_EQ(f0 + 1, n.flood_rearm);                 // both re-armed
  EXPECT_FALSE(n.c.trial.active());
  Node m;
  EXPECT_EQ(TR_OK, m.tryset(0, "60 advert.interval 180"));
  EXPECT_EQ(90, m.p.advert_interval);
  EXPECT_TRUE(m.revert());
  EXPECT_EQ(60, m.p.advert_interval);
  EXPECT_EQ(2, m.local_rearm);                      // once by `set`, once by the undo
  EXPECT_EQ(1, m.flood_rearm);
}

TEST(TrialFlow, KeepSavesLikePlainSet) {
  Node a, b;
  a.p.advert_interval = b.p.advert_interval = 20;
  a.flash = b.flash = a.p;
  EXPECT_EQ(TR_OK, a.tryset(0, "60 af 3"));
  EXPECT_EQ(TR_OK, a.keepIt());
  b.command("set af 3");                            // the plain command
  EXPECT_EQ(b.flash.airtime_factor, a.flash.airtime_factor);
  EXPECT_EQ(b.flash.advert_interval, a.flash.advert_interval);   // both tidy the same way
  EXPECT_EQ(0, a.flash.advert_interval);
  EXPECT_FALSE(a.c.trial.active());
  EXPECT_EQ(TR_NONE, a.keepIt());
}

TEST(TrialFlow, ExpiredThenKeepNeverSavesTheTrialValue) {
  // finding 2, the interleaving "expiry first, then keep"
  Node n;
  n.flash = n.p;
  EXPECT_EQ(TR_OK, n.tryset(0, "30 flood.max 3"));
  EXPECT_TRUE(n.expireAt(30000));
  EXPECT_EQ(TR_NONE, n.keepIt());
  EXPECT_EQ(64, n.p.flood_max);
  EXPECT_EQ(64, n.flash.flood_max);
  EXPECT_EQ(0, n.writes);
}

TEST(TrialFlow, KeepThenExpiryLeavesTheKeptValue) {
  Node n;
  n.flash = n.p;
  EXPECT_EQ(TR_OK, n.tryset(0, "30 flood.max 3"));
  EXPECT_EQ(TR_OK, n.keepIt());
  EXPECT_FALSE(n.expireAt(1000000));                // trial is over: expiry has nothing to undo
  EXPECT_EQ(3, n.p.flood_max);
  EXPECT_EQ(3, n.flash.flood_max);
}

TEST(TrialFlow, SecondTrySetWhileOneRunsIsRefusedAndFirstIntact) {
  Node n;
  EXPECT_EQ(TR_OK, n.tryset(0, "60 flood.max 3"));
  EXPECT_EQ(TR_BUSY, n.tryset(1, "60 af 3"));
  EXPECT_EQ(3, n.p.flood_max);
  EXPECT_EQ(0.5f, n.p.airtime_factor);
  EXPECT_STREQ("flood.max", n.c.trial.key());
}

TEST(TrialFlow, ExpiryDoesNotWaitForTheLockAndRetriesLater) {
  Node n;
  EXPECT_EQ(TR_OK, n.tryset(0, "30 flood.max 3"));
  std::atomic<bool> held(false), release(false);
  std::thread holder([&]() {                        // a web command holding the lock across a flash write
    Guard g(n.c.lock);
    held = true;
    while (!release) std::this_thread::yield();
  });
  while (!held) std::this_thread::yield();
  EXPECT_FALSE(n.expireAt(99999));                  // skipped, not blocked
  release = true;
  holder.join();
  EXPECT_TRUE(n.c.trial.active());
  EXPECT_TRUE(n.expireAt(99999));                   // next pass
  EXPECT_EQ(64, n.p.flood_max);
}

TEST(TrialFlow, SetDuringTrial) {
  Node n;
  n.p.advert_interval = 20;
  n.flash = n.p;
  EXPECT_EQ(TR_OK, n.tryset(0, "60 flood.max 3"));
  // snapshot settings are refused, whichever spacing
  EXPECT_EQ("REFUSED", n.command("set af 2"));
  EXPECT_EQ("REFUSED", n.command("set flood.max 9"));
  EXPECT_EQ("REFUSED", n.command("set   advert.interval 120"));
  EXPECT_EQ(3, n.p.flood_max);
  // anything else may run (recovery commands), and its save does not leak the trial value or the tidy
  EXPECT_EQ("OK", n.command("set name x"));
  EXPECT_EQ(64, n.flash.flood_max);                 // the file still holds the original
  EXPECT_EQ(20, n.flash.advert_interval);           // and was not tidied by this save
  EXPECT_EQ(3, n.p.flood_max);                      // the trial value is still live
  EXPECT_EQ(20, n.p.advert_interval);               // tidy undone live too
  EXPECT_TRUE(n.c.trial.active());
  EXPECT_TRUE(n.revert());
  EXPECT_EQ(64, n.p.flood_max);
  EXPECT_EQ(20, n.p.advert_interval);
  EXPECT_EQ("OK", n.command("set af 2"));           // after the trial, set works as ever
}

TEST(TrialFlow, RefusedSetByTrialLeavesNothingChanged) {
  Node n;
  n.flash = n.p;
  EXPECT_EQ(TR_APPLY, n.tryset(0, "60 advert.interval 45"));   // the set code refuses 45 minutes
  EXPECT_FALSE(n.c.trial.active());
  EXPECT_EQ(60, n.p.advert_interval);
  EXPECT_FALSE(n.c.applying);
  EXPECT_EQ(0, n.writes);
}

TEST(TrialFlow, TimerStartFailureRestoresEverything) {
  // finding 6: Trial::begin refused (here: seconds out of range, bypassing parse) -> put everything back
  Node n;
  n.p.advert_interval = 20;
  n.flash = n.p;
  Args a;
  memset(&a, 0, sizeof(a));
  a.secs = 5;
  strcpy(a.key, "advert.interval");
  strcpy(a.value, "120");
  const Result r = start(n.c, n.p, 0, a, [&]() { return n.command("set advert.interval 120") == "OK"; }, n.rearm());
  EXPECT_EQ(TR_SECS, r);
  EXPECT_FALSE(n.c.trial.active());
  EXPECT_EQ(20, n.p.advert_interval);
  EXPECT_FALSE(n.c.applying);
  EXPECT_TRUE(n.local_rearm >= 2 && n.flood_rearm >= 1);   // timers put back too
}

TEST(TrialFlow, ConcurrentTrialsNeverReachFlash) {
  // finding 2: web task starting/reverting/saving while the loop task expires and saves. A reverted or
  // expired trial value (flood.max 3) must never be in the file; only a kept one may.
  Node n;
  n.flash = n.p;
  std::atomic<bool> stop(false);
  std::atomic<int> bad(0);
  std::thread web([&]() {
    uint32_t t = 0;
    while (!stop) {
      n.tryset(t, "30 flood.max 3");
      std::this_thread::yield();
      n.revert();
      n.command("set name x");
      t += 1;
    }
  });
  std::thread web2([&]() {                           // a second web client
    while (!stop) { n.tryset(0, "30 flood.max 3"); n.command("set name y"); n.revert(); }
  });
  std::thread loop([&]() {
    while (!stop) { n.expireAt(1000000); }
  });
  std::thread saver([&]() {
    while (!stop) {   // MyMesh::savePrefs() reached from some other command or task
      save(n.c, n.p, [&]() { n.flash = n.p; });
      Guard g(n.c.lock);
      if (n.flash.flood_max != 64) bad++;
    }
  });
  std::this_thread::sleep_for(std::chrono::milliseconds(400));
  stop = true;
  web.join(); web2.join(); loop.join(); saver.join();
  n.revert();
  EXPECT_EQ(0, bad.load());
  EXPECT_EQ(64, n.flash.flood_max);
  EXPECT_EQ(64, n.p.flood_max);
  EXPECT_FALSE(n.c.applying);
}

TEST(TrialLimits, ValuesAreRangeChecked) {
  Args a;
  EXPECT_EQ(TR_RANGE, parse("60 multi.acks 300", a));
  EXPECT_STREQ("Err - multi.acks must be 0 or 1", rangeText(a.key));
  EXPECT_EQ(TR_RANGE, parse("60 multi.acks 2", a));
  EXPECT_EQ(TR_RANGE, parse("60 multi.acks -1", a));
  EXPECT_EQ(TR_RANGE, parse("60 multi.acks 0.5", a));
  EXPECT_EQ(TR_OK, parse("60 multi.acks 0", a));
  EXPECT_EQ(TR_OK, parse("60 multi.acks 1", a));
  EXPECT_EQ(TR_RANGE, parse("60 flood.max 0", a));
  EXPECT_EQ(TR_RANGE, parse("60 flood.max 65", a));
  EXPECT_EQ(TR_RANGE, parse("60 flood.max abc", a));
  EXPECT_EQ(TR_OK, parse("60 flood.max 1", a));
  EXPECT_EQ(TR_OK, parse("60 flood.max 64", a));
  EXPECT_EQ(TR_RANGE, parse("60 flood.max.advert 0", a));
  EXPECT_EQ(TR_RANGE, parse("60 flood.max.unscoped 0", a));
  EXPECT_EQ(TR_RANGE, parse("60 dutycycle 1", a));
  EXPECT_EQ(TR_RANGE, parse("60 dutycycle 9.9", a));
  EXPECT_EQ(TR_OK, parse("60 dutycycle 10", a));
  EXPECT_EQ(TR_OK, parse("60 dutycycle 100", a));
  EXPECT_EQ(TR_RANGE, parse("60 dutycycle 101", a));
  EXPECT_EQ(TR_RANGE, parse("60 af 9.5", a));
  EXPECT_EQ(TR_RANGE, parse("60 af -1", a));
  EXPECT_EQ(TR_OK, parse("60 af 0", a));
  EXPECT_EQ(TR_RANGE, parse("60 rxdelay 11", a));
  EXPECT_EQ(TR_OK, parse("60 rxdelay 10", a));
  EXPECT_EQ(TR_RANGE, parse("60 txdelay 1.5", a));
  EXPECT_EQ(TR_RANGE, parse("60 direct.txdelay 2", a));
  EXPECT_EQ(TR_OK, parse("60 direct.txdelay 1", a));
  EXPECT_EQ(TR_RANGE, parse("60 agc.reset.interval 300000", a));
  EXPECT_EQ(TR_OK, parse("60 agc.reset.interval 600", a));
  EXPECT_EQ(TR_RANGE, parse("60 rxdelay nan", a));
  EXPECT_EQ(TR_RANGE, parse("60 rxdelay 1e999", a));
  EXPECT_EQ(TR_OK, parse("60 advert.interval 120", a));   // left to the ordinary set code
}

TEST(TrialKeys, ChunksFitTheReplyAndCoverEveryKey) {
  const char* const* t;
  const size_t n = keyTable(&t);
  char out[160];
  std::string all;
  unsigned pages = keyChunk(1, out, sizeof(out));
  EXPECT_TRUE(pages >= 2);
  for (unsigned pg = 1; pg <= pages; pg++) {
    memset(out, 0, sizeof(out));
    EXPECT_EQ(pages, keyChunk(pg, out, sizeof(out)));
    EXPECT_TRUE(strlen(out) < 157);
    all += out;
  }
  for (size_t i = 0; i < n; i++) EXPECT_TRUE(all.find(t[i]) != std::string::npos);
  EXPECT_EQ(0u, keyChunk(0, out, sizeof(out)));
  EXPECT_EQ(0u, keyChunk(pages + 1, out, sizeof(out)));
  EXPECT_EQ(0u, keyChunk(1, out, 50));                    // buffer too small: refuses, no overflow
  EXPECT_TRUE(strlen(errText(TR_KEY)) < 157);             // the unknown-key reply is whole, not cut
  EXPECT_TRUE(std::string(errText(TR_KEY)).find("tryset keys") != std::string::npos);
  // each key sits whole on exactly one page
  for (size_t i = 0; i < n; i++) {
    int hits = 0;
    for (unsigned pg = 1; pg <= pages; pg++) {
      keyChunk(pg, out, sizeof(out));
      const std::string s(out);
      const std::string needle = std::string(": ") + t[i];
      size_t pos = 0;
      while ((pos = s.find(t[i], pos)) != std::string::npos) {
        const bool startOk = pos >= 2 && (s.compare(pos - 2, 2, ": ") == 0 || s.compare(pos - 2, 2, ", ") == 0);
        const size_t e = pos + strlen(t[i]);
        const bool endOk = e == s.size() || s[e] == ',' || s[e] == ' ';
        if (startOk && endOk) hits++;
        pos = e;
      }
    }
    EXPECT_EQ(1, hits) << t[i];
  }
}

TEST(TrialSub, FormsAndTrailingSpaces) {
  unsigned pg;
  EXPECT_EQ(SUB_STATUS, subcommand("", &pg));
  EXPECT_EQ(SUB_STATUS, subcommand("  status  ", &pg));
  EXPECT_EQ(SUB_KEEP, subcommand("keep", &pg));
  EXPECT_EQ(SUB_KEEP, subcommand("keep ", &pg));
  EXPECT_EQ(SUB_KEEP, subcommand("  keep   ", &pg));
  EXPECT_EQ(SUB_REVERT, subcommand("revert ", &pg));
  EXPECT_EQ(SUB_START, subcommand("keep now", &pg));
  EXPECT_EQ(SUB_START, subcommand("keeper", &pg));
  EXPECT_EQ(SUB_START, subcommand("60 af 1", &pg));
  EXPECT_EQ(SUB_KEYS, subcommand("keys", &pg));
  EXPECT_EQ(1u, pg);
  EXPECT_EQ(SUB_KEYS, subcommand("keys 2 ", &pg));
  EXPECT_EQ(2u, pg);
  EXPECT_EQ(SUB_KEYS, subcommand("keys 0", &pg));
  EXPECT_EQ(0u, pg);
  Args a;
  EXPECT_EQ(TR_FORMAT, parse("keep now", a));
}

TEST(TrialScope, OnlySetAndTrysetTakeTheLock) {
  EXPECT_TRUE(isSet("set af 1"));
  EXPECT_FALSE(isSet("setx af 1"));
  EXPECT_FALSE(isSet("get af"));
  EXPECT_TRUE(isTryset("tryset"));
  EXPECT_TRUE(isTryset("tryset keep"));
  EXPECT_FALSE(isTryset("trysetx"));
  char k[28];
  setKey("set   flood.max  5", k, sizeof(k));
  EXPECT_STREQ("flood.max", k);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
