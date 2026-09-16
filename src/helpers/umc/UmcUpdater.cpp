#include "UmcUpdater.h"
#include "UmcLog.h"

#include <helpers/TxtDataHelpers.h>
#include <string.h>

#include "UmcService.h"
#include "UmcVersion.h"

#if defined(ESP_PLATFORM)
  #include <Preferences.h>
  #include <esp_http_client.h>
  #include <esp_https_ota.h>
  extern "C" esp_err_t esp_crt_bundle_attach(void* conf);
#endif

#ifndef UMC_ENV
  #define UMC_ENV "unknown"
#endif
#ifndef UMC_COMMIT
  #define UMC_COMMIT "unknown"
#endif
#ifndef UMC_UPDATE_URL
  #define UMC_UPDATE_URL "https://2e0lxy.github.io/ultimate-meshcore/"
#endif

namespace {
#ifdef UMC_UPDATE_DEBUG
constexpr uint32_t kFirstAutoCheckMs = 30UL * 1000UL;         // debug builds: check soon after boot
#else
constexpr uint32_t kFirstAutoCheckMs = 5UL * 60UL * 1000UL;  // a few minutes after boot
#endif
constexpr size_t kBuildsJsonMax = 8192;   // ~25 published builds

// Find "key": "value" at the top level of a small JSON text (no nesting needed here).
bool jsonString(const char* json, const char* key, char* out, size_t out_size) {
  char pat[48];
  snprintf(pat, sizeof(pat), "\"%s\"", key);
  const char* p = strstr(json, pat);
  if (p == nullptr) return false;
  p = strchr(p + strlen(pat), ':');
  if (p == nullptr) return false;
  p = strchr(p, '"');
  if (p == nullptr) return false;
  p++;
  size_t i = 0;
  while (*p && *p != '"' && i + 1 < out_size) out[i++] = *p++;
  out[i] = 0;
  return i > 0;
}
}  // namespace

UmcUpdater::UmcUpdater(UmcService& umc)
    : _umc(umc), _state(State::Idle), _install_after_check(false), _progress(-1), _error{0}, _latest_version{0},
      _latest_commit{0}, _url{0}, _auto_mode(1), _interval_h(24), _next_auto_ms(0), _task_running(false) {}

const char* UmcUpdater::buildEnv() { return UMC_ENV; }
const char* UmcUpdater::buildCommit() { return UMC_COMMIT; }

void UmcUpdater::begin() {
  StrHelper::strncpy(_url, UMC_UPDATE_URL, sizeof(_url));
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (nvs.begin("umc_upd", true)) {
    if (nvs.isKey("url")) nvs.getString("url", _url, sizeof(_url));
    _auto_mode = nvs.getUChar("auto", _auto_mode);
    _interval_h = nvs.getUShort("interval", _interval_h);
    nvs.end();
  }
#endif
  _next_auto_ms = millis() + kFirstAutoCheckMs;
}

void UmcUpdater::save() {
#if defined(ESP_PLATFORM)
  Preferences nvs;
  if (nvs.begin("umc_upd", false)) {
    nvs.putString("url", _url);
    nvs.putUChar("auto", _auto_mode);
    nvs.putUShort("interval", _interval_h);
    nvs.end();
  }
#endif
}

bool UmcUpdater::setUrl(const char* url) {
  if (url == nullptr || strncmp(url, "https://", 8) != 0 || strlen(url) >= sizeof(_url) - 1) return false;
  StrHelper::strncpy(_url, url, sizeof(_url) - 1);
  size_t n = strlen(_url);
  if (_url[n - 1] != '/') {
    _url[n] = '/';
    _url[n + 1] = 0;
  }
  save();
  return true;
}

const char* UmcUpdater::autoModeLabel(uint8_t mode) {
  return mode == 0 ? "off" : mode == 2 ? "install" : "check";
}

bool UmcUpdater::setAutoMode(const char* mode) {
  uint8_t m;
  if (strcmp(mode, "off") == 0) m = 0;
  else if (strcmp(mode, "check") == 0) m = 1;
  else if (strcmp(mode, "install") == 0) m = 2;
  else return false;
  _auto_mode = m;
  save();
  return true;
}

bool UmcUpdater::setIntervalHours(uint16_t h) {
  if (h < 1 || h > 720) return false;
  _interval_h = h;
  save();
  return true;
}

void UmcUpdater::setError(const char* msg) {
  StrHelper::strncpy(_error, msg, sizeof(_error));
  _state = State::Error;
  UMC_LOGF("[UMC] update: %s\n", msg);
}

void UmcUpdater::tlsBegin() {
  if (!_tls_held && _umc.host() != nullptr) {
    _umc.setQuietServers(true);
    _umc.host()->umcTlsBegin();
    _tls_held = true;
  }
}

void UmcUpdater::loop(bool network_up) {
  if (_tls_release && !_task_running) {
    _tls_release = false;
    if (_tls_held && _state != State::Done && _umc.host() != nullptr) {  // Done = rebooting
      _umc.host()->umcTlsEnd();
      _umc.setQuietServers(false);
    }
    _tls_held = false;
  }
  if (_state == State::Done && !_umc.isRebootPending()) {
    _umc.scheduleReboot(3000);
  }
  if (_auto_mode == 0 || !network_up || _task_running) return;
  if (millis() < _next_auto_ms) return;
  _next_auto_ms = millis() + static_cast<unsigned long>(_interval_h) * 3600000UL;
  _install_after_check = _auto_mode == 2;
  startCheck();
}

bool UmcUpdater::startCheck() {
#if defined(ESP_PLATFORM)
  if (_task_running) return false;
  _task_running = true;
  _state = State::Checking;
  tlsBegin();
  if (xTaskCreate(checkTask, "umc-upd-check", 8192, this, 1, nullptr) != pdPASS) {
    _task_running = false;
    _tls_release = true;
    setError("no memory for update task");
    return false;
  }
  return true;
#else
  return false;
#endif
}

bool UmcUpdater::startInstall() {
#if defined(ESP_PLATFORM)
  if (_task_running) return false;
  if (_state != State::Available) {
    _install_after_check = true;  // check first, then install if newer
    return startCheck();
  }
  _task_running = true;
  _state = State::Downloading;
  _progress = 0;
  _umc.notifyOtaStarting();
  tlsBegin();
  if (xTaskCreate(installTask, "umc-upd-ota", 8192, this, 1, nullptr) != pdPASS) {
    _task_running = false;
    _tls_release = true;
    setError("no memory for update task");
    return false;
  }
  return true;
#else
  return false;
#endif
}

#if defined(ESP_PLATFORM)
void UmcUpdater::checkTask(void* arg) {
  auto* self = static_cast<UmcUpdater*>(arg);
  bool newer = self->doCheck();
  bool install = self->_install_after_check && newer;
  self->_install_after_check = false;
  if (install) {
    self->_state = State::Downloading;
    self->_progress = 0;
    self->_umc.notifyOtaStarting();
    self->doInstall();
  }
  self->_tls_release = true;
  self->_task_running = false;
  vTaskDelete(nullptr);
}

void UmcUpdater::installTask(void* arg) {
  auto* self = static_cast<UmcUpdater*>(arg);
  self->doInstall();
  self->_tls_release = true;
  self->_task_running = false;
  vTaskDelete(nullptr);
}

bool UmcUpdater::doCheck() {
  char full[192];
  snprintf(full, sizeof(full), "%sbuilds.json", _url);

  esp_http_client_config_t cfg = {};
  cfg.url = full;
  cfg.timeout_ms = 15000;
  cfg.crt_bundle_attach = esp_crt_bundle_attach;
  esp_http_client_handle_t client = esp_http_client_init(&cfg);
  if (client == nullptr) {
    setError("http client init failed");
    return false;
  }
  char* body = static_cast<char*>(malloc(kBuildsJsonMax));
  if (body == nullptr) {
    esp_http_client_cleanup(client);
    setError("out of memory");
    return false;
  }
  bool ok = false;
  UMC_LOGF("[UMC] update check: heap free %u, largest block %u\n", (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getMaxAllocHeap());
  const esp_err_t open_err = esp_http_client_open(client, 0);
  if (open_err == ESP_OK) {
    esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);
    int total = 0;
    while (total < static_cast<int>(kBuildsJsonMax) - 1) {
      int n = esp_http_client_read(client, body + total, kBuildsJsonMax - 1 - total);
      if (n <= 0) break;
      total += n;
    }
    body[total] = 0;
    if (status != 200) {
      char msg[64];
      snprintf(msg, sizeof(msg), "server returned HTTP %d (is the repo public?)", status);
      setError(msg);
    } else {
      ok = true;
    }
  } else {
    // Say why: a DNS or connect failure is a network problem; a TLS failure with little free
    // memory is the device running short while making the secure connection.
    char msg[96];
    const unsigned free_kb = ESP.getFreeHeap() / 1024, block_kb = ESP.getMaxAllocHeap() / 1024;
    snprintf(msg, sizeof(msg), "can't reach update server (%s, %u KB free, largest %u KB)", esp_err_to_name(open_err), free_kb, block_kb);
    UMC_LOGF("[UMC] update check failed: %s\n", msg);
    setError(msg);
  }
  esp_http_client_close(client);
  esp_http_client_cleanup(client);

  if (!ok) {
    free(body);
    return false;
  }

  char env_pat[64];
  snprintf(env_pat, sizeof(env_pat), "\"env\": \"%s\"", buildEnv());
  bool has_env = strstr(body, env_pat) != nullptr;
  if (!jsonString(body, "commit", _latest_commit, sizeof(_latest_commit)) ||
      !jsonString(body, "version", _latest_version, sizeof(_latest_version))) {
    free(body);
    setError("unexpected builds.json");
    return false;
  }
  free(body);
  if (!has_env) {
    setError("no published build for this board/role");
    return false;
  }
  bool newer = strncmp(_latest_commit, buildCommit(), 7) != 0;
  _state = newer ? State::Available : State::UpToDate;
  UMC_LOGF("[UMC] update check: running %s, latest %s (%.7s) -> %s\n", buildCommit(), _latest_version,
                _latest_commit, newer ? "update available" : "up to date");
  return newer;
}

bool UmcUpdater::doInstall() {
  char full[192];
  snprintf(full, sizeof(full), "%sfirmware/%s/firmware.bin", _url, buildEnv());
  UMC_LOGF("[UMC] update: downloading %s\n", full);

  esp_http_client_config_t http = {};
  http.url = full;
  http.timeout_ms = 20000;
  http.buffer_size = 4096;
  http.buffer_size_tx = 1024;
  http.keep_alive_enable = true;
  http.crt_bundle_attach = esp_crt_bundle_attach;
  esp_https_ota_config_t ota = {};
  ota.http_config = &http;

  esp_https_ota_handle_t handle = nullptr;
  if (esp_https_ota_begin(&ota, &handle) != ESP_OK) {
    setError("download failed to start");
    return false;
  }
  esp_app_desc_t desc;
  if (esp_https_ota_get_img_desc(handle, &desc) != ESP_OK) {
    esp_https_ota_abort(handle);
    setError("downloaded file is not a firmware image");
    return false;
  }
  int total = esp_https_ota_get_image_size(handle);
  esp_err_t err;
  while ((err = esp_https_ota_perform(handle)) == ESP_ERR_HTTPS_OTA_IN_PROGRESS) {
    int got = esp_https_ota_get_image_len_read(handle);
    _progress = total > 0 ? (got * 100) / total : -1;
  }
  if (err != ESP_OK || !esp_https_ota_is_complete_data_received(handle)) {
    esp_https_ota_abort(handle);
    setError("download interrupted");
    return false;
  }
  if (esp_https_ota_finish(handle) != ESP_OK) {
    setError("image verification failed");
    return false;
  }
  _progress = 100;
  _state = State::Done;
  UMC_LOGLN("[UMC] update: installed, rebooting");
  return true;
}
#endif

void UmcUpdater::formatStatus(char* reply, size_t reply_size) const {
  switch (_state) {
    case State::Idle:
      snprintf(reply, reply_size, "> idle running:%s build:%.7s auto:%s", UMC_VERSION, buildCommit(), autoModeLabel(_auto_mode));
      break;
    case State::Checking:
      snprintf(reply, reply_size, "> checking");
      break;
    case State::UpToDate:
      snprintf(reply, reply_size, "> up-to-date running:%s build:%.7s", UMC_VERSION, buildCommit());
      break;
    case State::Available:
      snprintf(reply, reply_size, "> available latest:%s build:%.7s running:%s build:%.7s", _latest_version, _latest_commit,
               UMC_VERSION, buildCommit());
      break;
    case State::Downloading:
      snprintf(reply, reply_size, "> downloading %d%%", _progress);
      break;
    case State::Done:
      snprintf(reply, reply_size, "> installed - rebooting");
      break;
    case State::Error:
      snprintf(reply, reply_size, "> error %s", _error);
      break;
  }
}
