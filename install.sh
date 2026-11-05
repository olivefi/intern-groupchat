#!/bin/bash
# One-time install on a machine that runs claude:
#   ./install.sh <hub node>                      e.g. ./install.sh gc-hub.tail4e78b.ts.net
#   ./install.sh <hub node> --system-tailscale   use an already-installed, logged-in system tailscale instead
#
# By default this runs its own tailscale in userspace mode as you (no root, no tun device). That
# also works under VPN clients such as Cisco Secure Client that block other interfaces.
set -e
hub=${1:?usage: install.sh <hub address[:port]> [--system-tailscale]}
[[ "$hub" =~ ^[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || { echo "bad hub address '$hub' (expected e.g. gc-hub.<tailnet>.ts.net)"; exit 1; }
dir=$(cd "$(dirname "$0")" && pwd)
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v claude >/dev/null || { echo "claude (Claude Code) is required"; exit 1; }

mkdir -p ~/.gc/bin ~/.gc/inbox ~/.claude/skills
chmod +x "$dir/bridge/gc" "$dir/bridge/gc-bridge.py"
ln -sfn "$dir/bridge/gc" ~/.gc/bin/gc
ln -sfn "$dir/plugin" ~/.claude/skills/gc

if [ "$2" = --system-tailscale ]; then
  command -v tailscale >/dev/null || { echo "no system tailscale found"; exit 1; }
  printf '{"hub": "%s"}\n' "$hub" > ~/.gc/config.json
else
  ts=~/.gc/tailscale
  mkdir -p "$ts/state"
  if [ ! -x "$ts/tailscaled" ]; then
    if [ -x /usr/sbin/tailscaled ] && [ -x /usr/bin/tailscale ]; then
      ln -sfn /usr/sbin/tailscaled "$ts/tailscaled"; ln -sfn /usr/bin/tailscale "$ts/tailscale"
    elif [ "$(uname -s)" = Linux ]; then
      case "$(uname -m)" in x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch"; exit 1 ;; esac
      tgz=$(curl -fsSL "https://pkgs.tailscale.com/stable/?mode=json" | python3 -c "import json,sys; print(json.load(sys.stdin)['Tarballs']['$arch'])")
      echo "downloading $tgz"
      curl -fsSL "https://pkgs.tailscale.com/stable/$tgz" | tar xz -C "$ts" --strip-components=1 --wildcards '*/tailscale' '*/tailscaled'
    else
      echo "macOS: brew install tailscale, then rerun"; exit 1
    fi
  fi
  printf '{"hub": "%s", "socks": "127.0.0.1:1055", "tailscale": "%s"}\n' "$hub" "$ts" > ~/.gc/config.json
  ~/.gc/bin/gc ensure-tailscale
  cli="$ts/tailscale --socket $ts/ts.sock"
  if ! $cli ip -4 >/dev/null 2>&1; then
    : > "$ts/up.log"
    ($cli up --hostname "$(hostname -s)-gc" > "$ts/up.log" 2>&1 &)
    for i in $(seq 1 30); do grep -q https "$ts/up.log" && break; sleep 1; done
    echo; echo ">>> Open this link and log in with your Tailscale account:"; echo; grep -o 'https://[^ ]*' "$ts/up.log"; echo
    printf "waiting for login"
    until $cli ip -4 >/dev/null 2>&1; do printf .; sleep 3; done
    echo " ok"
  fi
  echo "tailscale node: $($cli status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
  node=${hub%%:*}; node=${node%%.*}
  if ! $cli status | grep -qw "$node"; then
    echo; echo "!!! $node is not visible from this tailnet. You probably logged in before accepting the"
    echo "    hub owner's invite (or with a different account). Accept the invite, then rerun:"
    echo "    $cli up --force-reauth"
  fi
fi

cp "$dir/INSTALL_VERSION" ~/.gc/install_version
~/.gc/bin/gc ensure-bridge
sleep 3
~/.gc/bin/gc status | head -5 || true
echo
echo "done. Start claude as usual: /peers shows sessions shared with you;"
echo "say 'share this session with <name>' to share yours, 'send <file> to <peer>' to send files."
