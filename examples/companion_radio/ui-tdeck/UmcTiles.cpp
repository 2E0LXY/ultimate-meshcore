#include "UmcTiles.h"

#if defined(LILYGO_TDECK)

#include <FS.h>
#include <SD.h>
#include <SPI.h>
#include <helpers/ui/ST7789LCDDisplay.h>

#ifndef TDECK_SD_CS
  #define TDECK_SD_CS 39
#endif

extern DISPLAY_CLASS display;   // the T-Deck shares one SPI bus for display, radio and card

bool UmcTiles::begin(int cache_tiles) {
  if (_ok) return true;
  // The card sits on the same SPI bus as the display; reuse that bus object.
  if (!SD.begin(TDECK_SD_CS, display.spiBus(), 4000000)) {   // 20 MHz can wedge the shared SPI bus
    strncpy(_status, "no SD card", sizeof(_status) - 1);
    return false;
  }
  if (!SD.exists("/maps")) {
    strncpy(_status, "card has no /maps folder", sizeof(_status) - 1);
    return false;
  }
  _num_slots = cache_tiles;
  _slots = new Slot[_num_slots];
  for (int i = 0; i < _num_slots; i++) {
    _slots[i].px = static_cast<uint16_t*>(heap_caps_malloc(UMC_TILE_BYTES, MALLOC_CAP_SPIRAM));
    if (_slots[i].px == nullptr) {  // no PSRAM: keep whatever slots we managed to get
      _num_slots = i;
      break;
    }
  }
  if (_num_slots == 0) {
    strncpy(_status, "not enough memory for tiles", sizeof(_status) - 1);
    return false;
  }
  scanZooms();
  if (_max_zoom < 0) {
    // Say what is actually there: the usual mistake is image files, or tiles one folder
    // deeper, instead of /maps/<zoom>/<x>/<y>.bin
    int files = 0, dirs = 0;
    File dir = SD.open("/maps");
    for (File f = dir.openNextFile(); f && files + dirs < 200; f = dir.openNextFile()) {
      if (f.isDirectory()) dirs++; else files++;
      f.close();
    }
    dir.close();
    snprintf(_status, sizeof(_status), "/maps: %d files, %d folders - need /maps/<zoom>/<x>/<y>.bin", files, dirs);
    return false;
  }
  snprintf(_status, sizeof(_status), "SD maps, zoom %d-%d", _min_zoom, _max_zoom);
  _ok = true;
  return true;
}

void UmcTiles::scanZooms() {
  _min_zoom = 99;
  _max_zoom = -1;
  File dir = SD.open("/maps");
  if (!dir) return;
  for (File f = dir.openNextFile(); f; f = dir.openNextFile()) {
    if (!f.isDirectory()) { f.close(); continue; }
    const char* name = strrchr(f.name(), '/');
    name = name ? name + 1 : f.name();
    char* end = nullptr;
    long z = strtol(name, &end, 10);
    if (end != name && z >= 0 && z <= 20) {
      if (z < _min_zoom) _min_zoom = (int)z;
      if (z > _max_zoom) _max_zoom = (int)z;
    }
    f.close();
  }
  dir.close();
  if (_max_zoom < 0) _min_zoom = 0;
}

// Called from the web server's task: hand the tile over and wait for the UI task.
bool UmcTiles::queueTile(int z, int x, int y, const uint8_t* data, size_t len) {
  if (data == nullptr || len != UMC_TILE_BYTES) return false;
  if (z < 0 || z > 20) return false;
  const int span = 1 << z;
  if (x < 0 || y < 0 || x >= span || y >= span) return false;
  if (_pending.state != 0) return false;            // one upload at a time

  _pending.z = z;
  _pending.x = x;
  _pending.y = y;
  _pending.data = data;
  _pending.len = len;
  _pending.state = 1;

  for (int waited = 0; waited < 8000 && _pending.state == 1; waited += 2) {
    vTaskDelay(pdMS_TO_TICKS(2));                   // the UI loop picks it up within a tick
  }
  const bool ok = _pending.state == 2;
  _pending.data = nullptr;
  _pending.state = 0;
  return ok;
}

// Called from the UI loop, which is the only task allowed near the card.
void UmcTiles::servicePending() {
  if (_pending.state != 1) return;
  const bool ok = writeTileNow(_pending.z, _pending.x, _pending.y, _pending.data, _pending.len);
  _pending.state = ok ? 2 : 3;
}

bool UmcTiles::writeTileNow(int z, int x, int y, const uint8_t* data, size_t len) {
  if (SD.cardType() == CARD_NONE) {                 // a card put in after start-up
    if (!SD.begin(TDECK_SD_CS, display.spiBus(), 4000000)) {
      strncpy(_status, "no SD card", sizeof(_status) - 1);
      return false;
    }
  }
  char path[48];
  // each level has to be made on its own
  if (!SD.exists("/maps") && !SD.mkdir("/maps")) return false;
  snprintf(path, sizeof(path), "/maps/%d", z);
  if (!SD.exists(path) && !SD.mkdir(path)) return false;
  snprintf(path, sizeof(path), "/maps/%d/%d", z, x);
  if (!SD.exists(path) && !SD.mkdir(path)) return false;

  snprintf(path, sizeof(path), "/maps/%d/%d/%d.bin", z, x, y);
  File f = SD.open(path, FILE_WRITE);
  if (!f) return false;
  const size_t put = f.write(data, len);
  f.close();
  if (put != len) {
    SD.remove(path);                                // a half-written tile is worse than none
    return false;
  }

  // a new zoom folder may have appeared, and the first tile makes the map usable
  for (int i = 0; i < _num_slots; i++) {
    if (_slots[i].z == z && _slots[i].x == x && _slots[i].y == y) _slots[i].z = -1;   // drop stale cache
  }
  scanZooms();
  if (_max_zoom >= 0) {
    if (_slots == nullptr) {                        // begin() gave up earlier: set up now
      _num_slots = 6;
      _slots = new Slot[_num_slots];
      for (int i = 0; i < _num_slots; i++) {
        _slots[i].px = static_cast<uint16_t*>(heap_caps_malloc(UMC_TILE_BYTES, MALLOC_CAP_SPIRAM));
        if (_slots[i].px == nullptr) { _num_slots = i; break; }
      }
    }
    if (_num_slots > 0) {
      snprintf(_status, sizeof(_status), "SD maps, zoom %d-%d", _min_zoom, _max_zoom);
      _ok = true;
    }
  }
  return true;
}

// Used by the self-test to clear up after itself.
bool UmcTiles::removeTile(int z, int x, int y) {
  char path[48];
  snprintf(path, sizeof(path), "/maps/%d/%d/%d.bin", z, x, y);
  const bool gone = SD.remove(path);
  snprintf(path, sizeof(path), "/maps/%d/%d", z, x);
  SD.rmdir(path);
  snprintf(path, sizeof(path), "/maps/%d", z);
  SD.rmdir(path);
  scanZooms();
  return gone;
}

const uint16_t* UmcTiles::tile(int z, int x, int y) {
  if (!_ok || z < 0) return nullptr;
  const int span = 1 << z;
  if (x < 0 || y < 0 || x >= span || y >= span) return nullptr;

  for (int i = 0; i < _num_slots; i++) {
    if (_slots[i].z == z && _slots[i].x == x && _slots[i].y == y) {
      _slots[i].used = millis();
      return _slots[i].px;
    }
  }
  char path[48];
  snprintf(path, sizeof(path), "/maps/%d/%d/%d.bin", z, x, y);
  File f = SD.open(path, FILE_READ);
  if (!f) return nullptr;
  if (f.size() != UMC_TILE_BYTES) {
    f.close();
    return nullptr;
  }
  Slot* victim = &_slots[0];
  for (int i = 1; i < _num_slots; i++) {
    if (_slots[i].z < 0) { victim = &_slots[i]; break; }
    if (_slots[i].used < victim->used) victim = &_slots[i];
  }
  const size_t got = f.read(reinterpret_cast<uint8_t*>(victim->px), UMC_TILE_BYTES);
  f.close();
  if (got != UMC_TILE_BYTES) {
    victim->z = -1;
    return nullptr;
  }
  victim->z = z; victim->x = x; victim->y = y; victim->used = millis();
  return victim->px;
}

#else  // not a T-Deck build

bool UmcTiles::begin(int) { return false; }
const uint16_t* UmcTiles::tile(int, int, int) { return nullptr; }
void UmcTiles::scanZooms() {}
bool UmcTiles::queueTile(int, int, int, const uint8_t*, size_t) { return false; }
void UmcTiles::servicePending() {}
bool UmcTiles::writeTileNow(int, int, int, const uint8_t*, size_t) { return false; }
bool UmcTiles::removeTile(int, int, int) { return false; }

#endif
