#pragma once

#include <stddef.h>
#include <stdint.h>

// Long-term health of one device: how often it has restarted and why, how long it has run in
// total, and how much traffic it has carried - all kept across reboots in flash. Together with
// a short log of things that went wrong (watchdog recoveries, abnormal restarts) it answers
// "has this repeater been behaving?" without a serial cable.
//
//   stats-life [clear]            boots, crashes, total uptime, packets
//   safety log [N] | tail | clear | state
//
// The counters are saved every ten minutes, so a power cut loses at most that much.
class UmcHealth {
public:
  void begin();
  // Call often. rx / tx are the packets carried since this boot.
  void loop(unsigned long now_ms, uint32_t rx, uint32_t tx);
  // True when the command was one of ours; the answer is in reply.
  bool command(const char* command, char* reply, size_t reply_size);
  // Add a line to the safety log.
  void note(const char* text);
  // The clock, when known, so log lines can carry a date (0 = unknown).
  void setEpoch(uint32_t epoch) { _epoch = epoch; }

private:
  void load();
  void save(uint32_t rx, uint32_t tx);
  void appendLog(const char* text);
  void readLog(char* out, size_t out_size);
  void breadcrumb(unsigned long now_ms);

  bool _begun = false;
  uint32_t _epoch = 0;
  unsigned long _last_save = 0, _last_crumb = 0;
  // lifetime totals as they stood when this boot began
  uint32_t _boots = 0, _crashes = 0, _first_epoch = 0, _longest = 0;
  uint32_t _base_uptime = 0, _base_rx = 0, _base_tx = 0;
  uint32_t _saved_run_up = 0;
  uint32_t _last_rx = 0, _last_tx = 0;
  char _reason[24] = "";
};

extern UmcHealth umc_health;

// Lets the radio driver (which knows nothing about UMC) report an event.
extern "C" void umc_health_note(const char* text);
