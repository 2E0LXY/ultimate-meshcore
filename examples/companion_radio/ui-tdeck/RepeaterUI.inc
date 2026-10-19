// ---------------------------------------------------------------- repeater page
// Included from the end of UITask.cpp, because it draws with that file's helpers.
//
// Opened from the Who tab by tapping a repeater. Three pages:
//   Status  log in with the admin password, then read the repeater's own counters
//   Path    the route messages take to it, a trace of every hop's signal, set or clear the route
//   Admin   run any command the repeater understands, with a list of the usual ones

struct RepCmd {
  const char* cmd;
  const char* what;
  uint8_t kind;   // 0 run now, 1 type the rest, 2 ask twice first
};

static const RepCmd kRepCmds[] = {
  {"ver", "firmware version", 0},
  {"board", "board name", 0},
  {"clock", "its clock", 0},
  {"clock sync", "set its clock from mine", 0},
  {"neighbors", "repeaters it hears", 0},
  {"advert", "send an advert now", 0},
  {"get name", "its name", 0},
  {"set name ", "rename it", 1},
  {"get radio", "frequency, bw, sf, cr", 0},
  {"set radio ", "freq,bw,sf,cr", 1},
  {"get tx", "transmit power", 0},
  {"set tx ", "power in dBm", 1},
  {"get repeat", "repeating on or off", 0},
  {"set repeat ", "on or off", 1},
  {"get lat", "latitude", 0},
  {"set lat ", "latitude", 1},
  {"get lon", "longitude", 0},
  {"set lon ", "longitude", 1},
  {"get advert.interval", "zero-hop advert, minutes", 0},
  {"set advert.interval ", "minutes", 1},
  {"get flood.advert.interval", "flood advert, hours", 0},
  {"set flood.advert.interval ", "hours", 1},
  {"get flood.max", "most hops a flood travels", 0},
  {"set flood.max ", "hops", 1},
  {"get path.hash.mode", "repeater id size", 0},
  {"set path.hash.mode ", "0, 1 or 2", 1},
  {"get loop.detect", "loop detection", 0},
  {"set loop.detect ", "off, minimal ...", 1},
  {"get dutycycle", "duty cycle limit", 0},
  {"set dutycycle ", "percent", 1},
  {"stats-core", "core statistics", 0},
  {"stats-radio", "radio statistics", 0},
  {"stats-packets", "packet statistics", 0},
  {"stats-rf", "recent noise floor spread", 0},
  {"get public.key", "its public key", 0},
  {"password ", "change the admin password", 1},
  {"set guest.password ", "set the guest password", 1},
  {"reboot", "restart it", 2},
  {"start ota", "open its update hotspot", 2},
};
static const int kRepCmdCount = sizeof(kRepCmds) / sizeof(kRepCmds[0]);

// The eight quick buttons on the Admin page.
struct RepQuick {
  const char* label;
  const char* cmd;
  bool confirm;
};
static const RepQuick kRepQuick[8] = {
  {"Ver", "ver", false},          {"Clock", "clock", false},       {"Neighbours", "neighbors", false}, {"Advert", "advert", false},
  {"Radio", "get radio", false},  {"Name", "get name", false},     {"Sync clock", "clock sync", false}, {"Reboot", "reboot", true},
};

static const char* repDuration(uint32_t s, char* b, size_t n) {
  if (s >= 86400UL) snprintf(b, n, "%lud %luh", (unsigned long)(s / 86400UL), (unsigned long)((s % 86400UL) / 3600UL));
  else if (s >= 3600UL) snprintf(b, n, "%luh %lum", (unsigned long)(s / 3600UL), (unsigned long)((s % 3600UL) / 60UL));
  else snprintf(b, n, "%lum %lus", (unsigned long)(s / 60UL), (unsigned long)(s % 60UL));
  return b;
}

// The repeater a hop id belongs to, by the start of its key. Several can share an id.
static void repHopName(const uint8_t* hash, int hsz, char* out, size_t n) {
  out[0] = 0;
  int found = 0;
  ContactInfo c;
  const int slots = the_mesh.getTotalContactSlots();
  for (int i = 0; i < slots; i++) {
    if (!the_mesh.getContactByIdx((uint32_t)i, c)) break;
    if (c.type != ADV_TYPE_REPEATER || c.name[0] == 0) continue;
    if (memcmp(c.id.pub_key, hash, hsz) == 0) {
      if (found == 0) snprintf(out, n, "%s", c.name);
      found++;
    }
  }
  if (found > 1) snprintf(out, n, "%d repeaters share it", found);
}

void UITask::openRepeater(int contact_idx) {
  ContactInfo c;
  if (!contactAt(contact_idx, c)) return;
  _rep.open(c);
  the_mesh.setRepeaterTap(&_rep);
  _rep_open = true;
  _rep_page = 0;
  _rep_list = false;
  _rep_edit = false;
  _rep_confirm = -1;
  _rep_rev_seen = _rep.rev - 1;
  _dirty = true;
}

void UITask::closeRepeater() {
  _rep.close();
  the_mesh.setRepeaterTap(nullptr);
  _rep_open = false;
  _rep_edit = false;
  _rep_list = false;
  _dirty = true;
}

void UITask::repeaterTick() {
  if (!_rep_open) return;
  const unsigned long now = millis();
  _rep.tick(now);
  if (_rep.login == RepeaterAdmin::LG_OK && !_rep.have_status && !_rep.status_wait && !_rep.status_tried) {
    _rep.status_tried = true;
    repStatus();                                   // read the status as soon as we are in
  }
  if (_rep_confirm >= 0 && now > _rep_confirm_until) {
    _rep_confirm = -1;
    _dirty = true;
  }
  if (_rep.rev != _rep_rev_seen) {
    _rep_rev_seen = _rep.rev;
    _dirty = true;
  }
  if (_tab == TAB_CONTACTS && _rep.waiting() && now >= _rep_next_tick) {   // the seconds counting up
    _rep_next_tick = now + 1000;
    _dirty = true;
  }
}

void UITask::repListScroll(int d) {
  const int max_scroll = kRepCmdCount > 5 ? kRepCmdCount - 5 : 0;
  _rep_list_scroll = constrain(_rep_list_scroll + d, 0, max_scroll);
  _dirty = true;
}

// ---- things the page can ask the repeater to do ----

void UITask::repLogin(const char* pw) {
  ContactInfo* live = the_mesh.lookupContactByPubKey(_rep.key, PUB_KEY_SIZE);
  if (live == NULL) { showAlert("Repeater not found", 1500); return; }
  uint32_t est = 0;
  const int r = the_mesh.sendLogin(*live, pw, est);
  if (r == MSG_SEND_FAILED) { showAlert("Could not send - try again", 1500); return; }
  _rep.loginSent(est);
  showAlert(r == MSG_SEND_SENT_FLOOD ? "Logging in (flood)..." : "Logging in...", 1200);
}

void UITask::repStatus() {
  ContactInfo* live = the_mesh.lookupContactByPubKey(_rep.key, PUB_KEY_SIZE);
  if (live == NULL) return;
  uint32_t tag = 0, est = 0;
  const int r = the_mesh.sendRequest(*live, REQ_TYPE_GET_STATUS, tag, est);
  if (r == MSG_SEND_FAILED) { showAlert("Could not send - try again", 1500); return; }
  _rep.statusSent(tag, est);
}

void UITask::repCli(const char* cmd) {
  if (_rep.login != RepeaterAdmin::LG_OK) { showAlert("Log in first", 1500); return; }
  ContactInfo* live = the_mesh.lookupContactByPubKey(_rep.key, PUB_KEY_SIZE);
  if (live == NULL) return;
  uint32_t est = 0;
  const uint32_t ts = rtc_clock.getCurrentTimeUnique();
  const int r = the_mesh.sendCommandData(*live, ts, 0, cmd, est);
  if (r == MSG_SEND_FAILED) { showAlert("Could not send - try again", 1500); return; }
  _rep.commandSent(cmd, est);
  _rep_page = 2;
}

void UITask::repTrace() {
  ContactInfo* live = the_mesh.lookupContactByPubKey(_rep.key, PUB_KEY_SIZE);
  if (live == NULL) return;
  uint32_t tag = 0, est = 0;
  switch (the_mesh.umcSendTrace(*live, tag, est)) {
    case 0: _rep.traceSent(tag, est); break;
    case 1: _rep.say("No route yet - log in or ask for status first"); break;
    case 2: _rep.say("A direct neighbour: nothing to trace"); break;
    case 3: _rep.say("Trace needs 1 or 2 byte ids and a shorter route"); break;
    default: _rep.say("Busy - try again"); break;
  }
}

// "a1,b2,c3" (or spaces, or >): the route messages to this repeater will take. Nothing clears it.
void UITask::repSetRoute(const char* text) {
  uint8_t hops[MAX_PATH_SIZE];
  int count = 0, hsz = 0;
  const char* p = text;
  while (*p) {
    while (*p == ' ' || *p == ',' || *p == '>') p++;
    if (!*p) break;
    int len = 0;
    const char* q = p;
    while (isxdigit((unsigned char)*q)) { q++; len++; }
    if (len == 0 || (len & 1) || len > 6) { _rep.say("Ids are 2, 4 or 6 hex digits, like a1,b2"); return; }
    const int sz = len / 2;
    if (hsz == 0) hsz = sz;
    else if (sz != hsz) { _rep.say("Every id must be the same length"); return; }
    if ((count + 1) * hsz > (int)sizeof(hops)) { _rep.say("That route is too long"); return; }
    for (int i = 0; i < sz; i++) {
      char hx[3] = {p[i * 2], p[i * 2 + 1], 0};
      hops[count * hsz + i] = (uint8_t)strtol(hx, NULL, 16);
    }
    count++;
    p = q;
    if (*p && *p != ' ' && *p != ',' && *p != '>') { _rep.say("Separate the ids with commas"); return; }
  }
  ContactInfo* live = the_mesh.lookupContactByPubKey(_rep.key, PUB_KEY_SIZE);
  if (live == NULL) return;
  if (the_mesh.umcSetRoute(*live, hops, count, hsz ? hsz : 1)) _rep.say(count ? "Route set" : "Route cleared - it floods next time");
  else _rep.say("Could not set that route");
}

void UITask::repEditStart(int what, const char* prompt, const char* preset, bool secret) {
  _rep_edit = true;
  _rep_edit_what = what;
  _rep_edit_secret = secret;
  StrHelper::strncpy(_rep_prompt, prompt, sizeof(_rep_prompt));
  StrHelper::strncpy(_rep_buf, preset, sizeof(_rep_buf));
  _rep_len = strlen(_rep_buf);
  _rep_secret_from = secret ? _rep_len : 9999;
  _dirty = true;
}

void UITask::repEditDone() {
  _rep_edit = false;
  switch (_rep_edit_what) {
    case 0: repLogin(_rep_buf); break;
    case 1: if (_rep_len > 0) repCli(_rep_buf); break;
    default: repSetRoute(_rep_buf); break;
  }
  _dirty = true;
}

// A row of the command list was tapped.
void UITask::repRun(int idx) {
  if (idx < 0 || idx >= kRepCmdCount) return;
  const RepCmd& rc = kRepCmds[idx];
  if (rc.kind == 1) {
    _rep_list = false;
    const bool secret = strstr(rc.cmd, "password") != NULL;
    repEditStart(1, rc.what, rc.cmd, secret);
  } else if (rc.kind == 2) {
    if (_rep_confirm == 100 + idx) {
      _rep_confirm = -1;
      _rep_list = false;
      repCli(rc.cmd);
    } else {
      _rep_confirm = 100 + idx;
      _rep_confirm_until = millis() + 4000;
      showAlert("Tap again to confirm", 1500);
    }
  } else {
    _rep_list = false;
    repCli(rc.cmd);
  }
  _dirty = true;
}

// ---- drawing ----

void UITask::drawRepeater() {
  const int top = BODY_Y;
  const int cy = top + 50;
  const int by = SCR_H - TAB_H - 26;
  ContactInfo* live = the_mesh.lookupContactByPubKey(_rep.key, PUB_KEY_SIZE);
  if (live == NULL) {
    closeRepeater();
    return;
  }
  const ContactInfo& c = *live;
  fill(0, top, SCR_W, BODY_H, C_BG);
  drawIcon(6, top + 5, kindIcon(c.type), kindColour(c.type), 13);
  textFClip(24, top + 3, SCR_W - 30, c.name[0] ? c.name : "(repeater)", C_TXT, F_MED);

  static const char* const pages[3] = {"Status", "Path", "Admin"};
  for (int i = 0; i < 3; i++) button(2 + i * 62, top + 26, 60, 18, pages[i], _rep_page == i);

  char chip[40];
  uint16_t chip_c = C_WARN;
  switch (_rep.login) {
    case RepeaterAdmin::LG_OK:
      snprintf(chip, sizeof(chip), "logged in (%s)", _rep.role >= 3 ? "admin" : _rep.role == 2 ? "read-write" : _rep.role == 1 ? "read-only" : "guest");
      chip_c = C_OK;
      break;
    case RepeaterAdmin::LG_SENT: snprintf(chip, sizeof(chip), "logging in..."); chip_c = C_ACC; break;
    case RepeaterAdmin::LG_FAIL: snprintf(chip, sizeof(chip), "login failed"); chip_c = C_BAD; break;
    default: snprintf(chip, sizeof(chip), "not logged in"); break;
  }
  textClip(192, top + 29, SCR_W - 194, chip, chip_c);

  char buf[96];

  if (_rep_list) {                                   // the command list replaces the page
    const int row_h = 20, rows = 5;
    for (int r = 0; r < rows; r++) {
      const int idx = _rep_list_scroll + r;
      if (idx >= kRepCmdCount) break;
      const RepCmd& rc = kRepCmds[idx];
      const int y = cy + 2 + r * row_h;
      fill(0, y, SCR_W, row_h - 2, _rep_confirm == 100 + idx ? C_WARN : C_CARD);
      textClip(6, y + 4, 142, rc.cmd, rc.kind == 2 ? C_WARN : C_TXT);
      textClip(150, y + 4, SCR_W - 156, _rep_confirm == 100 + idx ? "tap again to confirm" : rc.what, C_DIM);
    }
    snprintf(buf, sizeof(buf), "%d-%d of %d  (drag or roll to scroll)", _rep_list_scroll + 1,
             min(_rep_list_scroll + rows, kRepCmdCount), kRepCmdCount);
    text(6, by + 7, buf, C_DIM);
    button(236, by, 80, 22, "< Back");
    return;
  }

  if (_rep_page == 0) {
    // ---- Status ----
    if (_rep.login != RepeaterAdmin::LG_OK) {
      if (_rep.login == RepeaterAdmin::LG_SENT) {
        text(8, cy + 6, "Logging in...", C_ACC);
      } else {
        text(8, cy + 6, "Log in to read this repeater's status and", C_TXT);
        text(8, cy + 19, "change its settings. Tap Log in and enter the", C_TXT);
        text(8, cy + 32, "admin password (a new repeater uses 'password').", C_TXT);
      }
      if (_rep.note[0]) textClip(8, cy + 56, 304, _rep.note, C_BAD);
    } else if (!_rep.have_status) {
      if (_rep.status_wait) text(8, cy + 6, "Asking for status...", C_ACC);
      else text(8, cy + 6, _rep.note[0] ? _rep.note : "Tap Refresh to ask for status.", _rep.note[0] ? C_BAD : C_DIM);
    } else {
      const RepeaterAdmin::Stats& s = _rep.st;
      char v[32], d[16];
      int y = cy + 2;
      auto row = [&](int x, const char* label, const char* value, uint16_t col) {
        text(x, y, label, C_DIM);
        textClip(x + 66, y, 88, value, col);
      };
      // left column
      if (s.batt_milli_volts) snprintf(v, sizeof(v), "%d.%02d V", s.batt_milli_volts / 1000, (s.batt_milli_volts % 1000) / 10);
      else snprintf(v, sizeof(v), "--");
      row(6, "Battery", v, s.batt_milli_volts && s.batt_milli_volts < 3500 ? C_BAD : C_TXT); y += 13;
      row(6, "Uptime", repDuration(s.total_up_time_secs, d, sizeof(d)), C_TXT); y += 13;
      snprintf(v, sizeof(v), "%d dBm", s.noise_floor); row(6, "Noise", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%d dBm", s.last_rssi); row(6, "Last RSSI", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%.1f dB", s.last_snr / 4.0f); row(6, "Last SNR", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%u", (unsigned)s.curr_tx_queue_len); row(6, "Tx queue", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%u / %lu", (unsigned)s.err_events, (unsigned long)s.n_recv_errors);
      row(6, "Errors", v, s.err_events ? C_WARN : C_TXT);
      // right column
      y = cy + 2;
      snprintf(v, sizeof(v), "%lu", (unsigned long)s.n_packets_recv); row(162, "Heard", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%lu", (unsigned long)s.n_packets_sent); row(162, "Sent", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%lu / %lu", (unsigned long)s.n_sent_flood, (unsigned long)s.n_sent_direct); row(162, "Sent f/d", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%lu / %lu", (unsigned long)s.n_recv_flood, (unsigned long)s.n_recv_direct); row(162, "Heard f/d", v, C_TXT); y += 13;
      snprintf(v, sizeof(v), "%u / %u", (unsigned)s.n_direct_dups, (unsigned)s.n_flood_dups); row(162, "Dups d/f", v, C_TXT); y += 13;
      row(162, "Air time tx", repDuration(s.total_air_time_secs, d, sizeof(d)), C_TXT); y += 13;
      row(162, "Air time rx", repDuration(s.total_rx_air_time_secs, d, sizeof(d)), C_TXT);
      char age[12];
      snprintf(buf, sizeof(buf), "Updated %s ago", shortAge((millis() - _rep.status_at) / 1000, age, sizeof(age)));
      text(6, cy + 2 + 7 * 13, buf, C_DIM);
    }
    button(2, by, 74, 22, "Log in");
    button(80, by, 74, 22, "Refresh");
    button(158, by, 74, 22, "Details");
    button(236, by, 80, 22, "< Back");
  } else if (_rep_page == 1) {
    // ---- Path ----
    text(6, cy + 2, "Route", C_DIM);
    if (c.out_path_len == OUT_PATH_UNKNOWN) {
      text(64, cy + 2, "flood (no route learned yet)", C_WARN);
    } else {
      const int hops = c.out_path_len & 63;
      const int hsz = 1 + (c.out_path_len >> 6);
      if (hops == 0) {
        text(64, cy + 2, "direct (a neighbour)", C_OK);
      } else {
        snprintf(buf, sizeof(buf), "%d hop%s, %d-byte ids", hops, hops == 1 ? "" : "s", hsz);
        text(64, cy + 2, buf, C_OK);
        size_t pos = 0;
        buf[0] = 0;
        for (int i = 0; i < hops && pos + 8 < sizeof(buf); i++) {
          if (i) pos += snprintf(&buf[pos], sizeof(buf) - pos, " > ");
          for (int b = 0; b < hsz; b++) pos += snprintf(&buf[pos], sizeof(buf) - pos, "%02X", c.out_path[i * hsz + b]);
        }
        textClip(6, cy + 15, 308, buf, C_ACC);
      }
    }
    text(6, cy + 32, "Trace", C_DIM);
    if (_rep.trace_wait) {
      snprintf(buf, sizeof(buf), "waiting for it to come back... %lus", (unsigned long)((millis() - _rep.trace_sent) / 1000));
      text(64, cy + 32, buf, C_ACC);
    } else if (_rep.trace_have) {
      const int all = _rep.trace_n + (_rep.trace_final ? 1 : 0);
      if (all > 5) snprintf(buf, sizeof(buf), "done in %.1f s (first 5 of %d)", _rep.trace_took_ms / 1000.0f, all);
      else snprintf(buf, sizeof(buf), "done in %.1f s", _rep.trace_took_ms / 1000.0f);
      text(64, cy + 32, buf, C_OK);
    } else if (_rep.note[0]) {
      textClip(64, cy + 32, 250, _rep.note, C_BAD);
    } else {
      text(64, cy + 32, "tap Trace to test every hop", C_DIM);
    }
    if (_rep.trace_have) {
      const int rows = 5;
      const int total = _rep.trace_n + (_rep.trace_final ? 1 : 0);
      for (int i = 0; i < total && i < rows; i++) {
        const int y = cy + 45 + i * 12;
        const bool is_back = i == _rep.trace_n;
        const float snr = is_back ? _rep.trace_final4 / 4.0f : _rep.trace_snr4[i] / 4.0f;
        snprintf(buf, sizeof(buf), "%d", i + 1);
        text(6, y, buf, C_DIM);
        if (is_back) {
          text(22, y, "back to me", C_TXT);
        } else {
          char id[8] = {0};
          for (int b = 0; b < _rep.trace_hsz && b < 3; b++) snprintf(&id[b * 2], 3, "%02X", _rep.trace_hash[i * _rep.trace_hsz + b]);
          text(22, y, id, C_ACC);
          char nm[40];
          repHopName(&_rep.trace_hash[i * _rep.trace_hsz], _rep.trace_hsz, nm, sizeof(nm));
          textClip(62, y, 180, nm[0] ? nm : "(not in your contacts)", nm[0] ? C_TXT : C_DIM);
        }
        snprintf(buf, sizeof(buf), "%.1f dB", snr);
        text(252, y, buf, snr >= 5 ? C_OK : snr > -5 ? C_WARN : C_BAD);
      }
    }
    button(2, by, 74, 22, "Trace");
    button(80, by, 74, 22, "Set route");
    button(158, by, 74, 22, "Reset");
    button(236, by, 80, 22, "< Back");
  } else {
    // ---- Admin ----
    fill(4, cy, 312, 50, C_CARD);
    gfx()->drawRect(4, cy, 312, 50, C_LINE);
    // what has been said, wrapped, the newest lines at the bottom
    char lines[12][64];
    int n = 0;
    const char* p = _rep.out;
    while (*p && n < 12) {
      const char* nl = strchr(p, '\n');
      int seg = nl ? (int)(nl - p) : (int)strlen(p);
      char one[160];
      if (seg > (int)sizeof(one) - 1) seg = sizeof(one) - 1;
      memcpy(one, p, seg);
      one[seg] = 0;
      p += seg;
      if (*p == '\n') p++;
      int pos = 0;                                       // wrap this paragraph to the box width
      do {
        int take = strlen(one + pos);
        if (take > (int)sizeof(lines[0]) - 1) take = sizeof(lines[0]) - 1;
        char probe[64];
        memcpy(probe, one + pos, take);
        probe[take] = 0;
        while (take > 1 && textWidth(probe) > 298) probe[--take] = 0;
        memcpy(lines[n], one + pos, take);
        lines[n][take] = 0;
        n++;
        pos += take;
      } while (one[pos] && n < 12);
    }
    if (n == 0) {
      text(10, cy + 6, _rep.login == RepeaterAdmin::LG_OK ? "Run a command below, or tap Command to type one." : "Log in first (Log in, bottom row).", C_DIM);
    } else {
      const int show = 4;
      const int first = n > show ? n - show : 0;
      for (int i = first; i < n; i++) {
        const bool echo = lines[i][0] == '>' && lines[i][1] == ' ';
        textClip(10, cy + 3 + (i - first) * 12, 298, lines[i], echo ? C_ACC : C_TXT);
      }
    }
    for (int i = 0; i < 8; i++) {
      const int x = 2 + (i % 4) * 79;
      const int y = cy + 54 + (i / 4) * 20;
      const bool sure = kRepQuick[i].confirm && _rep_confirm == i;
      button(x, y, 76, 18, sure ? "Sure?" : kRepQuick[i].label, sure);
    }
    if (_rep.cli_wait) text(8, cy + 98, "waiting for the repeater...", C_ACC);
    else if (_rep.note[0]) textClip(8, cy + 98, 304, _rep.note, C_BAD);
    button(2, by, 74, 22, "Command");
    button(80, by, 74, 22, "List");
    button(158, by, 74, 22, "Log in");
    button(236, by, 80, 22, "< Back");
  }

  if (_rep_edit) {                                   // typing a password, command or route
    const int y0 = cy;
    fill(4, y0, 312, 112, C_CARD);
    gfx()->drawRect(4, y0, 312, 112, C_ACC);
    textClip(10, y0 + 6, 300, _rep_prompt, C_DIM);
    fill(10, y0 + 22, 300, 22, C_BG);
    gfx()->drawRect(10, y0 + 22, 300, 22, C_LINE);
    char shown[80];
    for (int i = 0; i < _rep_len && i < (int)sizeof(shown) - 1; i++) shown[i] = i >= _rep_secret_from ? '*' : _rep_buf[i];
    shown[_rep_len < (int)sizeof(shown) - 1 ? _rep_len : (int)sizeof(shown) - 1] = 0;
    const char* tail = shown;
    while (tail[0] != 0 && textWidth(tail) > 284) tail++;
    text(14, y0 + 28, tail, C_TXT);
    fill(15 + textWidth(tail), y0 + 26, 2, 12, C_ACC);
    text(10, y0 + 52, "Enter sends, Esc cancels", C_DIM);
    if (_rep_edit_what == 0) text(10, y0 + 66, "A new repeater uses the password 'password'.", C_DIM);
    else if (_rep_edit_what == 2) text(10, y0 + 66, "Leave it empty to clear the route (it floods).", C_DIM);
    button(150, y0 + 86, 80, 22, "Send");
    button(234, y0 + 86, 76, 22, "Cancel");
  }
}

// ---- touch and keys ----

bool UITask::repeaterTouch(const TouchEvent& ev) {
  const int top = BODY_Y;
  const int cy = top + 50;
  const int by = SCR_H - TAB_H - 26;

  if (_rep_edit) {
    if (hit(ev, 150, cy + 86, 80, 22)) { repEditDone(); return true; }
    if (hit(ev, 234, cy + 86, 76, 22)) { _rep_edit = false; _dirty = true; return true; }
    return true;
  }

  if (_rep_list) {
    const int row_h = 20, rows = 5;
    if (hit(ev, 236, by, 80, 22)) { _rep_list = false; _rep_confirm = -1; _dirty = true; return true; }
    if (ev.released && ev.y >= cy + 2 && ev.y < cy + 2 + rows * row_h && abs(ev.y - ev.start_y) < 12) {
      repRun(_rep_list_scroll + (ev.y - (cy + 2)) / row_h);
      return true;
    }
    if (ev.down && ev.dy) repListScroll(ev.dy > 0 ? -1 : 1);
    return true;
  }

  for (int i = 0; i < 3; i++) {
    if (hit(ev, 2 + i * 62, top + 26, 60, 18)) { _rep_page = i; _dirty = true; return true; }
  }

  if (hit(ev, 236, by, 80, 22)) { closeRepeater(); return true; }

  if (_rep_page == 0) {
    if (hit(ev, 2, by, 74, 22)) { repEditStart(0, "Admin password for this repeater", "", true); return true; }
    if (hit(ev, 80, by, 74, 22)) {
      if (_rep.login == RepeaterAdmin::LG_OK) repStatus();
      else showAlert("Log in first", 1500);
      return true;
    }
    if (hit(ev, 158, by, 74, 22)) {
      closeRepeater();
      _contact_detail = true;
      _forget_confirm = -1;
      _dirty = true;
      return true;
    }
  } else if (_rep_page == 1) {
    if (hit(ev, 2, by, 74, 22)) { repTrace(); return true; }
    if (hit(ev, 80, by, 74, 22)) { repEditStart(2, "Route to use: repeater ids, like a1,b2,c3", "", false); return true; }
    if (hit(ev, 158, by, 74, 22)) {
      ContactInfo* live = the_mesh.lookupContactByPubKey(_rep.key, PUB_KEY_SIZE);
      if (live && the_mesh.umcSetRoute(*live, NULL, 0, 1)) _rep.say("Route cleared - it floods next time");
      return true;
    }
  } else {
    if (hit(ev, 2, by, 74, 22)) { repEditStart(1, "Command for the repeater", "", false); return true; }
    if (hit(ev, 80, by, 74, 22)) { _rep_list = true; _rep_list_scroll = 0; _dirty = true; return true; }
    if (hit(ev, 158, by, 74, 22)) { repEditStart(0, "Admin password for this repeater", "", true); return true; }
    for (int i = 0; i < 8; i++) {
      const int x = 2 + (i % 4) * 79;
      const int y = cy + 54 + (i / 4) * 20;
      if (!hit(ev, x, y, 76, 18)) continue;
      if (kRepQuick[i].confirm && _rep_confirm != i) {
        _rep_confirm = i;
        _rep_confirm_until = millis() + 4000;
        showAlert("Tap again to confirm", 1500);
        _dirty = true;
      } else {
        _rep_confirm = -1;
        repCli(kRepQuick[i].cmd);
      }
      return true;
    }
  }
  return true;
}

bool UITask::repeaterKey(char c) {
  if (_rep_edit) {
    if (c == 8 || c == 127) {
      if (_rep_len > 0) _rep_buf[--_rep_len] = 0;
    } else if (c == 13 || c == 10) {
      repEditDone();
    } else if (c == 27) {
      _rep_edit = false;
    } else if (c >= 32 && c < 127 && _rep_len < (int)sizeof(_rep_buf) - 1) {
      _rep_buf[_rep_len++] = c;
      _rep_buf[_rep_len] = 0;
    }
    _dirty = true;
    return true;
  }
  if (_rep_page == 2 && !_rep_list && c >= 32 && c < 127) {   // typing on the Admin page starts a command
    const char first[2] = {c, 0};
    repEditStart(1, "Command for the repeater", first, false);
  }
  return true;
}
