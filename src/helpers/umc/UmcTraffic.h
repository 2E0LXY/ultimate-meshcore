#pragma once

#include <Arduino.h>
#include <Packet.h>
#include <string.h>
#include <helpers/AdvertDataHelpers.h>

// Small ring buffer of recent packets for the OLED traffic screen, `get traffic`
// and the web UI. Written from the mesh loop only.
class UmcTraffic {
public:
  static constexpr int kSize = 16;

  struct Entry {
    uint32_t ms;
    int16_t rssi;
    int8_t snr4;       // SNR * 4
    uint8_t type;      // PAYLOAD_TYPE_*
    uint8_t hops;      // path length (hash count) when received
    uint8_t len;
    bool tx;
    bool flood;
    // Who it concerns, where the packet says (nothing here is decrypted):
    //  adverts carry the sender's key and name; requests, responses, messages and paths carry the
    //  one-byte hashes of the destination and the sender; channel packets the channel's hash; and
    //  `via` is the repeater that handed it to us (the last hash in its path).
    uint8_t flags;     // F_* below
    uint8_t src, dst, via, chan;
    uint8_t key[4];    // first bytes of the advertiser's public key
    char name[13];     // advertiser's name, cut to 12 characters
  };
  static constexpr uint8_t F_ENDS = 1, F_VIA = 2, F_CHAN = 4, F_KEY = 8;

  void add(const mesh::Packet* pkt, int len, bool tx, float rssi, float snr) {
    Entry& e = _entries[_head];
    e.ms = millis();
    e.rssi = static_cast<int16_t>(rssi);
    e.snr4 = static_cast<int8_t>(constrain(snr * 4.0f, -128.0f, 127.0f));
    e.type = pkt->getPayloadType();
    e.hops = pkt->getPathHashCount();
    e.len = static_cast<uint8_t>(len > 255 ? 255 : len);
    e.tx = tx;
    e.flood = pkt->isRouteFlood();
    e.flags = 0;
    e.src = e.dst = e.via = e.chan = 0;
    e.name[0] = 0;
    const uint8_t type = e.type;
    constexpr int kAdvertHead = PUB_KEY_SIZE + 4 + SIGNATURE_SIZE;
    if (type == PAYLOAD_TYPE_ADVERT && pkt->payload_len > kAdvertHead) {
      memcpy(e.key, pkt->payload, 4);
      e.flags |= F_KEY;
      const int app_len = pkt->payload_len - kAdvertHead;
      if (app_len > 0 && app_len <= MAX_ADVERT_DATA_SIZE) {
        AdvertDataParser parser(&pkt->payload[kAdvertHead], static_cast<uint8_t>(app_len));
        if (parser.isValid() && parser.hasName()) {
          strncpy(e.name, parser.getName(), sizeof(e.name) - 1);
          e.name[sizeof(e.name) - 1] = 0;
        }
      }
    } else if ((type == PAYLOAD_TYPE_REQ || type == PAYLOAD_TYPE_RESPONSE || type == PAYLOAD_TYPE_TXT_MSG ||
                type == PAYLOAD_TYPE_PATH) && pkt->payload_len >= 2) {
      e.dst = pkt->payload[0];
      e.src = pkt->payload[1];
      e.flags |= F_ENDS;
    } else if ((type == PAYLOAD_TYPE_GRP_TXT || type == PAYLOAD_TYPE_GRP_DATA) && pkt->payload_len >= 1) {
      e.chan = pkt->payload[0];
      e.flags |= F_CHAN;
    }
    if (pkt->getPathHashCount() > 0) {
      e.via = pkt->path[(pkt->getPathHashCount() - 1) * pkt->getPathHashSize()];
      e.flags |= F_VIA;
    }
    _head = (_head + 1) % kSize;
    if (_count < kSize) _count++;
    if (tx) _tx_total++; else _rx_total++;
  }

  int count() const { return _count; }
  uint32_t rxTotal() const { return _rx_total; }
  uint32_t txTotal() const { return _tx_total; }

  // i = 0 is the most recent entry
  const Entry* get(int i) const {
    if (i < 0 || i >= _count) return nullptr;
    return &_entries[(_head - 1 - i + kSize) % kSize];
  }

  // packets in the last window_ms
  int countSince(uint32_t window_ms, bool tx) const {
    int n = 0;
    uint32_t now = millis();
    for (int i = 0; i < _count; i++) {
      const Entry* e = get(i);
      if (now - e->ms > window_ms) break;
      if (e->tx == tx) n++;
    }
    return n;
  }

  static const char* typeName(uint8_t type) {
    switch (type) {
      case PAYLOAD_TYPE_REQ: return "REQ";
      case PAYLOAD_TYPE_RESPONSE: return "RESP";
      case PAYLOAD_TYPE_TXT_MSG: return "MSG";
      case PAYLOAD_TYPE_ACK: return "ACK";
      case PAYLOAD_TYPE_ADVERT: return "ADVERT";
      case PAYLOAD_TYPE_GRP_TXT: return "CHAN";
      case PAYLOAD_TYPE_GRP_DATA: return "CHDATA";
      case PAYLOAD_TYPE_ANON_REQ: return "ANON";
      case PAYLOAD_TYPE_PATH: return "PATH";
      case PAYLOAD_TYPE_TRACE: return "TRACE";
      case PAYLOAD_TYPE_MULTIPART: return "MULTI";
      case PAYLOAD_TYPE_CONTROL: return "CTRL";
      case PAYLOAD_TYPE_RAW_CUSTOM: return "RAW";
      default: return "?";
    }
  }

  // "RX CHAN F h3 -97/6.2" style line (max ~21 chars for a 128px OLED)
  static void formatShort(const Entry& e, char* out, size_t n) {
    if (e.tx) {
      snprintf(out, n, "TX %-6s %s", typeName(e.type), e.flood ? "flood" : "direct");
    } else {
      snprintf(out, n, "RX %-6s%c%d %d/%.0f", typeName(e.type), e.flood ? 'F' : 'D', e.hops, e.rssi, e.snr4 / 4.0f);
    }
  }

private:
  Entry _entries[kSize] = {};
  int _head = 0;
  int _count = 0;
  uint32_t _rx_total = 0;
  uint32_t _tx_total = 0;
};

extern UmcTraffic umc_traffic;
