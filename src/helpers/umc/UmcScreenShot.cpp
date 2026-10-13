#include "UmcScreenShot.h"

#include <Arduino.h>

static UmcShotFn s_shot = nullptr;

void umcSetScreenShot(UmcShotFn fn) { s_shot = fn; }

UmcShotFn umcScreenShot() { return s_shot; }

static uint32_t s_share_until = 0;   // millis() deadline, 0 = closed

void umcOpenScreenShare(uint32_t for_ms) {
  s_share_until = millis() + for_ms;
  if (s_share_until == 0) s_share_until = 1;
}

void umcCloseScreenShare() { s_share_until = 0; }

bool umcScreenShareOpen() { return s_share_until != 0 && (int32_t)(s_share_until - millis()) > 0; }
