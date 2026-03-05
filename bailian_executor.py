"""
Bailian Executor — Alibaba Cloud Bailian Coding Plan backend.

Single API key for 9+ models via DashScope OpenAI-compatible endpoint.
Models: kimi-k2.5, glm-5, qwen3.5-flash, qwen3-coder-next, deepseek-v3.2, etc.

Endpoint: https://dashscope.aliyuncs.com/compatible-mode/v1
Plan: Coding Lite (¥7.9→¥40/mo, 18K requests) or Pro (¥39.9→¥200/mo, 90K requests)

Fallback chain position: OpenCode → **Bailian** → Grok → MiniMax → SDK
"""

import logging
import os

import httpx

from cost_tracker import log_cost_event

logger = logging.getLogger("openclaw.bailian_executor")

BAILIAN_BASE_URL = "https://coding-intl.dashscope.aliyuncs.com/v1"

# Models confirmed working on the Coding Plan (tested 2026-03-05)
MODELS = {
    "code": "qwen3-coder-next",    # Code-specialized (primary)
    "kimi": "kimi-k2.5",           # Kimi K2.5 (strong all-rounder)
    "glm5": "glm-5",               # Zhipu GLM-5
    "glm4": "glm-4.7",             # Zhipu GLM-4.7
    "plus": "qwen3.5-plus",        # Higher quality Qwen
}

# Approximate pricing per 1M tokens (bundled plan — actual cost is ¥7.9-40/mo flat)
# These rates are for cost tracking only
PRICING = {
    "qwen3-coder-next": {"input": 0.14, "output": 0.28},
    "kimi-k2.5":        {"input": 0.14, "output": 0.28},
    "glm-5":            {"input": 0.14, "output": 0.28},
    "glm-4.7":          {"input": 0.10, "output": 0.20},
    "qwen3.5-plus":     {"input": 0.50, "output": 1.50},
}

DEFAULT_MODEL = "qwen3-coder-next"


def _get_api_key() -> str:
    return os.environ.get("BAILIAN_API_KEY", "")


def is_available() -> bool:
    """Check if Bailian executor is configured."""
    return bool(_get_api_key())


async def call_bailian(
    prompt: str,
    system_prompt: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8192,
    temperature: float = 0.1,
    timeout: int = 120,
) -> dict:
    """Call Bailian DashScope API and return response text + cost estimate."""

    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("BAILIAN_API_KEY not set")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{BAILIAN_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]
    text = choice["message"]["content"]
    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    pricing = PRICING.get(model, PRICING[DEFAULT_MODEL])
    cost_usd = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    logger.info(f"Bailian {model}: {input_tokens}in/{output_tokens}out = ${cost_usd:.4f}")

    return {
        "text": text,
        "tokens": input_tokens + output_tokens,
        "cost_usd": cost_usd,
        "model": model,
        "tool_calls": [],
        "source": "bailian",
    }


async def execute_with_bailian(
    prompt: str,
    job_id: str,
    phase: str,
    priority: str,
    conversation: list | None = None,
    system_prompt: str = "",
) -> dict:
    """Execute a job phase using Bailian. Returns same dict format as other executors."""

    # Pick model based on priority and phase
    if priority == "P0":
        model = "qwen3.5-plus"
    elif phase in ("execute", "verify"):
        model = "qwen3-coder-next"
    else:
        model = "kimi-k2.5"

    full_prompt = prompt
    if conversation:
        context_parts = []
        for msg in conversation[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                context_parts.append(f"[Previous {role}]: {content[:1000]}")
        if context_parts:
            full_prompt = "CONTEXT FROM PREVIOUS STEPS:\n" + "\n".join(context_parts) + "\n\n---\n\n" + prompt

    if not system_prompt:
        system_prompt = (
            "You are an autonomous AI agent executing a task for the OpenClaw agency. "
            "Provide clear, actionable output. Write code directly when needed. "
            "Be thorough but concise in analysis."
        )

    result = await call_bailian(
        prompt=full_prompt,
        system_prompt=system_prompt,
        model=model,
        max_tokens=8192,
        temperature=0.1,
    )

    # Log cost
    log_cost_event(
        project="openclaw",
        agent="bailian",
        model=model,
        tokens_input=result.get("tokens", 0) // 2,
        tokens_output=result.get("tokens", 0) // 2,
        cost=result["cost_usd"],
        event_type="bailian_call",
        metadata={"phase": phase, "priority": priority},
        job_id=job_id,
    )

    logger.info(f"Bailian completed {job_id}/{phase} with {model} for ${result['cost_usd']:.4f}")
    return result
