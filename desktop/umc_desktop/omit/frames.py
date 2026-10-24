"""The companion radio protocol frames the chat bot needs, read and written. Layouts follow the
firmware (examples/companion_radio/MyMesh.cpp): little-endian, SNR sent as a signed byte times 4."""
import struct

CMD_SEND_CHANNEL_TXT = 3
CMD_GET_CONTACTS = 4
CMD_GET_CHANNEL = 31

RESP_CONTACT = 3
RESP_CONTACT_MSG_V3 = 16
RESP_CHANNEL_MSG_V3 = 17
RESP_CHANNEL_INFO = 18
RESP_CONTACT_MSG, RESP_CHANNEL_MSG = 7, 8
PUSH_MSG_WAITING = 0x83
PUSH_LOGIN_OK, PUSH_LOGIN_FAIL, PUSH_STATUS, PUSH_TRACE = 0x85, 0x86, 0x87, 0x89
PUSH_LOG_RX = 0x88
CMD_SEND_TXT, CMD_SEND_LOGIN, CMD_SEND_STATUS_REQ, CMD_SEND_TRACE = 2, 26, 27, 36
RESP_SENT = 6
TXT_CLI = 1

TXT_PLAIN = 0
ROUTE = {0: "transport-flood", 1: "flood", 2: "direct", 3: "transport-direct"}
PAYLOAD = {0: "req", 1: "response", 2: "txt", 3: "ack", 4: "advert", 5: "grp_txt", 6: "grp_data", 7: "anon_req",
           8: "path", 9: "trace", 10: "multipart", 11: "control", 15: "raw"}
GRP_TXT = 5
DIRECT = 0xFF                      # path_len of a message that was routed direct: the hop count is not known


def _cstr(b):
    return b.split(b"\0", 1)[0].decode("utf-8", "replace")


def _snr(b):
    return (b - 256 if b > 127 else b) / 4.0


def split_sender(text):
    """Channel text arrives as "Name: message"."""
    name, sep, msg = text.partition(": ")
    return (name, msg) if sep else ("", text)


def parse_packet(raw):
    """The header of a raw MeshCore packet: route, payload type, hash size, path and payload length."""
    if len(raw) < 2:
        return None
    i, header = 1, raw[0]
    route = header & 3
    if route in (0, 3):
        i += 4                                          # transport codes
    if i >= len(raw):
        return None
    path_len = raw[i]
    i += 1
    size, count = (path_len >> 6) + 1, path_len & 63
    if size == 4 or i + size * count > len(raw):
        return None
    path = [raw[i + k * size:i + (k + 1) * size].hex() for k in range(count)]
    return {"route": ROUTE[route], "type": (header >> 2) & 15, "type_name": PAYLOAD.get((header >> 2) & 15, "?"),
            "hash_size": size, "hops": count, "path": path, "payload_len": len(raw) - i - size * count}


STATS = struct.Struct("<HHhhIIIIIIIIHhHHII")      # the repeater's RepeaterStats, little-endian
STATS_KEYS = ("bat_mv", "tx_queue", "noise_floor", "last_rssi", "n_recv", "n_sent", "airtime_s", "uptime_s",
              "n_sent_flood", "n_sent_direct", "n_recv_flood", "n_recv_direct", "err_events", "last_snr",
              "direct_dups", "flood_dups", "rx_airtime_s", "recv_errors")


def parse_stats(b):
    """A repeater's statistics. Older firmware sends fewer fields: what is there is read, the rest left out."""
    out, off = {}, 0
    for key, ch in zip(STATS_KEYS, STATS.format[1:]):
        size = struct.calcsize("<" + ch)
        if off + size > len(b):
            break
        out[key] = struct.unpack_from("<" + ch, b, off)[0]
        off += size
    if "last_snr" in out:
        out["last_snr"] = out["last_snr"] / 4.0
    return out


def parse(frame):
    """A frame from the radio -> a dict with a "kind", or None for frames the bot does not use."""
    if not frame:
        return None
    code = frame[0]
    if code == RESP_CHANNEL_MSG_V3 and len(frame) >= 11:
        path_len = frame[5]
        ts = struct.unpack_from("<I", frame, 7)[0]
        return {"kind": "channel_msg", "snr": _snr(frame[1]), "channel_idx": frame[4],
                "hops": None if path_len == DIRECT else path_len, "txt_type": frame[6], "timestamp": ts,
                "text": frame[11:].decode("utf-8", "replace").rstrip("\0")}
    if code == RESP_CONTACT_MSG_V3 and len(frame) >= 16:
        path_len = frame[10]
        ts = struct.unpack_from("<I", frame, 12)[0]
        return {"kind": "contact_msg", "snr": _snr(frame[1]), "prefix": frame[4:10].hex(),
                "hops": None if path_len == DIRECT else path_len, "txt_type": frame[11], "timestamp": ts,
                "text": frame[16:].decode("utf-8", "replace").rstrip("\0")}
    if code == RESP_CONTACT and len(frame) >= 1 + 32 + 3 + 64 + 32 + 16:
        i = 1
        pub = frame[i:i + 32]
        i += 32
        ctype, flags, out_len = frame[i], frame[i + 1], frame[i + 2]
        out_path = frame[i + 3:i + 3 + 64]
        i += 3 + 64
        name = _cstr(frame[i:i + 32])
        i += 32
        adv, lat, lon = struct.unpack_from("<Iii", frame, i)
        size, count = ((out_len >> 6) + 1, out_len & 63) if out_len != 0xFF else (1, None)
        route = None if count is None else [out_path[k * size:(k + 1) * size].hex() for k in range(count)]
        return {"kind": "contact", "pubkey": pub.hex(), "type": ctype, "flags": flags, "name": name,
                "last_advert": adv, "lat": lat / 1e6, "lon": lon / 1e6, "route": route, "hash_size": size}
    if code == RESP_CHANNEL_INFO and len(frame) >= 2 + 32 + 16:
        return {"kind": "channel_info", "idx": frame[1], "name": _cstr(frame[2:34]), "secret": frame[34:50].hex()}
    if code == PUSH_LOG_RX and len(frame) >= 5:
        raw = bytes(frame[3:])
        return {"kind": "log_rx", "snr": _snr(frame[1]), "rssi": frame[2] - 256 if frame[2] > 127 else frame[2],
                "raw": raw, "packet": parse_packet(raw)}
    if code in (PUSH_LOGIN_OK, PUSH_LOGIN_FAIL) and len(frame) >= 8:
        return {"kind": "login_ok" if code == PUSH_LOGIN_OK else "login_fail", "prefix": frame[2:8].hex(),
                "admin": bool(frame[1] & 1) if code == PUSH_LOGIN_OK else False}
    if code == PUSH_STATUS and len(frame) >= 8:
        return {"kind": "status", "prefix": frame[2:8].hex(), "stats": parse_stats(frame[8:])}
    if code == PUSH_TRACE and len(frame) >= 13:
        path_len, flags = frame[2], frame[3]
        n = path_len >> (flags & 3)
        i = 12 + path_len
        if len(frame) < i + n + 1:
            return None
        return {"kind": "trace", "tag": struct.unpack_from("<I", frame, 4)[0], "flags": flags,
                "hashes": frame[12:i].hex(), "snrs": [_snr(b) for b in frame[i:i + n]], "final_snr": _snr(frame[i + n])}
    if code == PUSH_MSG_WAITING:
        return {"kind": "msg_waiting"}
    return None


# ---------------------------------------------------------------- commands
def send_channel(idx, text, timestamp):
    """CMD_SEND_CHANNEL_TXT_MSG: the radio puts our node name in front of the text itself."""
    return bytes([CMD_SEND_CHANNEL_TXT, TXT_PLAIN, idx]) + struct.pack("<I", int(timestamp)) + text.encode("utf-8")


def login(pubkey_hex, password):
    return bytes([CMD_SEND_LOGIN]) + bytes.fromhex(pubkey_hex) + password.encode("utf-8")


def status_request(pubkey_hex):
    return bytes([CMD_SEND_STATUS_REQ]) + bytes.fromhex(pubkey_hex)


def trace(tag, hashes, hash_size=1, auth=0):
    """CMD_SEND_TRACE_PATH: hashes is a list of hex strings, all of one size; the radio collects the SNR at each hop."""
    flags = {1: 0, 2: 1, 4: 2}.get(hash_size, 0)
    return (bytes([CMD_SEND_TRACE]) + struct.pack("<II", tag, auth) + bytes([flags])
            + b"".join(bytes.fromhex(h) for h in hashes))


def cli_command(prefix_hex, text, timestamp=0):
    """A command line sent to a repeater as a direct message of type CLI; its answer comes back as a message."""
    return bytes([CMD_SEND_TXT, TXT_CLI, 0]) + struct.pack("<I", int(timestamp)) + bytes.fromhex(prefix_hex)[:6] + text.encode("utf-8")


def get_channel(idx):
    return bytes([CMD_GET_CHANNEL, idx])


def get_contacts():
    return bytes([CMD_GET_CONTACTS])


# ---------------------------------------------------------------- building frames, for tests and simulators
def build_channel_msg(idx, text, timestamp, snr=5.5, hops=1):
    path_len = DIRECT if hops is None else hops
    return (bytes([RESP_CHANNEL_MSG_V3, int(snr * 4) & 255, 0, 0, idx, path_len, TXT_PLAIN])
            + struct.pack("<I", int(timestamp)) + text.encode("utf-8"))


def build_log_rx(raw, snr=5.5, rssi=-90):
    return bytes([PUSH_LOG_RX, int(snr * 4) & 255, rssi & 255]) + bytes(raw)


def build_contact(pubkey, name, ctype=1, lat=0.0, lon=0.0, last_advert=0, route=None):
    out_len = 255 if route is None else len(route)
    path = b"".join(bytes.fromhex(h) for h in (route or [])).ljust(64, b"\0")
    return (bytes([RESP_CONTACT]) + bytes.fromhex(pubkey) + bytes([ctype, 0, out_len]) + path
            + name.encode()[:31].ljust(32, b"\0") + struct.pack("<Iiii", last_advert, int(lat * 1e6), int(lon * 1e6), 0))


def build_stats(**kw):
    vals = {k: 0 for k in STATS_KEYS}
    vals.update(kw)
    vals["last_snr"] = int(vals["last_snr"] * 4)
    return STATS.pack(*[vals[k] for k in STATS_KEYS])


def build_status_push(prefix_hex, stats_bytes):
    return bytes([PUSH_STATUS, 0]) + bytes.fromhex(prefix_hex)[:6] + stats_bytes


def build_login_push(prefix_hex, ok=True):
    return bytes([PUSH_LOGIN_OK if ok else PUSH_LOGIN_FAIL, 1 if ok else 0]) + bytes.fromhex(prefix_hex)[:6]


def build_trace_push(tag, hashes, snrs, final_snr, hash_size=1):
    flags = {1: 0, 2: 1, 4: 2}.get(hash_size, 0)
    raw = b"".join(bytes.fromhex(h) for h in hashes)
    return (bytes([PUSH_TRACE, 0, len(raw), flags]) + struct.pack("<II", tag, 0) + raw
            + bytes(int(v * 4) & 255 for v in snrs) + bytes([int(final_snr * 4) & 255]))


def build_cli_reply(prefix_hex, text, timestamp=0, snr=3.0):
    return (bytes([RESP_CONTACT_MSG_V3, int(snr * 4) & 255, 0, 0]) + bytes.fromhex(prefix_hex)[:6]
            + bytes([DIRECT, TXT_CLI]) + struct.pack("<I", int(timestamp)) + text.encode("utf-8"))
