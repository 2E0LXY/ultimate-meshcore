#pragma once

#include <Arduino.h>

class UmcService;

// Internet firmware updates from the project's published builds (GitHub Pages).
//
//   <update.url>/builds.json                       -> latest version + commit + env list
//   <update.url>/firmware/<UMC_ENV>/firmware.bin   -> app image for this exact board/role
//
// HTTPS is verified against the ESP-IDF certificate bundle. Checks and downloads run in
// their own FreeRTOS task so the mesh keeps running; the device reboots into the new
// image (the old one stays in the other OTA slot).
class UmcUpdater {
public:
  enum class State : uint8_t { Idle, Checking, UpToDate, Available, Downloading, Done, Error };

  explicit UmcUpdater(UmcService& umc);
  void begin();
  void loop(bool network_up);

  bool startCheck();
  bool startInstall();   // installs whatever the last check found (checks first if needed)

  void formatStatus(char* reply, size_t reply_size) const;
  State state() const { return _state; }
  const char* latestVersion() const { return _latest_version; }

  const char* url() const { return _url; }
  bool setUrl(const char* url);
  uint8_t autoMode() const { return _auto_mode; }     // 0 off, 1 check, 2 install
  bool setAutoMode(const char* mode);
  static const char* autoModeLabel(uint8_t mode);
  uint16_t intervalHours() const { return _interval_h; }
  bool setIntervalHours(uint16_t h);

  static const char* buildEnv();
  static const char* buildCommit();

private:
  static void checkTask(void* arg);
  static void installTask(void* arg);
  bool doCheck();
  bool doInstall();
  void setError(const char* msg);
  void save();

  UmcService& _umc;
  volatile State _state;
  volatile bool _install_after_check;
  volatile int _progress;          // percent, -1 unknown
  char _error[96];
  char _latest_version[24];
  char _latest_commit[48];
  char _url[128];
  uint8_t _auto_mode;
  uint16_t _interval_h;
  unsigned long _next_auto_ms;
  bool _task_running;
  volatile bool _tls_release = false;  // task finished: give the host its memory back (loop task)
  bool _tls_held = false;
  void tlsBegin();
};
