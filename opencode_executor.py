"""
OpenCode Executor — Cheap execution backend for OpenClaw jobs.
================================================================
Wraps the OpenCode CLI (Go-based coding assistant) to execute agent tasks
at ~$0.05-0.08/job instead of $0.50-0.70 via Claude SDK. Falls back to
_call_agent_sdk() on error or timeout.

OpenCode CLI: /root/go/bin/opencode
Docs: opencode -p "prompt" -f json -q -c /workspace

Cost savings: ~90% reduction per job execution.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from cost_tracker import log_cost_event

logger = logging.getLogger("opencode_executor")

# OpenCode CLI binary path
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", "/root/go/bin/opencode")

# Default timeout for OpenCode execution (seconds)
DEFAULT_TIMEOUT = 120

# Cost per 1M tokens for OpenCode (Gemini 2.5 Flash via opencode.json)
OPENCODE_COST_PRICING = {
    "input": 0.15,
    "output": 0.60,
}


async def run_opencode(
    prompt: str,
    workspace: str = "/root/openclaw",
    timeout: int = DEFAULT_TIMEOUT,
    job_id: str = "",
    phase: str = "",
) -> dict:
    """
    Execute a prompt via the OpenCode CLI.

    Runs `opencode -p "prompt" -f json -q -c <workspace>` as a subprocess.
    Parses JSON output for structured results.

    Returns: {
        "text": str,          # Agent's response text
        "tokens": int,        # Estimated token count
        "tool_calls": list,   # Tool calls made (from JSON output)
        "cost_usd": float,    # Estimated cost
        "source": "opencode", # Execution source identifier
    }

    Raises:
        OpenCodeError: On execution failure, timeout, or parse error.
    """
    if not os.path.isfile(OPENCODE_BIN):
        raise OpenCodeError(f"OpenCode binary not found at {OPENCODE_BIN}")

    # Build command
    cmd = [
        OPENCODE_BIN,
        "-p", prompt,
        "-f", "json",
        "-q",  # quiet mode — no interactive UI
        "-c", workspace,
    ]

    logger.info(
        f"OpenCode call: job={job_id} phase={phase} "
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
                "NO_COLOR": "1",  # Disable ANSI colors in output
            },
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )

        elapsed = time.time() - start_time

    except asyncio.TimeoutError:
        # Kill the process on timeout
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise OpenCodeError(
            f"OpenCode timed out after {timeout}s for job={job_id} phase={phase}"
        )

    except Exception as e:
        raise OpenCodeError(f"OpenCode subprocess failed: {e}") from e

    # Check exit code
    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")[:2000]
        raise OpenCodeError(
            f"OpenCode exited with code {process.returncode}: {stderr_text}"
        )

    # Parse output
    stdout_text = stdout.decode("utf-8", errors="replace")

    result = _parse_opencode_output(stdout_text)
    result["source"] = "opencode"

    # Estimate cost based on output length (rough token estimation)
    # ~4 chars per token is a reasonable approximation
    est_input_tokens = len(prompt) // 4
    est_output_tokens = len(result["text"]) // 4
    result["tokens"] = est_input_tokens + est_output_tokens
    result["cost_usd"] = round(
        (est_input_tokens * OPENCODE_COST_PRICING["input"]
         + est_output_tokens * OPENCODE_COST_PRICING["output"]) / 1_000_000,
        6,
    )

    # Log cost
    log_cost_event(
        project="openclaw",
        agent="opencode",
        model="opencode",
        tokens_input=est_input_tokens,
        tokens_output=est_output_tokens,
        cost=result["cost_usd"],
        event_type="opencode_call",
        metadata={
            "phase": phase,
            "elapsed_s": round(elapsed, 2),
            "exit_code": process.returncode,
        },
        job_id=job_id,
    )

    logger.info(
        f"OpenCode complete: job={job_id} phase={phase} "
        f"elapsed={elapsed:.1f}s cost=${result['cost_usd']:.6f} "
        f"tokens={result['tokens']}"
    )

    return result


def _parse_opencode_output(stdout: str) -> dict:
    """
    Parse OpenCode CLI JSON output into our standard result format.

    OpenCode with -f json returns structured JSON. Falls back to
    treating raw text as the response if JSON parsing fails.
    """
    text = ""
    tool_calls = []

    # Try to parse as JSON first
    try:
        data = json.loads(stdout.strip())

        # OpenCode JSON format varies — handle known structures
        if isinstance(data, dict):
            text = data.get("response", data.get("content", data.get("text", "")))
            if isinstance(text, list):
                # Content blocks
                text = "\n".join(
                    block.get("text", "") for block in text
                    if isinstance(block, dict) and block.get("type") == "text"
                ) or str(text)

            # Extract tool calls if present
            raw_tools = data.get("tool_calls", data.get("tools", []))
            if isinstance(raw_tools, list):
                for tc in raw_tools:
                    if isinstance(tc, dict):
                        tool_calls.append({
                            "tool": tc.get("name", tc.get("tool", "unknown")),
                            "input": tc.get("input", tc.get("args", {})),
                            "result": tc.get("result", "(opencode-managed)"),
                        })

        elif isinstance(data, list):
            # Array of content blocks
            text = "\n".join(
                item.get("text", str(item)) for item in data
                if isinstance(item, dict)
            ) or stdout

    except (json.JSONDecodeError, ValueError):
        # Not JSON — use raw text
        text = stdout.strip()

    if not text:
        text = stdout.strip() or "(no output)"

    return {
        "text": text[:10000],  # Cap output size
        "tokens": 0,  # Calculated by caller
        "tool_calls": tool_calls,
        "cost_usd": 0.0,  # Calculated by caller
    }


async def execute_with_fallback(
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
    Execute via OpenCode first, fall back to Agent SDK on failure.

    This is the primary entry point for the autonomous runner when
    USE_OPENCODE=1. It tries the cheap path first and only escalates
    to the expensive SDK path when OpenCode fails.

    Returns: Standard result dict with "text", "tokens", "tool_calls", "cost_usd"
    """
    # Try OpenCode first
    try:
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

        result = await run_opencode(
            prompt=full_prompt,
            workspace=workspace,
            timeout=timeout,
            job_id=job_id,
            phase=phase,
        )

        # Validate result has meaningful content
        if result["text"] and len(result["text"].strip()) > 20:
            logger.info(f"OpenCode succeeded for {job_id}/{phase}")
            return result

        logger.warning(
            f"OpenCode returned empty/short result for {job_id}/{phase}, "
            f"falling back to SDK"
        )

    except OpenCodeError as e:
        logger.warning(
            f"OpenCode failed for {job_id}/{phase}: {e} — falling back to SDK"
        )

    except Exception as e:
        logger.error(
            f"Unexpected OpenCode error for {job_id}/{phase}: {e} — falling back to SDK"
        )

    # Fall back to Agent SDK
    from autonomous_runner import _call_agent_sdk

    logger.info(f"Falling back to Agent SDK for {job_id}/{phase}")
    return await _call_agent_sdk(
        prompt=prompt,
        system_prompt=system_prompt,
        job_id=job_id,
        phase=phase,
        priority=priority,
        guardrails=guardrails,
        workspace=workspace,
    )


class OpenCodeError(Exception):
    """Raised when OpenCode CLI execution fails."""
    pass
