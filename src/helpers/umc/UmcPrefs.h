#pragma once

#include <stdint.h>

// UMC service settings. Stored as individual NVS keys (namespace "umc") so new
// settings can be added without any struct-layout migration.
struct UmcPrefs {
  bool setup_done;
  bool http_enabled;
  uint16_t http_port;
  bool telnet_enabled;
  uint16_t telnet_port;
  uint16_t session_timeout_min;
  char pin[9];                 // 8 digits; used as setup/rescue AP password and BLE PIN
  bool ble_enabled;
  uint16_t ble_idle_off_min;   // 0 = never auto-off
  uint8_t display_mode;        // 0 = cycle pages, 1 = status page only, 2 = off (button wakes)
  uint16_t display_timeout_s;  // 0 = never blank
  uint8_t display_ip_s;        // seconds the flashing IP screen shows each cycle
  uint8_t display_page_s;      // seconds per settings page
  uint16_t display_traffic_s;  // seconds on the live traffic screen
  uint8_t group_hops_max;      // flood hop limit for channel (group) messages, 64 = no extra limit
  bool app_tcp;                // MeshCore app connection on TCP
  uint16_t app_tcp_port;       // default 5000
  char admin_pw[33];           // web/telnet password on roles without a mesh admin password (companion)
};

class UmcPrefsStore {
public:
  static void setDefaults(UmcPrefs& p);
  static void load(UmcPrefs& p);   // generates a PIN on first boot
  static bool save(const UmcPrefs& p);
  static bool erase();             // wipe the whole "umc" namespace
  static bool isValidPin(const char* pin);
};
