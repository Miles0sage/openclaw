"""
Cost Tracker Module for OpenClaw Gateway
Logs API calls and calculates costs in JSONL format
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# Pricing constants (Feb 2026 Claude API rates)
PRICING = {
    "claude-3-5-haiku-20241022": {
        "input": 0.8,      # $0.80 per million input tokens
        "output": 4.0,     # $4.00 per million output tokens
    },
    "claude-3-5-sonnet-20241022": {
        "input": 3.0,      # $3.00 per million input tokens
        "output": 15.0,    # $15.00 per million output tokens
    },
    "claude-opus-4-6": {
        "input": 15.0,     # $15.00 per million input tokens
        "output": 75.0,    # $75.00 per million output tokens
    },
    # Aliases for common references
    "claude-3-5-haiku": {"input": 0.8, "output": 4.0},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-opus": {"input": 15.0, "output": 75.0},
}


def get_cost_log_path() -> str:
    """Get cost log file path from env or default"""
    return os.getenv("OPENCLAW_COST_LOG", "/tmp/openclaw_costs.jsonl")


def get_pricing(model: str) -> Optional[dict]:
    """Get pricing for a model"""
    # Try exact match first
    if model in PRICING:
        return PRICING[model]

    # Try partial match for aliases
    for key, pricing in PRICING.items():
        if key.replace("-", "").lower() in model.replace("-", "").lower():
            return pricing

    # Default to Sonnet pricing
    print(f"⚠️  Unknown model: {model}, defaulting to Sonnet pricing")
    return PRICING["claude-3-5-sonnet-20241022"]


def calculate_cost(model: str, tokens_input: int, tokens_output: int) -> float:
    """Calculate cost for tokens"""
    pricing = get_pricing(model)
    if not pricing:
        pricing = PRICING["claude-3-5-sonnet-20241022"]

    cost = (tokens_input * pricing["input"] + tokens_output * pricing["output"]) / 1_000_000
    return round(cost, 6)


def log_cost_event(
    project: str,
    agent: str,
    model: str,
    tokens_input: int,
    tokens_output: int,
    cost: Optional[float] = None,
) -> float:
    """
    Log a cost event to JSONL file
    Returns: calculated cost (in USD)
    """
    if cost is None:
        cost = calculate_cost(model, tokens_input, tokens_output)

    event = {
        "project": project,
        "agent": agent,
        "model": model,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "cost": round(cost, 6),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    log_path = get_cost_log_path()

    try:
        # Ensure directory exists
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

        # Append to JSONL (newline-delimited JSON)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

        return cost
    except Exception as e:
        print(f"❌ Failed to log cost event: {e}")
        return cost


def read_cost_log() -> list:
    """Read and parse JSONL cost log"""
    log_path = get_cost_log_path()

    if not os.path.exists(log_path):
        return []

    try:
        entries = []
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        print(f"⚠️  Failed to parse cost log line: {line}")

        return entries
    except Exception as e:
        print(f"❌ Failed to read cost log: {e}")
        return []


def get_cost_metrics(time_window: Optional[str] = None) -> dict:
    """Get cost metrics aggregated from log"""
    entries = read_cost_log()

    if not entries:
        return {
            "total_cost": 0.0,
            "by_project": {},
            "by_model": {},
            "by_agent": {},
            "entries_count": 0,
            "timestamp_range": {"first": "", "last": ""},
        }

    # Filter by time window if provided (e.g., "24h", "7d", "30d")
    filtered = entries
    if time_window:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        cutoff = parse_time_window(now, time_window)

        filtered = [
            e
            for e in entries
            if datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) >= cutoff
        ]

    # Aggregate metrics
    metrics = {
        "total_cost": 0.0,
        "by_project": {},
        "by_model": {},
        "by_agent": {},
        "entries_count": len(filtered),
        "timestamp_range": {
            "first": filtered[0]["timestamp"] if filtered else "",
            "last": filtered[-1]["timestamp"] if filtered else "",
        },
    }

    for entry in filtered:
        cost = entry.get("cost", 0.0)
        metrics["total_cost"] += cost
        metrics["by_project"][entry["project"]] = (
            metrics["by_project"].get(entry["project"], 0.0) + cost
        )
        metrics["by_model"][entry["model"]] = (
            metrics["by_model"].get(entry["model"], 0.0) + cost
        )
        metrics["by_agent"][entry["agent"]] = (
            metrics["by_agent"].get(entry["agent"], 0.0) + cost
        )

    # Round all costs to 6 decimal places
    metrics["total_cost"] = round(metrics["total_cost"], 6)
    for key in metrics["by_project"]:
        metrics["by_project"][key] = round(metrics["by_project"][key], 6)
    for key in metrics["by_model"]:
        metrics["by_model"][key] = round(metrics["by_model"][key], 6)
    for key in metrics["by_agent"]:
        metrics["by_agent"][key] = round(metrics["by_agent"][key], 6)

    return metrics


def parse_time_window(now, window: str):
    """Parse time window string to datetime cutoff (expects timezone-aware datetime)"""
    from datetime import timedelta
    import re

    match = re.match(r"^(\d+)([hdm])$", window)
    if not match:
        print(f"⚠️  Invalid time window: {window}, defaulting to 24h")
        return now - timedelta(hours=24)

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "h":
        return now - timedelta(hours=value)
    elif unit == "d":
        return now - timedelta(days=value)
    elif unit == "m":
        return now - timedelta(minutes=value)
    else:
        return now - timedelta(hours=24)


def clear_cost_log() -> bool:
    """Clear all cost data (for testing)"""
    log_path = get_cost_log_path()

    try:
        if os.path.exists(log_path):
            os.remove(log_path)
            print("✅ Cost log cleared")
            return True
        return False
    except Exception as e:
        print(f"❌ Failed to clear cost log: {e}")
        return False


def get_cost_summary() -> str:
    """Get cost summary for debugging"""
    metrics = get_cost_metrics()

    summary = [
        "═" * 50,
        "📊 COST SUMMARY",
        "═" * 50,
        f"Total Cost:  ${metrics['total_cost']:.4f}",
        f"Entries:     {metrics['entries_count']}",
        "",
        "By Project:",
    ]

    for project, cost in sorted(metrics["by_project"].items()):
        summary.append(f"  • {project}: ${cost:.4f}")

    summary.extend(["", "By Model:"])

    for model, cost in sorted(metrics["by_model"].items()):
        summary.append(f"  • {model}: ${cost:.4f}")

    summary.extend(["", "By Agent:"])

    for agent, cost in sorted(metrics["by_agent"].items()):
        summary.append(f"  • {agent}: ${cost:.4f}")

    summary.append("═" * 50)

    return "\n".join(summary)
