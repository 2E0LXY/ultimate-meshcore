#pragma once

#include <Arduino.h>

class UmcService;
class WiFiServer;
class WiFiClient;

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
