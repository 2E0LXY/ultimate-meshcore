#pragma once

#include <Arduino.h>

// Diagnostic logging for the UMC network services. Companion firmware shares the USB
// serial port with the MeshCore app protocol, so it builds with UMC_QUIET_SERIAL to keep
// text out of the binary frame stream.
#ifdef UMC_QUIET_SERIAL
  #define UMC_LOGF(...) ((void)0)
  #define UMC_LOGLN(...) ((void)0)
#else
  #define UMC_LOGF(...) Serial.printf(__VA_ARGS__)
  #define UMC_LOGLN(...) Serial.println(__VA_ARGS__)
#endif
