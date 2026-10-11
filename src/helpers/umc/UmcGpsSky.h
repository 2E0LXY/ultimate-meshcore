#pragma once

#include <Arduino.h>
#include <stdint.h>

// Satellites the receiver can see, taken from the GPS's own $..GSV sentences as they go
// past. The position itself is handled elsewhere; this is only for showing the sky.
#ifndef UMC_GPS_MAX_SATS
  #define UMC_GPS_MAX_SATS 32
#endif

class UmcGpsSky {
public:
  struct Sat {
    uint8_t prn;         // satellite number
    int8_t elevation;    // degrees above the horizon, 0-90
    int16_t azimuth;     // degrees clockwise from north
    uint8_t snr;         // 0 = not being received
    char system;         // P GPS, L GLONASS, A Galileo, B BeiDou, Q QZSS
    uint32_t seen_ms;
  };

  // One character of the GPS's output.
  void feed(char c) {
    _bytes++;                       // counted even when nothing parses, to prove it is alive
    _byte_ms = millis();
    if (c == '$') {
      _len = 0;
      _in_sentence = true;
      return;
    }
    if (!_in_sentence) return;
    if (c == '\r' || c == '\n') {
      _buf[_len] = 0;
      if (_len > 0) {
        _sentences++;
        strncpy(_last, _buf, sizeof(_last) - 1);
        _last[sizeof(_last) - 1] = 0;
      }
      if (_len > 6) parse();
      _in_sentence = false;
      _len = 0;
      return;
    }
    if (_len < sizeof(_buf) - 1) _buf[_len++] = c;
  }

  int count() const { return _count; }
  const Sat& get(int i) const { return _sats[i]; }
  int inView() const { return _in_view; }
  // How many are actually being received (non-zero signal).
  int tracked() const {
    int n = 0;
    for (int i = 0; i < _count; i++) {
      if (_sats[i].snr > 0) n++;
    }
    return n;
  }
  // Diagnostics: has the receiver sent anything, and what did it last say?
  uint32_t bytes() const { return _bytes; }
  uint32_t sentences() const { return _sentences; }
  const char* lastSentence() const { return _last; }
  uint32_t sinceByteMs() const { return _byte_ms == 0 ? 0 : millis() - _byte_ms; }

  bool fresh(uint32_t within_ms = 30000) const { return _count > 0 && millis() - _newest_ms < within_ms; }

  void clear() {
    _count = 0;
    _in_view = 0;
  }

private:
  // "GPGSV,3,1,11,07,79,048,42,08,52,296,37,..." - sentences per constellation
  void parse() {
    const char* p = _buf;
    if (p[0] == 0 || _buf[2] != 'G' || _buf[3] != 'S' || _buf[4] != 'V') return;
    const char system = _buf[1] == 'L' ? 'L' : _buf[0] == 'G' && _buf[1] == 'A' ? 'A'
                        : _buf[1] == 'B' ? 'B' : _buf[1] == 'Q' ? 'Q' : 'P';

    char* fields[24];
    int n = 0;
    char* s = _buf;
    while (n < 24) {
      char* comma = strchr(s, ',');
      fields[n++] = s;
      if (comma == nullptr) break;
      *comma = 0;
      s = comma + 1;
    }
    if (n < 4) return;
    const int msg_no = atoi(fields[2]);
    if (msg_no == 1 && system == _first_system) _count = 0;   // a new round for this cycle
    if (msg_no == 1) {
      _first_system = system;
      _in_view = 0;
    }
    _in_view += 0;   // counted from the entries we actually store
    for (int base = 4; base + 3 < n; base += 4) {
      const int prn = atoi(fields[base]);
      if (prn <= 0) continue;
      Sat sat;
      sat.prn = (uint8_t)prn;
      sat.elevation = (int8_t)atoi(fields[base + 1]);
      sat.azimuth = (int16_t)atoi(fields[base + 2]);
      sat.snr = (uint8_t)atoi(fields[base + 3]);
      sat.system = system;
      sat.seen_ms = millis();
      store(sat);
    }
    _newest_ms = millis();
    _in_view = _count;
  }

  void store(const Sat& sat) {
    for (int i = 0; i < _count; i++) {
      if (_sats[i].prn == sat.prn && _sats[i].system == sat.system) {
        _sats[i] = sat;
        return;
      }
    }
    if (_count < UMC_GPS_MAX_SATS) _sats[_count++] = sat;
  }

  Sat _sats[UMC_GPS_MAX_SATS];
  char _buf[96];
  size_t _len = 0;
  bool _in_sentence = false;
  int _count = 0;
  int _in_view = 0;
  char _first_system = 0;
  uint32_t _newest_ms = 0;
  uint32_t _bytes = 0;
  uint32_t _sentences = 0;
  uint32_t _byte_ms = 0;
  char _last[96] = {0};
};

extern UmcGpsSky umc_gps_sky;
