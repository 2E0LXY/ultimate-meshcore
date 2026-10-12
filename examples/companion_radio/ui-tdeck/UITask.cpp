#include "UITask.h"

#include <helpers/umc/UmcMapSink.h>

#include <Adafruit_ST7789.h>
#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>
#include <Fonts/FreeSansBold24pt7b.h>
#include <helpers/ui/ST7789LCDDisplay.h>

#include "../MyMesh.h"
#include "UmcSplash.h"
#include "target.h"

#include <WiFi.h>
#include <ctype.h>
#include <math.h>
#include <time.h>

// Setup tab pages and the things you can type into
enum SetupPage { SP_ROOT = 0, SP_DEVICE, SP_RADIO, SP_WIFI, SP_WIFI_PICK, SP_BLE, SP_REGION, SP_GPS, SP_FW,
                 SP_CHANNELS, SP_MESSAGING, SP_CONTACTS_CFG, SP_TELEMETRY, SP_CONSOLE, SP_DISPLAY };
enum SetupEdit { SE_NONE = 0, SE_NAME, SE_SSID, SE_PASSWORD, SE_PIN, SE_REGION, SE_CHANNEL, SE_COMMAND };

// ---- layout (320 x 240 landscape) ----
#define SCR_W 320
#define SCR_H 240
#define HDR_H 20
#define TAB_H 30
#define BODY_Y HDR_H
#define BODY_H (SCR_H - HDR_H - TAB_H)
#define COMPOSE_H 26

// ---- colour themes ----
// Nine schemes, like a phone messenger: the page colour, the two bubble colours and the
// text on them. Chosen in Setup > Display and kept in the device's settings.
struct UiTheme {
  const char* name;
  uint16_t bg, card, line, text, dim, accent, mine, mine_text, theirs, theirs_text;
};
static const UiTheme kThemes[] = {
  {"Green",   0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0x0568, 0x0568, 0xFFFF, 0x2104, 0xE73C},
  {"Blue",    0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0x1C9F, 0x1C9F, 0xFFFF, 0x2104, 0xE73C},
  {"Teal",    0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0x045F, 0x045F, 0xFFFF, 0x2104, 0xE73C},
  {"Purple",  0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0x7819, 0x7819, 0xFFFF, 0x2104, 0xE73C},
  {"Olive",   0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0x5B2A, 0x5B2A, 0xFFFF, 0x2104, 0xE73C},
  {"Orange",  0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0xC9A0, 0xC9A0, 0xFFFF, 0x2104, 0xE73C},
  {"Rose",    0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0xB2CC, 0xB2CC, 0xFFFF, 0x2104, 0xE73C},
  {"Magenta", 0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0xC80E, 0xC80E, 0xFFFF, 0x2104, 0xE73C},
  {"Grey",    0x0861, 0x18E3, 0x3186, 0xE73C, 0x8410, 0x8410, 0x8410, 0xFFFF, 0x2104, 0xE73C},
};
static const int kThemeCount = sizeof(kThemes) / sizeof(kThemes[0]);
static int g_theme = 0;
#define TH (kThemes[g_theme])

// ---- colours (RGB565) ----
#define C_BG 0x0861
#define C_CARD 0x18E3
#define C_LINE 0x3186
#define C_TXT 0xE73C
#define C_DIM 0x8410
#define C_ACC 0x2D7F
#define C_OK 0x3DE6
#define C_WARN 0xFC60
#define C_BAD 0xF9A6
#define C_ME 0x1C9F

static Adafruit_ST7789* gfx() { return display.gfx(); }

static void fill(int x, int y, int w, int h, uint16_t c) { gfx()->fillRect(x, y, w, h, c); }

// ---------------------------------------------------------------------------------------
// Typography. Every screen uses one family in three sizes, so nothing is drawn with the
// blocky 5x7 built-in font any more.
static const GFXfont* const F_SMALL = &FreeSans9pt7b;      // lists, labels, values, buttons
static const GFXfont* const F_MED = &FreeSansBold12pt7b;   // the figure a card is about
static const GFXfont* const F_BIG = &FreeSansBold24pt7b;   // the clock

static const GFXfont* fontFor(int size) { return size >= 4 ? F_BIG : size >= 2 ? F_MED : F_SMALL; }

// ---------------------------------------------------------------------------------------
// Station names arrive as UTF-8 and often carry an emoji or an accented letter, neither of
// which the fonts above hold - they stop at plain ASCII, so the raw bytes came out as a
// run of nonsense. Names are folded first: letters lose their accents, and symbols become
// one of these little 12x12 icons.
enum {
  IC_NONE = 0,
  IC_DISH,
  IC_TOWER,
  IC_SUN,
  IC_BOLT,
  IC_HOUSE,
  IC_PIN,
  IC_STAR,
  IC_HEART,
  IC_RADIO,
  IC_CAR,
  IC_PLANE,
  IC_GLOBE,
  IC_PAW,
  IC_FACE,
  IC_CHECK,
  IC_DEG,
  IC_FLAG,
  IC_DOT,
  IC_COUNT
};

static const uint8_t kIconBits[IC_COUNT - 1][24] = {
    { 0x0F, 0x00, 0x30, 0x80, 0x40, 0x40, 0x40, 0x40, 0x40, 0xC0, 0x21, 0x00, 0x1E, 0x00, 0x04, 0x00, 0x04, 0x00, 0x0E, 0x00, 0x1F, 0x00, 0x3F, 0x80 },   // DISH
    { 0x06, 0x00, 0x06, 0x00, 0x09, 0x00, 0x0F, 0x00, 0x10, 0x80, 0x16, 0x80, 0x20, 0x40, 0x2F, 0x40, 0x40, 0x20, 0x4F, 0x20, 0x80, 0x10, 0xFF, 0xF0 },   // TOWER
    { 0x06, 0x00, 0x46, 0x20, 0x20, 0x40, 0x0F, 0x00, 0x1F, 0x80, 0xDF, 0xB0, 0xDF, 0xB0, 0x1F, 0x80, 0x0F, 0x00, 0x20, 0x40, 0x46, 0x20, 0x06, 0x00 },   // SUN
    { 0x00, 0x00, 0x07, 0x00, 0x0E, 0x00, 0x1C, 0x00, 0x3F, 0x00, 0x07, 0x00, 0x0E, 0x00, 0x1C, 0x00, 0x38, 0x00, 0x70, 0x00, 0x20, 0x00, 0x00, 0x00 },   // BOLT
    { 0x06, 0x00, 0x0F, 0x00, 0x1F, 0x80, 0x3F, 0xC0, 0x7F, 0xE0, 0xFF, 0xF0, 0x30, 0xC0, 0x30, 0xC0, 0x36, 0xC0, 0x36, 0xC0, 0x3F, 0xC0, 0x00, 0x00 },   // HOUSE
    { 0x1E, 0x00, 0x3F, 0x00, 0x61, 0x80, 0x6D, 0x80, 0x6D, 0x80, 0x61, 0x80, 0x3F, 0x00, 0x1E, 0x00, 0x0C, 0x00, 0x0C, 0x00, 0x04, 0x00, 0x04, 0x00 },   // PIN
    { 0x06, 0x00, 0x06, 0x00, 0x0F, 0x00, 0xFF, 0xF0, 0x7F, 0xE0, 0x3F, 0xC0, 0x1F, 0x80, 0x39, 0xC0, 0x30, 0xC0, 0x60, 0x60, 0x40, 0x20, 0x00, 0x00 },   // STAR
    { 0x00, 0x00, 0x60, 0x60, 0xF0, 0xF0, 0xFF, 0xF0, 0xFF, 0xF0, 0x7F, 0xE0, 0x3F, 0xC0, 0x1F, 0x80, 0x0F, 0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00 },   // HEART
    { 0x00, 0x80, 0x00, 0x80, 0x00, 0x80, 0x3F, 0x80, 0x21, 0x80, 0x2D, 0x80, 0x2D, 0x80, 0x21, 0x80, 0x29, 0x80, 0x21, 0x80, 0x3F, 0x80, 0x00, 0x00 },   // RADIO
    { 0x00, 0x00, 0x00, 0x00, 0x1F, 0x00, 0x31, 0x80, 0x60, 0xC0, 0xFF, 0xF0, 0xFF, 0xF0, 0xFF, 0xF0, 0x60, 0xC0, 0x7B, 0xC0, 0x31, 0x80, 0x00, 0x00 },   // CAR
    { 0x00, 0x00, 0x06, 0x00, 0x06, 0x00, 0x06, 0x00, 0xFF, 0xF0, 0xFF, 0xF0, 0x07, 0x00, 0x06, 0x00, 0x0F, 0x00, 0x1F, 0x80, 0x00, 0x00, 0x00, 0x00 },   // PLANE
    { 0x00, 0x00, 0x1F, 0x80, 0x29, 0x40, 0x49, 0x20, 0xFF, 0xF0, 0x90, 0x90, 0x90, 0x90, 0xFF, 0xF0, 0x49, 0x20, 0x29, 0x40, 0x1F, 0x80, 0x00, 0x00 },   // GLOBE
    { 0x30, 0xC0, 0x79, 0xE0, 0x79, 0xE0, 0x30, 0xC0, 0x00, 0x00, 0x1F, 0x80, 0x3F, 0xC0, 0x7F, 0xE0, 0x7F, 0xE0, 0x3F, 0xC0, 0x1F, 0x80, 0x00, 0x00 },   // PAW
    { 0x00, 0x00, 0x1F, 0x80, 0x60, 0x60, 0x80, 0x10, 0x99, 0x90, 0x99, 0x90, 0x80, 0x10, 0xA0, 0x50, 0x9F, 0x90, 0x60, 0x60, 0x1F, 0x80, 0x00, 0x00 },   // FACE
    { 0x00, 0x00, 0x00, 0x00, 0x00, 0x60, 0x00, 0xC0, 0x01, 0x80, 0x03, 0x00, 0x66, 0x00, 0x76, 0x00, 0x3C, 0x00, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00 },   // CHECK
    { 0x3C, 0x00, 0x66, 0x00, 0x42, 0x00, 0x66, 0x00, 0x3C, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 },   // DEG
    { 0x60, 0x00, 0x7F, 0x80, 0x61, 0xC0, 0x60, 0xC0, 0x7F, 0x80, 0x60, 0x00, 0x60, 0x00, 0x60, 0x00, 0x60, 0x00, 0x60, 0x00, 0x60, 0x00, 0x00, 0x00 },   // FLAG
    { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x00, 0x0F, 0x00, 0x0F, 0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 },   // DOT
};

// Scaled 1-bit blit, so the same art serves a list row and a headline.
static void drawIcon(int x, int y, uint8_t id, uint16_t c, int px) {
  if (id == IC_NONE || id >= IC_COUNT) return;
  const uint8_t* bits = kIconBits[id - 1];
  for (int row = 0; row < 12; row++) {
    const int y0 = y + row * px / 12, y1 = y + (row + 1) * px / 12;
    int col = 0;
    while (col < 12) {
      if (!(bits[row * 2 + (col >> 3)] & (0x80 >> (col & 7)))) { col++; continue; }
      int run = col;                                   // one rectangle per run of pixels
      while (run < 12 && (bits[row * 2 + (run >> 3)] & (0x80 >> (run & 7)))) run++;
      const int x0 = x + col * px / 12, x1 = x + run * px / 12;
      gfx()->fillRect(x0, y0, x1 - x0 > 0 ? x1 - x0 : 1, y1 - y0 > 0 ? y1 - y0 : 1, c);
      col = run;
    }
  }
}

// The icon a symbol is drawn as. Related symbols share one, so a modest set of art covers
// the names people actually give their nodes.
static uint8_t iconForCodepoint(uint32_t cp) {
  switch (cp) {
    case 0x1F4E1: case 0x1F6F0: case 0x1F4F6: case 0x1F4FD: return IC_DISH;
    case 0x1F5FC: case 0x1F3D7: case 0x1F3ED: case 0x26F0: return IC_TOWER;
    case 0x2600: case 0x1F31E: case 0x2601: case 0x1F324: case 0x1F326:
    case 0x1F506: return IC_SUN;
    case 0x26A1: case 0x1F50B: case 0x1F50C: case 0x1F525: return IC_BOLT;
    case 0x1F3E0: case 0x1F3E1: case 0x1F3E2: case 0x1F3DB: case 0x26FA: return IC_HOUSE;
    case 0x1F4CD: case 0x1F4CC: case 0x1F3F4: case 0x1F6A9: return IC_PIN;
    case 0x2B50: case 0x1F31F: case 0x2728: case 0x1F3C6: case 0x2605:
    case 0x2606: return IC_STAR;
    case 0x2764: case 0x1F49A: case 0x1F499: case 0x1F49C: case 0x1F9E1:
    case 0x1F496: case 0x1F49B: return IC_HEART;
    case 0x1F4FB: case 0x1F4F1: case 0x1F4DE: case 0x260E: case 0x1F50A:
    case 0x1F3A7: case 0x1F4BB: return IC_RADIO;
    case 0x1F697: case 0x1F699: case 0x1F690: case 0x1F69B: case 0x1F3CD:
    case 0x1F6B2: case 0x1F69C: case 0x1F6FB: return IC_CAR;
    case 0x2708: case 0x1F6E9: case 0x1F681: case 0x1F680: case 0x1F388:
    case 0x26F5: case 0x1F6A2: case 0x26F4: return IC_PLANE;
    case 0x1F30D: case 0x1F30E: case 0x1F30F: case 0x1F310: case 0x1F5FA: return IC_GLOBE;
    case 0x2705: case 0x2714: case 0x2713: case 0x1F44D: case 0x1F197: return IC_CHECK;
    case 0x00B0: case 0x2103: case 0x2109: return IC_DEG;
  }
  if (cp >= 0x1F400 && cp <= 0x1F43F) return IC_PAW;         // animals
  if (cp >= 0x1F980 && cp <= 0x1F9AE) return IC_PAW;         // and the newer animals
  if (cp >= 0x1F600 && cp <= 0x1F64F) return IC_FACE;        // faces
  if (cp >= 0x1F466 && cp <= 0x1F487) return IC_FACE;        // people
  if (cp >= 0x1F47A && cp <= 0x1F47F) return IC_FACE;        // ghosts, aliens and friends
  if (cp >= 0x1F910 && cp <= 0x1F9FF) return IC_FACE;        // the rest of that block
  if (cp >= 0x1F1E6 && cp <= 0x1F1FF) return IC_FLAG;        // the letters that make flags
  return IC_DOT;
}

// Accented letters and typographic punctuation fold onto what the font does have.
static const char* asciiForCodepoint(uint32_t cp) {
  if (cp >= 0x00C0 && cp <= 0x00FF) {
    static const char* const latin1[64] = {
      "A", "A", "A", "A", "A", "A", "AE", "C", "E", "E", "E", "E", "I", "I", "I", "I",
      "D", "N", "O", "O", "O", "O", "O", "x", "O", "U", "U", "U", "U", "Y", "T", "ss",
      "a", "a", "a", "a", "a", "a", "ae", "c", "e", "e", "e", "e", "i", "i", "i", "i",
      "d", "n", "o", "o", "o", "o", "o", "/", "o", "u", "u", "u", "u", "y", "t", "y"};
    return latin1[cp - 0x00C0];
  }
  switch (cp) {
    case 0x2018: case 0x2019: case 0x02BC: return "'";
    case 0x201C: case 0x201D: case 0x00AB: case 0x00BB: return "\"";
    case 0x2013: case 0x2014: case 0x2212: return "-";
    case 0x2026: return "...";
    case 0x00A0: case 0x2007: case 0x202F: return " ";
    case 0x00B5: return "u";
    case 0x00D7: return "x";
    case 0x0100: case 0x0102: case 0x0104: return "A";
    case 0x0101: case 0x0103: case 0x0105: return "a";
    case 0x0106: case 0x0108: case 0x010C: return "C";
    case 0x0107: case 0x0109: case 0x010D: return "c";
    case 0x0112: case 0x0116: case 0x0118: return "E";
    case 0x0113: case 0x0117: case 0x0119: return "e";
    case 0x0141: return "L";
    case 0x0142: return "l";
    case 0x0143: case 0x0147: return "N";
    case 0x0144: case 0x0148: return "n";
    case 0x015A: case 0x015E: case 0x0160: return "S";
    case 0x015B: case 0x015F: case 0x0161: return "s";
    case 0x0179: case 0x017B: case 0x017D: return "Z";
    case 0x017A: case 0x017C: case 0x017E: return "z";
    case 0x014C: case 0x0150: return "O";
    case 0x014D: case 0x0151: return "o";
    case 0x016A: case 0x016E: case 0x0170: return "U";
    case 0x016B: case 0x016F: case 0x0171: return "u";
  }
  return NULL;
}

// Rewrites a UTF-8 string so the drawing code only ever sees ASCII plus icon markers
// (bytes 1..31, which are the icon ids).
static void foldUtf8(const char* s, char* out, size_t out_n) {
  size_t o = 0;
  uint32_t prev = 0;
  const uint8_t* p = (const uint8_t*)s;
  while (*p != 0 && o + 4 < out_n) {
    uint32_t cp = *p;
    int len = 1;
    if (cp >= 0xF0) { cp &= 0x07; len = 4; }
    else if (cp >= 0xE0) { cp &= 0x0F; len = 3; }
    else if (cp >= 0xC0) { cp &= 0x1F; len = 2; }
    else if (cp >= 0x80) { cp = 0xFFFD; }               // a stray continuation byte
    for (int i = 1; i < len; i++) {
      if ((p[i] & 0xC0) != 0x80) { len = i; cp = 0xFFFD; break; }
      cp = (cp << 6) | (p[i] & 0x3F);
    }
    p += len;

    if (cp < 0x80) {
      out[o++] = (cp >= 0x20 && cp < 0x7F) ? (char)cp : ' ';
    } else if (cp == 0xFE0F || cp == 0xFE0E || cp == 0x200D || cp == 0x20E3 ||
               (cp >= 0x1F3FB && cp <= 0x1F3FF) || (cp >= 0x0300 && cp <= 0x036F)) {
      // emoji presentation selector, joiner, skin tone, combining accent: nothing to draw
    } else if (cp >= 0x1F1E6 && cp <= 0x1F1FF) {
      if (!(prev >= 0x1F1E6 && prev <= 0x1F1FF)) out[o++] = (char)IC_FLAG;   // one per pair
    } else {
      const char* a = asciiForCodepoint(cp);
      if (a != NULL) {
        while (*a != 0 && o + 2 < out_n) out[o++] = *a++;
      } else {
        out[o++] = (char)iconForCodepoint(cp);
      }
    }
    prev = cp;
  }
  out[o] = 0;
}

// How far the pen moves for one character of a shaped font.
static int charAdvance(const GFXfont* f, uint8_t ch) {
  if (ch < f->first || ch > f->last) return f->yAdvance / 2;
  return f->glyph[ch - f->first].xAdvance;
}

// The cap height, so every row sits on the same baseline whatever it says - measuring each
// string on its own makes lines jump about depending on their letters.
static int fontAscent(const GFXfont* f) {
  if ('H' < f->first || 'H' > f->last) return f->yAdvance * 3 / 4;
  return -(int)f->glyph['H' - f->first].yOffset;
}

// Draws (or just measures) folded text, icons included, stopping at max_w. x, y is the
// top-left corner; the return is the width used.
static int richDraw(int x, int y, const char* s, uint16_t c, const GFXfont* font, int max_w, bool draw) {
  if (s == NULL || s[0] == 0) return 0;
  char buf[160];
  foldUtf8(s, buf, sizeof(buf));
  const int asc = fontAscent(font);
  const int ih = asc >= 28 ? 26 : asc >= 15 ? 16 : 12;     // icons match the letter height
  const int base = y + asc;
  const int limit = x + max_w;
  int pen = x;
  if (draw) {
    gfx()->setFont(font);
    gfx()->setTextSize(1);
    gfx()->setTextColor(c);
    gfx()->setTextWrap(false);
  }
  for (int i = 0; buf[i] != 0; i++) {
    const uint8_t ch = (uint8_t)buf[i];
    const bool is_icon = ch < 0x20;
    const int adv = is_icon ? ih + 2 : charAdvance(font, ch);
    if (pen + adv > limit) {                               // out of room: show it was cut
      const int tw = charAdvance(font, '~');
      if (draw) {
        gfx()->setCursor(pen + tw > limit ? limit - tw : pen, base);
        gfx()->write('~');
      }
      pen += tw;
      break;
    }
    if (draw) {
      if (is_icon) {
        drawIcon(pen + 1, base - asc + (asc - ih) / 2, ch, c, ih);
      } else {
        gfx()->setCursor(pen, base);
        gfx()->write(ch);
      }
    }
    pen += adv;
  }
  if (draw) gfx()->setFont(NULL);
  return pen - x;
}

static void textF(int x, int y, const char* s, uint16_t c, const GFXfont* font) {
  richDraw(x, y, s, c, font, 4096, true);
}

static int textFWidth(const char* s, const GFXfont* font) { return richDraw(0, 0, s, 0, font, 4096, false); }

static void textFClip(int x, int y, int max_w, const char* s, uint16_t c, const GFXfont* font) {
  richDraw(x, y, s, c, font, max_w, true);
}

static void text(int x, int y, const char* s, uint16_t c, int size = 1) {
  richDraw(x, y, s, c, fontFor(size), 4096, true);
}

// Prints at most max_w pixels, marking the cut with "~".
static void textClip(int x, int y, int max_w, const char* s, uint16_t c, int size = 1) {
  richDraw(x, y, s, c, fontFor(size), max_w, true);
}

// The width a string will actually occupy, for centring and column widths.
static int textWidth(const char* s, int size = 1) { return richDraw(0, 0, s, 0, fontFor(size), 4096, false); }

static void button(int x, int y, int w, int h, const char* label, bool on = false) {
  fill(x, y, w, h, on ? C_ACC : C_CARD);
  gfx()->drawRect(x, y, w, h, C_LINE);
  const int tw = textWidth(label);
  text(x + (w - tw) / 2, y + (h - 12) / 2, label, on ? 0xFFFF : C_TXT);
}

// The contact store keeps a few reserved slots at the front for anonymous requests, and
// getNumContacts() doesn't count them - so the screen must skip them too, or every list
// starts with blank entries.
static bool contactAt(int want, ContactInfo& dest) {
  if (want < 0) return false;
  int seen = 0;
  const int slots = the_mesh.getTotalContactSlots();
  for (int i = 0; i < slots; i++) {
    ContactInfo c;
    if (!the_mesh.getContactByIdx((uint32_t)i, c)) break;
    if (c.type == ADV_TYPE_NONE || c.name[0] == 0) continue;   // a reserved slot, not a contact
    if (seen++ == want) {
      dest = c;
      return true;
    }
  }
  return false;
}

// How many real contacts there are, counted the same way the list shows them.
static int contactCount() {
  int n = 0;
  ContactInfo c;
  const int slots = the_mesh.getTotalContactSlots();
  for (int i = 0; i < slots; i++) {
    if (!the_mesh.getContactByIdx((uint32_t)i, c)) break;
    if (c.type != ADV_TYPE_NONE && c.name[0] != 0) n++;
  }
  return n;
}

static bool hit(const TouchEvent& ev, int x, int y, int w, int h) {
  return ev.released && ev.x >= x && ev.x < x + w && ev.y >= y && ev.y < y + h &&
         abs(ev.x - ev.start_x) < 20 && abs(ev.y - ev.start_y) < 20;
}

static const char* shortAge(uint32_t secs, char* buf, size_t n) {
  if (secs < 90) snprintf(buf, n, "%lus", (unsigned long)secs);
  else if (secs < 5400) snprintf(buf, n, "%lum", (unsigned long)(secs / 60));
  else if (secs < 172800) snprintf(buf, n, "%luh", (unsigned long)(secs / 3600));
  else snprintf(buf, n, "%lud", (unsigned long)(secs / 86400));
  return buf;
}


// ---- helpers for the Home and Radio tabs ----

static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Horizontal meter: frac 0..1 filled with colour c.
static void meter(int x, int y, int w, int h, float frac, uint16_t c) {
  if (frac < 0) frac = 0;
  if (frac > 1) frac = 1;
  fill(x, y, w, h, C_CARD);
  fill(x, y, (int)(w * frac), h, c);
  gfx()->drawRect(x, y, w, h, C_LINE);
}

// 0 = Sunday
static int weekdayOf(int y, int m, int d) {
  static const int t[] = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};
  if (m < 3) y -= 1;
  return (y + y / 4 - y / 100 + y / 400 + t[m - 1] + d) % 7;
}

static int dayOfYear(int y, int m, int d) {
  static const int cum[] = {0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334};
  int n = cum[m - 1] + d;
  if (m > 2 && ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0)) n++;
  return n;
}

// NOAA solar-position approximation. Returns false when the sun does not rise or set that day.
// rise/set are minutes after local midnight (tz_min = local offset from UTC in minutes).
static bool sunTimes(double lat, double lon, int y, int m, int d, int tz_min, int& rise, int& set) {
  const double rad = M_PI / 180.0;
  const double g = 2.0 * M_PI / 365.0 * (dayOfYear(y, m, d) - 1);
  const double eqtime = 229.18 * (0.000075 + 0.001868 * cos(g) - 0.032077 * sin(g) - 0.014615 * cos(2 * g) -
                                  0.040849 * sin(2 * g));
  const double decl = 0.006918 - 0.399912 * cos(g) + 0.070257 * sin(g) - 0.006758 * cos(2 * g) +
                      0.000907 * sin(2 * g) - 0.002697 * cos(3 * g) + 0.00148 * sin(3 * g);
  const double c = cos(90.833 * rad) / (cos(lat * rad) * cos(decl)) - tan(lat * rad) * tan(decl);
  if (c < -1.0 || c > 1.0) return false;
  const double ha = acos(c) / rad;
  int r = (int)lround(720.0 - 4.0 * (lon + ha) - eqtime) + tz_min;
  int s2 = (int)lround(720.0 - 4.0 * (lon - ha) - eqtime) + tz_min;
  rise = ((r % 1440) + 1440) % 1440;
  set = ((s2 % 1440) + 1440) % 1440;
  return true;
}

// Home dashboard card slots: 3 columns x 2 rows under the clock.
static void homeCard(int i, int& x, int& y, int& w, int& h) {
  w = 101;
  h = 46;
  x = 4 + (i % 3) * (w + 3);
  y = BODY_Y + 90 + (i / 3) * (h + 3);
}

// The web server reaches the card through these: it has no business knowing about the
// screen, and the tile store belongs to the UI.
static UmcTiles* s_tiles = nullptr;
static TaskHandle_t s_ui_task = nullptr;

static bool umcTileSinkThunk(int z, int x, int y, const uint8_t* data, size_t len) {
  if (s_tiles == nullptr) return false;
  // Called from the UI task itself (the console's self-test): write straight away, since
  // handing it to the queue would wait for a task that is already here.
  if (xTaskGetCurrentTaskHandle() == s_ui_task) return s_tiles->writeTileNow(z, x, y, data, len);
  return s_tiles->queueTile(z, x, y, data, len);
}

// Clears up after the self-test, again only from the UI task.
static bool umcTileRemoveThunk(int z, int x, int y) {
  return s_tiles != nullptr && s_tiles->removeTile(z, x, y);
}

static const char* umcTileStatusThunk() { return s_tiles != nullptr ? s_tiles->status() : "no display task"; }

void UITask::begin(DisplayDriver* disp, SensorManager* sensors, NodePrefs* node_prefs) {
  _display = disp;
  _sensors = sensors;
  _prefs = node_prefs;
  if (_display) _display->turnOn();
  // start screen: full-screen artwork, with the MeshCore version over it
  gfx()->drawRGBBitmap(0, 0, const_cast<uint16_t*>(UMC_SPLASH), UMC_SPLASH_W, UMC_SPLASH_H);
  text(8, 224, "MeshCore " FIRMWARE_VERSION, C_DIM);
  delay(2500);
  _input.begin(SCR_W, SCR_H, the_mesh.getUmc().prefs().touch_map);
  _tiles.begin();
  // let the web server upload map tiles to the card
  s_tiles = &_tiles;
  s_ui_task = xTaskGetCurrentTaskHandle();
  umcSetMapTileSink(umcTileSinkThunk);
  umcSetMapStatusFn(umcTileStatusThunk);
  umcSetMapRemoveFn(umcTileRemoveThunk);
#ifdef PIN_TFT_LEDA_CTL
  pinMode(PIN_TFT_LEDA_CTL, OUTPUT);
  digitalWrite(PIN_TFT_LEDA_CTL, HIGH);
#endif
  ChannelDetails ch;
  if (the_mesh.getChannel(0, ch) && ch.name[0]) {
    StrHelper::strncpy(_to_name, ch.name, sizeof(_to_name));
  }
  applyTheme();
  _dirty = true;
}

void UITask::setBrightness(uint8_t pct) {
  _brightness = pct > 100 ? 100 : pct;
#ifdef PIN_TFT_LEDA_CTL
  // simple on/off fallback: full backlight unless turned right down
  digitalWrite(PIN_TFT_LEDA_CTL, _brightness > 5 ? HIGH : LOW);
#endif
}

void UITask::showAlert(const char* t, int duration_millis) {
  size_t n = 0;
  int readable = 0;
  for (; t != NULL && t[n] != 0 && n < sizeof(_alert) - 1; n++) {
    const char c = t[n];
    _alert[n] = (c >= 32 && c < 127) ? c : ' ';   // anything else would draw as nonsense
    if (isalnum((unsigned char)_alert[n])) readable++;
  }
  _alert[n] = 0;
  // Nothing worth reading (empty, or only punctuation left after cleaning): say nothing
  // rather than leave an empty box on the screen.
  if (readable < 2) { _alert_expiry = 0; return; }
  if (duration_millis < 300) duration_millis = 300;
  if (duration_millis > 5000) duration_millis = 5000;
  _alert_expiry = millis() + duration_millis;
  _dirty = true;
}

void UITask::msgRead(int) { _dirty = true; }

void UITask::newMsg(uint8_t, const char*, const char*, int) {
  // the message itself is already in umc_chatlog; just wake the screen
  if (_tab == TAB_MSGS) _msg_scroll = 0;
  _dirty = true;
}

void UITask::notify(UIEventType) { _dirty = true; }

bool UITask::selfLocation(double& lat, double& lon) const {
  lat = sensors.node_lat;
  lon = sensors.node_lon;
  return !(lat == 0 && lon == 0);
}

void UITask::centreOnSelf() {
  double lat, lon;
  if (selfLocation(lat, lon)) {
    _centre_lat = lat;
    _centre_lon = lon;
    _follow_self = true;
  } else {
    showAlert("No location yet", 1500);
  }
}

// ---------------------------------------------------------------- main loop

void UITask::loop() {
  if (_display == NULL) return;

  _tiles.servicePending();   // a tile uploaded over WiFi, written here where the bus is ours

  char key = _input.readKey();
  if (key) handleKey(key);

  char tb = _input.readTrackball();
  if (tb) {
    // left/right change tab everywhere; up/down scroll or move the selection on the tab
    // you are on, and move the map.
    if (_tab == TAB_SETUP && _editing) {
      // typing: the ball does nothing
    } else if (tb == 'L' && _tab == TAB_SETUP && _setup_page != SP_ROOT) {
      setupOpen(SP_ROOT);
    } else if (tb == 'L') _tab = (Tab)((_tab + TAB_COUNT - 1) % TAB_COUNT);
    else if (tb == 'R') _tab = (Tab)((_tab + 1) % TAB_COUNT);
    else if (_tab == TAB_MSGS) {
      _msg_scroll = tb == 'U' ? _msg_scroll + 1 : max(0, _msg_scroll - 1);
    } else if (_tab == TAB_CONTACTS) {
      const int total = contactCount();
      if (total > 0) {
        if (_contact_sel < 0) _contact_sel = 0;
        else _contact_sel = constrain(_contact_sel + (tb == 'U' ? -1 : 1), 0, total - 1);
        if (_contact_sel < _contact_scroll) _contact_scroll = _contact_sel;
        if (_contact_sel > _contact_scroll + 6) _contact_scroll = _contact_sel - 6;
      }
    } else if (_tab == TAB_MAP) {
      const double step = 40.0;   // pixels
      const double scale = UMC_TILE_PX * (1 << _zoom);
      const double cy = UmcTiles::latToWorldY(_centre_lat, _zoom) + (tb == 'U' ? -step : step);
      _centre_lat = UmcTiles::worldYToLat(cy, _zoom);
      _follow_self = false;
      (void)scale;
    } else if (_tab == TAB_SETUP && !_editing) {
      _setup_sel = constrain(_setup_sel + (tb == 'U' ? -1 : 1), 0, setupRowCount() - 1);
      _setup_confirm = -1;
    } else if (_tab == TAB_HOME || _tab == TAB_INFO || _tab == TAB_RADIO) {
      _tab = tb == 'U' ? TAB_HOME : TAB_INFO;   // quick jump between the summary screens
    }
    _dirty = true;
  }

  TouchEvent ev = _input.poll();
  if (ev.pressed || ev.released || (ev.down && (ev.dx || ev.dy))) handleTouch(ev);

  if (millis() >= _next_rssi) {
    _next_rssi = millis() + 1000;
    sampleRadio();
  }
  if (_tab == TAB_RADIO && millis() >= _next_fast) {
    _next_fast = millis() + 2000;
    _dirty = true;
  }

  if (umc_chatlog.revision() != _log_rev) {
    _log_rev = umc_chatlog.revision();
    if (_tab == TAB_MSGS) umc_chatlog.markRead();
    _dirty = true;
  }
  if (_alert_expiry && millis() > _alert_expiry) {
    _alert_expiry = 0;
    _dirty = true;
  }
  if (millis() > _next_refresh) {   // clock, battery, GPS and stats tick over
    _next_refresh = millis() + 2000;
    if (_input.touchMap() != the_mesh.getUmc().prefs().touch_map) _input.setTouchMap(the_mesh.getUmc().prefs().touch_map);
    const uint32_t sig = screenSignature();
    if (sig != _last_sig) {   // nothing on screen has changed: leave it alone, redrawing flickers
      _last_sig = sig;
      _dirty = true;
    }
  }
  // A full redraw flickers, so never do more than a few a second however often something
  // asks for one.
  if (_dirty && millis() - _last_draw >= kMinRedrawMs) {
    _dirty = false;
    _last_draw = millis();
    draw();
  }
}

// What the current tab is showing, as one number: while this doesn't change there is
// nothing to redraw, and a full redraw flickers.
uint32_t UITask::screenSignature() {
  uint32_t h = (uint32_t)_tab * 2654435761u;
  if (_tab == TAB_GPS) {     // satellites come and go
    return h ^ (uint32_t)(umc_gps_sky.count() * 131 + umc_gps_sky.tracked() * 7919 +
                          (uint32_t)sensors.getLocationProvider()->satellitesCount() * 31 + (millis() / 5000) * 3);
  }
  if (_tab == TAB_SETUP) {   // values here change as you set them
    return h ^ (uint32_t)(_setup_page * 65537 + _setup_sel * 131 + _setup_scroll * 17 +
                          (_editing ? 7919 : 0) + _edit_len * 31 + (_setup_confirm + 2) * 13 +
                          _wifi_scan_state * 101 + _wifi_found * 7 + (uint32_t)strlen(_setup_status) +
                          (uint32_t)strlen(_console_out) * 3);
  }
  const uint32_t clock_now = rtc_clock.getCurrentTime();
  h ^= clock_now / 60 * 2246822519u;                       // the clock shows minutes
  h ^= (uint32_t)(_board->getBattMilliVolts() / 100) * 3266489917u;   // coarse: it wanders
  h ^= (uint32_t)contactCount() * 668265263u;
  h ^= (uint32_t)umc_chatlog.count() * 374761393u + (uint32_t)umc_chatlog.unread() * 31u;
  h ^= (uint32_t)(the_mesh.getNetwork().isWifiConnected() ? 1 : 0) + (the_mesh.getNetwork().isApActive() ? 2 : 0) +
       (isBluetoothEnabled() ? 4 : 0) + (hasConnection() ? 8 : 0);
  h ^= (uint32_t)(_alert_expiry ? 1 : 0) * 2166136261u;
  if (_tab == TAB_HOME || _tab == TAB_RADIO) {
    // Only things that really change: the noise floor and RSSI wander by a dB constantly,
    // and redrawing for that flickers the screen about once a second.
    h ^= (uint32_t)(_busy_pct / 5 + 1) * 16777619u;
    h ^= (uint32_t)umc_traffic.rxTotal() * 2654435761u;
    h ^= (uint32_t)umc_traffic.txTotal() * 40503u;
  }
  if (_tab == TAB_INFO) {
    h ^= (uint32_t)(millis() / 60000) * 40503u;             // uptime, to the minute
    h ^= (uint32_t)(ESP.getFreeHeap() / 4096) * 12289u;
  }
  double lat, lon;
  h ^= selfLocation(lat, lon) ? (uint32_t)(lat * 1000) ^ (uint32_t)(lon * 1000) : 0u;
  return h;
}

// ---------------------------------------------------------------- drawing

void UITask::draw() {
  drawHeader();
  fill(0, BODY_Y, SCR_W, BODY_H, C_BG);
  switch (_tab) {
    case TAB_HOME: drawHome(); break;
    case TAB_MSGS: drawMessages(); break;
    case TAB_CONTACTS: drawContacts(); break;
    case TAB_MAP: drawMap(); break;
    case TAB_GPS: drawGps(); break;
    case TAB_RADIO: drawRadio(); break;
    case TAB_SETUP: drawSetup(); break;
    default: drawInfo(); break;
  }
  drawTabs();
  drawAlert();
}

void UITask::drawHeader() {
  fill(0, 0, SCR_W, HDR_H, C_CARD);
  textClip(4, 3, 142, the_mesh.getNodeName(), C_TXT);

  char buf[40];
  uint32_t now = rtc_clock.getCurrentTime();
  DateTime dt(now);
  snprintf(buf, sizeof(buf), "%02d:%02d", dt.hour(), dt.minute());
  text(SCR_W - 40, 3, buf, C_TXT);

  int x = SCR_W - 52;
  const uint16_t batt = _board->getBattMilliVolts();
  snprintf(buf, sizeof(buf), "%d.%02dV", batt / 1000, (batt % 1000) / 10);
  text(x - 46, 3, buf, batt && batt < 3500 ? C_BAD : C_DIM);

  // link indicators
  text(150, 3, the_mesh.getNetwork().isWifiConnected() ? "wifi" : (the_mesh.getNetwork().isApActive() ? "AP" : "----"),
       the_mesh.getNetwork().isWifiConnected() ? C_OK : C_DIM);
  text(188, 3, isBluetoothEnabled() ? (hasConnection() ? "BT+" : "BT") : "--", hasConnection() ? C_OK : C_DIM);
}

void UITask::drawTabs() {
  static const char* names[TAB_COUNT] = {"Home", "Msgs", "Who", "Map", "GPS", "Radio", "Set", "Info"};
  const int w = SCR_W / TAB_COUNT;
  for (int i = 0; i < TAB_COUNT; i++) {
    const bool on = (int)_tab == i;
    fill(i * w, SCR_H - TAB_H, w, TAB_H, on ? C_ACC : C_CARD);
    gfx()->drawFastVLine(i * w, SCR_H - TAB_H, TAB_H, C_LINE);
    const char* label = names[i];
    const int tw = textWidth(label);
    const int lx = tw < w - 2 ? i * w + (w - tw) / 2 : i * w + 1;
    textClip(lx, SCR_H - TAB_H + 9, w - 2, label, on ? 0xFFFF : C_TXT);
    // the unread count rides in the corner, so the label keeps its room
    if (i == TAB_MSGS && umc_chatlog.unread() > 0) {
      gfx()->fillCircle(i * w + w - 8, SCR_H - TAB_H + 8, 6, C_WARN);
      char n[4];
      snprintf(n, sizeof(n), "%d", umc_chatlog.unread() > 9 ? 9 : umc_chatlog.unread());
      gfx()->setFont(NULL);
      gfx()->setTextSize(1);
      gfx()->setTextColor(0);
      gfx()->setCursor(i * w + w - 10, SCR_H - TAB_H + 5);
      gfx()->print(n);           // the one place the tiny built-in font still earns its keep
    }
  }
}

void UITask::drawAlert() {
  if (!_alert_expiry) return;
  const int w = 260, h = 34, x = (SCR_W - w) / 2, y = 90;
  fill(x, y, w, h, C_ACC);
  gfx()->drawRect(x, y, w, h, 0xFFFF);
  textClip(x + 8, y + 10, w - 16, _alert, 0xFFFF);
}

void UITask::applyTheme() {
  const int want = the_mesh.getUmc().prefs().theme;
  g_theme = want >= 0 && want < kThemeCount ? want : 0;
}

// One message bubble, drawn upwards from y_bottom. Returns the new bottom for the next one.
int UITask::drawBubble(int y_bottom, const char* who, const char* body, bool mine, bool selected, uint32_t when) {
  const int max_w = SCR_W - 70;
  const int pad = 5;
  const int line_h = 15;
  const int inner = max_w - pad * 2;

  // wrap on spaces
  char lines[5][48];
  int line_count = 0;
  const char* p = body;
  while (*p && line_count < 5) {
    int take = strlen(p);
    if (take > (int)sizeof(lines[0]) - 1) take = sizeof(lines[0]) - 1;
    char probe[sizeof(lines[0])];
    memcpy(probe, p, take);
    probe[take] = 0;
    while (take > 1 && textWidth(probe) > inner) probe[--take] = 0;    // trim to the width
    if (p[take] != 0) {
      int brk = take;
      while (brk > 6 && p[brk] != ' ') brk--;                          // back to a space
      if (brk > 6) take = brk;
    }
    memcpy(lines[line_count], p, take);
    lines[line_count][take] = 0;
    line_count++;
    p += take;
    while (*p == ' ') p++;
  }
  if (line_count == 0) return y_bottom;

  int widest = 0;
  for (int i = 0; i < line_count; i++) {
    const int w = textWidth(lines[i]);
    if (w > widest) widest = w;
  }
  char foot_pre[40];
  if (when) {
    DateTime dt0(when);
    snprintf(foot_pre, sizeof(foot_pre), "%s %02d:%02d", mine ? "" : who, dt0.hour(), dt0.minute());
  } else {
    snprintf(foot_pre, sizeof(foot_pre), "%s", mine ? "" : who);
  }
  const int fw = textWidth(foot_pre);          // the name and time can be wider than the body
  if (fw > widest) widest = fw > inner ? inner : fw;
  const int bw = widest + pad * 2;
  const int bh = line_count * line_h + pad * 2 + 15;      // room for the name/time line
  const int bx = mine ? SCR_W - bw - 6 : 6;
  const int by = y_bottom - bh;

  gfx()->fillRoundRect(bx, by, bw, bh, 7, mine ? TH.mine : TH.theirs);
  if (selected) gfx()->drawRoundRect(bx - 1, by - 1, bw + 2, bh + 2, 8, TH.accent == TH.mine ? 0xFFFF : TH.accent);

  const uint16_t tc = mine ? TH.mine_text : TH.theirs_text;
  for (int i = 0; i < line_count; i++) text(bx + pad, by + pad + i * line_h, lines[i], tc);

  char foot[40];
  if (when) {
    DateTime dt(when);
    snprintf(foot, sizeof(foot), "%s %02d:%02d", mine ? "" : who, dt.hour(), dt.minute());
  } else {
    snprintf(foot, sizeof(foot), "%s", mine ? "" : who);
  }
  textClip(bx + pad, by + bh - 17, bw - pad * 2, foot, mine ? tc : TH.dim);
  return by - 4;
}

void UITask::drawMessages() {
  applyTheme();
  const int top = BODY_Y + 2;
  const int list_h = BODY_H - COMPOSE_H - 4;

  // who we are writing to
  fill(0, top, SCR_W, 16, TH.card);
  char hdr[48];
  snprintf(hdr, sizeof(hdr), "To: %s%s", _to_channel ? "#" : "", _to_name);
  textClip(4, top + 2, SCR_W - 60, hdr, TH.text);
  button(SCR_W - 52, top, 50, 16, "change");

  fill(0, top + 17, SCR_W, list_h, TH.bg);

  // newest at the bottom, working upwards
  int y = top + 17 + list_h;
  const int first = umc_chatlog.count() - 1 - _msg_scroll;
  _msg_rows = 0;
  for (int i = first; i >= 0 && y > top + 28; i--) {
    const UmcChatLog::Entry* e = umc_chatlog.get(i);
    if (e == nullptr) continue;
    char who[40];
    if (e->from[0]) snprintf(who, sizeof(who), "%s", e->from);
    else snprintf(who, sizeof(who), "%02x%02x%02x", e->key[0], e->key[1], e->key[2]);
    const int bottom_before = y;
    y = drawBubble(y, who, e->text, e->outgoing, _msg_sel == i, e->epoch);
    if (_msg_rows < (int)(sizeof(_msg_row_y) / sizeof(_msg_row_y[0]))) {
      _msg_row_y[_msg_rows] = y;            // top of this bubble
      _msg_row_bottom[_msg_rows] = bottom_before;
      _msg_row_idx[_msg_rows] = i;
      _msg_rows++;
    }
  }
  if (umc_chatlog.count() == 0) {
    text(8, top + 40, "No messages yet.", TH.dim);
    text(8, top + 58, "Type below and press Enter to send.", TH.dim);
  } else if (_msg_sel < 0) {
    text(6, top + 17 + list_h - 15, "Tap a message to reply to it", TH.dim);
  }
  drawCompose();
}

void UITask::drawCompose() {
  if (_reply_to[0]) {
    const int ry = SCR_H - TAB_H - COMPOSE_H - 12;
    fill(0, ry, SCR_W, 12, TH.card);
    char line[52];
    snprintf(line, sizeof(line), "Reply to: %s", _reply_to);
    textClip(4, ry - 1, SCR_W - 40, line, TH.accent);
    button(SCR_W - 34, ry, 32, 12, "x");
  }
  const int y = SCR_H - TAB_H - COMPOSE_H;
  fill(0, y, SCR_W, COMPOSE_H, C_CARD);
  gfx()->drawFastHLine(0, y, SCR_W, C_LINE);
  const int max_w = SCR_W - 68;
  const char* shown = _compose;
  while (shown[0] != 0 && textWidth(shown) > max_w) shown++;     // keep the end in view
  text(4, y + 6, shown[0] ? shown : "type a message...", shown[0] ? C_TXT : C_DIM);
  if (shown[0]) fill(5 + textWidth(shown), y + 5, 2, 15, C_ACC);
  button(SCR_W - 62, y + 3, 58, 20, "Send", _compose_len > 0);
}

void UITask::drawContacts() {
  const int top = BODY_Y + 2;
  const int row_h = 22;
  const int rows = (BODY_H - 46) / row_h;
  const int total = contactCount();
  if (_contact_scroll > max(0, total - rows)) _contact_scroll = max(0, total - rows);

  char buf[48];
  snprintf(buf, sizeof(buf), "Contacts %d", total);
  text(4, top, buf, C_DIM);

  const uint32_t now = rtc_clock.getCurrentTime();
  int y = top + 17;
  for (int i = 0; i < rows; i++) {
    const int idx = _contact_scroll + i;
    if (idx >= total) break;
    ContactInfo c;
    if (!contactAt(idx, c)) continue;
    const bool sel = idx == _contact_sel;
    fill(0, y, SCR_W, row_h - 2, sel ? C_ACC : C_CARD);
    const uint8_t kind_icon = c.type == ADV_TYPE_REPEATER ? IC_TOWER : c.type == ADV_TYPE_ROOM ? IC_HOUSE
                              : c.type == ADV_TYPE_SENSOR ? IC_DISH : IC_FACE;
    drawIcon(4, y + 4, kind_icon, sel ? 0xFFFF : C_ACC, 12);
    textClip(21, y + 3, 133, c.name[0] ? c.name : "(no name)", sel ? 0xFFFF : C_TXT);
    const char* kind = c.type == ADV_TYPE_REPEATER ? "repeater" : c.type == ADV_TYPE_ROOM ? "room" : c.type == ADV_TYPE_SENSOR ? "sensor" : "chat";
    text(158, y + 3, kind, C_DIM);
    if (c.out_path_len == 0xFF) text(224, y + 3, "flood", C_DIM);
    else {
      snprintf(buf, sizeof(buf), "%dhop", c.out_path_len & 63);
      text(224, y + 3, buf, C_DIM);
    }
    char age[12];
    if (c.last_advert_timestamp && now > c.last_advert_timestamp) text(276, y + 3, shortAge(now - c.last_advert_timestamp, age, sizeof(age)), C_DIM);
    y += row_h;
  }
  if (total == 0) text(8, top + 36, "Nothing heard yet. Send an advert from Info.", C_DIM);

  // actions for the selected contact
  const int by = SCR_H - TAB_H - 26;
  if (_contact_sel >= 0 && _contact_sel < total) {
    button(2, by, 74, 22, "Message");
    button(80, by, 74, 22, "Show map");
    button(158, by, 74, 22, "Share");
    button(236, by, 80, 22, "Reset path");
  } else {
    text(6, by + 5, "Tap a contact to select it", C_DIM);
  }
}

void UITask::drawMap() {
  const int top = BODY_Y;
  // A card put in after start-up (or one that wasn't ready then) is picked up here.
  if (!_tiles.available() && millis() - _tiles_retry > 10000) {
    _tiles_retry = millis();
    _tiles.begin();
  }
  double self_lat, self_lon;
  const bool have_self = selfLocation(self_lat, self_lon);
  if (_centre_lat == 0 && _centre_lon == 0) {
    if (have_self) { _centre_lat = self_lat; _centre_lon = self_lon; }
  }

  const double cx = UmcTiles::lonToWorldX(_centre_lon, _zoom);
  const double cy = UmcTiles::latToWorldY(_centre_lat, _zoom);
  const double left = cx - SCR_W / 2.0, topw = cy - BODY_H / 2.0;

  bool drew_tiles = false;
  if (_tiles.available() && _tiles.hasZoom(_zoom) && (_centre_lat != 0 || _centre_lon != 0)) {
    const int tx0 = (int)floor(left / UMC_TILE_PX), ty0 = (int)floor(topw / UMC_TILE_PX);
    const int tx1 = (int)floor((left + SCR_W) / UMC_TILE_PX), ty1 = (int)floor((topw + BODY_H) / UMC_TILE_PX);
    for (int ty = ty0; ty <= ty1; ty++) {
      for (int tx = tx0; tx <= tx1; tx++) {
        const uint16_t* px = _tiles.tile(_zoom, tx, ty);
        if (px == nullptr) continue;
        const int sx = (int)lround(tx * UMC_TILE_PX - left);
        const int sy = (int)lround(ty * UMC_TILE_PX - topw) + top;
        // clip to the body area
        const int x0 = max(0, -sx), y0 = max(0, top - sy);
        const int x1 = min(UMC_TILE_PX, SCR_W - sx), y1 = min(UMC_TILE_PX, top + BODY_H - sy);
        for (int row = y0; row < y1; row++) {
          gfx()->drawRGBBitmap(sx + x0, sy + row, const_cast<uint16_t*>(px + row * UMC_TILE_PX + x0), x1 - x0, 1);
        }
        drew_tiles = true;
      }
    }
  }

  if (!drew_tiles) {
    // No tiles: plot contacts around us by range and bearing, with distance rings.
    fill(0, top, SCR_W, BODY_H, C_BG);
    const int mx = SCR_W / 2, my = top + BODY_H / 2;
    for (int r = 1; r <= 3; r++) {
      gfx()->drawCircle(mx, my, r * 30, C_LINE);
    }
    text(4, top + 4, _tiles.available() ? "No tiles for this zoom" : _tiles.status(), C_DIM);
    if (!have_self) {
      text(60, my - 4, "Set this node's location first", C_DIM);
    }
  }

  // markers
  const int total = contactCount();
  double far_m = 1;
  for (int i = 0; i < total; i++) {
    ContactInfo c;
    if (!contactAt(i, c)) continue;
    if (c.gps_lat == 0 && c.gps_lon == 0) continue;
    const double lat = c.gps_lat / 1e6, lon = c.gps_lon / 1e6;
    int px, py;
    if (drew_tiles) {
      px = (int)lround(UmcTiles::lonToWorldX(lon, _zoom) - left);
      py = (int)lround(UmcTiles::latToWorldY(lat, _zoom) - topw) + top;
    } else {
      if (!have_self) continue;
      const double d = UmcTiles::distanceM(self_lat, self_lon, lat, lon);
      const double b = UmcTiles::bearingDeg(self_lat, self_lon, lat, lon) * M_PI / 180.0;
      if (d > far_m) far_m = d;
      const double scale = 90.0 / (far_m > 1000 ? far_m : 1000);
      px = SCR_W / 2 + (int)lround(sin(b) * d * scale);
      py = top + BODY_H / 2 - (int)lround(cos(b) * d * scale);
    }
    if (px < 0 || px >= SCR_W || py < top || py >= top + BODY_H) continue;
    const uint16_t col = c.type == ADV_TYPE_REPEATER ? C_WARN : c.type == ADV_TYPE_ROOM ? C_OK : C_ACC;
    gfx()->fillCircle(px, py, 4, col);
    gfx()->drawCircle(px, py, 4, 0xFFFF);
    textClip(px + 6, py - 3, 90, c.name, 0xFFFF);
  }
  if (have_self) {
    int px = SCR_W / 2, py = top + BODY_H / 2;
    if (drew_tiles) {
      px = (int)lround(UmcTiles::lonToWorldX(self_lon, _zoom) - left);
      py = (int)lround(UmcTiles::latToWorldY(self_lat, _zoom) - topw) + top;
    }
    if (px >= 0 && px < SCR_W && py >= top && py < top + BODY_H) {
      gfx()->fillCircle(px, py, 5, C_ME);
      gfx()->drawCircle(px, py, 7, 0xFFFF);
    }
  }

  // controls
  button(SCR_W - 30, top + 4, 26, 24, "+");
  button(SCR_W - 30, top + 32, 26, 24, "-");
  button(SCR_W - 62, top + BODY_H - 28, 58, 24, "me", _follow_self);
  char z[24];
  snprintf(z, sizeof(z), "z%d", _zoom);
  text(4, top + BODY_H - 16, z, C_DIM);
}

void UITask::drawInfo() {
  const int VX = 108;   // where the values start: the labels need the room
  const int top = BODY_Y + 4;
  char buf[80];
  int y = top;
  const int lh = 14;   // the shaped font is taller than the old blocky one

  textF(4, y, "Node", C_DIM, F_SMALL); textFClip(VX, y, SCR_W - VX - 6, the_mesh.getNodeName(), C_TXT, F_SMALL); y += lh;

  NetworkService& net = the_mesh.getNetwork();
  textF(4, y, "WiFi", C_DIM, F_SMALL);
  if (net.isWifiConnected()) {
    snprintf(buf, sizeof(buf), "%s  %s", net.getWifiSSID(), net.getStaIp().c_str());
  } else if (net.isApActive()) {
    snprintf(buf, sizeof(buf), "hotspot %s  192.168.4.1", net.getApSsid());
  } else {
    snprintf(buf, sizeof(buf), "not connected");
  }
  textFClip(VX, y, SCR_W - VX - 6, buf, net.isWifiConnected() || net.isApActive() ? C_TXT : C_DIM, F_SMALL); y += lh;

  textF(4, y, "Web", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%s.local", net.getHostname());
  textFClip(VX, y, SCR_W - VX - 6, buf, C_TXT, F_SMALL); y += lh;

  textF(4, y, "Bluetooth", C_DIM, F_SMALL);
  if (!isBluetoothEnabled()) snprintf(buf, sizeof(buf), "off");
  else if (hasConnection()) snprintf(buf, sizeof(buf), "app connected");
  else snprintf(buf, sizeof(buf), "pairing PIN %lu", (unsigned long)the_mesh.getBLEPin());
  textFClip(VX, y, SCR_W - VX - 6, buf, isBluetoothEnabled() ? C_TXT : C_DIM, F_SMALL); y += lh;

  textF(4, y, "Radio", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%.3f MHz  SF%d  BW%.1f  %ddBm", _prefs->freq, _prefs->sf, _prefs->bw, _prefs->tx_power_dbm);
  textFClip(VX, y, SCR_W - VX - 6, buf, C_TXT, F_SMALL); y += lh;

  textF(4, y, "GPS", C_DIM, F_SMALL);
  double lat, lon;
  char fixtxt[32];
  if (selfLocation(lat, lon)) snprintf(fixtxt, sizeof(fixtxt), "%.4f, %.4f", lat, lon);
  else snprintf(fixtxt, sizeof(fixtxt), "no fix / not set");
  const uint32_t gbaud = sensors.gpsBaudDetected();   // which receiver answered at start-up
  const char* grx = gbaud == 38400 ? "u-blox 38400" : gbaud == 9600 ? "L76K 9600"
                    : gbaud ? "found" : "none found";
  snprintf(buf, sizeof(buf), "%s  (%s)", fixtxt, grx);
  textFClip(VX, y, SCR_W - VX - 6, buf, C_TXT, F_SMALL); y += lh;

  textF(4, y, "Input", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%s  keyboard %s  touch %s", _input.busOk() ? "I2C ok" : "I2C BUS JAMMED",
           _input.hasKeyboard() ? "yes" : "no", _input.hasTouch() ? "yes" : "no");
  textFClip(VX, y, SCR_W - VX - 6, buf, _input.busOk() && _input.hasKeyboard() && _input.hasTouch() ? C_TXT : C_WARN, F_SMALL); y += lh;

  textF(4, y, "Maps", C_DIM, F_SMALL); textFClip(VX, y, SCR_W - VX - 6, _tiles.status(), _tiles.available() ? C_TXT : C_DIM, F_SMALL); y += lh;

  textF(4, y, "Contacts", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%d contacts, %d messages kept", the_mesh.getNumContacts(), umc_chatlog.count());
  textFClip(VX, y, SCR_W - VX - 6, buf, C_TXT, F_SMALL); y += lh;

  textF(4, y, "Memory", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%u KB free, PSRAM %u KB", (unsigned)(ESP.getFreeHeap() / 1024), (unsigned)(ESP.getFreePsram() / 1024));
  textFClip(VX, y, SCR_W - VX - 6, buf, C_TXT, F_SMALL); y += lh;

  // Uptime and why it last restarted: an unexpected restart shows up here.
  textF(4, y, "Running", C_DIM, F_SMALL);
  const unsigned long up = millis() / 1000;
  const char* died = UmcService::lastBootStage();
  snprintf(buf, sizeof(buf), "%luh %lum %lus  ·  last restart: %s%s%s", up / 3600, (up % 3600) / 60, up % 60,
           UmcService::lastResetReason(), died[0] ? " while starting: " : "", died);
  textFClip(VX, y, SCR_W - VX - 6, buf, C_TXT, F_SMALL); y += lh;

  const int by = SCR_H - TAB_H - 30;
  button(2, by, 74, 26, "Advert");
  button(80, by, 74, 26, "Flood adv");
  button(158, by, 74, 26, isBluetoothEnabled() ? "BT off" : "BT on");
  button(236, by, 80, 26, "Reboot");
}

// ---------------------------------------------------------------- home + radio

// The newest received (not transmitted) packet in the log, or NULL when nothing is logged.
static const UmcTraffic::Entry* lastReceived() {
  for (int i = 0; i < umc_traffic.count(); i++) {
    const UmcTraffic::Entry* e = umc_traffic.get(i);
    if (e != NULL && !e->tx) return e;
  }
  return NULL;
}

void UITask::sampleRadio() {
  // The noise floor the radio driver already measures. Reading the radio over SPI from
  // here would fight the screen and SD card for the same bus and stall the whole device.
  const int nf = radio_driver.getNoiseFloor();
  if (nf) {
    _rssi_hist[_rssi_head] = (int8_t)clampi(nf, -140, 0);
    _rssi_head = (_rssi_head + 1) % RSSI_HIST;
    if (_rssi_n < RSSI_HIST) _rssi_n++;
  }
  // channel busy = (receive + transmit air time) over the last 15 s window
  const unsigned long now = millis();
  if (_busy_t == 0) {
    _busy_t = now;
    _busy_rx = the_mesh.getReceiveAirTime();
    _busy_tx = the_mesh.getTotalAirTime();
  } else if (now - _busy_t >= 15000) {
    const unsigned long rx = the_mesh.getReceiveAirTime(), tx = the_mesh.getTotalAirTime();
    _busy_pct = clampi((int)(((rx - _busy_rx) + (tx - _busy_tx)) * 100UL / (now - _busy_t)), 0, 100);
    _busy_t = now;
    _busy_rx = rx;
    _busy_tx = tx;
  }
}

void UITask::drawHome() {
  const int top = BODY_Y;
  char buf[64];
  static const char* wd[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
  static const char* mon[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};

  // ---- clock and date (local time when a timezone is set, otherwise as the header) ----
  const uint32_t now = rtc_clock.getCurrentTime();
  const bool clock_ok = now > 1700000000UL;
  struct tm lt = {0}, gt = {0};
  int tz_min = 0;
  if (clock_ok) {
    time_t t = (time_t)now;
    localtime_r(&t, &lt);
    gmtime_r(&t, &gt);
    tz_min = (lt.tm_hour * 60 + lt.tm_min) - (gt.tm_hour * 60 + gt.tm_min);
    if (tz_min > 720) tz_min -= 1440;
    if (tz_min < -720) tz_min += 1440;
    snprintf(buf, sizeof(buf), "%02d:%02d", lt.tm_hour, lt.tm_min);
  } else {
    snprintf(buf, sizeof(buf), "--:--");
  }
  textF(8, top + 4, buf, C_TXT, F_BIG);
  if (clock_ok) {
    snprintf(buf, sizeof(buf), "%s %02d %s %04d", wd[weekdayOf(lt.tm_year + 1900, lt.tm_mon + 1, lt.tm_mday)],
             lt.tm_mday, mon[lt.tm_mon], lt.tm_year + 1900);
    textF(8, top + 52, buf, C_DIM, F_SMALL);
  } else {
    textF(8, top + 52, "clock not set", C_WARN, F_SMALL);
  }

  // ---- sunrise / sunset from the node's position ----
  double lat, lon;
  int rise, set;
  if (clock_ok && selfLocation(lat, lon) &&
      sunTimes(lat, lon, lt.tm_year + 1900, lt.tm_mon + 1, lt.tm_mday, tz_min, rise, set)) {
    snprintf(buf, sizeof(buf), "Sunrise %02d:%02d", rise / 60, rise % 60);
    text(8, top + 74, buf, C_WARN);
    snprintf(buf, sizeof(buf), "Sunset  %02d:%02d", set / 60, set % 60);
    text(110, top + 74, buf, C_WARN);
  } else {
    text(8, top + 74, selfLocation(lat, lon) ? "No sunrise/sunset today" : "Sunrise/sunset: needs a location", C_DIM);
  }

  // ---- channel busy ----
  text(176, top + 8, "CHANNEL BUSY", C_DIM);
  if (_busy_pct >= 0) {
    snprintf(buf, sizeof(buf), "%d%%", _busy_pct);
    meter(176, top + 22, 140, 10, _busy_pct / 100.0f, _busy_pct > 60 ? C_BAD : (_busy_pct > 25 ? C_WARN : C_OK));
    textF(176, top + 34, buf, C_TXT, F_MED);
  } else {
    text(176, top + 22, "measuring...", C_DIM);
  }
  const int nf = radio_driver.getNoiseFloor();
  if (nf) {
    snprintf(buf, sizeof(buf), "noise %d dBm", nf);
    text(176, top + 60, buf, C_DIM);
  }

  // ---- status cards ----
  const uint16_t batt = _board->getBattMilliVolts();
  NetworkService& net = the_mesh.getNetwork();
  const UmcTraffic::Entry* last_rx = lastReceived();
  const float rssi = last_rx ? last_rx->rssi : 0.0f;
  const float snr = last_rx ? last_rx->snr4 / 4.0f : 0.0f;
  double glat, glon;
  const bool fix = selfLocation(glat, glon);

  struct Card { const char* title; char val[12]; char sub[22]; uint16_t col; } cards[6];
  memset(cards, 0, sizeof(cards));

  cards[0].title = "BATTERY";
  if (batt) {
    snprintf(cards[0].val, sizeof(cards[0].val), "%d.%02dV", batt / 1000, (batt % 1000) / 10);
    const int pct = clampi((int)(((int)batt - 3300) * 100 / 900), 0, 100);   // rough Li-ion curve
    snprintf(cards[0].sub, sizeof(cards[0].sub), "~%d%%", pct);
    cards[0].col = batt < 3500 ? C_BAD : (batt < 3700 ? C_WARN : C_OK);
  } else {
    snprintf(cards[0].val, sizeof(cards[0].val), "--");
    cards[0].col = C_DIM;
  }

  cards[1].title = "GPS";
  snprintf(cards[1].val, sizeof(cards[1].val), fix ? "FIX" : "NONE");
  if (fix) snprintf(cards[1].sub, sizeof(cards[1].sub), "%.3f,%.3f", glat, glon);
  cards[1].col = fix ? C_OK : C_DIM;

  cards[2].title = "NODES";
  snprintf(cards[2].val, sizeof(cards[2].val), "%d", contactCount());
  snprintf(cards[2].sub, sizeof(cards[2].sub), "contacts");
  cards[2].col = C_TXT;

  cards[3].title = "MESSAGES";
  snprintf(cards[3].val, sizeof(cards[3].val), "%d", umc_chatlog.unread());
  snprintf(cards[3].sub, sizeof(cards[3].sub), "unread / %d kept", umc_chatlog.count());
  cards[3].col = umc_chatlog.unread() > 0 ? C_WARN : C_TXT;

  cards[4].title = "LAST SIGNAL";
  if (rssi != 0) {
    snprintf(cards[4].val, sizeof(cards[4].val), "%d", (int)rssi);
    snprintf(cards[4].sub, sizeof(cards[4].sub), "dBm  SNR %.1f", snr);
    cards[4].col = snr > 5 ? C_OK : (snr > -5 ? C_WARN : C_BAD);
  } else {
    snprintf(cards[4].val, sizeof(cards[4].val), "--");
    cards[4].col = C_DIM;
  }

  cards[5].title = "LINKS";
  snprintf(cards[5].val, sizeof(cards[5].val), net.isWifiConnected() ? "WIFI" : (net.isApActive() ? "AP" : "OFF"));
  snprintf(cards[5].sub, sizeof(cards[5].sub), "BT %s", isBluetoothEnabled() ? (hasConnection() ? "app" : "on") : "off");
  cards[5].col = net.isWifiConnected() ? C_OK : C_DIM;

  for (int i = 0; i < 6; i++) {
    int x, y, w, h;
    homeCard(i, x, y, w, h);
    fill(x, y, w, h, C_CARD);
    gfx()->drawRect(x, y, w, h, C_LINE);
    textClip(x + 4, y + 2, w - 8, cards[i].title, C_DIM);
    textFClip(x + 4, y + 15, w - 8, cards[i].val, cards[i].col, F_MED);
    textClip(x + 4, y + 32, w - 8, cards[i].sub, C_DIM);
  }
}

void UITask::drawRadio() {
  const int top = BODY_Y + 4;
  char buf[80];

  snprintf(buf, sizeof(buf), "%.3f MHz  SF%d  BW%.1f  CR%d  %ddBm", _prefs->freq, _prefs->sf, _prefs->bw, _prefs->cr,
           _prefs->tx_power_dbm);
  textClip(4, top, 312, buf, C_TXT);

  // time on air for typical packet sizes at the live radio settings
  snprintf(buf, sizeof(buf), "Airtime  32B %lums  100B %lums  200B %lums", (unsigned long)radio_driver.getEstAirtimeFor(32),
           (unsigned long)radio_driver.getEstAirtimeFor(100), (unsigned long)radio_driver.getEstAirtimeFor(200));
  textClip(4, top + 18, 312, buf, C_DIM);

  // history statistics
  int peak = -140, now_r = -140;
  for (int i = 0; i < _rssi_n; i++) {
    const int v = _rssi_hist[(_rssi_head + RSSI_HIST - 1 - i) % RSSI_HIST];
    if (i == 0) now_r = v;
    if (v > peak) peak = v;
  }
  const int floor_db = radio_driver.getNoiseFloor() ? radio_driver.getNoiseFloor() : -120;
  const UmcTraffic::Entry* last_rx = lastReceived();
  const float last_rssi = last_rx ? last_rx->rssi : 0.0f;

  // dBm scale -130 .. -40 across the bar
  struct Row { const char* label; int dbm; uint16_t col; bool valid; };
  const Row rows[3] = {
      {"NOW", now_r, C_ACC, _rssi_n > 0},
      {"FLOOR", floor_db, C_DIM, true},
      {"PEAK", peak, C_WARN, _rssi_n > 0},
  };
  int y = top + 38;
  for (int i = 0; i < 3; i++, y += 17) {
    text(4, y - 2, rows[i].label, C_DIM);
    meter(52, y, 190, 10, rows[i].valid ? (rows[i].dbm + 130) / 90.0f : 0, rows[i].col);
    if (rows[i].valid) snprintf(buf, sizeof(buf), "%d dBm", rows[i].dbm);
    else snprintf(buf, sizeof(buf), "--");
    text(248, y - 2, buf, C_TXT);
  }
  // margin: how far the last received packet sat above the noise floor
  text(4, y - 2, "MARGIN", C_DIM);
  if (last_rssi != 0) {
    const int margin = (int)last_rssi - floor_db;
    meter(52, y, 190, 10, margin / 40.0f, margin > 10 ? C_OK : (margin > 3 ? C_WARN : C_BAD));
    snprintf(buf, sizeof(buf), "%+d dB", margin);
  } else {
    meter(52, y, 190, 10, 0, C_DIM);
    snprintf(buf, sizeof(buf), "--");
  }
  text(248, y - 2, buf, C_TXT);
  y += 20;

  // live spectrum: the last two minutes of RSSI, one bar per second
  const int sx = 4, sh = 46, sw = RSSI_HIST * 2;
  fill(sx, y, sw, sh, C_CARD);
  gfx()->drawRect(sx - 1, y - 1, sw + 2, sh + 2, C_LINE);
  for (int i = 0; i < _rssi_n; i++) {
    const int v = _rssi_hist[(_rssi_head + RSSI_HIST - _rssi_n + i) % RSSI_HIST];
    const int bh = clampi((v + 130) * sh / 90, 1, sh);
    fill(sx + (RSSI_HIST - _rssi_n + i) * 2, y + sh - bh, 2, bh, v > floor_db + 10 ? C_WARN : C_ACC);
  }
  text(sx + sw + 6, y, "-40", C_DIM);
  text(sx + sw + 6, y + sh - 13, "-130", C_DIM);
  if (_busy_pct >= 0) {
    snprintf(buf, sizeof(buf), "busy %d%%", _busy_pct);
    text(sx + sw + 6, y + 17, buf, C_TXT);
  }
  y += sh + 6;

  snprintf(buf, sizeof(buf), "Sent flood %lu direct %lu   Heard flood %lu direct %lu", (unsigned long)the_mesh.getNumSentFlood(),
           (unsigned long)the_mesh.getNumSentDirect(), (unsigned long)the_mesh.getNumRecvFlood(),
           (unsigned long)the_mesh.getNumRecvDirect());
  textClip(4, y, 312, buf, C_DIM);
}


// ---------------------------------------------------------------- GPS screen

// Satellites drawn where they are in the sky: the circle edge is the horizon, the middle
// is straight up, north at the top. Filled dots are being received.
void UITask::drawGps() {
  const int top = BODY_Y;
  char buf[64];
  fill(0, top, SCR_W, BODY_H, C_BG);

  const int cx = SCR_W - 70, cy = top + 76, r = 62;
  gfx()->drawCircle(cx, cy, r, C_LINE);
  gfx()->drawCircle(cx, cy, r * 2 / 3, C_LINE);      // 30 degrees up
  gfx()->drawCircle(cx, cy, r / 3, C_LINE);          // 60 degrees up
  gfx()->drawFastHLine(cx - r, cy, r * 2, C_LINE);
  gfx()->drawFastVLine(cx, cy - r, r * 2, C_LINE);
  textF(cx - 3, cy - r - 9, "N", C_DIM, F_SMALL);
  textF(cx + r + 2, cy - 3, "E", C_DIM, F_SMALL);
  textF(cx - 3, cy + r + 3, "S", C_DIM, F_SMALL);
  textF(cx - r - 8, cy - 3, "W", C_DIM, F_SMALL);

  int drawn = 0, strongest = 0;
  for (int i = 0; i < umc_gps_sky.count(); i++) {
    const UmcGpsSky::Sat& s = umc_gps_sky.get(i);
    if (s.elevation < 0 || s.elevation > 90) continue;
    const double az = s.azimuth * M_PI / 180.0;
    const double rr = r * (90 - s.elevation) / 90.0;
    const int x = cx + (int)lround(sin(az) * rr);
    const int y = cy - (int)lround(cos(az) * rr);
    const uint16_t col = s.snr >= 35 ? C_OK : s.snr >= 20 ? C_WARN : s.snr > 0 ? C_ACC : C_DIM;
    if (s.snr > 0) {
      gfx()->fillCircle(x, y, 4, col);
    } else {
      gfx()->drawCircle(x, y, 4, col);
    }
    if (s.snr > strongest) strongest = s.snr;
    drawn++;
  }

  // ---- the numbers, down the left
  int y = top + 6;
  const int VCOL = 70, VW = SCR_W - 70 - 62 - VCOL - 6;   // stops short of the sky circle
  const int lh = 15;
  double lat, lon;
  const bool fix = selfLocation(lat, lon);

  textF(4, y, "Fix", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%s", fix ? "yes" : (drawn ? "searching" : "no signal"));
  textFClip(VCOL, y, VW, buf, fix ? C_OK : C_WARN, F_SMALL); y += lh;

  textF(4, y, "Sats", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%d of %d", (int)sensors.getLocationProvider()->satellitesCount(), drawn);
  textFClip(VCOL, y, VW, buf, C_TXT, F_SMALL); y += lh;

  textF(4, y, "Best", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%d dB", strongest);
  textFClip(VCOL, y, VW, buf, strongest >= 35 ? C_OK : C_TXT, F_SMALL); y += lh;

  textF(4, y, "Position", C_DIM, F_SMALL); y += lh;
  if (fix) {
    snprintf(buf, sizeof(buf), "%.5f", lat);
    textF(10, y, buf, C_TXT, F_SMALL); y += lh;
    snprintf(buf, sizeof(buf), "%.5f", lon);
    textF(10, y, buf, C_TXT, F_SMALL); y += lh;
  } else {
    textF(10, y, "not known yet", C_DIM, F_SMALL); y += lh * 2;
  }

  textF(4, y, "Alt", C_DIM, F_SMALL);
  snprintf(buf, sizeof(buf), "%ld m", sensors.getLocationProvider()->getAltitude() / 1000);
  textFClip(VCOL, y, VW, buf, C_TXT, F_SMALL); y += lh;

  textF(4, y, "Rx", C_DIM, F_SMALL);
  const uint32_t baud = sensors.gpsBaudDetected();
  snprintf(buf, sizeof(buf), "%s", baud == 38400 ? "u-blox" : baud == 9600 ? "L76K" : baud ? "found" : "none");
  textFClip(VCOL, y, VW, buf, baud ? C_TXT : C_WARN, F_SMALL); y += lh;

  textF(4, y, "Power", C_DIM, F_SMALL);
  textFClip(VCOL, y, VW, the_mesh.getNodePrefs()->gps_enabled ? "on" : "off",
            the_mesh.getNodePrefs()->gps_enabled ? C_OK : C_DIM, F_SMALL); y += lh;

  // buttons
  const int by = SCR_H - TAB_H - 26;
  button(4, by, 96, 22, the_mesh.getNodePrefs()->gps_enabled ? "GPS off" : "GPS on");
  button(104, by, 108, 22, "Use as my location");
}

// ---------------------------------------------------------------- setup tab

// The Setup tab is a small menu: a list of sections, each with its own screen. Everything
// is applied through the same command line the web interface uses, so the device and the
// browser can never disagree.

struct RadioBand { const char* name; float freq; float bw; uint8_t sf; uint8_t cr; };
static const RadioBand kBands[] = {
  {"EU/UK 869.6 narrow", 869.618f, 62.5f, 8, 5},
  {"EU/UK 869.5 medium", 869.525f, 250.0f, 10, 5},
  {"EU/UK 869.5 long", 869.525f, 250.0f, 11, 5},
  {"EU 433.65 long", 433.65f, 250.0f, 11, 5},
  {"Switzerland 869.6", 869.618f, 62.5f, 8, 5},
  {"Czech 869.4", 869.432f, 62.5f, 7, 5},
  {"Portugal 433.4", 433.375f, 62.5f, 9, 5},
  {"USA/Canada 910.5", 910.525f, 62.5f, 7, 5},
  {"Australia/NZ 915.8", 915.8f, 62.5f, 8, 5},
};
static const int kBandCount = sizeof(kBands) / sizeof(kBands[0]);
static const int kTxSteps[] = {2, 5, 8, 11, 14, 17, 20, 22};
static const int kTxCount = sizeof(kTxSteps) / sizeof(kTxSteps[0]);
static const char* kScopes[] = {"-", "yorkshire", "northwest", "uk"};
static const int kScopeCount = sizeof(kScopes) / sizeof(kScopes[0]);

// Runs a command and returns the reply with any leading "> " removed.
static const char* umcCli(const char* cmd) {
  static char reply[192];
  reply[0] = 0;
  the_mesh.umcCommand(cmd, reply, sizeof(reply));
  const char* out = reply;
  while (*out == '>' || *out == ' ') out++;
  return out;
}

// Which band the radio is on now, or -1. Compared as numbers: the radio reports its
// frequency in full precision (869.6179809), so text matching would never agree.
static int currentBand() {
  float f = 0, bw = 0;
  int sf = 0, cr = 0;
  if (sscanf(umcCli("get radio"), "%f,%f,%d,%d", &f, &bw, &sf, &cr) != 4) return -1;
  for (int i = 0; i < kBandCount; i++) {
    if (fabsf(kBands[i].freq - f) < 0.01f && fabsf(kBands[i].bw - bw) < 0.1f && kBands[i].sf == sf) return i;
  }
  return -1;
}

void UITask::setupOpen(int page) {
  _setup_page = page;
  _setup_sel = 0;
  _setup_scroll = 0;
  _setup_confirm = -1;
  _dirty = true;
}

void UITask::wifiScanStart() {
  _wifi_scan_state = 1;
  _wifi_found = 0;
  _wifi_scan_started = millis();
  WiFi.scanDelete();
  WiFi.scanNetworks(true, false);   // asynchronous: the screen stays alive
  StrHelper::strncpy(_setup_status, "Scanning...", sizeof(_setup_status));
}

void UITask::wifiScanPoll() {
  if (_wifi_scan_state != 1) return;
  const int n = WiFi.scanComplete();
  if (n >= 0) {
    _wifi_found = n > 24 ? 24 : n;
    _wifi_scan_state = 2;
    snprintf(_setup_status, sizeof(_setup_status), "%d network%s found", _wifi_found, _wifi_found == 1 ? "" : "s");
    _dirty = true;
  } else if (millis() - _wifi_scan_started > 15000) {
    _wifi_scan_state = 2;
    _wifi_found = 0;
    StrHelper::strncpy(_setup_status, "Scan failed", sizeof(_setup_status));
    _dirty = true;
  }
}

int UITask::setupRowCount() const {
  switch (_setup_page) {
    case SP_ROOT: return 13;                   // the sections
    case SP_DEVICE: return 4;                  // name, restart, factory reset, back
    case SP_RADIO: return kBandCount + 2;      // bands, TX power, back
    case SP_WIFI: return 5;                    // scan, network, password, connect, back
    case SP_WIFI_PICK: return _wifi_found + 1; // networks, back
    case SP_BLE: return 3;                     // on/off, PIN, back
    case SP_REGION: return kScopeCount + 1;
    case SP_GPS: return 2;
    case SP_FW: return 4;                      // version, check, install, back
    case SP_CHANNELS: return MAX_GROUP_CHANNELS > 12 ? 14 : MAX_GROUP_CHANNELS + 2;   // channels, add, back
    case SP_MESSAGING: return 7;
    case SP_CONTACTS_CFG: return 8;
    case SP_TELEMETRY: return 4;
    case SP_CONSOLE: return 2;
    case SP_DISPLAY: return kThemeCount + 3;   // themes, touch orientation, brightness, back
    default: return 1;
  }
}

// One row's label and value. Keeping this in one place means the screen and the taps can
// never disagree about what row 4 is.
void UITask::setupRow(int row, char* label, size_t label_n, char* value, size_t value_n) const {
  label[0] = 0;
  value[0] = 0;
  NetworkService& net = the_mesh.getNetwork();
  switch (_setup_page) {
    case SP_ROOT: {
      static const char* sections[13] = {"Device", "Radio", "WiFi", "Bluetooth", "Region", "GPS", "Firmware",
                                         "Channels", "Messaging", "New contacts", "Telemetry", "Command line",
                                         "Display & touch"};
      snprintf(label, label_n, "%s", sections[row]);
      switch (row) {
        case 0: snprintf(value, value_n, "%s", the_mesh.getNodeName()); break;
        case 1: {
          const int b = currentBand();
          snprintf(value, value_n, "%s", b >= 0 ? kBands[b].name : umcCli("get radio"));
          break;
        }
        case 2: snprintf(value, value_n, "%s", net.isWifiConnected() ? net.getStaIp().c_str()
                                                                     : (net.isApActive() ? "hotspot" : "not connected")); break;
        case 3: snprintf(value, value_n, "%s", isBluetoothEnabled() ? "on" : "off"); break;
        case 4: snprintf(value, value_n, "%s", umcCli("get scope")); break;
        case 5: snprintf(value, value_n, "%s", umcCli("gps")); break;
        case 6: snprintf(value, value_n, "v%s", UMC_VERSION); break;
        case 7: {
          int n = 0;
          ChannelDetails ch;
          for (int i = 0; i < MAX_GROUP_CHANNELS; i++) {
            if (the_mesh.getChannel(i, ch) && ch.name[0]) n++;
          }
          snprintf(value, value_n, "%d set up", n);
          break;
        }
        case 8: snprintf(value, value_n, "acks, paths, repeat"); break;
        case 9: snprintf(value, value_n, "%s", strcmp(umcCli("get contacts.manual"), "on") == 0 ? "manual" : "automatic"); break;
        case 10: snprintf(value, value_n, "%s", umcCli("get telemetry.base")); break;
        case 11: snprintf(value, value_n, "run any command"); break;
        case 12: snprintf(value, value_n, "%s", kThemes[g_theme].name); break;
      }
      break;
    }
    case SP_DEVICE:
      if (row == 0) { snprintf(label, label_n, "Name"); snprintf(value, value_n, "%s", the_mesh.getNodeName()); }
      else if (row == 1) { snprintf(label, label_n, "Restart"); snprintf(value, value_n, "%s", _setup_confirm == row ? "tap again" : "tap"); }
      else if (row == 2) { snprintf(label, label_n, "Factory reset"); snprintf(value, value_n, "%s", _setup_confirm == row ? "tap again to erase" : "tap"); }
      else snprintf(label, label_n, "< Back");
      break;
    case SP_RADIO:
      if (row < kBandCount) {
        snprintf(label, label_n, "%s", kBands[row].name);
        snprintf(value, value_n, "%s", currentBand() == row ? "in use" : "");
      } else if (row == kBandCount) {
        snprintf(label, label_n, "TX power");
        snprintf(value, value_n, "%s dBm", umcCli("get tx"));
      } else {
        snprintf(label, label_n, "< Back");
      }
      break;
    case SP_WIFI:
      if (row == 0) { snprintf(label, label_n, "Scan for networks"); snprintf(value, value_n, "%s", _wifi_scan_state == 1 ? "scanning" : "tap"); }
      else if (row == 1) { snprintf(label, label_n, "Network"); snprintf(value, value_n, "%s", _wifi_ssid[0] ? _wifi_ssid : umcCli("get wifi.ssid")); }
      else if (row == 2) { snprintf(label, label_n, "Password"); snprintf(value, value_n, "%s", _wifi_pwd[0] ? "********" : "not set"); }
      else if (row == 3) { snprintf(label, label_n, "Connect"); snprintf(value, value_n, "%s", net.isWifiConnected() ? net.getStaIp().c_str() : "tap"); }
      else snprintf(label, label_n, "< Back");
      break;
    case SP_WIFI_PICK:
      if (row < _wifi_found) {
        snprintf(label, label_n, "%s", WiFi.SSID(row).c_str());
        snprintf(value, value_n, "%d dBm%s", (int)WiFi.RSSI(row), WiFi.encryptionType(row) == WIFI_AUTH_OPEN ? "  open" : "");
      } else {
        snprintf(label, label_n, "< Back");
      }
      break;
    case SP_BLE:
      if (row == 0) {
        snprintf(label, label_n, "Bluetooth");
        snprintf(value, value_n, "%s%s", isBluetoothEnabled() ? "on" : "off", _ble_pending ? " (restart to apply)" : "");
      } else if (row == 1) {
        snprintf(label, label_n, "Pairing PIN");
        snprintf(value, value_n, "%lu", (unsigned long)the_mesh.getBLEPin());
      } else {
        snprintf(label, label_n, "< Back");
      }
      break;
    case SP_REGION:
      if (row < kScopeCount) {
        snprintf(label, label_n, "%s", strcmp(kScopes[row], "-") == 0 ? "No region (whole mesh)" : kScopes[row]);
        snprintf(value, value_n, "%s", strcmp(umcCli("get scope"), kScopes[row]) == 0 ? "in use" : "");
      } else {
        snprintf(label, label_n, "< Back");
      }
      break;
    case SP_GPS:
      if (row == 0) { snprintf(label, label_n, "GPS"); snprintf(value, value_n, "%s", umcCli("gps")); }
      else snprintf(label, label_n, "< Back");
      break;
    case SP_FW:
      if (row == 0) { snprintf(label, label_n, "Version"); snprintf(value, value_n, "%s (MeshCore %s)", UMC_VERSION, FIRMWARE_VERSION); }
      else if (row == 1) { snprintf(label, label_n, "Check for update"); snprintf(value, value_n, "%s", umcCli("get update.status")); }
      else if (row == 2) { snprintf(label, label_n, "Install update"); snprintf(value, value_n, "%s", _setup_confirm == row ? "tap again" : "needs WiFi"); }
      else snprintf(label, label_n, "< Back");
      break;

    case SP_CHANNELS: {
      const int slots = setupRowCount() - 2;
      if (row < slots) {
        ChannelDetails ch;
        if (the_mesh.getChannel(row, ch) && ch.name[0]) {
          snprintf(label, label_n, "%d  %s", row, ch.name);
          snprintf(value, value_n, "%s", _setup_confirm == row ? "tap again to remove" : "");
        } else {
          snprintf(label, label_n, "%d  (empty)", row);
        }
      } else if (row == slots) {
        snprintf(label, label_n, "Add a #channel");
        snprintf(value, value_n, "type its name");
      } else {
        snprintf(label, label_n, "< Back");
      }
      break;
    }

    case SP_MESSAGING:
      switch (row) {
        case 0: snprintf(label, label_n, "Extra ACKs"); snprintf(value, value_n, "%s", strcmp(umcCli("get multi.acks"), "1") == 0 ? "on" : "off"); break;
        case 1: snprintf(label, label_n, "Path hash size"); snprintf(value, value_n, "%s byte(s)", umcCli("get path.hash.mode")); break;
        case 2: snprintf(label, label_n, "Share my location"); snprintf(value, value_n, "%s", umcCli("get advert.loc")); break;
        case 3: snprintf(label, label_n, "Relay for others"); snprintf(value, value_n, "%s", umcCli("get repeat")); break;
        case 4: snprintf(label, label_n, "Airtime factor"); snprintf(value, value_n, "%s", umcCli("get af")); break;
        case 5: snprintf(label, label_n, "RX delay"); snprintf(value, value_n, "%s", umcCli("get rxdelay")); break;
        default: snprintf(label, label_n, "< Back"); break;
      }
      break;

    case SP_CONTACTS_CFG:
      switch (row) {
        case 0: snprintf(label, label_n, "Add new contacts"); snprintf(value, value_n, "%s", strcmp(umcCli("get contacts.manual"), "on") == 0 ? "only the types below" : "automatically"); break;
        case 1: snprintf(label, label_n, "Chat nodes"); snprintf(value, value_n, "%s", umcCli("get autoadd.chat")); break;
        case 2: snprintf(label, label_n, "Repeaters"); snprintf(value, value_n, "%s", umcCli("get autoadd.repeater")); break;
        case 3: snprintf(label, label_n, "Room servers"); snprintf(value, value_n, "%s", umcCli("get autoadd.room")); break;
        case 4: snprintf(label, label_n, "Sensors"); snprintf(value, value_n, "%s", umcCli("get autoadd.sensor")); break;
        case 5: snprintf(label, label_n, "Replace oldest"); snprintf(value, value_n, "%s", umcCli("get autoadd.overwrite")); break;
        case 6: snprintf(label, label_n, "Max hops"); snprintf(value, value_n, "%s", umcCli("get autoadd.maxhops")); break;
        default: snprintf(label, label_n, "< Back"); break;
      }
      break;

    case SP_TELEMETRY:
      if (row == 0) { snprintf(label, label_n, "Battery & basic"); snprintf(value, value_n, "%s", umcCli("get telemetry.base")); }
      else if (row == 1) { snprintf(label, label_n, "Location"); snprintf(value, value_n, "%s", umcCli("get telemetry.loc")); }
      else if (row == 2) { snprintf(label, label_n, "Sensors"); snprintf(value, value_n, "%s", umcCli("get telemetry.env")); }
      else snprintf(label, label_n, "< Back");
      break;

    case SP_CONSOLE:
      if (row == 0) { snprintf(label, label_n, "Command"); snprintf(value, value_n, "%s", _console_cmd[0] ? _console_cmd : "tap to type"); }
      else snprintf(label, label_n, "< Back");
      break;

    case SP_DISPLAY:
      if (row < kThemeCount) {
        snprintf(label, label_n, "Theme: %s", kThemes[row].name);
        snprintf(value, value_n, "%s", g_theme == row ? "in use" : "");
      } else if (row == kThemeCount) {
        snprintf(label, label_n, "Touch orientation");
        snprintf(value, value_n, "%s  (tap to change)", umcCli("get touch.map"));
      } else if (row == kThemeCount + 1) {
        snprintf(label, label_n, "Backlight");
        snprintf(value, value_n, "%d%%", (int)brightness());
      } else {
        snprintf(label, label_n, "< Back");
      }
      break;
    default: snprintf(label, label_n, "< Back"); break;
  }
}

void UITask::drawSetup() {
  const int top = BODY_Y;
  const int row_h = 20;
  const int list_top = top + 18;
  const int rows_visible = (BODY_H - 18 - 14) / row_h;
  char label[64], value[80];

  wifiScanPoll();

  if (_editing) {   // typing line
    fill(0, top, SCR_W, BODY_H, C_BG);
    static const char* what[] = {"", "Node name", "WiFi network", "WiFi password", "Bluetooth PIN", "Region name",
                                 "Channel name (without the #)", "Command"};
    textF(8, top + 12, what[_edit_what], C_DIM, F_SMALL);
    fill(6, top + 32, SCR_W - 12, 28, C_CARD);
    gfx()->drawRect(6, top + 32, SCR_W - 12, 28, C_ACC);
    char shown[sizeof(_edit_buf)];
    if (_edit_secret) {
      int n = _edit_len < (int)sizeof(shown) - 2 ? _edit_len : (int)sizeof(shown) - 2;
      for (int i = 0; i < n; i++) shown[i] = '*';
      shown[n] = 0;
    } else {
      StrHelper::strncpy(shown, _edit_buf, sizeof(shown));
    }
    strncat(shown, "_", sizeof(shown) - strlen(shown) - 1);
    textFClip(12, top + 42, SCR_W - 24, shown, C_TXT, F_SMALL);
    textF(8, top + 72, "Enter saves   Esc cancels   Backspace deletes", C_DIM, F_SMALL);
    return;
  }

  static const char* titles[] = {"Setup", "Device", "Radio band", "WiFi", "Choose a network",
                                 "Bluetooth", "Region scope", "GPS", "Firmware", "Channels", "Messaging",
                                 "New contacts", "Telemetry sharing", "Command line", "Display & touch"};
  fill(0, top, SCR_W, 16, C_CARD);
  textF(6, top + 4, titles[_setup_page], C_ACC, F_SMALL);
  if (_setup_page != SP_ROOT) textF(SCR_W - 76, top + 4, "Back: left", C_DIM, F_SMALL);

  const int count = setupRowCount();
  if (_setup_sel >= count) _setup_sel = count - 1;
  if (_setup_sel < 0) _setup_sel = 0;
  if (_setup_sel < _setup_scroll) _setup_scroll = _setup_sel;
  if (_setup_sel >= _setup_scroll + rows_visible) _setup_scroll = _setup_sel - rows_visible + 1;

  fill(0, list_top, SCR_W, BODY_H - 18 - 14, C_BG);
  for (int i = 0; i < rows_visible; i++) {
    const int row = _setup_scroll + i;
    if (row >= count) break;
    const int y = list_top + i * row_h;
    const bool on = row == _setup_sel;
    if (on) fill(0, y, SCR_W, row_h, C_CARD);
    setupRow(row, label, sizeof(label), value, sizeof(value));
    const bool danger = _setup_page == SP_DEVICE && row == 2 && _setup_confirm == row;
    textF(6, y + 6, label, on ? C_TXT : C_DIM, F_SMALL);
    textFClip(150, y + 6, SCR_W - 156, value, danger ? C_BAD : (on ? C_TXT : C_DIM), F_SMALL);
  }

  if (count > rows_visible) {   // a hint that the list goes on
    char pos[24];
    snprintf(pos, sizeof(pos), "%d/%d", _setup_sel + 1, count);
    textF(SCR_W - 42, SCR_H - TAB_H - 12, pos, C_DIM, F_SMALL);
  }
  if (_setup_page == SP_CONSOLE && _console_out[0]) {
    // the reply, wrapped over the rest of the screen
    int y = list_top + 2 * 20 + 4;
    const char* p = _console_out;
    char line[46];
    while (*p && y < SCR_H - TAB_H - 12) {
      size_t n = 0;
      while (p[n] && p[n] != '\n' && n < sizeof(line) - 1) n++;
      memcpy(line, p, n);
      line[n] = 0;
      text(6, y, line, C_TXT);
      y += 11;
      p += n;
      while (*p == '\n') p++;
    }
  }
  if (_setup_status[0]) textFClip(6, SCR_H - TAB_H - 12, SCR_W - 50, _setup_status, C_OK, F_SMALL);
}

void UITask::setupAction(int row) {
  char cmd[128];
  const int page = _setup_page;
  if (!(page == SP_DEVICE && (row == 1 || row == 2))) _setup_confirm = -1;

  switch (page) {
    case SP_ROOT: {
      static const int pages[13] = {SP_DEVICE, SP_RADIO, SP_WIFI, SP_BLE, SP_REGION, SP_GPS, SP_FW,
                                    SP_CHANNELS, SP_MESSAGING, SP_CONTACTS_CFG, SP_TELEMETRY, SP_CONSOLE,
                                    SP_DISPLAY};
      setupOpen(pages[row < 13 ? row : 0]);
      return;
    }

    case SP_DEVICE:
      if (row == 0) {
        _editing = true; _edit_what = SE_NAME; _edit_secret = false;
        StrHelper::strncpy(_edit_buf, the_mesh.getNodeName(), sizeof(_edit_buf));
        _edit_len = strlen(_edit_buf);
      } else if (row == 1) {
        if (_setup_confirm != row) { _setup_confirm = row; break; }
        showAlert("Restarting...", 1200);
        draw();
        delay(600);
        the_mesh.getUmc().scheduleReboot(200);
      } else if (row == 2) {
        if (_setup_confirm != row) { _setup_confirm = row; break; }
        StrHelper::strncpy(_setup_status, umcCli("factory reset confirm"), sizeof(_setup_status));
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    case SP_RADIO:
      if (row < kBandCount) {
        snprintf(cmd, sizeof(cmd), "set radio %.3f,%.1f,%u,%u", kBands[row].freq, kBands[row].bw,
                 (unsigned)kBands[row].sf, (unsigned)kBands[row].cr);
        StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      } else if (row == kBandCount) {
        const int now = atoi(umcCli("get tx"));
        int next = kTxSteps[0];
        for (int i = 0; i < kTxCount; i++) {
          if (kTxSteps[i] == now) { next = kTxSteps[(i + 1) % kTxCount]; break; }
        }
        snprintf(cmd, sizeof(cmd), "set tx %d", next);
        StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    case SP_WIFI:
      if (row == 0) { wifiScanStart(); setupOpen(SP_WIFI_PICK); return; }
      if (row == 1) {
        _editing = true; _edit_what = SE_SSID; _edit_secret = false;
        StrHelper::strncpy(_edit_buf, _wifi_ssid, sizeof(_edit_buf));
        _edit_len = strlen(_edit_buf);
      } else if (row == 2) {
        _editing = true; _edit_what = SE_PASSWORD; _edit_secret = true;
        _edit_buf[0] = 0; _edit_len = 0;
      } else if (row == 3) {
        if (_wifi_ssid[0] == 0) { StrHelper::strncpy(_setup_status, "Choose a network first", sizeof(_setup_status)); break; }
        snprintf(cmd, sizeof(cmd), "set wifi.ssid %s", _wifi_ssid);
        umcCli(cmd);
        snprintf(cmd, sizeof(cmd), "set wifi.pwd %s", _wifi_pwd);
        umcCli(cmd);
        StrHelper::strncpy(_setup_status, umcCli("wifi reconnect"), sizeof(_setup_status));
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    case SP_WIFI_PICK:
      if (row < _wifi_found) {
        StrHelper::strncpy(_wifi_ssid, WiFi.SSID(row).c_str(), sizeof(_wifi_ssid));
        snprintf(_setup_status, sizeof(_setup_status), "Chosen: %s", _wifi_ssid);
        setupOpen(SP_WIFI);
        _setup_sel = 2;      // straight to the password
        return;
      }
      setupOpen(SP_WIFI);
      return;

    case SP_BLE:
      if (row == 0) {
        StrHelper::strncpy(_setup_status, umcCli(isBluetoothEnabled() ? "set ble off" : "set ble on"), sizeof(_setup_status));
        _ble_pending = true;
      } else if (row == 1) {
        _editing = true; _edit_what = SE_PIN; _edit_secret = false;
        snprintf(_edit_buf, sizeof(_edit_buf), "%lu", (unsigned long)the_mesh.getBLEPin());
        _edit_len = strlen(_edit_buf);
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    case SP_REGION:
      if (row < kScopeCount) {
        snprintf(cmd, sizeof(cmd), "set scope %s", kScopes[row]);
        StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    case SP_GPS:
      if (row == 0) {
        StrHelper::strncpy(_setup_status, umcCli(strcmp(umcCli("gps"), "on") == 0 ? "gps off" : "gps on"), sizeof(_setup_status));
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    case SP_FW:
      if (row == 1) {
        StrHelper::strncpy(_setup_status, umcCli("update check"), sizeof(_setup_status));
      } else if (row == 2) {
        if (_setup_confirm != row) { _setup_confirm = row; break; }
        StrHelper::strncpy(_setup_status, umcCli("update install"), sizeof(_setup_status));
      } else if (row == 3) {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    case SP_CHANNELS: {
      const int slots = setupRowCount() - 2;
      if (row < slots) {
        ChannelDetails ch;
        if (the_mesh.getChannel(row, ch) && ch.name[0]) {
          if (_setup_confirm != row) { _setup_confirm = row; break; }
          ChannelDetails blank;
          memset(&blank, 0, sizeof(blank));
          the_mesh.setChannel(row, blank);
          the_mesh.saveChannels();
          StrHelper::strncpy(_setup_status, "Channel removed", sizeof(_setup_status));
          _setup_confirm = -1;
        }
      } else if (row == slots) {
        _editing = true; _edit_what = SE_CHANNEL; _edit_secret = false;
        _edit_buf[0] = 0; _edit_len = 0;
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;
    }

    case SP_MESSAGING:
      switch (row) {
        case 0: StrHelper::strncpy(_setup_status, umcCli(strcmp(umcCli("get multi.acks"), "1") == 0 ? "set multi.acks 0" : "set multi.acks 1"), sizeof(_setup_status)); break;
        case 1: {
          const int now = atoi(umcCli("get path.hash.mode"));
          snprintf(cmd, sizeof(cmd), "set path.hash.mode %d", (now + 1) % 3);
          StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
          break;
        }
        case 2: StrHelper::strncpy(_setup_status, umcCli(strcmp(umcCli("get advert.loc"), "share") == 0 ? "set advert.loc none" : "set advert.loc share"), sizeof(_setup_status)); break;
        case 3: StrHelper::strncpy(_setup_status, umcCli(strcmp(umcCli("get repeat"), "on") == 0 ? "set repeat off" : "set repeat on"), sizeof(_setup_status)); break;
        case 4: {
          const float now = atof(umcCli("get af"));
          snprintf(cmd, sizeof(cmd), "set af %.1f", now >= 2.0f ? 0.0f : now + 0.5f);
          StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
          break;
        }
        case 5: {
          const float now = atof(umcCli("get rxdelay"));
          snprintf(cmd, sizeof(cmd), "set rxdelay %.1f", now >= 10.0f ? 0.0f : now + 2.5f);
          StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
          break;
        }
        default: setupOpen(SP_ROOT); return;
      }
      break;

    case SP_CONTACTS_CFG: {
      static const char* keys[7] = {"contacts.manual", "autoadd.chat", "autoadd.repeater", "autoadd.room",
                                    "autoadd.sensor", "autoadd.overwrite", "autoadd.maxhops"};
      if (row >= 0 && row < 6) {
        snprintf(cmd, sizeof(cmd), "get %s", keys[row]);
        const bool on = strcmp(umcCli(cmd), "on") == 0;
        snprintf(cmd, sizeof(cmd), "set %s %s", keys[row], on ? "off" : "on");
        StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      } else if (row == 6) {
        const int now = atoi(umcCli("get autoadd.maxhops"));
        snprintf(cmd, sizeof(cmd), "set autoadd.maxhops %d", now >= 6 ? 0 : now + 1);
        StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;
    }

    case SP_TELEMETRY: {
      static const char* tkeys[3] = {"telemetry.base", "telemetry.loc", "telemetry.env"};
      static const char* tvals[3] = {"deny", "contacts", "all"};
      if (row >= 0 && row < 3) {
        snprintf(cmd, sizeof(cmd), "get %s", tkeys[row]);
        const char* now = umcCli(cmd);
        int next = 0;
        for (int i = 0; i < 3; i++) {
          if (strcmp(now, tvals[i]) == 0) { next = (i + 1) % 3; break; }
        }
        snprintf(cmd, sizeof(cmd), "set %s %s", tkeys[row], tvals[next]);
        StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;
    }

    case SP_DISPLAY: {
      char cmd2[48];
      if (row < kThemeCount) {
        snprintf(cmd2, sizeof(cmd2), "set theme %d", row);
        StrHelper::strncpy(_setup_status, umcCli(cmd2), sizeof(_setup_status));
        applyTheme();
      } else if (row == kThemeCount) {
        const int now = atoi(umcCli("get touch.map"));
        snprintf(cmd2, sizeof(cmd2), "set touch.map %d", (now + 1) % 8);
        StrHelper::strncpy(_setup_status, umcCli(cmd2), sizeof(_setup_status));
        _input.setTouchMap((now + 1) % 8);
      } else if (row == kThemeCount + 1) {
        setBrightness(brightness() >= 100 ? 20 : brightness() + 20);
        snprintf(_setup_status, sizeof(_setup_status), "Backlight %d%%", (int)brightness());
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;
    }

    case SP_CONSOLE:
      if (row == 0) {
        _editing = true; _edit_what = SE_COMMAND; _edit_secret = false;
        StrHelper::strncpy(_edit_buf, _console_cmd, sizeof(_edit_buf));
        _edit_len = strlen(_edit_buf);
      } else {
        setupOpen(SP_ROOT);
        return;
      }
      break;

    default:
      setupOpen(SP_ROOT);
      return;
  }
  _dirty = true;
}

// Runs one command and keeps the reply for the screen.
void UITask::consoleRun(const char* cmd) {
  _console_out[0] = 0;
  if (cmd == NULL || cmd[0] == 0) return;
  the_mesh.umcCommand(cmd, _console_out, sizeof(_console_out));
  if (_console_out[0] == 0) StrHelper::strncpy(_console_out, "(no reply)", sizeof(_console_out));
}

void UITask::setupEditDone() {
  char cmd[160];
  switch (_edit_what) {
    case SE_NAME:
      if (_edit_len > 0) {
        snprintf(cmd, sizeof(cmd), "set name %s", _edit_buf);
        StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      }
      break;
    case SE_SSID:
      StrHelper::strncpy(_wifi_ssid, _edit_buf, sizeof(_wifi_ssid));
      break;
    case SE_PASSWORD:
      StrHelper::strncpy(_wifi_pwd, _edit_buf, sizeof(_wifi_pwd));
      break;
    case SE_PIN:
      snprintf(cmd, sizeof(cmd), "set ble.pin %s", _edit_buf);
      StrHelper::strncpy(_setup_status, umcCli(cmd), sizeof(_setup_status));
      _ble_pending = true;
      break;
    case SE_CHANNEL:
      if (_edit_len > 0) {
        // a hashtag channel: its key is worked out from the name, the same way the apps do
        ChannelDetails ch;
        memset(&ch, 0, sizeof(ch));
        char hashed[40];
        snprintf(hashed, sizeof(hashed), "#%s", _edit_buf[0] == '#' ? _edit_buf + 1 : _edit_buf);
        StrHelper::strncpy(ch.name, hashed, sizeof(ch.name));
        TransportKeyStore temp;
        TransportKey key;
        temp.getAutoKeyFor(0, hashed, key);
        memset(ch.channel.secret, 0, sizeof(ch.channel.secret));
        memcpy(ch.channel.secret, key.key, 16);   // 128-bit, as the apps use
        int slot = -1;
        ChannelDetails existing;
        for (int i = 0; i < MAX_GROUP_CHANNELS; i++) {
          if (!the_mesh.getChannel(i, existing) || existing.name[0] == 0) { slot = i; break; }
        }
        if (slot < 0) {
          StrHelper::strncpy(_setup_status, "No free channel slots", sizeof(_setup_status));
        } else if (the_mesh.setChannel(slot, ch)) {
          the_mesh.saveChannels();
          snprintf(_setup_status, sizeof(_setup_status), "Added %s", hashed);
        } else {
          StrHelper::strncpy(_setup_status, "Could not add that channel", sizeof(_setup_status));
        }
      }
      break;
    case SE_COMMAND:
      StrHelper::strncpy(_console_cmd, _edit_buf, sizeof(_console_cmd));
      consoleRun(_console_cmd);
      break;
    default: break;
  }
  _editing = false;
  _edit_what = SE_NONE;
  _edit_buf[0] = 0;
  _edit_len = 0;
  _dirty = true;
}

// ---------------------------------------------------------------- input

bool UITask::touchInTabs(const TouchEvent& ev) {
  if (!ev.released || ev.y < SCR_H - TAB_H) return false;
  const int w = SCR_W / TAB_COUNT;
  const int t = ev.x / w;
  if (t >= 0 && t < TAB_COUNT) {
    _tab = (Tab)t;
    if (_tab == TAB_MSGS) umc_chatlog.markRead();
    if (_tab == TAB_MAP && _follow_self) centreOnSelf();
    _dirty = true;
  }
  return true;
}

void UITask::handleTouch(const TouchEvent& ev) {
  if (touchInTabs(ev)) return;

  if (_tab == TAB_HOME) {
    static const Tab target[6] = {TAB_INFO, TAB_MAP, TAB_CONTACTS, TAB_MSGS, TAB_RADIO, TAB_INFO};
    for (int i = 0; i < 6; i++) {
      int x, y, w, h;
      homeCard(i, x, y, w, h);
      if (hit(ev, x, y, w, h)) {
        _tab = target[i];
        if (_tab == TAB_MSGS) umc_chatlog.markRead();
        if (_tab == TAB_MAP && _follow_self) centreOnSelf();
        _dirty = true;
        return;
      }
    }
  }

  if (_tab == TAB_MSGS) {
    const int top = BODY_Y + 2;
    if (hit(ev, SCR_W - 52, top, 50, 16)) {   // change conversation
      // cycle: channels with a name, then contacts we have messages from
      ChannelDetails ch;
      if (_to_channel) {
        int next = _to_channel_idx + 1;
        while (next < MAX_GROUP_CHANNELS && (!the_mesh.getChannel(next, ch) || !ch.name[0])) next++;
        if (next < MAX_GROUP_CHANNELS) {
          _to_channel_idx = next;
          StrHelper::strncpy(_to_name, ch.name, sizeof(_to_name));
        } else if (contactCount() > 0) {
          selectContact(0);
        }
      } else {
        // move to the next contact, then wrap back to channel 0
        int idx = -1;
        ContactInfo c;
        for (int i = 0; i < contactCount(); i++) {
          if (contactAt(i, c) && memcmp(c.id.pub_key, _to_key, 6) == 0) { idx = i; break; }
        }
        if (idx >= 0 && idx + 1 < the_mesh.getNumContacts()) {
          selectContact(idx + 1);
        } else {
          _to_channel = true;
          _to_channel_idx = 0;
          if (the_mesh.getChannel(0, ch)) StrHelper::strncpy(_to_name, ch.name, sizeof(_to_name));
        }
      }
      _dirty = true;
      return;
    }
    if (hit(ev, SCR_W - 62, SCR_H - TAB_H - COMPOSE_H + 3, 58, 20)) { sendCompose(); return; }
    if (_reply_to[0] && hit(ev, SCR_W - 34, SCR_H - TAB_H - COMPOSE_H - 12, 32, 12)) {
      _reply_to[0] = 0;              // stop replying
      _msg_sel = -1;
      _dirty = true;
      return;
    }
    if (ev.released) {               // tap a message to reply to it
      for (int i = 0; i < _msg_rows; i++) {
        if (ev.y >= _msg_row_y[i] && ev.y < _msg_row_bottom[i]) {
          const UmcChatLog::Entry* e = umc_chatlog.get(_msg_row_idx[i]);
          if (e != NULL) {
            _msg_sel = _msg_row_idx[i];
            StrHelper::strncpy(_reply_to, e->text, sizeof(_reply_to));
            _dirty = true;
          }
          return;
        }
      }
    }
    if (ev.down && ev.dy) {                    // drag the message list
      _msg_scroll = max(0, _msg_scroll + (ev.dy > 0 ? 1 : -1));
      _dirty = true;
    }
    return;
  }

  if (_tab == TAB_CONTACTS) {
    const int row_h = 22, top = BODY_Y + 14;
    const int by = SCR_H - TAB_H - 26;
    const int total = contactCount();
    ContactInfo c;
    if (_contact_sel >= 0 && _contact_sel < total && contactAt(_contact_sel, c)) {
      if (hit(ev, 2, by, 74, 22)) { selectContact(_contact_sel); _tab = TAB_MSGS; _dirty = true; return; }
      if (hit(ev, 80, by, 74, 22)) {
        if (c.gps_lat || c.gps_lon) {
          _centre_lat = c.gps_lat / 1e6; _centre_lon = c.gps_lon / 1e6; _follow_self = false; _tab = TAB_MAP;
        } else showAlert("No location for that contact", 1500);
        _dirty = true; return;
      }
      if (hit(ev, 158, by, 74, 22)) {
        showAlert(the_mesh.shareContactZeroHop(c) ? "Shared with nodes in range" : "Busy - try again", 1500);
        return;
      }
      if (hit(ev, 236, by, 80, 22)) {
        ContactInfo* live = the_mesh.lookupContactByPubKey(c.id.pub_key, PUB_KEY_SIZE);
        if (live) { the_mesh.resetPathTo(*live); showAlert("Path reset", 1500); }
        return;
      }
    }
    if (ev.released && ev.y >= top && ev.y < SCR_H - TAB_H - 28) {
      const int idx = _contact_scroll + (ev.y - top) / row_h;
      if (idx >= 0 && idx < total) { _contact_sel = idx; _dirty = true; }
      return;
    }
    if (ev.down && ev.dy) {
      _contact_scroll = max(0, _contact_scroll - (ev.dy > 0 ? 1 : -1));
      _dirty = true;
    }
    return;
  }

  if (_tab == TAB_MAP) {
    const int top = BODY_Y;
    if (hit(ev, SCR_W - 30, top + 4, 26, 24)) { if (_zoom < 19) _zoom++; _dirty = true; return; }
    if (hit(ev, SCR_W - 30, top + 32, 26, 24)) { if (_zoom > 1) _zoom--; _dirty = true; return; }
    if (hit(ev, SCR_W - 62, top + BODY_H - 28, 58, 24)) { centreOnSelf(); _dirty = true; return; }
    if (ev.down && (ev.dx || ev.dy)) {         // pan
      const double scale = UMC_TILE_PX * (1 << _zoom);
      _centre_lon -= ev.dx * 360.0 / scale;
      const double cy = UmcTiles::latToWorldY(_centre_lat, _zoom) - ev.dy;
      _centre_lat = UmcTiles::worldYToLat(cy, _zoom);
      _follow_self = false;
      _dirty = true;
    }
    return;
  }

  if (_tab == TAB_GPS) {
    const int by = SCR_H - TAB_H - 26;
    if (hit(ev, 4, by, 96, 22)) {
      showAlert(umcCli(the_mesh.getNodePrefs()->gps_enabled ? "gps off" : "gps on"), 1500);
      return;
    }
    if (hit(ev, 104, by, 108, 22)) {
      double lat, lon;
      if (selfLocation(lat, lon)) {
        char cmd[48];
        snprintf(cmd, sizeof(cmd), "set lat %.5f", lat);
        umcCli(cmd);
        snprintf(cmd, sizeof(cmd), "set lon %.5f", lon);
        showAlert(umcCli(cmd), 1500);
      } else {
        showAlert("No fix yet", 1500);
      }
      return;
    }
    return;
  }

  if (_tab == TAB_SETUP) {
    if (_editing) return;            // the keyboard does the talking while editing
    const int row_h = 20, list_top = BODY_Y + 18;
    if (ev.released && ev.y >= BODY_Y && ev.y < list_top) {   // the title bar goes back
      if (_setup_page != SP_ROOT) setupOpen(SP_ROOT);
      return;
    }
    if (ev.released && ev.y >= list_top && ev.y < SCR_H - TAB_H) {
      const int row = _setup_scroll + (ev.y - list_top) / row_h;
      if (row >= 0 && row < setupRowCount()) {
        _setup_sel = row;
        setupAction(row);
      }
    }
    return;
  }

  if (_tab != TAB_INFO) return;   // the buttons below belong to the Info tab only

  const int by = SCR_H - TAB_H - 30;
  if (hit(ev, 2, by, 74, 26)) { showAlert(the_mesh.advert() ? "Advert sent" : "Busy - try again", 1500); return; }
  if (hit(ev, 80, by, 74, 26)) {
    char reply[96];
    the_mesh.umcCommand("advert.flood", reply, sizeof(reply));
    showAlert(reply, 1800);
    return;
  }
  if (hit(ev, 158, by, 74, 26)) {
    if (isBluetoothEnabled()) disableBluetooth(); else enableBluetooth();
    showAlert(isBluetoothEnabled() ? "Bluetooth on" : "Bluetooth off", 1500);
    return;
  }
  if (hit(ev, 236, by, 80, 26)) {
    showAlert("Rebooting...", 1200);
    draw();
    delay(800);
    the_mesh.getUmc().scheduleReboot(200);
  }
}

void UITask::handleKey(char c) {
  if (_tab == TAB_SETUP) {
    if (_editing) {
      if (c == 8 || c == 127) {                   // backspace
        if (_edit_len > 0) _edit_buf[--_edit_len] = 0;
      } else if (c == 13 || c == 10) {            // enter saves
        setupEditDone();
      } else if (c == 27) {                       // escape cancels
        _editing = false; _edit_what = SE_NONE; _edit_len = 0; _edit_buf[0] = 0;
      } else if (c >= 32 && c < 127 && _edit_len < (int)sizeof(_edit_buf) - 1) {
        _edit_buf[_edit_len++] = c;
        _edit_buf[_edit_len] = 0;
      }
    } else if (c == 13 || c == 10) {
      setupAction(_setup_sel);
    }
    _dirty = true;
    return;
  }
  if (_tab != TAB_MSGS) {
    _tab = TAB_MSGS;   // typing anywhere jumps to the messages screen
    umc_chatlog.markRead();
  }
  if (c == 8 || c == 127) {                 // backspace
    if (_compose_len > 0) _compose[--_compose_len] = 0;
  } else if (c == 13 || c == 10) {          // enter sends
    sendCompose();
  } else if (c >= 32 && c < 127 && _compose_len < (int)sizeof(_compose) - 1) {
    _compose[_compose_len++] = c;
    _compose[_compose_len] = 0;
  }
  _dirty = true;
}

void UITask::selectContact(int idx) {
  ContactInfo c;
  if (!contactAt(idx, c)) return;
  _to_channel = false;
  memcpy(_to_key, c.id.pub_key, 6);
  StrHelper::strncpy(_to_name, c.name[0] ? c.name : "contact", sizeof(_to_name));
  _contact_sel = idx;
  _dirty = true;
}

void UITask::sendCompose() {
  if (_compose_len == 0) return;
  if (_reply_to[0]) {   // put a short quote of what is being answered on the front
    char quoted[sizeof(_compose)];
    char head[28];
    StrHelper::strncpy(head, _reply_to, sizeof(head));
    snprintf(quoted, sizeof(quoted), "> %s\n%s", head, _compose);
    StrHelper::strncpy(_compose, quoted, sizeof(_compose));
    _compose_len = strlen(_compose);
    _reply_to[0] = 0;
    _msg_sel = -1;
  }
  const uint32_t ts = rtc_clock.getCurrentTimeUnique();
  if (_to_channel) {
    ChannelDetails ch;
    if (!the_mesh.getChannel(_to_channel_idx, ch) || !ch.name[0]) { showAlert("No channel selected", 1500); return; }
    if (the_mesh.sendGroupMessage(ts, ch.channel, the_mesh.getNodeName(), _compose, _compose_len)) {
      umc_chatlog.addChannel(_to_channel_idx, the_mesh.getNodeName(), _compose, ts, true);
      showAlert("Sent", 900);
    } else {
      showAlert("Send failed", 1500);
    }
  } else {
    ContactInfo* c = the_mesh.lookupContactByPubKey(_to_key, 6);
    if (c == NULL) { showAlert("Contact not found", 1500); return; }
    uint32_t ack, timeout;
    const int res = the_mesh.sendMessage(*c, ts, 0, _compose, ack, timeout);
    if (res == MSG_SEND_FAILED) {
      showAlert("Send failed", 1500);
    } else {
      umc_chatlog.addDirect(_to_key, "", _compose, ts, true);
      showAlert(res == MSG_SEND_SENT_FLOOD ? "Sent (flood)" : "Sent", 900);
    }
  }
  _compose[0] = 0;
  _compose_len = 0;
  _msg_scroll = 0;
  _dirty = true;
}
