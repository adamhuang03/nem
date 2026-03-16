#!/usr/bin/env python3
import json
import os
import subprocess
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP

os.environ.pop("CLAUDECODE", None)

SKILLS_DIR = Path(__file__).parent
mcp = FastMCP("nem")
sessions = {}  # reserved for future stateful use


@mcp.tool()
def nem_start(task: str) -> dict:
    """Run the nem pipeline for a given task. Returns the full plan.

    If status is 'complete': show the thought_log, then immediately execute the plan
    step by step using available MCP tools. Do not show the plan or ask for approval
    first. Show progress inline as each step completes. Before any live action (sending
    a message, publishing a doc, updating a record) pause and confirm with the user first.
    If status is 'questions': show the questions to the user, then show the note verbatim
    on its own line before asking them to respond.
    If status is 'error': surface the message.
    """
    session_id = str(uuid.uuid4())
    cwd = os.environ.get("PI_PROJECT_CWD", os.getcwd())

    result = subprocess.run(
        ["python3", str(SKILLS_DIR / "orchestrate.py"), task],
        capture_output=True,
        text=True,
        env={**os.environ, "PI_PROJECT_CWD": cwd, "NEM_SESSION_ID": session_id},
        timeout=600,
    )

    if result.returncode != 0:
        return {"status": "error", "message": result.stderr}

    output = result.stdout

    # Surface questions if JAL_1 detected prerequisites
    if output.startswith("=== QUESTIONS ==="):
        questions = [l.lstrip("0123456789. ") for l in output.split("\n")[1:] if l.strip()]
        return {
            "status": "questions",
            "session_id": session_id,
            "questions": questions,
            "note": "nem will trust whatever answers you give and continue. Try to be as honest as you can. In the future, nem will ask more questions if your answers don't match how you really think about your workflows.",
        }

    # Parse thought log and plan from output
    thought_log, plan = "", output
    if "=== THOUGHT_LOG ===" in output and "=== PLAN ===" in output:
        parts = output.split("=== PLAN ===", 1)
        thought_log = parts[0].replace("=== THOUGHT_LOG ===", "").strip()
        plan = parts[1].strip()

    sessions[session_id] = {"task": task, "plan": plan}

    return {
        "status": "complete",
        "session_id": session_id,
        "thought_log": thought_log,
        "plan": plan,
    }


@mcp.tool()
def nem_answer(session_id: str, answers: str) -> dict:
    """Provide answers to nem's prerequisite questions. Runs merge and returns the full plan.

    When complete: show the thought_log, then immediately execute the plan step by step
    using available MCP tools. Do not show the plan or ask for approval first. Show
    progress inline as each step completes. Before any live action (sending a message,
    publishing a doc, updating a record) pause and confirm with the user first.
    """
    session_file = SKILLS_DIR / "sessions" / f"{session_id}.json"
    if not session_file.exists():
        return {"status": "error", "message": f"Session {session_id} not found."}

    session = json.loads(session_file.read_text())

    merge_result = subprocess.run(
        [
            "python3", str(SKILLS_DIR / "merge.py"),
            "--task", session["task"],
            "--jal1", session["jal1_output"],
            "--bal", session["bal_output"],
            "--answers", answers,
        ],
        capture_output=True,
        text=True,
    )

    if merge_result.returncode != 0:
        return {"status": "error", "message": merge_result.stderr}

    output = merge_result.stdout
    thought_log, plan = "", output
    if "=== THOUGHT_LOG ===" in output and "=== PLAN ===" in output:
        parts = output.split("=== PLAN ===", 1)
        thought_log = parts[0].replace("=== THOUGHT_LOG ===", "").strip()
        plan = parts[1].strip()

    return {"status": "complete", "session_id": session_id, "thought_log": thought_log, "plan": plan}


@mcp.tool()
def nem_review(session_id: str, step_number: int, executed_result: str) -> dict:
    """[PLACEHOLDER] Review an executed step against the plan. Not yet implemented."""
    return {"status": "not_implemented", "message": "Step review coming soon."}


if __name__ == "__main__":
    mcp.run()
