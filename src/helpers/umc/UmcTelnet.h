#pragma once

#include <Arduino.h>

class UmcService;
#if defined(ESP32) && defined(UMC_WIFI_CSI)
  #include <WiFi.h>   // Arduino-ESP32 3.x makes these typedefs of NetworkServer/NetworkClient, which cannot be forward-declared as classes
#else
class WiFiServer;
class WiFiClient;
#endif

// Password-protected line CLI on TCP (default port 23). Runs on the loop task.
class UmcTelnet {
public:
  explicit UmcTelnet(UmcService& umc);
  void loop(bool enabled);

private:
  void start();
  void stop();
  void handleLine(char* line);
  void send(const char* text);

  UmcService& _umc;
  WiFiServer* _server;
  WiFiClient* _client;
  char _line[192];
  size_t _len;
  bool _authed;
  uint8_t _failures;
  unsigned long _last_activity;
  unsigned long _locked_until;
};
