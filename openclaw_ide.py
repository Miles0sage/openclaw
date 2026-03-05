"""
OpenClaw IDE — Multi-model native tool-calling executor with 81 MCP tools.

Models with native tool calling:
  - Claude Sonnet 4.6 (Anthropic) — best coder, $3/$15 per 1M tokens
  - Gemini 2.5 Flash (Google)     — cheap + reliable, $0.30/$2.50 per 1M tokens
  - Grok 3 Mini (xAI)             — OpenAI-compatible, ~$0.30/$0.50 per 1M tokens

Routing: Claude for coding tasks (P0/P1), Gemini for analysis (P2/P3), Grok as fallback.
Cost: ~$0.001-0.02/job depending on model.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from agent_tools import execute_tool as _raw_execute_tool, AGENT_TOOLS
from cost_tracker import log_cost_event

logger = logging.getLogger("openclaw_ide")

# Load env — ensure all API keys are available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass

MAX_ITERATIONS = 25

# Cost per 1M tokens
MODEL_COSTS = {
    "claude-sonnet-4-6":      {"input": 3.00,  "output": 15.00},
    "minimax-m2.5":           {"input": 0.30,  "output": 1.20},
    "gemini-2.5-pro":         {"input": 1.25,  "output": 10.00},
    "gemini-2.5-flash":       {"input": 0.30,  "output": 2.50},
    "gemini-3-pro-preview":   {"input": 0.00,  "output": 0.00},   # FREE preview
    "gemini-3-flash-preview": {"input": 0.00,  "output": 0.00},   # FREE preview
    "grok-3-mini":            {"input": 0.30,  "output": 0.50},
}

# Provider per model — "openai_compat" uses the same _call_openai_compat() for Grok/MiniMax
MODEL_PROVIDER = {
    "claude-sonnet-4-6":      "anthropic",
    "minimax-m2.5":           "openai_compat",
    "gemini-2.5-pro":         "gemini",
    "gemini-2.5-flash":       "gemini",
    "gemini-3-pro-preview":   "gemini",
    "gemini-3-flash-preview": "gemini",
    "grok-3-mini":            "openai_compat",
}

# OpenAI-compatible API endpoints per model
OPENAI_COMPAT_CONFIG = {
    "grok-3-mini":  {"base_url": "https://api.x.ai/v1",         "env_key": "XAI_API_KEY",     "api_model": "grok-3-mini"},
    "minimax-m2.5": {"base_url": "https://api.minimax.io/v1",   "env_key": "MINIMAX_API_KEY", "api_model": "MiniMax-M2.5"},
}

# Priority-based model selection
# MiniMax for coding (80.2% SWE-Bench, $0.30/$1.20) — same quality as Claude at 10x less cost
PRIORITY_MODELS = {
    "P0": "minimax-m2.5",        # Best value coder (80.2% SWE-Bench, cheap)
    "P1": "minimax-m2.5",        # Strong coder for important tasks
    "P2": "gemini-2.5-flash",    # Cheap + reliable for routine
    "P3": "gemini-2.5-flash",    # Cheapest for low-priority
}

# Phase-based overrides (coding phases use Claude)
CODING_PHASES = {"execute", "verify", "deliver"}


def _fix_schema_for_gemini(schema: dict) -> dict:
    """Fix JSON Schema issues that Gemini rejects (e.g. array without items)."""
    if not isinstance(schema, dict):
        return schema
    fixed = {}
    for k, v in schema.items():
        if isinstance(v, dict):
            v = _fix_schema_for_gemini(v)
            if v.get("type") == "array" and "items" not in v:
                v = {**v, "items": {"type": "string"}}
        fixed[k] = v
    return fixed


def _compact_tools(tools: list, max_tools: int = 81) -> list:
    """Shorten tool descriptions to save tokens. Keep name + params."""
    compact = []
    for t in tools[:max_tools]:
        schema = _fix_schema_for_gemini(t.get("input_schema", {}))
        compact.append({
            "name": t["name"],
            "description": t.get("description", "")[:120],
            "input_schema": schema,
        })
    return compact


def _execute_tool_safe(tool_name: str, tool_input: dict, job_id: str = "") -> str:
    """Execute a tool with error handling. Returns result string."""
    try:
        try:
            from tool_router import get_registry
            registry = get_registry()
            result = registry.execute_tool(tool_name, tool_input, job_id=job_id)
            return result if isinstance(result, str) else json.dumps(result)
        except (ImportError, Exception):
            pass
        result = _raw_execute_tool(tool_name, tool_input)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})


def _calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate cost in USD."""
    costs = MODEL_COSTS.get(model, {"input": 0.30, "output": 2.50})
    return (tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000


def _select_model(priority: str = "P2", phase: str = "", model: Optional[str] = None) -> str:
    """Select the best model based on priority and phase."""
    if model:
        return model
    # Coding phases get Claude regardless of priority
    if phase.lower() in CODING_PHASES:
        return "claude-sonnet-4-6"
    return PRIORITY_MODELS.get(priority, "gemini-2.5-flash")


# ─── Claude (Anthropic) Tool Calling ──────────────────────────────────────────

def _tools_to_anthropic(tools: list) -> list:
    """Convert our tool format to Anthropic's tool_use format."""
    anthropic_tools = []
    for t in tools:
        schema = t.get("input_schema", {})
        # Anthropic wants: name, description, input_schema (JSON Schema)
        anthropic_tools.append({
            "name": t["name"],
            "description": t.get("description", "")[:200],
            "input_schema": schema,
        })
    return anthropic_tools


async def _call_claude(
    prompt: str,
    tools: list,
    system_prompt: str,
    job_id: str,
    phase: str,
    max_iterations: int,
    timeout: int,
    model: str = "claude-sonnet-4-6",
) -> dict:
    """Execute prompt with Claude's native tool_use calling."""
    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    start_time = time.time()
    anthropic_tools = _tools_to_anthropic(tools)
    messages = [{"role": "user", "content": prompt}]

    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    all_tool_calls = []
    final_text = ""
    iterations = 0

    for iteration in range(max_iterations):
        if time.time() - start_time > timeout:
            logger.warning(f"Claude timeout after {iteration} iters for {job_id}/{phase}")
            break

        iterations = iteration + 1

        try:
            payload = {
                "model": model,
                "max_tokens": 16384,
                "temperature": 0.2,
                "messages": messages,
                "tools": anthropic_tools,
            }
            if system_prompt:
                payload["system"] = system_prompt

            async with httpx.AsyncClient(timeout=timeout) as http_client:
                response = await http_client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            # Token tracking
            usage = data.get("usage", {})
            tokens_in = usage.get("input_tokens", 0)
            tokens_out = usage.get("output_tokens", 0)
            total_tokens_in += tokens_in
            total_tokens_out += tokens_out
            total_cost += _calculate_cost(model, tokens_in, tokens_out)

            # Parse content blocks
            content = data.get("content", [])
            stop_reason = data.get("stop_reason", "end_turn")

            text_blocks = [b["text"] for b in content if b.get("type") == "text"]
            tool_blocks = [b for b in content if b.get("type") == "tool_use"]

            if text_blocks:
                final_text = "\n".join(text_blocks)

            # No tool calls = done
            if not tool_blocks:
                if not final_text and all_tool_calls:
                    result_summaries = [f"Tool {tc['tool']}: {tc['result'][:500]}" for tc in all_tool_calls[-5:]]
                    final_text = "Task completed. Tool results:\n" + "\n".join(result_summaries)
                logger.info(f"Claude: {job_id}/{phase} complete after {iterations} iters, {len(all_tool_calls)} tool calls, ${total_cost:.6f}")
                break

            # Add assistant response to messages
            messages.append({"role": "assistant", "content": content})

            # Execute tool calls
            tool_results = []
            for tb in tool_blocks:
                tool_name = tb["name"]
                tool_input = tb.get("input", {})
                tool_use_id = tb["id"]

                logger.info(f"Claude: {job_id}/{phase} calling {tool_name}({json.dumps(tool_input)[:100]})")

                result_str = await asyncio.get_running_loop().run_in_executor(
                    None, _execute_tool_safe, tool_name, tool_input, job_id
                )

                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n... (truncated)"

                all_tool_calls.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result_str[:2000],
                })

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_str,
                })

            # Feed tool results back
            messages.append({"role": "user", "content": tool_results})

        except httpx.HTTPStatusError as e:
            error_body = e.response.text[:300] if hasattr(e.response, 'text') else str(e)
            logger.warning(f"Claude HTTP error: {error_body}")
            raise
        except Exception as e:
            logger.error(f"Claude error in iteration {iteration}: {e}")
            raise

    elapsed = time.time() - start_time

    if total_cost > 0 and job_id:
        try:
            log_cost_event(
                agent="openclaw_ide", model=model,
                input_tokens=total_tokens_in, output_tokens=total_tokens_out,
                cost_usd=total_cost, job_id=job_id, phase=phase, provider="anthropic",
            )
        except Exception:
            pass

    return {
        "text": final_text,
        "tokens": total_tokens_in + total_tokens_out,
        "tool_calls": all_tool_calls,
        "cost_usd": round(total_cost, 6),
        "model": model,
        "iterations": iterations,
        "elapsed_seconds": round(elapsed, 1),
    }


# ─── OpenAI-Compatible Tool Calling (Grok, MiniMax, etc.) ─────────────────────

def _tools_to_openai(tools: list) -> list:
    """Convert our tool format to OpenAI-compatible function calling format."""
    openai_tools = []
    for t in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", "")[:200],
                "parameters": t.get("input_schema", {}),
            },
        })
    return openai_tools


async def _call_openai_compat(
    prompt: str,
    tools: list,
    system_prompt: str,
    job_id: str,
    phase: str,
    max_iterations: int,
    timeout: int,
    model: str = "grok-3-mini",
) -> dict:
    """Execute prompt with any OpenAI-compatible API (Grok, MiniMax, etc.)."""
    import httpx

    config = OPENAI_COMPAT_CONFIG.get(model, {})
    base_url = config.get("base_url", "https://api.x.ai/v1")
    env_key = config.get("env_key", "XAI_API_KEY")
    api_model = config.get("api_model", model)
    label = model.split("-")[0].capitalize()  # "Grok" or "Minimax"

    api_key = os.environ.get(env_key, "")
    if not api_key:
        raise ValueError(f"{env_key} not set")

    start_time = time.time()
    openai_tools = _tools_to_openai(tools)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    all_tool_calls = []
    final_text = ""
    iterations = 0

    for iteration in range(max_iterations):
        if time.time() - start_time > timeout:
            logger.warning(f"{label} timeout after {iteration} iters for {job_id}/{phase}")
            break

        iterations = iteration + 1

        try:
            payload = {
                "model": api_model,
                "max_tokens": 16384,
                "temperature": 0.2,
                "messages": messages,
                "tools": openai_tools,
            }

            async with httpx.AsyncClient(timeout=timeout) as http_client:
                response = await http_client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            # Token tracking
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            total_tokens_in += tokens_in
            total_tokens_out += tokens_out
            total_cost += _calculate_cost(model, tokens_in, tokens_out)

            # Parse response
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})

            # Strip <think> tags from content (MiniMax includes reasoning)
            content = message.get("content", "") or ""
            import re as _re
            content = _re.sub(r"<think>.*?</think>", "", content, flags=_re.DOTALL).strip()
            if content:
                final_text = content

            tool_calls_raw = message.get("tool_calls", [])

            if not tool_calls_raw:
                if not final_text and all_tool_calls:
                    result_summaries = [f"Tool {tc['tool']}: {tc['result'][:500]}" for tc in all_tool_calls[-5:]]
                    final_text = "Task completed. Tool results:\n" + "\n".join(result_summaries)
                logger.info(f"{label}: {job_id}/{phase} complete after {iterations} iters, {len(all_tool_calls)} tool calls, ${total_cost:.6f}")
                break

            # Add assistant message to conversation (keep original for API)
            messages.append(message)

            for tc in tool_calls_raw:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    tool_input = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_input = {}
                call_id = tc.get("id", str(uuid.uuid4()))

                logger.info(f"{label}: {job_id}/{phase} calling {tool_name}({json.dumps(tool_input)[:100]})")

                result_str = await asyncio.get_running_loop().run_in_executor(
                    None, _execute_tool_safe, tool_name, tool_input, job_id
                )

                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n... (truncated)"

                all_tool_calls.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result_str[:2000],
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_str,
                })

        except httpx.HTTPStatusError as e:
            error_body = e.response.text[:300] if hasattr(e.response, 'text') else str(e)
            logger.warning(f"{label} HTTP error: {error_body}")
            raise
        except Exception as e:
            logger.error(f"{label} error in iteration {iteration}: {e}")
            raise

    elapsed = time.time() - start_time
    provider = env_key.replace("_API_KEY", "").lower()

    if total_cost > 0 and job_id:
        try:
            log_cost_event(
                agent="openclaw_ide", model=model,
                input_tokens=total_tokens_in, output_tokens=total_tokens_out,
                cost_usd=total_cost, job_id=job_id, phase=phase, provider=provider,
            )
        except Exception:
            pass

    return {
        "text": final_text,
        "tokens": total_tokens_in + total_tokens_out,
        "tool_calls": all_tool_calls,
        "cost_usd": round(total_cost, 6),
        "model": model,
        "iterations": iterations,
        "elapsed_seconds": round(elapsed, 1),
    }


# ─── Gemini Tool Calling (existing) ──────────────────────────────────────────

async def _call_gemini(
    prompt: str,
    tools: list,
    system_prompt: str,
    job_id: str,
    phase: str,
    max_iterations: int,
    timeout: int,
    model: str = "gemini-2.5-flash",
) -> dict:
    """Execute prompt with Gemini's native tool calling."""
    import httpx
    from gemini_client import GeminiClient

    start_time = time.time()

    try:
        client = GeminiClient()
    except ValueError as e:
        raise ValueError(f"Gemini init failed: {e}")

    gemini_tools = client._convert_tools_to_gemini(tools)
    conversation = [{"role": "user", "parts": [{"text": prompt}]}]

    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    all_tool_calls = []
    final_text = ""
    iterations = 0
    selected_model = model

    gemini_chain = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash-preview"]

    for iteration in range(max_iterations):
        if time.time() - start_time > timeout:
            logger.warning(f"Gemini timeout after {iteration} iters for {job_id}/{phase}")
            break

        iterations = iteration + 1

        try:
            payload = {
                "contents": conversation,
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 16384},
                "tools": gemini_tools,
            }
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

            api_model = client.MODELS[selected_model]["api_name"]
            url = f"{client.BASE_URL}/models/{api_model}:generateContent"

            async with httpx.AsyncClient(timeout=timeout) as http_client:
                response = await http_client.post(
                    url,
                    headers={"Content-Type": "application/json", "x-goog-api-key": client.api_key},
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning(f"Gemini: No candidates from {selected_model} for {job_id}/{phase}")
                break

            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])

            usage = data.get("usageMetadata", {})
            tokens_in = usage.get("promptTokenCount", 0)
            tokens_out = usage.get("candidatesTokenCount", 0)
            total_tokens_in += tokens_in
            total_tokens_out += tokens_out
            total_cost += _calculate_cost(selected_model, tokens_in, tokens_out)

            text_parts = [p["text"] for p in parts if "text" in p]
            tool_call_parts = [p for p in parts if "functionCall" in p]

            if text_parts:
                final_text = "\n".join(text_parts)

            if not tool_call_parts and not final_text and all_tool_calls:
                result_summaries = [f"Tool {tc['tool']}: {tc['result'][:500]}" for tc in all_tool_calls[-5:]]
                final_text = "Task completed. Tool results:\n" + "\n".join(result_summaries)
            if not tool_call_parts:
                logger.info(f"Gemini: {job_id}/{phase} complete after {iterations} iters, {len(all_tool_calls)} tool calls, ${total_cost:.6f}")
                break

            conversation.append({"role": "model", "parts": parts})

            tool_results = []
            for tc_part in tool_call_parts:
                fc = tc_part["functionCall"]
                tool_name = fc["name"]
                tool_input = fc.get("args", {})

                logger.info(f"Gemini: {job_id}/{phase} calling {tool_name}({json.dumps(tool_input)[:100]})")

                result_str = await asyncio.get_running_loop().run_in_executor(
                    None, _execute_tool_safe, tool_name, tool_input, job_id
                )

                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n... (truncated)"

                all_tool_calls.append({
                    "tool": tool_name,
                    "input": tool_input,
                    "result": result_str[:2000],
                })

                tool_results.append({
                    "functionResponse": {
                        "name": tool_name,
                        "response": {"result": result_str},
                    }
                })

            conversation.append({"role": "user", "parts": tool_results})

        except httpx.HTTPStatusError as e:
            error_body = e.response.text[:300] if hasattr(e.response, 'text') else str(e)
            logger.warning(f"Gemini: {selected_model} HTTP error: {error_body}")
            current_idx = gemini_chain.index(selected_model) if selected_model in gemini_chain else 0
            if current_idx + 1 < len(gemini_chain):
                selected_model = gemini_chain[current_idx + 1]
                logger.info(f"Gemini: Falling back to {selected_model}")
                continue
            else:
                raise
        except Exception as e:
            logger.error(f"Gemini error in iteration {iteration}: {e}")
            raise

    elapsed = time.time() - start_time

    if total_cost > 0 and job_id:
        try:
            log_cost_event(
                agent="openclaw_ide", model=selected_model,
                input_tokens=total_tokens_in, output_tokens=total_tokens_out,
                cost_usd=total_cost, job_id=job_id, phase=phase, provider="gemini",
            )
        except Exception:
            pass

    return {
        "text": final_text,
        "tokens": total_tokens_in + total_tokens_out,
        "tool_calls": all_tool_calls,
        "cost_usd": round(total_cost, 6),
        "model": selected_model,
        "iterations": iterations,
        "elapsed_seconds": round(elapsed, 1),
    }


# ─── Main Entry Points ───────────────────────────────────────────────────────

async def execute_with_ide(
    prompt: str,
    tools: Optional[list] = None,
    system_prompt: str = "",
    workspace: str = "/root/openclaw",
    job_id: str = "",
    phase: str = "",
    priority: str = "P2",
    max_iterations: int = MAX_ITERATIONS,
    timeout: int = 300,
    model: Optional[str] = None,
) -> dict:
    """
    Execute a prompt with native tool calling via the best available model.

    Routes to Claude (coding), Gemini (analysis), or Grok (fallback) based on
    priority and phase. All models use native tool calling with our 81 MCP tools.

    Returns: {"text": str, "tokens": int, "tool_calls": list, "cost_usd": float}
    """
    if tools is None:
        tools = _compact_tools(AGENT_TOOLS)

    if not system_prompt:
        system_prompt = (
            "You are an autonomous AI agent with access to tools. "
            "Execute the task by calling the appropriate tools. "
            "Read files before editing them. Test code after writing it. "
            f"Working directory: {workspace}\n"
            "When done, respond with your final summary (no tool calls)."
        )

    selected_model = _select_model(priority, phase, model)
    provider = MODEL_PROVIDER.get(selected_model, "gemini")

    logger.info(f"IDE: {job_id}/{phase} using {selected_model} ({provider}) [priority={priority}]")

    call_args = dict(
        prompt=prompt, tools=tools, system_prompt=system_prompt,
        job_id=job_id, phase=phase, max_iterations=max_iterations,
        timeout=timeout, model=selected_model,
    )

    if provider == "anthropic":
        return await _call_claude(**call_args)
    elif provider == "openai_compat":
        return await _call_openai_compat(**call_args)
    else:
        return await _call_gemini(**call_args)


async def execute_ide_with_fallback(
    prompt: str,
    tools: Optional[list] = None,
    system_prompt: str = "",
    workspace: str = "/root/openclaw",
    job_id: str = "",
    phase: str = "",
    priority: str = "P2",
    guardrails=None,
    **kwargs,
) -> dict:
    """
    Execute with the best model, falling back through the chain on failure.
    Chain: MiniMax → Gemini Pro → Gemini Flash → Claude → Grok → text-only
    """
    if tools is None:
        tools = _compact_tools(AGENT_TOOLS)

    if not system_prompt:
        system_prompt = (
            "You are an autonomous AI agent with access to tools. "
            "Execute the task by calling the appropriate tools. "
            "Read files before editing them. Test code after writing it. "
            f"Working directory: {workspace}\n"
            "When done, respond with your final summary (no tool calls)."
        )

    selected_model = _select_model(priority, phase)
    provider = MODEL_PROVIDER.get(selected_model, "gemini")

    # Build fallback chain: primary → cheaper fallbacks → premium last resort
    fallback_chain = []
    if provider == "openai_compat":
        # MiniMax primary → Gemini Pro → Gemini Flash → Claude → Grok
        fallback_chain = [
            ("openai_compat", selected_model),
            ("gemini", "gemini-2.5-pro"),
            ("gemini", "gemini-2.5-flash"),
            ("anthropic", "claude-sonnet-4-6"),
            ("openai_compat", "grok-3-mini"),
        ]
    elif provider == "anthropic":
        fallback_chain = [
            ("anthropic", "claude-sonnet-4-6"),
            ("openai_compat", "minimax-m2.5"),
            ("gemini", "gemini-2.5-pro"),
            ("gemini", "gemini-2.5-flash"),
        ]
    else:
        # Gemini primary → MiniMax → Gemini Pro → Grok
        fallback_chain = [
            ("gemini", "gemini-2.5-flash"),
            ("openai_compat", "minimax-m2.5"),
            ("gemini", "gemini-2.5-pro"),
            ("openai_compat", "grok-3-mini"),
        ]

    call_args = dict(
        prompt=prompt, tools=tools, system_prompt=system_prompt,
        job_id=job_id, phase=phase, max_iterations=MAX_ITERATIONS,
        timeout=300,
    )

    for prov, mdl in fallback_chain:
        try:
            if prov == "anthropic":
                result = await _call_claude(**call_args, model=mdl)
            elif prov == "openai_compat":
                result = await _call_openai_compat(**call_args, model=mdl)
            else:
                result = await _call_gemini(**call_args, model=mdl)

            if result and result.get("text"):
                return result
            logger.warning(f"IDE: {mdl} returned empty for {job_id}/{phase}")
        except Exception as e:
            logger.warning(f"IDE: {mdl} failed for {job_id}/{phase}: {e}")

    # Text-only fallbacks
    try:
        from grok_executor import execute_with_grok
        logger.info(f"Falling back to Grok text-only for {job_id}/{phase}")
        grok_result = await execute_with_grok(
            prompt=prompt, job_id=job_id, phase=phase,
            priority=priority, system_prompt=system_prompt,
        )
        if grok_result and grok_result.get("text"):
            return grok_result
    except Exception as e:
        logger.warning(f"Grok text-only fallback failed: {e}")

    try:
        from minimax_executor import execute_with_minimax
        logger.info(f"Falling back to MiniMax for {job_id}/{phase}")
        mm_result = await execute_with_minimax(
            prompt=prompt, job_id=job_id, phase=phase,
            priority=priority, system_prompt=system_prompt,
        )
        if mm_result and mm_result.get("text"):
            return mm_result
    except Exception as e:
        logger.warning(f"MiniMax fallback failed: {e}")

    return {"text": "", "tokens": 0, "tool_calls": [], "cost_usd": 0.0}


# Quick self-test
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    async def test():
        print("=" * 60)
        print("OpenClaw IDE — Multi-Model Self-Test")
        print("=" * 60)

        # Test 1: Claude tool calling (coding task)
        print("\nTest 1: Claude — Read + analyze code...")
        result = await execute_with_ide(
            prompt=(
                "Read the file /root/openclaw/bet_tracker.py and tell me how many "
                "functions it defines. List each function name."
            ),
            job_id="ide-claude-001",
            phase="execute",  # coding phase → Claude
            priority="P1",
        )
        print(f"  Model: {result['model']}")
        print(f"  Tool calls: {len(result['tool_calls'])}")
        print(f"  Cost: ${result['cost_usd']:.6f}")
        print(f"  Response: {result['text'][:300]}")
        if result["tool_calls"]:
            print(f"  Tools used: {[tc['tool'] for tc in result['tool_calls']]}")
            print("  PASS: Claude tool calling works!")
        else:
            print("  WARN: No tool calls")

        # Test 2: Gemini tool calling (analysis task)
        print("\nTest 2: Gemini — Sports analysis...")
        result2 = await execute_with_ide(
            prompt="Use sportsbook_odds with action='sports' to list available sports.",
            job_id="ide-gemini-001",
            phase="plan",  # non-coding → Gemini
            priority="P2",
        )
        print(f"  Model: {result2['model']}")
        print(f"  Tool calls: {len(result2['tool_calls'])}")
        print(f"  Cost: ${result2['cost_usd']:.6f}")
        if result2["tool_calls"]:
            print("  PASS: Gemini tool calling works!")

        # Test 3: Claude CODING task — actually write/edit code
        print("\nTest 3: Claude — Real coding task (write a function)...")
        result3 = await execute_with_ide(
            prompt=(
                "Read /root/openclaw/betting_brain.py. Then use file_edit to add a new function "
                "called `calculate_roi(stake: float, payout: float) -> float` that returns "
                "(payout - stake) / stake * 100. Add it at the end of the file, before any "
                "if __name__ block. Then read the file again to verify the edit."
            ),
            job_id="ide-claude-002",
            phase="execute",
            priority="P0",
        )
        print(f"  Model: {result3['model']}")
        print(f"  Tool calls: {len(result3['tool_calls'])}")
        print(f"  Cost: ${result3['cost_usd']:.6f}")
        print(f"  Tools used: {[tc['tool'] for tc in result3['tool_calls']]}")
        if any(tc["tool"] == "file_edit" for tc in result3["tool_calls"]):
            print("  PASS: Claude wrote actual code via tool calling!")
        elif any(tc["tool"] == "file_write" for tc in result3["tool_calls"]):
            print("  PASS: Claude wrote code via file_write!")
        else:
            print("  WARN: No code-writing tool called")

        total_cost = result["cost_usd"] + result2["cost_usd"] + result3["cost_usd"]
        total_tools = len(result["tool_calls"]) + len(result2["tool_calls"]) + len(result3["tool_calls"])
        print(f"\n{'=' * 60}")
        print(f"Total: {total_tools} tool calls, ${total_cost:.6f}")
        print(f"Models used: {result['model']}, {result2['model']}, {result3['model']}")
        print(f"{'=' * 60}")

    asyncio.run(test())
