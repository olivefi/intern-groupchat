---
name: gc-send-file
description: Send a file to a coworker's Claude Code session over intern-groupchat. Use when the user says "send plot.html to alice", "give bob this file", "send this to alice:pr-123", or when a peer asks for a file. Peers are the `<user>:<name>` entries from /peers.
---

`"$HOME/.gc/bin/gc" send-file --pid $PPID <peer> <path>` — `<peer>` exactly as listed by
`/peers` or `"$HOME/.gc/bin/gc" peers` (e.g. `alice:pr-123`), `<path>` any local file.

Run it with Bash (`$PPID` must be evaluated by the Bash tool). The file lands in the
recipient's `~/.gc/inbox/<you>/` and their session gets a message with the path and an
https link. If the peer isn't listed, show the user `gc peers` output and ask which one.
For a plain message (no file), use SendMessage to the peer as usual.
