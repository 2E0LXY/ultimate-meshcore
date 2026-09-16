#pragma once

#include <Arduino.h>
#include <MeshCore.h>
#include <helpers/SensorManager.h>
#include <helpers/ui/DisplayDriver.h>
#include <helpers/umc/UmcChatLog.h>

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
  enum Tab { TAB_MSGS = 0, TAB_CONTACTS, TAB_MAP, TAB_INFO, TAB_COUNT };

  void draw();
  void drawHeader();
  void drawTabs();
  void drawMessages();
  void drawContacts();
  void drawMap();
  void drawInfo();
  void drawCompose();
  void drawAlert();

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
};
