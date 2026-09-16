#include "UmcWebApp.h"

#include <string.h>

#if defined(ESP_PLATFORM)
  #include <esp_random.h>
#endif

UmcWebApp umc_webapp;

namespace {
constexpr uint8_t kPushMsgWaiting = 0x83;
constexpr uint8_t kPushLogRxData = 0x88;

int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}
}  // namespace

UmcWebApp::UmcWebApp()
    : _ring(nullptr), _head(0), _count(0), _seq(0), _boot(0), _inbox(nullptr), _in_head(0), _in_count(0), _enabled(false), _direct(false),
      _last_poll_ms(0)
#if defined(ESP_PLATFORM)
      , _lock(nullptr)
#endif
{
}

void UmcWebApp::begin() {
  if (_ring == nullptr) _ring = static_cast<Entry*>(calloc(kRing, sizeof(Entry)));
  if (_inbox == nullptr) _inbox = static_cast<Entry*>(calloc(kInbox, sizeof(Entry)));
#if defined(ESP_PLATFORM)
  if (_lock == nullptr) _lock = xSemaphoreCreateMutex();
  _boot = esp_random();
#endif
}

void UmcWebApp::lock() const {
#if defined(ESP_PLATFORM)
  if (_lock != nullptr) xSemaphoreTake(_lock, portMAX_DELAY);
#endif
}

void UmcWebApp::unlock() const {
#if defined(ESP_PLATFORM)
  if (_lock != nullptr) xSemaphoreGive(_lock);
#endif
}

void UmcWebApp::store(const uint8_t* frame, size_t len) {
  if (len == 0 || len > MAX_FRAME_SIZE || _ring == nullptr) return;
  lock();
  Entry& e = _ring[_head];
  e.seq = ++_seq;
  e.len = static_cast<uint8_t>(len);
  memcpy(e.buf, frame, len);
  _head = (_head + 1) % kRing;
  if (_count < kRing) _count++;
  unlock();
}

size_t UmcWebApp::writeFrame(const uint8_t src[], size_t len) {
  if (len == 0) return 0;
  // Replies to a browser command are kept whole. Otherwise keep only asynchronous pushes:
  // replies meant for a phone app (contact lists, sync responses) would flood the ring.
  if (_direct || (src[0] >= 0x80 && src[0] != kPushMsgWaiting && src[0] != kPushLogRxData)) {
    store(src, len);
  }
  return len;
}

void UmcWebApp::mirror(const uint8_t* frame, size_t len) {
  store(frame, len);
}

size_t UmcWebApp::takeFrame(uint8_t dest[]) {
  size_t len = 0;
  if (_inbox == nullptr) return 0;
  lock();
  if (_in_count > 0) {
    Entry& e = _inbox[_in_head];
    len = e.len;
    memcpy(dest, e.buf, len);
    _in_head = (_in_head + 1) % kInbox;
    _in_count--;
  }
  unlock();
  return len;
}

bool UmcWebApp::postHex(const char* hex) {
  if (hex == nullptr) return false;
  while (*hex == ' ' || *hex == '\n' || *hex == '\r') hex++;
  size_t n = strlen(hex);
  while (n > 0 && (hex[n - 1] == ' ' || hex[n - 1] == '\n' || hex[n - 1] == '\r')) n--;
  if (n < 2 || n % 2 != 0 || n / 2 > MAX_FRAME_SIZE) return false;
  uint8_t buf[MAX_FRAME_SIZE];
  for (size_t i = 0; i < n / 2; i++) {
    int hi = hexNibble(hex[i * 2]), lo = hexNibble(hex[i * 2 + 1]);
    if (hi < 0 || lo < 0) return false;
    buf[i] = static_cast<uint8_t>((hi << 4) | lo);
  }
  bool ok = false;
  if (_inbox == nullptr) return false;
  lock();
  if (_in_count < kInbox) {
    Entry& e = _inbox[(_in_head + _in_count) % kInbox];
    e.len = static_cast<uint8_t>(n / 2);
    memcpy(e.buf, buf, n / 2);
    _in_count++;
    ok = true;
  }
  _last_poll_ms = millis();
  unlock();
  return ok;
}

size_t UmcWebApp::formatSince(uint32_t since, char* out, size_t out_size) {
  if (_ring == nullptr) return snprintf(out, out_size, "{\"frames\":[],\"boot\":0,\"seq\":0,\"first\":1,\"more\":false}");
  lock();
  _last_poll_ms = millis();
  if (since > _seq) since = 0;  // device rebooted (browser shows boot change too)
  size_t pos = 0;
  int sent = 0;
  bool more = false;
  uint32_t last = since;
  const int oldest = (_head - _count + kRing) % kRing;
  pos = snprintf(out, out_size, "{\"frames\":[");
  for (int i = 0; i < _count; i++) {
    const Entry& e = _ring[(oldest + i) % kRing];
    if (e.seq <= since) continue;
    if (sent >= kMaxPerPoll || pos + e.len * 2 + 8 + 64 >= out_size) {
      more = true;
      break;
    }
    pos += snprintf(out + pos, out_size - pos, "%s\"", sent ? "," : "");
    for (int b = 0; b < e.len; b++) pos += snprintf(out + pos, out_size - pos, "%02x", e.buf[b]);
    pos += snprintf(out + pos, out_size - pos, "\"");
    last = e.seq;
    sent++;
  }
  // frames older than the ring are lost: tell the browser where the ring now starts
  uint32_t first = _count > 0 ? _ring[oldest].seq : _seq + 1;
  pos += snprintf(out + pos, out_size - pos, "],\"boot\":%lu,\"seq\":%lu,\"first\":%lu,\"more\":%s}",
                  static_cast<unsigned long>(_boot), static_cast<unsigned long>(sent ? last : (more ? since : _seq)),
                  static_cast<unsigned long>(first), more ? "true" : "false");
  unlock();
  return pos;
}
