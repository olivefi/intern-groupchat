# intern-groupchat — user guide

You use Claude Code (`claude`) as always. This adds three things: coworkers' shared
sessions appear in your `/peers`, you can share yours, and you can send files or whole
conversations around. There is no new UI; you just talk to your own Claude.

## Setup (5 minutes, once per machine)

1. The hub owner sends you a Tailscale share link. Open it and sign in with any account
   (GitHub, Google, …). If you don't have Tailscale installed, you don't need it — the next
   step brings its own.
2. In a terminal:
   ```sh
   git clone git@github.com:olivefi/intern-groupchat.git ~/.gc/intern-groupchat
   ~/.gc/intern-groupchat/install.sh gc-hub.<tailnet>.ts.net      # address from the owner
   ```
   It prints a link; open it and log in with the same account as in step 1. That's it.
3. Start `claude` as usual. `/peers` lists what's shared with you (may be empty for now).

Nothing runs as root. The pieces live in `~/.gc/` and start themselves whenever you start
`claude`.

## Names

- You are your Tailscale login's first part: `alice@github` → `alice`.
- A shared session is `<owner>:<session name>`, e.g. `oli:pr-5`, `oli:repo-agent`.
- Give your own sessions a name so others can recognise them: `claude --name pr-123`, or
  `/rename pr-123` inside.

## Talking to a shared session

Just tell your Claude what you want, naming the peer:

> tell oli:pr-5 that the velocity clamp on line 40 is wrong

> ask oli:repo-agent to regenerate the slope plot for run 7b04a4 and send it to me

> wait for oli:repo-agent's answer

The message arrives in Oli's terminal as a normal peer message; his agent handles it and
replies into your session. You'll see the reply as a message from `oli:pr-5`.

Things to know:
- Your messages can't approve anything on the other side; the owner stays in control.
- A session that's busy gets your message on its next turn; an idle one wakes up.
- If a peer isn't listed anymore, its owner stopped sharing it or closed it.

## Sharing your session

Inside the session you want to share:

> share this session with oli and bob

> share this session with oli, with history      ← lets him fetch / fork the conversation

> stop sharing this session

Private is the default. Sharing with `everyone` (or `*`) means everyone on the hub.
Messages from peers show up in your terminal; to review them before your agent acts,
put `"crossSessionInbound": "hold"` in `~/.claude/settings.json`.

## Files

> send plot.html to oli:pr-5

The file lands in Oli's `~/.gc/inbox/alice/plot.html` and his session is told, with an
http link as well. Files others send you are in `~/.gc/inbox/<their name>/`.

## Getting someone's full context, or splitting off

If a session was shared **with history**, you can:

> what has oli:pr-5 done so far                   ← fetches the transcript and summarises

> fork oli:pr-5 here                               ← new local session with Oli's whole
                                                     conversation as its memory

The fork is a background session named `oli-pr-5-fork`; open it with
`claude attach oli-pr-5-fork`. Run it in your own clone of the same repo (say "fork
oli:pr-5 in ~/work/lunarleaper" or let it use the current directory). It's a copy: from
then on it's yours and diverges from Oli's live session.

From a terminal the same is `gc fork oli:pr-5` (opens it right there) and
`gc transcript oli:pr-5` (just the files, `.jsonl` and a readable `.md`).

## Without a terminal: the web page

`~/.gc/bin/gc web` opens the hub's page in your browser (or go to
`http://gc-hub.<tailnet>.ts.net:7778/` if your Tailscale is the normal one). It lists the
sessions you may see; pick one, write to its agent, read the replies, send or download files,
read its history. Coworkers who never run `claude` only need the Tailscale app for this.

## Repo agents

Owners can leave a session running in a repo and share it with everyone, typically named
`repo-agent`. Treat it like a colleague who knows that repo: ask it questions, ask for
analyses or plots, ask it to send you results.

## If something's off

- `~/.gc/bin/gc status` — am I connected, as whom, what do I see, what do I share.
- `~/.gc/bin/gc ensure-bridge` — (re)start the pieces by hand.
- Logs: `~/.gc/bridge.log`, `~/.gc/tailscale/tailscaled.log`.
- Peer not listed although the owner shared it: are you both online, did the owner spell
  your name as it appears in `gc status` (`user`)?
- Update: `cd ~/.gc/intern-groupchat && git pull`, then `gc stop && gc ensure-bridge`.
