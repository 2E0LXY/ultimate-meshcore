#include "NetworkPrefs.h"

#include <helpers/TxtDataHelpers.h>
#include <string.h>

#if defined(ESP_PLATFORM)
  #include <Preferences.h>
#endif

namespace {

#ifndef DEFAULT_NTP_SERVER1
  #ifdef UMC_BUILD
    #define DEFAULT_NTP_SERVER1 "uk.pool.ntp.org"
  #else
    #define DEFAULT_NTP_SERVER1 "au.pool.ntp.org"
  #endif
#endif
#ifndef DEFAULT_NTP_SERVER2
  #define DEFAULT_NTP_SERVER2 "time.cloudflare.com"
#endif
#ifndef DEFAULT_NTP_SERVER3
  #define DEFAULT_NTP_SERVER3 "time.google.com"
#endif
#ifndef UMC_DEFAULT_TIMEZONE
  #define UMC_DEFAULT_TIMEZONE "GMT0BST,M3.5.0/1,M10.5.0"  // Europe/London
#endif

constexpr const char* kDefaultNtpServer1 = DEFAULT_NTP_SERVER1;
constexpr const char* kDefaultNtpServer2 = DEFAULT_NTP_SERVER2;
constexpr const char* kDefaultNtpServer3 = DEFAULT_NTP_SERVER3;

struct LegacyWebPrefsV1 {
  uint32_t magic;
  uint8_t web_enabled;
  uint8_t web_stats_enabled;
  uint8_t wifi_powersave;
  uint8_t reserved;
  char wifi_ssid[33];
  char wifi_pwd[65];
};

bool loadLegacyWebWifiPrefs(FILESYSTEM* fs, NetworkPrefs& prefs) {
  if (fs == nullptr || !fs->exists("/web_prefs")) {
    return false;
  }

#if defined(RP2040_PLATFORM)
  File file = fs->open("/web_prefs", "r");
#else
  File file = fs->open("/web_prefs");
#endif
  if (!file) {
    return false;
  }

  if (static_cast<size_t>(file.size()) < sizeof(LegacyWebPrefsV1)) {
    file.close();
    return false;
  }

  LegacyWebPrefsV1 legacy{};
  bool ok = file.read(reinterpret_cast<uint8_t*>(&legacy), sizeof(legacy)) == sizeof(legacy);
  file.close();
  if (!ok || legacy.magic != 0x57454250) {
    return false;
  }

  prefs.wifi_powersave = legacy.wifi_powersave <= 2 ? legacy.wifi_powersave : 0;
  StrHelper::strncpy(prefs.wifi_ssid, legacy.wifi_ssid, sizeof(prefs.wifi_ssid));
  StrHelper::strncpy(prefs.wifi_pwd, legacy.wifi_pwd, sizeof(prefs.wifi_pwd));
  return true;
}

#if defined(ESP_PLATFORM)
// Upper bound on the stored blob we are willing to read. NetworkPrefs only ever
// grows by APPENDING fields (see NetworkPrefs.h), so this just needs headroom
// above the current struct size to guard against corruption.
static constexpr size_t kNetworkPrefsMaxBlob = 1024;

bool loadNvsNetworkPrefs(NetworkPrefs& prefs) {
  static_assert(sizeof(NetworkPrefs) <= kNetworkPrefsMaxBlob,
                "NetworkPrefs grew past kNetworkPrefsMaxBlob");
  Preferences nvs;
  if (!nvs.begin("eastmesh-net", true)) {
    return false;
  }
  // Tolerate the struct having grown or shrunk between firmware versions instead
  // of rejecting on an exact size match (which silently wiped WiFi creds across
  // any layout change). Read whatever blob is stored, then copy the overlapping
  // prefix into a zero-initialised struct: appended fields stay zero (and get
  // defaulted by the caller), trailing bytes from a newer layout are ignored.
  const size_t blob_len = nvs.getBytesLength("prefs");
  if (blob_len < sizeof(prefs.magic) || blob_len > kNetworkPrefsMaxBlob) {
    nvs.end();
    return false;
  }
  uint8_t buf[kNetworkPrefsMaxBlob];
  memset(buf, 0, sizeof(buf));
  const size_t read = nvs.getBytes("prefs", buf, blob_len);
  nvs.end();
  if (read != blob_len) {
    return false;
  }
  NetworkPrefs stored{};
  const size_t copy_len = blob_len < sizeof(stored) ? blob_len : sizeof(stored);
  memcpy(&stored, buf, copy_len);
  if (stored.magic != NetworkPrefsStore::magicValue()) {
    return false;
  }
  prefs = stored;
  return true;
}

bool saveNvsNetworkPrefs(const NetworkPrefs& prefs) {
  Preferences nvs;
  if (!nvs.begin("eastmesh-net", false)) {
    return false;
  }
  const size_t written = nvs.putBytes("prefs", &prefs, sizeof(prefs));
  nvs.end();
  return written == sizeof(prefs);
}
#else
bool loadNvsNetworkPrefs(NetworkPrefs&) {
  return false;
}

bool saveNvsNetworkPrefs(const NetworkPrefs&) {
  return true;
}
#endif

void applyNtpDefaults(NetworkPrefs& prefs) {
  if (prefs.ntp_server1[0] == 0) {
    StrHelper::strncpy(prefs.ntp_server1, kDefaultNtpServer1, sizeof(prefs.ntp_server1));
  }
  if (prefs.ntp_server2[0] == 0) {
    StrHelper::strncpy(prefs.ntp_server2, kDefaultNtpServer2, sizeof(prefs.ntp_server2));
  }
  if (prefs.ntp_server3[0] == 0) {
    StrHelper::strncpy(prefs.ntp_server3, kDefaultNtpServer3, sizeof(prefs.ntp_server3));
  }
  // Every load path funnels through here, so UMC fields get initialised on upgrade too.
  NetworkPrefsStore::applyUmcDefaults(prefs);
}

}  // namespace

void NetworkPrefsStore::applyUmcDefaults(NetworkPrefs& prefs) {
  if (prefs.umc_magic == kUmcMagic) {
    if (prefs.ap_rescue_secs == 0) prefs.ap_rescue_secs = 60;
    return;
  }
  // First boot of UMC on this device (or upgraded from EastMesh/upstream): zero the
  // appended block but keep any existing primary SSID/password and NTP servers.
  prefs.umc_magic = kUmcMagic;
  prefs.wifi_ssid2[0] = prefs.wifi_pwd2[0] = 0;
  prefs.wifi_ssid3[0] = prefs.wifi_pwd3[0] = 0;
  prefs.ip_static = 0;
  prefs.ap_mode = 0;
  prefs.wifi_mode = 0;
  prefs.mdns_enabled = 1;
  prefs.ip_addr = prefs.ip_mask = prefs.ip_gw = prefs.ip_dns = 0;
  prefs.hostname[0] = 0;
  prefs.ap_password[0] = 0;
  StrHelper::strncpy(prefs.timezone, UMC_DEFAULT_TIMEZONE, sizeof(prefs.timezone));
  prefs.ap_rescue_secs = 60;
  prefs.reserved_umc = 0;
}

void NetworkPrefsStore::setDefaults(NetworkPrefs& prefs) {
  memset(&prefs, 0, sizeof(prefs));
  prefs.magic = kMagic;
  prefs.wifi_powersave = 0;
  prefs.wifi_channel = 0;
  applyNtpDefaults(prefs);
  applyUmcDefaults(prefs);
}

bool NetworkPrefsStore::load(FILESYSTEM* fs, NetworkPrefs& prefs,
                             uint8_t legacy_wifi_powersave,
                             const char* legacy_wifi_ssid,
                             const char* legacy_wifi_pwd) {
  setDefaults(prefs);
  if (fs == nullptr) {
    if (loadNvsNetworkPrefs(prefs)) {
      applyNtpDefaults(prefs);
    }
    return false;
  }

  if (!fs->exists(kFilename)) {
    if (loadNvsNetworkPrefs(prefs)) {
      applyNtpDefaults(prefs);
      save(fs, prefs);
      return true;
    }
    prefs.wifi_powersave = legacy_wifi_powersave <= 2 ? legacy_wifi_powersave : 0;
    if (legacy_wifi_ssid != nullptr) {
      StrHelper::strncpy(prefs.wifi_ssid, legacy_wifi_ssid, sizeof(prefs.wifi_ssid));
    }
    if (legacy_wifi_pwd != nullptr) {
      StrHelper::strncpy(prefs.wifi_pwd, legacy_wifi_pwd, sizeof(prefs.wifi_pwd));
    }
    loadLegacyWebWifiPrefs(fs, prefs);
    save(fs, prefs);
    return false;
  }

#if defined(RP2040_PLATFORM)
  File file = fs->open(kFilename, "r");
#else
  File file = fs->open(kFilename);
#endif
  if (!file) {
    return false;
  }

  NetworkPrefs persisted{};
  size_t bytes_to_read = min(static_cast<size_t>(file.size()), sizeof(persisted));
  bool ok = bytes_to_read >= sizeof(persisted.magic) &&
            file.read(reinterpret_cast<uint8_t*>(&persisted), bytes_to_read) == bytes_to_read;
  file.close();

  if (!ok || persisted.magic != kMagic) {
    fs->remove(kFilename);
    if (loadNvsNetworkPrefs(prefs)) {
      applyNtpDefaults(prefs);
      save(fs, prefs);
      return true;
    }
    save(fs, prefs);
    return false;
  }

  prefs = persisted;
  applyNtpDefaults(prefs);
  if (prefs.wifi_powersave > 2) {
    prefs.wifi_powersave = 0;
  }
  if (prefs.wifi_channel < 1 || prefs.wifi_channel > 14) {
    prefs.wifi_channel = 0;
  }
  bool repaired = false;
  if (prefs.wifi_ssid[0] == 0 && legacy_wifi_ssid != nullptr && legacy_wifi_ssid[0] != 0) {
    StrHelper::strncpy(prefs.wifi_ssid, legacy_wifi_ssid, sizeof(prefs.wifi_ssid));
    prefs.wifi_channel = 0;
    repaired = true;
  }
  if (prefs.wifi_pwd[0] == 0 && legacy_wifi_pwd != nullptr && legacy_wifi_pwd[0] != 0) {
    StrHelper::strncpy(prefs.wifi_pwd, legacy_wifi_pwd, sizeof(prefs.wifi_pwd));
    prefs.wifi_channel = 0;
    repaired = true;
  }
  if (repaired) {
    save(fs, prefs);
  } else {
    saveNvsNetworkPrefs(prefs);
  }
  return true;
}

bool NetworkPrefsStore::save(FILESYSTEM* fs, const NetworkPrefs& prefs) {
  const bool nvs_ok = saveNvsNetworkPrefs(prefs);
  if (fs == nullptr) {
    return nvs_ok;
  }
  if (fs->exists(kFilename) && !fs->remove(kFilename)) {
    return nvs_ok;
  }
#if defined(RP2040_PLATFORM)
  File file = fs->open(kFilename, "w");
#else
  File file = fs->open(kFilename, "w", true);
#endif
  if (!file) {
    return nvs_ok;
  }
  bool ok = file.write(reinterpret_cast<const uint8_t*>(&prefs), sizeof(prefs)) == sizeof(prefs);
  file.close();
  return ok && nvs_ok;
}
