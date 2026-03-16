#!/bin/bash
set -e

NEM_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_JSON="$HOME/.claude.json"

echo "Installing dependencies..."
pip install -r "$NEM_DIR/requirements.txt" -q

echo "Registering nem MCP server in $CLAUDE_JSON..."
python3 - <<EOF
import json, sys
from pathlib import Path

path = Path("$CLAUDE_JSON")
config = json.loads(path.read_text()) if path.exists() else {}

servers = config.setdefault("mcpServers", {})
if "nem" in servers:
    print("nem already registered — skipping.")
else:
    servers["nem"] = {
        "type": "stdio",
        "command": "python3",
        "args": ["$NEM_DIR/mcp_server.py"]
    }
    path.write_text(json.dumps(config, indent=2))
    print("nem registered.")
EOF

echo "Done. Restart Claude Code to load nem."
