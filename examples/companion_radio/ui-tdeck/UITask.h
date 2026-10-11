#pragma once

#include <Arduino.h>
#include <MeshCore.h>
#include <helpers/SensorManager.h>
#include <helpers/ui/DisplayDriver.h>
#include <helpers/umc/UmcChatLog.h>
#include <helpers/umc/UmcGpsSky.h>
#include <helpers/umc/UmcTraffic.h>

#include "../AbstractUITask.h"
#include "../NodePrefs.h"
#include "TDeckInput.h"
#include "UmcTiles.h"

// Touch interface for the LilyGo T-Deck / T-Deck Plus running the Ultimate MeshCore Client.
//
//   Messages  - conversations with the on-screen log and the built-in keyboard
//   Contacts  - everyone the radio knows, with actions
//   Map       - offline map tiles from the SD card (or a range/bearing plot without them),
//               showing this node and every contact that shares its location
//   Info      - radio, WiFi, Bluetooth, GPS, storage and quick actions
class UITask : public AbstractUITask {
public:
  UITask(mesh::MainBoard* board, MultiSerialInterface* serial) : AbstractUITask(board, serial) {}

  void begin(DisplayDriver* display, SensorManager* sensors, NodePrefs* node_prefs);

  // AbstractUITask
  void msgRead(int msgcount) override;
  void newMsg(uint8_t path_len, const char* from_name, const char* text, int msgcount) override;
  void notify(UIEventType t = UIEventType::none) override;
  void loop() override;

  void showAlert(const char* text, int duration_millis);
  bool hasDisplay() const { return _display != NULL; }
  void setBrightness(uint8_t pct);
  uint8_t brightness() const { return _brightness; }
  void setTouchMap(uint8_t m) { _input.setTouchMap(m); }
  const char* mapStatus() { return _tiles.status(); }

private:
  enum Tab { TAB_HOME = 0, TAB_MSGS, TAB_CONTACTS, TAB_MAP, TAB_GPS, TAB_RADIO, TAB_SETUP, TAB_INFO, TAB_COUNT };

  void draw();
  void drawHeader();
  void drawTabs();
  void drawMessages();
  void drawContacts();
  void drawMap();
  void drawInfo();
  void drawHome();
  void drawRadio();
  void drawGps();
  void drawSetup();
  void setupAction(int row);
  void setupEditDone();
  void setupOpen(int page);
  void consoleRun(const char* cmd);
  int setupRowCount() const;
  void setupRow(int row, char* label, size_t label_n, char* value, size_t value_n) const;
  void wifiScanStart();
  void wifiScanPoll();
  void sampleRadio();
  void drawCompose();
  void applyTheme();
  int drawBubble(int y_bottom, const char* who, const char* body, bool mine, bool selected, uint32_t when);
  void drawAlert();
  uint32_t screenSignature();

  void handleTouch(const TouchEvent& ev);
  void handleKey(char c);
  bool touchInTabs(const TouchEvent& ev);
  void sendCompose();
  void selectContact(int idx);
  void centreOnSelf();
  bool selfLocation(double& lat, double& lon) const;

  DisplayDriver* _display = NULL;
  SensorManager* _sensors = NULL;
  NodePrefs* _prefs = NULL;
  TDeckInput _input;
  UmcTiles _tiles;

  Tab _tab = TAB_MSGS;
  bool _dirty = true;
  unsigned long _last_draw = 0;
  unsigned long _tiles_retry = 0;

  // Setup tab: a list of settings, changed on the device itself
  int _setup_page = 0;              // which Setup screen (SetupPage)
  int _setup_sel = 0;
  int _setup_scroll = 0;
  int _setup_confirm = -1;          // row waiting for a second tap to confirm
  bool _editing = false;            // typing into _edit_buf
  bool _edit_secret = false;
  int _edit_what = -1;              // SetupEdit
  char _edit_buf[72] = {0};
  int _edit_len = 0;
  char _wifi_ssid[33] = {0};        // chosen or typed, applied by "Connect"
  char _wifi_pwd[65] = {0};
  char _setup_status[64] = {0};
  int _msg_sel = -1;                // message tapped, to reply to
  int _msg_rows = 0;                // where each bubble ended up, so a tap finds it
  int _msg_row_y[12] = {0};
  int _msg_row_bottom[12] = {0};
  int _msg_row_idx[12] = {0};
  char _reply_to[48] = {0};         // what that message said, quoted in the reply
  char _console_cmd[80] = {0};      // last command typed on the console page
  char _console_out[320] = {0};     // and what it said
  bool _ble_pending = false;        // Bluetooth setting waiting for a restart
  int _wifi_scan_state = 0;         // 0 idle, 1 scanning, 2 done
  int _wifi_found = 0;
  unsigned long _wifi_scan_started = 0;
  uint32_t _last_sig = 0;
  static const unsigned long kMinRedrawMs = 400;
  unsigned long _next_refresh = 0;
  unsigned long _alert_expiry = 0;
  char _alert[64] = {0};
  uint32_t _log_rev = 0;
  uint8_t _brightness = 100;

  // conversation being written to: channel index, or a contact key prefix
  bool _to_channel = true;
  uint8_t _to_channel_idx = 0;
  uint8_t _to_key[6] = {0};
  char _to_name[32] = "Public";

  char _compose[140] = {0};
  int _compose_len = 0;

  int _msg_scroll = 0;       // 0 = newest at the bottom
  int _contact_scroll = 0;
  int _contact_sel = -1;

  // map view
  int _zoom = 12;
  double _centre_lat = 0, _centre_lon = 0;
  bool _follow_self = true;
  int _map_marker_sel = -1;

  // radio tab: one RSSI sample per second (about two minutes of history) and channel-busy estimate
  static const int RSSI_HIST = 120;
  int8_t _rssi_hist[RSSI_HIST] = {0};
  uint8_t _rssi_n = 0, _rssi_head = 0;
  unsigned long _next_rssi = 0, _next_fast = 0;
  unsigned long _busy_t = 0, _busy_rx = 0, _busy_tx = 0;
  int _busy_pct = -1;        // -1 until the first 15 s window has completed
};
