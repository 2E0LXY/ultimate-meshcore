#pragma once

#include <Arduino.h>
#include <Wire.h>

// Input for the LilyGo T-Deck / T-Deck Plus: capacitive touch (GT911), the built-in
// keyboard (an I2C co-processor at 0x55) and the trackball.
//
// The touch panel is mounted portrait while the screen runs landscape, and different
// batches differ, so the mapping is a runtime setting (`set touch.map 0..7`) that can be
// corrected without reflashing.
#ifndef TDECK_KEYBOARD_ADDR
  #define TDECK_KEYBOARD_ADDR 0x55
#endif
#ifndef TDECK_TOUCH_INT
  #define TDECK_TOUCH_INT 16
#endif
#ifndef TDECK_TB_UP
  #define TDECK_TB_UP 3
#endif
#ifndef TDECK_TB_DOWN
  #define TDECK_TB_DOWN 15
#endif
#ifndef TDECK_TB_LEFT
  #define TDECK_TB_LEFT 1
#endif
#ifndef TDECK_TB_RIGHT
  #define TDECK_TB_RIGHT 2
#endif

struct TouchEvent {
  bool down = false;      // finger is on the glass
  bool pressed = false;   // first frame of a touch
  bool released = false;  // finger lifted this frame
  int x = 0, y = 0;       // screen coordinates
  int start_x = 0, start_y = 0;
  int dx = 0, dy = 0;     // movement since the last frame (drag)
};

class TDeckInput {
public:
  void begin(int screen_w, int screen_h, uint8_t touch_map = 0) {
    _w = screen_w;
    _h = screen_h;
    _map = touch_map;
    pinMode(TDECK_TOUCH_INT, INPUT);
    _addr = probe(0x5D) ? 0x5D : (probe(0x14) ? 0x14 : 0);
    _kbd = probe(TDECK_KEYBOARD_ADDR);
    for (int pin : {TDECK_TB_UP, TDECK_TB_DOWN, TDECK_TB_LEFT, TDECK_TB_RIGHT}) pinMode(pin, INPUT_PULLUP);
    _tb_state = trackballBits();
  }

  bool hasTouch() const { return _addr != 0; }
  bool hasKeyboard() const { return _kbd; }
  void setTouchMap(uint8_t m) { _map = m & 7; }
  uint8_t touchMap() const { return _map; }

  // One key press from the built-in keyboard, 0 if none. 8 = backspace, 13 = enter.
  char readKey() {
    if (!_kbd) return 0;
    if (Wire.requestFrom((uint8_t)TDECK_KEYBOARD_ADDR, (uint8_t)1) != 1) return 0;
    int c = Wire.read();
    return c > 0 ? (char)c : 0;
  }

  // Trackball as arrow keys: returns 'U', 'D', 'L', 'R' or 0.
  char readTrackball() {
    uint8_t now = trackballBits();
    uint8_t changed = now ^ _tb_state;
    _tb_state = now;
    if (changed & 1) return 'U';
    if (changed & 2) return 'D';
    if (changed & 4) return 'L';
    if (changed & 8) return 'R';
    return 0;
  }

  TouchEvent poll() {
    TouchEvent ev;
    ev.down = _down;
    if (_addr == 0) return ev;

    uint8_t status = 0;
    if (!readReg(0x814E, &status, 1)) return ev;
    const bool have = (status & 0x80) && (status & 0x0F) > 0;
    if (have) {
      uint8_t p[4];
      if (readReg(0x8150, p, 4)) {
        int rx = p[0] | (p[1] << 8);
        int ry = p[2] | (p[3] << 8);
        mapPoint(rx, ry, ev.x, ev.y);
        if (!_down) {
          _down = true;
          ev.pressed = true;
          _sx = ev.x; _sy = ev.y;
        } else {
          ev.dx = ev.x - _lx;
          ev.dy = ev.y - _ly;
        }
        _lx = ev.x; _ly = ev.y;
        ev.down = true;
        ev.start_x = _sx; ev.start_y = _sy;
      }
    } else if (_down) {
      _down = false;
      ev.released = true;
      ev.x = _lx; ev.y = _ly;
      ev.start_x = _sx; ev.start_y = _sy;
    }
    if (status & 0x80) writeReg(0x814E, 0);  // tell the controller we have read this point
    return ev;
  }

private:
  bool probe(uint8_t addr) {
    Wire.beginTransmission(addr);
    return Wire.endTransmission() == 0;
  }
  bool readReg(uint16_t reg, uint8_t* dest, size_t len) {
    if (_addr == 0) return false;
    Wire.beginTransmission(_addr);
    Wire.write((uint8_t)(reg >> 8));
    Wire.write((uint8_t)(reg & 0xFF));
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(_addr, (uint8_t)len) != len) return false;
    for (size_t i = 0; i < len; i++) dest[i] = Wire.read();
    return true;
  }
  void writeReg(uint16_t reg, uint8_t value) {
    Wire.beginTransmission(_addr);
    Wire.write((uint8_t)(reg >> 8));
    Wire.write((uint8_t)(reg & 0xFF));
    Wire.write(value);
    Wire.endTransmission();
  }
  // The panel reports portrait coordinates (short side first); _map picks the rotation/flip.
  void mapPoint(int rx, int ry, int& x, int& y) const {
    const int pw = (_map & 4) ? _w : _h;   // panel width in its own orientation
    const int ph = (_map & 4) ? _h : _w;
    int px = rx, py = ry;
    if (px < 0) px = 0; if (px > pw) px = pw;
    if (py < 0) py = 0; if (py > ph) py = ph;
    switch (_map & 3) {
      case 0: x = py; y = _h - 1 - px; break;   // portrait panel, landscape screen
      case 1: x = _w - 1 - py; y = px; break;
      case 2: x = px; y = py; break;            // same orientation
      case 3: x = _w - 1 - px; y = _h - 1 - py; break;
    }
    if (_map & 4) {  // mirror horizontally for panels fitted the other way round
      x = _w - 1 - x;
    }
    if (x < 0) x = 0; if (x >= _w) x = _w - 1;
    if (y < 0) y = 0; if (y >= _h) y = _h - 1;
  }
  uint8_t trackballBits() const {
    return (digitalRead(TDECK_TB_UP) ? 1 : 0) | (digitalRead(TDECK_TB_DOWN) ? 2 : 0) |
           (digitalRead(TDECK_TB_LEFT) ? 4 : 0) | (digitalRead(TDECK_TB_RIGHT) ? 8 : 0);
  }

  uint8_t _addr = 0;
  bool _kbd = false;
  bool _down = false;
  int _w = 320, _h = 240;
  int _lx = 0, _ly = 0, _sx = 0, _sy = 0;
  uint8_t _map = 0;
  uint8_t _tb_state = 0;
};
