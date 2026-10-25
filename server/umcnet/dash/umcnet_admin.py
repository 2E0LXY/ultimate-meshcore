#!/usr/bin/env python3
"""UMC Net admin helper: the one small part of the dashboard that runs as root.

The dashboard itself is an unprivileged service. When the operator adds, approves, blocks or removes a repeater,
resets a password, or changes the dashboard login, the dashboard asks this helper over a Unix socket that only the
dashboard's user can open. The helper accepts a short list of operations, checks every argument strictly, and does
them by calling the same tools an operator would use by hand (umcnet-user, caddy, systemctl).
Python standard library only.
"""
import hashlib, hmac, json, os, re, secrets, socket, socketserver, subprocess, sys, threading, time

SOCK = os.environ.get("ADMIN_SOCK", "/run/umcnet-admin/admin.sock")
USER_TOOL = os.environ.get("ADMIN_USER_TOOL", "/opt/umcnet/umcnet-user")
HASH_FILE = os.environ.get("ADMIN_HASH_FILE", "/etc/umcnet-dash/admin.pbkdf2")
CADDY_FILE = os.environ.get("ADMIN_CADDY_FILE", "/etc/caddy/conf.d/umcnet.caddy")
CRED_FILE = os.environ.get("ADMIN_CRED_FILE", "/root/umcnet-credentials.txt")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,23}$")
DEVICE = re.compile(r"^[0-9A-F]{64}$")
PROTECTED = {"admin", "dash", "controller"}                  # accounts the dashboard itself relies on
ROLES_FROM_UI = {"repeater", "client", "viewer"}
STATES = {"approved", "pending", "blocked"}
SERVICES = {"umcnet-mosquitto", "umcnet-dash", "caddy"}
_fails = []
LOCK = threading.Lock()


def run(*args, timeout=60):
    p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def tool(*args):
    rc, out = run(USER_TOOL, *args)
    return {"ok": rc == 0, "output": out, "password": (re.search(r"password: (\S+)", out) or [None, None])[1]}


def pbkdf2(password, salt=None, iterations=200_000):
    salt = salt or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "%d$%s$%s" % (iterations, salt.hex(), h.hex())


def check_password(password, stored):
    try:
        it, salt, h = stored.strip().split("$")
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(it)).hex(), h)
    except Exception:
        return False


def change_dash_password(current, new):
    now = time.time()
    with LOCK:
        _fails[:] = [t for t in _fails if now - t < 300]
        if len(_fails) >= 5:
            return {"ok": False, "error": "too many wrong attempts; wait five minutes"}
    if len(new) < 12 or len(new) > 100 or new.lower() == new or not re.search(r"\d", new):
        return {"ok": False, "error": "the new password needs 12 or more characters, with a capital letter and a number"}
    try:
        stored = open(HASH_FILE).read()
    except FileNotFoundError:
        stored = ""
    if not stored or not check_password(current, stored):
        with LOCK: _fails.append(now)
        return {"ok": False, "error": "the current password is not right"}
    rc, bc = run("caddy", "hash-password", "--plaintext", new)
    if rc != 0 or not bc.startswith("$2"):
        return {"ok": False, "error": "could not make the login hash: " + bc[:120]}
    text = open(CADDY_FILE).read()
    new_text, n = re.subn(r"(^\s*admin\s+)\$2[^\s]+", lambda m: m.group(1) + bc, text, count=1, flags=re.M)
    if n != 1:
        return {"ok": False, "error": "could not find the login in the Caddy site file"}
    backup = CADDY_FILE + ".backup-before-password"
    open(backup, "w").write(text)
    open(CADDY_FILE, "w").write(new_text)
    rc, out = run("caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
    if rc != 0:
        open(CADDY_FILE, "w").write(text)
        return {"ok": False, "error": "Caddy refused the change, the old login is back: " + out[-120:]}
    run("systemctl", "reload", "caddy")
    os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
    open(HASH_FILE, "w").write(pbkdf2(new)); os.chmod(HASH_FILE, 0o600)
    try:                                                    # the old password must not stay on disk in plain text
        lines = open(CRED_FILE).read().splitlines()
        lines = [("dashboard-login admin (changed %s; the password is not stored)" % time.strftime("%Y-%m-%d %H:%M")) if l.startswith("dashboard-login ") else l for l in lines]
        open(CRED_FILE, "w").write("\n".join(lines) + "\n")
    except OSError:
        pass
    return {"ok": True}


def handle(req):
    op = req.get("op")
    if op == "ping":
        return {"ok": True}
    if op in ("user_add", "user_remove", "user_device", "user_state", "user_passwd"):
        name = str(req.get("name", ""))
        if not NAME.match(name):
            return {"ok": False, "error": "name: 2 to 24 characters, lowercase letters, digits and dashes"}
        if name in PROTECTED and op != "user_passwd":
            return {"ok": False, "error": "that account is used by the dashboard itself"}
        if op == "user_add":
            role = str(req.get("role", "repeater"))
            if role not in ROLES_FROM_UI:
                return {"ok": False, "error": "role must be repeater, client or viewer"}
            args = ["add", name, role]
            dev = str(req.get("device", "")).upper()
            if role == "repeater":
                if dev:
                    if not DEVICE.match(dev): return {"ok": False, "error": "the device id is 64 hexadecimal characters"}
                    args += ["--device", dev]
                else:
                    args += ["--pending"]
            return tool(*args)
        if op == "user_remove": return tool("remove", name)
        if op == "user_passwd": return tool("passwd", name)
        if op == "user_device":
            dev = str(req.get("device", "")).upper()
            if not DEVICE.match(dev): return {"ok": False, "error": "the device id is 64 hexadecimal characters"}
            return tool("device", name, dev)
        st = str(req.get("state", ""))
        if st not in STATES: return {"ok": False, "error": "state must be approved, pending or blocked"}
        return tool("state", name, st)
    if op == "dash_password":
        return change_dash_password(str(req.get("current", "")), str(req.get("new", "")))
    if op == "service":
        name, act = str(req.get("name", "")), str(req.get("action", ""))
        if name not in SERVICES or act not in ("restart", "reload"):
            return {"ok": False, "error": "not allowed"}
        rc, out = run("systemctl", act, name)
        return {"ok": rc == 0, "output": out}
    return {"ok": False, "error": "unknown operation"}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(65536)
            res = handle(json.loads(line.decode()))
        except Exception as e:
            res = {"ok": False, "error": "bad request: %s" % e}
        self.wfile.write((json.dumps(res) + "\n").encode())


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    if os.path.exists(SOCK):
        os.unlink(SOCK)
    srv = Server(SOCK, Handler)
    try:
        import grp
        os.chown(SOCK, 0, grp.getgrnam("umcnet-dash").gr_gid)
    except (KeyError, ImportError, PermissionError):
        pass
    os.chmod(SOCK, 0o660)
    print("umcnet-admin helper on", SOCK, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
