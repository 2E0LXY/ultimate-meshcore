#include <gtest/gtest.h>
#include <helpers/umc/UmcBootId.h>

using namespace umcboot;

static int g_calls = 0;
static uint32_t fakeRng() { g_calls++; return g_calls == 1 ? 0x00ABCDEFu : 0x12345678u; }

TEST(BootId, MadeOnceThenStable) {
  resetForTest();
  g_calls = 0;
  EXPECT_EQ(0x00ABCDEF12345678ull, bootId(fakeRng));
  EXPECT_EQ(0x00ABCDEF12345678ull, bootId(fakeRng));
  EXPECT_EQ(0x00ABCDEF12345678ull, bootId());
  EXPECT_EQ(2, g_calls);   // two 32-bit draws, once
}

TEST(BootId, HexIsSixteenUppercaseDigits) {
  char s[17];
  toHex(0x00ABCDEF12345678ull, s);
  EXPECT_STREQ("00ABCDEF12345678", s);
  toHex(0, s);
  EXPECT_STREQ("0000000000000000", s);
  toHex(0xFFFFFFFFFFFFFFFFull, s);
  EXPECT_STREQ("FFFFFFFFFFFFFFFF", s);
  toHex(1, s);
  EXPECT_STREQ("0000000000000001", s);
}

TEST(BootId, DefaultRngVariesBetweenBoots) {
  uint64_t seen[8];
  bool differ = false;
  for (int i = 0; i < 8; i++) {
    resetForTest();
    seen[i] = bootId();
    if (i && seen[i] != seen[0]) differ = true;
  }
  EXPECT_TRUE(differ);
}

int main(int argc, char** argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
