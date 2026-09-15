#pragma once

#include <Arduino.h>

class UmcService;
class WiFiServer;
class WiFiClient;

// MeshCore companion-protocol server on TCP (default port 5000), so the MeshCore apps,
// meshcore-open, meshcore_py, meshcore-cli and Home Assistant can connect over the LAN.
//
// Wire format (same as USB serial companion): app -> device '<' len_lo len_hi payload,
// device -> app '>' len_lo len_hi payload. Runs on the Arduino loop task; frames are
// handed to UmcHost::umcAppFrame() which answers through send()/queueMessage().
class UmcAppServer {
public:
  static constexpr int kMaxClients = 3;
  static constexpr size_t kMaxFrame = 172;
  static constexpr int kQueueLen = 6;

  explicit UmcAppServer(UmcService& umc);
  void loop(bool enabled);

  bool send(int client, const uint8_t* data, size_t len);
  // Queue a frame for CMD_SYNC_NEXT_MESSAGE and send the PUSH_CODE_MSG_WAITING tickle.
  void queueMessage(int client, const uint8_t* data, size_t len);
  // Returns the next queued frame length (0 if none).
  size_t popMessage(int client, uint8_t* out);

  bool isLoggedIn(int client) const { return client >= 0 && client < kMaxClients && _clients[client].logged_in; }
  bool isAdmin(int client) const { return isLoggedIn(client) && _clients[client].admin; }
  void setLogin(int client, bool logged_in, bool admin);
  uint8_t appVersion(int client) const { return (client >= 0 && client < kMaxClients) ? _clients[client].app_ver : 0; }
  void setAppVersion(int client, uint8_t v) { if (client >= 0 && client < kMaxClients) _clients[client].app_ver = v; }
  int connectedCount() const;
  uint16_t port() const { return _port; }

private:
  struct Client {
    WiFiClient* sock;
    uint8_t state;
    uint16_t frame_len;
    uint16_t rx_len;
    uint8_t rx[kMaxFrame + 1];
    bool logged_in;
    bool admin;
    uint8_t app_ver;
    uint8_t q_len[kQueueLen];
    uint8_t q[kQueueLen][kMaxFrame];
    uint8_t q_head, q_count;
    unsigned long last_rx_ms;
  };

  void start();
  void stop();
  void drop(int i);

  UmcService& _umc;
  WiFiServer* _server;
  uint16_t _port;
  Client _clients[kMaxClients];
};
