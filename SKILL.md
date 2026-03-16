# PI Skill

## Trigger
This skill activates when the user types `/pi [task]`. Extract everything after `/pi` as the task.

## Purpose
PI is a personalized context layer. It pulls how the user actually works from their connected tools, builds a personalized execution plan, then executes immediately — so outputs land in one shot without back-and-forth.

---

## Execution Instructions

### Step 1 — Extract Task
Extract the task from the user's input. Everything after `/pi` is the task. If nothing follows `/pi`, ask: "What's the task?"

---

### Steps 2–4 — Orchestrate (Code Layer)

Run via Bash with a 10-minute timeout (required — JAL_1 queries multiple MCP tools in parallel):

```bash
PI_PROJECT_CWD=$(pwd) python3 ~/.claude/skills/pi/orchestrate.py "[task]"
```

**Important:** Use `timeout=600000` on this Bash call.

This script:
1. Reads MCP server configs from `~/.claude.json` for the active project
2. Spawns JAL_1 (with MCP access) and BAL in parallel via `claude-agent-sdk`
3. Merges BAL's generic steps against JAL_1's formula and flushes each step via `anthropic` SDK

Capture stdout. Parse two sections:
- Everything between `=== THOUGHT_LOG ===` and `=== PLAN ===` → thought log
- Everything after `=== PLAN ===` → plan body

If the script exits non-zero, or output contains `Missing connector:` or `No examples found`, stop and surface the message to the user verbatim. Do not proceed to Step 5.

---

### Step 5 — Render Thought Log, Then Execute

Show JAL_1's thought log:
```
Pulling your [tools used].
[Anything skipped and why]
[Key judgment call based on user's pattern]
[Any gaps flagged]
```

Then immediately proceed to Step 6. Do not show the plan or ask for approval.

---

### Step 6 — Execute

Execute the plan step by step using connected MCP tools. Rules:
- Complete each step before moving to the next
- Show progress inline as each step completes
- **Do not push anything live** (send message, publish doc, update record) without a final confirmation
- Last line of execution output is always: "Done — want me to send/save/publish this?"

---

## Error Handling

- **Tool missing**: If JAL_1 flags a missing required connector, stop and tell the user which tool needs to be connected before PI can run this task.
- **Thin context**: If JAL_1 flags only 1-2 examples, proceed but note it in the thought log.
- **No examples found**: Pause and ask the user to provide context before continuing.
