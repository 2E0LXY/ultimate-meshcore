"""UMC Net zero-touch enrolment: the server half (Python standard library only).

A repeater that is switched to "join UMC Net" with no account knocks on the broker as the public `enrol`
account and publishes a signed request. The dashboard shows it; on approval the dashboard creates the
repeater's own account and sends the credentials back encrypted so that only that repeater can read them.
The protocol is described in docs/umc/ENROL.md and mirrored in src/helpers/mqtt/Enrol.h (tested against each other).

  hello  (repeater -> server)  umcnet/v1/enrol/hello          JSON, signed with the repeater's Ed25519 identity
  grant  (server -> repeater)  umcnet/v1/enrol/grant/<ID>     retained, base64url, encrypted to the repeater's key
"""
import base64, hashlib, hmac, json, os, re, time

# ---------------------------------------------------------------- Curve25519 / Ed25519 (RFC 7748, RFC 8032)
P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
I = pow(2, (P - 1) // 4, P)


def _inv(x): return pow(x, P - 2, P)


def x25519(k32, u32):
    """X25519 as in RFC 7748 (the top bit of u is ignored, the scalar is clamped)."""
    k = bytearray(k32)
    k[0] &= 248; k[31] &= 127; k[31] |= 64
    k = int.from_bytes(k, "little")
    u = int.from_bytes(u32, "little") & ((1 << 255) - 1)
    x1, x2, z2, x3, z3, swap = u, 1, 0, u, 1, 0
    a24 = 121665
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        swap ^= kt
        if swap: x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        A = (x2 + z2) % P; AA = A * A % P; B = (x2 - z2) % P; BB = B * B % P
        E = (AA - BB) % P; C = (x3 + z3) % P; Dd = (x3 - z3) % P
        DA = Dd * A % P; CB = C * B % P
        x3 = (DA + CB) % P; x3 = x3 * x3 % P
        z3 = (DA - CB) % P; z3 = z3 * z3 % P * x1 % P
        x2 = AA * BB % P
        z2 = E * ((AA + a24 * E) % P) % P
    if swap: x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * _inv(z2) % P).to_bytes(32, "little")


def ed_to_mont_u(pub32):
    """Montgomery u of an Ed25519 public key: (1 + y) / (1 - y)."""
    y = int.from_bytes(pub32, "little") & ((1 << 255) - 1)
    return ((1 + y) * _inv((1 - y) % P) % P).to_bytes(32, "little")


def mont_u_to_ed_y(u32):
    """The Edwards y that maps back to this Montgomery u: (u - 1) / (u + 1), sign bit 0."""
    u = int.from_bytes(u32, "little") & ((1 << 255) - 1)
    return ((u - 1) * _inv((u + 1) % P) % P).to_bytes(32, "little")


def _recover_x(y, sign):
    if y >= P: return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0: return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0: x = x * I % P
    if (x * x - x2) % P != 0: return None
    if (x & 1) != sign: x = P - x
    return x


_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % P; b = (p[1] + p[0]) * (q[1] + q[0]) % P
    c = 2 * p[3] * q[3] * D % P; d = 2 * p[2] * q[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1: q = _add(q, p)
        p = _add(p, p); s >>= 1
    return q


def _enc(p):
    zi = _inv(p[2]); x = p[0] * zi % P; y = p[1] * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _dec(b):
    y = int.from_bytes(b, "little"); sign = y >> 255; y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _h(m): return int.from_bytes(hashlib.sha512(m).digest(), "little")


def ed_keypair(seed32):
    """(private 64 bytes in the layout the firmware uses, public 32 bytes) from a 32-byte seed."""
    h = bytearray(hashlib.sha512(seed32).digest())
    h[0] &= 248; h[31] &= 63; h[31] |= 64
    return bytes(h), _enc(_mul(int.from_bytes(h[:32], "little"), G))


def ed_sign(prv64, pub32, msg):
    a = int.from_bytes(prv64[:32], "little")
    r = _h(prv64[32:] + msg) % L
    R = _enc(_mul(r, G))
    k = _h(R + pub32 + msg) % L
    return R + ((r + k * a) % L).to_bytes(32, "little")


def ed_verify(pub32, msg, sig64):
    try:
        if len(sig64) != 64 or len(pub32) != 32: return False
        A = _dec(pub32); R = _dec(sig64[:32])
        S = int.from_bytes(sig64[32:], "little")
        if A is None or R is None or S >= L: return False
        k = _h(sig64[:32] + pub32 + msg) % L
        lhs = _mul(S, G); rhs = _add(R, _mul(k, A))
        return (lhs[0] * rhs[2] - rhs[0] * lhs[2]) % P == 0 and (lhs[1] * rhs[2] - rhs[1] * lhs[2]) % P == 0
    except Exception:
        return False


# ---------------------------------------------------------------- the protocol
HELLO_PREFIX = b"UMC-ENROL1|"
ID_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


def hello_message(dev_id, ts, nonce):
    return HELLO_PREFIX + dev_id.upper().encode() + b"|" + str(int(ts)).encode() + b"|" + nonce.encode()


def verify_hello(raw, now=None, max_skew=86400):
    """Parse and verify a request. Returns (info, None) or (None, why-not)."""
    try:
        j = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
    except Exception:
        return None, "not JSON"
    if not isinstance(j, dict) or j.get("v") != 1: return None, "unknown version"
    dev, ts, nc, sig = j.get("id", ""), j.get("ts"), j.get("nc", ""), j.get("sig", "")
    if not isinstance(dev, str) or not ID_RE.match(dev): return None, "bad id"
    if not isinstance(ts, int) or isinstance(ts, bool): return None, "bad time"
    if not isinstance(nc, str) or not re.match(r"^[0-9a-f]{8,32}$", nc): return None, "bad nonce"
    if not isinstance(sig, str) or not re.match(r"^[0-9a-fA-F]{128}$", sig): return None, "bad signature field"
    now = time.time() if now is None else now
    if abs(now - ts) > max_skew: return None, "clock too far off"
    if not ed_verify(bytes.fromhex(dev), hello_message(dev, ts, nc), bytes.fromhex(sig)): return None, "signature does not match the id"
    name = re.sub(r"[^\x20-\x7e]", "", str(j.get("name", "")))[:31]
    return {"id": dev.upper(), "name": name, "fw": str(j.get("fw", ""))[:16], "bd": str(j.get("bd", ""))[:32], "ts": ts, "nc": nc}, None


def _kdf(shared, dev_id_bytes, eph_pub):
    return hmac.new(shared, b"UMC-ENROL1 key" + dev_id_bytes + eph_pub, hashlib.sha256).digest()


def _stream(key, nonce, n):
    out = b""; ctr = 0
    while len(out) < n:
        out += hmac.new(key, b"ks" + nonce + ctr.to_bytes(4, "big"), hashlib.sha256).digest(); ctr += 1
    return out[:n]


def make_grant(dev_id, join_code, eph_scalar=None, nonce=None):
    """base64url text for the retained grant topic: version | eph(32) | nonce(12) | ciphertext | tag(16)."""
    dev = bytes.fromhex(dev_id)
    k = eph_scalar or os.urandom(32)
    eph_pub = mont_u_to_ed_y(x25519(k, (9).to_bytes(32, "little")))
    shared = x25519(k, ed_to_mont_u(dev))
    key = _kdf(shared, dev, eph_pub)
    nonce = nonce or os.urandom(12)
    pt = join_code.encode()
    ct = bytes(a ^ b for a, b in zip(pt, _stream(key, nonce, len(pt))))
    tag = hmac.new(key, b"mac" + nonce + ct, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(b"\x01" + eph_pub + nonce + ct + tag).decode().rstrip("=")


def open_grant(prv64, dev_id, text):
    """What the repeater does (used by tests and the simulator): the join code, or None."""
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if len(raw) < 1 + 32 + 12 + 16 or raw[0] != 1: return None
    eph_pub, nonce, ct, tag = raw[1:33], raw[33:45], raw[45:-16], raw[-16:]
    dev = bytes.fromhex(dev_id)
    key = _kdf(x25519(prv64[:32], ed_to_mont_u(eph_pub)), dev, eph_pub)
    if not hmac.compare_digest(hmac.new(key, b"mac" + nonce + ct, hashlib.sha256).digest()[:16], tag): return None
    return bytes(a ^ b for a, b in zip(ct, _stream(key, nonce, len(ct)))).decode("utf-8", "replace")
