#include "UmcMapSink.h"

static UmcMapTileSink s_sink = nullptr;
static UmcMapStatusFn s_status = nullptr;

void umcSetMapTileSink(UmcMapTileSink sink) { s_sink = sink; }

UmcMapTileSink umcMapTileSink() { return s_sink; }

void umcSetMapStatusFn(UmcMapStatusFn fn) { s_status = fn; }

const char* umcMapStatus() { return s_status != nullptr ? s_status() : "this board has no tile storage"; }

static UmcMapRemoveFn s_remove = nullptr;

void umcSetMapRemoveFn(UmcMapRemoveFn fn) { s_remove = fn; }

bool umcMapRemove(int zoom, int x, int y) { return s_remove != nullptr && s_remove(zoom, x, y); }
