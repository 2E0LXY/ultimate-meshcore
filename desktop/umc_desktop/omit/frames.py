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
PUSH_LOG_RX = 0x88

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
        i += 3 + 64
        name = _cstr(frame[i:i + 32])
        i += 32
        adv, lat, lon = struct.unpack_from("<Iii", frame, i)
        return {"kind": "contact", "pubkey": pub.hex(), "type": ctype, "flags": flags, "name": name,
                "last_advert": adv, "lat": lat / 1e6, "lon": lon / 1e6}
    if code == RESP_CHANNEL_INFO and len(frame) >= 2 + 32 + 16:
        return {"kind": "channel_info", "idx": frame[1], "name": _cstr(frame[2:34]), "secret": frame[34:50].hex()}
    if code == PUSH_LOG_RX and len(frame) >= 5:
        raw = bytes(frame[3:])
        return {"kind": "log_rx", "snr": _snr(frame[1]), "rssi": frame[2] - 256 if frame[2] > 127 else frame[2],
                "raw": raw, "packet": parse_packet(raw)}
    if code == PUSH_MSG_WAITING:
        return {"kind": "msg_waiting"}
    return None


# ---------------------------------------------------------------- commands
def send_channel(idx, text, timestamp):
    """CMD_SEND_CHANNEL_TXT_MSG: the radio puts our node name in front of the text itself."""
    return bytes([CMD_SEND_CHANNEL_TXT, TXT_PLAIN, idx]) + struct.pack("<I", int(timestamp)) + text.encode("utf-8")


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


def build_contact(pubkey, name, ctype=1, lat=0.0, lon=0.0, last_advert=0):
    return (bytes([RESP_CONTACT]) + bytes.fromhex(pubkey) + bytes([ctype, 0, 255]) + b"\0" * 64
            + name.encode()[:31].ljust(32, b"\0") + struct.pack("<Iiii", last_advert, int(lat * 1e6), int(lon * 1e6), 0))
