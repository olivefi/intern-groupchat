# intern-groupchat

Share Claude Code sessions and files with coworkers. Everyone keeps using `claude` exactly
as before on their own machine; sessions you share show up in their `/peers` and they can
talk to them — "tell oli:pr-5 the velocity clamp is wrong", "ask oli:repo-agent for the
slope plot", "send alice the rosbag", "fork bob:analysis here". User guide: [GUIDE.md](GUIDE.md).
Design: [ARCHITECTURE.md](ARCHITECTURE.md).

Needs: python3 and Claude Code ≥ 2.1.224 on every machine, Tailscale on the hub. Clients
bring their own userspace Tailscale (no root), so nothing to install there.

## Hub (once, on an always-on machine — e.g. the jetson)

```sh
git clone git@github.com:olivefi/intern-groupchat.git && cd intern-groupchat
GC_STORE=/mnt/ssd/gc-hub/store hub/install.sh     # system service, starts after tailscale at boot
```
It prints the hub node name (e.g. `gc-hub.tail4e78b.ts.net`). In https://login.tailscale.com/admin/machines
disable key expiry on it. Give someone access: share that machine with them (⋯ → Share).
Revoke = unshare.

## Everyone (once per machine)

Accept the hub share link (any Tailscale account: GitHub/Google/…), then:
```sh
git clone git@github.com:olivefi/intern-groupchat.git ~/.gc/intern-groupchat
~/.gc/intern-groupchat/install.sh gc-hub.<tailnet>.ts.net
```
It prints one login link — open it, done. Nothing else changes. The client runs its own
Tailscale in userspace mode as you (no sudo, no tun device), which also works under VPN
clients like Cisco Secure Client that block traffic on other interfaces. If you already
have a system Tailscale logged in and no such VPN, `--system-tailscale` uses it instead.

## Using it

| You say, inside any `claude` session | What happens |
|---|---|
| "share this session with alice and bob" | it appears in their `/peers` as `<you>:<session name>` |
| "share this session with alice with history" | same, and Alice may also fetch or fork its transcript |
| "stop sharing this session" | it disappears |
| `/peers` | shows your peers, including remote shared ones: `alice:pr-123`, `oli:repo-agent` |
| "tell alice:pr-123 the velocity clamp on line 40 is wrong" | arrives in Alice's terminal as a normal peer message; her agent replies to you |
| "send plot.html to alice:pr-123" | lands in her `~/.gc/inbox/<you>/plot.html`; her session is told, with an http link too |
| "what has alice:pr-123 done so far" | fetches the transcript (if shared with history) and summarises it |
| "fork alice:pr-123 here" | starts a local background session with Alice's whole conversation as context; `claude attach alice-pr-123-fork` |
| "wait for alice:pr-123's answer" | your session idles until the reply arrives |

Name a session with `claude --name pr-123` (or `/rename`) so it's recognisable; otherwise
it's the auto name. You always see your own sessions on your other machines.

Receiving side: everything Claude Code already does with peer messages applies — messages
can't approve permission prompts, and `"crossSessionInbound": "hold"` in settings makes
your agent wait for your OK before acting on them.

**Repo agent** (a session anyone can ask about a repo): in the repo,
`claude --bg --name repo-agent --permission-mode auto "You answer questions about this repo for coworkers; write results to files and send them with gc send-file."`
then `~/.gc/bin/gc share --name repo-agent '*'`. It runs until you `claude stop` it.

## CLI (what the skills call)

```
~/.gc/bin/gc status | peers
~/.gc/bin/gc share   --pid $PPID|--name <session> [--with-history] <names...|*>
~/.gc/bin/gc unshare --pid $PPID|--name <session>
~/.gc/bin/gc send-file --pid $PPID|--name <session> <peer> <path>
~/.gc/bin/gc transcript <peer>                    # → ~/.gc/transcripts/<peer>-<time>.jsonl + .md
~/.gc/bin/gc fork [--bg] [--cwd DIR] <peer>       # continue that conversation as your own session
```
From a terminal, `gc fork alice:pr-123` opens the forked session right there; `--bg` (what
the skill uses) starts it in the background for `claude attach`.

Bridge log: `~/.gc/bridge.log`; userspace tailscale state and log: `~/.gc/tailscale/`.
Update: `git pull` in the clone (hub: `sudo systemctl restart gc-hub`).
To ssh into the hub machine through the userspace tailscale (e.g. under a VPN):
`ssh -o ProxyCommand='nc -X 5 -x 127.0.0.1:1055 %h %p' <user>@gc-hub`.

## Layout

```
hub/        hub.py + install.sh (systemd)
bridge/     gc-bridge.py (daemon), gc (CLI)
plugin/     Claude Code plugin: SessionStart hook + skills (symlinked to ~/.claude/skills/gc)
install.sh  client install
GUIDE.md    user guide for coworkers
```
