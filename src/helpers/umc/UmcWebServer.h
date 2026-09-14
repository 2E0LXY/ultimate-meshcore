#pragma once

#include <Arduino.h>

#if defined(ESP_PLATFORM)
  #include <esp_http_server.h>
#endif

class UmcService;

// Plain-HTTP web UI + JSON API. Works on the LAN (STA) and on the setup/rescue AP.
//
//   GET  /                 single-page app (gzip, embedded)
//   GET  /api/info         public device summary (name, role, setup state, features)
//   POST /api/login        body = admin password  -> {"token": "..."}
//   POST /api/logout
//   POST /api/cli          body = newline-separated CLI commands -> ["reply", ...]
//   GET  /api/scan         WiFi scan results (starts a scan when none is cached)
//   POST /api/ota          raw .bin body (app image) -> flashes inactive slot, reboots
//   *    captive-portal probes redirect to the app while the AP is active
//
// Auth: X-Auth-Token header. While the device is in setup mode, requests arriving on the
// setup AP interface (WPA2, PIN-protected) are allowed without a token.
class UmcWebServer {
public:
  explicit UmcWebServer(UmcService& umc);
  void loop(bool enabled);
  bool isRunning() const;

private:
#if defined(ESP_PLATFORM)
  static constexpr int kMaxSessions = 4;
  struct Session {
    char token[33];
    unsigned long last_ms;
  };

  bool start();
  void stop();

  static esp_err_t handleIndex(httpd_req_t* req);
  static esp_err_t handleInfo(httpd_req_t* req);
  static esp_err_t handleLogin(httpd_req_t* req);
  static esp_err_t handleLogout(httpd_req_t* req);
  static esp_err_t handleCli(httpd_req_t* req);
  static esp_err_t handleScan(httpd_req_t* req);
  static esp_err_t handleRoutes(httpd_req_t* req);
  static esp_err_t handleTraffic(httpd_req_t* req);
  static esp_err_t handleOta(httpd_req_t* req);
  static esp_err_t handleCaptive(httpd_req_t* req);
  static esp_err_t handleNotFound(httpd_req_t* req, httpd_err_code_t err);

  bool isAuthorized(httpd_req_t* req);
  bool isSetupApRequest(httpd_req_t* req) const;
  const char* newSession();
  void dropSession(const char* token);
  static void setCommonHeaders(httpd_req_t* req);

  httpd_handle_t _server;
  Session _sessions[kMaxSessions];
  uint8_t _login_failures;
  unsigned long _login_locked_until;
  bool _ota_active;
#endif
  UmcService& _umc;
};
