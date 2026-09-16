#include "UmcPrefs.h"

#include <string.h>

#if defined(ESP_PLATFORM)
  #include <Preferences.h>
  #include <esp_random.h>
#endif

#ifndef UMC_DEFAULT_TELNET
  #define UMC_DEFAULT_TELNET false
#endif
#ifndef UMC_DEFAULT_BLE
  #define UMC_DEFAULT_BLE true
#endif
#ifndef UMC_DEFAULT_BLE_IDLE_OFF_MIN
  #define UMC_DEFAULT_BLE_IDLE_OFF_MIN 0
#endif

namespace {
constexpr const char* kNs = "umc";
}

void UmcPrefsStore::setDefaults(UmcPrefs& p) {
  memset(&p, 0, sizeof(p));
  p.setup_done = false;
  p.http_enabled = true;
  p.http_port = 80;
  p.telnet_enabled = UMC_DEFAULT_TELNET;
  p.telnet_port = 23;
  p.session_timeout_min = 30;
  p.ble_enabled = UMC_DEFAULT_BLE;
  p.ble_idle_off_min = UMC_DEFAULT_BLE_IDLE_OFF_MIN;
  p.display_mode = 0;
  p.display_timeout_s = 0;
  p.display_ip_s = 6;
  p.display_page_s = 5;
  p.display_traffic_s = 60;
  p.group_hops_max = 64;
  p.app_tcp = true;
  p.app_tcp_port = 5000;
  strcpy(p.admin_pw, "password");
}

bool UmcPrefsStore::isValidPin(const char* pin) {
  if (pin == nullptr || strlen(pin) != 8) return false;
  for (int i = 0; i < 8; i++) {
    if (pin[i] < '0' || pin[i] > '9') return false;
  }
  return true;
}

void UmcPrefsStore::load(UmcPrefs& p) {
  setDefaults(p);
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (nvs.begin(kNs, true)) {
    p.setup_done = nvs.getBool("setup", p.setup_done);
    p.http_enabled = nvs.getBool("http", p.http_enabled);
    p.http_port = nvs.getUShort("http_port", p.http_port);
    p.telnet_enabled = nvs.getBool("telnet", p.telnet_enabled);
    p.telnet_port = nvs.getUShort("telnet_port", p.telnet_port);
    p.session_timeout_min = nvs.getUShort("sess_min", p.session_timeout_min);
    p.ble_enabled = nvs.getBool("ble", p.ble_enabled);
    p.ble_idle_off_min = nvs.getUShort("ble_idle", p.ble_idle_off_min);
    p.display_mode = nvs.getUChar("disp_mode", p.display_mode);
    p.display_timeout_s = nvs.getUShort("disp_to", p.display_timeout_s);
    p.display_ip_s = nvs.getUChar("disp_ip", p.display_ip_s);
    p.display_page_s = nvs.getUChar("disp_page", p.display_page_s);
    p.display_traffic_s = nvs.getUShort("disp_trf", p.display_traffic_s);
    p.group_hops_max = nvs.getUChar("grp_hops", p.group_hops_max);
    p.app_tcp = nvs.getBool("app_tcp", p.app_tcp);
    p.app_tcp_port = nvs.getUShort("app_port", p.app_tcp_port);
    nvs.getString("pin", p.pin, sizeof(p.pin));
    if (nvs.isKey("admin_pw")) nvs.getString("admin_pw", p.admin_pw, sizeof(p.admin_pw));
    nvs.end();
  }
  if (!isValidPin(p.pin)) {
    uint32_t r = esp_random() % 100000000UL;
    snprintf(p.pin, sizeof(p.pin), "%08lu", static_cast<unsigned long>(r));
    save(p);
  }
#endif
}

bool UmcPrefsStore::save(const UmcPrefs& p) {
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (!nvs.begin(kNs, false)) return false;
  nvs.putBool("setup", p.setup_done);
  nvs.putBool("http", p.http_enabled);
  nvs.putUShort("http_port", p.http_port);
  nvs.putBool("telnet", p.telnet_enabled);
  nvs.putUShort("telnet_port", p.telnet_port);
  nvs.putUShort("sess_min", p.session_timeout_min);
  nvs.putBool("ble", p.ble_enabled);
  nvs.putUShort("ble_idle", p.ble_idle_off_min);
  nvs.putUChar("disp_mode", p.display_mode);
  nvs.putUShort("disp_to", p.display_timeout_s);
  nvs.putUChar("disp_ip", p.display_ip_s);
  nvs.putUChar("disp_page", p.display_page_s);
  nvs.putUShort("disp_trf", p.display_traffic_s);
  nvs.putUChar("grp_hops", p.group_hops_max);
  nvs.putBool("app_tcp", p.app_tcp);
  nvs.putUShort("app_port", p.app_tcp_port);
  nvs.putString("pin", p.pin);
  nvs.putString("admin_pw", p.admin_pw);
  nvs.end();
  return true;
#else
  (void)p;
  return false;
#endif
}

bool UmcPrefsStore::erase() {
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (!nvs.begin(kNs, false)) return false;
  bool ok = nvs.clear();
  nvs.end();
  return ok;
#else
  return false;
#endif
}
