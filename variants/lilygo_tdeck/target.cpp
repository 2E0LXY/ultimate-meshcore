#include <Arduino.h>
#include "target.h"

TDeckBoard board;

#if defined(P_LORA_SCLK)
  static SPIClass spi;
  RADIO_CLASS radio = new Module(P_LORA_NSS, P_LORA_DIO_1, P_LORA_RESET, P_LORA_BUSY, spi);
#else
  RADIO_CLASS radio = new Module(P_LORA_NSS, P_LORA_DIO_1, P_LORA_RESET, P_LORA_BUSY);
#endif

WRAPPER_CLASS radio_driver(radio, board);

ESP32RTCClock fallback_clock;
AutoDiscoverRTCClock rtc_clock(fallback_clock);
MicroNMEALocationProvider gps(Serial1, &rtc_clock);
EnvironmentSensorManager sensors(gps);

#ifdef DISPLAY_CLASS
  DISPLAY_CLASS display;
  MomentaryButton user_btn(PIN_USER_BTN, 1000, true);
#endif

// True when the keyboard/touch/clock bus came up cleanly.
bool tdeck_i2c_ok = false;

// A slave that was interrupted mid-byte keeps SDA low and jams the bus; clocking SCL lets
// it finish. Standard recovery, done before the I2C peripheral takes the pins.
static bool tdeckFreeI2CBus(int sda, int scl) {
#ifdef PIN_PERF_POWERON
  // Power-cycle the peripheral rail: the keyboard co-processor and the touch panel both
  // live on it, and they only answer if they started cleanly.
  pinMode(PIN_PERF_POWERON, OUTPUT);
  digitalWrite(PIN_PERF_POWERON, LOW);
  delay(60);
  digitalWrite(PIN_PERF_POWERON, HIGH);
  delay(600);
#endif
  pinMode(sda, INPUT_PULLUP);
  pinMode(scl, INPUT_PULLUP);
  delay(5);
  if (digitalRead(sda) == HIGH && digitalRead(scl) == HIGH) return true;
  for (int i = 0; i < 9 && digitalRead(sda) == LOW; i++) {
    pinMode(scl, OUTPUT);
    digitalWrite(scl, LOW);
    delayMicroseconds(5);
    pinMode(scl, INPUT_PULLUP);
    delayMicroseconds(5);
  }
  // stop condition, so everything on the bus is back to idle
  pinMode(sda, OUTPUT);
  digitalWrite(sda, LOW);
  delayMicroseconds(5);
  pinMode(scl, INPUT_PULLUP);
  delayMicroseconds(5);
  pinMode(sda, INPUT_PULLUP);
  delay(5);
  return digitalRead(sda) == HIGH && digitalRead(scl) == HIGH;
}

bool radio_init() {
  fallback_clock.begin();
  // I2C first, on the T-Deck's pins: anything that starts the bus before this (the clock
  // driver did) leaves it on the default pins for good, and the keyboard, touch panel and
  // clock all sit on 18/8 and never answer.
  tdeck_i2c_ok = tdeckFreeI2CBus(18, 8);
  if (tdeck_i2c_ok) {
    Wire.begin(18, 8);
    Wire.setTimeOut(50);      // a missing device must not stall the main loop
    rtc_clock.begin(Wire);
  }

#if defined(P_LORA_SCLK)
  return radio.std_init(&spi);
#else
  return radio.std_init();
#endif
}

mesh::LocalIdentity radio_new_identity() {
  RadioNoiseListener rng(radio);
  return mesh::LocalIdentity(&rng); // create new random identity
}
