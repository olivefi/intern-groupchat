---
name: gc-fork
description: Fetch the full transcript of a coworker's shared Claude Code session, or fork it into a local session with all its context. Use when the user says "get the full context of alice:pr-123", "what has bob's agent done so far", "fork alice's session", "split off from oli:repo-agent", "continue their session here". Peers are the `<user>:<name>` entries from /peers; their owner must have shared with history.
---

- Just read it: `"$HOME/.gc/bin/gc" transcript <peer>` → prints the raw `.jsonl` path and a
  readable `.md`; Read the `.md` and answer the user's question from it.
- Fork it (continue with full context, as a separate session): from inside a session use
  `"$HOME/.gc/bin/gc" fork --bg <peer> --cwd <local checkout of the same repo>`; it prints
  `claude attach <name>` for the user. From a terminal the user can run
  `gc fork <peer>` directly for an interactive one.

The fork is a copy: it diverges from the owner's live session. Paths in the transcript refer
to the owner's checkout; the fork's first prompt explains the new location to the model.
If the command says history is not shared, tell the user the owner has to run
`gc share --with-history <names>` (or say "share this session with X including history").
