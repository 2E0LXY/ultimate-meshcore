#pragma once

#include <Arduino.h>

#include "UmcHost.h"
#include "UmcPrefs.h"

#if defined(ESP_PLATFORM)
  #include <freertos/FreeRTOS.h>
  #include <freertos/semphr.h>
#endif

class NetworkService;
class UmcWebServer;
class UmcTelnet;

// Ultimate MeshCore network-services orchestrator. One instance per firmware.
//
//  * owns UMC prefs (setup state, PIN, service toggles)
//  * runs the HTTP web UI / REST API, telnet CLI
//  * marshals CLI requests from other FreeRTOS tasks onto the Arduino loop task
//  * implements the UMC-specific CLI commands (wifi slots, net.*, ap.*, setup ...)
class UmcService {
public:
  static constexpr size_t kMaxCommandLen = 192;
  static constexpr size_t kMaxReplyLen = 256;

  UmcService();

  void begin(UmcHost* host, NetworkService* network);
  void loop();

  // UMC CLI commands. Returns true when the command was recognised (reply filled).
  bool handleCommand(const char* command, char* reply, size_t reply_size);

  // Thread-safe: run newline-separated CLI commands on the loop task and write a JSON
  // array of reply strings into out. Returns false on timeout / overload.
  bool runBatch(const char* commands, char* out, size_t out_size, uint32_t timeout_ms = 15000);

  bool checkAdminPassword(const char* password) const;
  bool isDefaultAdminPassword() const;
  bool isSetupMode() const { return !_prefs.setup_done; }
  const char* getPin() const { return _prefs.pin; }
  const UmcPrefs& prefs() const { return _prefs; }
  UmcHost* host() const { return _host; }
  NetworkService* network() const { return _network; }

  void scheduleReboot(uint32_t delay_ms);
  bool isRebootPending() const { return _reboot_at != 0; }
  void notifyOtaStarting();

  // Public, unauthenticated device summary for the login / setup screens.
  void formatInfoJson(char* out, size_t out_size) const;
  static size_t appendJsonEscaped(char* out, size_t out_size, size_t pos, const char* text);

private:
  void processMailbox();
  bool factoryReset();
  void applySetupState();

  UmcHost* _host;
  NetworkService* _network;
  UmcPrefs _prefs;
  UmcWebServer* _web;
  UmcTelnet* _telnet;
  unsigned long _reboot_at;

#if defined(ESP_PLATFORM)
  SemaphoreHandle_t _mb_lock;
  SemaphoreHandle_t _mb_done;
#endif
  const char* volatile _mb_commands;
  char* volatile _mb_out;
  volatile size_t _mb_out_size;
  volatile bool _mb_pending;
  volatile bool _mb_busy;
  volatile bool _ota_prepare;
};
