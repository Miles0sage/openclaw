#!/usr/bin/env python3
"""
Bailian Agent — Multi-model autonomous agent for tmux-spawned sub-tasks.

Replaces Claude Code CLI for automated agents (TOS-compliant).
Uses Bailian Coding Plan ($1.10/mo flat) + MiniMax M2.5 (pay-per-use).

Model routing:
  - Planning/Research: Bailian kimi-k2.5 (free via plan)
  - Code generation:   Bailian qwen3-coder-next (free via plan)
  - Complex coding:    MiniMax M2.5 (80.2% SWE-Bench, $0.30/$1.20 per 1M)
  - Code review:       Bailian glm-5 (free via plan)

Called by tmux_spawner as: python3 bailian_agent.py <prompt_file> <output_file> <work_dir>

The agent:
1. Reads the prompt and classifies task complexity
2. Routes to optimal model (Bailian for simple, MiniMax for complex)
3. For complex tasks: plan with kimi → code with MiniMax → review with glm
4. Extracts code blocks and writes files directly
5. Outputs results to the output file
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, "/root/openclaw")
from dotenv import load_dotenv
load_dotenv("/root/openclaw/.env")

from bailian_executor import call_bailian

# Try MiniMax — optional but preferred for complex coding
try:
    from minimax_executor import call_minimax
    HAS_MINIMAX = bool(os.environ.get("MINIMAX_API_KEY", ""))
except ImportError:
    HAS_MINIMAX = False

# Complexity threshold (char count + signal words)
COMPLEX_THRESHOLD = 5


def extract_file_blocks(text: str) -> list[dict]:
    """Extract file paths and code from markdown code blocks."""
    files = []
    seen = set()

    # Pattern: **`filename`** or ### filename followed by ```code```
    pattern1 = r'(?:\*\*`([^`]+)`\*\*|###?\s+`?([^\n`]+?)`?\s*\n)\s*```[\w]*\n(.*?)```'
    for m in re.finditer(pattern1, text, re.DOTALL):
        filepath = (m.group(1) or m.group(2) or "").strip()
        content = m.group(3)
        if filepath and content and ('/' in filepath or '.' in filepath) and filepath not in seen:
            files.append({"path": filepath, "content": content})
            seen.add(filepath)

    # Pattern: File: path or Create: path followed by ```code```
    pattern2 = r'(?:File|Create|Write):\s*`?([^\n`]+?)`?\s*\n```[\w]*\n(.*?)```'
    for m in re.finditer(pattern2, text, re.DOTALL):
        filepath = m.group(1).strip()
        content = m.group(2)
        if filepath and content and ('/' in filepath or '.' in filepath) and filepath not in seen:
            files.append({"path": filepath, "content": content})
            seen.add(filepath)

    return files


def write_files(files: list[dict], work_dir: str) -> list[str]:
    """Write extracted files to disk. Returns list of written paths."""
    written = []
    for f in files:
        filepath = f["path"]
        if not os.path.isabs(filepath):
            filepath = os.path.join(work_dir, filepath)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as fh:
            fh.write(f["content"])
        written.append(filepath)
        print(f"  [WROTE] {filepath} ({len(f['content'])} bytes)")
    return written


def classify_task(prompt: str) -> tuple[str, bool]:
    """Classify task type and complexity. Returns (type, is_complex)."""
    lower = prompt.lower()

    planning_signals = ["plan", "research", "strategy", "roadmap", "architecture", "design", "analyze", "recommend"]
    review_signals = ["review", "audit", "check", "verify", "test", "validate"]
    complex_signals = ["refactor", "multi-file", "full project", "complete", "entire", "build a",
                       "implement", "migrate", "redesign", "overhaul", "end-to-end", "production"]

    plan_score = sum(1 for s in planning_signals if s in lower)
    review_score = sum(1 for s in review_signals if s in lower)
    complex_score = sum(1 for s in complex_signals if s in lower)

    # Long prompts are inherently more complex
    if len(prompt) > 500:
        complex_score += 2
    if len(prompt) > 1500:
        complex_score += 2

    is_complex = complex_score >= COMPLEX_THRESHOLD

    if review_score > plan_score:
        return "review", is_complex
    elif plan_score > 1:
        return "planning", is_complex
    return "coding", is_complex


async def call_model(prompt: str, system_prompt: str, model: str,
                     max_tokens: int = 8192, temperature: float = 0.2,
                     use_minimax: bool = False) -> dict:
    """Call either Bailian or MiniMax based on routing."""
    if use_minimax and HAS_MINIMAX:
        print(f"  [MODEL] MiniMax M2.5 (complex coding)")
        result = await call_minimax(
            prompt=prompt,
            system_prompt=system_prompt,
            model="MiniMax-M2.5",
            max_tokens=max_tokens,
            temperature=temperature,
        )
        result["source"] = "minimax"
        return result
    else:
        print(f"  [MODEL] Bailian {model}")
        return await call_bailian(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )


SYSTEM_PROMPTS = {
    "planning": (
        "You are an expert software architect. Provide detailed, actionable plans "
        "with specific file paths, technology choices with rationale, and steps. "
        "When creating files, format as: **`path/to/file.ext`** followed by a code block."
    ),
    "coding": (
        "You are an expert software developer. Write production-quality code. "
        "For each file, format as:\n**`path/to/file.ext`**\n```language\ncode\n```\n"
        "Create complete, working files. Include imports, error handling. No snippets."
    ),
    "review": (
        "You are an expert code reviewer. For each issue: severity, description, concrete fix. "
        "Format suggested changes as complete files with paths."
    ),
}


async def run_simple(prompt: str, task_type: str, output_file: str, work_dir: str) -> dict:
    """Simple path: single Bailian call."""
    model_map = {"planning": "kimi-k2.5", "coding": "qwen3-coder-next", "review": "glm-5"}
    model = model_map.get(task_type, "qwen3-coder-next")

    print(f"[SIMPLE] {task_type} → Bailian {model}")

    result = await call_model(prompt, SYSTEM_PROMPTS[task_type], model)

    text = result.get("text", "")
    tokens = result.get("tokens", 0)
    cost = result.get("cost_usd", 0)

    with open(output_file, "a") as f:
        f.write(text)
        f.write(f"\n\n[STATS] model={model} tokens={tokens} cost=${cost:.4f}\n")

    files = extract_file_blocks(text)
    if files:
        print(f"[SIMPLE] Extracted {len(files)} files")
        write_files(files, work_dir)

    print(f"[SIMPLE] Done. {tokens} tokens, ${cost:.4f}")
    return result


async def run_complex(prompt: str, task_type: str, output_file: str, work_dir: str) -> dict:
    """Complex path: plan → code → review (multi-model pipeline)."""
    total_cost = 0.0
    total_tokens = 0

    # Phase 1: Plan with kimi-k2.5 (free via Bailian plan)
    print(f"[COMPLEX] Phase 1: Planning with kimi-k2.5...")
    plan_result = await call_model(
        prompt=(
            f"Analyze this task and create a detailed implementation plan. "
            f"List every file that needs to be created/modified, with specific contents described.\n\n"
            f"TASK:\n{prompt}"
        ),
        system_prompt=SYSTEM_PROMPTS["planning"],
        model="kimi-k2.5",
        max_tokens=4096,
        temperature=0.3,
    )
    plan_text = plan_result.get("text", "")
    total_cost += plan_result.get("cost_usd", 0)
    total_tokens += plan_result.get("tokens", 0)
    print(f"  Plan: {plan_result.get('tokens', 0)} tokens")

    with open(output_file, "a") as f:
        f.write(f"## Phase 1: Plan\n{plan_text}\n\n")

    # Phase 2: Code with MiniMax M2.5 (or qwen3-coder-next fallback)
    use_mm = task_type == "coding" and HAS_MINIMAX
    code_model = "MiniMax-M2.5" if use_mm else "qwen3-coder-next"
    print(f"[COMPLEX] Phase 2: Coding with {code_model}...")

    code_result = await call_model(
        prompt=(
            f"Implement the following plan. Create all files with complete, working code.\n\n"
            f"PLAN:\n{plan_text[:6000]}\n\n"
            f"ORIGINAL TASK:\n{prompt[:2000]}\n\n"
            f"Format every file as: **`path/to/file.ext`** followed by a complete code block."
        ),
        system_prompt=SYSTEM_PROMPTS["coding"],
        model=code_model,
        max_tokens=8192,
        temperature=0.1,
        use_minimax=use_mm,
    )
    code_text = code_result.get("text", "")
    total_cost += code_result.get("cost_usd", 0)
    total_tokens += code_result.get("tokens", 0)
    print(f"  Code: {code_result.get('tokens', 0)} tokens")

    with open(output_file, "a") as f:
        f.write(f"## Phase 2: Code\n{code_text}\n\n")

    # Write files from code phase
    files = extract_file_blocks(code_text)
    written = []
    if files:
        print(f"[COMPLEX] Extracted {len(files)} files from code phase")
        written = write_files(files, work_dir)

    # Phase 3: Review with glm-5 (free via Bailian plan)
    if written:
        print(f"[COMPLEX] Phase 3: Review with glm-5...")
        file_list = "\n".join(f"- {p}" for p in written)
        review_result = await call_model(
            prompt=(
                f"Review these files for bugs, security issues, and improvements:\n{file_list}\n\n"
                f"Original task: {prompt[:500]}"
            ),
            system_prompt=SYSTEM_PROMPTS["review"],
            model="glm-5",
            max_tokens=2048,
            temperature=0.1,
        )
        review_text = review_result.get("text", "")
        total_cost += review_result.get("cost_usd", 0)
        total_tokens += review_result.get("tokens", 0)
        print(f"  Review: {review_result.get('tokens', 0)} tokens")

        with open(output_file, "a") as f:
            f.write(f"## Phase 3: Review\n{review_text}\n\n")

    with open(output_file, "a") as f:
        f.write(f"\n[TOTAL_STATS] tokens={total_tokens} cost=${total_cost:.4f} files={len(written)}\n")

    print(f"[COMPLEX] Done. {total_tokens} tokens, ${total_cost:.4f}, {len(written)} files written")
    return {"text": code_text, "tokens": total_tokens, "cost_usd": total_cost, "source": "multi-model"}


async def run_agent(prompt_file: str, output_file: str, work_dir: str):
    """Main agent entry point."""
    with open(prompt_file, "r") as f:
        prompt = f.read()

    task_type, is_complex = classify_task(prompt)
    print(f"[AGENT] Task: {task_type}, Complex: {is_complex}, MiniMax: {HAS_MINIMAX}")

    if is_complex:
        result = await run_complex(prompt, task_type, output_file, work_dir)
    else:
        result = await run_simple(prompt, task_type, output_file, work_dir)

    return result


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <prompt_file> <output_file> <work_dir>")
        sys.exit(1)

    prompt_file = sys.argv[1]
    output_file = sys.argv[2]
    work_dir = sys.argv[3]

    asyncio.run(run_agent(prompt_file, output_file, work_dir))


if __name__ == "__main__":
    main()
