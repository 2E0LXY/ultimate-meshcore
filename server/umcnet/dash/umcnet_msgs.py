"""UMC Net messaging: read and send MeshCore group (channel) messages from the dashboard.

Everything a repeater publishes on the broker's raw topic is a packet exactly as it went over the air. A group text message is
encrypted with a channel key, so the dashboard can read the channels whose keys it has been given (a "#hashtag" channel's key is
the first 16 bytes of SHA-256 of its name, so it needs no secret). A packet sent into a region carries a 16-bit code that
only the region's name can produce, so the dashboard names the region by trying the regions it knows. Sending builds the same
packet a radio would and hands it to the repeaters through the broker (their UMC Net bridge transmits it).
Layout and crypto mirror src/Utils.cpp, src/Mesh.cpp, src/helpers/TransportKeyStore.cpp (tested against them in test_dash.py).
Python standard library only (a small AES lives here because the standard library has none)."""
import base64, hashlib, hmac, struct

# ---------------------------------------------------------------- AES-128 (FIPS 197), ECB, one block at a time
_SBOX = bytearray(256); _INV = bytearray(256)
def _init_sbox():
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)          # multiply p by 3
        q ^= q << 1; q ^= q << 2; q ^= q << 4; q &= 0xFF
        if q & 0x80: q ^= 0x09                                          # divide q by 3
        x = q ^ ((q << 1) | (q >> 7)) & 0xFF ^ ((q << 2) | (q >> 6)) & 0xFF ^ ((q << 3) | (q >> 5)) & 0xFF ^ ((q << 4) | (q >> 4)) & 0xFF
        _SBOX[p] = (x ^ 0x63) & 0xFF
        if p == 1: break
    _SBOX[0] = 0x63
    for i in range(256): _INV[_SBOX[i]] = i
_init_sbox()
def _xt(a): return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1)
def _mul(a, b):
    r = 0
    while b:
        if b & 1: r ^= a
        a = _xt(a); b >>= 1
    return r
def _expand(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]; rc = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [_SBOX[t[1]] ^ rc, _SBOX[t[2]], _SBOX[t[3]], _SBOX[t[0]]]; rc = _xt(rc)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]
def aes_encrypt_block(key, block):
    rk = _expand(key); s = [block[i] ^ rk[0][i] for i in range(16)]
    for r in range(1, 11):
        s = [_SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]               # ShiftRows (column-major state)
        if r < 10:
            o = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                o += [_mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3], a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3], a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3), _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)]
            s = o
        s = [s[i] ^ rk[r][i] for i in range(16)]
    return bytes(s)
def aes_decrypt_block(key, block):
    rk = _expand(key); s = [block[i] ^ rk[10][i] for i in range(16)]
    for r in range(9, -1, -1):
        s = [s[(i - 4 * (i % 4)) % 16] for i in range(16)]               # InvShiftRows
        s = [_INV[b] for b in s]
        s = [s[i] ^ rk[r][i] for i in range(16)]
        if r > 0:
            o = []
            for c in range(4):
                a = s[c * 4:c * 4 + 4]
                o += [_mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9), _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13), _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11), _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)]
            s = o
    return bytes(s)
def aes_ecb(key, data, encrypt):
    f = aes_encrypt_block if encrypt else aes_decrypt_block
    if encrypt and len(data) % 16: data = data + bytes(16 - len(data) % 16)     # the firmware zero-pads the last block
    return b"".join(f(key, data[i:i + 16]) for i in range(0, len(data) - len(data) % 16, 16))

# ---------------------------------------------------------------- channels and regions
PUBLIC_PSK = "izOH6cXN6mrJ5e26oRXNcg=="                 # MeshCore's well-known Public channel

class Channel:
    def __init__(self, name, psk_b64=None):
        self.name = name
        if psk_b64:
            raw = base64.b64decode(psk_b64)
            if len(raw) not in (16, 32): raise ValueError("a channel key is 16 or 32 bytes (base64)")
        elif name.startswith("#") and len(name) > 1: raw = hashlib.sha256(name.encode()).digest()[:16]     # a hashtag channel: the name is the key
        else: raise ValueError("a channel needs a key, or a name that starts with #")
        self.key = raw[:16]; self.secret = raw + bytes(32 - len(raw))                  # 32 bytes, zero-padded, as the firmware keeps it
        self.hash = hashlib.sha256(raw).digest()[0]

def region_key(name):
    return hashlib.sha256(("#" + name.lstrip("#")).encode()).digest()[:16]

def region_code(key16, ptype, payload):
    c = int.from_bytes(hmac.new(key16, bytes([ptype]) + payload, hashlib.sha256).digest()[:2], "little")
    return 1 if c == 0 else 0xFFFE if c == 0xFFFF else c

def parse_wire(raw):
    """Header, transport codes, path and payload of a packet as heard on the air, or None."""
    try:
        h = raw[0]; route = h & 3; ptype = (h >> 2) & 15; i = 1; codes = None
        if route in (0, 3): codes = struct.unpack("<HH", raw[i:i + 4]); i += 4
        pl = raw[i]; i += 1; count, size = pl & 63, (pl >> 6) + 1
        if size > 3 or i + count * size > len(raw): return None
        path = [raw[i + k * size:i + (k + 1) * size] for k in range(count)]; i += count * size
        return {"route": route, "ptype": ptype, "codes": codes, "path": path, "payload": raw[i:]}
    except Exception:
        return None

def decrypt_group(channels, payload):
    """(channel, timestamp, text) for the first channel whose hash and MAC match, else None."""
    if len(payload) < 1 + 2 + 16: return None
    for ch in channels:
        if ch.hash != payload[0]: continue
        mac, cipher = payload[1:3], payload[3:]
        if len(cipher) % 16 or not hmac.compare_digest(hmac.new(ch.secret, cipher, hashlib.sha256).digest()[:2], mac): continue
        plain = aes_ecb(ch.key, cipher, False)
        if len(plain) < 6: continue
        ts = struct.unpack("<I", plain[:4])[0]; flags = plain[4]
        text = plain[5:].split(b"\0", 1)[0].decode("utf-8", "replace")
        return ch, ts, flags, text
    return None

def split_sender(text):
    """MeshCore puts 'sender: message' in the text."""
    if ": " in text[:40]:
        a, b = text.split(": ", 1); return a, b
    return "", text

def find_region(regions, parsed):
    """Name of the region a scoped packet was sent into (from its transport code), or ''."""
    if not parsed["codes"]: return ""
    for name in regions:
        if region_code(region_key(name), parsed["ptype"], parsed["payload"]) == parsed["codes"][0]: return name
    return ""

def build_group_text(ch, sender, text, ts, region=None):
    """The raw packet a radio would send for this group message (flood, or flood scoped to a region)."""
    body = struct.pack("<I", ts) + b"\x00" + ("%s: %s" % (sender, text)).encode("utf-8")
    if len(body) > 5 + 160: raise ValueError("that message is too long")
    cipher = aes_ecb(ch.key, body, True)
    payload = bytes([ch.hash]) + hmac.new(ch.secret, cipher, hashlib.sha256).digest()[:2] + cipher
    ptype = 5
    if region:
        code = region_code(region_key(region), ptype, payload)
        return bytes([(ptype << 2) | 0]) + struct.pack("<HH", code, 0) + b"\x00" + payload
    return bytes([(ptype << 2) | 1]) + b"\x00" + payload
