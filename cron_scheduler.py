"""
Cron Scheduler for OpenClaw Gateway

Non-blocking cron job scheduler that runs inside the gateway process.
Uses asyncio + threading for background execution. Replaces the need
for the native TypeScript cron system.

Built-in jobs:
  - morning_briefing   (7 AM daily)
  - stale_task_sweep    (every 30 min)
  - weekly_review       (Friday 5 PM)
  - health_check        (every 5 min)
  - cost_alert          (every hour)
"""

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger("cron-scheduler")

GATEWAY_URL = "http://localhost:18789"
SLACK_CHANNEL = "C0AFE4QHKH7"
CRON_LOG_PATH = "/tmp/openclaw_cron.jsonl"
JOBS_FILE = Path("/tmp/openclaw_jobs/jobs.jsonl")
COST_LOG_PATH = "/tmp/openclaw_costs.jsonl"
DAILY_BUDGET_LIMIT = 20.0  # $20/day
COST_ALERT_THRESHOLD = 0.80  # 80% of daily limit

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

def _read_jobs_file() -> List[Dict[str, Any]]:
    """Read jobs directly from the JSONL file on disk."""
    if not JOBS_FILE.exists():
        return []
    jobs = []
    try:
        with open(JOBS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        jobs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        pass
    return jobs


def _read_todays_costs() -> float:
    """Sum today's costs from the cost log file."""
    if not os.path.exists(COST_LOG_PATH):
        return 0.0
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    total = 0.0
    try:
        with open(COST_LOG_PATH, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    if ts.startswith(today_str):
                        total += entry.get("cost", 0.0)
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        pass
    return round(total, 4)


def _morning_briefing() -> None:
    """7 AM daily: real briefing with jobs, stale tasks, costs, health."""
    now = datetime.now()
    now_str = now.strftime("%A, %B %d %Y")

    # --- Jobs analysis ---
    jobs = _read_jobs_file()
    pending = [j for j in jobs if j.get("status") in ("pending", "queued")]
    analyzing = [j for j in jobs if j.get("status") in ("analyzing", "code_generated")]
    completed_today = []
    failed_today = []
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    for j in jobs:
        completed_at = j.get("completed_at", "")
        if completed_at and completed_at.startswith(today_str):
            if j.get("status") in ("done", "merged", "approved"):
                completed_today.append(j)
            elif j.get("status") == "failed":
                failed_today.append(j)

    # --- Stale detection ---
    stale_count = 0
    for j in analyzing:
        updated = j.get("updated_at") or j.get("created_at", "")
        if updated:
            try:
                ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).replace(tzinfo=None)
                if (now - ts).total_seconds() > 1800:
                    stale_count += 1
            except (ValueError, TypeError):
                pass

    # --- Costs ---
    daily_cost = _read_todays_costs()
    budget_pct = (daily_cost / DAILY_BUDGET_LIMIT * 100) if DAILY_BUDGET_LIMIT > 0 else 0

    # --- Proposals ---
    proposals = _get("/api/proposals") or []
    pending_proposals = [p for p in proposals if isinstance(p, dict) and p.get("status") == "pending"]

    # --- Health ---
    health_data = _get("/health", timeout=5)
    health_status = "OK" if health_data and health_data.get("status") == "operational" else "DEGRADED"

    # --- Build briefing ---
    lines = [
        f"*Morning Briefing* -- {now_str}",
        "",
        f"Gateway: *{health_status}*",
        "",
        "*Job Queue:*",
        f"  Pending: *{len(pending)}*  |  In-Progress: *{len(analyzing)}*  |  Stale: *{stale_count}*",
        f"  Completed today: *{len(completed_today)}*  |  Failed today: *{len(failed_today)}*",
        f"  Total all-time: *{len(jobs)}*",
        "",
        f"*Budget:* ${daily_cost:.2f} / ${DAILY_BUDGET_LIMIT:.2f} ({budget_pct:.0f}% used)",
    ]

    if budget_pct >= 80:
        lines.append(f"  :warning: Daily budget at {budget_pct:.0f}% -- slow down or switch to Kimi")

    if pending_proposals:
        lines.append("")
        lines.append(f"*Pending Proposals:* {len(pending_proposals)}")
        for p in pending_proposals[:3]:
            lines.append(f"  - {p.get('title', p.get('id', '?'))}")

    if stale_count > 0:
        lines.append("")
        lines.append(f":warning: *{stale_count} stale task(s)* stuck >30 min -- sweep will auto-fail them")

    if pending:
        lines.append("")
        lines.append("_Top pending jobs:_")
        for j in pending[:5]:
            lines.append(f"  - `{j.get('id', '?')}`: {j.get('task', j.get('description', 'untitled'))}")

    _post_slack("\n".join(lines))


def _stale_task_sweep() -> None:
    """Every 30 min: read jobs.jsonl, find stuck jobs, auto-fail them, notify Slack."""
    if not JOBS_FILE.exists():
        return

    now = datetime.utcnow()
    stale_threshold_min = 30
    jobs = []
    stale = []
    modified = False

    # Read all jobs
    try:
        with open(JOBS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    jobs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning(f"stale_task_sweep: cannot read jobs file: {exc}")
        return

    # Check each job for staleness
    for j in jobs:
        status = j.get("status", "")
        if status not in ("analyzing", "code_generated", "pending"):
            continue

        # Use updated_at or created_at to determine age
        updated = j.get("updated_at") or j.get("created_at", "")
        if not updated:
            continue

        try:
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).replace(tzinfo=None)
            elapsed_min = (now - ts).total_seconds() / 60
        except (ValueError, TypeError):
            continue

        if elapsed_min > stale_threshold_min:
            stale.append((j, elapsed_min))
            # Auto-fail the job
            j["status"] = "failed"
            j["updated_at"] = now.isoformat()
            j["failure_reason"] = f"Auto-failed by stale_task_sweep: stuck for {int(elapsed_min)} min"
            modified = True

            # Emit event if event engine available
            try:
                from event_engine import get_event_engine
                engine = get_event_engine()
                engine.emit("job.failed", {
                    "job_id": j.get("id", "unknown"),
                    "agent": j.get("agent", "unknown"),
                    "reason": j["failure_reason"],
                    "task_type": j.get("task", ""),
                    "auto_sweep": True,
                })
            except Exception:
                pass

    # Rewrite jobs file if we modified anything
    if modified:
        try:
            with open(JOBS_FILE, "w") as f:
                for j in jobs:
                    f.write(json.dumps(j) + "\n")
        except OSError as exc:
            logger.error(f"stale_task_sweep: failed to rewrite jobs file: {exc}")

    if not stale:
        return

    lines = [f"*Stale Task Sweep* -- {len(stale)} stuck task(s) auto-failed"]
    for j, mins in stale:
        job_id = j.get("id", "?")
        task = j.get("task", j.get("description", "untitled"))[:60]
        lines.append(f"  - `{job_id}` was *{j.get('status', '?')}* for {int(mins)} min -> *failed*  ({task})")

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


# Track health check state to avoid spamming Slack on repeated failures
_health_state = {"consecutive_failures": 0, "last_alert_time": None, "alert_cooldown_min": 15}


def _health_check() -> None:
    """Every 5 min: hit /health, report to Slack only on state change or degradation."""
    global _health_state

    now = datetime.now()
    data = _get("/health", timeout=5)

    if data is None:
        _health_state["consecutive_failures"] += 1
        fail_count = _health_state["consecutive_failures"]

        # Only alert on first failure, then every 15 min (3 checks)
        last_alert = _health_state.get("last_alert_time")
        cooldown = _health_state["alert_cooldown_min"]
        should_alert = (
            fail_count == 1
            or last_alert is None
            or (now - last_alert).total_seconds() > cooldown * 60
        )
        if should_alert:
            _post_slack(
                f":red_circle: *ALERT*: Gateway health check failed "
                f"({fail_count} consecutive failure{'s' if fail_count > 1 else ''}). "
                f"No response from /health."
            )
            _health_state["last_alert_time"] = now

            # Emit event
            try:
                from event_engine import get_event_engine
                get_event_engine().emit("agent.timeout", {
                    "agent": "gateway",
                    "reason": f"Health check unreachable ({fail_count}x)",
                })
            except Exception:
                pass
        return

    status = data.get("status", "unknown")

    # If we were in failure state and recovered, notify
    if _health_state["consecutive_failures"] > 0:
        _post_slack(
            f":large_green_circle: *RECOVERED*: Gateway health check passed after "
            f"{_health_state['consecutive_failures']} failure(s). Status: *{status}*"
        )
        _health_state["consecutive_failures"] = 0
        _health_state["last_alert_time"] = None
        return

    _health_state["consecutive_failures"] = 0

    if status != "operational":
        _post_slack(
            f":warning: *DEGRADED*: Gateway health status is *{status}* (expected operational)"
        )
        try:
            from event_engine import get_event_engine
            get_event_engine().emit("agent.stale", {
                "agent": "gateway",
                "reason": f"Health status: {status}",
            })
        except Exception:
            pass


# Track cost alert state to avoid duplicate alerts within same hour
_cost_alert_state = {"last_alert_hour": None, "last_alert_pct": 0}


def _cost_alert() -> None:
    """Hourly: check if daily spend > 80% of $20 limit, post to Slack."""
    global _cost_alert_state

    daily_cost = _read_todays_costs()
    budget_pct = (daily_cost / DAILY_BUDGET_LIMIT * 100) if DAILY_BUDGET_LIMIT > 0 else 0
    current_hour = datetime.utcnow().strftime("%Y-%m-%d-%H")

    # Skip if we already alerted this hour at the same severity tier
    tier = 0
    if budget_pct >= 100:
        tier = 3
    elif budget_pct >= 90:
        tier = 2
    elif budget_pct >= COST_ALERT_THRESHOLD * 100:
        tier = 1

    if tier == 0:
        return  # Under threshold, no alert

    # Only alert if tier escalated or new hour
    last_hour = _cost_alert_state.get("last_alert_hour")
    last_tier = _cost_alert_state.get("last_alert_pct", 0)
    if last_hour == current_hour and last_tier >= tier:
        return

    _cost_alert_state["last_alert_hour"] = current_hour
    _cost_alert_state["last_alert_pct"] = tier

    # Build cost breakdown by reading the cost log
    by_agent = {}
    by_model = {}
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        if os.path.exists(COST_LOG_PATH):
            with open(COST_LOG_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts = entry.get("timestamp", "")
                        if ts.startswith(today_str):
                            cost = entry.get("cost", 0.0)
                            agent = entry.get("agent", "unknown")
                            model = entry.get("model", "unknown")
                            by_agent[agent] = by_agent.get(agent, 0.0) + cost
                            by_model[model] = by_model.get(model, 0.0) + cost
                    except (json.JSONDecodeError, TypeError):
                        continue
    except OSError:
        pass

    if budget_pct >= 100:
        icon = ":rotating_light:"
        severity = "BUDGET EXCEEDED"
    elif budget_pct >= 90:
        icon = ":red_circle:"
        severity = "CRITICAL"
    else:
        icon = ":warning:"
        severity = "WARNING"

    lines = [
        f"{icon} *Cost Alert ({severity})* -- ${daily_cost:.2f} / ${DAILY_BUDGET_LIMIT:.2f} ({budget_pct:.0f}%)",
    ]

    if by_agent:
        lines.append("")
        lines.append("_Spend by agent:_")
        for agent, cost in sorted(by_agent.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {agent}: ${cost:.4f}")

    if by_model:
        lines.append("")
        lines.append("_Spend by model:_")
        for model, cost in sorted(by_model.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {model}: ${cost:.4f}")

    if budget_pct >= 90:
        lines.append("")
        lines.append("_Recommendation:_ Route all tasks to Kimi until tomorrow's budget reset.")

    _post_slack("\n".join(lines))

    # Emit cost event
    try:
        from event_engine import get_event_engine
        get_event_engine().emit("cost.threshold_exceeded", {
            "daily_cost": daily_cost,
            "daily_limit": DAILY_BUDGET_LIMIT,
            "percent_used": round(budget_pct, 1),
            "severity": severity,
        })
    except Exception:
        pass


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
    scheduler.add_job("cost_alert", "0 * * * *", _cost_alert)

    _scheduler_instance = scheduler
    logger.info("CronScheduler: initialized with 5 built-in jobs")
    return scheduler


def get_cron_scheduler() -> Optional[CronScheduler]:
    """Return the singleton scheduler instance (None if not initialized)."""
    return _scheduler_instance
