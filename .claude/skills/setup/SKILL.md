---
name: setup
description: Set up intern-groupchat — the hub on an always-on machine (e.g. the jetson) and/or the client bridge on this machine.
---

Ask which side to set up if unclear. Do each step, show the result, stop on failure.

**Hub (once, on the always-on machine):**
1. Tailscale must be up on that machine (`tailscale status`). If not: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`.
2. Clone this repo there and run `hub/install.sh`. It prints the hub node name.
3. Tell the user: share that machine with each coworker in https://login.tailscale.com/admin/machines
   (or invite them to the tailnet). If the tailnet ACL isn't the default allow-all, it needs
   `src: ["autogroup:member", "autogroup:shared"]` → `dst: ["<hub>:7777,7778"]`.

**Client (every machine that runs claude, including the owner's):**
1. Tailscale installed and connected; the hub node reachable (`tailscale ping <hub>`).
2. `./install.sh <hub node>` from this repo.
3. Restart claude; `/peers` should list shared sessions once there are any. `~/.gc/bin/gc status` shows the bridge state.

**Repo agent (optional):** in the repo, `claude --bg --name repo-agent --permission-mode auto "<instructions>"`,
then `~/.gc/bin/gc share --name repo-agent '*'` (or specific names). It appears as `<you>:repo-agent` for them.
