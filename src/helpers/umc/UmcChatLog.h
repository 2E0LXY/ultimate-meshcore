#pragma once

#include <Arduino.h>
#include <string.h>

// Recent messages kept on the device so a screen (T-Deck touch UI) can show conversations.
// Apps and the browser keep their own history; this is only what the device itself displays,
// so it is a small ring buffer that never touches flash.
#ifndef UMC_CHATLOG_SIZE
  #define UMC_CHATLOG_SIZE 60
#endif
#ifndef UMC_CHATLOG_TEXT
  #define UMC_CHATLOG_TEXT 140
#endif

class UmcChatLog {
public:
  static constexpr int kMax = UMC_CHATLOG_SIZE;

  struct Entry {
    uint8_t key[6];      // contact public-key prefix (direct messages)
    uint8_t channel;     // channel index, 0xFF = direct message
    bool outgoing;
    bool cli;            // reply from a remote admin command
    // Our own direct messages carry the ACK hash the recipient will send back, so the
    // screen can say whether one arrived. 0 means nothing is expected (a channel message,
    // or one sent without an ACK); delivered is set when that hash comes back.
    uint32_t expect_ack;
    bool delivered;
    uint8_t relays;      // channel messages: how many repeaters were heard passing it on
    uint32_t sent_ms;    // when it went out, so a silent message can be called failed
    int8_t snr4;
    uint8_t hops;        // 0xFF = arrived by flood
    uint32_t epoch;      // sender timestamp
    unsigned long ms;
    char from[24];       // sender name (channels and room servers)
    char text[UMC_CHATLOG_TEXT];
  };

  void addDirect(const uint8_t* key_prefix, const char* from, const char* text, uint32_t epoch, bool outgoing, int8_t snr4 = 0,
                 uint8_t hops = 0xFF, bool cli = false) {
    Entry& e = next();
    memcpy(e.key, key_prefix, 6);
    e.channel = 0xFF;
    fill(e, from, text, epoch, outgoing, snr4, hops, cli);
  }

  void addChannel(uint8_t channel, const char* from, const char* text, uint32_t epoch, bool outgoing, int8_t snr4 = 0,
                  uint8_t hops = 0xFF) {
    Entry& e = next();
    memset(e.key, 0, sizeof(e.key));
    e.channel = channel;
    fill(e, from, text, epoch, outgoing, snr4, hops, false);
  }

  int count() const { return _count; }
  uint32_t revision() const { return _rev; }  // changes whenever something is added

  // idx 0 = oldest kept message
  const Entry* get(int idx) const {
    if (idx < 0 || idx >= _count) return nullptr;
    return &_ring[(_head - _count + idx + kMax) % kMax];
  }

  bool isDirect(const Entry& e, const uint8_t* key_prefix) const {
    return e.channel == 0xFF && memcmp(e.key, key_prefix, 6) == 0;
  }

  int unread() const { return _unread; }

  // Marks the newest message still waiting on this ACK hash as delivered. Returns true if
  // one was found, so the screen knows to redraw.
  bool markDelivered(uint32_t ack) {
    if (ack == 0) return false;
    for (int i = _count - 1; i >= 0; i--) {
      Entry& e = _ring[(_head - _count + i + kMax * 2) % kMax];
      if (e.outgoing && !e.delivered && e.expect_ack == ack) {
        e.delivered = true;
        _rev++;
        return true;
      }
    }
    return false;
  }

  // Our own most recent message, for attaching the ACK hash once it is known.
  Entry* newestOutgoing() {
    for (int i = _count - 1; i >= 0; i--) {
      Entry& e = _ring[(_head - _count + i + kMax * 2) % kMax];
      if (e.outgoing) return &e;
    }
    return NULL;
  }

  // Counts another repeater heard passing one of our channel messages on.
  bool countRelay(uint32_t epoch) {
    for (int i = _count - 1; i >= 0; i--) {
      Entry& e = _ring[(_head - _count + i + kMax * 2) % kMax];
      if (e.outgoing && e.epoch == epoch && e.relays < 255) {
        e.relays++;
        _rev++;
        return true;
      }
    }
    return false;
  }
  void markRead() { _unread = 0; }

private:
  Entry& next() {
    Entry& e = _ring[_head];
    _head = (_head + 1) % kMax;
    if (_count < kMax) _count++;
    _rev++;
    return e;
  }
  void fill(Entry& e, const char* from, const char* text, uint32_t epoch, bool outgoing, int8_t snr4, uint8_t hops, bool cli) {
    e.expect_ack = 0;
    e.delivered = false;
    e.relays = 0;
    e.sent_ms = millis();
    e.outgoing = outgoing;
    e.cli = cli;
    e.snr4 = snr4;
    e.hops = hops;
    e.epoch = epoch;
    e.ms = millis();
    strncpy(e.from, from ? from : "", sizeof(e.from) - 1);
    e.from[sizeof(e.from) - 1] = 0;
    strncpy(e.text, text ? text : "", sizeof(e.text) - 1);
    e.text[sizeof(e.text) - 1] = 0;
    if (!outgoing) _unread++;
  }

  Entry _ring[kMax] = {};
  int _head = 0, _count = 0, _unread = 0;
  uint32_t _rev = 0;
};

extern UmcChatLog umc_chatlog;
