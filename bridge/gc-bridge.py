#!/usr/bin/env python3
"""gc-bridge: makes shared Claude Code sessions on other machines appear as local peers.

One per machine and user, started by the gc plugin's SessionStart hook. It publishes the
local sessions (and who they're shared with) to the hub, and for every remote session the
hub says we may see it writes a session-registry entry plus a proxy socket, so Claude Code's
own /peers and SendMessage work unchanged. Messages are forwarded line by line; only the
`from` address is rewritten so replies route back through the proxy. It also delivers files
and, for sessions shared with history, transcripts."""
import asyncio, base64, glob, hashlib, json, os, re, secrets, signal, socket, time, uuid

GC = os.path.expanduser("~/.gc")
CFG = json.load(open(f"{GC}/config.json"))
CLAUDE = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude"))
SESS = f"{CLAUDE}/sessions"
INBOX = f"{GC}/inbox"
STATE = f"{GC}/state.json"    # {"fake": {addr: {"pid":.., "sock":..}}}
SHARED = f"{GC}/shared.json"  # {sessionId: [acl] | {"acl": [...], "history": bool}}
CTRL = f"{GC}/bridge.sock"
MACHINE = socket.gethostname()
FAKE_BASE = 4_000_000
MAX_LINE = 96 * 1024 * 1024


def load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def save(p, obj):
    json.dump(obj, open(p + ".tmp", "w"))
    os.replace(p + ".tmp", p)


def short(login):
    return login.split("@")[0]


def display(addr):
    user, _, name = addr.partition("/")
    return f"{short(user)}:{name}"


def shared_entry(v):
    return (v, False) if isinstance(v, list) else (v.get("acl", []), bool(v.get("history")))


def local_sessions():
    """real sessions on this machine, by name"""
    out = {}
    for f in glob.glob(f"{SESS}/*.json"):
        r = load(f, None)
        if r and r.get("pid", 0) < FAKE_BASE and os.path.exists(r.get("messagingSocketPath", "")):
            out[r["name"]] = r
    return out


def transcript_path(rec):
    return f"{CLAUDE}/projects/{re.sub(r'[^A-Za-z0-9]', '-', rec['cwd'])}/{rec['sessionId']}.jsonl"


def sockdir():
    for r in local_sessions().values():
        return os.path.dirname(r["messagingSocketPath"])
    d = f"/run/user/{os.getuid()}/cc-socks"
    return d if os.path.isdir(os.path.dirname(d)) else f"/tmp/cc-socks-{os.getuid()}"


def message(from_sock, from_name, text):
    return json.dumps({"msgV": 1, "msg_id": str(uuid.uuid4()), "type": "user", "priority": "next",
                       "from": f"uds:{from_sock}", "message": {"role": "user", "content":
                       f'<cross-session-message from="uds:{from_sock}" from-name="{from_name}" from-mode="prompting">\n{text}\n</cross-session-message>'}})


class Bridge:
    def __init__(self):
        self.user = self.w = None
        self.fake = load(STATE, {}).get("fake", {})  # addr -> {"pid", "sock"}
        self.servers = {}                             # addr -> unix server
        self.peers = {}                               # addr -> info from hub
        self.pending = {}                             # req id -> future (transcript requests)
        self.published = None

    # ---- hub link -------------------------------------------------------------------
    async def hub(self, obj):
        if self.w:
            self.w.write((json.dumps(obj) + "\n").encode())
            await self.w.drain()

    async def connect(self):
        host, _, port = CFG["hub"].partition(":")
        port = int(port or 7777)
        socks = CFG.get("socks")  # "host:port" of the userspace tailscale's SOCKS5 proxy
        if not socks:
            return await asyncio.open_connection(host, port, limit=MAX_LINE)
        sh, _, sp = socks.partition(":")
        r, w = await asyncio.open_connection(sh, int(sp or 1055), limit=MAX_LINE)
        w.write(b"\x05\x01\x00")
        await w.drain()
        if await r.readexactly(2) != b"\x05\x00":
            raise ConnectionError("socks5 handshake failed")
        w.write(b"\x05\x01\x00\x03" + bytes([len(host)]) + host.encode() + port.to_bytes(2, "big"))
        await w.drain()
        rep = await r.readexactly(4)
        if rep[1] != 0:
            raise ConnectionError(f"socks5 connect to {host}:{port} failed ({rep[1]})")
        n = {1: 4, 4: 16}.get(rep[3]) or (await r.readexactly(1))[0]
        await r.readexactly(n + 2)
        return r, w

    async def run_hub(self):
        while True:
            try:
                r, w = await asyncio.wait_for(self.connect(), 20)
                self.w = w
                await self.hub({"t": "hello", "user": CFG.get("user"), "machine": MACHINE})
                self.published = None
                while line := await r.readline():
                    m = json.loads(line)
                    if m["t"] == "welcome":
                        self.user = m["user"]
                        print(f"connected to {CFG['hub']} as {self.user}", flush=True)
                    elif m["t"] == "peers":
                        await self.sync_peers(m["sessions"])
                    elif m["t"] in ("send", "file"):
                        await self.deliver(m)
                    elif m["t"] == "transcript_req":
                        await self.send_transcript(m)
                    elif m["t"] == "transcript" or (m["t"] == "error" and m.get("req")):
                        self.resolve(m["req"], m)
                    elif m["t"] == "error":
                        await self.notify(m.get("re"), f"gc: {m['msg']}")
            except Exception as e:
                print("hub:", e, flush=True)
            self.w = None
            await asyncio.sleep(3)

    async def run_publish(self):
        while True:
            if self.w:
                shared = load(SHARED, {})
                pub = []
                for n, r in local_sessions().items():
                    acl, hist = shared_entry(shared.get(r["sessionId"], []))
                    pub.append({"name": n, "acl": acl, "history": hist})
                if pub != self.published:
                    await self.hub({"t": "publish", "sessions": pub})
                    self.published = pub
            await asyncio.sleep(2)

    # ---- remote sessions as local peers --------------------------------------------------
    async def sync_peers(self, sessions):
        wanted = {s["addr"]: s for s in sessions
                  if not (s["user"] == self.user and s["machine"] == MACHINE) or os.environ.get("GC_MATERIALIZE_SELF")}
        self.peers = wanted
        for a in list(self.servers):
            if a not in wanted:
                self.dematerialize(a)
        for a in wanted:
            await self.materialize(a)

    def addr_of(self, disp):
        a = next((a for a in self.peers if display(a) == disp), None)
        if not a:
            raise ValueError(f"unknown peer {disp} (see: gc peers)")
        return a

    async def materialize(self, addr):
        if addr in self.servers:
            return
        info = self.fake.get(addr)
        if not info:
            pid = FAKE_BASE + 1 + max([v["pid"] - FAKE_BASE for v in self.fake.values()] + [0])
            info = self.fake[addr] = {"pid": pid, "sock": f"{sockdir()}/{pid}.sock"}
            save(STATE, {"fake": self.fake})
        pid, sock = info["pid"], info["sock"]
        if os.path.exists(sock):
            os.unlink(sock)
        self.servers[addr] = await asyncio.start_unix_server(lambda r, w: self.on_proxy(addr, r, w), sock)
        version = next((r["version"] for r in local_sessions().values() if r.get("version")), "2.1.318")
        now = int(time.time() * 1000)
        # minimal record in the shape of a real one; the listing keys on messagingSocketPath
        rec = {"pid": pid, "sessionId": str(uuid.uuid5(uuid.NAMESPACE_URL, addr)), "cwd": f"gc://{addr}",
               "startedAt": now, "procStart": "1", "version": version, "peerProtocol": 1, "peerFeatures": ["notify_idle"],
               "kind": "interactive", "entrypoint": "cli",
               "pidDomain": f"linux:{hashlib.md5(addr.encode()).hexdigest()}:pid:[1]",
               "messagingSocketPath": sock, "name": display(addr), "nameSource": "peer", "nameSince": now,
               "status": "idle", "updatedAt": now, "statusUpdatedAt": now}
        save(f"{SESS}/{pid}.json", rec)
        key = f"{SESS}/{pid}.{hashlib.sha256(sock.encode()).hexdigest()}.key"
        with open(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump({"peerToken": secrets.token_hex(16), "procStart": "1", "pidDomain": rec["pidDomain"]}, f)

    def dematerialize(self, addr):
        srv = self.servers.pop(addr, None)
        if srv:
            srv.close()
        info = self.fake.get(addr)
        if info:
            for f in glob.glob(f"{SESS}/{info['pid']}.*") + [info["sock"]]:
                try:
                    os.unlink(f)
                except FileNotFoundError:
                    pass

    def purge(self):
        for a in list(self.fake):
            self.dematerialize(a)

    # ---- message paths ------------------------------------------------------------------
    async def on_proxy(self, addr, r, w):
        """a local session wrote to the proxy socket of remote `addr`"""
        try:
            while line := await r.readline():
                m = json.loads(line)
                src = m.get("from", "")[4:]
                name = next((n for n, s in local_sessions().items() if s["messagingSocketPath"] == src), None)
                if name:
                    await self.hub({"t": "send", "to": addr, "from": name, "payload": line.decode()})
        except Exception as e:
            print("proxy:", e, flush=True)
        finally:
            w.close()

    async def deliver(self, m):
        local = local_sessions().get(m["to"])
        if not local:
            return
        await self.materialize(m["from"])
        proxy = self.fake[m["from"]]["sock"]
        disp = display(m["from"])
        if m["t"] == "send":
            p = json.loads(m["payload"])
            p["from"] = f"uds:{proxy}"
            c = p.get("message", {}).get("content")
            if isinstance(c, str):
                c = re.sub(r'from="uds:[^"]*"', f'from="uds:{proxy}"', c)
                p["message"]["content"] = re.sub(r'from-name="[^"]*"', f'from-name="{disp}"', c)
            line = json.dumps(p)
        else:
            d = f"{INBOX}/{short(m['from'].partition('/')[0])}"
            os.makedirs(d, exist_ok=True)
            path = f"{d}/{os.path.basename(m['name'])}"
            with open(path, "wb") as f:
                f.write(base64.b64decode(m["data"]))
            line = message(proxy, disp, f"{disp} sent you a file: {path}\n(also at {m['url']})")
        await self.write_sock(local["messagingSocketPath"], line)

    async def notify(self, session_name, text):
        local = local_sessions().get(session_name or "")
        if local:
            await self.write_sock(local["messagingSocketPath"], message(CTRL, "gc-bridge", text))

    async def write_sock(self, path, line):
        r, w = await asyncio.open_unix_connection(path)
        w.write(line.encode() + b"\n")
        await w.drain()
        w.close()

    # ---- transcripts ------------------------------------------------------------------------
    def resolve(self, req, m):
        f = self.pending.pop(req, None)
        if f and not f.done():
            f.set_result(m)

    async def send_transcript(self, m):
        """owner side: the hub verified the requester may have this session's history"""
        reply = {"req": m["req"], "reply_user": m["reply_user"], "reply_machine": m["reply_machine"]}
        local = local_sessions().get(m["to"])
        path = transcript_path(local) if local else ""
        if not os.path.exists(path):
            await self.hub({"t": "error", "msg": f"no transcript found for {m['to']}", **reply})
            return
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        await self.hub({"t": "transcript", "name": m["to"], "cwd": local["cwd"], "data": data, **reply})

    async def fetch_transcript(self, disp):
        addr = self.addr_of(disp)
        req = uuid.uuid4().hex[:8]
        fut = self.pending[req] = asyncio.get_running_loop().create_future()
        await self.hub({"t": "transcript_req", "to": addr, "req": req})
        r = await asyncio.wait_for(fut, 120)
        if r["t"] == "error":
            raise ValueError(r["msg"])
        d = f"{GC}/transcripts"
        os.makedirs(d, exist_ok=True)
        path = f"{d}/{disp.replace(':', '-')}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return {"path": path, "cwd": r["cwd"]}

    # ---- control socket for the gc CLI -----------------------------------------------------
    async def on_ctrl(self, r, w):
        res = {"ok": True}
        try:
            m = json.loads(await r.readline())
            if m["cmd"] == "status":
                res.update(user=self.user, connected=bool(self.w), machine=MACHINE,
                           peers=[display(a) for a in self.peers],
                           history=[display(a) for a, s in self.peers.items() if s.get("history")],
                           shared=load(SHARED, {}))
            elif m["cmd"] == "send-file":
                addr = self.addr_of(m["to"])
                with open(m["path"], "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                await self.hub({"t": "file", "to": addr, "from": m["from"], "name": os.path.basename(m["path"]), "data": data})
            elif m["cmd"] == "transcript":
                res.update(await self.fetch_transcript(m["to"]))
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        w.write((json.dumps(res) + "\n").encode())
        await w.drain()
        w.close()


async def main():
    os.makedirs(INBOX, exist_ok=True)
    with open(f"{GC}/bridge.pid", "w") as f:
        f.write(str(os.getpid()))
    b = Bridge()
    b.purge()
    if os.path.exists(CTRL):
        os.unlink(CTRL)
    ctrl = await asyncio.start_unix_server(b.on_ctrl, CTRL)
    stop = asyncio.Event()
    for s in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(s, stop.set)
    tasks = [asyncio.create_task(b.run_hub()), asyncio.create_task(b.run_publish())]
    await stop.wait()
    for t in tasks:
        t.cancel()
    b.purge()
    ctrl.close()


asyncio.run(main())
