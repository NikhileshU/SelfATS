#!/bin/bash
# Registers the job-aggregator MCP server in Claude Desktop's config.
# Must run while the Claude app is QUIT — the app rewrites its config file
# on exit and will clobber edits made while it is running. This script
# quits the app itself, patches the config, and relaunches.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
UV_BIN="$(command -v uv || echo /opt/homebrew/bin/uv)"

echo "Quitting Claude..."
osascript -e 'quit app "Claude"' 2>/dev/null || true
for _ in $(seq 1 20); do
  pgrep -xq Claude || break
  sleep 1
done
if pgrep -xq Claude; then
  echo "Claude is still running — quit it manually and re-run this script." >&2
  exit 1
fi

python3 - "$CONFIG" "$UV_BIN" "$REPO_DIR" <<'EOF'
import json, sys

config_path, uv_bin, repo_dir = sys.argv[1:4]
with open(config_path) as f:
    config = json.load(f)

config.setdefault("mcpServers", {})["job-aggregator"] = {
    "command": uv_bin,
    "args": ["run", "--directory", repo_dir, "job-aggregator-mcp"],
}

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print("Patched", config_path)
EOF

echo "Relaunching Claude..."
open -a Claude
echo "Done. Check Settings -> Developer (or the tools icon in a new chat) for job-aggregator."
