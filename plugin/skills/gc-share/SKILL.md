---
name: gc-share
description: Share or unshare the current Claude Code session with coworkers over intern-groupchat, or explain who can see it. Use when the user says "share this session with alice", "let bob see this", "share with history", "make this session visible to the team", "unshare", "stop sharing", "who is this shared with", or asks what the "alice:pr-123" entries in /peers are.
---

Sessions are private until shared. Sharing makes this session appear in the other
person's `/peers` as `<you>:<session name>`; they can then message it, and you see their
messages here like any peer message. Remote sessions shared with you appear as
`<user>:<name>`. Files sent to you land in `~/.gc/inbox/<user>/`.

- Share: `"$HOME/.gc/bin/gc" share <names...>` — names are first names of
  tailscale logins (`alice`), full logins (`alice@github`), or `*` for everyone on the hub.
- Share with history: add `--with-history` — then those people can also fetch this
  session's full transcript (`gc transcript`) or fork it (`gc fork`). Use it when the user
  says "with history", "including history", "so they can fork it", "give them the full context".
- Unshare: `"$HOME/.gc/bin/gc" unshare`
- Status / who can see what: `"$HOME/.gc/bin/gc" status`

- Name: sessions are shared under the user's name for them, else their terminal title. If `gc share`
  prints a note that the name is automatic (no title yet), run the same share command again with
  `--as <name>`, a short kebab-case name for what this session is doing (`slope-plot`,
  `pr-123-review`, `velocity-clamp-bug`), and tell the user the name. The share name sticks
  for later `gc share` calls on this session.

Run the command with Bash (it identifies this session from the environment). Report the one-line result. If it says the bridge isn't running, run
`"$HOME/.gc/bin/gc" ensure-bridge` and retry once.
