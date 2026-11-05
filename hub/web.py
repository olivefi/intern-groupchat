"""Browser UI for the hub: one page, identity from tailscale like everything else.
Each browser user is a virtual session <user>/web, so agents can reply to it."""
import __main__ as hub  # hub.py runs as the script
import asyncio, base64, json, os, re, shutil, threading, time, uuid
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
IDLE = 120  # seconds without a poll before the web session disappears from peers
FILE_TTL_DAYS = float(os.environ.get("GC_FILE_TTL_DAYS", 7))  # files in the store are deleted after this
# chat histories, outside the file store (which is served over http)
HISTORY = os.environ.get("GC_WEB_HISTORY") or os.path.join(os.path.dirname(hub.STORE), "web-history")
parked = {}  # user -> idle WebConn, kept so the chat history survives closing the tab


def cross_session(text):
    """what a Claude Code session would write; the receiving bridge rewrites from/from-name"""
    return json.dumps({"msgV": 1, "msg_id": str(uuid.uuid4()), "type": "user", "priority": "next", "from": "uds:gc-web",
                       "message": {"role": "user", "content":
                       f'<cross-session-message from="uds:gc-web" from-name="web" from-mode="prompting">\n{text}\n</cross-session-message>'}})


def text_of(payload):
    m = json.loads(payload)
    if m.get("type") != "user":
        return None
    c = m.get("message", {}).get("content", "")
    if not isinstance(c, str):
        c = "".join(b.get("text", "") for b in c if b.get("type") == "text")
    return re.sub(r"</?cross-session-message[^>]*>", "", c).strip()


def render(jsonl):
    out = []
    for line in jsonl.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") not in ("user", "assistant"):
            continue
        content = e.get("message", {}).get("content", "")
        if isinstance(content, str):
            out.append({"role": e["type"], "text": content.strip()})
            continue
        for b in content:
            if b.get("type") == "text" and b["text"].strip():
                out.append({"role": e["type"], "text": b["text"].strip()})
            elif b.get("type") == "tool_use":
                out.append({"role": "tool", "text": f"[{b['name']}] {json.dumps(b.get('input', {}))[:200]}"})
    return out


class WebConn(hub.Conn):
    def __init__(self, user):
        super().__init__(user, "web", None)
        self.sessions = {"web": {"acl": [], "history": False}}
        self.path = os.path.join(HISTORY, re.sub(r"[^\w@.-]", "_", user) + ".json")
        saved = json.load(open(self.path)) if os.path.exists(self.path) else {"queue": [], "seq": 0}
        self.queue, self.seq, self.seen = saved["queue"], saved["seq"], time.time()
        self.cv = threading.Condition()
        self.pending = {}  # transcript req -> [event, reply]

    async def send(self, obj):
        t = obj["t"]
        if t == "transcript" or (t == "error" and obj.get("req")):
            p = self.pending.get(obj["req"])
            if p:
                p[1] = obj
                p[0].set()
            return
        if t == "send":
            text = text_of(obj["payload"])
            if text is None:
                return
            item = {"from": obj["from"], "text": text}
        elif t == "file":
            item = {"from": obj["from"], "text": f"sent you a file: {obj['name']}", "url": obj["url"]}
        elif t == "error":
            item = {"from": "hub", "to": obj.get("to"), "text": obj["msg"]}
        else:
            return
        self.push(item)

    def push(self, item):
        with self.cv:
            self.seq += 1
            self.queue = (self.queue + [{"seq": self.seq, "ts": time.time(), **item}])[-300:]
            os.makedirs(HISTORY, exist_ok=True)
            with open(self.path + ".tmp", "w") as f:
                json.dump({"queue": self.queue, "seq": self.seq}, f)
            os.replace(self.path + ".tmp", self.path)
            self.cv.notify_all()

    def wait(self, after, timeout):
        with self.cv:
            self.cv.wait_for(lambda: self.seq > after, timeout)
            return [m for m in self.queue if m["seq"] > after]


def web_conn(user):
    c = hub.conn_of(user, "web")
    if not c:
        c = parked.pop(user, None) or WebConn(user)
        hub.conns.add(c)
        run(hub.push_peers())
    c.seen = time.time()
    return c


def run(coro, timeout=130):
    return asyncio.run_coroutine_threadsafe(coro, hub.loop).result(timeout)


def expire_files():
    cutoff = time.time() - FILE_TTL_DAYS * 86400
    for d in os.listdir(hub.STORE):
        p = os.path.join(hub.STORE, d)
        if re.fullmatch(r"[0-9a-f]{12}", d) and os.path.getmtime(p) < cutoff:
            shutil.rmtree(p, ignore_errors=True)


async def expire():
    swept = 0
    while True:
        if time.time() - swept > 3600:
            expire_files()
            swept = time.time()
        await asyncio.sleep(30)
        stale = [c for c in hub.conns if isinstance(c, WebConn) and time.time() - c.seen > IDLE]
        for c in stale:
            hub.conns.discard(c)
            parked[c.user] = c
        if stale:
            await hub.push_peers()


class Handler(hub.Files):
    def user(self):
        u = hub.whois(self.client_address[0]) or (hub.DEV_TRUST_HELLO and "dev@local")
        if not u:
            self.reply(403, {"error": "unknown tailscale identity"})
        return u

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            body = open(f"{HERE}/web.html", "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/state":
            u = self.user()
            if not u:
                return
            c = web_conn(u)
            msgs = c.wait(int(q.get("after", 0)), float(q.get("wait", 15)))
            peers = [v for v in hub.visible(u) if v["addr"] != f"{u}/web"]
            self.reply(200, {"user": u, "peers": peers, "msgs": msgs, "seq": c.seq, "file_ttl_days": FILE_TTL_DAYS})
        elif url.path == "/api/transcript":
            u = self.user()
            if not u:
                return
            c = web_conn(u)
            req = uuid.uuid4().hex[:8]
            c.pending[req] = [threading.Event(), None]
            run(hub.relay(c, {"t": "transcript_req", "to": q["to"], "req": req}))
            c.pending[req][0].wait(120)
            r = c.pending.pop(req)[1]
            if not r:
                self.reply(504, {"error": "no answer from the session's machine"})
            elif r["t"] == "error":
                self.reply(400, {"error": r["msg"]})
            elif q.get("raw"):
                body = base64.b64decode(r["data"])
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Disposition", f'attachment; filename="{q["to"].replace("/", "-")}.jsonl"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.reply(200, {"cwd": r["cwd"], "items": render(base64.b64decode(r["data"]).decode(errors="replace"))})
        else:
            self.sandbox = True  # files from peers run in an opaque origin, away from the API
            super().do_GET()

    def end_headers(self):
        if getattr(self, "sandbox", False):
            self.send_header("Content-Security-Policy", "sandbox allow-scripts allow-popups allow-downloads")
        super().end_headers()

    def do_POST(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if self.headers.get("X-GC") != "1":  # other sites can't set this header, so they can't post as you
            return self.reply(403, {"error": "missing X-GC header"})
        u = self.user()
        if not u:
            return
        c = web_conn(u)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if url.path == "/api/send":
            m = json.loads(body)
            c.push({"from": "me", "to": m["to"], "text": m["text"]})
            run(hub.relay(c, {"t": "send", "to": m["to"], "from": "web", "payload": cross_session(m["text"])}))
        elif url.path == "/api/file":
            name = os.path.basename(q["name"])
            link = run(hub.relay(c, {"t": "file", "to": q["to"], "from": "web", "name": name, "data": base64.b64encode(body).decode()}))
            if link:
                c.push({"from": "me", "to": q["to"], "text": f"sent file {name}", "url": link})
        else:
            return self.reply(404, {"error": "no such endpoint"})
        self.reply(200, {"ok": True})
