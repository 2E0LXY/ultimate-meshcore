#pragma once

#include <Arduino.h>
#include <helpers/BaseChatMesh.h>
#include <helpers/umc/UmcRepeaterTap.h>
#include <string.h>

// Everything the repeater page knows about the repeater it is open on: whether we are logged in,
// the last status it sent, what it answered to commands, and the last trace. The companion calls
// the three callbacks when a reply arrives; the screen reads the fields and draws them.
class RepeaterAdmin : public UmcRepeaterTap {
public:
  // What a repeater sends back for a status request (the same layout as the repeater's own struct).
  struct Stats {
    uint16_t batt_milli_volts;
    uint16_t curr_tx_queue_len;
    int16_t noise_floor;
    int16_t last_rssi;
    uint32_t n_packets_recv;
    uint32_t n_packets_sent;
    uint32_t total_air_time_secs;
    uint32_t total_up_time_secs;
    uint32_t n_sent_flood, n_sent_direct;
    uint32_t n_recv_flood, n_recv_direct;
    uint16_t err_events;
    int16_t last_snr;  // x 4
    uint16_t n_direct_dups, n_flood_dups;
    uint32_t total_rx_air_time_secs;
    uint32_t n_recv_errors;
  };

  enum Login : uint8_t { LG_NONE = 0, LG_SENT, LG_OK, LG_FAIL };

  bool active = false;                  // a repeater page is open: replies for it are ours
  uint8_t key[PUB_KEY_SIZE] = {0};
  uint32_t rev = 0;                     // changes whenever anything the screen shows changes

  Login login = LG_NONE;
  uint8_t role = 0;                     // 0 guest, 1 read-only, 2 read-write, 3 admin
  unsigned long login_deadline = 0;

  bool have_status = false;
  bool status_tried = false;            // asked once since logging in
  bool status_wait = false;
  uint32_t status_tag = 0;
  unsigned long status_deadline = 0, status_at = 0;
  Stats st;

  char out[420] = {0};                  // commands typed and what the repeater said, oldest first
  int out_len = 0;
  bool cli_wait = false;
  unsigned long cli_deadline = 0;

  bool trace_wait = false, trace_have = false, trace_final = false;
  uint32_t trace_tag = 0;
  unsigned long trace_deadline = 0, trace_sent = 0, trace_took_ms = 0;
  int trace_n = 0, trace_hsz = 1;
  uint8_t trace_hash[48] = {0};
  int8_t trace_snr4[16] = {0};
  int8_t trace_final4 = 0;

  char note[72] = {0};                  // one line for the screen: "no answer", "wrong password" ...

  RepeaterAdmin() { memset(&st, 0, sizeof(st)); }

  void say(const char* s) {
    strncpy(note, s, sizeof(note) - 1);
    note[sizeof(note) - 1] = 0;
    rev++;
  }

  void open(const ContactInfo& c) {
    if (memcmp(key, c.id.pub_key, PUB_KEY_SIZE) != 0) {   // a different repeater: start clean
      reset();
      memcpy(key, c.id.pub_key, PUB_KEY_SIZE);
    }
    active = true;
    rev++;
  }

  void close() {
    active = false;
    status_wait = cli_wait = trace_wait = false;
    rev++;
  }

  void reset() {
    login = LG_NONE;
    role = 0;
    have_status = status_tried = status_wait = false;
    out[0] = 0;
    out_len = 0;
    cli_wait = false;
    trace_wait = trace_have = false;
    note[0] = 0;
    rev++;
  }

  bool isFor(const ContactInfo& c) const { return active && memcmp(c.id.pub_key, key, PUB_KEY_SIZE) == 0; }
  bool waiting() const { return login == LG_SENT || status_wait || cli_wait || trace_wait; }

  static unsigned long deadlineFor(unsigned long est) {
    unsigned long wait = est + 8000;
    return millis() + (wait < 15000 ? 15000 : wait);
  }
  void loginSent(unsigned long est) {
    login = LG_SENT;
    login_deadline = deadlineFor(est);
    status_tried = false;
    have_status = false;
    note[0] = 0;
    rev++;
  }
  void statusSent(uint32_t tag, unsigned long est) {
    status_wait = true;
    status_tag = tag;
    status_deadline = deadlineFor(est);
    rev++;
  }
  void commandSent(const char* cmd, unsigned long est) {
    cli_wait = true;
    cli_deadline = deadlineFor(est);
    append("> ");
    append(cmd);
    append("\n");
  }
  void traceSent(uint32_t tag, unsigned long est) {
    trace_wait = true;
    trace_have = false;
    trace_tag = tag;
    trace_sent = millis();
    trace_deadline = deadlineFor(est * 2);
    rev++;
  }

  void append(const char* s) {
    const int n = strlen(s);
    if (n >= (int)sizeof(out) - 1) return;
    if (out_len + n >= (int)sizeof(out) - 1) {          // full: drop the oldest half
      const int drop = out_len / 2;
      memmove(out, out + drop, out_len - drop + 1);
      out_len -= drop;
    }
    memcpy(out + out_len, s, n + 1);
    out_len += n;
    rev++;
  }

  // call often: gives up on anything that has not been answered in time
  void tick(unsigned long now) {
    if (login == LG_SENT && (long)(now - login_deadline) > 0) {
      login = LG_FAIL;
      say("No answer from the repeater (out of range?)");
    }
    if (status_wait && (long)(now - status_deadline) > 0) {
      status_wait = false;
      say("No status reply");
    }
    if (cli_wait && (long)(now - cli_deadline) > 0) {
      cli_wait = false;
      append("(no reply)\n");
    }
    if (trace_wait && (long)(now - trace_deadline) > 0) {
      trace_wait = false;
      say("Trace timed out - a hop may be out of range");
    }
  }

  // ---- replies from the companion ----
  bool onContactResponse(const ContactInfo& from, const uint8_t* data, uint8_t len) override {
    if (!isFor(from) || len < 5) return false;
    uint32_t tag;
    memcpy(&tag, data, 4);
    if (login == LG_SENT) {
      if (len >= 6 && memcmp(&data[4], "OK", 2) == 0) {                // older repeaters
        login = LG_OK;
        role = 0;
      } else if (len >= 8 && data[4] == RESP_SERVER_LOGIN_OK) {
        login = LG_OK;
        role = data[6] & 3;
      } else {
        login = LG_FAIL;
        say("Login refused - wrong password?");
      }
      note[0] = login == LG_OK ? 0 : note[0];
      rev++;
      return true;
    }
    if (status_wait && (tag == status_tag || len >= 4 + 40)) {
      const int n = len - 4;
      memset(&st, 0, sizeof(st));
      memcpy(&st, data + 4, n < (int)sizeof(st) ? n : (int)sizeof(st));
      have_status = true;
      status_wait = false;
      status_at = millis();
      note[0] = 0;
      rev++;
      return true;
    }
    return false;
  }

  bool onCommandReply(const ContactInfo& from, const char* text) override {
    if (!isFor(from)) return false;
    cli_wait = false;
    append(text);
    append("\n");
    return true;
  }

  bool onTrace(uint32_t tag, const uint8_t* hashes, const uint8_t* snrs, uint8_t path_len, uint8_t flags,
               int8_t final_snr_x4) override {
    if (!trace_wait || tag != trace_tag) return false;
    const int sz = flags & 3;
    const int hsz = 1 << sz;
    int n = path_len >> sz;
    if (n > 16) n = 16;
    if (n * hsz > (int)sizeof(trace_hash)) n = sizeof(trace_hash) / hsz;
    trace_hsz = hsz;
    trace_n = n;
    memcpy(trace_hash, hashes, n * hsz);
    memcpy(trace_snr4, snrs, n);
    trace_final4 = final_snr_x4;
    trace_final = true;
    trace_have = true;
    trace_wait = false;
    trace_took_ms = millis() - trace_sent;
    note[0] = 0;
    rev++;
    return true;
  }
};
