# intern-groupchat — architecture

Goal: coworkers keep using plain `claude` on their own machines, and can still message
each other's live sessions, talk to repo agents, and send files — with nothing to notice
beyond a one-time install.

## Core idea: extend the native mesh across machines

Claude Code's cross-session messaging (`/peers`, `SendMessage`) is "same machine, same
user": each session binds a Unix socket and registers itself as a JSON file in
`~/.claude/sessions/`. Messages are newline-delimited JSON written to the socket:

```
{"msgV":1,"msg_id":…,"type":"user","priority":"next","from":"uds:/run/user/1000/cc-socks/<pid>.sock",
 "message":{"role":"user","content":"<cross-session-message from=\"uds:…\" from-name=\"oli-22\" from-mode=\"prompting\">…</cross-session-message>"}}
```

The `from` address is the sender's own socket path, and the receiver replies by writing to
it. Verified on 2026-11-04: a registry entry with a foreign pid and pidDomain whose socket
is a proxy is listed and messaged like any local session.

So the bridge needs no new UX: it makes remote sessions *look local*.

```
 Alice's laptop                       hub (jetson, tailscale)                    Oli's workstation
 claude ──/peers──▶ ~/.claude/sessions  ┌──────────────────────────┐   ~/.claude/sessions ◀──/peers── claude
   "oli:pr-5" ─▶ proxy sock ─▶ gc-bridge ─▶ directory · ACL · relay ◀─ gc-bridge ─▶ real sock of "pr-5"
                                          │ file store (http)       │
                                          └──────────────────────────┘
```

## Components

| | |
|---|---|
| `hub/hub.py` | One process on an always-on tailnet node. Identity of each connection = `tailscale whois`. Keeps the directory of online sessions + ACLs, relays message lines and files between bridges, serves files over http. Stateless except the file store. |
| `bridge/gc-bridge.py` | One per machine/user. Publishes local sessions (name + who they're shared with). For each remote session it may see, writes a registry entry named `<user>:<name>` and a proxy socket; forwards lines to the hub; on delivery rewrites `from` to the local proxy for the sender so replies route back. Also delivers files into `~/.gc/inbox/<user>/` and injects a native message about them. |
| `bridge/gc` | CLI: `share`, `unshare`, `send-file`, `status`, `ensure-bridge`. |
| `plugin/` | Claude Code plugin (symlinked into `~/.claude/skills/gc`): a `SessionStart` hook that starts the bridge if needed, and skills so "share this session with alice" / "send plot.html to bob" work in natural language. |
| `install.sh`, `hub/install.sh` | Client one-liner; hub systemd service. |

## Semantics

* **Private by default.** All local sessions are published to the hub by name, but only
  shared ones are visible to others. Sharing is per session: `gc share --pid $PPID alice`
  (the skill does this), ACL = first names, full logins, or `*`.
* **Contact rule.** If A messages B, A's session becomes visible to B's user (so B can
  reply) even if A never shared it.
* **Own sessions everywhere.** You always see your own sessions on your other machines.
* **Receiving.** Messages land in the TUI as `Message from @alice:pr-123`; everything
  Claude Code already does with peer messages applies (`crossSessionInbound: hold|refuse`,
  no permission approval via messages).
* **Files.** `gc send-file <peer> <path>`: uploaded to the hub store, pushed to the peer's
  machine (`~/.gc/inbox/<you>/`), and announced in their session with the path and an http
  link. Links work in a browser for anyone on the tailnet.
* **Repo agents** are ordinary `claude --bg --name repo-agent` sessions that are shared.
* **History.** `gc share --with-history` additionally lets those people fetch the
  session's transcript (`~/.claude/projects/<cwd-encoded>/<id>.jsonl`) through the hub
  (`transcript_req` → owner's bridge → requester). `gc transcript` renders it to markdown;
  `gc fork` resumes it locally with `claude --resume <file> --fork-session`, which keeps the
  whole conversation as context in the requester's own checkout — a copy that diverges
  from the owner's live session. Verified: resume by path works across project dirs.

## Tailscale's role

Reachability (the hub is the only thing that must be reachable; bridges dial out),
identity (`whois`, so no tokens or invites), encryption. Coworkers get the hub node shared
with them — one action per person, also the revocation point.

Clients run their **own tailscaled in userspace-networking mode** (`~/.gc/tailscale/`,
started by `gc ensure-bridge`, no root, no tun) and the bridge reaches the hub through its
SOCKS5 proxy. Reason, found the hard way: Cisco Secure Client (ETH VPN) in full-tunnel
mode filters new flows on every other interface, so a kernel-mode `tailscale0` is
unreachable while the VPN is up, although Tailscale's own UDP still gets out. Userspace
mode never touches the kernel path, so it works regardless — and it needs no sudo, which
makes the coworker install trivial. The hub (jetson) uses the normal system tailscale.

## Risks

* The registry/socket format is internal to Claude Code and may change; everything that
  depends on it is in `gc-bridge.py` (`local_sessions`, `materialize`, `deliver`).
* The hub sees session names and relays message text (it is the owner's machine).
* Anyone the hub trusts can message a shared session; messages can't approve permissions,
  but a session in auto mode acts on them. Share repo agents accordingly.

## Rejected alternatives

ssh into a shared container per repo (coworkers must change how they work, context lost),
moving transcripts between machines (same), Channels (needs org toggle + a dialog per
session, different UX), Discord bots (one bot per session, external dependency), Cloudflare
Tunnel (needs a domain; no better than tailscale here).
