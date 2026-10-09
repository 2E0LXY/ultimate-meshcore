#include "UITask.h"

#include <Adafruit_ST7789.h>
#include <helpers/ui/ST7789LCDDisplay.h>

#include "../MyMesh.h"
#include "target.h"

#include <math.h>
#include <time.h>

// ---- layout (320 x 240 landscape) ----
#define SCR_W 320
#define SCR_H 240
#define HDR_H 20
#define TAB_H 30
#define BODY_Y HDR_H
#define BODY_H (SCR_H - HDR_H - TAB_H)
#define COMPOSE_H 26

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

static void text(int x, int y, const char* s, uint16_t c, int size = 1) {
  gfx()->setTextSize(size);
  gfx()->setTextColor(c);
  gfx()->setCursor(x, y);
  gfx()->print(s);
}

// Prints at most max_w pixels, adding "…" when the text is cut.
static void textClip(int x, int y, int max_w, const char* s, uint16_t c, int size = 1) {
  const int cw = 6 * size;
  int chars = max_w / cw;
  if (chars <= 0) return;
  char buf[64];
  int n = strlen(s);
  if (n <= chars) {
    strncpy(buf, s, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = 0;
  } else {
    if (chars > (int)sizeof(buf) - 1) chars = sizeof(buf) - 1;
    strncpy(buf, s, chars - 1);
    buf[chars - 1] = '~';
    buf[chars] = 0;
  }
  text(x, y, buf, c, size);
}

static void button(int x, int y, int w, int h, const char* label, bool on = false) {
  fill(x, y, w, h, on ? C_ACC : C_CARD);
  gfx()->drawRect(x, y, w, h, C_LINE);
  const int tw = strlen(label) * 6;
  text(x + (w - tw) / 2, y + (h - 8) / 2, label, on ? 0xFFFF : C_TXT);
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
  h = 44;
  x = 4 + (i % 3) * (w + 3);
  y = BODY_Y + 92 + (i / 3) * (h + 4);
}

void UITask::begin(DisplayDriver* disp, SensorManager* sensors, NodePrefs* node_prefs) {
  _display = disp;
  _sensors = sensors;
  _prefs = node_prefs;
  if (_display) _display->turnOn();
  // start screen
  fill(0, 0, SCR_W, SCR_H, C_BG);
  text(40, 60, "Ultimate MeshCore", C_ACC, 2);
  text(88, 96, "Client v" UMC_VERSION, C_TXT, 2);
  text(104, 128, "MeshCore " FIRMWARE_VERSION, C_DIM);
  text(76, 168, "By Daren Loxley  2E0LXY", C_TXT);
  delay(2500);
  _input.begin(SCR_W, SCR_H, the_mesh.getUmc().prefs().touch_map);
  _tiles.begin();
#ifdef PIN_TFT_LEDA_CTL
  pinMode(PIN_TFT_LEDA_CTL, OUTPUT);
  digitalWrite(PIN_TFT_LEDA_CTL, HIGH);
#endif
  ChannelDetails ch;
  if (the_mesh.getChannel(0, ch) && ch.name[0]) {
    StrHelper::strncpy(_to_name, ch.name, sizeof(_to_name));
  }
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
  strncpy(_alert, t, sizeof(_alert) - 1);
  _alert[sizeof(_alert) - 1] = 0;
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

  char key = _input.readKey();
  if (key) handleKey(key);

  char tb = _input.readTrackball();
  if (tb) {
    if (tb == 'U') { _msg_scroll++; _contact_scroll = max(0, _contact_scroll - 1); }
    if (tb == 'D') { _msg_scroll = max(0, _msg_scroll - 1); _contact_scroll++; }
    if (tb == 'L') _tab = (Tab)((_tab + TAB_COUNT - 1) % TAB_COUNT);
    if (tb == 'R') _tab = (Tab)((_tab + 1) % TAB_COUNT);
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
    _next_refresh = millis() + 5000;
    if (_input.touchMap() != the_mesh.getUmc().prefs().touch_map) _input.setTouchMap(the_mesh.getUmc().prefs().touch_map);
    _dirty = true;
  }
  if (_dirty) {
    _dirty = false;
    draw();
  }
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
    case TAB_RADIO: drawRadio(); break;
    default: drawInfo(); break;
  }
  drawTabs();
  drawAlert();
}

void UITask::drawHeader() {
  fill(0, 0, SCR_W, HDR_H, C_CARD);
  textClip(4, 6, 150, the_mesh.getNodeName(), C_TXT);

  char buf[40];
  uint32_t now = rtc_clock.getCurrentTime();
  DateTime dt(now);
  snprintf(buf, sizeof(buf), "%02d:%02d", dt.hour(), dt.minute());
  text(SCR_W - 34, 6, buf, C_TXT);

  int x = SCR_W - 52;
  const uint16_t batt = _board->getBattMilliVolts();
  snprintf(buf, sizeof(buf), "%d.%02dV", batt / 1000, (batt % 1000) / 10);
  text(x - 36, 6, buf, batt && batt < 3500 ? C_BAD : C_DIM);

  // link indicators
  text(160, 6, the_mesh.getNetwork().isWifiConnected() ? "wifi" : (the_mesh.getNetwork().isApActive() ? "AP" : "----"),
       the_mesh.getNetwork().isWifiConnected() ? C_OK : C_DIM);
  text(192, 6, isBluetoothEnabled() ? (hasConnection() ? "BT+" : "BT") : "--", hasConnection() ? C_OK : C_DIM);
}

void UITask::drawTabs() {
  static const char* names[TAB_COUNT] = {"Home", "Msgs", "People", "Map", "Radio", "Info"};
  const int w = SCR_W / TAB_COUNT;
  for (int i = 0; i < TAB_COUNT; i++) {
    const bool on = (int)_tab == i;
    fill(i * w, SCR_H - TAB_H, w, TAB_H, on ? C_ACC : C_CARD);
    gfx()->drawFastVLine(i * w, SCR_H - TAB_H, TAB_H, C_LINE);
    char label[16];
    if (i == TAB_MSGS && umc_chatlog.unread() > 0 && !on) snprintf(label, sizeof(label), "Msgs(%d)", umc_chatlog.unread());
    else snprintf(label, sizeof(label), "%s", names[i]);
    const int tw = strlen(label) * 6;
    text(i * w + (w - tw) / 2, SCR_H - TAB_H + 11, label, on ? 0xFFFF : C_TXT);
  }
}

void UITask::drawAlert() {
  if (!_alert_expiry) return;
  const int w = 260, h = 34, x = (SCR_W - w) / 2, y = 90;
  fill(x, y, w, h, C_ACC);
  gfx()->drawRect(x, y, w, h, 0xFFFF);
  textClip(x + 8, y + 13, w - 16, _alert, 0xFFFF);
}

void UITask::drawMessages() {
  const int top = BODY_Y + 2;
  const int list_h = BODY_H - COMPOSE_H - 4;

  // conversation being written to
  fill(0, top, SCR_W, 16, C_CARD);
  char hdr[48];
  snprintf(hdr, sizeof(hdr), "To: %s%s", _to_channel ? "#" : "", _to_name);
  textClip(4, top + 4, SCR_W - 60, hdr, C_TXT);
  button(SCR_W - 52, top, 50, 16, "change");

  // messages, newest at the bottom
  int y = top + 18 + list_h - 12;
  const int first = umc_chatlog.count() - 1 - _msg_scroll;
  for (int i = first; i >= 0 && y > top + 18; i--) {
    const UmcChatLog::Entry* e = umc_chatlog.get(i);
    if (e == nullptr) continue;
    char who[40];
    if (e->outgoing) snprintf(who, sizeof(who), "me%s", e->channel != 0xFF ? " >" : " >");
    else if (e->from[0]) snprintf(who, sizeof(who), "%s", e->from);
    else snprintf(who, sizeof(who), "%02x%02x%02x", e->key[0], e->key[1], e->key[2]);

    // wrap the text to two lines at most
    const int cols = 48;
    char line1[64] = {0}, line2[64] = {0};
    strncpy(line1, e->text, cols);
    if ((int)strlen(e->text) > cols) strncpy(line2, e->text + cols, cols);
    const int lines = line2[0] ? 2 : 1;
    y -= (lines - 1) * 10;
    if (y <= top + 18) break;

    const uint16_t col = e->outgoing ? C_ME : (e->cli ? C_WARN : C_TXT);
    char tag[24];
    if (e->channel != 0xFF) snprintf(tag, sizeof(tag), "#%d %s:", e->channel, who);
    else snprintf(tag, sizeof(tag), "%s:", who);
    text(4, y, tag, C_DIM);
    const int indent = 4 + strlen(tag) * 6 + 4;
    textClip(indent, y, SCR_W - indent - 4, line1, col);
    if (line2[0]) textClip(4, y + 10, SCR_W - 8, line2, col);
    y -= 12;
  }
  if (umc_chatlog.count() == 0) {
    text(8, top + 40, "No messages yet.", C_DIM);
    text(8, top + 54, "Type below and press Enter to send.", C_DIM);
  }
  drawCompose();
}

void UITask::drawCompose() {
  const int y = SCR_H - TAB_H - COMPOSE_H;
  fill(0, y, SCR_W, COMPOSE_H, C_CARD);
  gfx()->drawFastHLine(0, y, SCR_W, C_LINE);
  const int max_w = SCR_W - 68;
  const char* shown = _compose;
  const int cols = max_w / 6;
  if (_compose_len > cols) shown = _compose + (_compose_len - cols);
  text(4, y + 9, shown[0] ? shown : "type a message...", shown[0] ? C_TXT : C_DIM);
  if (shown[0]) {
    const int cx = 4 + strlen(shown) * 6;
    fill(cx, y + 7, 6, 11, C_ACC);
  }
  button(SCR_W - 62, y + 3, 58, 20, "Send", _compose_len > 0);
}

void UITask::drawContacts() {
  const int top = BODY_Y + 2;
  const int row_h = 22;
  const int rows = (BODY_H - 30) / row_h;
  const int total = the_mesh.getNumContacts();
  if (_contact_scroll > max(0, total - rows)) _contact_scroll = max(0, total - rows);

  char buf[48];
  snprintf(buf, sizeof(buf), "Contacts %d", total);
  text(4, top, buf, C_DIM);

  const uint32_t now = rtc_clock.getCurrentTime();
  int y = top + 12;
  for (int i = 0; i < rows; i++) {
    const int idx = _contact_scroll + i;
    if (idx >= total) break;
    ContactInfo c;
    if (!the_mesh.getContactByIdx(idx, c)) continue;
    const bool sel = idx == _contact_sel;
    fill(0, y, SCR_W, row_h - 2, sel ? C_ACC : C_CARD);
    textClip(4, y + 3, 150, c.name[0] ? c.name : "(no name)", sel ? 0xFFFF : C_TXT);
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
  if (total == 0) text(8, top + 30, "Nothing heard yet. Send an advert from Info.", C_DIM);

  // actions for the selected contact
  const int by = SCR_H - TAB_H - 26;
  if (_contact_sel >= 0 && _contact_sel < total) {
    button(2, by, 74, 22, "Message");
    button(80, by, 74, 22, "Show map");
    button(158, by, 74, 22, "Share");
    button(236, by, 80, 22, "Reset path");
  } else {
    text(6, by + 7, "Tap a contact to select it", C_DIM);
  }
}

void UITask::drawMap() {
  const int top = BODY_Y;
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
  const int total = the_mesh.getNumContacts();
  double far_m = 1;
  for (int i = 0; i < total; i++) {
    ContactInfo c;
    if (!the_mesh.getContactByIdx(i, c)) continue;
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
  text(4, top + BODY_H - 12, z, C_DIM);
}

void UITask::drawInfo() {
  const int top = BODY_Y + 4;
  char buf[80];
  int y = top;
  const int lh = 13;

  text(4, y, "Node", C_DIM); textClip(60, y, 250, the_mesh.getNodeName(), C_TXT); y += lh;

  NetworkService& net = the_mesh.getNetwork();
  text(4, y, "WiFi", C_DIM);
  if (net.isWifiConnected()) {
    snprintf(buf, sizeof(buf), "%s  %s", net.getWifiSSID(), net.getStaIp().c_str());
  } else if (net.isApActive()) {
    snprintf(buf, sizeof(buf), "hotspot %s  192.168.4.1", net.getApSsid());
  } else {
    snprintf(buf, sizeof(buf), "not connected");
  }
  textClip(60, y, 250, buf, net.isWifiConnected() || net.isApActive() ? C_TXT : C_DIM); y += lh;

  text(4, y, "Web", C_DIM);
  snprintf(buf, sizeof(buf), "%s.local", net.getHostname());
  textClip(60, y, 250, buf, C_TXT); y += lh;

  text(4, y, "Bluetooth", C_DIM);
  if (!isBluetoothEnabled()) snprintf(buf, sizeof(buf), "off");
  else if (hasConnection()) snprintf(buf, sizeof(buf), "app connected");
  else snprintf(buf, sizeof(buf), "pairing PIN %lu", (unsigned long)the_mesh.getBLEPin());
  textClip(60, y, 250, buf, isBluetoothEnabled() ? C_TXT : C_DIM); y += lh;

  text(4, y, "Radio", C_DIM);
  snprintf(buf, sizeof(buf), "%.3f MHz  SF%d  BW%.1f  %ddBm", _prefs->freq, _prefs->sf, _prefs->bw, _prefs->tx_power_dbm);
  textClip(60, y, 250, buf, C_TXT); y += lh;

  text(4, y, "GPS", C_DIM);
  double lat, lon;
  if (selfLocation(lat, lon)) snprintf(buf, sizeof(buf), "%.4f, %.4f", lat, lon);
  else snprintf(buf, sizeof(buf), "no fix / not set");
  textClip(60, y, 250, buf, C_TXT); y += lh;

  text(4, y, "Maps", C_DIM); textClip(60, y, 250, _tiles.status(), _tiles.available() ? C_TXT : C_DIM); y += lh;

  text(4, y, "Contacts", C_DIM);
  snprintf(buf, sizeof(buf), "%d contacts, %d messages kept", the_mesh.getNumContacts(), umc_chatlog.count());
  textClip(60, y, 250, buf, C_TXT); y += lh;

  text(4, y, "Memory", C_DIM);
  snprintf(buf, sizeof(buf), "%u KB free, PSRAM %u KB", (unsigned)(ESP.getFreeHeap() / 1024), (unsigned)(ESP.getFreePsram() / 1024));
  textClip(60, y, 250, buf, C_TXT); y += lh;

  const int by = SCR_H - TAB_H - 30;
  button(2, by, 74, 26, "Advert");
  button(80, by, 74, 26, "Flood adv");
  button(158, by, 74, 26, isBluetoothEnabled() ? "BT off" : "BT on");
  button(236, by, 80, 26, "Reboot");
}

// ---------------------------------------------------------------- home + radio

void UITask::sampleRadio() {
  // one RSSI reading a second while the radio is listening (not transmitting)
  if (radio_driver.isInRecvMode()) {
    const int r = clampi((int)radio_driver.getCurrentRSSI(), -140, 0);
    _rssi_hist[_rssi_head] = (int8_t)r;
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
  text(8, top + 6, buf, C_TXT, 5);
  if (clock_ok) {
    snprintf(buf, sizeof(buf), "%s %02d %s %04d", wd[weekdayOf(lt.tm_year + 1900, lt.tm_mon + 1, lt.tm_mday)],
             lt.tm_mday, mon[lt.tm_mon], lt.tm_year + 1900);
    text(8, top + 52, buf, C_DIM, 2);
  } else {
    text(8, top + 52, "clock not set", C_WARN, 2);
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
    text(176, top + 36, buf, C_TXT, 2);
  } else {
    text(176, top + 24, "measuring...", C_DIM);
  }
  const int nf = radio_driver.getNoiseFloor();
  if (nf) {
    snprintf(buf, sizeof(buf), "noise %d dBm", nf);
    text(176, top + 60, buf, C_DIM);
  }

  // ---- status cards ----
  const uint16_t batt = _board->getBattMilliVolts();
  NetworkService& net = the_mesh.getNetwork();
  const float rssi = radio_driver.getLastRSSI();
  const float snr = radio_driver.getLastSNR();
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
  snprintf(cards[2].val, sizeof(cards[2].val), "%d", the_mesh.getNumContacts());
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
    text(x + 4, y + 4, cards[i].title, C_DIM);
    text(x + 4, y + 16, cards[i].val, cards[i].col, 2);
    textClip(x + 4, y + 34, w - 8, cards[i].sub, C_DIM);
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
  textClip(4, top + 12, 312, buf, C_DIM);

  // history statistics
  int peak = -140, now_r = -140;
  for (int i = 0; i < _rssi_n; i++) {
    const int v = _rssi_hist[(_rssi_head + RSSI_HIST - 1 - i) % RSSI_HIST];
    if (i == 0) now_r = v;
    if (v > peak) peak = v;
  }
  const int floor_db = radio_driver.getNoiseFloor() ? radio_driver.getNoiseFloor() : -120;
  const float last_rssi = radio_driver.getLastRSSI();

  // dBm scale -130 .. -40 across the bar
  struct Row { const char* label; int dbm; uint16_t col; bool valid; };
  const Row rows[3] = {
      {"NOW", now_r, C_ACC, _rssi_n > 0},
      {"FLOOR", floor_db, C_DIM, true},
      {"PEAK", peak, C_WARN, _rssi_n > 0},
  };
  int y = top + 30;
  for (int i = 0; i < 3; i++, y += 15) {
    text(4, y + 1, rows[i].label, C_DIM);
    meter(52, y, 190, 10, rows[i].valid ? (rows[i].dbm + 130) / 90.0f : 0, rows[i].col);
    if (rows[i].valid) snprintf(buf, sizeof(buf), "%d dBm", rows[i].dbm);
    else snprintf(buf, sizeof(buf), "--");
    text(248, y + 1, buf, C_TXT);
  }
  // margin: how far the last received packet sat above the noise floor
  text(4, y + 1, "MARGIN", C_DIM);
  if (last_rssi != 0) {
    const int margin = (int)last_rssi - floor_db;
    meter(52, y, 190, 10, margin / 40.0f, margin > 10 ? C_OK : (margin > 3 ? C_WARN : C_BAD));
    snprintf(buf, sizeof(buf), "%+d dB", margin);
  } else {
    meter(52, y, 190, 10, 0, C_DIM);
    snprintf(buf, sizeof(buf), "--");
  }
  text(248, y + 1, buf, C_TXT);
  y += 18;

  // live spectrum: the last two minutes of RSSI, one bar per second
  const int sx = 4, sh = 40, sw = RSSI_HIST * 2;
  fill(sx, y, sw, sh, C_CARD);
  gfx()->drawRect(sx - 1, y - 1, sw + 2, sh + 2, C_LINE);
  for (int i = 0; i < _rssi_n; i++) {
    const int v = _rssi_hist[(_rssi_head + RSSI_HIST - _rssi_n + i) % RSSI_HIST];
    const int bh = clampi((v + 130) * sh / 90, 1, sh);
    fill(sx + (RSSI_HIST - _rssi_n + i) * 2, y + sh - bh, 2, bh, v > floor_db + 10 ? C_WARN : C_ACC);
  }
  text(sx + sw + 6, y, "-40", C_DIM);
  text(sx + sw + 6, y + sh - 8, "-130", C_DIM);
  if (_busy_pct >= 0) {
    snprintf(buf, sizeof(buf), "busy %d%%", _busy_pct);
    text(sx + sw + 6, y + 16, buf, C_TXT);
  }
  y += sh + 6;

  snprintf(buf, sizeof(buf), "Sent flood %lu direct %lu   Heard flood %lu direct %lu", (unsigned long)the_mesh.getNumSentFlood(),
           (unsigned long)the_mesh.getNumSentDirect(), (unsigned long)the_mesh.getNumRecvFlood(),
           (unsigned long)the_mesh.getNumRecvDirect());
  textClip(4, y, 312, buf, C_DIM);
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
        } else if (the_mesh.getNumContacts() > 0) {
          selectContact(0);
        }
      } else {
        // move to the next contact, then wrap back to channel 0
        int idx = -1;
        ContactInfo c;
        for (int i = 0; i < the_mesh.getNumContacts(); i++) {
          if (the_mesh.getContactByIdx(i, c) && memcmp(c.id.pub_key, _to_key, 6) == 0) { idx = i; break; }
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
    if (ev.down && ev.dy) {                    // drag the message list
      _msg_scroll = max(0, _msg_scroll + (ev.dy > 0 ? 1 : -1));
      _dirty = true;
    }
    return;
  }

  if (_tab == TAB_CONTACTS) {
    const int row_h = 22, top = BODY_Y + 14;
    const int by = SCR_H - TAB_H - 26;
    const int total = the_mesh.getNumContacts();
    ContactInfo c;
    if (_contact_sel >= 0 && _contact_sel < total && the_mesh.getContactByIdx(_contact_sel, c)) {
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

  // Info tab
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
  if (!the_mesh.getContactByIdx(idx, c)) return;
  _to_channel = false;
  memcpy(_to_key, c.id.pub_key, 6);
  StrHelper::strncpy(_to_name, c.name[0] ? c.name : "contact", sizeof(_to_name));
  _contact_sel = idx;
  _dirty = true;
}

void UITask::sendCompose() {
  if (_compose_len == 0) return;
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
