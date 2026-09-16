#ifdef UMC_NIMBLE

#include "SerialNimBLEInterface.h"
#include "esp_mac.h"

#define SERVICE_UUID           "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"  // Nordic UART service, as the apps expect
#define CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

#define ADVERT_RESTART_DELAY   1000  // millis
#define BLE_WRITE_MIN_INTERVAL 60

void SerialNimBLEInterface::begin(const char* prefix, char* name, uint32_t pin_code) {
  _pin_code = pin_code;

  if (strcmp(name, "@@MAC") == 0) {
    uint8_t addr[8];
    memset(addr, 0, sizeof(addr));
    esp_efuse_mac_get_default(addr);
    sprintf(name, "%02X%02X%02X%02X%02X%02X", addr[5], addr[4], addr[3], addr[2], addr[1], addr[0]);
  }
  snprintf(_dev_name, sizeof(_dev_name), "%s%s", prefix, name);
  start();
}

void SerialNimBLEInterface::start() {
  NimBLEDevice::init(_dev_name);
  NimBLEDevice::setMTU(MAX_FRAME_SIZE);
  // Passkey entry with the device PIN, MITM protection, LE Secure Connections, bonding
  NimBLEDevice::setSecurityAuth(true, true, true);
  NimBLEDevice::setSecurityPasskey(_pin_code);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);

  pServer = NimBLEDevice::createServer();
  pServer->setCallbacks(this, false);
  pServer->advertiseOnDisconnect(false);  // restarted from checkRecvFrame(), like the Bluedroid interface

  pService = pServer->createService(SERVICE_UUID);
  pTxCharacteristic = pService->createCharacteristic(
      CHARACTERISTIC_UUID_TX, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ_ENC | NIMBLE_PROPERTY::READ_AUTHEN);
  NimBLECharacteristic* rx = pService->createCharacteristic(
      CHARACTERISTIC_UUID_RX, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC | NIMBLE_PROPERTY::WRITE_AUTHEN);
  rx->setCallbacks(this);
  pService->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
}

void SerialNimBLEInterface::suspend() {
  if (_suspended || pServer == NULL) return;
  _resume_enabled = _isEnabled;
  disable();
  NimBLEDevice::deinit(true);  // deletes server/service objects and releases the controller memory
  pServer = NULL;
  pService = NULL;
  pTxCharacteristic = NULL;
  _suspended = true;
}

void SerialNimBLEInterface::resume() {
  if (!_suspended) return;
  _suspended = false;
  start();
  if (_resume_enabled) enable();
}

// -------- NimBLEServerCallbacks

void SerialNimBLEInterface::onConnect(NimBLEServer* server, ble_gap_conn_desc* desc) {
  (void)server;
  last_conn_handle = desc->conn_handle;
}

void SerialNimBLEInterface::onDisconnect(NimBLEServer* server, ble_gap_conn_desc* desc) {
  (void)server;
  (void)desc;
  deviceConnected = false;
  if (_isEnabled) {
    adv_restart_time = millis() + ADVERT_RESTART_DELAY;
  }
}

uint32_t SerialNimBLEInterface::onPassKeyRequest() {
  return _pin_code;
}

bool SerialNimBLEInterface::onConfirmPIN(uint32_t pass_key) {
  (void)pass_key;
  return true;
}

void SerialNimBLEInterface::onAuthenticationComplete(ble_gap_conn_desc* desc) {
  if (desc->sec_state.encrypted && desc->sec_state.authenticated) {
    deviceConnected = true;
  } else {
    pServer->disconnect(desc->conn_handle);
    adv_restart_time = millis() + ADVERT_RESTART_DELAY;
  }
}

// -------- NimBLECharacteristicCallbacks

void SerialNimBLEInterface::onWrite(NimBLECharacteristic* characteristic) {
  NimBLEAttValue value = characteristic->getValue();
  size_t len = value.length();
  if (len == 0 || len > MAX_FRAME_SIZE) return;
  Frame frame = {};
  frame.len = static_cast<uint8_t>(len);
  memcpy(frame.buf, value.data(), len);
  xQueueSend(recv_queue, &frame, 0);  // dropped if the loop is not keeping up
}

// ---------- public methods

void SerialNimBLEInterface::clearBuffers() {
  xQueueReset(recv_queue);
  send_queue_len = 0;
}

void SerialNimBLEInterface::enable() {
  if (_isEnabled) return;
  if (_suspended) {  // remember the request; applied on resume()
    _resume_enabled = true;
    return;
  }
  _isEnabled = true;
  clearBuffers();
  NimBLEDevice::getAdvertising()->start();
  adv_restart_time = 0;
}

void SerialNimBLEInterface::disable() {
  if (_suspended) {
    _resume_enabled = false;
    return;
  }
  _isEnabled = false;
  NimBLEDevice::getAdvertising()->stop();
  if (pServer != NULL && pServer->getConnectedCount() > 0) {
    pServer->disconnect(last_conn_handle);
  }
  oldDeviceConnected = deviceConnected = false;
  adv_restart_time = 0;
}

size_t SerialNimBLEInterface::writeFrame(const uint8_t src[], size_t len) {
  if (len > MAX_FRAME_SIZE) return 0;
  if (deviceConnected && len > 0) {
    if (send_queue_len >= NIMBLE_FRAME_QUEUE_SIZE) return 0;
    send_queue[send_queue_len].len = len;
    memcpy(send_queue[send_queue_len].buf, src, len);
    send_queue_len++;
    return len;
  }
  return 0;
}

bool SerialNimBLEInterface::isWriteBusy() const {
  return millis() < _last_write + BLE_WRITE_MIN_INTERVAL;  // still too soon to start another write?
}

size_t SerialNimBLEInterface::checkRecvFrame(uint8_t dest[]) {
  if (_suspended) return 0;
  if (send_queue_len > 0 && millis() >= _last_write + BLE_WRITE_MIN_INTERVAL) {
    _last_write = millis();
    pTxCharacteristic->setValue(send_queue[0].buf, send_queue[0].len);
    pTxCharacteristic->notify();
    send_queue_len--;
    for (int i = 0; i < send_queue_len; i++) {
      send_queue[i] = send_queue[i + 1];
    }
  }

  Frame frame;
  if (xQueueReceive(recv_queue, &frame, 0) == pdTRUE) {
    memcpy(dest, frame.buf, frame.len);
    return frame.len;
  }

  if (deviceConnected != oldDeviceConnected) {
    if (!deviceConnected) {
      clearBuffers();
      adv_restart_time = millis() + ADVERT_RESTART_DELAY;
    } else {
      NimBLEDevice::getAdvertising()->stop();
      adv_restart_time = 0;
    }
    oldDeviceConnected = deviceConnected;
  }

  if (adv_restart_time && millis() >= adv_restart_time) {
    if (_isEnabled && pServer->getConnectedCount() == 0) {
      NimBLEDevice::getAdvertising()->start();
    }
    adv_restart_time = 0;
  }
  return 0;
}

bool SerialNimBLEInterface::isConnected() const {
  return deviceConnected && !_suspended;
}

#endif  // UMC_NIMBLE
