#include "UmcService.h"
#include "UmcLog.h"

#include <helpers/NetworkService.h>
#include <helpers/TxtDataHelpers.h>
#include <string.h>

#include "UmcChatLog.h"
#include "UmcTelnet.h"
#include "UmcAppServer.h"
#include "UmcRoutes.h"
#include "UmcTraffic.h"
#include "UmcUpdater.h"
#include "UmcVersion.h"

UmcTraffic umc_traffic;
UmcRoutes umc_routes;
UmcChatLog umc_chatlog;

// Default for hosts without an app protocol: reject every command as unsupported.
void UmcHost::umcAppFrame(UmcAppServer& server, int client, const uint8_t* frame, size_t len) {
  (void)frame;
  (void)len;
  const uint8_t err[2] = {1 /* RESP_CODE_ERR */, 1 /* ERR_CODE_UNSUPPORTED_CMD */};
  server.send(client, err, sizeof(err));
}

#if defined(ESP_PLATFORM)
#include <esp_ota_ops.h>
#include <esp_system.h>
#include <esp_task_wdt.h>

// Tell the Arduino core not to confirm a freshly updated image at boot: UMC confirms it
// only after it has run healthily (see UmcService::loop), so a firmware that crashes or
// hangs early is rolled back to the previous slot by the bootloader.
// The core declares this weak symbol in a C file, so it needs C linkage to override it.
extern "C" bool verifyRollbackLater() { return true; }

namespace {
constexpr unsigned long kOtaHealthyAfterMs = 60000;
constexpr uint32_t kLoopWatchdogSecs = 60;  // reboot if the main loop stops running for this long

const char* resetReasonLabel(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "power-on";
    case ESP_RST_EXT: return "reset pin";
    case ESP_RST_SW: return "restart";
    case ESP_RST_PANIC: return "crash";
    case ESP_RST_INT_WDT: return "watchdog (interrupt)";
    case ESP_RST_TASK_WDT: return "watchdog (hang)";
    case ESP_RST_WDT: return "watchdog";
    case ESP_RST_DEEPSLEEP: return "deep sleep wake";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    default: return "unknown";
  }
}

const char* otaStateLabel(esp_ota_img_states_t s) {
  switch (s) {
    case ESP_OTA_IMG_NEW: return "new";
    case ESP_OTA_IMG_PENDING_VERIFY: return "pending-verify";
    case ESP_OTA_IMG_VALID: return "valid";
    case ESP_OTA_IMG_INVALID: return "invalid";
    case ESP_OTA_IMG_ABORTED: return "aborted";
    default: return "undefined";
  }
}
}  // namespace

bool umcOtaPendingVerify() {
  esp_ota_img_states_t state;
  const esp_partition_t* running = esp_ota_get_running_partition();
  return running != nullptr && esp_ota_get_state_partition(running, &state) == ESP_OK && state == ESP_OTA_IMG_PENDING_VERIFY;
}

void umcOtaFailBoot() {
  if (umcOtaPendingVerify()) {
    UMC_LOGLN("[UMC] new firmware failed its boot check - rolling back to the previous version");
    delay(200);
    esp_ota_mark_app_invalid_rollback_and_reboot();
  }
}
#endif

namespace {
size_t appendHexPath(char* out, size_t n, const uint8_t* path, uint8_t len, uint8_t hash_size, const char* sep) {
  size_t pos = 0;
  if (n) out[0] = 0;
  for (uint8_t i = 0; i + hash_size <= len && pos + 8 < n; i += hash_size) {
    if (i) pos += snprintf(out + pos, n - pos, "%s", sep);
    for (uint8_t b = 0; b < hash_size; b++) pos += snprintf(out + pos, n - pos, "%02x", path[i + b]);
  }
  return pos;
}
}  // namespace

// Seconds since a route was last heard: this session's millis, else the saved RTC time; -1 if unknown.
long UmcService::routeAgeSecs(const UmcRoutes::Route& r) const {
  if (r.heard_ms != 0) return static_cast<long>((millis() - r.heard_ms) / 1000);
  uint32_t now = _host != nullptr ? _host->umcEpoch() : 0;
  if (r.heard_epoch > 1735689600UL && now >= r.heard_epoch) return static_cast<long>(now - r.heard_epoch);
  return -1;
}

void UmcService::formatTrafficJson(char* out, size_t out_size) const {
  size_t pos = snprintf(out, out_size, "{\"rx_total\":%lu,\"tx_total\":%lu,\"packets\":[",
                        static_cast<unsigned long>(umc_traffic.rxTotal()), static_cast<unsigned long>(umc_traffic.txTotal()));
  const uint32_t now = millis();
  for (int i = 0; i < umc_traffic.count() && pos + 120 < out_size; i++) {
    const UmcTraffic::Entry e = *umc_traffic.get(i);  // copy: the loop task may be writing
    pos += snprintf(out + pos, out_size - pos,
                    "%s{\"age\":%lu,\"tx\":%s,\"type\":\"%s\",\"flood\":%s,\"hops\":%u,\"rssi\":%d,\"snr\":%.2f,\"len\":%u}",
                    i ? "," : "", static_cast<unsigned long>((now - e.ms) / 1000), e.tx ? "true" : "false",
                    UmcTraffic::typeName(e.type), e.flood ? "true" : "false", e.hops, e.rssi, e.snr4 / 4.0f, e.len);
  }
  snprintf(out + pos, out_size - pos, "]}");
}

void UmcService::formatRoutesJson(char* out, size_t out_size) const {
  size_t pos = snprintf(out, out_size, "{\"routes\":[");
  UmcRoutes::Route r;
  bool first = true;
  for (int i = 0; i < UmcRoutes::kMaxRoutes && pos + 260 < out_size; i++) {
    if (!umc_routes.copy(i, r)) continue;
    char key[16], path[80], pin[80];
    appendHexPath(key, sizeof(key), r.key, UmcRoutes::kKeyBytes, 1, "");
    appendHexPath(path, sizeof(path), r.path, r.path_len, r.hash_size, ",");
    appendHexPath(pin, sizeof(pin), r.pin, r.pin_len, 1, ",");
    pos += snprintf(out + pos, out_size - pos, "%s{\"key\":\"%s\",\"name\":", first ? "" : ",", key);
    pos = appendJsonEscaped(out, out_size, pos, r.name);
    pos += snprintf(out + pos, out_size - pos,
                    ",\"type\":\"%s\",\"hops\":%u,\"hash\":%u,\"path\":\"%s\",\"pin\":\"%s\",\"snr\":%.2f,\"ago\":%ld,\"adverts\":%lu",
                    UmcRoutes::typeName(r.type), r.path_len / (r.hash_size ? r.hash_size : 1), r.hash_size, path, pin,
                    r.snr4 / 4.0f, routeAgeSecs(r), static_cast<unsigned long>(r.adverts));
    if (r.has_loc) pos += snprintf(out + pos, out_size - pos, ",\"lat\":%.4f,\"lon\":%.4f", r.lat, r.lon);
    pos += snprintf(out + pos, out_size - pos, "}");
    first = false;
  }
  snprintf(out + pos, out_size - pos, "]}");
}
#include "UmcWebServer.h"

#if defined(ESP_PLATFORM)
  #include <Preferences.h>
  #include <SPIFFS.h>
  #include <esp_system.h>
  #include <nvs_flash.h>
#endif

namespace {

bool startsWith(const char* s, const char* prefix) {
  return strncmp(s, prefix, strlen(prefix)) == 0;
}

bool parseOnOff(const char* v, bool& out) {
  while (*v == ' ') v++;
  if (strcmp(v, "on") == 0 || strcmp(v, "1") == 0 || strcmp(v, "true") == 0) {
    out = true;
    return true;
  }
  if (strcmp(v, "off") == 0 || strcmp(v, "0") == 0 || strcmp(v, "false") == 0) {
    out = false;
    return true;
  }
  return false;
}

const char* onOff(bool b) { return b ? "on" : "off"; }

void appendFeature(char* out, size_t out_size, size_t& pos, const char* name) {
  pos += snprintf(&out[pos], out_size > pos ? out_size - pos : 0, "%s\"%s\"", out[pos - 1] == '[' ? "" : ",", name);
}

}  // namespace

UmcService::UmcService()
    : _host(nullptr), _network(nullptr), _prefs{}, _web(nullptr), _telnet(nullptr), _updater(nullptr), _app(nullptr), _reboot_at(0),
#if defined(ESP_PLATFORM)
      _mb_lock(nullptr), _mb_done(nullptr),
#endif
      _mb_commands(nullptr), _mb_out(nullptr), _mb_out_size(0), _mb_pending(false), _mb_busy(false), _ota_prepare(false) {
  UmcPrefsStore::setDefaults(_prefs);
}

void UmcService::begin(UmcHost* host, NetworkService* network) {
  _host = host;
  _network = network;
  UmcPrefsStore::load(_prefs);
#if defined(ESP_PLATFORM)
  _mb_lock = xSemaphoreCreateMutex();
  _mb_done = xSemaphoreCreateBinary();
#endif
  if (_network != nullptr) {
    _network->setNodeName(_host->umcNodeName());
    _network->setDefaultApPassword(_prefs.pin);
  }
  applySetupState();

  _web = new UmcWebServer(*this);
  _telnet = new UmcTelnet(*this);
  _updater = new UmcUpdater(*this);
  _updater->begin();
  _app = new UmcAppServer(*this);
#if defined(ESP_PLATFORM)
  // begin() and loop() both run on the Arduino loop task, so this watches the whole mesh loop.
  esp_task_wdt_init(kLoopWatchdogSecs, true);
  esp_task_wdt_add(nullptr);
  UMC_LOGF("[UMC] last reset: %s\n", resetReasonLabel(esp_reset_reason()));
#endif

  UMC_LOGF("[UMC] %s v%s (%s, %s) setup=%s pin=%s\n", UMC_NAME, UMC_VERSION, _host->umcRole(),
                _host->umcFirmwareVersion(), isSetupMode() ? "pending" : "done", _prefs.pin);
}

void UmcService::applySetupState() {
  if (_network != nullptr) {
    _network->setSetupMode(isSetupMode());
  }
}

void UmcService::loop() {
#if defined(ESP_PLATFORM)
  esp_task_wdt_reset();
#endif
  processMailbox();
  if (_ota_prepare) {
    _ota_prepare = false;
    if (_host != nullptr) _host->umcPrepareForOta();
  }
  // Servers listen on every interface, so they survive WiFi reconnects and AP/STA changes.
  // Tearing them down on a short WiFi drop is what can stall the loop (httpd_stop waits for
  // its task), so once the network has been up they stay up until disabled in settings.
  if (_network != nullptr && _network->isNetworkReachable()) _net_seen = true;
  // update mode needs every byte for the secure download: no web page, telnet or app port
  const bool net = _net_seen && !(_updater != nullptr && _updater->inUpdateBoot());
  if (_web != nullptr) {
    _web->loop(_prefs.http_enabled && net);
  }
  if (_telnet != nullptr) {
    _telnet->loop(_prefs.telnet_enabled && net && !isDefaultAdminPassword() && !_quiet_servers);
  }
  if (_updater != nullptr) {
    _updater->loop(_network != nullptr && _network->isWifiConnected());
  }
  if (_app != nullptr) {
    _app->loop(_prefs.app_tcp && net && !_quiet_servers);
  }
  umc_routes.loop();
#if defined(ESP_PLATFORM)
  if (!_ota_confirmed && millis() > kOtaHealthyAfterMs) {
    _ota_confirmed = true;
    if (umcOtaPendingVerify()) {
      esp_ota_mark_app_valid_cancel_rollback();
      UMC_LOGLN("[UMC] new firmware ran healthily for 60 s - confirmed");
    }
  }
#endif
  if (_reboot_at != 0 && millis() >= _reboot_at) {
    _reboot_at = 0;
    UMC_LOGLN("[UMC] rebooting");
    if (_host != nullptr) _host->umcBeforeReboot();
    delay(100);
#if defined(ESP_PLATFORM)
    if (_rollback_requested) {
      esp_ota_mark_app_invalid_rollback_and_reboot();  // boots the other slot
    }
    esp_restart();
#endif
  }
}

void UmcService::setQuietServers(bool quiet) {
  _quiet_servers = quiet;
  if (quiet) {   // stop now: the download task starts straight away
    if (_telnet != nullptr) _telnet->loop(false);
    if (_app != nullptr) _app->loop(false);
  }
}

void UmcService::scheduleReboot(uint32_t delay_ms) {
  unsigned long at = millis() + delay_ms;
  _reboot_at = at == 0 ? 1 : at;
}

void UmcService::notifyOtaStarting() {
  _ota_prepare = true;  // called from the HTTP task; the host is notified on the loop task
}

bool UmcService::checkAdminPassword(const char* password) const {
  if (_host == nullptr || password == nullptr) return false;
  const char* admin = _host->umcAdminPassword();
  // constant-time compare
  size_t la = strlen(admin), lp = strlen(password);
  uint8_t diff = la != lp;
  for (size_t i = 0; i < lp; i++) {
    diff |= static_cast<uint8_t>(password[i] ^ (i < la ? admin[i] : 0));
  }
  return diff == 0 && la > 0;
}

bool UmcService::setLocalAdminPassword(const char* password) {
  if (password == nullptr) return false;
  size_t n = strlen(password);
  if (n < 8 || n >= sizeof(_prefs.admin_pw)) return false;
  strcpy(_prefs.admin_pw, password);
  return UmcPrefsStore::save(_prefs);
}

bool UmcService::isDefaultAdminPassword() const {
  if (_host == nullptr) return true;
  const char* admin = _host->umcAdminPassword();
  return admin[0] == 0 || strcmp(admin, "password") == 0;
}

size_t UmcService::appendJsonEscaped(char* out, size_t out_size, size_t pos, const char* text) {
  if (pos + 2 >= out_size) return pos;
  out[pos++] = '"';
  for (const char* p = text; p != nullptr && *p && pos + 8 < out_size; p++) {
    unsigned char c = static_cast<unsigned char>(*p);
    switch (c) {
      case '"': out[pos++] = '\\'; out[pos++] = '"'; break;
      case '\\': out[pos++] = '\\'; out[pos++] = '\\'; break;
      case '\n': out[pos++] = '\\'; out[pos++] = 'n'; break;
      case '\r': out[pos++] = '\\'; out[pos++] = 'r'; break;
      case '\t': out[pos++] = '\\'; out[pos++] = 't'; break;
      default:
        if (c < 0x20) {
          pos += snprintf(&out[pos], out_size - pos, "\\u%04x", c);
        } else {
          out[pos++] = static_cast<char>(c);
        }
    }
  }
  out[pos++] = '"';
  out[pos] = 0;
  return pos;
}

void UmcService::formatInfoJson(char* out, size_t out_size) const {
  size_t pos = snprintf(out, out_size, "{\"fw\":\"%s\",\"umc\":\"%s\",\"api\":%d,\"name\":", UMC_SHORT_NAME, UMC_VERSION,
                        UMC_API_VERSION);
  pos = appendJsonEscaped(out, out_size, pos, _host ? _host->umcNodeName() : "");
  pos += snprintf(&out[pos], out_size - pos, ",\"role\":\"%s\",\"ver\":", _host ? _host->umcRole() : "");
  pos = appendJsonEscaped(out, out_size, pos, _host ? _host->umcFirmwareVersion() : "");
  pos += snprintf(&out[pos], out_size - pos, ",\"build\":");
  pos = appendJsonEscaped(out, out_size, pos, _host ? _host->umcBuildDate() : "");
  pos += snprintf(&out[pos], out_size - pos, ",\"board\":");
  pos = appendJsonEscaped(out, out_size, pos, _host ? _host->umcBoardName() : "");
  pos += snprintf(&out[pos], out_size - pos, ",\"env\":\"%s\",\"commit\":\"%.7s\"", UmcUpdater::buildEnv(), UmcUpdater::buildCommit());
#if defined(ESP_PLATFORM)
  pos += snprintf(&out[pos], out_size - pos, ",\"reset\":\"%s\",\"heap\":{\"free\":%u,\"max_block\":%u,\"min_free\":%u}",
                  resetReasonLabel(esp_reset_reason()), ESP.getFreeHeap(), ESP.getMaxAllocHeap(), ESP.getMinFreeHeap());
#endif
  pos += snprintf(&out[pos], out_size - pos, ",\"setup\":%s,\"default_pw\":%s,\"features\":[",
                  isSetupMode() ? "true" : "false", isDefaultAdminPassword() ? "true" : "false");
  appendFeature(out, out_size, pos, "wifi");
  appendFeature(out, out_size, pos, "ota");
  appendFeature(out, out_size, pos, "telnet");
#ifdef WITH_MQTT_UPLINK
  appendFeature(out, out_size, pos, "mqtt");
#endif
#ifdef WITH_MQTT_BRIDGE
  appendFeature(out, out_size, pos, "mqtt_bridge");
#endif
#ifdef WITH_ESPNOW_BRIDGE
  appendFeature(out, out_size, pos, "espnow");
#endif
#ifdef WITH_RS232_BRIDGE
  appendFeature(out, out_size, pos, "rs232");
#endif
#if defined(WITH_ESPNOW_BRIDGE) || defined(WITH_RS232_BRIDGE) || defined(WITH_MQTT_BRIDGE)
  appendFeature(out, out_size, pos, "bridge");
#endif
#if ENV_INCLUDE_GPS == 1
  appendFeature(out, out_size, pos, "gps");
#endif
#ifdef DISPLAY_CLASS
  appendFeature(out, out_size, pos, "display");
#endif
#if defined(WITH_WEB_PANEL) && WITH_WEB_PANEL
  appendFeature(out, out_size, pos, "webstats");
#endif
#ifdef UMC_WITH_BLE
  appendFeature(out, out_size, pos, "ble");
#endif
  if (_webapp != nullptr) appendFeature(out, out_size, pos, "webapp");
#if defined(BOARD_HAS_PSRAM)
  appendFeature(out, out_size, pos, "psram");
#endif
  pos += snprintf(&out[pos], out_size - pos, "],\"net\":");
  if (_network != nullptr) {
    char net[640];
    _network->formatNetJson(net, sizeof(net));
    pos += snprintf(&out[pos], out_size - pos, "%s", net);
  } else {
    pos += snprintf(&out[pos], out_size - pos, "null");
  }
  snprintf(&out[pos], out_size - pos, "}");
}

bool UmcService::runBatch(const char* commands, char* out, size_t out_size, uint32_t timeout_ms) {
#if defined(ESP_PLATFORM)
  if (commands == nullptr || out == nullptr || out_size < 16) return false;
  if (xSemaphoreTake(_mb_lock, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) return false;
  _mb_commands = commands;
  _mb_out = out;
  _mb_out_size = out_size;
  xSemaphoreTake(_mb_done, 0);  // clear any stale signal
  _mb_pending = true;
  bool ok = xSemaphoreTake(_mb_done, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
  if (!ok) {
    // Loop task may be mid-way through this batch: never return (and let the caller
    // free its buffers) while it still holds pointers into them.
    _mb_pending = false;
    while (_mb_busy) {
      vTaskDelay(pdMS_TO_TICKS(20));
    }
  }
  _mb_commands = nullptr;
  _mb_out = nullptr;
  xSemaphoreGive(_mb_lock);
  return ok;
#else
  (void)commands; (void)out; (void)out_size; (void)timeout_ms;
  return false;
#endif
}

void UmcService::processMailbox() {
#if defined(ESP_PLATFORM)
  if (!_mb_pending) return;
  _mb_busy = true;
  _mb_pending = false;
  const char* cmds = _mb_commands;
  char* out = _mb_out;
  size_t out_size = _mb_out_size;
  if (cmds == nullptr || out == nullptr || _host == nullptr) {
    _mb_busy = false;
    return;
  }
  runCommandsNow(cmds, out, out_size);
  _mb_busy = false;
  xSemaphoreGive(_mb_done);
#endif
}

void UmcService::runCommandsNow(const char* cmds, char* out, size_t out_size) {
  if (_host == nullptr || out_size < 32) return;
  size_t pos = snprintf(out, out_size, "[");
  char line[kMaxCommandLen];
  char reply[kMaxReplyLen];
  const char* p = cmds;
  int count = 0;
  while (*p && count < 64) {
    const char* eol = strchr(p, '\n');
    size_t len = eol ? static_cast<size_t>(eol - p) : strlen(p);
    if (len >= sizeof(line)) len = sizeof(line) - 1;
    memcpy(line, p, len);
    line[len] = 0;
    if (len > 0 && line[len - 1] == '\r') line[len - 1] = 0;
    p = eol ? eol + 1 : p + strlen(p);
    if (line[0] == 0) continue;

    reply[0] = 0;
    if (strcmp(line, "reboot") == 0) {
      // Reply first; rebooting inline would drop the HTTP/telnet response.
      strcpy(reply, "OK - rebooting");
      scheduleReboot(1500);
    } else {
      _host->umcCommand(line, reply, sizeof(reply));
    }
    reply[sizeof(reply) - 1] = 0;
    if (count > 0 && pos + 1 < out_size) out[pos++] = ',';
    pos = appendJsonEscaped(out, out_size, pos, reply);
    count++;
    if (pos + 16 >= out_size) break;
  }
  if (pos + 2 < out_size) {
    out[pos++] = ']';
    out[pos] = 0;
  } else {
    snprintf(out, out_size, "[\"Err - reply too large\"]");
  }
}

// Desktop / app bridge: the same data as the web API, for a computer connected over USB or
// Bluetooth. Runs on the loop task. Requests: "info", "routes", "traffic", "scan",
// "scan refresh", "cli <commands>" (newline-separated). Writes JSON into out.
bool UmcService::handleBridge(const char* req, char* out, size_t out_size) {
  if (req == nullptr || out == nullptr || out_size < 32) return false;
  if (strcmp(req, "info") == 0) {
    formatInfoJson(out, out_size);
    size_t len = strlen(out);
    if (len > 1 && len + 32 < out_size) snprintf(&out[len - 1], out_size - len + 1, ",\"auth_required\":false,\"bridge\":true}");
    return true;
  }
  if (strcmp(req, "routes") == 0) { formatRoutesJson(out, out_size); return true; }
  if (strcmp(req, "traffic") == 0) { formatTrafficJson(out, out_size); return true; }
  if (strncmp(req, "scan", 4) == 0) {
#if defined(ESP_PLATFORM)
    if (_network != nullptr) {
      if (strstr(req, "refresh") != nullptr || WiFi.scanComplete() == WIFI_SCAN_FAILED) _network->startScan();
      _network->formatScanJson(out, out_size);
      return true;
    }
#endif
    snprintf(out, out_size, "[]");
    return true;
  }
  if (strncmp(req, "cli ", 4) == 0) {
    runCommandsNow(req + 4, out, out_size);
    return true;
  }
  snprintf(out, out_size, "{\"error\":\"unknown request\"}");
  return false;
}

bool UmcService::factoryReset() {
#if defined(ESP_PLATFORM)
  if (_host != nullptr) _host->umcBeforeReboot();
  SPIFFS.format();
  UmcPrefsStore::erase();
  Preferences nvs;
  if (nvs.begin("eastmesh-net", false)) {
    nvs.clear();
    nvs.end();
  }
  return true;
#else
  return false;
#endif
}

bool UmcService::handleCommand(const char* command, char* reply, size_t reply_size) {
  if (command == nullptr || reply == nullptr || reply_size == 0) return false;
  const NetworkService* net_c = _network;
  NetworkService* net = _network;

  // ---- identity / version ----
  if (strcmp(command, "get umc.version") == 0 || strcmp(command, "umc") == 0) {
    snprintf(reply, reply_size, "> %s %s (MeshCore %s, %s)", UMC_NAME, UMC_VERSION,
             _host ? _host->umcFirmwareVersion() : "?", _host ? _host->umcRole() : "?");
    return true;
  }

  // ---- setup mode ----
  if (strcmp(command, "get setup") == 0) {
    snprintf(reply, reply_size, "> %s", isSetupMode() ? "pending" : "done");
    return true;
  }
  if (strcmp(command, "setup start") == 0) {
    _prefs.setup_done = false;
    UmcPrefsStore::save(_prefs);
    applySetupState();
    snprintf(reply, reply_size, "OK - setup mode, join WiFi AP (password = PIN)");
    return true;
  }
  if (strcmp(command, "setup done") == 0) {
    if (isDefaultAdminPassword() || (_host && strlen(_host->umcAdminPassword()) < 8)) {
      snprintf(reply, reply_size, "Err - set an admin password (8+ chars) first");
      return true;
    }
    _prefs.setup_done = true;
    UmcPrefsStore::save(_prefs);
    applySetupState();
    snprintf(reply, reply_size, "OK - setup complete");
    return true;
  }

  // ---- PIN (AP password + BLE PIN) ----
  if (strcmp(command, "get pin") == 0) {
    snprintf(reply, reply_size, "> %s", _prefs.pin);
    return true;
  }
  if (startsWith(command, "set pin ")) {
    const char* v = command + 8;
    if (!UmcPrefsStore::isValidPin(v)) {
      snprintf(reply, reply_size, "Err - PIN must be 8 digits");
    } else {
      StrHelper::strncpy(_prefs.pin, v, sizeof(_prefs.pin));
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK - PIN updated (AP restarts with it)");
    }
    return true;
  }

  // ---- services ----
  if (strcmp(command, "get http") == 0) {
    snprintf(reply, reply_size, "> %s", onOff(_prefs.http_enabled));
    return true;
  }
  if (startsWith(command, "set http ")) {
    bool b;
    if (!parseOnOff(command + 9, b)) {
      snprintf(reply, reply_size, "Err - use on|off");
    } else {
      _prefs.http_enabled = b;
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }
  if (strcmp(command, "get http.timeout") == 0) {
    snprintf(reply, reply_size, "> %u", _prefs.session_timeout_min);
    return true;
  }
  if (startsWith(command, "set http.timeout ")) {
    int v = atoi(command + 17);
    if (v < 1 || v > 1440) {
      snprintf(reply, reply_size, "Err - 1..1440 minutes");
    } else {
      _prefs.session_timeout_min = static_cast<uint16_t>(v);
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }
  if (strcmp(command, "get app.tcp") == 0) {
    snprintf(reply, reply_size, "> %s", onOff(_prefs.app_tcp));
    return true;
  }
  if (startsWith(command, "set app.tcp ")) {
    bool b;
    if (!parseOnOff(command + 12, b)) {
      snprintf(reply, reply_size, "Err - use on|off");
    } else {
      _prefs.app_tcp = b;
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }
  if (strcmp(command, "get app.status") == 0) {
    snprintf(reply, reply_size, "> %s port:%u apps:%d", onOff(_prefs.app_tcp), _prefs.app_tcp_port,
             _app != nullptr ? _app->connectedCount() : 0);
    return true;
  }
  if (strcmp(command, "get telnet") == 0) {
    snprintf(reply, reply_size, "> %s", onOff(_prefs.telnet_enabled));
    return true;
  }
  if (startsWith(command, "set telnet ")) {
    bool b;
    if (!parseOnOff(command + 11, b)) {
      snprintf(reply, reply_size, "Err - use on|off");
    } else {
      _prefs.telnet_enabled = b;
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, b && isDefaultAdminPassword() ? "OK - starts once admin password is changed" : "OK");
    }
    return true;
  }
  if (strcmp(command, "get ble") == 0) {
    snprintf(reply, reply_size, "> %s", onOff(_prefs.ble_enabled));
    return true;
  }
  if (startsWith(command, "set ble ")) {
    bool b;
    if (!parseOnOff(command + 8, b)) {
      snprintf(reply, reply_size, "Err - use on|off");
    } else {
      _prefs.ble_enabled = b;
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK - reboot to apply");
    }
    return true;
  }
  if (strcmp(command, "get ble.idle") == 0) {
    snprintf(reply, reply_size, "> %u", _prefs.ble_idle_off_min);
    return true;
  }
  if (startsWith(command, "set ble.idle ")) {
    int v = atoi(command + 13);
    if (v < 0 || v > 1440) {
      snprintf(reply, reply_size, "Err - 0..1440 minutes (0 = never)");
    } else {
      _prefs.ble_idle_off_min = static_cast<uint16_t>(v);
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }

  // ---- OLED display cycle ----
  if (strcmp(command, "get display.mode") == 0) {
    static const char* const modes[] = {"cycle", "status", "off"};
    snprintf(reply, reply_size, "> %s", modes[_prefs.display_mode <= 2 ? _prefs.display_mode : 0]);
    return true;
  }
  if (startsWith(command, "set display.mode ")) {
    const char* v = command + 17;
    int m = strcmp(v, "cycle") == 0 ? 0 : strcmp(v, "status") == 0 ? 1 : strcmp(v, "off") == 0 ? 2 : -1;
    if (m < 0) {
      snprintf(reply, reply_size, "Err - use cycle|status|off");
    } else {
      _prefs.display_mode = static_cast<uint8_t>(m);
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }
  struct DisplayNum { const char* key; int min; int max; };
  static const DisplayNum display_nums[] = {
      {"display.timeout", 0, 3600}, {"display.ip", 0, 60}, {"display.page", 1, 60}, {"display.traffic", 0, 600}};
  for (const auto& dn : display_nums) {
    char get_key[32], set_key[32];
    snprintf(get_key, sizeof(get_key), "get %s", dn.key);
    snprintf(set_key, sizeof(set_key), "set %s ", dn.key);
    bool is_get = strcmp(command, get_key) == 0;
    bool is_set = startsWith(command, set_key);
    if (!is_get && !is_set) continue;
    uint16_t* u16 = nullptr;
    uint8_t* u8 = nullptr;
    if (strcmp(dn.key, "display.timeout") == 0) u16 = &_prefs.display_timeout_s;
    else if (strcmp(dn.key, "display.traffic") == 0) u16 = &_prefs.display_traffic_s;
    else if (strcmp(dn.key, "display.ip") == 0) u8 = &_prefs.display_ip_s;
    else u8 = &_prefs.display_page_s;
    if (is_get) {
      snprintf(reply, reply_size, "> %u", u16 ? *u16 : *u8);
    } else {
      int v = atoi(command + strlen(set_key));
      if (v < dn.min || v > dn.max) {
        snprintf(reply, reply_size, "Err - %d..%d seconds", dn.min, dn.max);
      } else {
        if (u16) *u16 = static_cast<uint16_t>(v); else *u8 = static_cast<uint8_t>(v);
        UmcPrefsStore::save(_prefs);
        snprintf(reply, reply_size, "OK");
      }
    }
    return true;
  }

  // ---- per-type flood hop caps (Low-Power firmware compatible names) ----
  if (strcmp(command, "get touch.map") == 0) {
    snprintf(reply, reply_size, "> %u", _prefs.touch_map);
    return true;
  }
  if (startsWith(command, "set touch.map ")) {
    int v = atoi(command + 14);
    if (v < 0 || v > 7) {
      snprintf(reply, reply_size, "Err - 0 to 7 (rotation/mirror of the touch panel)");
      return true;
    }
    _prefs.touch_map = static_cast<uint8_t>(v);
    UmcPrefsStore::save(_prefs);
    snprintf(reply, reply_size, "OK - touch mapping %d", v);
    return true;
  }
  if (strcmp(command, "get group.hops.max") == 0) {
    snprintf(reply, reply_size, "> %u", _prefs.group_hops_max);
    return true;
  }
  if (startsWith(command, "set group.hops.max ")) {
    int v = atoi(command + 19);
    if (v < 0 || v > 64) {
      snprintf(reply, reply_size, "Err - 0..64 (0 = never relay channel messages, 64 = no extra limit)");
    } else {
      _prefs.group_hops_max = static_cast<uint8_t>(v);
      UmcPrefsStore::save(_prefs);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }
  if ((strcmp(command, "get advert.hops.max") == 0 || startsWith(command, "set advert.hops.max ")) && _host != nullptr) {
    char alias[48];
    snprintf(alias, sizeof(alias), "%s flood.max.advert%s", command[0] == 'g' ? "get" : "set", command[0] == 'g' ? "" : command + 19);
    _host->umcCommand(alias, reply, reply_size);
    return true;
  }

  // ---- recent traffic ----
  if (strcmp(command, "get traffic") == 0) {
    size_t pos = snprintf(reply, reply_size, "> rx:%lu tx:%lu", static_cast<unsigned long>(umc_traffic.rxTotal()),
                          static_cast<unsigned long>(umc_traffic.txTotal()));
    for (int i = 0; i < umc_traffic.count() && pos + 28 < reply_size; i++) {
      const auto* e = umc_traffic.get(i);
      char line[32];
      UmcTraffic::formatShort(*e, line, sizeof(line));
      pos += snprintf(&reply[pos], reply_size - pos, "\n%lus %s", static_cast<unsigned long>((millis() - e->ms) / 1000), line);
    }
    return true;
  }

  // ---- routes learned from adverts, pinned routes, trace results ----
  if (strcmp(command, "routes") == 0 || strcmp(command, "get routes") == 0) {
    size_t pos = snprintf(reply, reply_size, "> %d node(s)", umc_routes.count());
    UmcRoutes::Route r;
    for (int i = 0; i < UmcRoutes::kMaxRoutes && pos + 40 < reply_size; i++) {
      if (!umc_routes.copy(i, r)) continue;
      pos += snprintf(reply + pos, reply_size - pos, "\n%02x%02x%02x %.12s h%u", r.key[0], r.key[1], r.key[2],
                      r.name[0] ? r.name : "?", r.path_len / (r.hash_size ? r.hash_size : 1));
    }
    return true;
  }
  if (startsWith(command, "route ")) {
    const char* arg = command + 6;
    while (*arg == ' ') arg++;
    char sub[8] = "";
    const char* rest = arg;
    for (const char* s : {"find ", "pin ", "unpin ", "forget "}) {
      if (startsWith(arg, s)) {
        StrHelper::strncpy(sub, s, sizeof(sub));
        rest = arg + strlen(s);
      }
    }
    char target[32];
    StrHelper::strncpy(target, rest, sizeof(target));
    char* space = strchr(target, ' ');
    const char* path_arg = "";
    if (space != nullptr && strcmp(sub, "pin ") == 0) {
      *space = 0;
      path_arg = rest + (space - target) + 1;
    }
    int idx = umc_routes.search(target);
    UmcRoutes::Route r;
    if (idx < 0 || !umc_routes.copy(idx, r)) {
      snprintf(reply, reply_size, "Err - no node matching '%s'", target);
      return true;
    }
    char key[16];
    snprintf(key, sizeof(key), "%02x%02x%02x%02x", r.key[0], r.key[1], r.key[2], r.key[3]);
    UmcRoutes::Route* entry = umc_routes.findHex(key);
    if (strcmp(sub, "pin ") == 0) {
      uint8_t path[UmcRoutes::kMaxPathBytes];
      int len = UmcRoutes::parsePath(path_arg, path, sizeof(path), 1);
      snprintf(reply, reply_size, len > 0 && umc_routes.setPin(entry, path, len) ? "OK - route pinned (used by 'trace route')"
                                                                                  : "Err - use: route pin <node> a1,b2,a1");
      return true;
    }
    if (strcmp(sub, "unpin ") == 0) {
      umc_routes.setPin(entry, nullptr, 0);
      snprintf(reply, reply_size, "OK - pinned route removed");
      return true;
    }
    if (strcmp(sub, "forget ") == 0) {
      umc_routes.forget(entry);
      snprintf(reply, reply_size, "OK - forgotten");
      return true;
    }
    // show / find
    char path[80], pin[80];
    appendHexPath(path, sizeof(path), r.path, r.path_len, r.hash_size, ">");
    appendHexPath(pin, sizeof(pin), r.pin, r.pin_len, 1, ",");
    snprintf(reply, reply_size, "> %s %s [%s] %s via %s snr:%.1f %lds ago%s%s", key, r.name[0] ? r.name : "?",
             UmcRoutes::typeName(r.type), r.path_len ? "heard" : "heard direct", r.path_len ? path : "-", r.snr4 / 4.0f,
             routeAgeSecs(r), r.pin_len ? " pinned:" : "", pin);
    return true;
  }
  if (strcmp(command, "get trace") == 0) {
    auto& t = umc_routes.trace();
    char path[80];
    appendHexPath(path, sizeof(path), t.path, t.path_len, t.hash_size, ",");
    switch (t.state) {
      case UmcRoutes::Trace::Idle:
        snprintf(reply, reply_size, "> idle");
        break;
      case UmcRoutes::Trace::Waiting:
        snprintf(reply, reply_size, "> waiting %lus path:%s", static_cast<unsigned long>((millis() - t.sent_ms) / 1000), path);
        break;
      case UmcRoutes::Trace::Timeout:
        snprintf(reply, reply_size, "> timeout path:%s (a hop didn't answer)", path);
        break;
      case UmcRoutes::Trace::Done: {
        size_t pos = snprintf(reply, reply_size, "> done %.1fs path:%s snr:", (t.done_ms - t.sent_ms) / 1000.0f, path);
        for (uint8_t i = 0; i < t.snr_count && pos + 8 < reply_size; i++) {
          pos += snprintf(reply + pos, reply_size - pos, "%s%.1f", i ? "," : "", t.snr4[i] / 4.0f);
        }
        snprintf(reply + pos, reply_size - pos, " final:%.1f", t.snr4[t.snr_count] / 4.0f);
        break;
      }
    }
    return true;
  }

  // ---- region presets (lowercase names match the public map / community catalogue) ----
  if (startsWith(command, "region preset")) {
    const char* v = command + 13;
    while (*v == ' ') v++;
    // Each preset: parent-first list, "name:parent" ("" parent = wildcard root).
    struct Preset { const char* id; const char* const* steps; };
    static const char* const yorkshire[] = {"yorkshire:", nullptr};
    static const char* const northwest[] = {"northwest:", nullptr};
    static const char* const uk[] = {"uk:", "yorkshire:uk", "northwest:uk", nullptr};
    static const Preset presets[] = {{"yorkshire", yorkshire}, {"northwest", northwest}, {"uk", uk}};
    const Preset* chosen = nullptr;
    for (const auto& p : presets) {
      if (strcmp(v, p.id) == 0) chosen = &p;
    }
    if (chosen == nullptr || _host == nullptr) {
      snprintf(reply, reply_size, "Err - presets: yorkshire | northwest | uk (then 'region save')");
      return true;
    }
    char cmd[64], r[160];
    int added = 0;
    for (const char* const* s = chosen->steps; *s != nullptr; s++) {
      char name[32];
      StrHelper::strncpy(name, *s, sizeof(name));
      char* colon = strchr(name, ':');
      const char* parent = "";
      if (colon) {
        *colon = 0;
        parent = colon + 1;
      }
      snprintf(cmd, sizeof(cmd), parent[0] ? "region put %s %s" : "region put %s", name, parent);
      r[0] = 0;
      _host->umcCommand(cmd, r, sizeof(r));
      snprintf(cmd, sizeof(cmd), "region allowf %s", name);
      r[0] = 0;
      _host->umcCommand(cmd, r, sizeof(r));
      added++;
    }
    snprintf(reply, reply_size, "OK - added %d region(s), flood allowed; run 'region save' to keep", added);
    return true;
  }

#if defined(ESP_PLATFORM)
  // ---- OTA slots / rollback ----
  if (strcmp(command, "get ota.state") == 0) {
    const esp_partition_t* running = esp_ota_get_running_partition();
    const esp_partition_t* other = esp_ota_get_next_update_partition(nullptr);
    esp_ota_img_states_t rs = ESP_OTA_IMG_UNDEFINED, os = ESP_OTA_IMG_UNDEFINED;
    if (running) esp_ota_get_state_partition(running, &rs);
    bool other_ok = other && esp_ota_get_state_partition(other, &os) == ESP_OK;
    esp_app_desc_t other_desc;
    bool other_app = other && esp_ota_get_partition_description(other, &other_desc) == ESP_OK;
    snprintf(reply, reply_size, "> running:%s (%s) other:%s (%s)%s%s", running ? running->label : "?", otaStateLabel(rs),
             other ? other->label : "?", other_ok ? otaStateLabel(os) : (other_app ? "has app" : "empty"),
             other_app ? " other_date:" : "", other_app ? other_desc.date : "");
    return true;
  }
  if (strcmp(command, "ota rollback") == 0) {
    if (!esp_ota_check_rollback_is_possible()) {
      snprintf(reply, reply_size, "Err - no previous firmware to roll back to");
    } else {
      snprintf(reply, reply_size, "OK - rolling back to the previous firmware");
      scheduleReboot(1500);
      _rollback_requested = true;
    }
    return true;
  }
#endif

  // ---- internet firmware update ----
  if (_updater != nullptr) {
    if (strcmp(command, "update check") == 0) {
      snprintf(reply, reply_size, _updater->startCheck() ? "OK - checking, then: get update.status" : "Err - busy");
      return true;
    }
    if (strcmp(command, "update install") == 0) {
      if (_network == nullptr || !_network->isWifiConnected()) {
        snprintf(reply, reply_size, "Err - needs WiFi with internet");
      } else {
        snprintf(reply, reply_size, _updater->startInstall() ? "OK - updating, device reboots when done" : "Err - busy");
      }
      return true;
    }
    if (strcmp(command, "get update.status") == 0) {
      _updater->formatStatus(reply, reply_size);
      return true;
    }
    if (strcmp(command, "get update.url") == 0) {
      snprintf(reply, reply_size, "> %s", _updater->url());
      return true;
    }
    if (startsWith(command, "set update.url ")) {
      snprintf(reply, reply_size, _updater->setUrl(command + 15) ? "OK" : "Err - must be an https:// URL");
      return true;
    }
    if (strcmp(command, "get update.auto") == 0) {
      snprintf(reply, reply_size, "> %s", UmcUpdater::autoModeLabel(_updater->autoMode()));
      return true;
    }
    if (startsWith(command, "set update.auto ")) {
      snprintf(reply, reply_size, _updater->setAutoMode(command + 16) ? "OK" : "Err - use off|check|install");
      return true;
    }
    if (strcmp(command, "get update.interval") == 0) {
      snprintf(reply, reply_size, "> %u", _updater->intervalHours());
      return true;
    }
    if (startsWith(command, "set update.interval ")) {
      snprintf(reply, reply_size, _updater->setIntervalHours(static_cast<uint16_t>(atoi(command + 20))) ? "OK" : "Err - 1..720 hours");
      return true;
    }
    if (strcmp(command, "get build") == 0) {
      snprintf(reply, reply_size, "> %s %s commit:%s", UMC_VERSION, UmcUpdater::buildEnv(), UmcUpdater::buildCommit());
      return true;
    }
  }

  // ---- factory reset ----
  if (strcmp(command, "factory reset") == 0) {
    snprintf(reply, reply_size, "Err - this erases identity & all settings; send 'factory reset confirm'");
    return true;
  }
  if (strcmp(command, "factory reset confirm") == 0) {
    factoryReset();
    snprintf(reply, reply_size, "OK - erased, rebooting");
    scheduleReboot(1500);
    return true;
  }

  if (net == nullptr) return false;

  // ---- WiFi networks (slots 1..3; slot 1 also answers to wifi.ssid / wifi.pwd) ----
  for (uint8_t slot = 2; slot <= NetworkService::kMaxNetworks; slot++) {
    char key[32];
    snprintf(key, sizeof(key), "get wifi.ssid%u", slot);
    if (strcmp(command, key) == 0) {
      snprintf(reply, reply_size, "> %s", net_c->getWifiSSIDSlot(slot)[0] ? net_c->getWifiSSIDSlot(slot) : "-");
      return true;
    }
    snprintf(key, sizeof(key), "get wifi.pwd%u", slot);
    if (strcmp(command, key) == 0) {
      snprintf(reply, reply_size, "> %s", net_c->hasWifiPasswordSlot(slot) ? "set" : "-");
      return true;
    }
    snprintf(key, sizeof(key), "set wifi.ssid%u ", slot);
    if (startsWith(command, key)) {
      snprintf(reply, reply_size, net->setWifiSSIDSlot(slot, command + strlen(key)) ? "OK" : "Err - bad ssid");
      return true;
    }
    snprintf(key, sizeof(key), "set wifi.pwd%u ", slot);
    if (startsWith(command, key)) {
      snprintf(reply, reply_size, net->setWifiPasswordSlot(slot, command + strlen(key)) ? "OK" : "Err - bad password");
      return true;
    }
  }
  // slot 1 (wifi.ssid / wifi.pwd) - every role: the setup wizard and the apps use these
  if (strcmp(command, "get wifi.ssid") == 0) {
    snprintf(reply, reply_size, "> %s", net_c->getWifiSSIDSlot(1)[0] ? net_c->getWifiSSIDSlot(1) : "-");
    return true;
  }
  if (startsWith(command, "set wifi.ssid ")) {
    snprintf(reply, reply_size, net->setWifiSSIDSlot(1, command + 14) ? "OK" : "Err - bad ssid");
    return true;
  }
  if (startsWith(command, "set wifi.pwd ")) {
    snprintf(reply, reply_size, net->setWifiPasswordSlot(1, command + 13) ? "OK" : "Err - bad password");
    return true;
  }
  if (strcmp(command, "get wifi.status") == 0) {
    net_c->formatWifiStatusReply(reply, reply_size);
    return true;
  }
  if (strcmp(command, "get wifi.powersaving") == 0) {
    snprintf(reply, reply_size, "> %s", net_c->getWifiPowerSave());
    return true;
  }
  if (startsWith(command, "set wifi.powersaving ")) {
    snprintf(reply, reply_size, net->setWifiPowerSave(command + 21) ? "OK" : "Err - use none|min|max");
    return true;
  }
  if (strcmp(command, "wifi reconnect") == 0) {
    net->forceReconnect();
    snprintf(reply, reply_size, "OK - wifi reconnecting");
    return true;
  }
  if (strcmp(command, "get wifi.pwd") == 0) {
    snprintf(reply, reply_size, "> %s", net_c->hasWifiPasswordSlot(1) ? "set" : "-");
    return true;
  }
  if (strcmp(command, "set wifi.ssid") == 0 || strcmp(command, "set wifi.pwd") == 0) {
    // allow clearing / open networks with an empty value
    snprintf(reply, reply_size, (command[9] == 's' ? net->setWifiSSIDSlot(1, "") : net->setWifiPasswordSlot(1, "")) ? "OK" : "Err");
    return true;
  }
  if (startsWith(command, "wifi clear ")) {
    int slot = atoi(command + 11);
    snprintf(reply, reply_size, net->clearWifiSlot(static_cast<uint8_t>(slot)) ? "OK" : "Err - slot 1..3");
    return true;
  }
  if (strcmp(command, "get wifi.networks") == 0) {
    snprintf(reply, reply_size, "> 1:%s 2:%s 3:%s", net_c->getWifiSSIDSlot(1)[0] ? net_c->getWifiSSIDSlot(1) : "-",
             net_c->getWifiSSIDSlot(2)[0] ? net_c->getWifiSSIDSlot(2) : "-",
             net_c->getWifiSSIDSlot(3)[0] ? net_c->getWifiSSIDSlot(3) : "-");
    return true;
  }
  if (strcmp(command, "wifi scan") == 0) {
    snprintf(reply, reply_size, net->startScan() ? "OK - scanning, then: get wifi.scan" : "Err - scan failed");
    return true;
  }
  if (strcmp(command, "get wifi.scan") == 0) {
    char json[512];
    net_c->formatScanJson(json, sizeof(json));
    snprintf(reply, reply_size, "> %s", json);
    return true;
  }
  if (strcmp(command, "get wifi.enabled") == 0) {
    snprintf(reply, reply_size, "> %s", onOff(net_c->isWifiEnabled()));
    return true;
  }
  if (startsWith(command, "set wifi.enabled ")) {
    bool b;
    if (!parseOnOff(command + 17, b)) {
      snprintf(reply, reply_size, "Err - use on|off");
    } else {
      net->setWifiEnabled(b);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }

  // ---- IP / hostname / mDNS ----
  if (strcmp(command, "get net.ip") == 0) {
    net_c->formatIpConfig(reply, reply_size);
    return true;
  }
  if (startsWith(command, "set net.ip ")) {
    snprintf(reply, reply_size, net->setIpConfig(command + 11) ? "OK" : "Err - use dhcp | <ip> <mask> <gw> [dns]");
    return true;
  }
  if (strcmp(command, "get net.hostname") == 0) {
    snprintf(reply, reply_size, "> %s", net_c->getHostname());
    return true;
  }
  if (startsWith(command, "set net.hostname")) {
    const char* v = command + 16;
    while (*v == ' ') v++;
    snprintf(reply, reply_size, net->setHostname(v) ? "OK" : "Err - letters, digits, '-' (max 32)");
    return true;
  }
  if (strcmp(command, "get net.mdns") == 0) {
    snprintf(reply, reply_size, "> %s", onOff(net_c->isMdnsEnabled()));
    return true;
  }
  if (startsWith(command, "set net.mdns ")) {
    bool b;
    if (!parseOnOff(command + 13, b)) {
      snprintf(reply, reply_size, "Err - use on|off");
    } else {
      net->setMdnsEnabled(b);
      snprintf(reply, reply_size, "OK");
    }
    return true;
  }
  if (strcmp(command, "get net.status") == 0) {
    char json[640];
    net_c->formatNetJson(json, sizeof(json));
    snprintf(reply, reply_size, "> %s", json);
    return true;
  }

  // ---- access point ----
  if (strcmp(command, "get ap.mode") == 0) {
    snprintf(reply, reply_size, "> %s", net_c->getApModeLabel());
    return true;
  }
  if (startsWith(command, "set ap.mode ")) {
    snprintf(reply, reply_size, net->setApMode(command + 12) ? "OK" : "Err - use auto|on|off");
    return true;
  }
  if (strcmp(command, "get ap.password") == 0) {
    snprintf(reply, reply_size, "> %s", net_c->hasCustomApPassword() ? "set" : "pin");
    return true;
  }
  if (startsWith(command, "set ap.password ")) {
    const char* v = command + 16;
    if (strcmp(v, "pin") == 0 || strcmp(v, "default") == 0) v = "";
    snprintf(reply, reply_size, net->setApPassword(v) ? "OK" : "Err - 8..63 chars, or 'pin'");
    return true;
  }
  if (strcmp(command, "get ap.rescue") == 0) {
    snprintf(reply, reply_size, "> %u", net_c->getApRescueSecs());
    return true;
  }
  if (startsWith(command, "set ap.rescue ")) {
    snprintf(reply, reply_size, net->setApRescueSecs(static_cast<uint16_t>(atoi(command + 14))) ? "OK" : "Err - 15..3600 s");
    return true;
  }
  if (strcmp(command, "get ap.status") == 0) {
    if (net_c->isApActive()) {
      snprintf(reply, reply_size, "> up ssid:%s ip:192.168.4.1 clients:%u", net_c->getApSsid(), net_c->getApClientCount());
    } else {
      snprintf(reply, reply_size, "> down mode:%s", net_c->getApModeLabel());
    }
    return true;
  }

  // ---- time zone (display / web only; mesh time stays UTC) ----
  if (strcmp(command, "get timezone") == 0) {
    snprintf(reply, reply_size, "> %s", net_c->getTimezone());
    return true;
  }
  if (startsWith(command, "set timezone ")) {
    snprintf(reply, reply_size, net->setTimezone(command + 13) ? "OK" : "Err - POSIX TZ string");
    return true;
  }

  return false;
}
