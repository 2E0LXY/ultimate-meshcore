#!/usr/bin/env python3
"""UMC Net admin helper: the one small part of the dashboard that runs as root.

The dashboard itself is an unprivileged service. When the operator adds, approves, blocks or removes a repeater,
resets a password, or changes the dashboard login, the dashboard asks this helper over a Unix socket that only the
dashboard's user can open. The helper accepts a short list of operations, checks every argument strictly, and does
them by calling the same tools an operator would use by hand (umcnet-user, caddy, systemctl).
Python standard library only.
"""
import hashlib, hmac, json, os, re, secrets, socketserver, subprocess, threading, time

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


BCRYPT = re.compile(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}")


def bcrypt_from(text):
    """The bcrypt hash in whatever caddy printed (it may add a notice), or None."""
    m = BCRYPT.search(text or "")
    return m.group(0) if m else None


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


WEBNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,30}$")


def user_hash_file(user):
    return HASH_FILE if user == "admin" else os.path.join(os.path.dirname(HASH_FILE), "user-%s.pbkdf2" % user)


def strong_enough(pw):
    return 12 <= len(pw) <= 100 and pw.lower() != pw and re.search(r"\d", pw)


def caddy_users(text):
    """The (name, bcrypt) pairs in the dashboard's basic_auth block, and the block's span."""
    m = re.search(r"basic_auth\s*\{\n(.*?)\n[ \t]*\}", text, re.S)
    if not m:
        return None, None
    users = []
    for line in m.group(1).splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("$2"):
            users.append((parts[0], parts[1]))
    return users, m.span(1)


def write_caddy_users(users):
    """Rewrite the login list and reload Caddy; put the old file back if Caddy refuses it."""
    text = open(CADDY_FILE).read()
    old, span = caddy_users(text)
    if span is None:
        return {"ok": False, "error": "could not find the login list in the Caddy site file"}
    new_text = text[:span[0]] + "\n".join("\t\t\t%s %s" % u for u in users) + text[span[1]:]
    open(CADDY_FILE + ".backup-before-users", "w").write(text)
    open(CADDY_FILE, "w").write(new_text)
    rc, out = run("caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
    if rc != 0:
        open(CADDY_FILE, "w").write(text)
        return {"ok": False, "error": "Caddy refused the change, the old logins are back: " + out[-120:]}
    run("systemctl", "reload", "caddy")
    return {"ok": True}


def make_bcrypt(pw):
    p = subprocess.run(["caddy", "hash-password", "--plaintext", pw], capture_output=True, text=True, timeout=60)
    bc = bcrypt_from(p.stdout)
    return bc if p.returncode == 0 and bc else None


def save_pbkdf2(user, pw):
    f = user_hash_file(user)
    os.makedirs(os.path.dirname(f), exist_ok=True)
    open(f, "w").write(pbkdf2(pw)); os.chmod(f, 0o600)


def web_user_set(name, pw):
    """Add a dashboard login, or give an existing one a new password (the admin's own login is changed with dash_password)."""
    if not WEBNAME.match(name) or name == "admin":
        return {"ok": False, "error": "user names are 2 to 31 lowercase letters, digits, dots, dashes or underscores (not admin)"}
    if not strong_enough(pw):
        return {"ok": False, "error": "the password needs 12 or more characters, with a capital letter and a number"}
    bc = make_bcrypt(pw)
    if not bc:
        return {"ok": False, "error": "could not make the login hash"}
    with LOCK:
        users, span = caddy_users(open(CADDY_FILE).read())
        if users is None:
            return {"ok": False, "error": "could not find the login list in the Caddy site file"}
        users = [u for u in users if u[0] != name] + [(name, bc)]
        r = write_caddy_users(users)
    if r["ok"]:
        save_pbkdf2(name, pw)
    return r


def web_user_remove(name):
    if not WEBNAME.match(name) or name == "admin":
        return {"ok": False, "error": "that login cannot be removed"}
    with LOCK:
        users, span = caddy_users(open(CADDY_FILE).read())
        if users is None:
            return {"ok": False, "error": "could not find the login list in the Caddy site file"}
        r = write_caddy_users([u for u in users if u[0] != name])
    try:
        os.unlink(user_hash_file(name))
    except OSError:
        pass
    return r


def change_dash_password(current, new, user="admin"):
    now = time.time()
    with LOCK:
        _fails[:] = [t for t in _fails if now - t < 300]
        if len(_fails) >= 5:
            return {"ok": False, "error": "too many wrong attempts; wait five minutes"}
    if user != "admin" and not WEBNAME.match(user):
        return {"ok": False, "error": "unknown user"}
    if not strong_enough(new):
        return {"ok": False, "error": "the new password needs 12 or more characters, with a capital letter and a number"}
    try:
        stored = open(user_hash_file(user)).read()
    except FileNotFoundError:
        stored = ""
    if not stored or not check_password(current, stored):
        with LOCK: _fails.append(now)
        return {"ok": False, "error": "the current password is not right"}
    bc = make_bcrypt(new)
    if not bc:
        return {"ok": False, "error": "could not make the login hash"}
    with LOCK:
        users, span = caddy_users(open(CADDY_FILE).read())
        if not users or not any(u[0] == user for u in users):
            return {"ok": False, "error": "could not find the login in the Caddy site file"}
        r = write_caddy_users([(u[0], bc if u[0] == user else u[1]) for u in users])
    if not r["ok"]:
        return r
    save_pbkdf2(user, new)
    if user == "admin":
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
        return change_dash_password(str(req.get("current", "")), str(req.get("new", "")), str(req.get("user", "admin")))
    if op == "web_user_set":
        return web_user_set(str(req.get("name", "")), str(req.get("password", "")))
    if op == "web_user_remove":
        return web_user_remove(str(req.get("name", "")))
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
