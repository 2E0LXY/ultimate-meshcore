// Ultimate MeshCore: MeshCore companion protocol for a repeater, served over TCP (port 5000).
//
// A repeater has no contacts or channels of its own, so it presents itself to the app as a
// single "console" contact. Logging in to that contact opens the app's normal repeater
// screens (status, telemetry, neighbours, command line) exactly as when administering a
// repeater over LoRa, but directly over WiFi. Native settings commands (name, radio, TX power,
// adverts, time, reboot) require an admin login on the same connection.

#ifdef UMC_BUILD

#include "MyMesh.h"

#include <helpers/umc/UmcAppServer.h>
#include <helpers/umc/UmcVersion.h>

#ifndef MAX_LORA_TX_POWER
  #define MAX_LORA_TX_POWER 22   // SX1262 limit when the board doesn't specify one
#endif

namespace {

// companion protocol codes (examples/companion_radio/MyMesh.cpp)
constexpr uint8_t CMD_APP_START = 1, CMD_SEND_TXT_MSG = 2, CMD_GET_CONTACTS = 4, CMD_GET_DEVICE_TIME = 5,
                  CMD_SET_DEVICE_TIME = 6, CMD_SEND_SELF_ADVERT = 7, CMD_SET_ADVERT_NAME = 8, CMD_SYNC_NEXT_MESSAGE = 10,
                  CMD_SET_RADIO_PARAMS = 11, CMD_SET_RADIO_TX_POWER = 12, CMD_SET_ADVERT_LATLON = 14, CMD_REBOOT = 19,
                  CMD_GET_BATT_AND_STORAGE = 20, CMD_SET_TUNING_PARAMS = 21, CMD_DEVICE_QUERY = 22, CMD_SEND_LOGIN = 26,
                  CMD_SEND_STATUS_REQ = 27, CMD_HAS_CONNECTION = 28, CMD_LOGOUT = 29, CMD_GET_CONTACT_BY_KEY = 30,
                  CMD_GET_CHANNEL = 31, CMD_SET_OTHER_PARAMS = 38, CMD_SEND_TELEMETRY_REQ = 39, CMD_GET_CUSTOM_VARS = 40,
                  CMD_GET_TUNING_PARAMS = 43, CMD_SEND_BINARY_REQ = 50, CMD_GET_STATS = 56, CMD_SET_PATH_HASH_MODE = 61;

constexpr uint8_t RESP_CODE_OK = 0, RESP_CODE_ERR = 1, RESP_CODE_CONTACTS_START = 2, RESP_CODE_CONTACT = 3,
                  RESP_CODE_END_OF_CONTACTS = 4, RESP_CODE_SELF_INFO = 5, RESP_CODE_SENT = 6, RESP_CODE_CONTACT_MSG_RECV = 7,
                  RESP_CODE_CURR_TIME = 9, RESP_CODE_NO_MORE_MESSAGES = 10, RESP_CODE_BATT_AND_STORAGE = 12,
                  RESP_CODE_DEVICE_INFO = 13, RESP_CODE_CONTACT_MSG_RECV_V3 = 16, RESP_CODE_CUSTOM_VARS = 21,
                  RESP_CODE_TUNING_PARAMS = 23, RESP_CODE_STATS = 24;

constexpr uint8_t PUSH_CODE_LOGIN_SUCCESS = 0x85, PUSH_CODE_LOGIN_FAIL = 0x86, PUSH_CODE_STATUS_RESPONSE = 0x87,
                  PUSH_CODE_TELEMETRY_RESPONSE = 0x8B, PUSH_CODE_BINARY_RESPONSE = 0x8C;

constexpr uint8_t ERR_CODE_UNSUPPORTED_CMD = 1, ERR_CODE_NOT_FOUND = 2, ERR_CODE_TABLE_FULL = 3, ERR_CODE_BAD_STATE = 4,
                  ERR_CODE_ILLEGAL_ARG = 6;

constexpr uint8_t kFirmwareVerCode = 10;     // companion protocol level we answer as
constexpr uint8_t kFirmwareVerLevel = 2;     // repeater login reply level
constexpr uint8_t kStatsCore = 0, kStatsRadio = 1, kStatsPackets = 2;
constexpr uint8_t REQ_GET_STATUS = 0x01, REQ_GET_TELEMETRY = 0x03;

}  // namespace

void MyMesh::umcConsoleKey(uint8_t* key) const {
  // Same identity as the repeater except the last byte, so apps (which hide contacts that
  // equal the radio's own key) show it, while 6-byte prefixes still match this repeater.
  memcpy(key, self_id.pub_key, PUB_KEY_SIZE);
  key[PUB_KEY_SIZE - 1] ^= 0xA5;
}

bool MyMesh::umcIsConsoleKey(const uint8_t* key, size_t n) const {
  uint8_t console[PUB_KEY_SIZE];
  umcConsoleKey(console);
  return memcmp(key, console, n) == 0 || memcmp(key, self_id.pub_key, n) == 0;
}

void MyMesh::umcAppFrame(UmcAppServer& srv, int client, const uint8_t* c, size_t len) {
  uint8_t out[UmcAppServer::kMaxFrame];
  auto sendErr = [&](uint8_t code) {
    const uint8_t f[2] = {RESP_CODE_ERR, code};
    srv.send(client, f, 2);
  };
  auto sendOk = [&]() {
    const uint8_t f[1] = {RESP_CODE_OK};
    srv.send(client, f, 1);
  };
  auto sendSent = [&](uint32_t tag) {
    out[0] = RESP_CODE_SENT;
    out[1] = 0;  // sent "direct"
    memcpy(&out[2], &tag, 4);
    uint32_t est_timeout = 3000;
    memcpy(&out[6], &est_timeout, 4);
    srv.send(client, out, 10);
  };
  auto needAdmin = [&]() -> bool {
    if (srv.isAdmin(client)) return true;
    sendErr(ERR_CODE_BAD_STATE);  // log in to the console contact as admin first
    return false;
  };
  if (len < 1) return;

  switch (c[0]) {
    case CMD_DEVICE_QUERY: {
      if (len >= 2) srv.setAppVersion(client, c[1]);
      size_t i = 0;
      out[i++] = RESP_CODE_DEVICE_INFO;
      out[i++] = kFirmwareVerCode;
      out[i++] = 1;  // MAX_CONTACTS / 2: just the console contact
      out[i++] = 0;  // no group channels
      memset(&out[i], 0, 4);  // BLE PIN (n/a)
      i += 4;
      memset(&out[i], 0, 12);
      StrHelper::strncpy(static_cast<char*>(static_cast<void*>(&out[i])), FIRMWARE_BUILD_DATE, 12);
      i += 12;
      StrHelper::strzcpy(static_cast<char*>(static_cast<void*>(&out[i])), board.getManufacturerName(), 40);
      i += 40;
      char ver[24];
      snprintf(ver, sizeof(ver), "%s UMC%s", FIRMWARE_VERSION, UMC_VERSION);
      StrHelper::strzcpy(static_cast<char*>(static_cast<void*>(&out[i])), ver, 20);
      i += 20;
      out[i++] = _prefs.disable_fwd ? 0 : 1;
      out[i++] = _prefs.path_hash_mode;
      srv.send(client, out, i);
      return;
    }
    case CMD_APP_START: {
      size_t i = 0;
      out[i++] = RESP_CODE_SELF_INFO;
      out[i++] = ADV_TYPE_REPEATER;
      out[i++] = static_cast<uint8_t>(_prefs.tx_power_dbm);
      out[i++] = MAX_LORA_TX_POWER;
      memcpy(&out[i], self_id.pub_key, PUB_KEY_SIZE);
      i += PUB_KEY_SIZE;
      int32_t lat = static_cast<int32_t>(_prefs.node_lat * 1000000.0);
      int32_t lon = static_cast<int32_t>(_prefs.node_lon * 1000000.0);
      memcpy(&out[i], &lat, 4);
      i += 4;
      memcpy(&out[i], &lon, 4);
      i += 4;
      out[i++] = _prefs.multi_acks;
      out[i++] = _prefs.advert_loc_policy;
      out[i++] = 0;  // telemetry modes
      out[i++] = 1;  // manual add contacts (don't expect auto-added adverts)
      uint32_t freq = static_cast<uint32_t>(_prefs.freq * 1000);
      memcpy(&out[i], &freq, 4);
      i += 4;
      uint32_t bw = static_cast<uint32_t>(_prefs.bw * 1000);
      memcpy(&out[i], &bw, 4);
      i += 4;
      out[i++] = _prefs.sf;
      out[i++] = _prefs.cr;
      size_t nlen = strlen(_prefs.node_name);
      if (i + nlen > sizeof(out)) nlen = sizeof(out) - i;
      memcpy(&out[i], _prefs.node_name, nlen);
      i += nlen;
      srv.send(client, out, i);
      return;
    }
    case CMD_GET_CONTACTS:
    case CMD_GET_CONTACT_BY_KEY: {
      if (c[0] == CMD_GET_CONTACT_BY_KEY && (len < 1 + PUB_KEY_SIZE || !umcIsConsoleKey(&c[1], PUB_KEY_SIZE))) {
        sendErr(ERR_CODE_NOT_FOUND);
        return;
      }
      uint32_t now = getRTCClock()->getCurrentTime();
      if (c[0] == CMD_GET_CONTACTS) {
        out[0] = RESP_CODE_CONTACTS_START;
        uint32_t count = 1;
        memcpy(&out[1], &count, 4);
        srv.send(client, out, 5);
      }
      size_t i = 0;
      out[i++] = RESP_CODE_CONTACT;
      umcConsoleKey(&out[i]);
      i += PUB_KEY_SIZE;
      out[i++] = ADV_TYPE_REPEATER;
      out[i++] = 0;  // flags
      out[i++] = 0;  // out_path_len: direct
      memset(&out[i], 0, MAX_PATH_SIZE);
      i += MAX_PATH_SIZE;
      char name[32];
      snprintf(name, sizeof(name), "%.22s (console)", _prefs.node_name);
      StrHelper::strzcpy(static_cast<char*>(static_cast<void*>(&out[i])), name, 32);
      i += 32;
      memcpy(&out[i], &now, 4);  // last advert
      i += 4;
      int32_t lat = static_cast<int32_t>(_prefs.node_lat * 1000000.0);
      int32_t lon = static_cast<int32_t>(_prefs.node_lon * 1000000.0);
      memcpy(&out[i], &lat, 4);
      i += 4;
      memcpy(&out[i], &lon, 4);
      i += 4;
      memcpy(&out[i], &now, 4);  // lastmod
      i += 4;
      srv.send(client, out, i);
      if (c[0] == CMD_GET_CONTACTS) {
        out[0] = RESP_CODE_END_OF_CONTACTS;
        memcpy(&out[1], &now, 4);
        srv.send(client, out, 5);
      }
      return;
    }
    case CMD_GET_CHANNEL:
      sendErr(ERR_CODE_NOT_FOUND);
      return;
    case CMD_GET_CUSTOM_VARS:
      out[0] = RESP_CODE_CUSTOM_VARS;
      srv.send(client, out, 1);
      return;
    case CMD_SYNC_NEXT_MESSAGE: {
      size_t n = srv.popMessage(client, out);
      if (n == 0) {
        out[0] = RESP_CODE_NO_MORE_MESSAGES;
        n = 1;
      }
      srv.send(client, out, n);
      return;
    }
    case CMD_GET_DEVICE_TIME: {
      out[0] = RESP_CODE_CURR_TIME;
      uint32_t now = getRTCClock()->getCurrentTime();
      memcpy(&out[1], &now, 4);
      srv.send(client, out, 5);
      return;
    }
    case CMD_GET_BATT_AND_STORAGE: {
      size_t i = 0;
      out[i++] = RESP_CODE_BATT_AND_STORAGE;
      uint16_t mv = board.getBattMilliVolts();
      uint32_t used_kb = SPIFFS.usedBytes() / 1024, total_kb = SPIFFS.totalBytes() / 1024;
      memcpy(&out[i], &mv, 2);
      i += 2;
      memcpy(&out[i], &used_kb, 4);
      i += 4;
      memcpy(&out[i], &total_kb, 4);
      i += 4;
      srv.send(client, out, i);
      return;
    }
    case CMD_GET_STATS: {
      if (len < 2) break;
      size_t i = 0;
      out[i++] = RESP_CODE_STATS;
      out[i++] = c[1];
      if (c[1] == kStatsCore) {
        uint16_t mv = board.getBattMilliVolts();
        uint32_t up = static_cast<uint32_t>(uptime_millis / 1000);
        memcpy(&out[i], &mv, 2);
        i += 2;
        memcpy(&out[i], &up, 4);
        i += 4;
        memcpy(&out[i], &_err_flags, 2);
        i += 2;
        out[i++] = static_cast<uint8_t>(_mgr->getOutboundTotal());
      } else if (c[1] == kStatsRadio) {
        int16_t nf = static_cast<int16_t>(_radio->getNoiseFloor());
        memcpy(&out[i], &nf, 2);
        i += 2;
        out[i++] = static_cast<uint8_t>(static_cast<int8_t>(radio_driver.getLastRSSI()));
        out[i++] = static_cast<uint8_t>(static_cast<int8_t>(radio_driver.getLastSNR() * 4.0f));
        uint32_t tx_air = getTotalAirTime() / 1000, rx_air = getReceiveAirTime() / 1000;
        memcpy(&out[i], &tx_air, 4);
        i += 4;
        memcpy(&out[i], &rx_air, 4);
        i += 4;
      } else if (c[1] == kStatsPackets) {
        uint32_t v[7] = {radio_driver.getPacketsRecv(), radio_driver.getPacketsSent(), getNumSentFlood(), getNumSentDirect(),
                         getNumRecvFlood(), getNumRecvDirect(), radio_driver.getPacketsRecvErrors()};
        memcpy(&out[i], v, sizeof(v));
        i += sizeof(v);
      } else {
        sendErr(ERR_CODE_ILLEGAL_ARG);
        return;
      }
      srv.send(client, out, i);
      return;
    }
    case CMD_GET_TUNING_PARAMS: {
      size_t i = 0;
      out[i++] = RESP_CODE_TUNING_PARAMS;
      uint32_t rx = static_cast<uint32_t>(_prefs.rx_delay_base * 1000.0f), af = static_cast<uint32_t>(_prefs.airtime_factor * 1000.0f);
      memcpy(&out[i], &rx, 4);
      i += 4;
      memcpy(&out[i], &af, 4);
      i += 4;
      srv.send(client, out, i);
      return;
    }

    // ---- console contact: login, status, telemetry, binary requests, CLI ----
    case CMD_SEND_LOGIN: {
      if (len < 1 + PUB_KEY_SIZE) break;
      if (!umcIsConsoleKey(&c[1], PUB_KEY_SIZE)) {
        sendErr(ERR_CODE_NOT_FOUND);  // only the console contact exists here
        return;
      }
      char pwd[33];
      size_t plen = len - (1 + PUB_KEY_SIZE);
      if (plen > sizeof(pwd) - 1) plen = sizeof(pwd) - 1;
      memcpy(pwd, &c[1 + PUB_KEY_SIZE], plen);
      pwd[plen] = 0;
      uint32_t tag;
      memcpy(&tag, self_id.pub_key, 4);  // apps match the login push by key prefix
      sendSent(tag);
      bool admin = strcmp(pwd, _prefs.password) == 0;
      bool guest = !admin && strcmp(pwd, _prefs.guest_password) == 0;
      size_t i = 0;
      uint8_t prefix[PUB_KEY_SIZE];
      umcConsoleKey(prefix);
      if (admin || guest) {
        srv.setLogin(client, true, admin);
        out[i++] = PUSH_CODE_LOGIN_SUCCESS;
        out[i++] = admin ? 1 : 0;
        memcpy(&out[i], prefix, 6);
        i += 6;
        uint32_t now = getRTCClock()->getCurrentTime();
        memcpy(&out[i], &now, 4);
        i += 4;
        out[i++] = admin ? PERM_ACL_ADMIN : PERM_ACL_GUEST;
        out[i++] = kFirmwareVerLevel;
        Serial.printf("[UMC] app login (slot %d) as %s\n", client, admin ? "admin" : "guest");
      } else {
        srv.setLogin(client, false, false);
        out[i++] = PUSH_CODE_LOGIN_FAIL;
        out[i++] = 0;
        memcpy(&out[i], prefix, 6);
        i += 6;
      }
      srv.send(client, out, i);
      return;
    }
    case CMD_LOGOUT:
      srv.setLogin(client, false, false);
      sendOk();
      return;
    case CMD_HAS_CONNECTION:
      if (srv.isLoggedIn(client)) sendOk();
      else sendErr(ERR_CODE_NOT_FOUND);
      return;

    case CMD_SEND_STATUS_REQ:
    case CMD_SEND_TELEMETRY_REQ:
    case CMD_SEND_BINARY_REQ: {
      size_t key_off = c[0] == CMD_SEND_TELEMETRY_REQ ? 4 : 1;
      if (len < key_off + PUB_KEY_SIZE) break;
      if (!umcIsConsoleKey(&c[key_off], PUB_KEY_SIZE)) {
        sendErr(ERR_CODE_NOT_FOUND);
        return;
      }
      if (!srv.isLoggedIn(client)) {
        sendErr(ERR_CODE_BAD_STATE);
        return;
      }
      uint32_t tag = getRTCClock()->getCurrentTimeUnique();
      uint8_t req[UmcAppServer::kMaxFrame] = {0};
      size_t req_len;
      if (c[0] == CMD_SEND_STATUS_REQ) {
        req[0] = REQ_GET_STATUS;
        req_len = 5;
        memcpy(&tag, self_id.pub_key, 4);  // legacy matching by key prefix
      } else if (c[0] == CMD_SEND_TELEMETRY_REQ) {
        req[0] = REQ_GET_TELEMETRY;
        req_len = 5;
      } else {
        req_len = len - (1 + PUB_KEY_SIZE);
        if (req_len == 0) break;
        memcpy(req, &c[1 + PUB_KEY_SIZE], req_len);
      }
      sendSent(tag);

      ClientInfo local{};
      local.id = self_id;
      local.permissions = srv.isAdmin(client) ? PERM_ACL_ADMIN : PERM_ACL_GUEST;
      int reply_len = handleRequest(&local, tag, req, req_len);
      if (reply_len <= 4) return;  // not allowed / unknown: the app times out like over LoRa

      uint8_t prefix[PUB_KEY_SIZE];
      umcConsoleKey(prefix);
      size_t i = 0;
      size_t data_len = static_cast<size_t>(reply_len - 4);
      if (c[0] == CMD_SEND_BINARY_REQ) {
        out[i++] = PUSH_CODE_BINARY_RESPONSE;
        out[i++] = 0;
        memcpy(&out[i], &tag, 4);
        i += 4;
      } else {
        out[i++] = c[0] == CMD_SEND_STATUS_REQ ? PUSH_CODE_STATUS_RESPONSE : PUSH_CODE_TELEMETRY_RESPONSE;
        out[i++] = 0;
        memcpy(&out[i], prefix, 6);
        i += 6;
      }
      if (i + data_len > sizeof(out)) data_len = sizeof(out) - i;
      memcpy(&out[i], &reply_data[4], data_len);
      i += data_len;
      srv.send(client, out, i);
      return;
    }

    case CMD_SEND_TXT_MSG: {
      if (len < 14) break;
      uint8_t txt_type = c[1];
      if (!umcIsConsoleKey(&c[7], 6)) {
        sendErr(ERR_CODE_NOT_FOUND);
        return;
      }
      if (txt_type != 1 /* TXT_TYPE_CLI_DATA */ && txt_type != 0 /* TXT_TYPE_PLAIN */) {
        sendErr(ERR_CODE_UNSUPPORTED_CMD);
        return;
      }
      if (!srv.isAdmin(client)) {
        sendErr(ERR_CODE_BAD_STATE);
        return;
      }
      char text[UmcAppServer::kMaxFrame + 1];
      size_t tlen = len - 13;
      memcpy(text, &c[13], tlen);
      text[tlen] = 0;
      sendSent(0);

      char reply[160];
      reply[0] = 0;
      if (strcmp(text, "reboot") == 0) {
        strcpy(reply, "OK - rebooting");
        umc.scheduleReboot(1500);
      } else {
        handleCommand(0, text, reply);
      }
      if (reply[0] == 0) strcpy(reply, "OK");

      uint8_t prefix[PUB_KEY_SIZE];
      umcConsoleKey(prefix);
      size_t i = 0;
      if (srv.appVersion(client) >= 3) {
        out[i++] = RESP_CODE_CONTACT_MSG_RECV_V3;
        out[i++] = 0;  // SNR
        out[i++] = 0;
        out[i++] = 0;
      } else {
        out[i++] = RESP_CODE_CONTACT_MSG_RECV;
      }
      memcpy(&out[i], prefix, 6);
      i += 6;
      out[i++] = 0xFF;  // path_len: direct
      out[i++] = 1;     // TXT_TYPE_CLI_DATA
      uint32_t ts = getRTCClock()->getCurrentTimeUnique();
      memcpy(&out[i], &ts, 4);
      i += 4;
      size_t rlen = strlen(reply);
      if (i + rlen > sizeof(out)) rlen = sizeof(out) - i;
      memcpy(&out[i], reply, rlen);
      i += rlen;
      srv.queueMessage(client, out, i);
      return;
    }

    // ---- native settings (admin only) ----
    case CMD_SET_DEVICE_TIME: {
      if (len < 5 || !needAdmin()) return;
      uint32_t secs;
      memcpy(&secs, &c[1], 4);
      getRTCClock()->setCurrentTime(secs);
      sendOk();
      return;
    }
    case CMD_SEND_SELF_ADVERT: {
      if (!needAdmin()) return;
      mesh::Packet* pkt = createSelfAdvert();
      if (pkt == nullptr) {
        sendErr(ERR_CODE_TABLE_FULL);
        return;
      }
      if (len >= 2 && c[1] == 1) sendFlood(pkt, 0, static_cast<uint8_t>(_prefs.path_hash_mode + 1));
      else sendZeroHop(pkt);
      sendOk();
      return;
    }
    case CMD_SET_ADVERT_NAME: {
      if (len < 2 || !needAdmin()) return;
      size_t n = len - 1;
      if (n > sizeof(_prefs.node_name) - 1) n = sizeof(_prefs.node_name) - 1;
      memcpy(_prefs.node_name, &c[1], n);
      _prefs.node_name[n] = 0;
      savePrefs();
      sendOk();
      return;
    }
    case CMD_SET_ADVERT_LATLON: {
      if (len < 9 || !needAdmin()) return;
      int32_t lat, lon;
      memcpy(&lat, &c[1], 4);
      memcpy(&lon, &c[5], 4);
      if (lat > 90000000 || lat < -90000000 || lon > 180000000 || lon < -180000000) {
        sendErr(ERR_CODE_ILLEGAL_ARG);
        return;
      }
      _prefs.node_lat = lat / 1000000.0;
      _prefs.node_lon = lon / 1000000.0;
      savePrefs();
      sendOk();
      return;
    }
    case CMD_SET_RADIO_PARAMS: {
      if (len < 11 || !needAdmin()) return;
      uint32_t freq, bw;
      memcpy(&freq, &c[1], 4);
      memcpy(&bw, &c[5], 4);
      uint8_t sf = c[9], cr = c[10];
      if (freq < 300000 || freq > 2500000 || sf < 5 || sf > 12 || cr < 5 || cr > 8 || bw < 7000 || bw > 500000) {
        sendErr(ERR_CODE_ILLEGAL_ARG);
        return;
      }
      _prefs.freq = freq / 1000.0f;
      _prefs.bw = bw / 1000.0f;
      _prefs.sf = sf;
      _prefs.cr = cr;
      savePrefs();
      radio_driver.setParams(_prefs.freq, _prefs.bw, _prefs.sf, _prefs.cr);
      sendOk();
      return;
    }
    case CMD_SET_RADIO_TX_POWER: {
      if (len < 2 || !needAdmin()) return;
      int8_t p = static_cast<int8_t>(c[1]);
      if (p < -9 || p > MAX_LORA_TX_POWER) {
        sendErr(ERR_CODE_ILLEGAL_ARG);
        return;
      }
      _prefs.tx_power_dbm = p;
      savePrefs();
      radio_driver.setTxPower(p);
      sendOk();
      return;
    }
    case CMD_SET_TUNING_PARAMS: {
      if (len < 9 || !needAdmin()) return;
      uint32_t rx, af;
      memcpy(&rx, &c[1], 4);
      memcpy(&af, &c[5], 4);
      if (af > 9000) {
        sendErr(ERR_CODE_ILLEGAL_ARG);
        return;
      }
      _prefs.rx_delay_base = rx / 1000.0f;
      _prefs.airtime_factor = af / 1000.0f;
      savePrefs();
      sendOk();
      return;
    }
    case CMD_SET_OTHER_PARAMS:
      if (!needAdmin()) return;
      if (len >= 4) _prefs.advert_loc_policy = c[3];
      if (len >= 5) _prefs.multi_acks = c[4];
      savePrefs();
      sendOk();
      return;
    case CMD_SET_PATH_HASH_MODE:
      if (len < 3 || !needAdmin()) return;
      if (c[2] > 2) {
        sendErr(ERR_CODE_ILLEGAL_ARG);
        return;
      }
      _prefs.path_hash_mode = c[2];
      savePrefs();
      sendOk();
      return;
    case CMD_REBOOT:
      if (!needAdmin()) return;
      sendOk();
      umc.scheduleReboot(1500);
      return;
    default:
      break;
  }
  sendErr(ERR_CODE_UNSUPPORTED_CMD);
}

#endif  // UMC_BUILD
