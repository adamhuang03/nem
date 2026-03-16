#!/usr/bin/env python3
"""
PI Orchestrator — spawns JAL_1 and BAL in parallel via claude-agent-sdk.
Usage: PI_PROJECT_CWD=/path/to/project python3 orchestrate.py "task description"
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import McpHttpServerConfig, ResultMessage

SKILLS_DIR = Path(__file__).parent
AGENTS_DIR = SKILLS_DIR / "agents"

# Allow claude-agent-sdk to spawn sessions from within an active Claude Code session
os.environ.pop("CLAUDECODE", None)


def read_mcp_servers(cwd: str) -> dict:
    """Read MCP server configs from ~/.claude.json for the given project path."""
    config_path = Path.home() / ".claude.json"
    try:
        config = json.loads(config_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    projects = config.get("projects", {})
    # Exact match first, then longest prefix
    if cwd in projects:
        return projects[cwd].get("mcpServers", {})
    for path in sorted(projects.keys(), key=len, reverse=True):
        if cwd.startswith(path):
            return projects[path].get("mcpServers", {})
    return {}


def build_mcp_config(servers: dict) -> dict[str, McpHttpServerConfig]:
    """Build SDK-compatible MCP server config from ~/.claude.json mcpServers dict."""
    result = {}
    for name, cfg in servers.items():
        if cfg.get("type") == "http":
            result[name] = McpHttpServerConfig(
                type="http",
                url=cfg["url"],
            )
    return result


def parse_questions(jal1_output: str) -> list[str]:
    """Extract questions from JAL_1's QUESTIONS section, if any."""
    import re
    if "**QUESTIONS**" not in jal1_output:
        return []
    section = jal1_output.split("**QUESTIONS**", 1)[1]
    # Stop at next section header (**WORD** at start of a line), not inline bold
    next_header = re.search(r"\n\*\*[A-Z]", section)
    if next_header:
        section = section[: next_header.start()]
    lines = [l.strip() for l in section.strip().splitlines() if l.strip()]
    return [l.lstrip("0123456789. ") for l in lines if l]


def write_session(session_id: str, task: str, jal1_output: str, bal_output: str, questions: list[str]) -> None:
    """Write session state to disk for use by nem_answer."""
    sessions_dir = SKILLS_DIR / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    data = {"task": task, "jal1_output": jal1_output, "bal_output": bal_output, "questions": questions}
    (sessions_dir / f"{session_id}.json").write_text(json.dumps(data, indent=2))


def save_run_log(task: str, jal1_output: str, bal_output: str, merge_stdout: str) -> None:
    """Save a structured MD log of this PI run to ~/.claude/skills/pi/runs/."""
    runs_dir = SKILLS_DIR / "runs"
    runs_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    # Parse merge output sections
    thought_log, plan = "", merge_stdout
    if "=== THOUGHT_LOG ===" in merge_stdout and "=== PLAN ===" in merge_stdout:
        parts = merge_stdout.split("=== PLAN ===", 1)
        thought_log = parts[0].replace("=== THOUGHT_LOG ===", "").strip()
        plan = parts[1].strip()

    content = f"""# PI Run — {timestamp}
**Task:** {task}

---
## JAL_1 Output
{jal1_output}

---
## BAL Output
{bal_output}

---
## Thought Log
{thought_log or "(none)"}

---
## Final Plan
{plan}
"""
    (runs_dir / f"{timestamp}.md").write_text(content)
    print(f"PI: Run saved to runs/{timestamp}.md", file=sys.stderr)


async def run_agent(prompt_file: str, task: str, options: ClaudeAgentOptions) -> str:
    """Run a single agent query and return the result text."""
    prompt = (AGENTS_DIR / prompt_file).read_text()
    full_prompt = f"{prompt}\n\n---\n\nTask: {task}"
    result = ""
    async for msg in query(prompt=full_prompt, options=options):
        if isinstance(msg, ResultMessage):
            result = msg.result or ""
    return result


async def main():
    if len(sys.argv) < 2:
        print("Usage: orchestrate.py <task>", file=sys.stderr)
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    cwd = os.environ.get("PI_PROJECT_CWD", os.getcwd())
    session_id = os.environ.get("NEM_SESSION_ID", str(uuid.uuid4()))

    # Build MCP config from project settings
    mcp_servers_raw = read_mcp_servers(cwd)
    mcp_config = build_mcp_config(mcp_servers_raw)
    mcp_tool_names = [f"mcp__{name}__*" for name in mcp_servers_raw]

    # JAL_1: needs MCP tools to pull user context
    jal1_options = ClaudeAgentOptions(
        allowed_tools=mcp_tool_names,
        mcp_servers=mcp_config,
        cwd=cwd,
        permission_mode="bypassPermissions",
    )

    # BAL: no MCP needed — generic task breakdown only
    bal_options = ClaudeAgentOptions(
        allowed_tools=[],
        permission_mode="bypassPermissions",
    )

    print("PI: Running JAL_1 and BAL in parallel...", file=sys.stderr)

    jal1_output, bal_output = await asyncio.gather(
        run_agent("jal_1.md", task, jal1_options),
        run_agent("bal_mode1.md", task, bal_options),
        return_exceptions=True,
    )

    # Handle failures
    if isinstance(jal1_output, Exception):
        print(f"JAL_1 failed: {jal1_output}", file=sys.stderr)
        sys.exit(1)
    if isinstance(bal_output, Exception):
        print(f"BAL failed: {bal_output}", file=sys.stderr)
        sys.exit(1)

    # Surface hard stops from JAL_1 (missing connector / no examples)
    if "Missing connector:" in jal1_output or "No examples found" in jal1_output:
        print(jal1_output)
        sys.exit(0)

    # Check for prerequisite questions from JAL_1
    questions = parse_questions(jal1_output)
    write_session(session_id, task, jal1_output, bal_output, questions)

    if questions:
        print("=== QUESTIONS ===")
        for i, q in enumerate(questions, 1):
            print(f"{i}. {q}")
        sys.exit(0)

    print("PI: Merging and flushing...", file=sys.stderr)

    # Delegate merge + flush to merge.py (uses anthropic SDK directly)
    merge_result = subprocess.run(
        ["python3", str(SKILLS_DIR / "merge.py"), "--task", task, "--jal1", jal1_output, "--bal", bal_output],
        capture_output=True,
        text=True,
    )

    if merge_result.returncode != 0:
        print(f"Merge failed: {merge_result.stderr}", file=sys.stderr)
        sys.exit(1)

    save_run_log(task, jal1_output, bal_output, merge_result.stdout)
    print(merge_result.stdout)


if __name__ == "__main__":
    asyncio.run(main())
