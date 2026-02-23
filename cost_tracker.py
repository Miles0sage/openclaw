"""
cost_tracker.py — Single source of truth for cost tracking in OpenClaw.

Extracted from gateway.py (was inline) and autonomous_runner.py (was duplicated).
All cost logging, calculation, and summary functions live here.
"""

import json
import os
import time

# ---------------------------------------------------------------------------
# Pricing table (per million tokens, USD)
# ---------------------------------------------------------------------------
COST_PRICING = {
    "claude-haiku-4-5-20251001":  {"input": 0.8,  "output": 4.0},
    "claude-sonnet-4-20250514":   {"input": 3.0,  "output": 15.0},
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0},
    "claude-3-5-haiku-20241022":  {"input": 0.8,  "output": 4.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0,  "output": 15.0},
    "kimi-2.5":                   {"input": 0.14, "output": 0.28},
    "kimi":                       {"input": 0.27, "output": 0.68},
    "m2.5":                       {"input": 0.30, "output": 1.20},
    "gemini-2.5-flash-lite":      {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash":           {"input": 0.30, "output": 2.50},
    "gemini-3-flash-preview":     {"input": 0.00, "output": 0.00},
}

# Default fallback when a model is not in the table
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Return USD cost for the given token counts."""
    pricing = COST_PRICING.get(model, _DEFAULT_PRICING)
    return round(
        (tokens_in * pricing["input"] + tokens_out * pricing["output"]) / 1_000_000,
        6,
    )


def get_cost_log_path() -> str:
    return os.environ.get(
        "OPENCLAW_COSTS_PATH",
        os.path.join(
            os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data"),
            "costs",
            "costs.jsonl",
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    """Calculate cost without logging."""
    return _calc_cost(model, tokens_input, tokens_output)


def log_cost_event(
    project: str = "openclaw",
    agent: str = "unknown",
    model: str = "unknown",
    tokens_input: int = 0,
    tokens_output: int = 0,
    cost: float = None,
    event_type: str = "api_call",
    metadata: dict = None,
    **kwargs,          # absorb unknown kwargs for compat
) -> float:
    """Calculate (or accept) cost, write a JSONL line, and return the cost."""
    calculated_cost = cost if cost is not None else _calc_cost(model, tokens_input, tokens_output)
    entry = {
        "timestamp": time.time(),
        "type": event_type,
        "project": project,
        "agent": agent,
        "model": model,
        "tokens_in": tokens_input,
        "tokens_out": tokens_output,
        "cost": calculated_cost,
        "metadata": metadata or {},
    }
    cost_path = get_cost_log_path()
    try:
        os.makedirs(os.path.dirname(cost_path), exist_ok=True)
        with open(cost_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    return calculated_cost


def get_cost_metrics() -> dict:
    """Read the cost log and return aggregated metrics."""
    cost_path = get_cost_log_path()
    entries = []
    try:
        with open(cost_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass

    total = sum(e.get("cost", 0) for e in entries)
    by_agent: dict = {}
    for e in entries:
        a = e.get("agent", "unknown")
        by_agent[a] = by_agent.get(a, 0) + e.get("cost", 0)

    return {
        "total_cost":    round(total, 6),
        "entries_count": len(entries),
        "by_agent":      {k: round(v, 6) for k, v in by_agent.items()},
        # Aliases kept for callers that expect these keys
        "daily_total":   round(total, 6),
        "monthly_total": round(total, 6),
        "today_usd":     round(total, 6),
        "month_usd":     round(total, 6),
    }


def get_cost_summary() -> str:
    """One-liner summary string for dashboard/logs."""
    m = get_cost_metrics()
    return f"Total cost: ${m['total_cost']:.4f} across {m['entries_count']} API calls"
