#include <Arduino.h>
#include "TDeckBoard.h"

uint32_t deviceOnline = 0x00;

// True when the keyboard/touch/clock bus came up cleanly (read by the screen code).
bool tdeck_i2c_ok = false;

// A device interrupted mid-byte holds SDA low and jams the bus; clocking SCL lets it
// finish. Done before the I2C peripheral claims the pins.
static bool tdeckFreeI2CBus(int sda, int scl) {
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
  pinMode(sda, OUTPUT);          // stop condition: everything back to idle
  digitalWrite(sda, LOW);
  delayMicroseconds(5);
  pinMode(scl, INPUT_PULLUP);
  delayMicroseconds(5);
  pinMode(sda, INPUT_PULLUP);
  delay(5);
  return digitalRead(sda) == HIGH && digitalRead(scl) == HIGH;
}

void TDeckBoard::begin() {
  // Peripheral power first: the keyboard co-processor and the touch panel run from it and
  // need a moment to start, and the bus must be clear before anything talks on it.
  pinMode(PIN_PERF_POWERON, OUTPUT);
  digitalWrite(PIN_PERF_POWERON, LOW);
  delay(60);
  digitalWrite(PIN_PERF_POWERON, HIGH);
  delay(600);
  tdeck_i2c_ok = tdeckFreeI2CBus(PIN_BOARD_SDA, PIN_BOARD_SCL);

  ESP32Board::begin();   // brings up I2C on PIN_BOARD_SDA / PIN_BOARD_SCL

  

  // Configure user button
  pinMode(PIN_USER_BTN, INPUT);

  // Configure LoRa Pins
  pinMode(P_LORA_MISO, INPUT_PULLUP);
  // pinMode(P_LORA_DIO_1, INPUT_PULLUP);

  #ifdef P_LORA_TX_LED
    digitalWrite(P_LORA_TX_LED, HIGH); // inverted pin for SX1276 - HIGH for off
  #endif

  esp_reset_reason_t reason = esp_reset_reason();
  if (reason == ESP_RST_DEEPSLEEP) {
    long wakeup_source = esp_sleep_get_ext1_wakeup_status();
    if (wakeup_source & (1 << P_LORA_DIO_1)) {
      startup_reason = BD_STARTUP_RX_PACKET; // received a LoRa packet (while in deep sleep)
    }

    rtc_gpio_hold_dis((gpio_num_t)P_LORA_NSS);
    rtc_gpio_deinit((gpio_num_t)P_LORA_DIO_1);
  }
}