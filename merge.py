#!/usr/bin/env python3
"""
PI Merge — merges JAL_1 formula + BAL steps, flushes each step to detail.
Uses claude-agent-sdk for all LLM calls (no API key needed).
Usage: python3 merge.py --task "..." --jal1 "..." --bal "..."
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import ResultMessage

AGENTS_DIR = Path(__file__).parent / "agents"

os.environ.pop("CLAUDECODE", None)

# No MCP needed for merge/flush — pure reasoning
BASE_OPTIONS = ClaudeAgentOptions(
    allowed_tools=[],
    permission_mode="bypassPermissions",
)


def read_bal_section(section_name: str) -> str:
    """Extract a named section from bal.md."""
    bal_text = (AGENTS_DIR / "bal.md").read_text()
    pattern = rf"## {re.escape(section_name)}(.*?)(?=^## |\Z)"
    match = re.search(pattern, bal_text, re.DOTALL | re.MULTILINE)
    return match.group(1).strip() if match else ""


def extract_section(text: str, header: str) -> str:
    """Extract content under a **HEADER** block from agent output."""
    pattern = rf"\*\*{re.escape(header)}\*\*\s*\n(.*?)(?=\n\*\*[A-Z]|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def extract_thought_log(jal1_output: str) -> str:
    return extract_section(jal1_output, "THOUGHT LOG")


def extract_formula(jal1_output: str) -> str:
    formula = extract_section(jal1_output, "FORMULA")
    return formula if formula else jal1_output


def parse_steps(text: str) -> list[str]:
    """Parse a numbered list into individual step strings."""
    lines = text.strip().split("\n")
    steps, current = [], []
    for line in lines:
        if re.match(r"^\d+[.:]", line.strip()):
            if current:
                steps.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        steps.append("\n".join(current).strip())
    return steps if steps else [text]


async def run_query(prompt: str) -> str:
    """Run a single claude-agent-sdk query and return the result text."""
    result = ""
    async for msg in query(prompt=prompt, options=BASE_OPTIONS):
        if isinstance(msg, ResultMessage):
            result = msg.result or ""
    return result


async def merge_steps(jal1_output: str, bal_output: str, task: str) -> str:
    """Merge BAL's generic steps against JAL_1 formula."""
    mode2 = read_bal_section("Mode 2: Merge Against JAL_1 Formula")
    prompt = f"""You are BAL (Breakdown Agent Layer) in Mode 2: Merge Against JAL_1 Formula.

{mode2}

---

## Your original step list:
{bal_output}

## JAL_1 formula:
{jal1_output}

## Task:
{task}

Produce the revised merged ordered list only — no preamble."""
    result = await run_query(prompt)
    return result if result else bal_output


async def flush_step(step: str, formula: str, step_number: int) -> str:
    """Flush a single step to full personalized detail."""
    mode3 = read_bal_section("Mode 3: Flush a Single Action")
    prompt = f"""You are BAL (Breakdown Agent Layer) in Mode 3: Flush a Single Action.

{mode3}

---

## Action to flush (Step {step_number}):
{step}

## JAL_1 formula (for grounding):
{formula}

Produce the flushed step only — no preamble."""
    result = await run_query(prompt)
    return result if result else f"**Step {step_number}**\n{step}"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--jal1", required=True)
    parser.add_argument("--bal", required=True)
    parser.add_argument("--answers", default="", help="User's answers to JAL_1's prerequisite questions")
    args = parser.parse_args()

    task, jal1_output, bal_output = args.task, args.jal1, args.bal
    answers_block = (
        f"\n\n**USER ANSWERED THESE PREREQUISITE QUESTIONS BEFORE THIS PLAN:**\n{args.answers}\n"
        if args.answers else ""
    )

    print("PI merge: merging steps...", file=sys.stderr)
    merged = await merge_steps(jal1_output + answers_block, bal_output, task)
    steps = parse_steps(merged)
    formula = extract_formula(jal1_output)

    print(f"PI merge: flushing {len(steps)} steps in parallel...", file=sys.stderr)
    flushed = await asyncio.gather(
        *[flush_step(step, formula, i + 1) for i, step in enumerate(steps)],
        return_exceptions=True,
    )

    final_steps = [
        result if not isinstance(result, Exception) else f"**Step {i + 1}**\n{steps[i]}"
        for i, result in enumerate(flushed)
    ]

    thought_log = extract_thought_log(jal1_output)

    print("=== THOUGHT_LOG ===")
    print(thought_log if thought_log else "(No thought log from JAL_1)")
    print()
    print("=== PLAN ===")
    print("\n\n".join(final_steps))


if __name__ == "__main__":
    asyncio.run(main())
