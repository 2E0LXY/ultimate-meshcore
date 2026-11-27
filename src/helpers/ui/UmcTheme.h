#pragma once
// UMC colour themes for the colour (RGB565) displays: T-Deck and other ST7789 / LGFX panels.
// Plain C++ with no hardware headers, so it is host-testable.
//
// The RGB888 values below are copied from docs/umc/theme/tokens.json (the single source of
// truth) and scripts/test_umc_theme.py checks that they still match. Do not edit one
// without the other. Monochrome OLED / e-paper drivers do not use this.
#include <stdint.h>
#include <string.h>

#define UMC_THEME_OVERVIEW 0
#define UMC_THEME_ANALYTICS 1
#define UMC_THEME_COUNT 2
#define UMC_THEME_DEFAULT UMC_THEME_OVERVIEW

// 0xRRGGBB -> RGB565 (top bits kept, as every Adafruit/LGFX 565 helper does).
constexpr uint16_t umcRgb565(uint32_t rgb) {
  return (uint16_t)((((rgb >> 16) & 0xF8) << 8) | (((rgb >> 8) & 0xFC) << 3) | ((rgb & 0xFF) >> 3));
}

struct UmcThemeTokens {            // RGB888, as in tokens.json
  const char* name;
  uint32_t page, surface, surface2, sidebar, card, border, chip, track, ink, muted, faint, accent, accentInk, navActive, navActiveInk, ok, okBg, warn, warnBg, bad, badBg;
  uint32_t series[8];
  uint8_t seriesCount;
};

struct UmcPalette {           // RGB565, what the display draws with
  const char* name;
  uint16_t page, surface, surface2, sidebar, card, border, chip, track, ink, muted, faint, accent, accentInk, navActive, navActiveInk, ok, okBg, warn, warnBg, bad, badBg;
  uint16_t series[8];
  uint8_t seriesCount;
};

static constexpr UmcThemeTokens kUmcThemeTokens[UMC_THEME_COUNT] = {
  {"overview", 0x05070C, 0x0E1626, 0x131C2E, 0x0F1522, 0x0A0C11, 0x1A2030, 0x1A1D24, 0x23262D, 0xFFFFFF, 0xA0A9BB, 0x808AA0, 0x2563EB, 0xFFFFFF, 0x2563EB, 0xFFFFFF, 0x22C55E, 0x0D2A1B, 0xF59E0B, 0x2B2108, 0xEF4444, 0x2B0F15, {0x4F46E5, 0x3B82F6, 0x06B6D4, 0x22D3EE, 0xA78BFA, 0xF59E0B, 0, 0}, 6},
  {"analytics", 0xF3F4F6, 0x0B0B0D, 0x0B0B0D, 0x0B0B0D, 0x111114, 0x1C1C21, 0x17171B, 0x232329, 0xF4F4F5, 0xA5A5AE, 0x84848E, 0x3B5BFF, 0xFFFFFF, 0x17171B, 0xFFFFFF, 0x22C55E, 0x0D2417, 0xF5A524, 0x2A2008, 0xEF4444, 0x2B0F15, {0x3B5BFF, 0x29B6F6, 0x22C55E, 0xF2784B, 0x7C5CFF, 0xEC4899, 0xF5A524, 0x14B8A6}, 8},
};

constexpr UmcPalette umcMakePalette(const UmcThemeTokens& t) {
  return UmcPalette{t.name,
    umcRgb565(t.page), umcRgb565(t.surface), umcRgb565(t.surface2), umcRgb565(t.sidebar), umcRgb565(t.card), umcRgb565(t.border), umcRgb565(t.chip), umcRgb565(t.track), umcRgb565(t.ink), umcRgb565(t.muted), umcRgb565(t.faint), umcRgb565(t.accent), umcRgb565(t.accentInk), umcRgb565(t.navActive), umcRgb565(t.navActiveInk), umcRgb565(t.ok), umcRgb565(t.okBg), umcRgb565(t.warn), umcRgb565(t.warnBg), umcRgb565(t.bad), umcRgb565(t.badBg),
    {umcRgb565(t.series[0]), umcRgb565(t.series[1]), umcRgb565(t.series[2]), umcRgb565(t.series[3]),
     umcRgb565(t.series[4]), umcRgb565(t.series[5]), umcRgb565(t.series[6]), umcRgb565(t.series[7])},
    t.seriesCount};
}

static constexpr UmcPalette kUmcPalettes[UMC_THEME_COUNT] = {
  umcMakePalette(kUmcThemeTokens[0]),
  umcMakePalette(kUmcThemeTokens[1]),
};

// Out-of-range values fall back to the default, so a corrupt pref can never index past the table.
inline const UmcPalette& umcPalette(int theme) {
  return kUmcPalettes[(theme >= 0 && theme < UMC_THEME_COUNT) ? theme : UMC_THEME_DEFAULT];
}

inline const char* umcThemeName(int theme) { return umcPalette(theme).name; }

// "overview" / "analytics" (any case). Returns the theme index, or -1 when not a theme name.
// A bare number is deliberately not accepted: `set theme <n>` already means the chat colour scheme.
inline int umcThemeParse(const char* s) {
  if (s == nullptr) return -1;
  while (*s == ' ') s++;
  char buf[16];
  size_t n = 0;
  while (s[n] && s[n] != ' ' && n < sizeof(buf) - 1) { char c = s[n]; buf[n] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; n++; }
  if (s[n] && s[n] != ' ') return -1;   // too long to be a name
  buf[n] = 0;
  for (int i = 0; i < UMC_THEME_COUNT; i++) {
    if (strcmp(buf, kUmcThemeTokens[i].name) == 0) return i;
  }
  return -1;
}
