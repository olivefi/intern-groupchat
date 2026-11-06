#!/usr/bin/env python3
"""intern-groupchat hub: relays messages, files and transcripts between gc-bridges.
The identity of each connection is its tailscale login (tailscale whois)."""
import asyncio, base64, functools, http.server, json, os, subprocess, threading, time, uuid

PORT = int(os.environ.get("GC_PORT", 7777))
HTTP_PORT = int(os.environ.get("GC_HTTP_PORT", 7778))
STORE = os.path.expanduser(os.environ.get("GC_STORE", "~/.gc-hub/store"))
ALIASES = os.path.expanduser(os.environ.get("GC_ALIASES", "~/.gc-hub/aliases.json"))  # {"oliver": "olivefi@github"}
DEV_TRUST_HELLO = os.environ.get("GC_DEV_TRUST_HELLO") == "1"  # local testing only: take the user from hello
MAX_LINE = 96 * 1024 * 1024
COMMIT = subprocess.run(["git", "-C", os.path.dirname(os.path.abspath(__file__)), "rev-parse", "HEAD"],
                        capture_output=True, text=True).stdout.strip()


def ts(*args):
    try:
        return subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def whois(ip):
    try:
        return json.loads(ts("whois", "--json", ip))["UserProfile"]["LoginName"]
    except Exception:
        return None


BIND = os.environ.get("GC_BIND")
while not BIND:  # at boot, tailscale may still be coming up
    BIND = (ts("ip", "-4").split() or [None])[0]
    if not BIND:
        print("waiting for tailscale…", flush=True)
        time.sleep(5)
HOST = os.environ.get("GC_HOST") or json.loads(ts("status", "--json") or "{}").get("Self", {}).get("DNSName", "").rstrip(".") or BIND


class Conn:
    def __init__(self, user, machine, writer):
        self.user, self.machine, self.w = user, machine, writer
        self.sessions = {}  # name -> {"acl": [logins / short names / "*"], "history": bool}

    async def send(self, obj):
        self.w.write((json.dumps(obj) + "\n").encode())
        await self.w.drain()


conns = set()
contacts = set()  # (addr, user): addr has messaged one of user's sessions, so user may see and reply to it


def addr(c, name):
    return f"{c.user}/{name}"


_aliases = (None, {})


def aliases():
    """Friendly name -> login map, re-read whenever the file changes (no hub restart needed)."""
    global _aliases
    try:
        mtime = os.stat(ALIASES).st_mtime
        if mtime != _aliases[0]:
            with open(ALIASES) as f:
                _aliases = (mtime, {k.lower(): v for k, v in json.load(f).items()})
    except FileNotFoundError:
        _aliases = (None, {})
    except Exception as e:
        print("aliases:", e, flush=True)  # keep the last good map on a bad edit
    return _aliases[1]


def in_acl(user, acl):
    names = {a.lower() for a in acl}
    names |= {aliases().get(a, "").lower() for a in names}
    return "*" in names or user.lower() in names or user.split("@")[0].lower() in names


def own(c, user):
    return c.user == user and c.machine != "web"  # your browser tab is not a peer, unless it has messaged you


def visible(user):
    return [{"addr": addr(c, n), "user": c.user, "machine": c.machine, "name": n,
             "history": s["history"] or own(c, user), "cwd": s.get("cwd")}
            for c in conns for n, s in c.sessions.items()
            if own(c, user) or in_acl(user, s["acl"]) or (addr(c, n), user) in contacts]


async def push_peers():
    for c in list(conns):
        try:
            await c.send({"t": "peers", "sessions": visible(c.user)})
        except Exception:
            pass


def find(a):
    user, _, name = a.partition("/")
    for c in conns:
        if c.user == user and name in c.sessions:
            return c, name


def conn_of(user, machine):
    return next((c for c in conns if c.user == user and c.machine == machine), None)


async def relay(c, m):
    if m["t"] in ("send", "file"):
        src = addr(c, m["from"])
        target = find(m["to"])
        if not target or not any(v["addr"] == m["to"] for v in visible(c.user)):
            await c.send({"t": "error", "re": m["from"], "to": m["to"], "msg": f"{m['to']} is not online or not shared with you"})
            return
        tc, tname = target
        if (src, tc.user) not in contacts:
            contacts.add((src, tc.user))
            await push_peers()
        fwd = {"t": m["t"], "from": src, "to": tname}
        if m["t"] == "send":
            fwd["payload"] = m["payload"]
        else:
            fid = uuid.uuid4().hex[:12]
            name = os.path.basename(m["name"])
            os.makedirs(os.path.join(STORE, fid))
            with open(os.path.join(STORE, fid, name), "wb") as f:
                f.write(base64.b64decode(m["data"]))
            fwd.update(name=name, data=m["data"], url=f"http://{HOST}:{HTTP_PORT}/{fid}/{name}")
        await tc.send(fwd)
        return fwd.get("url")
    elif m["t"] == "transcript_req":
        target = find(m["to"])
        vis = next((v for v in visible(c.user) if v["addr"] == m["to"]), None)
        if not target or not vis:
            await c.send({"t": "error", "req": m["req"], "msg": f"{m['to']} is not online or not shared with you"})
        elif not vis["history"]:
            await c.send({"t": "error", "req": m["req"], "msg": f"{m['to']} is shared without history (owner: gc share --with-history)"})
        else:
            tc, tname = target
            await tc.send({"t": "transcript_req", "to": tname, "req": m["req"], "reply_user": c.user, "reply_machine": c.machine})
    elif m["t"] in ("transcript", "error") and m.get("reply_user"):
        rc = conn_of(m["reply_user"], m["reply_machine"])
        if rc:
            out = {k: v for k, v in m.items() if k not in ("reply_user", "reply_machine")}
            out["from"] = addr(c, m.get("name", ""))
            await rc.send(out)


async def handle(reader, writer):
    ip = writer.get_extra_info("peername")[0]
    c = None
    try:
        hello = json.loads(await reader.readline())
        user = hello.get("user") if DEV_TRUST_HELLO else whois(ip)
        if not user:
            writer.write(b'{"t":"error","msg":"unknown tailscale identity"}\n')
            await writer.drain()
            return
        c = Conn(user, hello.get("machine", "?"), writer)
        conns.add(c)
        await c.send({"t": "welcome", "user": user, "host": HOST, "http_port": HTTP_PORT, "commit": COMMIT})
        print(f"+ {user}@{c.machine} ({ip})", flush=True)
        while line := await reader.readline():
            m = json.loads(line)
            if m["t"] == "publish":
                c.sessions = {s["name"]: {"acl": s.get("acl", []), "history": bool(s.get("history")), "cwd": s.get("cwd")}
                              for s in m["sessions"]}
                await push_peers()
            elif m["t"] == "ping":
                await c.send({"t": "pong"})
            else:
                await relay(c, m)
    except (json.JSONDecodeError, ConnectionError, asyncio.IncompleteReadError, ValueError, KeyError):
        pass
    finally:
        if c:
            conns.discard(c)
            print(f"- {c.user}@{c.machine}", flush=True)
            await push_peers()
        writer.close()


class Files(http.server.SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(403)

    def log_message(self, *a):
        pass


loop = None


async def main():
    global loop
    loop = asyncio.get_running_loop()
    import web  # the browser UI; it reaches back into this module via __main__
    os.makedirs(STORE, exist_ok=True)
    httpd = http.server.ThreadingHTTPServer((BIND, HTTP_PORT), functools.partial(web.Handler, directory=STORE))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    asyncio.create_task(web.expire())
    server = await asyncio.start_server(handle, BIND, PORT, limit=MAX_LINE)
    print(f"gc-hub on {BIND}:{PORT}, files at http://{HOST}:{HTTP_PORT}/", flush=True)
    async with server:
        await server.serve_forever()


asyncio.run(main())
