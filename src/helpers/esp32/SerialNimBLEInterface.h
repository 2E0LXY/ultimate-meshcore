#pragma once

#include "../BaseSerialInterface.h"
#include <NimBLEDevice.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

// MeshCore companion link over Bluetooth LE using the NimBLE host stack.
//
// Same service, characteristics, PIN pairing and bonding as SerialBLEInterface (Bluedroid),
// so the MeshCore apps see no difference, but it needs roughly 60 KB less RAM. That is what
// lets Bluetooth, WiFi, the web UI and internet updates run together on boards without
// PSRAM such as the Heltec V3.
class SerialNimBLEInterface : public BaseSerialInterface, NimBLEServerCallbacks, NimBLECharacteristicCallbacks {
  NimBLEServer* pServer;
  NimBLEService* pService;
  NimBLECharacteristic* pTxCharacteristic;
  volatile bool deviceConnected;
  bool oldDeviceConnected;
  bool _isEnabled;
  volatile uint16_t last_conn_handle;
  uint32_t _pin_code;
  unsigned long _last_write;
  unsigned long adv_restart_time;

  struct Frame {
    uint8_t len;
    uint8_t buf[MAX_FRAME_SIZE];
  };

  #define NIMBLE_FRAME_QUEUE_SIZE 4
  StaticQueue_t recv_queue_state;
  uint8_t recv_queue_storage[NIMBLE_FRAME_QUEUE_SIZE * sizeof(Frame)];
  QueueHandle_t recv_queue;
  int send_queue_len;
  Frame send_queue[NIMBLE_FRAME_QUEUE_SIZE];

  char _dev_name[48];
  bool _suspended;
  bool _resume_enabled;

  void clearBuffers();
  void start();

protected:
  // NimBLEServerCallbacks (NimBLE-Arduino 1.4)
  void onConnect(NimBLEServer* server, ble_gap_conn_desc* desc) override;
  void onDisconnect(NimBLEServer* server, ble_gap_conn_desc* desc) override;
  uint32_t onPassKeyRequest() override;
  bool onConfirmPIN(uint32_t pass_key) override;
  void onAuthenticationComplete(ble_gap_conn_desc* desc) override;

  // NimBLECharacteristicCallbacks
  void onWrite(NimBLECharacteristic* characteristic) override;

public:
  SerialNimBLEInterface() {
    pServer = NULL;
    pService = NULL;
    pTxCharacteristic = NULL;
    deviceConnected = false;
    oldDeviceConnected = false;
    adv_restart_time = 0;
    _isEnabled = false;
    _last_write = 0;
    last_conn_handle = 0;
    _pin_code = 0;
    recv_queue = xQueueCreateStatic(NIMBLE_FRAME_QUEUE_SIZE, sizeof(Frame), recv_queue_storage, &recv_queue_state);
    send_queue_len = 0;
    _dev_name[0] = 0;
    _suspended = false;
    _resume_enabled = false;
  }

  // prefix + name form the advertised device name; name "@@MAC" is replaced with the MAC (IN/OUT).
  void begin(const char* prefix, char* name, uint32_t pin_code);

  // Shut the Bluetooth stack down and free its memory (about 70 KB), e.g. for an HTTPS
  // firmware download on boards without PSRAM; resume() brings it back as it was.
  void suspend();
  void resume();
  bool isSuspended() const { return _suspended; }

  // BaseSerialInterface methods
  void enable() override;
  void disable() override;
  bool isEnabled() const override { return _isEnabled; }

  bool isConnected() const override;
  bool isWriteBusy() const override;

  size_t writeFrame(const uint8_t src[], size_t len) override;
  size_t checkRecvFrame(uint8_t dest[]) override;
};
