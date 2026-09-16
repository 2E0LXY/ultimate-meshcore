#pragma once

#include <Arduino.h>
#include <math.h>

// Offline map tiles read from the SD card.
//
// Layout on the card:   /maps/<zoom>/<x>/<y>.bin
// Each file is a 256x256 raw RGB565 (big-endian) tile - the same tiles a normal map uses,
// converted by scripts/umc_make_map_tiles.py so the device never needs to decode PNG.
// Tiles are cached in PSRAM, so panning stays smooth.
#define UMC_TILE_PX 256
#define UMC_TILE_BYTES (UMC_TILE_PX * UMC_TILE_PX * 2)

class UmcTiles {
public:
  bool begin(int cache_tiles = 6);
  bool available() const { return _ok; }
  bool hasZoom(int z) const { return z >= _min_zoom && z <= _max_zoom; }
  int minZoom() const { return _min_zoom; }
  int maxZoom() const { return _max_zoom; }
  const char* status() const { return _status; }

  // Returns a cached tile (UMC_TILE_BYTES bytes) or NULL when that tile isn't on the card.
  const uint16_t* tile(int z, int x, int y);

  // Web-Mercator helpers: world pixel coordinates at a zoom level.
  static double lonToWorldX(double lon, int z) { return (lon + 180.0) / 360.0 * UMC_TILE_PX * (1 << z); }
  static double latToWorldY(double lat, int z) {
    const double s = sin(lat * M_PI / 180.0);
    return (0.5 - log((1 + s) / (1 - s)) / (4 * M_PI)) * UMC_TILE_PX * (1 << z);
  }
  static double worldXToLon(double x, int z) { return x / (UMC_TILE_PX * (1 << z)) * 360.0 - 180.0; }
  static double worldYToLat(double y, int z) {
    const double n = M_PI - 2.0 * M_PI * y / (UMC_TILE_PX * (1 << z));
    return 180.0 / M_PI * atan(0.5 * (exp(n) - exp(-n)));
  }
  // Great-circle distance in metres.
  static double distanceM(double lat1, double lon1, double lat2, double lon2) {
    const double r = 6371000.0, p = M_PI / 180.0;
    const double a = 0.5 - cos((lat2 - lat1) * p) / 2 + cos(lat1 * p) * cos(lat2 * p) * (1 - cos((lon2 - lon1) * p)) / 2;
    return 2 * r * asin(sqrt(a));
  }
  static double bearingDeg(double lat1, double lon1, double lat2, double lon2) {
    const double p = M_PI / 180.0;
    const double y = sin((lon2 - lon1) * p) * cos(lat2 * p);
    const double x = cos(lat1 * p) * sin(lat2 * p) - sin(lat1 * p) * cos(lat2 * p) * cos((lon2 - lon1) * p);
    double b = atan2(y, x) / p;
    return b < 0 ? b + 360 : b;
  }

private:
  struct Slot {
    int z = -1, x = -1, y = -1;
    unsigned long used = 0;
    uint16_t* px = nullptr;
  };
  void scanZooms();

  Slot* _slots = nullptr;
  int _num_slots = 0;
  bool _ok = false;
  int _min_zoom = 0, _max_zoom = -1;
  char _status[48] = "not started";
};
