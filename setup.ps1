$NEM_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$CLAUDE_JSON = "$env:USERPROFILE\.claude.json"

Write-Host "Installing dependencies..."
python3 -m pip install -r "$NEM_DIR\requirements.txt" -q

Write-Host "Registering nem MCP server in $CLAUDE_JSON..."
python3 - @"
import json, sys
from pathlib import Path

path = Path(r"$CLAUDE_JSON")
config = json.loads(path.read_text()) if path.exists() else {}

servers = config.setdefault("mcpServers", {})
if "nem" in servers:
    print("nem already registered -- skipping.")
else:
    servers["nem"] = {
        "type": "stdio",
        "command": "python3",
        "args": [r"$NEM_DIR\mcp_server.py"]
    }
    path.write_text(json.dumps(config, indent=2))
    print("nem registered.")
"@

Write-Host "Done. Restart Claude Code to load nem."
