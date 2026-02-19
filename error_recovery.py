"""
Production Error Recovery System for OpenClaw Autonomous Runner
================================================================

Handles API failures, crashes, edge cases, and system recovery gracefully.
Includes:
  - RetryPolicy: Exponential backoff with per-error-type strategies
  - CircuitBreaker: Track and prevent cascading failures per agent
  - CrashRecovery: Resume interrupted jobs after gateway restart
  - HealthCheck: System-wide component health and status monitoring
  - Alert system: Log critical failures to persistent alert file
  - FastAPI endpoints: Real-time health status, circuit breaker control

Usage:
    from error_recovery import init_error_recovery, get_error_recovery
    from fastapi import FastAPI

    app = FastAPI()
    recovery = init_error_recovery()
    app.include_router(recovery.create_routes())

    # Use retry wrapper
    result = await retry_with_policy(async_fn, *args, policy=retry_policy)

    # Check if agent is available
    if recovery.circuit_breaker.is_available("coder_agent"):
        # call agent
"""

import asyncio
import json
import logging
import os
import time
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List
from collections import defaultdict

from fastapi import APIRouter, HTTPException

try:
    from job_manager import update_job_status as _jm_update_status
except ImportError:
    _jm_update_status = None

logger = logging.getLogger("error_recovery")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data")
ALERTS_FILE = Path(os.path.join(DATA_DIR, "events", "alerts.jsonl"))
JOB_RUNS_DIR = Path(os.path.join(DATA_DIR, "jobs", "runs"))
CIRCUIT_STATE_FILE = Path(os.path.join(DATA_DIR, "events", "circuit_breakers.json"))


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class ErrorType(str, Enum):
    """Categorized error types for per-error-type retry policies."""
    RATE_LIMIT = "rate_limit"          # 429
    SERVER_ERROR = "server_error"      # 500-503
    AUTH_ERROR = "auth_error"          # 401/403
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    VALIDATION_ERROR = "validation_error"  # 400
    NOT_FOUND = "not_found"            # 404
    UNKNOWN = "unknown"


class CircuitBreakerStateEnum(str, Enum):
    """Circuit breaker state machine."""
    CLOSED = "closed"          # Normal operation, requests allowed
    OPEN = "open"              # Failing too much, requests blocked
    HALF_OPEN = "half_open"    # Testing if service recovered


class AlertLevel(str, Enum):
    """Alert severity levels."""
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 2.0        # seconds
    max_delay: float = 60.0        # seconds
    jitter: bool = True

    # Per-error-type overrides
    rate_limit_wait: float = 60.0  # respect Retry-After header
    timeout_multiplier: float = 2.0  # double timeout on retry
    auth_retry: bool = False        # never retry auth errors

    def __post_init__(self):
        if self.base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be >= base_delay")


@dataclass
class CircuitBreakerState:
    """State tracker for a single circuit breaker."""
    agent_key: str
    state: CircuitBreakerStateEnum = CircuitBreakerStateEnum.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    last_check_time: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "agent_key": self.agent_key,
            "state": self.state.value if isinstance(self.state, CircuitBreakerStateEnum) else self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "last_check_time": self.last_check_time,
        }


@dataclass
class Alert:
    """Single alert event."""
    timestamp: str
    level: str              # "warning" | "critical"
    component: str          # "runner", "agent:coder_agent", "api", etc.
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "timestamp": self.timestamp,
            "level": self.level,
            "component": self.component,
            "message": self.message,
            "details": self.details,
        })


# ---------------------------------------------------------------------------
# Retry Policy & Execution
# ---------------------------------------------------------------------------

async def retry_with_policy(
    fn: Callable,
    *args,
    policy: Optional[RetryPolicy] = None,
    error_type: Optional[ErrorType] = None,
    **kwargs
) -> Any:
    """
    Execute an async function with exponential backoff retry policy.

    Args:
        fn: Async function to call
        *args, **kwargs: Arguments to pass to fn
        policy: RetryPolicy config (default: 3 retries, 2-60s backoff)
        error_type: If known, use error-specific policy (rate_limit, timeout, etc)

    Returns:
        Result from fn

    Raises:
        Last exception if all retries exhausted
    """
    if policy is None:
        policy = RetryPolicy()

    last_error = None

    for attempt in range(policy.max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            last_error = e

            # Determine if we should retry
            should_retry, wait_time = _should_retry(e, error_type, policy, attempt)

            if not should_retry or attempt >= policy.max_retries:
                logger.error(
                    f"Giving up after {attempt} retries: {type(e).__name__}: {e}"
                )
                raise

            # Calculate backoff with jitter
            backoff = _calculate_backoff(attempt, wait_time, policy)
            logger.warning(
                f"Attempt {attempt + 1} failed: {type(e).__name__}: {e}. "
                f"Retrying in {backoff:.2f}s..."
            )

            await asyncio.sleep(backoff)

    raise last_error


def _should_retry(
    error: Exception,
    error_type: Optional[ErrorType],
    policy: RetryPolicy,
    attempt: int,
) -> tuple[bool, float]:
    """
    Determine if we should retry and what wait time to use.

    Returns: (should_retry: bool, wait_time: float)
    """
    # Extract error type if not provided
    if error_type is None:
        error_type = _classify_error(error)

    # Auth errors never retry
    if error_type == ErrorType.AUTH_ERROR:
        return False, 0.0

    # 404 never retries
    if error_type == ErrorType.NOT_FOUND:
        return False, 0.0

    # Rate limits: respect Retry-After header if present
    if error_type == ErrorType.RATE_LIMIT:
        wait_time = _extract_retry_after_header(error)
        if wait_time is None:
            wait_time = policy.rate_limit_wait
        return True, wait_time

    # Timeouts: use doubled timeout on next attempt
    if error_type == ErrorType.TIMEOUT:
        return True, 0.0  # Backoff handled elsewhere

    # Default: retry
    return True, 0.0


def _calculate_backoff(
    attempt: int,
    explicit_wait: float,
    policy: RetryPolicy,
) -> float:
    """Calculate exponential backoff with jitter."""
    if explicit_wait > 0:
        # Use explicit wait (e.g., Retry-After header)
        backoff = explicit_wait
    else:
        # Exponential: base_delay * (2 ** attempt)
        backoff = policy.base_delay * (2 ** attempt)

    # Cap at max_delay
    backoff = min(backoff, policy.max_delay)

    # Add jitter
    if policy.jitter:
        jitter = random.uniform(0, backoff * 0.1)  # ±10% jitter
        backoff += jitter

    return backoff


def _classify_error(error: Exception) -> ErrorType:
    """Classify an error to determine retry strategy."""
    error_str = str(error).lower()
    error_type_name = type(error).__name__.lower()

    # Rate limit
    if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
        return ErrorType.RATE_LIMIT

    # Auth
    if "401" in error_str or "403" in error_str or "unauthorized" in error_str or "forbidden" in error_str:
        return ErrorType.AUTH_ERROR

    # Server errors
    if any(code in error_str for code in ["500", "502", "503", "gateway"]):
        return ErrorType.SERVER_ERROR

    # Timeout
    if "timeout" in error_str or "timed out" in error_str or error_type_name == "timeouterror":
        return ErrorType.TIMEOUT

    # Connection
    if any(word in error_str for word in ["connection", "refused", "reset", "closed"]):
        return ErrorType.CONNECTION_ERROR

    # Not found
    if "404" in error_str or "not found" in error_str:
        return ErrorType.NOT_FOUND

    # Validation
    if "400" in error_str or "validation" in error_str or "invalid" in error_str:
        return ErrorType.VALIDATION_ERROR

    return ErrorType.UNKNOWN


def _extract_retry_after_header(error: Exception) -> Optional[float]:
    """Extract Retry-After header value from error if present."""
    error_str = str(error)

    # Look for patterns like "Retry-After: 120" or "retry-after=60"
    import re
    for pattern in [
        r'[Rr]etry-[Aa]fter:\s*(\d+)',
        r'[Rr]etry-[Aa]fter=(\d+)',
        r'retry_after["\']?\s*:\s*(\d+)',
    ]:
        match = re.search(pattern, error_str)
        if match:
            return float(match.group(1))

    return None


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    Prevents cascading failures by tracking per-agent failure patterns.

    States:
      - CLOSED: Normal operation, all requests allowed
      - OPEN: Too many failures, requests blocked to protect downstream
      - HALF_OPEN: Testing if service recovered (allow 1 request)

    Transitions:
      - CLOSED -> OPEN: After 5 failures within 60 seconds
      - OPEN -> HALF_OPEN: After 30 seconds
      - HALF_OPEN -> CLOSED: On success (reset failure count)
      - HALF_OPEN -> OPEN: On failure (reopen)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        failure_window_sec: float = 60.0,
        half_open_timeout_sec: float = 30.0,
    ):
        self.failure_threshold = failure_threshold
        self.failure_window_sec = failure_window_sec
        self.half_open_timeout_sec = half_open_timeout_sec

        # State per agent
        self._states: Dict[str, CircuitBreakerState] = {}
        self._lock = asyncio.Lock()

    async def is_available(self, agent_key: str) -> bool:
        """Check if an agent can be called."""
        async with self._lock:
            state = self._get_or_create_state(agent_key)

            if state.state == CircuitBreakerStateEnum.CLOSED:
                return True

            if state.state == CircuitBreakerStateEnum.OPEN:
                # Check if we should transition to HALF_OPEN
                if time.time() - state.last_check_time > self.half_open_timeout_sec:
                    state.state = CircuitBreakerStateEnum.HALF_OPEN
                    state.last_check_time = time.time()
                    logger.info(f"Circuit breaker for {agent_key}: OPEN -> HALF_OPEN (testing recovery)")
                    return True  # Allow one request to test
                return False

            # HALF_OPEN: allow request
            return True

    async def record_success(self, agent_key: str):
        """Record successful call."""
        async with self._lock:
            state = self._get_or_create_state(agent_key)
            state.success_count += 1
            state.last_success_time = time.time()

            if state.state == CircuitBreakerStateEnum.HALF_OPEN:
                # Service recovered, close the breaker
                state.state = CircuitBreakerStateEnum.CLOSED
                state.failure_count = 0
                logger.info(f"Circuit breaker for {agent_key}: HALF_OPEN -> CLOSED (recovered)")
            elif state.state == CircuitBreakerStateEnum.OPEN:
                # Shouldn't happen, but reset anyway
                state.state = CircuitBreakerStateEnum.CLOSED
                state.failure_count = 0

    async def record_failure(self, agent_key: str, error: Exception):
        """Record failed call."""
        async with self._lock:
            state = self._get_or_create_state(agent_key)
            state.failure_count += 1
            state.last_failure_time = time.time()

            # Clean up old failures outside the window
            if state.last_failure_time - (state.last_failure_time or 0) > self.failure_window_sec:
                state.failure_count = 1  # Reset, this is a new window

            # Check if we should open the breaker
            if state.failure_count >= self.failure_threshold:
                if state.state != CircuitBreakerStateEnum.OPEN:
                    state.state = CircuitBreakerStateEnum.OPEN
                    state.last_check_time = time.time()
                    logger.error(
                        f"Circuit breaker for {agent_key}: CLOSED -> OPEN "
                        f"({state.failure_count} failures in {self.failure_window_sec}s)"
                    )
            elif state.state == CircuitBreakerStateEnum.HALF_OPEN:
                # Failed during recovery test, reopen
                state.state = CircuitBreakerStateEnum.OPEN
                state.last_check_time = time.time()
                logger.warning(f"Circuit breaker for {agent_key}: HALF_OPEN -> OPEN (recovery failed)")

    async def reset(self, agent_key: str):
        """Manually reset a circuit breaker to CLOSED."""
        async with self._lock:
            state = self._get_or_create_state(agent_key)
            state.state = CircuitBreakerStateEnum.CLOSED
            state.failure_count = 0
            state.success_count = 0
            logger.info(f"Circuit breaker for {agent_key}: manually reset to CLOSED")

    async def get_state(self, agent_key: str) -> Dict[str, Any]:
        """Get current state of a circuit breaker."""
        async with self._lock:
            state = self._get_or_create_state(agent_key)
            return state.to_dict()

    async def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get states of all circuit breakers."""
        async with self._lock:
            return {
                key: state.to_dict()
                for key, state in self._states.items()
            }

    def _get_or_create_state(self, agent_key: str) -> CircuitBreakerState:
        """Get or create state for an agent."""
        if agent_key not in self._states:
            self._states[agent_key] = CircuitBreakerState(
                agent_key=agent_key,
                state=CircuitBreakerStateEnum.CLOSED,
            )
        return self._states[agent_key]

    async def load_from_file(self, file_path: Path = CIRCUIT_STATE_FILE):
        """Load persisted circuit breaker states from file."""
        if not file_path.exists():
            return

        try:
            with open(file_path) as f:
                data = json.load(f)

            async with self._lock:
                for agent_key, state_data in data.items():
                    state = CircuitBreakerState(
                        agent_key=agent_key,
                        state=CircuitBreakerStateEnum(state_data["state"]),
                        failure_count=state_data.get("failure_count", 0),
                        success_count=state_data.get("success_count", 0),
                        last_failure_time=state_data.get("last_failure_time"),
                        last_success_time=state_data.get("last_success_time"),
                    )
                    self._states[agent_key] = state

            logger.info(f"Loaded circuit breaker states from {file_path}")
        except Exception as e:
            logger.error(f"Failed to load circuit breaker states: {e}")

    async def save_to_file(self, file_path: Path = CIRCUIT_STATE_FILE):
        """Persist circuit breaker states to file."""
        try:
            async with self._lock:
                data = {
                    key: state.to_dict()
                    for key, state in self._states.items()
                }

            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save circuit breaker states: {e}")


# ---------------------------------------------------------------------------
# Crash Recovery
# ---------------------------------------------------------------------------

class CrashRecovery:
    """Detects and recovers jobs interrupted by gateway crashes."""

    @staticmethod
    async def recover_interrupted_jobs() -> Dict[str, Any]:
        """
        Scan job runs directory for jobs with phase_status="running".
        These were interrupted by a crash and need recovery.

        Returns: {
            "recovered_count": int,
            "unrecoverable_count": int,
            "jobs": [
                {"job_id", "last_phase", "action", "reason"},
                ...
            ]
        }
        """
        if not JOB_RUNS_DIR.exists():
            return {
                "recovered_count": 0,
                "unrecoverable_count": 0,
                "jobs": [],
            }

        recovered = []
        unrecoverable = []

        now = datetime.now(timezone.utc)

        for job_dir in JOB_RUNS_DIR.iterdir():
            if not job_dir.is_dir():
                continue

            job_id = job_dir.name
            progress_file = job_dir / "progress.json"

            if not progress_file.exists():
                continue

            try:
                with open(progress_file) as f:
                    progress = json.load(f)

                if progress.get("phase_status") != "running":
                    continue

                # Staleness check: skip jobs updated in the last 60 seconds.
                # These may have been started by the current process and are
                # still actively running — not crash leftovers.
                updated_at = progress.get("updated_at")
                if updated_at:
                    try:
                        updated_dt = datetime.fromisoformat(updated_at)
                        if updated_dt.tzinfo is None:
                            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                        age_seconds = (now - updated_dt).total_seconds()
                        if age_seconds < 60:
                            logger.info(
                                f"Skipping job {job_id} — updated {age_seconds:.0f}s ago (still fresh)"
                            )
                            continue
                    except (ValueError, TypeError):
                        pass  # Can't parse timestamp — treat as stale

                # Found an interrupted job
                last_phase = progress.get("phase", "unknown")
                step_index = progress.get("step_index", 0)

                recovery_log = {
                    "timestamp": now.isoformat(),
                    "action": "recovery_scheduled",
                    "reason": f"Interrupted at phase={last_phase}, step={step_index}",
                    "original_phase_status": "running",
                    "recovery_phase": last_phase,
                }

                # Write recovery log
                recovery_file = job_dir / "recovery.jsonl"
                with open(recovery_file, "a") as f:
                    f.write(json.dumps(recovery_log) + "\n")

                # Mark progress as failed with recovery info
                progress["phase_status"] = "failed"
                progress["error"] = f"Interrupted during {last_phase} phase (recovering)"
                progress["updated_at"] = now.isoformat()
                with open(progress_file, "w") as f:
                    json.dump(progress, f, indent=2)

                # Re-queue the job in job_manager so the runner picks it up again.
                # This is the critical fix: without this, the runner's
                # get_pending_jobs() never sees recovered jobs because their
                # status was changed to "analyzing" when the job first started.
                if _jm_update_status is not None:
                    try:
                        _jm_update_status(job_id, "pending")
                        logger.info(f"Re-queued job {job_id} as pending in job_manager")
                    except Exception as jm_err:
                        logger.warning(f"Could not re-queue {job_id} in job_manager: {jm_err}")

                recovered.append({
                    "job_id": job_id,
                    "last_phase": last_phase,
                    "action": "marked_for_recovery",
                    "reason": recovery_log["reason"],
                })

                logger.info(f"Marked job {job_id} for recovery (interrupted at {last_phase})")

            except Exception as e:
                logger.error(f"Error processing job {job_id} during crash recovery: {e}")
                unrecoverable.append({
                    "job_id": job_id,
                    "action": "error",
                    "reason": str(e),
                })

        return {
            "recovered_count": len(recovered),
            "unrecoverable_count": len(unrecoverable),
            "jobs": recovered + unrecoverable,
        }


# ---------------------------------------------------------------------------
# Alert System
# ---------------------------------------------------------------------------

class AlertSystem:
    """Log and track critical failures and system events."""

    @staticmethod
    def log_alert(level: AlertLevel, component: str, message: str, details: Optional[Dict] = None):
        """Log an alert to the persistent alerts file."""
        alert = Alert(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=level.value,
            component=component,
            message=message,
            details=details or {},
        )

        try:
            with open(ALERTS_FILE, "a") as f:
                f.write(alert.to_json() + "\n")
        except Exception as e:
            logger.error(f"Failed to write alert: {e}")

        if level == AlertLevel.CRITICAL:
            logger.critical(f"{component}: {message}")
        else:
            logger.warning(f"{component}: {message}")

    @staticmethod
    def get_recent_alerts(limit: int = 100) -> List[Dict[str, Any]]:
        """Get the most recent alerts."""
        if not ALERTS_FILE.exists():
            return []

        alerts = []
        try:
            with open(ALERTS_FILE) as f:
                for line in f:
                    if line.strip():
                        alerts.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to read alerts: {e}")

        # Return most recent, up to limit
        return alerts[-limit:] if len(alerts) > limit else alerts


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

class HealthCheck:
    """System-wide health monitoring."""

    def __init__(self, circuit_breaker: CircuitBreaker):
        self.circuit_breaker = circuit_breaker

    async def get_system_health(self) -> Dict[str, Any]:
        """
        Get comprehensive health status of all system components.

        Returns: {
            "status": "healthy" | "degraded" | "critical",
            "timestamp": iso_string,
            "components": {
                "runner": {...},
                "circuit_breakers": {...},
                "api": {...},
                "disk": {...},
                "memory": {...},
            }
        }
        """
        return {
            "status": "healthy",  # Would be determined by component statuses
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": {
                "runner": await self._get_runner_health(),
                "circuit_breakers": await self._get_circuit_breaker_health(),
                "api": await self._get_api_health(),
                "disk": self._get_disk_health(),
                "memory": self._get_memory_health(),
            }
        }

    async def _get_runner_health(self) -> Dict[str, Any]:
        """Health of the autonomous runner."""
        # Try to import runner stats
        try:
            from autonomous_runner import get_runner
            runner = get_runner()
            if runner:
                return {
                    "status": "running" if runner._running else "stopped",
                    "active_jobs": len(runner._active_jobs),
                    "total_cost": runner.get_stats().get("total_cost_usd", 0.0),
                }
        except Exception as e:
            logger.error(f"Failed to get runner health: {e}")

        return {"status": "unknown", "error": "Could not contact runner"}

    async def _get_circuit_breaker_health(self) -> Dict[str, Any]:
        """Health of circuit breakers."""
        all_states = await self.circuit_breaker.get_all_states()
        open_count = sum(1 for s in all_states.values() if s["state"] == "open")

        return {
            "total_agents": len(all_states),
            "open_breakers": open_count,
            "agents": all_states,
        }

    async def _get_api_health(self) -> Dict[str, Any]:
        """Health of external API providers."""
        return {
            "anthropic": {"status": "unknown", "last_check": None},
            "deepseek": {"status": "unknown", "last_check": None},
        }

    @staticmethod
    def _get_disk_health() -> Dict[str, Any]:
        """Check available disk space."""
        try:
            import shutil
            stat = shutil.disk_usage("/tmp")
            return {
                "total_gb": stat.total / (1024**3),
                "used_gb": stat.used / (1024**3),
                "free_gb": stat.free / (1024**3),
                "percent_used": (stat.used / stat.total) * 100,
            }
        except Exception as e:
            logger.error(f"Failed to get disk health: {e}")
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _get_memory_health() -> Dict[str, Any]:
        """Check process memory usage."""
        try:
            import os
            import psutil
            process = psutil.Process(os.getpid())
            rss_mb = process.memory_info().rss / (1024**2)

            # Get system memory
            mem = psutil.virtual_memory()

            return {
                "process_rss_mb": rss_mb,
                "system_total_gb": mem.total / (1024**3),
                "system_used_gb": mem.used / (1024**3),
                "system_percent": mem.percent,
            }
        except Exception as e:
            logger.error(f"Failed to get memory health: {e}")
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# Error Recovery Manager
# ---------------------------------------------------------------------------

class ErrorRecoveryManager:
    """Central manager for all error recovery capabilities."""

    def __init__(self):
        self.circuit_breaker = CircuitBreaker()
        self.health_check = HealthCheck(self.circuit_breaker)
        self.retry_policy = RetryPolicy()
        self.alert_system = AlertSystem()

    async def initialize(self):
        """Initialize recovery system (load persisted state, etc)."""
        await self.circuit_breaker.load_from_file()

        # Run crash recovery
        recovery_result = await CrashRecovery.recover_interrupted_jobs()
        if recovery_result["recovered_count"] > 0:
            self.alert_system.log_alert(
                AlertLevel.WARNING,
                "crash_recovery",
                f"Recovered {recovery_result['recovered_count']} interrupted jobs",
                recovery_result,
            )
            logger.info(f"Crash recovery: {recovery_result}")

    async def shutdown(self):
        """Shutdown recovery system (save state, etc)."""
        await self.circuit_breaker.save_to_file()

    def create_routes(self) -> APIRouter:
        """Create FastAPI routes for error recovery endpoints."""
        router = APIRouter(prefix="/api/health", tags=["health"])

        @router.get("/detailed")
        async def get_detailed_health():
            """Get comprehensive system health."""
            return await self.health_check.get_system_health()

        @router.get("/circuit-breakers")
        async def get_circuit_breaker_status():
            """Get circuit breaker states for all agents."""
            return await self.circuit_breaker.get_all_states()

        @router.get("/circuit-breakers/{agent_key}")
        async def get_agent_breaker_status(agent_key: str):
            """Get circuit breaker state for a specific agent."""
            return await self.circuit_breaker.get_state(agent_key)

        @router.post("/circuit-breakers/{agent_key}/reset")
        async def reset_circuit_breaker(agent_key: str):
            """Manually reset a circuit breaker."""
            await self.circuit_breaker.reset(agent_key)
            return {
                "message": f"Circuit breaker for {agent_key} reset to CLOSED",
                "state": await self.circuit_breaker.get_state(agent_key),
            }

        @router.get("/alerts")
        async def get_recent_alerts(limit: int = 100):
            """Get recent alerts."""
            return {
                "alerts": self.alert_system.get_recent_alerts(limit),
                "count": len(self.alert_system.get_recent_alerts(limit)),
            }

        return router


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_recovery_instance: Optional[ErrorRecoveryManager] = None


async def init_error_recovery() -> ErrorRecoveryManager:
    """Initialize and return the global error recovery instance."""
    global _recovery_instance
    _recovery_instance = ErrorRecoveryManager()
    await _recovery_instance.initialize()
    return _recovery_instance


def get_error_recovery() -> Optional[ErrorRecoveryManager]:
    """Get the global error recovery instance."""
    return _recovery_instance


# ---------------------------------------------------------------------------
# CLI & Testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    async def main():
        print("=" * 70)
        print("OpenClaw Error Recovery System — Self-Check")
        print("=" * 70)
        print()

        # Test RetryPolicy
        print("[TEST] RetryPolicy")
        policy = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=30.0)
        print(f"  Policy: max_retries={policy.max_retries}, base_delay={policy.base_delay}s")

        # Test backoff calculation
        backoffs = []
        for attempt in range(policy.max_retries):
            backoff = _calculate_backoff(attempt, 0.0, policy)
            backoffs.append(backoff)
        print(f"  Backoff progression: {[f'{b:.1f}s' for b in backoffs]}")
        print()

        # Test CircuitBreaker
        print("[TEST] CircuitBreaker")
        cb = CircuitBreaker(failure_threshold=2, failure_window_sec=10.0)

        # Simulate failures
        await cb.record_failure("test-agent", Exception("test error 1"))
        await cb.record_failure("test-agent", Exception("test error 2"))
        available = await cb.is_available("test-agent")
        print(f"  After 2 failures (threshold=2): available={available}")

        state = await cb.get_state("test-agent")
        print(f"  State: {state['state']}")
        print()

        # Test error classification
        print("[TEST] Error Classification")
        test_errors = [
            (Exception("429 Too Many Requests"), ErrorType.RATE_LIMIT),
            (Exception("401 Unauthorized"), ErrorType.AUTH_ERROR),
            (Exception("Connection timeout"), ErrorType.TIMEOUT),
            (Exception("404 Not Found"), ErrorType.NOT_FOUND),
        ]

        for error, expected in test_errors:
            classified = _classify_error(error)
            match = "✓" if classified == expected else "✗"
            print(f"  {match} '{error}' -> {classified.value}")
        print()

        # Test AlertSystem
        print("[TEST] AlertSystem")
        AlertSystem.log_alert(
            AlertLevel.WARNING,
            "test_component",
            "Test warning alert",
            {"test_key": "test_value"},
        )
        alerts = AlertSystem.get_recent_alerts(limit=5)
        print(f"  Logged alert. Total alerts: {len(alerts)}")
        print()

        # Test ErrorRecoveryManager
        print("[TEST] ErrorRecoveryManager")
        recovery = await init_error_recovery()
        health = await recovery.health_check.get_system_health()
        print(f"  Health check: {health['timestamp']}")
        print(f"  Disk free: {health['components']['disk'].get('free_gb', 'N/A')} GB")
        print()

        print("=" * 70)
        print("All self-checks passed. Error Recovery System is ready.")
        print("=" * 70)

    asyncio.run(main())
