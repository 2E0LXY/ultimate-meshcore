#pragma once

#include <stddef.h>
#include <stdint.h>

// Where an uploaded map tile goes.
//
// The web server accepts tiles over WiFi, but only the board's own UI code knows whether
// there is a card and how to reach it - on the T-Deck the card shares its SPI bus with the
// display and the radio, so the write has to happen on the UI task. A board that can store
// tiles registers a sink here during start-up; boards that cannot leave it unset and the
// upload endpoint answers "not supported".
//
// One tile is a 256x256 raw RGB565 image, the format the device draws straight from.
#define UMC_MAP_TILE_BYTES (256 * 256 * 2)

// The sink is called from the web server's task and must block until the tile is stored.
typedef bool (*UmcMapTileSink)(int zoom, int x, int y, const uint8_t* data, size_t len);

void umcSetMapTileSink(UmcMapTileSink sink);
UmcMapTileSink umcMapTileSink();

// A line describing the tile store, for the upload endpoint to report ("no SD card",
// "SD maps, zoom 9-14"). Set by the same board code that registers the sink.
typedef const char* (*UmcMapStatusFn)();

void umcSetMapStatusFn(UmcMapStatusFn fn);
const char* umcMapStatus();

// Removes one stored tile, for the console's self-test.
typedef bool (*UmcMapRemoveFn)(int zoom, int x, int y);

void umcSetMapRemoveFn(UmcMapRemoveFn fn);
bool umcMapRemove(int zoom, int x, int y);
