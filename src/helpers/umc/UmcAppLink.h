#pragma once

#include <helpers/BaseSerialInterface.h>
#include <string.h>

#include "UmcAppServer.h"

// Companion firmware: presents the UMC TCP app server (port 5000, up to three apps at
// once) as one more MeshCore serial interface, so apps on the LAN talk straight to the
// companion core exactly as they would over Bluetooth or USB.
class UmcAppLink : public BaseSerialInterface {
public:
  static constexpr int kInbox = 6;

  void attach(UmcAppServer* server) {
    _server = server;
    if (_server != nullptr) _server->setIdleDropMs(0);
  }

  // Called from UmcHost::umcAppFrame (loop task).
  void push(const uint8_t* frame, size_t len) {
    if (len == 0 || len > MAX_FRAME_SIZE || _count >= kInbox) return;
    Frame& f = _inbox[(_head + _count) % kInbox];
    f.len = static_cast<uint8_t>(len);
    memcpy(f.buf, frame, len);
    _count++;
  }

  void enable() override { _enabled = true; }
  void disable() override { _enabled = false; }
  bool isEnabled() const override { return _enabled; }
  bool isConnected() const override { return _server != nullptr && _server->connectedCount() > 0; }
  bool isWriteBusy() const override { return false; }

  size_t writeFrame(const uint8_t src[], size_t len) override {
    if (_server == nullptr || len == 0) return len;
    for (int i = 0; i < UmcAppServer::kMaxClients; i++) _server->send(i, src, len);
    return len;
  }

  size_t checkRecvFrame(uint8_t dest[]) override {
    if (_count == 0) return 0;
    Frame& f = _inbox[_head];
    size_t len = f.len;
    memcpy(dest, f.buf, len);
    _head = (_head + 1) % kInbox;
    _count--;
    return len;
  }

private:
  struct Frame {
    uint8_t len;
    uint8_t buf[MAX_FRAME_SIZE];
  };
  UmcAppServer* _server = nullptr;
  Frame _inbox[kInbox] = {};
  int _head = 0, _count = 0;
  bool _enabled = false;
};
