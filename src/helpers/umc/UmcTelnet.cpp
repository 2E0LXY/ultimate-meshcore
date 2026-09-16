#include "UmcTelnet.h"
#include "UmcLog.h"

#if defined(ESP_PLATFORM)
  #include <WiFi.h>
#endif

#include "UmcService.h"
#include "UmcVersion.h"

namespace {
constexpr unsigned long kIdleTimeoutMs = 10UL * 60UL * 1000UL;
constexpr unsigned long kLockoutMs = 60UL * 1000UL;
}

UmcTelnet::UmcTelnet(UmcService& umc)
    : _umc(umc), _server(nullptr), _client(nullptr), _line{0}, _len(0), _authed(false), _failures(0), _last_activity(0),
      _locked_until(0) {}

void UmcTelnet::start() {
#if defined(ESP_PLATFORM)
  if (_server != nullptr) return;
  _server = new WiFiServer(_umc.prefs().telnet_port);
  _server->begin();
  _server->setNoDelay(true);
  UMC_LOGF("[UMC] telnet CLI on port %u\n", _umc.prefs().telnet_port);
#endif
}

void UmcTelnet::stop() {
#if defined(ESP_PLATFORM)
  if (_client != nullptr) {
    _client->stop();
    delete _client;
    _client = nullptr;
  }
  if (_server != nullptr) {
    _server->end();
    delete _server;
    _server = nullptr;
  }
#endif
}

void UmcTelnet::send(const char* text) {
#if defined(ESP_PLATFORM)
  if (_client != nullptr && _client->connected()) {
    _client->print(text);
  }
#endif
}

void UmcTelnet::loop(bool enabled) {
#if defined(ESP_PLATFORM)
  if (!enabled) {
    stop();
    return;
  }
  start();

  if (_server->hasClient()) {
    WiFiClient incoming = _server->available();
    if (_client != nullptr && _client->connected()) {
      incoming.print("Busy - one session at a time\r\n");
      incoming.stop();
    } else {
      if (_client != nullptr) delete _client;
      _client = new WiFiClient(incoming);
      _len = 0;
      _authed = false;
      _last_activity = millis();
      char banner[128];
      snprintf(banner, sizeof(banner), "\r\n%s %s - %s\r\nPassword: ", UMC_NAME, UMC_VERSION,
               _umc.host() ? _umc.host()->umcNodeName() : "");
      send(banner);
    }
  }

  if (_client == nullptr) return;
  if (!_client->connected()) {
    delete _client;
    _client = nullptr;
    return;
  }
  if (millis() - _last_activity > kIdleTimeoutMs) {
    send("\r\nIdle timeout\r\n");
    _client->stop();
    return;
  }

  while (_client->available()) {
    int c = _client->read();
    _last_activity = millis();
    if (c == 0xFF) {  // swallow telnet IAC negotiation (3 bytes)
      _client->read();
      _client->read();
      continue;
    }
    if (c == '\r' || c == '\n') {
      if (_len == 0) continue;
      _line[_len] = 0;
      handleLine(_line);
      _len = 0;
      if (_client == nullptr || !_client->connected()) return;
    } else if (c == 8 || c == 127) {
      if (_len > 0) _len--;
    } else if (_len < sizeof(_line) - 1 && c >= 32) {
      _line[_len++] = static_cast<char>(c);
    }
  }
#else
  (void)enabled;
#endif
}

void UmcTelnet::handleLine(char* line) {
#if defined(ESP_PLATFORM)
  if (!_authed) {
    if (millis() < _locked_until) {
      send("Locked - try again later\r\n");
      _client->stop();
      return;
    }
    if (_umc.checkAdminPassword(line)) {
      _authed = true;
      _failures = 0;
      send("OK\r\n> ");
    } else {
      _failures++;
      if (_failures >= 5) {
        _locked_until = millis() + kLockoutMs;
        _failures = 0;
      }
      send("Bad password\r\n");
      _client->stop();
    }
    return;
  }
  if (strcmp(line, "exit") == 0 || strcmp(line, "quit") == 0) {
    send("Bye\r\n");
    _client->stop();
    return;
  }
  char reply[UmcService::kMaxReplyLen];
  reply[0] = 0;
  if (strcmp(line, "reboot") == 0) {
    strcpy(reply, "OK - rebooting");
    _umc.scheduleReboot(1000);
  } else if (_umc.host() != nullptr) {
    _umc.host()->umcCommand(line, reply, sizeof(reply));
  }
  if (reply[0]) {
    send("  -> ");
    send(reply);
    send("\r\n");
  }
  send("> ");
#else
  (void)line;
#endif
}
