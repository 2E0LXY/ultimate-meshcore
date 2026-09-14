#include "UITask.h"
#include "target.h"
#include <Arduino.h>
#include <WiFi.h>
#include <helpers/CommonCLI.h>

#ifndef USER_BTN_PRESSED
#define USER_BTN_PRESSED LOW
#endif

#define AUTO_OFF_MILLIS      20000  // 20 seconds
#define BOOT_SCREEN_MILLIS   4000   // 4 seconds

#define POWEROFF_DELAY 3000

// 'meshcore', 128x13px
static const uint8_t meshcore_logo [] PROGMEM = {
    0x3c, 0x01, 0xe3, 0xff, 0xc7, 0xff, 0x8f, 0x03, 0x87, 0xfe, 0x1f, 0xfe, 0x1f, 0xfe, 0x1f, 0xfe, 
    0x3c, 0x03, 0xe3, 0xff, 0xc7, 0xff, 0x8e, 0x03, 0x8f, 0xfe, 0x3f, 0xfe, 0x1f, 0xff, 0x1f, 0xfe, 
    0x3e, 0x03, 0xc3, 0xff, 0x8f, 0xff, 0x0e, 0x07, 0x8f, 0xfe, 0x7f, 0xfe, 0x1f, 0xff, 0x1f, 0xfc, 
    0x3e, 0x07, 0xc7, 0x80, 0x0e, 0x00, 0x0e, 0x07, 0x9e, 0x00, 0x78, 0x0e, 0x3c, 0x0f, 0x1c, 0x00, 
    0x3e, 0x0f, 0xc7, 0x80, 0x1e, 0x00, 0x0e, 0x07, 0x1e, 0x00, 0x70, 0x0e, 0x38, 0x0f, 0x3c, 0x00, 
    0x7f, 0x0f, 0xc7, 0xfe, 0x1f, 0xfc, 0x1f, 0xff, 0x1c, 0x00, 0x70, 0x0e, 0x38, 0x0e, 0x3f, 0xf8, 
    0x7f, 0x1f, 0xc7, 0xfe, 0x0f, 0xff, 0x1f, 0xff, 0x1c, 0x00, 0xf0, 0x0e, 0x38, 0x0e, 0x3f, 0xf8, 
    0x7f, 0x3f, 0xc7, 0xfe, 0x0f, 0xff, 0x1f, 0xff, 0x1c, 0x00, 0xf0, 0x1e, 0x3f, 0xfe, 0x3f, 0xf0, 
    0x77, 0x3b, 0x87, 0x00, 0x00, 0x07, 0x1c, 0x0f, 0x3c, 0x00, 0xe0, 0x1c, 0x7f, 0xfc, 0x38, 0x00, 
    0x77, 0xfb, 0x8f, 0x00, 0x00, 0x07, 0x1c, 0x0f, 0x3c, 0x00, 0xe0, 0x1c, 0x7f, 0xf8, 0x38, 0x00, 
    0x73, 0xf3, 0x8f, 0xff, 0x0f, 0xff, 0x1c, 0x0e, 0x3f, 0xf8, 0xff, 0xfc, 0x70, 0x78, 0x7f, 0xf8, 
    0xe3, 0xe3, 0x8f, 0xff, 0x1f, 0xfe, 0x3c, 0x0e, 0x3f, 0xf8, 0xff, 0xfc, 0x70, 0x3c, 0x7f, 0xf8, 
    0xe3, 0xe3, 0x8f, 0xff, 0x1f, 0xfc, 0x3c, 0x0e, 0x1f, 0xf8, 0xff, 0xf8, 0x70, 0x3c, 0x7f, 0xf8, 
};

void UITask::begin(NodePrefs* node_prefs, const char* build_date, const char* firmware_version) {
  _prevBtnState = HIGH;
  _auto_off = millis() + AUTO_OFF_MILLIS;
  _started_at = millis();
  _node_prefs = node_prefs;
  _display->turnOn();

#if defined(PIN_USER_BTN) && defined(DISPLAY_CLASS)
  user_btn.begin();
#endif

  // strip off dash and commit hash by changing dash to null terminator
  // e.g: v1.2.3-abcdef -> v1.2.3
  char *version = strdup(firmware_version);
  char *dash = strchr(version, '-');
  if(dash){
    *dash = 0;
  }

  // v1.2.3 (1 Jan 2025)
  snprintf(_version_info, sizeof(_version_info), "%s (%s)", version, build_date);
  free(version);
}

#ifdef UMC_BUILD
#include <helpers/NetworkService.h>
#include <helpers/umc/UmcService.h>
#include <helpers/umc/UmcTraffic.h>
#include <helpers/umc/UmcVersion.h>

namespace {
constexpr int kUmcSettingsPages = 4;            // radio, mesh, network, status
constexpr unsigned long kManualHoldMs = 30000;  // button browsing pauses the cycle
}

void UITask::header(const char* title, int page, int pages) {
  _display->setColor(UIColor::primary_txt);
  _display->setTextSize(1);
  _display->setCursor(0, 0);
  _display->print(title);
  // page dots, right aligned
  for (int i = 0; i < pages; i++) {
    int x = _display->width() - (pages - i) * 6;
    if (i == page) _display->fillRect(x, 2, 4, 4);
    else _display->drawRect(x, 2, 4, 4);
  }
  _display->fillRect(0, 10, _display->width(), 1);
}

void UITask::renderIpPage(bool flash_on) {
  char tmp[40];
  NetworkService* net = _umc ? _umc->network() : nullptr;
  header("NETWORK", 0, 1);
  _display->setCursor(0, 14);
  if (net != nullptr && net->isApActive() && (_umc->isSetupMode() || !net->isWifiConnected())) {
    _display->print(_umc->isSetupMode() ? "SETUP: join WiFi" : "RESCUE: join WiFi");
    _display->drawTextEllipsized(0, 24, _display->width(), net->getApSsid());
    if (_umc->isSetupMode()) snprintf(tmp, sizeof(tmp), "Open - no password");
    else snprintf(tmp, sizeof(tmp), "PIN %s", _umc->getPin());
    _display->setCursor(0, 34);
    _display->print(tmp);
    strcpy(tmp, "192.168.4.1");
  } else if (net != nullptr && net->isWifiConnected()) {
    _display->drawTextEllipsized(0, 14, _display->width(), WiFi.SSID().c_str());
    snprintf(tmp, sizeof(tmp), "%s.local", net->getHostname());
    _display->drawTextEllipsized(0, 24, _display->width(), tmp);
    snprintf(tmp, sizeof(tmp), "%d dBm", WiFi.RSSI());
    _display->setCursor(0, 34);
    _display->print(tmp);
    snprintf(tmp, sizeof(tmp), "%s", WiFi.localIP().toString().c_str());
  } else {
    _display->print("WiFi not connected");
    strcpy(tmp, "no IP");
  }
  // flashing inverse bar with the address
  const int y = 46;
  if (flash_on) {
    _display->fillRect(0, y - 2, _display->width(), 12);
    _display->setColor(UIColor::window_bkg);
  }
  _display->drawTextCentered(_display->width() / 2, y, tmp);
  _display->setColor(UIColor::primary_txt);
}

void UITask::renderPage(int page) {
  char tmp[40];
  NetworkService* net = _umc ? _umc->network() : nullptr;
  switch (page) {
    case 0: {
      header("RADIO", 0, kUmcSettingsPages);
      snprintf(tmp, sizeof(tmp), "%.3f MHz", _node_prefs->freq);
      _display->setCursor(0, 14); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "BW %.1f SF%d CR4/%d", _node_prefs->bw, _node_prefs->sf, _node_prefs->cr);
      _display->setCursor(0, 24); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "TX %d dBm duty %.0f%%", _node_prefs->tx_power_dbm, 100.0f / (1.0f + _node_prefs->airtime_factor));
      _display->setCursor(0, 34); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "RXgain %s AGC %ds", _node_prefs->rx_boosted_gain ? "on" : "off", _node_prefs->agc_reset_interval * 4);
      _display->setCursor(0, 44); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "Noise %d dBm", (int)radio_driver.getNoiseFloor());
      _display->setCursor(0, 54); _display->print(tmp);
      break;
    }
    case 1: {
      header("MESH", 1, kUmcSettingsPages);
      _display->drawTextEllipsized(0, 14, _display->width(), _node_prefs->node_name);
      snprintf(tmp, sizeof(tmp), "Repeat %s  hops %d", _node_prefs->disable_fwd ? "OFF" : "on", _node_prefs->flood_max);
      _display->setCursor(0, 24); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "Advert %dm flood %dh", _node_prefs->advert_interval * 2, _node_prefs->flood_advert_interval);
      _display->setCursor(0, 34); _display->print(tmp);
      static const char* const loops[] = {"off", "minimal", "moderate", "strict"};
      snprintf(tmp, sizeof(tmp), "Loop %s hash %db", loops[_node_prefs->loop_detect & 3], _node_prefs->path_hash_mode + 1);
      _display->setCursor(0, 44); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "TXdly %.1f RXdly %.1f", _node_prefs->tx_delay_factor, _node_prefs->rx_delay_base);
      _display->setCursor(0, 54); _display->print(tmp);
      break;
    }
    case 2: {
      header("WIFI", 2, kUmcSettingsPages);
      if (net == nullptr) break;
      if (net->isWifiConnected()) {
        _display->drawTextEllipsized(0, 14, _display->width(), WiFi.SSID().c_str());
        snprintf(tmp, sizeof(tmp), "IP %s", WiFi.localIP().toString().c_str());
        _display->setCursor(0, 24); _display->print(tmp);
        snprintf(tmp, sizeof(tmp), "%d dBm ch %d", WiFi.RSSI(), WiFi.channel());
        _display->setCursor(0, 34); _display->print(tmp);
      } else {
        _display->setCursor(0, 14);
        _display->print(net->configuredNetworkCount() ? "Connecting..." : "No WiFi configured");
      }
      snprintf(tmp, sizeof(tmp), "AP %s %s", net->getApModeLabel(), net->isApActive() ? "(up)" : "");
      _display->setCursor(0, 44); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "Web %s  Telnet %s", _umc->prefs().http_enabled ? "on" : "off", _umc->prefs().telnet_enabled ? "on" : "off");
      _display->setCursor(0, 54); _display->print(tmp);
      break;
    }
    default: {
      header("STATUS", 3, kUmcSettingsPages);
      unsigned long up = millis() / 1000;
      snprintf(tmp, sizeof(tmp), "Up %lud %02luh %02lum", up / 86400, (up % 86400) / 3600, (up % 3600) / 60);
      _display->setCursor(0, 14); _display->print(tmp);
      uint16_t mv = _board->getBattMilliVolts();
      if (mv > 0) snprintf(tmp, sizeof(tmp), "Battery %.2f V", mv / 1000.0f);
      else snprintf(tmp, sizeof(tmp), "Battery -");
      _display->setCursor(0, 24); _display->print(tmp);
      uint32_t now = rtc_clock.getCurrentTime();
      snprintf(tmp, sizeof(tmp), "Clock %02lu:%02lu UTC", (unsigned long)((now / 3600) % 24), (unsigned long)((now / 60) % 60));
      _display->setCursor(0, 34); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "RX %lu  TX %lu", (unsigned long)umc_traffic.rxTotal(), (unsigned long)umc_traffic.txTotal());
      _display->setCursor(0, 44); _display->print(tmp);
      snprintf(tmp, sizeof(tmp), "UMC %s", UMC_VERSION);
      _display->setCursor(0, 54); _display->print(tmp);
      break;
    }
  }
}

void UITask::renderTraffic() {
  char tmp[40];
  snprintf(tmp, sizeof(tmp), "TRAFFIC rx%d tx%d/m", umc_traffic.countSince(60000, false), umc_traffic.countSince(60000, true));
  _display->setColor(UIColor::primary_txt);
  _display->setTextSize(1);
  _display->setCursor(0, 0);
  _display->print(tmp);
  _display->fillRect(0, 10, _display->width(), 1);
  if (umc_traffic.count() == 0) {
    _display->drawTextCentered(_display->width() / 2, 30, "waiting for packets");
    return;
  }
  for (int i = 0; i < 5 && i < umc_traffic.count(); i++) {
    const auto* e = umc_traffic.get(i);
    UmcTraffic::formatShort(*e, tmp, sizeof(tmp));
    _display->drawTextEllipsized(0, 14 + i * 10, _display->width(), tmp);
  }
}

void UITask::renderUmcScreen() {
  const auto& p = _umc->prefs();
  const unsigned long now = millis();

  if (now < _manual_until) {   // user is browsing with the button
    if (_manual_page == 0) renderIpPage(true);
    else if (_manual_page <= kUmcSettingsPages) renderPage(_manual_page - 1);
    else renderTraffic();
    return;
  }
  if (p.display_mode == 1) {   // status only
    renderIpPage(false);
    return;
  }

  // cycle: flashing IP -> settings pages -> live traffic -> repeat
  const unsigned long ip_ms = p.display_ip_s * 1000UL;
  const unsigned long pages_ms = static_cast<unsigned long>(p.display_page_s) * 1000UL * kUmcSettingsPages;
  const unsigned long traffic_ms = p.display_traffic_s * 1000UL;
  const unsigned long total = ip_ms + pages_ms + traffic_ms;
  if (_cycle_start == 0 || total == 0 || now - _cycle_start >= total) _cycle_start = now;
  unsigned long t = now - _cycle_start;

  if (t < ip_ms) {
    renderIpPage((t / 500) % 2 == 0);
  } else if (t < ip_ms + pages_ms) {
    renderPage((t - ip_ms) / (p.display_page_s * 1000UL));
  } else {
    renderTraffic();
  }
}
#endif

void UITask::renderCurrScreen() {
  char tmp[80];
  if (millis() < _started_at + BOOT_SCREEN_MILLIS) { // boot screen
    // meshcore logo
    _display->setColor(UIColor::corp_blue);
    int logoWidth = 128;
    _display->drawXbm((_display->width() - logoWidth) / 2, 3, meshcore_logo, logoWidth, 13);

    // meshcore website
#ifdef UMC_BUILD
    const char* website = "Ultimate MeshCore";
#else
    const char* website = "https://meshcore.io";
#endif
    _display->setColor(UIColor::primary_txt);
    _display->setTextSize(1);
    _display->drawTextCentered(_display->width() / 2, 22, website);

    // version info
    _display->setTextSize(1);
    _display->drawTextCentered(_display->width() / 2, 35, _version_info);

    // node type
    const char* node_type = "< Repeater >";
    _display->drawTextCentered(_display->width() / 2, 48, node_type);
  } else if (_powering_off_at > 0) {
    // meshcore logo
    _display->setColor(UIColor::corp_blue);
    int logoWidth = 128;
    _display->drawXbm((_display->width() - logoWidth) / 2, 3, meshcore_logo, logoWidth, 13);

    // meshcore website
    const char* website = "https://meshcore.io";
    _display->setColor(UIColor::primary_txt);
    _display->setTextSize(1);
    _display->drawTextCentered(_display->width()/ 2, 22, website);

    // Powering off
    const char* poweroff_string = "Turning OFF";
    uint16_t poffWidth = _display->getTextWidth(poweroff_string);
    _display->setCursor((_display->width() - poffWidth) / 2, 48);
    _display->drawTextCentered(_display->width()/2, 48, poweroff_string);
#ifdef UMC_BUILD
  } else if (_umc != nullptr) {
    renderUmcScreen();
#endif
  } else {
    _display->setCursor(0, 0);
    _display->setTextSize(1);
    _display->setColor(UIColor::primary_txt);
    _display->print(_node_prefs->node_name);

    // freq / sf
    _display->setCursor(0, 20);
    sprintf(tmp, "FREQ: %06.3f SF%d", _node_prefs->freq, _node_prefs->sf);
    _display->print(tmp);

    // bw / cr
    _display->setCursor(0, 30);
    sprintf(tmp, "BW: %03.2f CR: %d", _node_prefs->bw, _node_prefs->cr);
    _display->print(tmp);

    // WiFi IP
    _display->setCursor(0, 40);
    if (WiFi.status() == WL_CONNECTED) {
      IPAddress ip = WiFi.localIP();
      snprintf(tmp, sizeof(tmp), "IP: %u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
    } else {
      snprintf(tmp, sizeof(tmp), "IP: -");
    }
    _display->print(tmp);
  }
}

void UITask::loop() {
#if defined(PIN_USER_BTN) && defined(DISPLAY_CLASS)
  int ev = user_btn.check();
  if (ev == BUTTON_EVENT_CLICK) {
    if (_display->isOn()) {
#ifdef UMC_BUILD
      // step through IP -> radio -> mesh -> wifi -> status -> traffic, pausing the auto cycle
      _manual_page = millis() < _manual_until ? (_manual_page + 1) % 6 : 0;
      _manual_until = millis() + kManualHoldMs;
      _next_refresh = 0;
#endif
    } else {
      _display->turnOn();
    }
    _auto_off = millis() + AUTO_OFF_MILLIS;   // extend auto-off timer
#ifdef UMC_BUILD
    if (_umc != nullptr && _umc->prefs().display_timeout_s > 0) {
      _auto_off = millis() + _umc->prefs().display_timeout_s * 1000UL;
    }
#endif
  } else if (ev == BUTTON_EVENT_LONG_PRESS) {
      _display->turnOn();
      Serial.println("Powering Off");
      _powering_off_at = millis() + POWEROFF_DELAY; 
  }
#endif

  if (_display->isOn()) {
    if (millis() >= _next_refresh) {
      _display->startFrame();
      renderCurrScreen();
      _display->endFrame();

#ifdef UMC_BUILD
      _next_refresh = millis() + (_umc != nullptr ? 250 : 1000);   // fast enough for the IP flash
#else
      _next_refresh = millis() + 1000;   // refresh every second
#endif
    }
#ifdef UMC_BUILD
    bool blank = false;
    if (_umc != nullptr) {
      const auto& p = _umc->prefs();
      // mode "off" blanks after the default timeout; otherwise only when a timeout is configured
      if (p.display_mode == 2) blank = millis() > _auto_off;
      else if (p.display_timeout_s > 0) blank = millis() > _auto_off;
    } else {
      blank = millis() > _auto_off;
    }
    if (blank && millis() > _started_at + BOOT_SCREEN_MILLIS) {
      _display->turnOff();
    }
#else
    if (millis() > _auto_off) {
      _display->turnOff();
    }
#endif
  }

  if (_powering_off_at > 0) { // power off timer armed
#ifdef LED_PIN
    digitalWrite(LED_PIN, LED_STATE_ON); // switch on the led until poweroff
#endif
    if (millis() > _powering_off_at) {
      _board->powerOff();  // should not return
    }
  }
}
