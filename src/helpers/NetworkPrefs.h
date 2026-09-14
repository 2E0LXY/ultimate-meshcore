#pragma once

#include <helpers/IdentityStore.h>
#include <stdint.h>

// IMPORTANT: persisted to NVS and LittleFS as a raw byte blob. To keep saved
// WiFi credentials across firmware updates, ONLY ever APPEND new fields to the
// end of this struct, and never reorder, resize, or remove existing fields or
// change `magic`. The loaders copy the overlapping prefix, so appended fields
// load as zero on older saves and are then filled in by the *Defaults helpers.
struct NetworkPrefs {
  uint32_t magic;
  uint8_t wifi_powersave;
  uint8_t wifi_channel;
  uint8_t reserved[2];
  char wifi_ssid[33];
  char wifi_pwd[65];
  char ntp_server1[64];
  char ntp_server2[64];
  char ntp_server3[64];
  // ---- UMC (Ultimate MeshCore) additions, appended ----
  uint32_t umc_magic;          // kUmcMagic once the UMC fields below are initialised
  char wifi_ssid2[33];
  char wifi_pwd2[65];
  char wifi_ssid3[33];
  char wifi_pwd3[65];
  uint8_t ip_static;           // 0 = DHCP, 1 = static
  uint8_t ap_mode;             // 0 = auto (setup + rescue), 1 = always on, 2 = never
  uint8_t wifi_mode;           // 0 = always, 1 = off
  uint8_t mdns_enabled;        // 1 = advertise <hostname>.local
  uint32_t ip_addr, ip_mask, ip_gw, ip_dns;  // network byte order (IPAddress raw)
  char hostname[33];           // empty = derived from node name
  char ap_password[65];        // empty = derived from device PIN
  char timezone[48];           // POSIX TZ string, e.g. "GMT0BST,M3.5.0/1,M10.5.0"
  uint16_t ap_rescue_secs;     // STA failure time before rescue AP (default 60)
  uint16_t reserved_umc;
};

class NetworkPrefsStore {
public:
  static void setDefaults(NetworkPrefs& prefs);
  static bool load(FILESYSTEM* fs, NetworkPrefs& prefs,
                   uint8_t legacy_wifi_powersave = 0,
                   const char* legacy_wifi_ssid = nullptr,
                   const char* legacy_wifi_pwd = nullptr);
  static bool save(FILESYSTEM* fs, const NetworkPrefs& prefs);
  static constexpr uint32_t magicValue() { return kMagic; }
  static constexpr uint32_t kUmcMagic = 0x554D4331;  // "UMC1"
  static void applyUmcDefaults(NetworkPrefs& prefs);

private:
  static constexpr uint32_t kMagic = 0x4E455450;
  static constexpr const char* kFilename = "/network_prefs";
};
