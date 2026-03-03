"""
Oz Executor — Warp Oz Agent execution backend for OpenClaw jobs.
=================================================================
Wraps the Oz CLI (`oz agent run`) to execute agent tasks using Warp's
multi-model orchestration (GPT-5.2, Claude 4.6, Gemini 3 Pro, etc.).

Oz auto-selects the best model per task and provides full tool access
(file read/write, shell commands, git operations) out of the box.

Execution chain: Oz (auto-model) → OpenCode (Gemini Flash) → SDK (Haiku/Sonnet)

Usage:
    from oz_executor import run_oz, execute_with_oz_fallback

    result = await run_oz(prompt="Fix the auth bug", workspace="/root/openclaw")
    result = await execute_with_oz_fallback(prompt, workspace, job_id, phase)
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional

from cost_tracker import log_cost_event

logger = logging.getLogger("oz_executor")

OZ_BIN = os.environ.get("OZ_BIN", "/usr/bin/oz")

# Default timeout (seconds) — Oz can take longer than OpenCode due to multi-step reasoning
DEFAULT_TIMEOUT = 180

# Idle timeout (seconds) — if Oz produces no output for this long, consider task complete.
# Oz streams JSONL but never closes stdout, so we detect completion by silence.
IDLE_TIMEOUT = 15

# Model selection per priority/complexity
OZ_MODELS = {
    "P0": "auto-genius",       # Best available for critical tasks
    "P1": "auto",              # Smart auto-selection
    "P2": "auto-efficient",    # Cost-optimized
    "P3": "auto-efficient",    # Cost-optimized
    "default": "auto-efficient",
}

# Cost estimation per model tier (approximate $/1M tokens)
OZ_COST_TIERS = {
    "auto-genius": {"input": 5.00, "output": 25.00},
    "auto": {"input": 2.00, "output": 10.00},
    "auto-efficient": {"input": 0.50, "output": 2.00},
}


async def run_oz(
    prompt: str,
    workspace: str = "/root/openclaw",
    timeout: int = DEFAULT_TIMEOUT,
    job_id: str = "",
    phase: str = "",
    model: str = "auto-efficient",
    name: str = "",
) -> dict:
    """
    Execute a prompt via the Oz CLI agent.

    Runs `oz agent run --prompt "..." --model <model> --output-format json --cwd <workspace>`
    Parses streaming JSON output for structured results.

    Returns: {
        "text": str,         # Agent's final response text
        "tokens": int,       # Estimated token count
        "tool_calls": list,  # Tool calls made
        "cost_usd": float,   # Estimated cost
        "source": "oz",      # Execution source identifier
        "model": str,        # Model used
        "conversation_id": str,
    }

    Raises:
        OzError: On execution failure, timeout, or parse error.
    """
    if not os.path.isfile(OZ_BIN):
        raise OzError(f"Oz binary not found at {OZ_BIN}")

    task_name = name or f"openclaw-{job_id}-{phase}" if job_id else "openclaw-task"

    cmd = [
        OZ_BIN, "agent", "run",
        "--prompt", prompt,
        "--output-format", "json",
        "--model", model,
        "--cwd", workspace,
        "--name", task_name,
    ]

    logger.info(
        f"Oz call: job={job_id} phase={phase} model={model} "
        f"workspace={workspace} timeout={timeout}s"
    )

    start_time = time.time()

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workspace,
            env={
                **os.environ,
                "NO_COLOR": "1",
            },
        )

        # Oz CLI never exits/closes stdout after completing a task.
        # Instead of process.communicate() (which waits for EOF forever),
        # we stream stdout line-by-line and detect completion by silence:
        # if no new output arrives within IDLE_TIMEOUT seconds, task is done.
        collected_lines: list[str] = []
        deadline = start_time + timeout

        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break

            wait_time = min(IDLE_TIMEOUT, remaining)
            try:
                raw_line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=wait_time,
                )
            except asyncio.TimeoutError:
                # No output for IDLE_TIMEOUT seconds — Oz is done (or stalled).
                # Check if we already have meaningful output before declaring success.
                if collected_lines:
                    logger.info(
                        f"Oz idle for {IDLE_TIMEOUT}s with {len(collected_lines)} lines collected — "
                        f"treating as complete for job={job_id} phase={phase}"
                    )
                    break
                # No output at all yet and we hit idle timeout — keep waiting
                # up to the hard deadline
                if time.time() - start_time < timeout * 0.5:
                    continue
                break

            if not raw_line:
                # EOF — process actually exited (rare for Oz but handle it)
                break

            line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
            if line:
                collected_lines.append(line)

        elapsed = time.time() - start_time

        # Kill the Oz process (it won't exit on its own)
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass

    except Exception as e:
        # Clean up process on any unexpected error
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise OzError(f"Oz subprocess failed: {e}") from e

    if not collected_lines:
        raise OzError(
            f"Oz produced no output for job={job_id} phase={phase} "
            f"(elapsed={elapsed:.1f}s)"
        )

    stdout_text = "\n".join(collected_lines)

    result = _parse_oz_output(stdout_text)
    result["source"] = "oz"
    result["model"] = model

    # Estimate cost
    cost_tier = OZ_COST_TIERS.get(model, OZ_COST_TIERS["auto-efficient"])
    est_input_tokens = len(prompt) // 4
    est_output_tokens = len(result["text"]) // 4
    result["tokens"] = est_input_tokens + est_output_tokens
    result["cost_usd"] = round(
        (est_input_tokens * cost_tier["input"]
         + est_output_tokens * cost_tier["output"]) / 1_000_000,
        6,
    )

    log_cost_event(
        project="openclaw",
        agent="oz",
        model=f"oz-{model}",
        tokens_input=est_input_tokens,
        tokens_output=est_output_tokens,
        cost=result["cost_usd"],
        event_type="oz_call",
        metadata={
            "phase": phase,
            "elapsed_s": round(elapsed, 2),
            "lines_collected": len(collected_lines),
            "conversation_id": result.get("conversation_id", ""),
        },
        job_id=job_id,
    )

    logger.info(
        f"Oz complete: job={job_id} phase={phase} model={model} "
        f"elapsed={elapsed:.1f}s cost=${result['cost_usd']:.6f} "
        f"tokens={result['tokens']} tools={len(result['tool_calls'])} "
        f"lines={len(collected_lines)}"
    )

    return result


def _parse_oz_output(stdout: str) -> dict:
    """
    Parse Oz CLI streaming JSON output.

    Oz outputs one JSON object per line (JSONL):
    {"type":"system","event_type":"conversation_started","conversation_id":"..."}
    {"type":"agent_reasoning","text":"..."}
    {"type":"agent","text":"..."}
    {"type":"tool_call","tool":"run_command","command":"..."}
    {"type":"tool_result","tool":"run_command","status":"complete","exit_code":0,"output":"..."}
    {"type":"artifact_created","artifact_type":"pull_request","url":"..."}
    """
    text_parts = []
    tool_calls = []
    conversation_id = ""
    artifacts = []

    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        obj_type = obj.get("type", "")

        if obj_type == "system" and obj.get("event_type") == "conversation_started":
            conversation_id = obj.get("conversation_id", "")

        elif obj_type == "agent":
            text_parts.append(obj.get("text", ""))

        elif obj_type == "agent_reasoning":
            pass  # Skip reasoning for output, but could log

        elif obj_type == "tool_call":
            tool_calls.append({
                "tool": obj.get("tool", "unknown"),
                "input": {
                    k: v for k, v in obj.items()
                    if k not in ("type", "tool")
                },
                "result": "(pending)",
            })

        elif obj_type == "tool_result":
            # Match to last tool_call of same tool name
            tool_name = obj.get("tool", "")
            for tc in reversed(tool_calls):
                if tc["tool"] == tool_name and tc["result"] == "(pending)":
                    tc["result"] = obj.get("output", obj.get("status", "done"))
                    # Capture file diffs from edit_files
                    if obj.get("diff"):
                        tc["result"] = obj["diff"]
                    break

        elif obj_type == "artifact_created":
            artifacts.append({
                "type": obj.get("artifact_type", "unknown"),
                "url": obj.get("url", ""),
            })

    text = "".join(text_parts).strip()

    if artifacts:
        text += "\n\nArtifacts created:\n"
        for a in artifacts:
            text += f"- {a['type']}: {a['url']}\n"

    if not text:
        # Fall back to collecting all tool results
        text = "\n".join(
            str(tc.get("result", ""))
            for tc in tool_calls
            if tc.get("result") and tc["result"] != "(pending)"
        )[:5000] or "(no output)"

    return {
        "text": text[:10000],
        "tokens": 0,
        "tool_calls": tool_calls,
        "cost_usd": 0.0,
        "conversation_id": conversation_id,
    }


async def execute_with_oz_fallback(
    prompt: str,
    workspace: str = "/root/openclaw",
    timeout: int = DEFAULT_TIMEOUT,
    job_id: str = "",
    phase: str = "",
    priority: str = "P2",
    guardrails=None,
    system_prompt: str = "",
) -> dict:
    """
    Execute via Oz first, fall back to OpenCode, then SDK.

    This is the primary entry point when USE_OZ=1. Tries:
    1. Oz agent (auto-model selection)
    2. OpenCode (Gemini Flash) on Oz failure
    3. SDK (Haiku/Sonnet) on OpenCode failure
    """
    model = OZ_MODELS.get(priority, OZ_MODELS["default"])

    # Try Oz first
    try:
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

        result = await run_oz(
            prompt=full_prompt,
            workspace=workspace,
            timeout=timeout,
            job_id=job_id,
            phase=phase,
            model=model,
        )

        if result["text"] and len(result["text"].strip()) > 20:
            logger.info(f"Oz succeeded for {job_id}/{phase}")
            return result

        logger.warning(
            f"Oz returned empty/short result for {job_id}/{phase}, "
            f"falling back to OpenCode"
        )

    except OzError as e:
        logger.warning(
            f"Oz failed for {job_id}/{phase}: {e} — falling back to OpenCode"
        )

    except Exception as e:
        logger.error(
            f"Unexpected Oz error for {job_id}/{phase}: {e} — falling back to OpenCode"
        )

    # Fall back to OpenCode
    try:
        from opencode_executor import execute_with_fallback
        logger.info(f"Falling back to OpenCode for {job_id}/{phase}")
        return await execute_with_fallback(
            prompt=prompt,
            workspace=workspace,
            timeout=timeout,
            job_id=job_id,
            phase=phase,
            priority=priority,
            guardrails=guardrails,
            system_prompt=system_prompt,
        )
    except Exception as e:
        logger.error(f"OpenCode fallback also failed for {job_id}/{phase}: {e}")

    # Final fallback to SDK
    from autonomous_runner import _call_agent_sdk
    logger.info(f"Final fallback to SDK for {job_id}/{phase}")
    return await _call_agent_sdk(
        prompt=prompt,
        system_prompt=system_prompt,
        job_id=job_id,
        phase=phase,
        priority=priority,
        guardrails=guardrails,
        workspace=workspace,
    )


class OzError(Exception):
    """Raised when Oz CLI execution fails."""
    pass
