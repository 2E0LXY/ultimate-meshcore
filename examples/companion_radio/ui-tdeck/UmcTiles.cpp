#include "UmcTiles.h"

#if defined(LILYGO_TDECK)

#include <FS.h>
#include <SD.h>
#include <SPI.h>
#include <helpers/TxtDataHelpers.h>
#include <helpers/ui/ST7789LCDDisplay.h>

#ifndef TDECK_SD_CS
  #define TDECK_SD_CS 39
#endif

extern DISPLAY_CLASS display;   // the T-Deck shares one SPI bus for display, radio and card

bool UmcTiles::begin(int cache_tiles) {
  if (_ok) return true;
  // The Map tab calls this again every few seconds while there are no tiles, so it must be
  // cheap to repeat: mount once, and look for tiles before allocating anything.
  // The card sits on the same SPI bus as the display; reuse that bus object.
  if (SD.cardType() == CARD_NONE &&
      !SD.begin(TDECK_SD_CS, display.spiBus(), 4000000)) {   // 20 MHz can wedge the shared SPI bus
    strncpy(_status, "no SD card", sizeof(_status) - 1);
    return false;
  }
  if (!SD.exists("/maps")) {
    strncpy(_status, "card has no /maps folder", sizeof(_status) - 1);
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
    if (files == 0 && dirs == 0) strncpy(_status, "no tiles on the card", sizeof(_status) - 1);
    else snprintf(_status, sizeof(_status), "no tiles - /maps has %d files, %d folders", files, dirs);
    return false;
  }
  // The cache is 128 KB a slot, so it is only made once there is something to put in it,
  // and only once: this used to allocate again on every retry and leak the lot.
  if (_slots == nullptr) {
    _num_slots = cache_tiles;
    _slots = new Slot[_num_slots];
    for (int i = 0; i < _num_slots; i++) {
      _slots[i].px = static_cast<uint16_t*>(heap_caps_malloc(UMC_TILE_BYTES, MALLOC_CAP_SPIRAM));
      if (_slots[i].px == nullptr) {  // no PSRAM: keep whatever slots we managed to get
        _num_slots = i;
        break;
      }
    }
  }
  if (_num_slots == 0) {
    strncpy(_status, "not enough memory for tiles", sizeof(_status) - 1);
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
  if (__atomic_load_n(&_pending.state, __ATOMIC_ACQUIRE) != P_IDLE) return false;   // one at a time

  _pending.z = z;
  _pending.x = x;
  _pending.y = y;
  _pending.data = data;
  _pending.len = len;
  __atomic_store_n(&_pending.state, P_QUEUED, __ATOMIC_RELEASE);   // the fields above are seen first

  // Wait for the UI task. If it never picks the tile up, take it back - but only while it
  // is still queued: once the UI task is writing, the caller's buffer is in use and must
  // not be freed, so wait for the write to finish instead.
  for (int waited = 0;; waited += 2) {
    const uint8_t s = __atomic_load_n(&_pending.state, __ATOMIC_ACQUIRE);
    if (s == P_DONE || s == P_FAILED) break;
    if (s == P_QUEUED && waited >= 8000) {
      uint8_t expect = P_QUEUED;
      if (__atomic_compare_exchange_n(&_pending.state, &expect, P_IDLE, false, __ATOMIC_ACQ_REL,
                                      __ATOMIC_ACQUIRE)) {
        return false;                               // never started: safe to give up
      }
      continue;                                     // it started just now; see it through
    }
    vTaskDelay(pdMS_TO_TICKS(2));                   // the UI loop picks it up within a tick
  }
  const bool ok = __atomic_load_n(&_pending.state, __ATOMIC_ACQUIRE) == P_DONE;
  _pending.data = nullptr;
  __atomic_store_n(&_pending.state, P_IDLE, __ATOMIC_RELEASE);
  return ok;
}

// Called from the UI loop, which is the only task allowed near the card.
void UmcTiles::servicePending() {
  // claim it, so the web task knows not to take it back
  uint8_t expect = P_QUEUED;
  if (!__atomic_compare_exchange_n(&_pending.state, &expect, P_WRITING, false, __ATOMIC_ACQ_REL,
                                   __ATOMIC_ACQUIRE)) {
    return;
  }
  const bool ok = writeTileNow(_pending.z, _pending.x, _pending.y, _pending.data, _pending.len);
  __atomic_store_n(&_pending.state, ok ? P_DONE : P_FAILED, __ATOMIC_RELEASE);
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

// True for a folder or file name that is all digits, with an optional ".bin" on a file.
static bool numericName(const char* name, bool want_bin) {
  const char* base = strrchr(name, '/');
  base = base ? base + 1 : name;
  int digits = 0;
  while (base[digits] >= '0' && base[digits] <= '9') digits++;
  if (digits == 0) return false;
  return want_bin ? strcmp(base + digits, ".bin") == 0 : base[digits] == 0;
}

static const char* baseName(const char* name) {
  const char* base = strrchr(name, '/');
  return base ? base + 1 : name;
}

int UmcTiles::clearAll() {
  if (SD.cardType() == CARD_NONE) return -1;
  int removed = 0;
  char path[64];
  // the folders are listed first and deleted afterwards: removing entries while a
  // directory is being walked confuses the walk
  static char zooms[24][8];      // static: too big for the loop task stack, and only it calls this
  int nz = 0;
  File root = SD.open("/maps");
  if (!root) return 0;
  for (File f = root.openNextFile(); f && nz < 24; f = root.openNextFile()) {
    if (f.isDirectory() && numericName(f.name(), false)) StrHelper::strncpy(zooms[nz++], baseName(f.name()), 8);
    f.close();
  }
  root.close();

  for (int zi = 0; zi < nz; zi++) {
    static char xs[160][8];
    int nx = 0;
    snprintf(path, sizeof(path), "/maps/%s", zooms[zi]);
    File zdir = SD.open(path);
    if (!zdir) continue;
    for (File f = zdir.openNextFile(); f && nx < 160; f = zdir.openNextFile()) {
      if (f.isDirectory() && numericName(f.name(), false)) StrHelper::strncpy(xs[nx++], baseName(f.name()), 8);
      f.close();
    }
    zdir.close();

    for (int xi = 0; xi < nx; xi++) {
      static char ys[160][12];
      int ny = 0;
      snprintf(path, sizeof(path), "/maps/%s/%s", zooms[zi], xs[xi]);
      File xdir = SD.open(path);
      if (!xdir) continue;
      for (File f = xdir.openNextFile(); f && ny < 160; f = xdir.openNextFile()) {
        if (!f.isDirectory() && numericName(f.name(), true)) StrHelper::strncpy(ys[ny++], baseName(f.name()), 12);
        f.close();
      }
      xdir.close();
      for (int yi = 0; yi < ny; yi++) {
        snprintf(path, sizeof(path), "/maps/%s/%s/%s", zooms[zi], xs[xi], ys[yi]);
        if (SD.remove(path)) removed++;
      }
      snprintf(path, sizeof(path), "/maps/%s/%s", zooms[zi], xs[xi]);
      SD.rmdir(path);                                // only succeeds if nothing else was in it
    }
    snprintf(path, sizeof(path), "/maps/%s", zooms[zi]);
    SD.rmdir(path);
  }

  for (int i = 0; i < _num_slots; i++) _slots[i].z = -1;   // the cache is stale now
  scanZooms();
  if (_max_zoom < 0) {
    _ok = false;
    strncpy(_status, "no tiles on the card", sizeof(_status) - 1);
  }
  return removed;
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
int UmcTiles::clearAll() { return -1; }

#endif
