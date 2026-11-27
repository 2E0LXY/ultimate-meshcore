#include <gtest/gtest.h>

#include <helpers/ui/UmcTheme.h>

// Expected values are RGB565 computed independently from docs/umc/theme/tokens.json.
struct Expect565 { const char* theme; int idx; uint16_t v[21]; uint16_t series[8]; int n; };

static const Expect565 kExpect[] = {
  {"overview", 0, {0x0021, 0x08A4, 0x10E5, 0x08A4, 0x0862, 0x1906, 0x18E4, 0x2125, 0xFFFF, 0xA557, 0x8454, 0x231D, 0xFFFF, 0x231D, 0xFFFF, 0x262B, 0x0943, 0xF4E1, 0x2901, 0xEA28, 0x2862}, {0x4A3C, 0x3C1E, 0x05BA, 0x269D, 0xA45F, 0xF4E1, 0x0000, 0x0000}, 6},
  {"analytics", 1, {0xF7BE, 0x0841, 0x0841, 0x0841, 0x1082, 0x18E4, 0x10A3, 0x2105, 0xF7BE, 0xA535, 0x8431, 0x3ADF, 0xFFFF, 0x10A3, 0xFFFF, 0x262B, 0x0922, 0xF524, 0x2901, 0xEA28, 0x2862}, {0x3ADF, 0x2DBE, 0x262B, 0xF3C9, 0x7AFF, 0xEA53, 0xF524, 0x15D4}, 8},
};

static uint16_t field(const UmcPalette& p, int k) {
  const uint16_t all[21] = {p.page, p.surface, p.surface2, p.sidebar, p.card, p.border, p.chip, p.track, p.ink, p.muted, p.faint, p.accent, p.accentInk, p.navActive, p.navActiveInk, p.ok, p.okBg, p.warn, p.warnBg, p.bad, p.badBg};
  return all[k];
}
static const char* const kKeys[21] = {"page", "surface", "surface2", "sidebar", "card", "border", "chip", "track", "ink", "muted", "faint", "accent", "accentInk", "navActive", "navActiveInk", "ok", "okBg", "warn", "warnBg", "bad", "badBg"};

TEST(UmcTheme, EveryTokenConvertsToExactRgb565) {
  for (const Expect565& e : kExpect) {
    const UmcPalette& p = umcPalette(e.idx);
    EXPECT_STREQ(e.theme, p.name);
    for (int k = 0; k < 21; k++) EXPECT_EQ(e.v[k], field(p, k)) << e.theme << " " << kKeys[k];
    EXPECT_EQ(e.n, p.seriesCount);
    for (int i = 0; i < 8; i++) EXPECT_EQ(e.series[i], p.series[i]) << e.theme << " series " << i;
  }
}

TEST(UmcTheme, ConverterEdgeValues) {
  EXPECT_EQ(0x0000, umcRgb565(0x000000));
  EXPECT_EQ(0xFFFF, umcRgb565(0xFFFFFF));
  EXPECT_EQ(0xF800, umcRgb565(0xFF0000));
  EXPECT_EQ(0x07E0, umcRgb565(0x00FF00));
  EXPECT_EQ(0x001F, umcRgb565(0x0000FF));
}

TEST(UmcTheme, ParseAcceptsNamesOnly) {
  EXPECT_EQ(UMC_THEME_OVERVIEW, umcThemeParse("overview"));
  EXPECT_EQ(UMC_THEME_ANALYTICS, umcThemeParse("analytics"));
  EXPECT_EQ(UMC_THEME_ANALYTICS, umcThemeParse("Analytics"));
  EXPECT_EQ(UMC_THEME_OVERVIEW, umcThemeParse("  OVERVIEW"));
  EXPECT_EQ(-1, umcThemeParse(""));
  EXPECT_EQ(-1, umcThemeParse(nullptr));
  EXPECT_EQ(-1, umcThemeParse("0"));          // numbers mean the chat colour scheme
  EXPECT_EQ(-1, umcThemeParse("dark"));
  EXPECT_EQ(-1, umcThemeParse("overviewx"));
  EXPECT_EQ(-1, umcThemeParse("overview-overview-overview"));
}

TEST(UmcTheme, OutOfRangeFallsBackToOverview) {
  EXPECT_STREQ("overview", umcThemeName(-1));
  EXPECT_STREQ("overview", umcThemeName(2));
  EXPECT_STREQ("overview", umcThemeName(255));
  EXPECT_STREQ("analytics", umcThemeName(1));
  EXPECT_EQ(UMC_THEME_OVERVIEW, UMC_THEME_DEFAULT);
}

int main(int argc, char **argv) {
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
