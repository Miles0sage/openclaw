"""
Event Engine for OpenClaw Closed-Loop System

Singleton event emission/subscription engine with persistent logging,
Slack notifications, and automatic reaction handlers for job lifecycle events.

Usage:
    from event_engine import get_event_engine, init_event_engine

    engine = init_event_engine()
    engine.subscribe("job.completed", my_handler)
    engine.emit("job.completed", {"job_id": "abc", "agent": "coder_agent"})
"""

import json
import os
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("event_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENT_LOG_PATH = "/tmp/openclaw_events.jsonl"

VALID_EVENT_TYPES = frozenset([
    "job.created",
    "job.completed",
    "job.failed",
    "job.approved",
    "job.timeout",
    "proposal.created",
    "proposal.approved",
    "proposal.rejected",
    "cost.alert",
    "agent.stale",
    "agent.timeout",
])

# Events that trigger a Slack notification
SLACK_NOTIFY_EVENTS = frozenset([
    "job.completed",
    "job.failed",
    "proposal.approved",
    "cost.alert",
    "agent.timeout",
])

GATEWAY_URL = "http://localhost:18789"
SLACK_REPORT_ENDPOINT = f"{GATEWAY_URL}/slack/report/send"

# ---------------------------------------------------------------------------
# Event record helper
# ---------------------------------------------------------------------------


def _make_event_record(event_type: str, data: dict) -> dict:
    """Build a canonical event record with metadata."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# EventEngine
# ---------------------------------------------------------------------------


class EventEngine:
    """Thread-safe event emission and subscription engine with persistent logging."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = threading.Lock()
        self._log_path = EVENT_LOG_PATH
        self._running = True

        # Register built-in subscribers
        self.subscribe("*", self._log_event)
        for evt in SLACK_NOTIFY_EVENTS:
            self.subscribe(evt, self._slack_notify)
        self.subscribe("job.completed", self._reaction_handler)
        self.subscribe("job.failed", self._reaction_handler)

        logger.info("EventEngine initialized with built-in subscribers")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def emit(self, event_type: str, data: dict) -> str:
        """Fire an event to all subscribers. Non-blocking (runs in a thread).

        Returns the generated event_id.
        """
        if event_type not in VALID_EVENT_TYPES:
            logger.warning("Unknown event type: %s (emitting anyway)", event_type)

        record = _make_event_record(event_type, data)
        event_id = record["event_id"]

        thread = threading.Thread(
            target=self._dispatch,
            args=(event_type, record),
            daemon=True,
            name=f"event-{event_type}-{event_id[:8]}",
        )
        thread.start()

        return event_id

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a handler for an event type. Use '*' for all events."""
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)
        logger.debug("Subscribed %s to %s", callback.__name__, event_type)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove a handler for an event type."""
        with self._lock:
            subs = self._subscribers.get(event_type, [])
            try:
                subs.remove(callback)
                logger.debug("Unsubscribed %s from %s", callback.__name__, event_type)
            except ValueError:
                logger.warning(
                    "Callback %s not found for event %s",
                    callback.__name__,
                    event_type,
                )

    def get_recent_events(
        self, limit: int = 50, event_type: Optional[str] = None
    ) -> List[dict]:
        """Read recent events from the persistent log file.

        Returns up to *limit* events, newest first. Optionally filter by
        *event_type*.
        """
        events: List[dict] = []
        if not os.path.exists(self._log_path):
            return events

        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event_type and record.get("event_type") != event_type:
                        continue
                    events.append(record)
        except OSError as exc:
            logger.error("Failed to read event log: %s", exc)
            return events

        # Return newest first, up to limit
        return events[-limit:][::-1]

    def shutdown(self) -> None:
        """Mark engine as shutting down (best-effort; daemon threads will exit)."""
        self._running = False
        logger.info("EventEngine shutting down")

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, event_type: str, record: dict) -> None:
        """Dispatch an event record to all matching subscribers."""
        with self._lock:
            # Gather callbacks for the specific event type + wildcard
            callbacks = list(self._subscribers.get(event_type, []))
            callbacks += list(self._subscribers.get("*", []))

        for cb in callbacks:
            try:
                cb(record)
            except Exception:
                logger.exception(
                    "Subscriber %s raised for %s", cb.__name__, event_type
                )

    # ------------------------------------------------------------------
    # Built-in subscribers
    # ------------------------------------------------------------------

    def _log_event(self, record: dict) -> None:
        """Append every event to the JSONL log file (always registered)."""
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.error("Failed to write event log: %s", exc)

    def _slack_notify(self, record: dict) -> None:
        """POST important events to Slack via the gateway report endpoint."""
        event_type = record.get("event_type", "unknown")
        data = record.get("data", {})
        event_id = record.get("event_id", "n/a")
        ts = record.get("timestamp", "")

        # Build a human-readable summary
        summary = self._format_slack_summary(event_type, data, event_id, ts)

        token = os.environ.get("GATEWAY_AUTH_TOKEN", "")
        if not token:
            logger.debug("GATEWAY_AUTH_TOKEN not set; skipping Slack notify")
            return

        payload = json.dumps({
            "text": summary,
            "event_type": event_type,
            "event_id": event_id,
        }).encode("utf-8")

        req = Request(
            SLACK_REPORT_ENDPOINT,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=5) as resp:
                logger.debug(
                    "Slack notify sent (%s): %d", event_type, resp.status
                )
        except (URLError, OSError) as exc:
            logger.warning("Slack notify failed for %s: %s", event_type, exc)

    def _reaction_handler(self, record: dict) -> None:
        """Automatic reactions to job lifecycle events.

        - job.completed + code task  -> emit proposal.created for "run tests"
        - job.failed                 -> emit proposal.created for "retry with higher priority"
        """
        event_type = record.get("event_type")
        data = record.get("data", {})

        if event_type == "job.completed":
            task_type = data.get("task_type", "")
            job_id = data.get("job_id", data.get("id", "unknown"))
            agent = data.get("agent", "unknown")

            # Only react to code-related tasks
            code_indicators = {"code", "build", "deploy", "implement", "fix", "refactor"}
            if any(kw in task_type.lower() for kw in code_indicators):
                self.emit("proposal.created", {
                    "title": f"Run tests for completed job {job_id}",
                    "description": (
                        f"Agent {agent} completed code task '{task_type}'. "
                        "Proposing automated test run to verify changes."
                    ),
                    "source_event_id": record.get("event_id"),
                    "source_job_id": job_id,
                    "priority": "normal",
                    "proposed_action": "run_tests",
                })
                logger.info("Reaction: proposed test run for job %s", job_id)

        elif event_type == "job.failed":
            job_id = data.get("job_id", data.get("id", "unknown"))
            agent = data.get("agent", "unknown")
            reason = data.get("reason", data.get("error", "unknown error"))

            self.emit("proposal.created", {
                "title": f"Retry failed job {job_id} with higher priority",
                "description": (
                    f"Agent {agent} failed: {reason}. "
                    "Proposing retry with elevated priority."
                ),
                "source_event_id": record.get("event_id"),
                "source_job_id": job_id,
                "priority": "high",
                "proposed_action": "retry",
            })
            logger.info("Reaction: proposed retry for failed job %s", job_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_slack_summary(
        event_type: str, data: dict, event_id: str, ts: str
    ) -> str:
        """Build a concise Slack-friendly text summary for an event."""
        prefix_map = {
            "job.completed": "[OK]",
            "job.failed": "[FAIL]",
            "proposal.approved": "[APPROVED]",
            "cost.alert": "[COST]",
            "agent.timeout": "[TIMEOUT]",
        }
        prefix = prefix_map.get(event_type, "[EVENT]")
        agent = data.get("agent", "system")
        job_id = data.get("job_id", data.get("id", ""))
        detail = data.get("reason", data.get("description", data.get("title", "")))

        parts = [f"{prefix} {event_type}"]
        if agent:
            parts.append(f"agent={agent}")
        if job_id:
            parts.append(f"job={job_id}")
        if detail:
            parts.append(f"| {detail[:120]}")
        parts.append(f"({event_id[:8]})")

        return " ".join(parts)


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_engine_instance: Optional[EventEngine] = None
_engine_lock = threading.Lock()


def init_event_engine() -> EventEngine:
    """Initialize the singleton EventEngine. Safe to call multiple times;
    returns the existing instance if already created."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = EventEngine()
        return _engine_instance


def get_event_engine() -> EventEngine:
    """Return the singleton EventEngine, initializing if needed."""
    if _engine_instance is None:
        return init_event_engine()
    return _engine_instance
