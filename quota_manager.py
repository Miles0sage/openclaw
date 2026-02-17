"""
Quota Manager for OpenClaw Gateway
Enforces daily/monthly spend limits and queue size limits
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from cost_tracker import get_cost_metrics, read_cost_log


def load_quota_config() -> dict:
    """Load quota configuration from config.json"""
    config_path = os.getenv("OPENCLAW_CONFIG", "/root/openclaw/config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            return config.get("quotas", {
                "enabled": False,
                "daily_limit_usd": 50,
                "monthly_limit_usd": 1000,
                "max_queue_size": 100,
                "per_project": {},
                "warning_threshold_percent": 80,
            })
    except Exception as e:
        print(f"⚠️  Failed to load quota config: {e}, using defaults")
        return {
            "enabled": False,
            "daily_limit_usd": 50,
            "monthly_limit_usd": 1000,
            "max_queue_size": 100,
            "per_project": {},
            "warning_threshold_percent": 80,
        }


def get_project_quota(project_id: str) -> dict:
    """Get quota limits for a specific project"""
    quota_config = load_quota_config()

    # Check if project has custom quotas
    if project_id in quota_config.get("per_project", {}):
        project_quota = quota_config["per_project"][project_id]
        return {
            "daily_limit_usd": project_quota.get("daily_limit_usd", quota_config["daily_limit_usd"]),
            "monthly_limit_usd": project_quota.get("monthly_limit_usd", quota_config["monthly_limit_usd"]),
        }

    # Use global defaults
    return {
        "daily_limit_usd": quota_config["daily_limit_usd"],
        "monthly_limit_usd": quota_config["monthly_limit_usd"],
    }


def get_project_spend(project_id: str, time_window: str = "24h") -> float:
    """Get total spend for a project in given time window"""
    try:
        metrics = get_cost_metrics(time_window)
        return metrics.get("by_project", {}).get(project_id, 0.0)
    except Exception as e:
        print(f"❌ Failed to get project spend: {e}")
        return 0.0


def check_daily_quota(project_id: str) -> Tuple[bool, Optional[str]]:
    """
    Check if project is within daily quota
    Returns: (is_within_quota, error_message)
    """
    quota_config = load_quota_config()

    if not quota_config.get("enabled", False):
        return (True, None)

    quota = get_project_quota(project_id)
    daily_limit = quota["daily_limit_usd"]
    current_spend = get_project_spend(project_id, "24h")

    if current_spend >= daily_limit:
        error_msg = (
            f"❌ Daily quota exceeded for project '{project_id}'. "
            f"Current: ${current_spend:.2f}, Limit: ${daily_limit:.2f}. "
            f"Try again in 24 hours or contact support."
        )
        return (False, error_msg)

    # Check warning threshold
    threshold_percent = quota_config.get("warning_threshold_percent", 80)
    warning_threshold = (daily_limit * threshold_percent) / 100
    if current_spend >= warning_threshold:
        print(f"⚠️  Daily quota warning for '{project_id}': ${current_spend:.2f}/${daily_limit:.2f} ({(current_spend/daily_limit)*100:.1f}%)")

    return (True, None)


def check_monthly_quota(project_id: str) -> Tuple[bool, Optional[str]]:
    """
    Check if project is within monthly quota
    Returns: (is_within_quota, error_message)
    """
    quota_config = load_quota_config()

    if not quota_config.get("enabled", False):
        return (True, None)

    quota = get_project_quota(project_id)
    monthly_limit = quota["monthly_limit_usd"]
    current_spend = get_project_spend(project_id, "30d")

    if current_spend >= monthly_limit:
        error_msg = (
            f"❌ Monthly quota exceeded for project '{project_id}'. "
            f"Current: ${current_spend:.2f}, Limit: ${monthly_limit:.2f}. "
            f"Contact support for a quota increase."
        )
        return (False, error_msg)

    # Check warning threshold
    threshold_percent = quota_config.get("warning_threshold_percent", 80)
    warning_threshold = (monthly_limit * threshold_percent) / 100
    if current_spend >= warning_threshold:
        print(f"⚠️  Monthly quota warning for '{project_id}': ${current_spend:.2f}/${monthly_limit:.2f} ({(current_spend/monthly_limit)*100:.1f}%)")

    return (True, None)


def check_queue_size(current_queue_size: int) -> Tuple[bool, Optional[str]]:
    """
    Check if queue is within size limits
    Returns: (is_within_quota, error_message)
    """
    quota_config = load_quota_config()

    if not quota_config.get("enabled", False):
        return (True, None)

    max_queue = quota_config.get("max_queue_size", 100)

    if current_queue_size >= max_queue:
        error_msg = (
            f"❌ Queue is full. Current size: {current_queue_size}, Max: {max_queue}. "
            f"Please wait for in-progress requests to complete."
        )
        return (False, error_msg)

    # Check warning threshold
    threshold_percent = quota_config.get("warning_threshold_percent", 80)
    warning_threshold = (max_queue * threshold_percent) / 100
    if current_queue_size >= warning_threshold:
        print(f"⚠️  Queue size warning: {current_queue_size}/{max_queue} ({(current_queue_size/max_queue)*100:.1f}%)")

    return (True, None)


def check_all_quotas(project_id: str, queue_size: int = 0) -> Tuple[bool, Optional[str]]:
    """
    Check all quota limits (daily, monthly, queue)
    Returns: (is_within_quotas, error_message)
    """
    quota_config = load_quota_config()

    if not quota_config.get("enabled", False):
        return (True, None)

    # Check daily quota
    daily_ok, daily_error = check_daily_quota(project_id)
    if not daily_ok:
        return (False, daily_error)

    # Check monthly quota
    monthly_ok, monthly_error = check_monthly_quota(project_id)
    if not monthly_ok:
        return (False, monthly_error)

    # Check queue size
    if queue_size > 0:
        queue_ok, queue_error = check_queue_size(queue_size)
        if not queue_ok:
            return (False, queue_error)

    return (True, None)


def get_quota_status(project_id: str) -> dict:
    """Get current quota status for a project"""
    quota_config = load_quota_config()

    if not quota_config.get("enabled", False):
        return {
            "quotas_enabled": False,
            "message": "Quotas are disabled"
        }

    quota = get_project_quota(project_id)
    daily_spend = get_project_spend(project_id, "24h")
    monthly_spend = get_project_spend(project_id, "30d")

    daily_pct = (daily_spend / quota["daily_limit_usd"] * 100) if quota["daily_limit_usd"] > 0 else 0
    monthly_pct = (monthly_spend / quota["monthly_limit_usd"] * 100) if quota["monthly_limit_usd"] > 0 else 0

    return {
        "quotas_enabled": True,
        "project": project_id,
        "daily": {
            "spend": round(daily_spend, 4),
            "limit": quota["daily_limit_usd"],
            "percent": round(daily_pct, 1),
            "remaining": round(quota["daily_limit_usd"] - daily_spend, 4),
        },
        "monthly": {
            "spend": round(monthly_spend, 4),
            "limit": quota["monthly_limit_usd"],
            "percent": round(monthly_pct, 1),
            "remaining": round(quota["monthly_limit_usd"] - monthly_spend, 4),
        },
    }
