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
  uint8_t touch_map;           // touch panel orientation on touch clients (0-7)
  uint8_t theme;               // colour scheme on screens that have one
  char admin_pw[33];           // web/telnet password on roles without a mesh admin password (companion)

  // ---- touch client extras ----
  char quick[6][40];           // canned replies, sent from the message composer
  bool lock_enabled;           // ask for a hold-to-unlock before the screen can be used
  bool clock_12h;              // show times as am/pm rather than 24 hour
  bool units_miles;            // distances in miles instead of kilometres
  bool beep_on_msg;            // a short tone when a message arrives
  bool flash_on_msg;           // the screen flashes when a message arrives
  // How much a sent message says about where it got to:
  //   0 off, 1 a coloured mark, 2 the mark plus the count of acks or relays
  uint8_t ack_display;
  // Regions this node knows about, as the mesh's own naming rules allow: up to 29 bytes of
  // lowercase letters, digits and hyphens. The first is used when a channel has no scope
  // of its own. Communities agree these between themselves, so they are typed in, not
  // built in.
  char regions[8][30];
  // Region scope per channel, as "#yorkshire=yorkshire;#northeast=eng-ne". A channel not
  // listed uses the default scope. This is how the community guides ask channels to be
  // set up - one region per channel, not one for everything.
  char ch_scopes[160];
};

#define UMC_QUICK_REPLIES 6
#define UMC_MAX_REGIONS 8

class UmcPrefsStore {
public:
  static void setDefaults(UmcPrefs& p);
  static void load(UmcPrefs& p);   // generates a PIN on first boot
  static bool save(const UmcPrefs& p);
  static bool erase();             // wipe the whole "umc" namespace
  static bool isValidPin(const char* pin);
};
