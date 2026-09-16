#pragma once

#include <Arduino.h>
#include <helpers/IdentityStore.h>
#include <helpers/NetworkStateProvider.h>

#if defined(ESP_PLATFORM)
  #include <WiFi.h>

  #include <atomic>
#endif

#include "NetworkPrefs.h"

class DNSServer;

class NetworkService : public NetworkStateProvider {
public:
  static constexpr uint8_t kMaxNetworks = 3;

  NetworkService();

  void begin(FILESYSTEM* fs,
             uint8_t legacy_wifi_powersave = 0,
             const char* legacy_wifi_ssid = nullptr,
             const char* legacy_wifi_pwd = nullptr);
  void end();
  void loop(bool network_required);

  bool setWifiSSID(const char* ssid);
  bool setWifiPassword(const char* pwd);
  const char* getWifiSSID() const { return _prefs.wifi_ssid; }
  bool setWifiPowerSave(const char* mode);
  const char* getWifiPowerSave() const;
  bool setNtpServer(uint8_t index, const char* server);
  const char* getNtpServer(uint8_t index) const;
  void formatWifiStatusReply(char* reply, size_t reply_size) const;
  void reconnectWifi();
  void forceReconnect();
  // Gateway watchdog state, as reported by `get wifi.status` (gw:ok|lost wd:<n>).
  bool isGatewayReachable() const;
  uint16_t getWatchdogReconnectCount() const;

  bool isWifiConnected() const override;
  bool hasTimeSync() const override { return _have_time_sync; }

  // ---- UMC: multi-network STA, static IP, setup/rescue AP, captive portal, mDNS ----
  // Slot numbers are 1..kMaxNetworks; slot 1 is the legacy wifi.ssid/wifi.pwd pair.
  bool setWifiSSIDSlot(uint8_t slot, const char* ssid);
  bool setWifiPasswordSlot(uint8_t slot, const char* pwd);
  const char* getWifiSSIDSlot(uint8_t slot) const;
  bool hasWifiPasswordSlot(uint8_t slot) const;
  bool clearWifiSlot(uint8_t slot);
  uint8_t configuredNetworkCount() const;

  bool setIpConfig(const char* spec);   // "dhcp" or "<ip> <mask> <gw> [dns]"
  void formatIpConfig(char* reply, size_t reply_size) const;
  bool setHostname(const char* hostname);  // "" = derive from node name
  const char* getHostname() const;         // effective hostname
  bool setMdnsEnabled(bool enabled);
  bool isMdnsEnabled() const { return _prefs.mdns_enabled != 0; }
  bool setApMode(const char* mode);        // auto | on | off
  const char* getApModeLabel() const;
  bool setApPassword(const char* pwd);     // "" = use device PIN
  bool hasCustomApPassword() const { return _prefs.ap_password[0] != 0; }
  bool setApRescueSecs(uint16_t secs);
  uint16_t getApRescueSecs() const { return _prefs.ap_rescue_secs; }
  bool setWifiEnabled(bool enabled);
  bool isWifiEnabled() const { return _prefs.wifi_mode == 0; }
  bool setTimezone(const char* tz);
  const char* getTimezone() const { return _prefs.timezone; }

  void setNodeName(const char* name) { _node_name = name; }
  // Lowest WiFi power-save mode allowed (Bluetooth coexistence needs at least modem sleep "min").
  void setMinPowerSave(uint8_t mode) { _min_powersave = mode; }
  uint8_t effectivePowerSave() const { return _prefs.wifi_powersave > _min_powersave ? _prefs.wifi_powersave : _min_powersave; }
  void setDefaultApPassword(const char* pin_password) { _default_ap_password = pin_password; }
  void setSetupMode(bool setup);           // forces the AP on until setup completes
  bool isSetupMode() const { return _setup_mode; }

  bool isApActive() const { return _ap_active; }
  uint8_t getApClientCount() const;
  const char* getApSsid() const { return _ap_ssid; }
  bool isNetworkReachable() const { return isWifiConnected() || _ap_active; }
  String getStaIp() const;

  bool startScan();
  // JSON array of scan results, or "null" while a scan is still running.
  void formatScanJson(char* out, size_t out_size) const;
  void formatNetJson(char* out, size_t out_size) const;

private:
#if defined(ESP_PLATFORM)
  static wifi_ps_type_t toEspPowerSave(uint8_t mode);
  static const char* getPowerSaveLabel(uint8_t mode);
  void ensureWifi(bool network_required);
  void updateTimeSync();
  void restartTimeSync();
  void updateConnectivityWatchdog();
  static void watchdogProbeCallback(void* arg);
  void updateAccessPoint(bool network_required);
  void startAccessPoint();
  void stopAccessPoint();
  void updateMdns();
  void applyStaConfig();
  bool selectNextSlot();
  const char* slotSsid(uint8_t idx) const;
  const char* slotPwd(uint8_t idx) const;
#endif
  static bool isValidNtpServer(const char* server);
  bool savePrefs();

  FILESYSTEM* _fs;
  NetworkPrefs _prefs;
  bool _wifi_started;
  bool _sntp_started;
  bool _have_time_sync;
  int _last_wifi_status;
  unsigned long _last_wifi_attempt;
  const char* _node_name;
  const char* _default_ap_password;
  bool _setup_mode;
  bool _ap_active;
  uint8_t _min_powersave = 0;
  char _ap_ssid[33];
  char _hostname_buf[33];
  uint8_t _slot;                   // 0-based index of the SSID currently being tried
  unsigned long _sta_down_since;   // 0 while connected
  bool _mdns_active;
  DNSServer* _dns;
#if defined(ESP_PLATFORM)
  // Connectivity watchdog: _wd_gateway_seen and _wd_probe_pending are shared with
  // the lwIP tcpip thread; _wd_gateway_ip is only written while no probe is pending.
  std::atomic<bool> _wd_gateway_seen;
  std::atomic<bool> _wd_probe_pending;
  uint32_t _wd_gateway_ip;
  bool _wd_was_connected;
  unsigned long _wd_last_gateway_ok;
  unsigned long _wd_last_probe;
  uint8_t _wd_backoff_shift;
  uint16_t _wd_reconnect_count;
#endif
};
