#pragma once

#include <Arduino.h>
#include <helpers/BaseSerialInterface.h>

#if defined(ESP_PLATFORM)
  #include <freertos/FreeRTOS.h>
  #include <freertos/semphr.h>
#endif

// Browser link for companion firmware: the web UI speaks the MeshCore companion protocol
// (the same frames the phone apps use) through /api/app, so the browser messenger gets
// every app feature without duplicating any of it in firmware.
//
//  * frames the browser posts are queued here and taken by the companion loop with
//    takeFrame(); the loop answers with this interface as the reply target (setDirect)
//  * as a member of the MultiSerialInterface it also receives every push frame (adverts,
//    ACKs, login results, status/telemetry responses ...)
//  * mirror() keeps a copy of each received message, so the browser sees conversations
//    even when a phone app drains the offline queue first
//
// Frames sit in a ring with increasing sequence numbers; the browser polls with the last
// sequence it has seen. HTTP handlers run on the httpd task, so everything is mutex-guarded.
class UmcWebApp : public BaseSerialInterface {
public:
#ifndef UMC_WEBAPP_RING
  #define UMC_WEBAPP_RING 48
#endif
  static constexpr int kRing = UMC_WEBAPP_RING;
  static constexpr int kInbox = 8;
  static constexpr int kMaxPerPoll = 12;

  UmcWebApp();
  void begin();

  // ---- loop task ----
  size_t takeFrame(uint8_t dest[]);
  void setDirect(bool direct) { _direct = direct; }
  void mirror(const uint8_t* frame, size_t len);

  // ---- BaseSerialInterface (loop task) ----
  void enable() override { _enabled = true; }
  void disable() override { _enabled = false; }
  bool isEnabled() const override { return _enabled; }
  bool isConnected() const override { return false; }  // never suppresses display notifications
  bool isWriteBusy() const override { return false; }
  size_t writeFrame(const uint8_t src[], size_t len) override;
  size_t checkRecvFrame(uint8_t dest[]) override { (void)dest; return 0; }  // see takeFrame()

  // ---- httpd task ----
  // hex: one frame as hex digits. Returns false when the inbox is full or the frame is bad.
  bool postHex(const char* hex);
  // JSON {"boot":..,"seq":..,"more":bool,"frames":["hex",..]} of frames after `since`.
  size_t formatSince(uint32_t since, char* out, size_t out_size);
  bool polledRecently() const { return _last_poll_ms != 0 && millis() - _last_poll_ms < 20000; }

private:
  struct Entry {
    uint32_t seq;
    uint8_t len;
    uint8_t buf[MAX_FRAME_SIZE];
  };
  void store(const uint8_t* frame, size_t len);
  void lock() const;
  void unlock() const;

  Entry* _ring;    // allocated in begin(): only companion firmware uses the browser link
  int _head;       // next write slot
  int _count;
  uint32_t _seq;
  uint32_t _boot;
  Entry* _inbox;
  int _in_head, _in_count;
  bool _enabled;
  volatile bool _direct;
  unsigned long _last_poll_ms;
#if defined(ESP_PLATFORM)
  SemaphoreHandle_t _lock;
#endif
};

extern UmcWebApp umc_webapp;
