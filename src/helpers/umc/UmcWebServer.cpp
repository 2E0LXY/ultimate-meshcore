#include "UmcWebServer.h"
#include "UmcLog.h"

#include "UmcService.h"
#include "UmcVersion.h"
#include "UmcWebApp.h"

#if defined(ESP_PLATFORM)
  #include <Update.h>
  #include <WiFi.h>
  #include <esp_app_format.h>
  #include <esp_random.h>
  #include <helpers/NetworkService.h>
  #include <lwip/sockets.h>

  #include "generated/umc_web_index.h"
#endif

#if defined(ESP_PLATFORM)
namespace {

constexpr size_t kCliBodyMax = 2048;   // the web UI sends at most 16 commands per request
constexpr size_t kCliReplyMax = 6144;
constexpr size_t kInfoMax = 1536;
constexpr size_t kOtaChunk = 4096;
constexpr unsigned long kLoginLockoutMs = 60UL * 1000UL;

void noopFree(void*) {}

UmcWebServer* self(httpd_req_t* req) {
  return static_cast<UmcWebServer*>(req->user_ctx);
}

bool readBody(httpd_req_t* req, char* buf, size_t buf_size) {
  if (req->content_len <= 0 || static_cast<size_t>(req->content_len) >= buf_size) return false;
  int remaining = req->content_len;
  int off = 0;
  while (remaining > 0) {
    int r = httpd_req_recv(req, buf + off, remaining);
    if (r == HTTPD_SOCK_ERR_TIMEOUT) continue;
    if (r <= 0) return false;
    off += r;
    remaining -= r;
  }
  buf[off] = 0;
  return true;
}

esp_err_t sendJson(httpd_req_t* req, const char* json, const char* status = nullptr) {
  if (status != nullptr) httpd_resp_set_status(req, status);
  httpd_resp_set_type(req, "application/json; charset=utf-8");
  return httpd_resp_sendstr(req, json);
}

}  // namespace

UmcWebServer::UmcWebServer(UmcService& umc)
    : _server(nullptr), _sessions{}, _login_failures(0), _login_locked_until(0), _ota_active(false), _umc(umc) {}

bool UmcWebServer::isRunning() const {
  return _server != nullptr;
}

void UmcWebServer::loop(bool enabled) {
  if (_ota_active) return;  // never tear down mid-upload
  if (enabled && _server == nullptr) {
    start();
  } else if (!enabled && _server != nullptr) {
    stop();
  }
  // expire idle sessions
  const unsigned long timeout_ms = static_cast<unsigned long>(_umc.prefs().session_timeout_min) * 60000UL;
  for (auto& s : _sessions) {
    if (s.token[0] && millis() - s.last_ms > timeout_ms) s.token[0] = 0;
  }
}

bool UmcWebServer::start() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = _umc.prefs().http_port;
  cfg.ctrl_port = 32770;  // distinct from any other httpd instance
  cfg.max_uri_handlers = 28;
  cfg.max_open_sockets = 5;
  cfg.lru_purge_enable = true;
  cfg.stack_size = 6144;
  cfg.recv_wait_timeout = 10;
  cfg.send_wait_timeout = 10;
  cfg.uri_match_fn = httpd_uri_match_wildcard;
  cfg.global_user_ctx = this;
  cfg.global_user_ctx_free_fn = noopFree;

  if (httpd_start(&_server, &cfg) != ESP_OK) {
    _server = nullptr;
    UMC_LOGLN("[UMC] http start failed");
    return false;
  }

  const httpd_uri_t routes[] = {
      {.uri = "/api/info", .method = HTTP_GET, .handler = handleInfo, .user_ctx = this},
      {.uri = "/api/login", .method = HTTP_POST, .handler = handleLogin, .user_ctx = this},
      {.uri = "/api/logout", .method = HTTP_POST, .handler = handleLogout, .user_ctx = this},
      {.uri = "/api/cli", .method = HTTP_POST, .handler = handleCli, .user_ctx = this},
      {.uri = "/api/scan", .method = HTTP_GET, .handler = handleScan, .user_ctx = this},
      {.uri = "/api/routes", .method = HTTP_GET, .handler = handleRoutes, .user_ctx = this},
      {.uri = "/api/traffic", .method = HTTP_GET, .handler = handleTraffic, .user_ctx = this},
      {.uri = "/api/app", .method = HTTP_GET, .handler = handleAppPoll, .user_ctx = this},
      {.uri = "/api/app", .method = HTTP_POST, .handler = handleAppPost, .user_ctx = this},
      {.uri = "/api/ota", .method = HTTP_POST, .handler = handleOta, .user_ctx = this},
      {.uri = "/generate_204", .method = HTTP_GET, .handler = handleCaptive, .user_ctx = this},
      {.uri = "/gen_204", .method = HTTP_GET, .handler = handleCaptive, .user_ctx = this},
      {.uri = "/hotspot-detect.html", .method = HTTP_GET, .handler = handleCaptive, .user_ctx = this},
      {.uri = "/connecttest.txt", .method = HTTP_GET, .handler = handleCaptive, .user_ctx = this},
      {.uri = "/ncsi.txt", .method = HTTP_GET, .handler = handleCaptive, .user_ctx = this},
      {.uri = "/", .method = HTTP_GET, .handler = handleIndex, .user_ctx = this},
      {.uri = "/index.html", .method = HTTP_GET, .handler = handleIndex, .user_ctx = this},
  };
  for (const auto& r : routes) {
    httpd_register_uri_handler(_server, &r);
  }
  httpd_register_err_handler(_server, HTTPD_404_NOT_FOUND, handleNotFound);
  UMC_LOGF("[UMC] web UI on port %u\n", cfg.server_port);
  return true;
}

void UmcWebServer::stop() {
  if (_server != nullptr) {
    httpd_stop(_server);
    _server = nullptr;
  }
}

void UmcWebServer::setCommonHeaders(httpd_req_t* req) {
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  httpd_resp_set_hdr(req, "X-Content-Type-Options", "nosniff");
  httpd_resp_set_hdr(req, "X-Frame-Options", "DENY");
}

const char* UmcWebServer::newSession() {
  Session* slot = &_sessions[0];
  for (auto& s : _sessions) {
    if (s.token[0] == 0) {
      slot = &s;
      break;
    }
    if (s.last_ms < slot->last_ms) slot = &s;  // evict least recently used
  }
  uint8_t raw[16];
  esp_fill_random(raw, sizeof(raw));
  for (int i = 0; i < 16; i++) {
    snprintf(&slot->token[i * 2], 3, "%02x", raw[i]);
  }
  slot->last_ms = millis();
  return slot->token;
}

void UmcWebServer::dropSession(const char* token) {
  for (auto& s : _sessions) {
    if (s.token[0] && strcmp(s.token, token) == 0) s.token[0] = 0;
  }
}

bool UmcWebServer::isSetupApRequest(httpd_req_t* req) const {
  if (!_umc.isSetupMode() || _umc.network() == nullptr || !_umc.network()->isApActive()) return false;
  int fd = httpd_req_to_sockfd(req);
  struct sockaddr_storage addr;
  socklen_t len = sizeof(addr);
  if (getsockname(fd, static_cast<struct sockaddr*>(static_cast<void*>(&addr)), &len) != 0) return false;
  uint32_t local = 0;
  if (addr.ss_family == AF_INET) {
    local = static_cast<struct sockaddr_in*>(static_cast<void*>(&addr))->sin_addr.s_addr;
  } else if (addr.ss_family == AF_INET6) {
    // IPv4-mapped IPv6 (::ffff:a.b.c.d)
    local = static_cast<struct sockaddr_in6*>(static_cast<void*>(&addr))->sin6_addr.un.u32_addr[3];
  }
  return local == static_cast<uint32_t>(WiFi.softAPIP());
}

bool UmcWebServer::isAuthorized(httpd_req_t* req) {
  if (isSetupApRequest(req)) return true;
  char token[40];
  if (httpd_req_get_hdr_value_str(req, "X-Auth-Token", token, sizeof(token)) != ESP_OK) return false;
  for (auto& s : _sessions) {
    if (s.token[0] && strcmp(s.token, token) == 0) {
      s.last_ms = millis();
      return true;
    }
  }
  return false;
}

esp_err_t UmcWebServer::handleIndex(httpd_req_t* req) {
  setCommonHeaders(req);
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  httpd_resp_set_hdr(req, "Content-Encoding", "gzip");
  return httpd_resp_send(req, static_cast<const char*>(static_cast<const void*>(umc_web_index_gz)), umc_web_index_gz_len);
}

esp_err_t UmcWebServer::handleCaptive(httpd_req_t* req) {
  httpd_resp_set_status(req, "302 Found");
  httpd_resp_set_hdr(req, "Location", "http://192.168.4.1/");
  setCommonHeaders(req);
  return httpd_resp_send(req, "", 0);
}

esp_err_t UmcWebServer::handleNotFound(httpd_req_t* req, httpd_err_code_t) {
  auto* s = static_cast<UmcWebServer*>(httpd_get_global_user_ctx(req->handle));
  if (s != nullptr && s->_umc.network() != nullptr && s->_umc.network()->isApActive() && strncmp(req->uri, "/api/", 5) != 0) {
    return handleCaptive(req);  // any unknown host/path from an AP client -> the app
  }
  httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Not found");
  return ESP_OK;
}

esp_err_t UmcWebServer::handleInfo(httpd_req_t* req) {
  auto* s = self(req);
  char* buf = static_cast<char*>(malloc(kInfoMax));
  if (buf == nullptr) return httpd_resp_send_500(req);
  s->_umc.formatInfoJson(buf, kInfoMax);
  // tell the client whether it needs to log in
  size_t len = strlen(buf);
  if (len > 1 && len + 32 < kInfoMax) {
    snprintf(&buf[len - 1], kInfoMax - len + 1, ",\"auth_required\":%s}", s->isAuthorized(req) ? "false" : "true");
  }
  setCommonHeaders(req);
  esp_err_t rc = sendJson(req, buf);
  free(buf);
  return rc;
}

esp_err_t UmcWebServer::handleLogin(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (millis() < s->_login_locked_until) {
    return sendJson(req, "{\"error\":\"Too many attempts - wait a minute\"}", "429 Too Many Requests");
  }
  char pwd[80];
  if (!readBody(req, pwd, sizeof(pwd))) {
    return sendJson(req, "{\"error\":\"Bad request\"}", "400 Bad Request");
  }
  if (!s->_umc.checkAdminPassword(pwd)) {
    if (++s->_login_failures >= 5) {
      s->_login_failures = 0;
      s->_login_locked_until = millis() + kLoginLockoutMs;
    }
    delay(400);  // slow brute force
    return sendJson(req, "{\"error\":\"Wrong password\"}", "401 Unauthorized");
  }
  if (s->_umc.isDefaultAdminPassword() && !s->isSetupApRequest(req)) {
    return sendJson(req, "{\"error\":\"Admin password is still the default. Change it over USB or the setup AP first.\"}",
                    "403 Forbidden");
  }
  s->_login_failures = 0;
  char json[64];
  snprintf(json, sizeof(json), "{\"token\":\"%s\"}", s->newSession());
  return sendJson(req, json);
}

esp_err_t UmcWebServer::handleLogout(httpd_req_t* req) {
  auto* s = self(req);
  char token[40];
  if (httpd_req_get_hdr_value_str(req, "X-Auth-Token", token, sizeof(token)) == ESP_OK) {
    s->dropSession(token);
  }
  setCommonHeaders(req);
  return sendJson(req, "{\"ok\":true}");
}

esp_err_t UmcWebServer::handleCli(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (!s->isAuthorized(req)) return sendJson(req, "{\"error\":\"Unauthorized\"}", "401 Unauthorized");

  char* body = static_cast<char*>(malloc(kCliBodyMax));
  char* out = static_cast<char*>(malloc(kCliReplyMax));
  if (body == nullptr || out == nullptr) {
    free(body);
    free(out);
    return httpd_resp_send_500(req);
  }
  esp_err_t rc;
  if (!readBody(req, body, kCliBodyMax)) {
    rc = sendJson(req, "{\"error\":\"Bad request\"}", "400 Bad Request");
  } else if (!s->_umc.runBatch(body, out, kCliReplyMax)) {
    rc = sendJson(req, "{\"error\":\"Device busy\"}", "503 Service Unavailable");
  } else {
    rc = sendJson(req, out);
  }
  free(body);
  free(out);
  return rc;
}

esp_err_t UmcWebServer::handleScan(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (!s->isAuthorized(req)) return sendJson(req, "{\"error\":\"Unauthorized\"}", "401 Unauthorized");
  NetworkService* net = s->_umc.network();
  if (net == nullptr) return sendJson(req, "[]");
  char q[16];
  bool refresh = httpd_req_get_url_query_str(req, q, sizeof(q)) == ESP_OK && strstr(q, "refresh") != nullptr;
  if (refresh || WiFi.scanComplete() == WIFI_SCAN_FAILED) {
    net->startScan();
  }
  char* buf = static_cast<char*>(malloc(3072));
  if (buf == nullptr) return httpd_resp_send_500(req);
  net->formatScanJson(buf, 3072);
  esp_err_t rc = sendJson(req, buf);
  free(buf);
  return rc;
}

esp_err_t UmcWebServer::handleRoutes(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (!s->isAuthorized(req)) return sendJson(req, "{\"error\":\"Unauthorized\"}", "401 Unauthorized");
  size_t max = 16384;
  char* buf = static_cast<char*>(malloc(max));
  if (buf == nullptr) {  // fragmented heap (Bluetooth + WiFi on boards without PSRAM): send what fits
    max = 4096;
    buf = static_cast<char*>(malloc(max));
  }
  if (buf == nullptr) return httpd_resp_send_500(req);
  s->_umc.formatRoutesJson(buf, max);
  esp_err_t rc = sendJson(req, buf);
  free(buf);
  return rc;
}

esp_err_t UmcWebServer::handleTraffic(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (!s->isAuthorized(req)) return sendJson(req, "{\"error\":\"Unauthorized\"}", "401 Unauthorized");
  char* buf = static_cast<char*>(malloc(3072));
  if (buf == nullptr) return httpd_resp_send_500(req);
  s->_umc.formatTrafficJson(buf, 3072);
  esp_err_t rc = sendJson(req, buf);
  free(buf);
  return rc;
}

// Companion browser link: GET /api/app?since=N returns queued protocol frames (hex).
esp_err_t UmcWebServer::handleAppPoll(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (!s->isAuthorized(req)) return sendJson(req, "{\"error\":\"Unauthorized\"}", "401 Unauthorized");
  UmcWebApp* app = s->_umc.webApp();
  if (app == nullptr) return sendJson(req, "{\"error\":\"Not available on this firmware\"}", "404 Not Found");
  char q[40], v[16];
  uint32_t since = 0;
  if (httpd_req_get_url_query_str(req, q, sizeof(q)) == ESP_OK && httpd_query_key_value(q, "since", v, sizeof(v)) == ESP_OK) {
    since = strtoul(v, nullptr, 10);
  }
  constexpr size_t kMax = 5120;  // UmcWebApp::kMaxPerPoll frames of up to 176 bytes as hex
  char* buf = static_cast<char*>(malloc(kMax));
  if (buf == nullptr) return httpd_resp_send_500(req);
  app->formatSince(since, buf, kMax);
  esp_err_t rc = sendJson(req, buf);
  free(buf);
  return rc;
}

// POST /api/app with one protocol frame per line (hex).
esp_err_t UmcWebServer::handleAppPost(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (!s->isAuthorized(req)) return sendJson(req, "{\"error\":\"Unauthorized\"}", "401 Unauthorized");
  UmcWebApp* app = s->_umc.webApp();
  if (app == nullptr) return sendJson(req, "{\"error\":\"Not available on this firmware\"}", "404 Not Found");
  char body[1536];
  if (!readBody(req, body, sizeof(body))) return sendJson(req, "{\"error\":\"Bad request\"}", "400 Bad Request");
  int accepted = 0;
  char* save = nullptr;
  for (char* line = strtok_r(body, "\n", &save); line != nullptr; line = strtok_r(nullptr, "\n", &save)) {
    if (!app->postHex(line)) break;
    accepted++;
  }
  char json[48];
  snprintf(json, sizeof(json), "{\"accepted\":%d}", accepted);
  return sendJson(req, json, accepted > 0 ? nullptr : "503 Service Unavailable");
}

esp_err_t UmcWebServer::handleOta(httpd_req_t* req) {
  auto* s = self(req);
  setCommonHeaders(req);
  if (!s->isAuthorized(req)) return sendJson(req, "{\"error\":\"Unauthorized\"}", "401 Unauthorized");
  if (req->content_len <= 0) return sendJson(req, "{\"error\":\"Empty upload\"}", "400 Bad Request");

  uint8_t* chunk = static_cast<uint8_t*>(malloc(kOtaChunk));
  if (chunk == nullptr) return httpd_resp_send_500(req);

  s->_ota_active = true;
  s->_umc.notifyOtaStarting();
  int remaining = req->content_len;
  bool started = false;
  const char* error = nullptr;

  while (remaining > 0) {
    int want = remaining > static_cast<int>(kOtaChunk) ? static_cast<int>(kOtaChunk) : remaining;
    int got = httpd_req_recv(req, static_cast<char*>(static_cast<void*>(chunk)), want);
    if (got == HTTPD_SOCK_ERR_TIMEOUT) continue;
    if (got <= 0) {
      error = "Upload interrupted";
      break;
    }
    if (!started) {
      // Validate: must be an ESP app image for this chip, not a merged/bootloader image.
      if (got < 64 || chunk[0] != ESP_IMAGE_HEADER_MAGIC) {
        error = "Not an ESP32 firmware image";
        break;
      }
      const auto* hdr = static_cast<const esp_image_header_t*>(static_cast<const void*>(chunk));
      if (hdr->chip_id != CONFIG_IDF_FIRMWARE_CHIP_ID) {
        error = "Firmware is for a different chip";
        break;
      }
      uint32_t app_magic;
      memcpy(&app_magic, chunk + sizeof(esp_image_header_t) + sizeof(esp_image_segment_header_t), sizeof(app_magic));
      if (app_magic != ESP_APP_DESC_MAGIC_WORD) {
        error = "This looks like a merged/full-flash image - upload the non-merged .bin";
        break;
      }
      char md5[33] = {0};
      if (httpd_req_get_hdr_value_str(req, "X-Firmware-MD5", md5, sizeof(md5)) == ESP_OK && strlen(md5) == 32) {
        Update.setMD5(md5);
      }
      if (!Update.begin(req->content_len, U_FLASH)) {
        error = "Not enough space for this image";
        break;
      }
      started = true;
      UMC_LOGF("[UMC] OTA upload %d bytes\n", req->content_len);
    }
    if (Update.write(chunk, got) != static_cast<size_t>(got)) {
      error = "Flash write failed";
      break;
    }
    remaining -= got;
  }
  free(chunk);

  if (error == nullptr && !Update.end(true)) {
    error = "Image verification failed";
  }
  if (error != nullptr) {
    if (started) Update.abort();
    s->_ota_active = false;
    UMC_LOGF("[UMC] OTA failed: %s\n", error);
    char json[160];
    snprintf(json, sizeof(json), "{\"error\":\"%s\"}", error);
    return sendJson(req, json, "400 Bad Request");
  }

  UMC_LOGLN("[UMC] OTA OK, rebooting");
  esp_err_t rc = sendJson(req, "{\"ok\":true,\"reboot\":true}");
  s->_umc.scheduleReboot(2000);
  return rc;
}

#else  // !ESP_PLATFORM

UmcWebServer::UmcWebServer(UmcService& umc) : _umc(umc) {}
void UmcWebServer::loop(bool) {}
bool UmcWebServer::isRunning() const { return false; }

#endif
