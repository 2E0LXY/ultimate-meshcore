#include "UmcMapSink.h"

#include <Arduino.h>

static UmcMapTileSink s_sink = nullptr;
static UmcMapStatusFn s_status = nullptr;

void umcSetMapTileSink(UmcMapTileSink sink) { s_sink = sink; }

UmcMapTileSink umcMapTileSink() { return s_sink; }

void umcSetMapStatusFn(UmcMapStatusFn fn) { s_status = fn; }

const char* umcMapStatus() { return s_status != nullptr ? s_status() : "this board has no tile storage"; }

static UmcMapRemoveFn s_remove = nullptr;

void umcSetMapRemoveFn(UmcMapRemoveFn fn) { s_remove = fn; }

bool umcMapRemove(int zoom, int x, int y) { return s_remove != nullptr && s_remove(zoom, x, y); }

static uint32_t s_upload_until = 0;      // millis() deadline, 0 = closed

void umcOpenMapUpload(uint32_t for_ms) {
  s_upload_until = millis() + for_ms;
  if (s_upload_until == 0) s_upload_until = 1;   // millis() wrapped exactly onto "closed"
}

void umcCloseMapUpload() { s_upload_until = 0; }

bool umcMapUploadOpen() { return s_upload_until != 0 && (int32_t)(s_upload_until - millis()) > 0; }

uint32_t umcMapUploadLeftMs() {
  if (!umcMapUploadOpen()) return 0;
  return s_upload_until - millis();
}
