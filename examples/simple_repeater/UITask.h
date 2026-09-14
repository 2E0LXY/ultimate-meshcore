#pragma once

#include <helpers/ui/DisplayDriver.h>
#include <helpers/CommonCLI.h>

#ifdef UMC_BUILD
class UmcService;
#endif

class UITask {
  mesh::MainBoard* _board;
  DisplayDriver* _display;
  unsigned long _next_read, _next_refresh, _auto_off;
  int _prevBtnState;
  NodePrefs* _node_prefs;
  char _version_info[32];
  unsigned long _powering_off_at = 0;
  unsigned long _started_at = 0;
#ifdef UMC_BUILD
  UmcService* _umc = nullptr;
  unsigned long _cycle_start = 0;     // start of the current IP -> settings -> traffic cycle
  unsigned long _manual_until = 0;    // button browsing pauses the automatic cycle
  int _manual_page = 0;
  void renderUmcScreen();
  void renderIpPage(bool flash_on);
  void renderPage(int page);
  void renderTraffic();
  void header(const char* title, int page, int pages);
#endif

  void renderCurrScreen();
public:
  UITask(mesh::MainBoard& board, DisplayDriver& display) : _board(&board), _display(&display) { _next_read = _next_refresh = 0; }
  void begin(NodePrefs* node_prefs, const char* build_date, const char* firmware_version);
#ifdef UMC_BUILD
  void setUmc(UmcService* umc) { _umc = umc; }
#endif

  void loop();
};
