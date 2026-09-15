#include "UmcAppServer.h"

#include <string.h>

#if defined(ESP_PLATFORM)
  #include <WiFi.h>
#endif

#include "UmcService.h"

namespace {
constexpr uint8_t kStateIdle = 0, kStateLen1 = 1, kStateLen2 = 2, kStateBody = 3;
constexpr unsigned long kIdleDropMs = 15UL * 60UL * 1000UL;   // apps poll often; drop dead sessions
constexpr uint8_t kPushMsgWaiting = 0x83;
}  // namespace

UmcAppServer::UmcAppServer(UmcService& umc) : _umc(umc), _server(nullptr), _port(5000), _clients{} {}

void UmcAppServer::start() {
#if defined(ESP_PLATFORM)
  if (_server != nullptr) return;
  _port = _umc.prefs().app_tcp_port;
  _server = new WiFiServer(_port);
  _server->begin();
  _server->setNoDelay(true);
  Serial.printf("[UMC] app connection (MeshCore companion protocol) on TCP %u\n", _port);
#endif
}

void UmcAppServer::stop() {
#if defined(ESP_PLATFORM)
  for (int i = 0; i < kMaxClients; i++) drop(i);
  if (_server != nullptr) {
    _server->end();
    delete _server;
    _server = nullptr;
  }
#endif
}

void UmcAppServer::drop(int i) {
#if defined(ESP_PLATFORM)
  Client& c = _clients[i];
  if (c.sock != nullptr) {
    c.sock->stop();
    delete c.sock;
  }
  memset(&c, 0, sizeof(c));
#else
  (void)i;
#endif
}

void UmcAppServer::setLogin(int client, bool logged_in, bool admin) {
  if (client < 0 || client >= kMaxClients) return;
  _clients[client].logged_in = logged_in;
  _clients[client].admin = logged_in && admin;
}

int UmcAppServer::connectedCount() const {
  int n = 0;
  for (const auto& c : _clients) n += c.sock != nullptr ? 1 : 0;
  return n;
}

bool UmcAppServer::send(int client, const uint8_t* data, size_t len) {
#if defined(ESP_PLATFORM)
  if (client < 0 || client >= kMaxClients || len > kMaxFrame) return false;
  WiFiClient* s = _clients[client].sock;
  if (s == nullptr || !s->connected()) return false;
  uint8_t frame[kMaxFrame + 3];
  frame[0] = '>';
  frame[1] = len & 0xFF;
  frame[2] = (len >> 8) & 0xFF;
  memcpy(frame + 3, data, len);
  size_t total = len + 3, sent = 0;
  unsigned long start = millis();
  while (sent < total && millis() - start < 500) {
    size_t n = s->write(frame + sent, total - sent);
    if (n == 0) {
      delay(1);
      continue;
    }
    sent += n;
  }
  return sent == total;
#else
  (void)client; (void)data; (void)len;
  return false;
#endif
}

void UmcAppServer::queueMessage(int client, const uint8_t* data, size_t len) {
  if (client < 0 || client >= kMaxClients || len > kMaxFrame) return;
  Client& c = _clients[client];
  if (c.q_count == kQueueLen) {  // drop oldest
    c.q_head = (c.q_head + 1) % kQueueLen;
    c.q_count--;
  }
  int slot = (c.q_head + c.q_count) % kQueueLen;
  memcpy(c.q[slot], data, len);
  c.q_len[slot] = static_cast<uint8_t>(len);
  c.q_count++;
  const uint8_t tickle = kPushMsgWaiting;
  send(client, &tickle, 1);
}

size_t UmcAppServer::popMessage(int client, uint8_t* out) {
  if (client < 0 || client >= kMaxClients) return 0;
  Client& c = _clients[client];
  if (c.q_count == 0) return 0;
  size_t len = c.q_len[c.q_head];
  memcpy(out, c.q[c.q_head], len);
  c.q_head = (c.q_head + 1) % kQueueLen;
  c.q_count--;
  return len;
}

void UmcAppServer::loop(bool enabled) {
#if defined(ESP_PLATFORM)
  if (!enabled) {
    stop();
    return;
  }
  start();

  while (_server->hasClient()) {
    WiFiClient incoming = _server->accept();
    int slot = -1;
    for (int i = 0; i < kMaxClients; i++) {
      if (_clients[i].sock == nullptr) {
        slot = i;
        break;
      }
    }
    if (slot < 0) {
      incoming.stop();
      continue;
    }
    memset(&_clients[slot], 0, sizeof(Client));
    _clients[slot].sock = new WiFiClient(incoming);
    _clients[slot].sock->setNoDelay(true);
    _clients[slot].last_rx_ms = millis();
    Serial.printf("[UMC] app connected from %s (slot %d)\n", incoming.remoteIP().toString().c_str(), slot);
  }

  for (int i = 0; i < kMaxClients; i++) {
    Client& c = _clients[i];
    if (c.sock == nullptr) continue;
    if (!c.sock->connected() || millis() - c.last_rx_ms > kIdleDropMs) {
      Serial.printf("[UMC] app disconnected (slot %d)\n", i);
      drop(i);
      continue;
    }
    int budget = 512;  // bytes per loop pass per client, keeps the mesh loop responsive
    while (budget-- > 0 && c.sock->available()) {
      int b = c.sock->read();
      if (b < 0) break;
      c.last_rx_ms = millis();
      switch (c.state) {
        case kStateIdle:
          if (b == '<') c.state = kStateLen1;
          break;
        case kStateLen1:
          c.frame_len = static_cast<uint8_t>(b);
          c.state = kStateLen2;
          break;
        case kStateLen2:
          c.frame_len |= static_cast<uint16_t>(b) << 8;
          c.rx_len = 0;
          c.state = c.frame_len > 0 ? kStateBody : kStateIdle;
          break;
        default:
          if (c.rx_len < kMaxFrame) c.rx[c.rx_len] = static_cast<uint8_t>(b);
          c.rx_len++;
          if (c.rx_len >= c.frame_len) {
            size_t n = c.frame_len > kMaxFrame ? kMaxFrame : c.frame_len;
            c.rx[n] = 0;
            c.state = kStateIdle;
            if (_umc.host() != nullptr) _umc.host()->umcAppFrame(*this, i, c.rx, n);
            if (_clients[i].sock == nullptr) budget = 0;  // handler dropped us
          }
          break;
      }
    }
  }
#else
  (void)enabled;
#endif
}
