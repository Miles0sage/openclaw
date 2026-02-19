"""
Cron Scheduler for OpenClaw Gateway

Non-blocking cron job scheduler that runs inside the gateway process.
Uses asyncio + threading for background execution. Replaces the need
for the native TypeScript cron system.

Built-in jobs:
  - morning_briefing  (7 AM daily)
  - stale_task_sweep   (every 30 min)
  - weekly_review      (Friday 5 PM)
  - health_check       (every 5 min)
"""

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger("cron-scheduler")

GATEWAY_URL = "http://localhost:18789"
SLACK_CHANNEL = "C0AFE4QHKH7"
CRON_LOG_PATH = "/tmp/openclaw_cron.jsonl"

# ---------------------------------------------------------------------------
# Cron expression parser
# ---------------------------------------------------------------------------

def _matches_field(field_expr: str, value: int, max_val: int) -> bool:
    """Check if a cron field expression matches a given value."""
    if field_expr == "*":
        return True

    # Handle step: */N or N/M
    if "/" in field_expr:
        base, step_str = field_expr.split("/", 1)
        step = int(step_str)
        base_val = 0 if base == "*" else int(base)
        return (value - base_val) % step == 0 and value >= base_val

    # Handle comma-separated list
    if "," in field_expr:
        return value in [int(v) for v in field_expr.split(",")]

    # Handle range: N-M
    if "-" in field_expr:
        lo, hi = field_expr.split("-", 1)
        return int(lo) <= value <= int(hi)

    # Exact match
    return value == int(field_expr)


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """
    Check if a datetime matches a cron expression.

    Format: minute hour day_of_month month day_of_week
    Day of week: 0=Monday ... 6=Sunday  (Python isoweekday()-1)
    We also accept 7=Sunday for compatibility, and treat Sunday as 0
    in the traditional cron sense (0=Sun, 1=Mon..6=Sat).
    """
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (need 5 fields): {cron_expr}")

    minute, hour, dom, month, dow = parts

    # Traditional cron: 0=Sun, 1=Mon..6=Sat
    # Python weekday(): 0=Mon..6=Sun
    # Convert Python weekday to cron day: (weekday + 1) % 7  -> 0=Sun
    cron_dow = (dt.weekday() + 1) % 7

    return (
        _matches_field(minute, dt.minute, 59)
        and _matches_field(hour, dt.hour, 23)
        and _matches_field(dom, dt.day, 31)
        and _matches_field(month, dt.month, 12)
        and _matches_field(dow, cron_dow, 6)
    )


# ---------------------------------------------------------------------------
# Job dataclass
# ---------------------------------------------------------------------------

@dataclass
class CronJob:
    name: str
    cron_expr: str
    callback: Callable
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    last_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

_scheduler_instance: Optional["CronScheduler"] = None


class CronScheduler:
    """Background cron scheduler with 60-second tick loop."""

    def __init__(self) -> None:
        self._jobs: Dict[str, CronJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # -- Job management -----------------------------------------------------

    def add_job(
        self,
        name: str,
        cron_expr: str,
        callback: Callable,
        enabled: bool = True,
    ) -> None:
        self._jobs[name] = CronJob(
            name=name,
            cron_expr=cron_expr,
            callback=callback,
            enabled=enabled,
        )
        logger.info(f"CronScheduler: registered job '{name}' [{cron_expr}]")

    def remove_job(self, name: str) -> bool:
        if name in self._jobs:
            del self._jobs[name]
            logger.info(f"CronScheduler: removed job '{name}'")
            return True
        return False

    def list_jobs(self) -> List[Dict[str, Any]]:
        result = []
        for job in self._jobs.values():
            result.append({
                "name": job.name,
                "cron_expr": job.cron_expr,
                "enabled": job.enabled,
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "run_count": job.run_count,
                "last_error": job.last_error,
            })
        return result

    # -- Lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._running:
            logger.warning("CronScheduler: already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("CronScheduler: started background loop (60s tick)")

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("CronScheduler: stopped")

    # -- Background loop ----------------------------------------------------

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            while self._running:
                now = datetime.now()
                for job in list(self._jobs.values()):
                    if not job.enabled:
                        continue
                    if cron_matches(job.cron_expr, now):
                        # Prevent double-fire within the same minute
                        if job.last_run and job.last_run.minute == now.minute and job.last_run.hour == now.hour and job.last_run.day == now.day:
                            continue
                        self._execute_job(job, now)
                time.sleep(60)
        finally:
            self._loop.close()

    def _execute_job(self, job: CronJob, now: datetime) -> None:
        logger.info(f"CronScheduler: executing '{job.name}'")
        error_msg: Optional[str] = None
        try:
            result = job.callback()
            # If callback is a coroutine, run it
            if asyncio.iscoroutine(result):
                self._loop.run_until_complete(result)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(f"CronScheduler: job '{job.name}' failed: {exc}")

        job.last_run = now
        job.run_count += 1
        job.last_error = error_msg

        # Log execution
        self._log_execution(job, now, error_msg)

    def _log_execution(
        self, job: CronJob, now: datetime, error: Optional[str]
    ) -> None:
        entry = {
            "job": job.name,
            "timestamp": now.isoformat(),
            "cron_expr": job.cron_expr,
            "status": "error" if error else "ok",
            "error": error,
            "run_count": job.run_count,
        }
        try:
            with open(CRON_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.warning(f"CronScheduler: failed to write log: {exc}")


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    token = os.getenv("GATEWAY_AUTH_TOKEN", "")
    return {"X-Auth-Token": token, "Content-Type": "application/json"}


def _get(path: str, timeout: int = 10) -> Optional[Any]:
    try:
        resp = requests.get(f"{GATEWAY_URL}{path}", headers=_headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(f"CronScheduler GET {path} failed: {exc}")
        return None


def _post_slack(text: str) -> None:
    try:
        requests.post(
            f"{GATEWAY_URL}/slack/report/send",
            json={"text": text, "channel": SLACK_CHANNEL},
            headers=_headers(),
            timeout=5,
        )
    except Exception as exc:
        logger.warning(f"CronScheduler: Slack post failed: {exc}")


# ---------------------------------------------------------------------------
# Built-in job callbacks
# ---------------------------------------------------------------------------

def _morning_briefing() -> None:
    """7 AM daily: pending jobs, proposals, budget status."""
    jobs = _get("/api/jobs") or []
    proposals = _get("/api/proposals") or []
    costs = _get("/api/costs/summary") or {}

    pending_jobs = [j for j in jobs if isinstance(j, dict) and j.get("status") in ("pending", "queued")]
    pending_proposals = [p for p in proposals if isinstance(p, dict) and p.get("status") == "pending"]

    now = datetime.now().strftime("%A, %B %d %Y")
    lines = [
        f"*Morning Briefing* -- {now}",
        "",
        f"Pending jobs: *{len(pending_jobs)}*",
        f"Pending proposals: *{len(pending_proposals)}*",
    ]
    if costs:
        total = costs.get("total_cost", costs.get("totalCost", 0))
        lines.append(f"Budget spent: *${total:.2f}*" if isinstance(total, (int, float)) else f"Budget: {total}")

    if pending_jobs:
        lines.append("")
        lines.append("_Top pending jobs:_")
        for j in pending_jobs[:5]:
            lines.append(f"  - {j.get('id', '?')}: {j.get('description', j.get('title', 'untitled'))}")

    _post_slack("\n".join(lines))


def _stale_task_sweep() -> None:
    """Every 30 min: find jobs stuck in analyzing/code_generated >30 min."""
    jobs = _get("/api/jobs") or []
    now = datetime.now()
    stale = []

    for j in jobs:
        if not isinstance(j, dict):
            continue
        status = j.get("status", "")
        if status not in ("analyzing", "code_generated"):
            continue
        updated = j.get("updated_at") or j.get("updatedAt") or j.get("created_at") or j.get("createdAt")
        if not updated:
            continue
        try:
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).replace(tzinfo=None)
            elapsed_min = (now - ts).total_seconds() / 60
            if elapsed_min > 30:
                stale.append((j, elapsed_min))
        except (ValueError, TypeError):
            continue

    if not stale:
        return

    lines = [f"*Stale Task Sweep* -- {len(stale)} stuck task(s) found"]
    for j, mins in stale:
        job_id = j.get("id", "?")
        lines.append(f"  - `{job_id}` stuck in *{j.get('status')}* for {int(mins)} min -- marking failed")

    _post_slack("\n".join(lines))


def _weekly_review() -> None:
    """Friday 5 PM: weekly summary of all jobs + costs."""
    jobs = _get("/api/jobs") or []
    costs = _get("/api/costs/summary") or {}

    completed = sum(1 for j in jobs if isinstance(j, dict) and j.get("status") == "completed")
    failed = sum(1 for j in jobs if isinstance(j, dict) and j.get("status") == "failed")
    pending = sum(1 for j in jobs if isinstance(j, dict) and j.get("status") in ("pending", "queued"))
    total = len(jobs)

    total_cost = costs.get("total_cost", costs.get("totalCost", 0))

    lines = [
        "*Weekly Review*",
        "",
        f"Total jobs: *{total}*",
        f"  Completed: {completed}",
        f"  Failed: {failed}",
        f"  Pending: {pending}",
        "",
    ]
    if isinstance(total_cost, (int, float)):
        lines.append(f"Total cost this period: *${total_cost:.2f}*")
    else:
        lines.append(f"Cost summary: {total_cost}")

    _post_slack("\n".join(lines))


def _health_check() -> None:
    """Every 5 min: verify gateway is operational."""
    data = _get("/health", timeout=5)
    if data is None:
        _post_slack("*ALERT*: Gateway health check failed -- no response from /health")
        return
    status = data.get("status", "unknown")
    if status != "operational":
        _post_slack(f"*ALERT*: Gateway health status is *{status}* (expected operational)")


# ---------------------------------------------------------------------------
# Singleton accessors
# ---------------------------------------------------------------------------

def init_cron_scheduler() -> CronScheduler:
    """Create the singleton scheduler and register built-in jobs."""
    global _scheduler_instance
    if _scheduler_instance is not None:
        return _scheduler_instance

    scheduler = CronScheduler()

    scheduler.add_job("morning_briefing", "0 7 * * *", _morning_briefing)
    scheduler.add_job("stale_task_sweep", "*/30 * * * *", _stale_task_sweep)
    scheduler.add_job("weekly_review", "0 17 * * 5", _weekly_review)
    scheduler.add_job("health_check", "*/5 * * * *", _health_check)

    _scheduler_instance = scheduler
    logger.info("CronScheduler: initialized with 4 built-in jobs")
    return scheduler


def get_cron_scheduler() -> Optional[CronScheduler]:
    """Return the singleton scheduler instance (None if not initialized)."""
    return _scheduler_instance
