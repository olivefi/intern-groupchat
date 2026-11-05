#!/bin/bash
# Run once on the hub machine (e.g. the jetson). Installs the hub as a system service that
# starts at boot after tailscale.   GC_STORE=/path/to/store ./install.sh   (default ~/.gc-hub/store)
set -e
dir=$(cd "$(dirname "$0")" && pwd)
store=${GC_STORE:-$HOME/.gc-hub/store}
command -v tailscale >/dev/null || { echo "install tailscale first:  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up --ssh"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }

mkdir -p "$store"
sudo tee /etc/systemd/system/gc-hub.service >/dev/null <<EOF
[Unit]
Description=intern-groupchat hub
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$USER
Environment=GC_STORE=$store
ExecStart=$(command -v python3) $dir/hub.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now gc-hub
sleep 2
systemctl --no-pager status gc-hub | head -3
node=$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || echo "<not logged in yet: sudo tailscale up --ssh>")
echo
echo "hub node: $node"
echo "coworkers install with:  ./install.sh $node"
echo "give someone access: share this machine with them in https://login.tailscale.com/admin/machines"
