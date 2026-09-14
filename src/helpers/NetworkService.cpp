#include "NetworkService.h"

#include <helpers/TxtDataHelpers.h>
#include <string.h>
#include <time.h>

#if defined(ESP_PLATFORM)
  #include <DNSServer.h>
  #include <ESPmDNS.h>
  #include <WiFi.h>
  #include <esp_netif.h>
  #include <esp_netif_net_stack.h>
  #include <esp_sntp.h>
  #include <lwip/etharp.h>
  #include <lwip/netif.h>
  #include <lwip/tcpip.h>
#endif

namespace {

#if defined(ESP_PLATFORM)
constexpr unsigned long kWifiRetryMillis = 15000;
constexpr unsigned long kWifiConnectTimeoutMillis = 45000;
constexpr unsigned long kWifiChannelHintTimeoutMillis = 7000;
// While a phone/laptop is attached to the setup/rescue AP, STA retries make the
// AP hop channels and drop the client, so retry far less often.
constexpr unsigned long kWifiRetryWithApClientMillis = 120000;
constexpr unsigned long kWatchdogProbeMillis = 30000;
constexpr unsigned long kWatchdogTimeoutMillis = 180000;
constexpr uint8_t kWatchdogMaxBackoffShift = 4;  // 180s .. 48min between forced reconnects
constexpr time_t kMinSaneEpoch = 1735689600;  // 2025-01-01T00:00:00Z
constexpr size_t kNtpServerMaxLen = 64;
constexpr uint16_t kDnsPort = 53;

bool isValidWifiChannel(uint8_t channel) {
  return channel >= 1 && channel <= 14;
}

int getWifiQualityPercent(int rssi_dbm) {
  if (rssi_dbm <= -100) {
    return 0;
  }
  if (rssi_dbm >= -50) {
    return 100;
  }
  return 2 * (rssi_dbm + 100);
}

const char* getWifiQualityLabel(int rssi_dbm) {
  if (rssi_dbm >= -60) {
    return "excellent";
  }
  if (rssi_dbm >= -67) {
    return "good";
  }
  if (rssi_dbm >= -75) {
    return "fair";
  }
  return "poor";
}

const char* authModeLabel(wifi_auth_mode_t mode) {
  switch (mode) {
    case WIFI_AUTH_OPEN: return "open";
    case WIFI_AUTH_WEP: return "wep";
    case WIFI_AUTH_WPA_PSK: return "wpa";
    case WIFI_AUTH_WPA2_PSK: return "wpa2";
    case WIFI_AUTH_WPA_WPA2_PSK: return "wpa/wpa2";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "enterprise";
    default: return "wpa3";
  }
}
#endif

// Minimal JSON string escaper for SSIDs / hostnames.
size_t appendJsonString(char* out, size_t out_size, size_t pos, const char* s) {
  if (pos + 1 >= out_size) return pos;
  out[pos++] = '"';
  for (; s != nullptr && *s && pos + 7 < out_size; s++) {
    unsigned char c = static_cast<unsigned char>(*s);
    if (c == '"' || c == '\\') {
      out[pos++] = '\\';
      out[pos++] = c;
    } else if (c < 0x20) {
      pos += snprintf(&out[pos], out_size - pos, "\\u%04x", c);
    } else {
      out[pos++] = c;
    }
  }
  if (pos + 1 < out_size) out[pos++] = '"';
  out[pos] = 0;
  return pos;
}

bool parseIp(const char* s, uint32_t& out) {
#if defined(ESP_PLATFORM)
  IPAddress ip;
  if (s == nullptr || !ip.fromString(s)) return false;
  out = static_cast<uint32_t>(ip);
  return true;
#else
  (void)s; (void)out;
  return false;
#endif
}

bool isValidHostname(const char* h) {
  size_t len = strlen(h);
  if (len == 0 || len > 32) return false;
  for (size_t i = 0; i < len; i++) {
    char c = h[i];
    bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-';
    if (!ok || (c == '-' && (i == 0 || i == len - 1))) return false;
  }
  return true;
}

}  // namespace

NetworkService::NetworkService()
    : _fs(nullptr), _prefs{}, _wifi_started(false), _sntp_started(false), _have_time_sync(false), _last_wifi_status(-1),
      _last_wifi_attempt(0), _node_name(nullptr), _default_ap_password(nullptr), _setup_mode(false), _ap_active(false),
      _ap_ssid{0}, _hostname_buf{0}, _slot(0), _sta_down_since(0), _mdns_active(false), _dns(nullptr) {
#if defined(ESP_PLATFORM)
  _wd_gateway_seen = false;
  _wd_probe_pending = false;
  _wd_gateway_ip = 0;
  _wd_was_connected = false;
  _wd_last_gateway_ok = 0;
  _wd_last_probe = 0;
  _wd_backoff_shift = 0;
  _wd_reconnect_count = 0;
#endif
  NetworkPrefsStore::setDefaults(_prefs);
}

void NetworkService::begin(FILESYSTEM* fs,
                           uint8_t legacy_wifi_powersave,
                           const char* legacy_wifi_ssid,
                           const char* legacy_wifi_pwd) {
  _fs = fs;
  NetworkPrefsStore::load(_fs, _prefs, legacy_wifi_powersave, legacy_wifi_ssid, legacy_wifi_pwd);
  NetworkPrefsStore::applyUmcDefaults(_prefs);
#if defined(ESP_PLATFORM)
  Serial.printf("[BOOT] wifi prefs powersave=%s channel=%u ssid=%s networks=%u ap=%s\n",
                getPowerSaveLabel(_prefs.wifi_powersave),
                _prefs.wifi_channel,
                _prefs.wifi_ssid[0] ? _prefs.wifi_ssid : "-",
                configuredNetworkCount(),
                getApModeLabel());
#endif
}

void NetworkService::end() {
#if defined(ESP_PLATFORM)
  stopAccessPoint();
  if (_mdns_active) {
    MDNS.end();
    _mdns_active = false;
  }
  if (_wifi_started) {
    WiFi.disconnect(true, true);
    WiFi.mode(WIFI_OFF);
  }
#endif
  _wifi_started = false;
  _sntp_started = false;
  _have_time_sync = false;
  _last_wifi_status = -1;
  _last_wifi_attempt = 0;
}

void NetworkService::loop(bool network_required) {
#if defined(ESP_PLATFORM)
  if (_prefs.wifi_mode != 0 && !_setup_mode) {
    network_required = false;
  }
  updateAccessPoint(network_required);
  ensureWifi(network_required);
  updateTimeSync();
  updateConnectivityWatchdog();
  updateMdns();
  if (_dns != nullptr) {
    _dns->processNextRequest();
  }
#else
  (void)network_required;
#endif
}

bool NetworkService::savePrefs() {
  return NetworkPrefsStore::save(_fs, _prefs);
}

bool NetworkService::setWifiSSID(const char* ssid) {
  return setWifiSSIDSlot(1, ssid);
}

bool NetworkService::setWifiPassword(const char* pwd) {
  return setWifiPasswordSlot(1, pwd);
}

bool NetworkService::setWifiSSIDSlot(uint8_t slot, const char* ssid) {
  if (ssid == nullptr || slot < 1 || slot > kMaxNetworks) {
    return false;
  }
  char* target = slot == 1 ? _prefs.wifi_ssid : (slot == 2 ? _prefs.wifi_ssid2 : _prefs.wifi_ssid3);
  StrHelper::strncpy(target, ssid, 33);
#if defined(ESP_PLATFORM)
  _prefs.wifi_channel = 0;
#endif
  bool ok = savePrefs();
  _slot = slot - 1;
  reconnectWifi();
  return ok;
}

bool NetworkService::setWifiPasswordSlot(uint8_t slot, const char* pwd) {
  if (pwd == nullptr || slot < 1 || slot > kMaxNetworks) {
    return false;
  }
  char* target = slot == 1 ? _prefs.wifi_pwd : (slot == 2 ? _prefs.wifi_pwd2 : _prefs.wifi_pwd3);
  StrHelper::strncpy(target, pwd, 65);
#if defined(ESP_PLATFORM)
  _prefs.wifi_channel = 0;
#endif
  bool ok = savePrefs();
  _slot = slot - 1;
  reconnectWifi();
  return ok;
}

const char* NetworkService::getWifiSSIDSlot(uint8_t slot) const {
  switch (slot) {
    case 1: return _prefs.wifi_ssid;
    case 2: return _prefs.wifi_ssid2;
    case 3: return _prefs.wifi_ssid3;
    default: return "";
  }
}

bool NetworkService::hasWifiPasswordSlot(uint8_t slot) const {
  switch (slot) {
    case 1: return _prefs.wifi_pwd[0] != 0;
    case 2: return _prefs.wifi_pwd2[0] != 0;
    case 3: return _prefs.wifi_pwd3[0] != 0;
    default: return false;
  }
}

bool NetworkService::clearWifiSlot(uint8_t slot) {
  if (slot < 1 || slot > kMaxNetworks) return false;
  char* ssid = slot == 1 ? _prefs.wifi_ssid : (slot == 2 ? _prefs.wifi_ssid2 : _prefs.wifi_ssid3);
  char* pwd = slot == 1 ? _prefs.wifi_pwd : (slot == 2 ? _prefs.wifi_pwd2 : _prefs.wifi_pwd3);
  memset(ssid, 0, 33);
  memset(pwd, 0, 65);
  _prefs.wifi_channel = 0;
  bool ok = savePrefs();
  _slot = 0;
  reconnectWifi();
  return ok;
}

uint8_t NetworkService::configuredNetworkCount() const {
  uint8_t n = 0;
  for (uint8_t s = 1; s <= kMaxNetworks; s++) {
    if (getWifiSSIDSlot(s)[0] != 0) n++;
  }
  return n;
}

bool NetworkService::setIpConfig(const char* spec) {
  if (spec == nullptr) return false;
  while (*spec == ' ') spec++;
  if (strcmp(spec, "dhcp") == 0) {
    _prefs.ip_static = 0;
  } else {
    char buf[96];
    StrHelper::strncpy(buf, spec, sizeof(buf));
    char* parts[4] = {nullptr, nullptr, nullptr, nullptr};
    int n = 0;
    for (char* tok = strtok(buf, " ,/"); tok != nullptr && n < 4; tok = strtok(nullptr, " ,/")) {
      parts[n++] = tok;
    }
    uint32_t ip = 0, mask = 0, gw = 0, dns = 0;
    if (n < 3 || !parseIp(parts[0], ip) || !parseIp(parts[1], mask) || !parseIp(parts[2], gw)) {
      return false;
    }
    if (n == 4 && !parseIp(parts[3], dns)) return false;
    if (n < 4) dns = gw;
    _prefs.ip_static = 1;
    _prefs.ip_addr = ip;
    _prefs.ip_mask = mask;
    _prefs.ip_gw = gw;
    _prefs.ip_dns = dns;
  }
  bool ok = savePrefs();
  reconnectWifi();
  return ok;
}

void NetworkService::formatIpConfig(char* reply, size_t reply_size) const {
#if defined(ESP_PLATFORM)
  if (_prefs.ip_static == 0) {
    snprintf(reply, reply_size, "> dhcp");
  } else {
    snprintf(reply, reply_size, "> %s %s %s %s", IPAddress(_prefs.ip_addr).toString().c_str(),
             IPAddress(_prefs.ip_mask).toString().c_str(), IPAddress(_prefs.ip_gw).toString().c_str(),
             IPAddress(_prefs.ip_dns).toString().c_str());
  }
#else
  snprintf(reply, reply_size, "> unsupported");
#endif
}

bool NetworkService::setHostname(const char* hostname) {
  if (hostname == nullptr) return false;
  while (*hostname == ' ') hostname++;
  if (hostname[0] != 0 && !isValidHostname(hostname)) return false;
  StrHelper::strncpy(_prefs.hostname, hostname, sizeof(_prefs.hostname));
  bool ok = savePrefs();
#if defined(ESP_PLATFORM)
  if (_mdns_active) {
    MDNS.end();
    _mdns_active = false;
  }
#endif
  reconnectWifi();
  return ok;
}

const char* NetworkService::getHostname() const {
  if (_prefs.hostname[0] != 0) return _prefs.hostname;
  // derive "umc-<node name>" -> lowercase, [a-z0-9-] only
  char* out = const_cast<char*>(_hostname_buf);
  size_t pos = 0;
  const char* prefix = "umc-";
  while (*prefix && pos < 32) out[pos++] = *prefix++;
  const char* name = _node_name != nullptr ? _node_name : "node";
  bool last_dash = true;
  for (; *name && pos < 32; name++) {
    char c = *name;
    if (c >= 'A' && c <= 'Z') c = c - 'A' + 'a';
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) {
      out[pos++] = c;
      last_dash = false;
    } else if (!last_dash) {
      out[pos++] = '-';
      last_dash = true;
    }
  }
  while (pos > 4 && out[pos - 1] == '-') pos--;
  out[pos] = 0;
  // "UMC Repeater" would otherwise become "umc-umc-repeater": drop the duplicated prefix.
  if (pos > 8 && strncmp(out + 4, "umc-", 4) == 0) {
    memmove(out, out + 4, pos - 4 + 1);
    pos -= 4;
  }
  if (pos == 4) {
    const char* fallback = "node";
    while (*fallback && pos < 32) out[pos++] = *fallback++;
  }
  out[pos] = 0;
  return _hostname_buf;
}

bool NetworkService::setMdnsEnabled(bool enabled) {
  _prefs.mdns_enabled = enabled ? 1 : 0;
#if defined(ESP_PLATFORM)
  if (!enabled && _mdns_active) {
    MDNS.end();
    _mdns_active = false;
  }
#endif
  return savePrefs();
}

bool NetworkService::setApMode(const char* mode) {
  if (mode == nullptr) return false;
  while (*mode == ' ') mode++;
  if (strcmp(mode, "auto") == 0) {
    _prefs.ap_mode = 0;
  } else if (strcmp(mode, "on") == 0 || strcmp(mode, "always") == 0) {
    _prefs.ap_mode = 1;
  } else if (strcmp(mode, "off") == 0 || strcmp(mode, "never") == 0) {
    _prefs.ap_mode = 2;
  } else {
    return false;
  }
  return savePrefs();
}

const char* NetworkService::getApModeLabel() const {
  switch (_prefs.ap_mode) {
    case 1: return "on";
    case 2: return "off";
    default: return "auto";
  }
}

bool NetworkService::setApPassword(const char* pwd) {
  if (pwd == nullptr) return false;
  size_t len = strlen(pwd);
  if (len != 0 && (len < 8 || len > 63)) return false;
  StrHelper::strncpy(_prefs.ap_password, pwd, sizeof(_prefs.ap_password));
  bool ok = savePrefs();
#if defined(ESP_PLATFORM)
  if (_ap_active) {
    stopAccessPoint();  // restarted with the new password on the next loop
  }
#endif
  return ok;
}

bool NetworkService::setApRescueSecs(uint16_t secs) {
  if (secs < 15 || secs > 3600) return false;
  _prefs.ap_rescue_secs = secs;
  return savePrefs();
}

bool NetworkService::setWifiEnabled(bool enabled) {
  _prefs.wifi_mode = enabled ? 0 : 1;
  bool ok = savePrefs();
  if (!enabled) reconnectWifi();
  return ok;
}

bool NetworkService::setTimezone(const char* tz) {
  if (tz == nullptr || strlen(tz) == 0 || strlen(tz) >= sizeof(_prefs.timezone)) return false;
  StrHelper::strncpy(_prefs.timezone, tz, sizeof(_prefs.timezone));
  return savePrefs();
}

void NetworkService::setSetupMode(bool setup) {
  _setup_mode = setup;
}

uint8_t NetworkService::getApClientCount() const {
#if defined(ESP_PLATFORM)
  return _ap_active ? WiFi.softAPgetStationNum() : 0;
#else
  return 0;
#endif
}

String NetworkService::getStaIp() const {
#if defined(ESP_PLATFORM)
  if (isWifiConnected()) return WiFi.localIP().toString();
#endif
  return String("");
}

bool NetworkService::startScan() {
#if defined(ESP_PLATFORM)
  if (WiFi.getMode() == WIFI_OFF) {
    WiFi.mode(WIFI_STA);
    _wifi_started = true;
  } else if (WiFi.getMode() == WIFI_AP) {
    WiFi.mode(WIFI_AP_STA);
  }
  WiFi.scanDelete();
  return WiFi.scanNetworks(true, false) == WIFI_SCAN_RUNNING;
#else
  return false;
#endif
}

void NetworkService::formatScanJson(char* out, size_t out_size) const {
  if (out_size == 0) return;
#if defined(ESP_PLATFORM)
  int n = WiFi.scanComplete();
  if (n == WIFI_SCAN_RUNNING) {
    snprintf(out, out_size, "null");
    return;
  }
  size_t pos = 0;
  pos += snprintf(out, out_size, "[");
  for (int i = 0; i < n && pos + 96 < out_size; i++) {
    String ssid = WiFi.SSID(i);
    if (ssid.length() == 0) continue;
    if (pos > 1) out[pos++] = ',';
    pos += snprintf(&out[pos], out_size - pos, "{\"ssid\":");
    pos = appendJsonString(out, out_size, pos, ssid.c_str());
    pos += snprintf(&out[pos], out_size - pos, ",\"rssi\":%d,\"ch\":%d,\"auth\":\"%s\"}", WiFi.RSSI(i), WiFi.channel(i),
                    authModeLabel(WiFi.encryptionType(i)));
  }
  if (pos + 2 < out_size) {
    out[pos++] = ']';
    out[pos] = 0;
  }
#else
  snprintf(out, out_size, "[]");
#endif
}

void NetworkService::formatNetJson(char* out, size_t out_size) const {
#if defined(ESP_PLATFORM)
  size_t pos = snprintf(out, out_size, "{\"sta\":{\"connected\":%s,\"ssid\":", isWifiConnected() ? "true" : "false");
  pos = appendJsonString(out, out_size, pos, isWifiConnected() ? WiFi.SSID().c_str() : "");
  pos += snprintf(&out[pos], out_size - pos, ",\"ip\":\"%s\",\"gw\":\"%s\",\"rssi\":%d,\"ch\":%d,\"mac\":\"%s\"},",
                  isWifiConnected() ? WiFi.localIP().toString().c_str() : "",
                  isWifiConnected() ? WiFi.gatewayIP().toString().c_str() : "", isWifiConnected() ? WiFi.RSSI() : 0,
                  isWifiConnected() ? WiFi.channel() : 0, WiFi.macAddress().c_str());
  pos += snprintf(&out[pos], out_size - pos, "\"ap\":{\"active\":%s,\"ssid\":", _ap_active ? "true" : "false");
  pos = appendJsonString(out, out_size, pos, _ap_active ? _ap_ssid : "");
  pos += snprintf(&out[pos], out_size - pos, ",\"ip\":\"%s\",\"clients\":%u,\"mode\":\"%s\"},",
                  _ap_active ? WiFi.softAPIP().toString().c_str() : "", getApClientCount(), getApModeLabel());
  pos += snprintf(&out[pos], out_size - pos, "\"hostname\":");
  pos = appendJsonString(out, out_size, pos, getHostname());
  pos += snprintf(&out[pos], out_size - pos, ",\"mdns\":%s,\"networks\":%u,\"setup\":%s,\"time_sync\":%s,\"wifi\":%s}",
                  _mdns_active ? "true" : "false", configuredNetworkCount(), _setup_mode ? "true" : "false",
                  _have_time_sync ? "true" : "false", isWifiEnabled() ? "true" : "false");
#else
  snprintf(out, out_size, "{}");
#endif
}

bool NetworkService::isValidNtpServer(const char* server) {
  if (server == nullptr || server[0] == 0) {
    return false;
  }
  size_t len = 0;
  while (server[len] != 0) {
    const char c = server[len];
    if (c <= ' ' || c == ',' || c == '\x7F') {
      return false;
    }
    len++;
    if (len >= kNtpServerMaxLen) {
      return false;
    }
  }
  return true;
}

bool NetworkService::setNtpServer(uint8_t index, const char* server) {
  if (!isValidNtpServer(server)) {
    return false;
  }

  char* target = nullptr;
  switch (index) {
    case 1:
      target = _prefs.ntp_server1;
      break;
    case 2:
      target = _prefs.ntp_server2;
      break;
    case 3:
      target = _prefs.ntp_server3;
      break;
    default:
      return false;
  }

  if (strcmp(target, server) == 0) {
    return true;
  }

  StrHelper::strncpy(target, server, sizeof(_prefs.ntp_server1));
  const bool ok = savePrefs();
#if defined(ESP_PLATFORM)
  restartTimeSync();
#endif
  return ok;
}

const char* NetworkService::getNtpServer(uint8_t index) const {
  switch (index) {
    case 1:
      return _prefs.ntp_server1;
    case 2:
      return _prefs.ntp_server2;
    case 3:
      return _prefs.ntp_server3;
    default:
      return "";
  }
}

bool NetworkService::setWifiPowerSave(const char* mode) {
  if (mode == nullptr) {
    return false;
  }

  char normalized[8];
  size_t len = 0;
  while (*mode == ' ' || *mode == '\t') {
    mode++;
  }
  while (len < sizeof(normalized) - 1) {
    char c = mode[len];
    if (c == 0 || c == '\r' || c == '\n' || c == ' ' || c == '\t') {
      break;
    }
    normalized[len] = c;
    len++;
  }
  normalized[len] = 0;

  uint8_t next_mode;
  if (strcmp(normalized, "none") == 0) {
    next_mode = 0;
  } else if (strcmp(normalized, "min") == 0) {
    next_mode = 1;
  } else if (strcmp(normalized, "max") == 0) {
    next_mode = 2;
  } else {
    return false;
  }

  if (_prefs.wifi_powersave == next_mode) {
    return true;
  }

  _prefs.wifi_powersave = next_mode;
  bool ok = savePrefs();
#if defined(ESP_PLATFORM)
  if (_wifi_started) {
    WiFi.setSleep(toEspPowerSave(_prefs.wifi_powersave));
  }
#endif
  return ok;
}

const char* NetworkService::getWifiPowerSave() const {
#if defined(ESP_PLATFORM)
  return getPowerSaveLabel(_prefs.wifi_powersave);
#else
  return "unsupported";
#endif
}

void NetworkService::formatWifiStatusReply(char* reply, size_t reply_size) const {
#if defined(ESP_PLATFORM)
  const char* status = "disconnected";
  const char* state = "disconnected";
  wl_status_t wifi_status = WiFi.status();
  if (configuredNetworkCount() == 0) {
    status = "unconfigured";
    state = "unconfigured";
  } else if (wifi_status == WL_CONNECTED) {
    status = "connected";
    state = "connected";
  } else if (_wifi_started) {
    status = "connecting";
  }

  switch (wifi_status) {
    case WL_IDLE_STATUS:
      state = "idle";
      break;
    case WL_NO_SSID_AVAIL:
      state = "no_ssid";
      break;
    case WL_SCAN_COMPLETED:
      state = "scan_completed";
      break;
    case WL_CONNECTED:
      state = "connected";
      break;
    case WL_CONNECT_FAILED:
      state = "connect_failed";
      break;
    case WL_CONNECTION_LOST:
      state = "connection_lost";
      break;
    case WL_DISCONNECTED:
      state = "disconnected";
      break;
    default:
      state = "unknown";
      break;
  }

  char ap_part[64];
  if (_ap_active) {
    snprintf(ap_part, sizeof(ap_part), " ap:%s clients:%u", _ap_ssid, getApClientCount());
  } else {
    ap_part[0] = 0;
  }

  if (wifi_status == WL_CONNECTED) {
    const int rssi_dbm = WiFi.RSSI();
    snprintf(reply, reply_size,
             "> ssid:%s status:%s code:%d state:%s ip:%s channel:%d rssi:%d quality:%d%% signal:%s gw:%s wd:%u%s",
             WiFi.SSID().c_str(), status, static_cast<int>(wifi_status), state, WiFi.localIP().toString().c_str(),
             WiFi.channel(), rssi_dbm, getWifiQualityPercent(rssi_dbm), getWifiQualityLabel(rssi_dbm),
             isGatewayReachable() ? "ok" : "lost", _wd_reconnect_count, ap_part);
  } else {
    const char* trying = slotSsid(_slot);
    snprintf(reply, reply_size, "> ssid:%s status:%s code:%d state:%s%s", trying[0] ? trying : "-",
             status, static_cast<int>(wifi_status), state, ap_part);
  }
#else
  snprintf(reply, reply_size, "> wifi:unsupported");
#endif
}

void NetworkService::reconnectWifi() {
#if defined(ESP_PLATFORM)
  if (_wifi_started) {
    WiFi.disconnect(false, true);
    if (!_ap_active) {
      WiFi.mode(WIFI_OFF);
    }
  }
  _wd_was_connected = false;
#endif
  _wifi_started = _ap_active;
  _sntp_started = false;
  _have_time_sync = false;
  _last_wifi_attempt = 0;
}

bool NetworkService::isGatewayReachable() const {
#if defined(ESP_PLATFORM)
  return millis() - _wd_last_gateway_ok < (kWatchdogProbeMillis * 3);
#else
  return false;
#endif
}

uint16_t NetworkService::getWatchdogReconnectCount() const {
#if defined(ESP_PLATFORM)
  return _wd_reconnect_count;
#else
  return 0;
#endif
}

void NetworkService::forceReconnect() {
#if defined(ESP_PLATFORM)
  // Clear the channel hint (RAM only) so the retry does a full scan and can land
  // on a different AP; the hint is re-learned and persisted on the next connect.
  _prefs.wifi_channel = 0;
#endif
  reconnectWifi();
}

void NetworkService::restartTimeSync() {
  _sntp_started = false;
  _have_time_sync = false;
}

bool NetworkService::isWifiConnected() const {
#if defined(ESP_PLATFORM)
  return _wifi_started && WiFi.status() == WL_CONNECTED;
#else
  return false;
#endif
}

#if defined(ESP_PLATFORM)
wifi_ps_type_t NetworkService::toEspPowerSave(uint8_t mode) {
  switch (mode) {
    case 1:
      return WIFI_PS_MIN_MODEM;
    case 2:
      return WIFI_PS_MAX_MODEM;
    default:
      return WIFI_PS_NONE;
  }
}

const char* NetworkService::getPowerSaveLabel(uint8_t mode) {
  switch (mode) {
    case 1:
      return "min";
    case 2:
      return "max";
    default:
      return "none";
  }
}

const char* NetworkService::slotSsid(uint8_t idx) const {
  return getWifiSSIDSlot(idx + 1);
}

const char* NetworkService::slotPwd(uint8_t idx) const {
  switch (idx) {
    case 0: return _prefs.wifi_pwd;
    case 1: return _prefs.wifi_pwd2;
    case 2: return _prefs.wifi_pwd3;
    default: return "";
  }
}

bool NetworkService::selectNextSlot() {
  for (uint8_t i = 1; i <= kMaxNetworks; i++) {
    uint8_t next = (_slot + i) % kMaxNetworks;
    if (slotSsid(next)[0] != 0) {
      _slot = next;
      return true;
    }
  }
  return slotSsid(_slot)[0] != 0;
}

void NetworkService::applyStaConfig() {
  WiFi.setHostname(getHostname());
  if (_prefs.ip_static != 0 && _prefs.ip_addr != 0) {
    WiFi.config(IPAddress(_prefs.ip_addr), IPAddress(_prefs.ip_gw), IPAddress(_prefs.ip_mask), IPAddress(_prefs.ip_dns));
  } else {
    WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE, INADDR_NONE);
  }
}

void NetworkService::startAccessPoint() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  if (_setup_mode) {
    snprintf(_ap_ssid, sizeof(_ap_ssid), "UMC-Setup-%02X%02X", mac[4], mac[5]);
  } else {
    char short_name[17];
    const char* n = _node_name != nullptr ? _node_name : "Node";
    size_t j = 0;
    for (; *n && j < sizeof(short_name) - 1; n++) {
      char c = *n;
      if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-') short_name[j++] = c;
    }
    short_name[j] = 0;
    snprintf(_ap_ssid, sizeof(_ap_ssid), "UMC-%s-%02X%02X", short_name[0] ? short_name : "Node", mac[4], mac[5]);
  }

  // First-time setup hotspot is open (no password) so anyone setting up the device can just join it.
  // The rescue / always-on AP of an already configured device stays WPA2 (custom password or PIN).
  const char* pwd = _setup_mode ? ""
                  : _prefs.ap_password[0] ? _prefs.ap_password
                  : (_default_ap_password != nullptr ? _default_ap_password : "");
  wifi_mode_t mode = WiFi.getMode();
  if (mode == WIFI_OFF || mode == WIFI_STA) {
    WiFi.mode(configuredNetworkCount() > 0 && _prefs.wifi_mode == 0 ? WIFI_AP_STA : WIFI_AP);
  }
  IPAddress ap_ip(192, 168, 4, 1);
  WiFi.softAPConfig(ap_ip, ap_ip, IPAddress(255, 255, 255, 0));
  bool ok = WiFi.softAP(_ap_ssid, strlen(pwd) >= 8 ? pwd : nullptr, 0, 0, 4);
  if (!ok) {
    Serial.println("[NET] AP start failed");
    return;
  }
  _ap_active = true;
  _wifi_started = true;
  if (_dns == nullptr) {
    _dns = new DNSServer();
  }
  _dns->setErrorReplyCode(DNSReplyCode::NoError);
  _dns->start(kDnsPort, "*", ap_ip);
  Serial.printf("[NET] AP up ssid=%s ip=%s secured=%s\n", _ap_ssid, ap_ip.toString().c_str(), strlen(pwd) >= 8 ? "yes" : "no");
}

void NetworkService::stopAccessPoint() {
  if (_dns != nullptr) {
    _dns->stop();
    delete _dns;
    _dns = nullptr;
  }
  if (_ap_active) {
    WiFi.softAPdisconnect(true);
    _ap_active = false;
    if (WiFi.getMode() == WIFI_AP_STA) {
      WiFi.mode(WIFI_STA);
    }
    Serial.println("[NET] AP down");
  }
}

void NetworkService::updateAccessPoint(bool network_required) {
  bool want_ap = false;
  const unsigned long now_ms = millis();
  const bool sta_connected = isWifiConnected();

  if (sta_connected) {
    _sta_down_since = 0;
  } else if (_sta_down_since == 0) {
    _sta_down_since = now_ms == 0 ? 1 : now_ms;
  }

  if (_setup_mode) {
    want_ap = true;
  } else if (_prefs.ap_mode == 2) {
    want_ap = false;
  } else if (_prefs.ap_mode == 1) {
    want_ap = true;
  } else if (!network_required && _prefs.wifi_mode != 0) {
    want_ap = false;  // wifi switched off entirely
  } else if (configuredNetworkCount() == 0) {
    want_ap = true;
  } else if (!sta_connected) {
    want_ap = now_ms - _sta_down_since >= static_cast<unsigned long>(_prefs.ap_rescue_secs) * 1000UL;
  } else {
    // Connected: keep the rescue AP only while someone is still using it.
    want_ap = _ap_active && WiFi.softAPgetStationNum() > 0;
  }

  if (want_ap && !_ap_active) {
    startAccessPoint();
  } else if (!want_ap && _ap_active) {
    stopAccessPoint();
  }
}

void NetworkService::updateMdns() {
  const bool want = _prefs.mdns_enabled != 0 && (isWifiConnected() || _ap_active);
  if (want && !_mdns_active) {
    if (MDNS.begin(getHostname())) {
      MDNS.addService("http", "tcp", 80);
      MDNS.addServiceTxt("http", "tcp", "fw", "umc");
      _mdns_active = true;
      Serial.printf("[NET] mDNS http://%s.local/\n", getHostname());
    }
  } else if (!want && _mdns_active) {
    MDNS.end();
    _mdns_active = false;
  }
}

void NetworkService::ensureWifi(bool network_required) {
  if (!network_required) {
    if (_wifi_started && !_ap_active) {
      WiFi.disconnect(true, true);
      WiFi.mode(WIFI_OFF);
      _wifi_started = false;
      _sntp_started = false;
      _have_time_sync = false;
      _last_wifi_status = -1;
    }
    return;
  }

  if (configuredNetworkCount() == 0 || _prefs.wifi_mode != 0) {
    _last_wifi_attempt = 0;
    return;
  }
  if (slotSsid(_slot)[0] == 0) {
    selectNextSlot();
  }

  wl_status_t status = WiFi.status();
  if (static_cast<int>(status) != _last_wifi_status) {
    _last_wifi_status = static_cast<int>(status);
    if (status == WL_CONNECTED) {
      const int connected_channel = WiFi.channel();
      Serial.printf("[BOOT] wifi connected t=%lu ssid=%s ip=%s rssi=%d channel=%d\n",
                    static_cast<unsigned long>(millis()),
                    WiFi.SSID().c_str(),
                    WiFi.localIP().toString().c_str(),
                    WiFi.RSSI(),
                    connected_channel);
      if (_slot == 0 && connected_channel > 0 && connected_channel <= 14 && _prefs.wifi_channel != connected_channel) {
        _prefs.wifi_channel = static_cast<uint8_t>(connected_channel);
        Serial.printf("[BOOT] wifi learned channel=%u save=%s\n",
                      _prefs.wifi_channel,
                      savePrefs() ? "ok" : "failed");
      }
    }
  }

  if (status == WL_CONNECTED) {
    return;
  }

  unsigned long now_ms = millis();
  const unsigned long retry_ms = (_ap_active && WiFi.softAPgetStationNum() > 0) ? kWifiRetryWithApClientMillis
                                                                                 : kWifiRetryMillis;
  if (_wifi_started && _last_wifi_attempt != 0) {
    if (_slot == 0 && isValidWifiChannel(_prefs.wifi_channel) &&
        now_ms - _last_wifi_attempt >= kWifiChannelHintTimeoutMillis) {
      Serial.printf("[BOOT] wifi channel hint timeout t=%lu channel=%u\n",
                    static_cast<unsigned long>(millis()),
                    _prefs.wifi_channel);
      _prefs.wifi_channel = 0;
      savePrefs();
      WiFi.disconnect(false, false);
      _last_wifi_attempt = 0;
    } else if (now_ms - _last_wifi_attempt < kWifiConnectTimeoutMillis) {
      return;
    } else {
      Serial.printf("[BOOT] wifi timeout t=%lu ssid=%s code=%d, trying next\n",
                    static_cast<unsigned long>(millis()), slotSsid(_slot),
                    static_cast<int>(status));
      WiFi.disconnect(false, false);
      if (!_ap_active) {
        WiFi.mode(WIFI_OFF);
        delay(100);
        _wifi_started = false;
      }
      _sntp_started = false;
      _have_time_sync = false;
      _last_wifi_status = -1;
      selectNextSlot();
      if (now_ms - _last_wifi_attempt < retry_ms) {
        return;
      }
    }
  }

  if (!_wifi_started || WiFi.getMode() == WIFI_OFF) {
    WiFi.mode(_ap_active ? WIFI_AP_STA : WIFI_STA);
    WiFi.setSleep(toEspPowerSave(_prefs.wifi_powersave));
    _wifi_started = true;
    Serial.printf("[BOOT] wifi start t=%lu\n", static_cast<unsigned long>(millis()));
  } else if (_ap_active && WiFi.getMode() == WIFI_AP) {
    WiFi.mode(WIFI_AP_STA);
  }

  applyStaConfig();
  _last_wifi_attempt = now_ms == 0 ? 1 : now_ms;
  const char* ssid = slotSsid(_slot);
  const char* pwd = slotPwd(_slot);
  if (_slot == 0 && isValidWifiChannel(_prefs.wifi_channel)) {
    WiFi.begin(ssid, pwd[0] ? pwd : nullptr, _prefs.wifi_channel);
    Serial.printf("[BOOT] wifi begin t=%lu ssid=%s channel=%u\n", static_cast<unsigned long>(millis()), ssid, _prefs.wifi_channel);
  } else {
    WiFi.begin(ssid, pwd[0] ? pwd : nullptr);
    Serial.printf("[BOOT] wifi begin t=%lu ssid=%s channel=scan\n", static_cast<unsigned long>(millis()), ssid);
  }
}

void NetworkService::updateTimeSync() {
  bool prev_have_time_sync = _have_time_sync;
  if (!_wifi_started || WiFi.status() != WL_CONNECTED) {
    _have_time_sync = false;
    return;
  }

  if (!_sntp_started) {
    configTzTime("UTC0", _prefs.ntp_server1, _prefs.ntp_server2, _prefs.ntp_server3);
    _sntp_started = true;
  }

  sntp_sync_status_t sync_status = sntp_get_sync_status();
  time_t now = time(nullptr);
  bool sane_time = now >= kMinSaneEpoch;
  bool sync_ready = sync_status == SNTP_SYNC_STATUS_COMPLETED || sync_status == SNTP_SYNC_STATUS_IN_PROGRESS;
  _have_time_sync = sane_time && (sync_ready || prev_have_time_sync);
}

// Runs in the lwIP tcpip thread (posted via tcpip_callback), where raw etharp
// calls are safe without core locking.
void NetworkService::watchdogProbeCallback(void* arg) {
  NetworkService* self = static_cast<NetworkService*>(arg);
  esp_netif_t* esp_nif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
  struct netif* nif = esp_nif ? static_cast<struct netif*>(esp_netif_get_netif_impl(esp_nif)) : nullptr;
  if (nif != nullptr && netif_is_up(nif)) {
    ip4_addr_t gw;
    gw.addr = self->_wd_gateway_ip;
    struct eth_addr* eth_ret = nullptr;
    const ip4_addr_t* ip_ret = nullptr;
    if (etharp_find_addr(nif, &gw, &eth_ret, &ip_ret) >= 0) {
      self->_wd_gateway_seen = true;
    }
    etharp_request(nif, &gw);
  }
  self->_wd_probe_pending = false;
}

void NetworkService::updateConnectivityWatchdog() {
  if (!_wifi_started || WiFi.status() != WL_CONNECTED) {
    _wd_was_connected = false;
    return;
  }

  const unsigned long now_ms = millis();
  if (!_wd_was_connected) {
    // Fresh association: give the gateway a full window before judging it.
    _wd_was_connected = true;
    _wd_last_gateway_ok = now_ms;
    _wd_last_probe = 0;
    _wd_gateway_seen = false;
  }

  if (_wd_gateway_seen.exchange(false)) {
    _wd_last_gateway_ok = now_ms;
    _wd_backoff_shift = 0;
  }

  const uint32_t gateway_ip = static_cast<uint32_t>(WiFi.gatewayIP());
  if (gateway_ip == 0) {
    // No gateway (e.g. static IP without one) - nothing meaningful to probe.
    _wd_last_gateway_ok = now_ms;
    return;
  }

  if (now_ms - _wd_last_probe >= kWatchdogProbeMillis && !_wd_probe_pending.load()) {
    _wd_last_probe = now_ms;
    _wd_gateway_ip = gateway_ip;
    _wd_probe_pending = true;
    if (tcpip_callback(watchdogProbeCallback, this) != ERR_OK) {
      _wd_probe_pending = false;
    }
  }

  const unsigned long timeout = kWatchdogTimeoutMillis << _wd_backoff_shift;
  if (now_ms - _wd_last_gateway_ok >= timeout) {
    _wd_reconnect_count++;
    if (_wd_backoff_shift < kWatchdogMaxBackoffShift) {
      _wd_backoff_shift++;
    }
    Serial.printf("[WDOG] gateway unreachable for %lus, forcing wifi reconnect (count=%u)\n",
                  (now_ms - _wd_last_gateway_ok) / 1000, _wd_reconnect_count);
    forceReconnect();
  }
}
#endif
