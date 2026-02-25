"""Provider fallback chain — automatic provider switching on failures.

Usage
-----
    from provider_chain import call_with_fallback, get_chain_status

    # Text-only research/planning phase (cheap providers first):
    result = await call_with_fallback(
        "text_reasoner",
        messages=[{"role": "user", "content": "Summarise this repo..."}],
        system="You are a helpful research assistant.",
    )

    # Tool-executing phase (Anthropic only, native tool_use required):
    result = await call_with_fallback(
        "tool_executor",
        messages=[{"role": "user", "content": "Run the tests."}],
        tools=[...],
    )

Return value
------------
    {
        "content":     <str | list>,   # str for kimi/minimax, list of blocks for anthropic
        "provider":    <str>,
        "model":       <str>,
        "usage":       {"input_tokens": int, "output_tokens": int},
        "stop_reason": <str | None>,
    }
"""

import asyncio
import logging
import time
import threading
from typing import Optional

logger = logging.getLogger("openclaw.provider_chain")

# ---------------------------------------------------------------------------
# Chain definitions — ordered by preference (cheapest first for text phases,
# Anthropic-only for tool execution because only Anthropic supports native
# tool_use content blocks that can be dispatched to execute_tool()).
# ---------------------------------------------------------------------------
PROVIDER_CHAINS: dict = {
    "tool_executor": [
        # Gemini 2.5 Flash supports native function calling — try it first.
        # Fall back to Anthropic if Gemini fails or key is missing.
        {"provider": "gemini",   "model": "gemini-2.5-flash"},
        {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    ],
    "text_reasoner": [
        # Cheapest provider first — Gemini 3 Flash Preview is FREE.
        {"provider": "gemini",   "model": "gemini-3-flash-preview"},
        {"provider": "kimi",     "model": "kimi-2.5"},
        {"provider": "minimax",  "model": "m2.5"},
        {"provider": "gemini",   "model": "gemini-2.5-flash-lite"},
        {"provider": "anthropic","model": "claude-haiku-4-5-20251001"},
    ],
}


# ---------------------------------------------------------------------------
# Lightweight synchronous provider-level cooldown tracker.
#
# error_recovery.CircuitBreaker operates per agent-key and is async; it is
# not designed for per-provider billing/rate-limit tracking.  We implement
# our own simple tracker here so provider_chain.py is self-contained and
# works without requiring a running asyncio event loop for cooldown queries.
# ---------------------------------------------------------------------------

class _ErrorKind:
    BILLING    = "billing"     # 402 / credit exhausted — long cooldown
    RATE_LIMIT = "rate_limit"  # 429                    — short cooldown
    OTHER      = "other"       # anything else          — brief cooldown

# Cooldown durations in seconds
_COOLDOWN = {
    _ErrorKind.BILLING:    3600,   # 1 hour — credits unlikely to refill faster
    _ErrorKind.RATE_LIMIT: 60,     # 1 minute
    _ErrorKind.OTHER:      15,     # brief pause before retry
}


class ProviderCooldownTracker:
    """Thread-safe, synchronous provider-level cooldown tracker.

    Tracks when a provider failed and prevents reuse until the appropriate
    cooldown window has elapsed.  Distinct from error_recovery.CircuitBreaker
    which operates on per-agent keys asynchronously.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # provider -> {"kind": str, "until": float}
        self._cooldowns: dict = {}

    def is_available(self, provider: str) -> tuple[bool, str]:
        """Return (available, reason_str).

        Thread-safe, synchronous — safe to call from any context.
        """
        with self._lock:
            entry = self._cooldowns.get(provider)
            if entry is None:
                return True, "ok"
            if time.time() >= entry["until"]:
                del self._cooldowns[provider]
                return True, "ok"
            remaining = int(entry["until"] - time.time())
            return False, f"cooling down ({entry['kind']}, {remaining}s remaining)"

    def mark_failure(self, provider: str, kind: str = _ErrorKind.OTHER) -> None:
        """Record a provider failure and start the appropriate cooldown."""
        duration = _COOLDOWN.get(kind, _COOLDOWN[_ErrorKind.OTHER])
        with self._lock:
            self._cooldowns[provider] = {
                "kind":  kind,
                "until": time.time() + duration,
            }
        logger.warning(
            f"Provider '{provider}' marked as {kind!r} — cooldown {duration}s"
        )

    def mark_success(self, provider: str) -> None:
        """Clear any cooldown after a successful call."""
        with self._lock:
            self._cooldowns.pop(provider, None)

    def get_status(self) -> dict:
        """Return a snapshot of all active cooldowns."""
        with self._lock:
            return {
                p: {
                    "kind":      e["kind"],
                    "remaining": max(0, int(e["until"] - time.time())),
                }
                for p, e in self._cooldowns.items()
            }


# Module-level singleton — imported by other modules for shared state.
provider_cooldowns = ProviderCooldownTracker()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def call_with_fallback(
    chain_name: str,
    messages: list,
    tools: list = None,
    max_tokens: int = 4096,
    system: str = None,
) -> dict:
    """Try providers in chain order, skipping cooled-down ones.

    Args:
        chain_name:  Key in PROVIDER_CHAINS — "tool_executor" or "text_reasoner".
        messages:    Conversation messages list (OpenAI/Anthropic style dicts).
        tools:       Tool definitions (Anthropic format).  Only works with
                     the "tool_executor" chain (Anthropic provider).
        max_tokens:  Maximum output tokens.
        system:      System prompt string.

    Returns:
        Normalised response dict — see module docstring.

    Raises:
        RuntimeError if every provider in the chain is unavailable or fails.
    """
    candidates = PROVIDER_CHAINS.get(chain_name, PROVIDER_CHAINS["text_reasoner"])
    errors: list[str] = []

    for candidate in candidates:
        provider = candidate["provider"]
        model    = candidate["model"]

        available, reason = provider_cooldowns.is_available(provider)
        if not available:
            msg = f"{provider}/{model}: {reason}"
            errors.append(msg)
            logger.info(f"Skipping provider {provider!r}: {reason}")
            continue

        try:
            result = await _call_provider(
                provider, model, messages,
                tools=tools,
                max_tokens=max_tokens,
                system=system,
            )
            provider_cooldowns.mark_success(provider)
            logger.info(
                f"Provider {provider!r} ({model}) succeeded — "
                f"usage={result.get('usage', {})}"
            )
            return result

        except Exception as exc:
            err_str = str(exc).lower()

            if any(x in err_str for x in ["credit", "billing", "402", "balance", "payment", "insufficient"]):
                kind = _ErrorKind.BILLING
            elif any(x in err_str for x in ["rate", "429", "too many", "throttl"]):
                kind = _ErrorKind.RATE_LIMIT
            else:
                kind = _ErrorKind.OTHER

            provider_cooldowns.mark_failure(provider, kind)
            msg = f"{provider}/{model}: {exc}"
            errors.append(msg)
            logger.warning(
                f"Provider {provider!r} failed ({kind}): {exc} — trying next in chain"
            )
            continue

    raise RuntimeError(
        f"All providers in chain '{chain_name}' exhausted. "
        f"Errors: {'; '.join(errors)}"
    )


async def _call_provider(
    provider: str,
    model: str,
    messages: list,
    tools: list = None,
    max_tokens: int = 4096,
    system: str = None,
) -> dict:
    """Dispatch to the appropriate provider client.

    All providers are called via run_in_executor so the event loop stays
    unblocked while waiting for network I/O.

    Anthropic returns a list of content blocks (matching the SDK response
    format expected by autonomous_runner._call_agent).  Kimi and MiniMax
    return a plain string in the "content" field.
    """
    loop = asyncio.get_running_loop()

    if provider == "anthropic":
        return await loop.run_in_executor(
            None,
            lambda: _call_anthropic(model, messages, tools=tools, max_tokens=max_tokens, system=system),
        )

    elif provider == "kimi":
        return await loop.run_in_executor(
            None,
            lambda: _call_kimi(model, messages, system=system, max_tokens=max_tokens),
        )

    elif provider == "minimax":
        return await loop.run_in_executor(
            None,
            lambda: _call_minimax(model, messages, system=system, max_tokens=max_tokens),
        )

    elif provider == "gemini":
        return await loop.run_in_executor(
            None,
            lambda: _call_gemini(model, messages, tools=tools, system=system, max_tokens=max_tokens),
        )

    else:
        raise ValueError(f"Unknown provider: {provider!r}")


# ---------------------------------------------------------------------------
# Provider-specific synchronous call helpers
# (run inside run_in_executor — must not use await)
# ---------------------------------------------------------------------------

def _call_anthropic(
    model: str,
    messages: list,
    tools: list = None,
    max_tokens: int = 4096,
    system: str = None,
) -> dict:
    """Synchronous Anthropic SDK call."""
    import os
    import anthropic  # type: ignore

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)

    kwargs: dict = {
        "model":      model,
        "max_tokens": max_tokens,
        "messages":   messages,
    }
    if system:
        kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    if tools:
        # Cache tool definitions (they don't change between calls)
        cached_tools = list(tools)
        if cached_tools:
            cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}
        kwargs["tools"] = cached_tools

    # Cache conversation prefix — mark last user message
    # Anthropic allows max 4 cache_control blocks; system (1) + tools (1) = 2 already
    existing_cache_blocks = (1 if system else 0) + (1 if tools else 0)
    if messages and len(messages) >= 2 and existing_cache_blocks < 4:
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                content = messages[i]["content"]
                if isinstance(content, str):
                    messages[i]["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                elif isinstance(content, list):
                    last_block = content[-1]
                    if isinstance(last_block, dict) and "cache_control" not in last_block:
                        content[-1] = {**last_block, "cache_control": {"type": "ephemeral"}}
                break

    response = client.messages.create(**kwargs)

    return {
        "content":     response.content,          # list of SDK content blocks
        "provider":    "anthropic",
        "model":       response.model,
        "usage": {
            "input_tokens":  response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
        "stop_reason": response.stop_reason,
    }


def _call_kimi(
    model: str,
    messages: list,
    system: str = None,
    max_tokens: int = 4096,
) -> dict:
    """Synchronous Kimi (Deepseek) call via deepseek_client.DeepseekClient.

    Converts the messages list to a (system_prompt, user_prompt) pair that
    DeepseekClient.call() expects.  If there are multiple turns we pass the
    last user message as the prompt and reconstruct system from the first
    system block (if any).
    """
    from deepseek_client import DeepseekClient  # type: ignore

    # Extract system prompt — prefer explicit arg, fall back to messages list.
    sys_prompt = system
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system" and sys_prompt is None:
            sys_prompt = msg["content"]
        else:
            user_messages.append(msg)

    # Build prompt: join all user/assistant turns, then end with final user msg.
    if not user_messages:
        raise ValueError("No user messages provided for kimi call")

    # For simplicity, concatenate prior turns as context in the prompt string.
    # DeepseekClient.call() does not natively accept multi-turn arrays, so we
    # flatten them here.  Full multi-turn support could use the conversation_history
    # feature of KimiAgent, but that requires an agent_id rather than a raw model.
    if len(user_messages) == 1:
        prompt = user_messages[-1]["content"]
    else:
        parts = []
        for m in user_messages:
            role_label = "User" if m["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {m['content']}")
        prompt = "\n".join(parts)

    client = DeepseekClient()
    response = client.call(
        model=model,
        prompt=prompt,
        system_prompt=sys_prompt,
        max_tokens=max_tokens,
    )

    return {
        "content":     response.content,
        "provider":    "kimi",
        "model":       model,
        "usage": {
            "input_tokens":  response.tokens_input,
            "output_tokens": response.tokens_output,
        },
        "stop_reason": getattr(response, "stop_reason", "stop"),
    }


def _call_minimax(
    model: str,
    messages: list,
    system: str = None,
    max_tokens: int = 4096,
) -> dict:
    """Synchronous MiniMax call via minimax_client.MiniMaxClient.

    Same flattening strategy as _call_kimi — MiniMaxClient.call() takes
    (model, prompt, system_prompt) rather than a messages array.
    """
    from minimax_client import MiniMaxClient  # type: ignore

    sys_prompt = system
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system" and sys_prompt is None:
            sys_prompt = msg["content"]
        else:
            user_messages.append(msg)

    if not user_messages:
        raise ValueError("No user messages provided for minimax call")

    if len(user_messages) == 1:
        prompt = user_messages[-1]["content"]
    else:
        parts = []
        for m in user_messages:
            role_label = "User" if m["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {m['content']}")
        prompt = "\n".join(parts)

    # MiniMaxClient constructor raises ValueError if MINIMAX_API_KEY is unset.
    client = MiniMaxClient()
    response = client.call(
        model=model,
        prompt=prompt,
        system_prompt=sys_prompt,
        max_tokens=max_tokens,
    )

    return {
        "content":     response.content,
        "provider":    "minimax",
        "model":       model,
        "usage": {
            "input_tokens":  response.tokens_input,
            "output_tokens": response.tokens_output,
        },
        "stop_reason": response.stop_reason,
    }


def _call_gemini(
    model: str,
    messages: list,
    tools: list = None,
    system: str = None,
    max_tokens: int = 4096,
) -> dict:
    """Synchronous Gemini call via gemini_client.GeminiClient.

    Same flattening strategy as _call_kimi — GeminiClient.call() takes
    (model, prompt, system_prompt) rather than a messages array.

    When tools are provided, they are converted to Gemini functionDeclarations
    and any functionCall responses are normalized to Anthropic-style tool_use
    content blocks (list format matching Anthropic provider output).
    """
    from gemini_client import GeminiClient  # type: ignore

    sys_prompt = system
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system" and sys_prompt is None:
            sys_prompt = msg["content"]
        else:
            user_messages.append(msg)

    if not user_messages:
        raise ValueError("No user messages provided for gemini call")

    if len(user_messages) == 1:
        prompt = user_messages[-1]["content"]
    else:
        parts = []
        for m in user_messages:
            role_label = "User" if m["role"] == "user" else "Assistant"
            parts.append(f"{role_label}: {m['content']}")
        prompt = "\n".join(parts)

    client = GeminiClient()
    response = client.call(
        model=model,
        prompt=prompt,
        system_prompt=sys_prompt,
        max_tokens=max_tokens,
        tools=tools,
    )

    # Build content — if tool calls present, return as list of content blocks
    # (matching Anthropic format for tool_executor chain compatibility).
    if response.tool_calls:
        content_blocks = []
        if response.content:
            content_blocks.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            content_blocks.append(tc)
        content = content_blocks
    else:
        content = response.content

    return {
        "content":     content,
        "provider":    "gemini",
        "model":       model,
        "usage": {
            "input_tokens":  response.tokens_input,
            "output_tokens": response.tokens_output,
        },
        "stop_reason": response.stop_reason,
    }


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def get_chain_status() -> dict:
    """Return current availability of all providers across all chains.

    Example output::

        {
            "tool_executor": [
                {"provider": "anthropic", "model": "claude-haiku-4-5-20251001",
                 "available": True, "reason": "ok"}
            ],
            "text_reasoner": [
                {"provider": "kimi",    "model": "kimi-2.5",
                 "available": False, "reason": "cooling down (billing, 3412s remaining)"},
                ...
            ]
        }
    """
    status: dict = {}
    for chain_name, candidates in PROVIDER_CHAINS.items():
        chain_status = []
        for c in candidates:
            available, reason = provider_cooldowns.is_available(c["provider"])
            chain_status.append({
                "provider":  c["provider"],
                "model":     c["model"],
                "available": available,
                "reason":    reason,
            })
        status[chain_name] = chain_status
    return status
