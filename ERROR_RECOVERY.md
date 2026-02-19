# OpenClaw Error Recovery System

Production-grade error handling and recovery system for the autonomous runner. Handles API failures, crashes, cascading failures, and system degradation gracefully.

## Overview

The error recovery system consists of five integrated components:

1. **RetryPolicy** — Intelligent retry with exponential backoff and per-error-type strategies
2. **CircuitBreaker** — Prevent cascading failures by tracking per-agent health
3. **CrashRecovery** — Resume interrupted jobs after gateway crashes
4. **AlertSystem** — Log critical failures and system events
5. **HealthCheck** — Comprehensive system monitoring and diagnostics
6. **ErrorRecoveryManager** — Central coordinator with FastAPI endpoints

## Components

### 1. RetryPolicy

Configurable retry strategy with exponential backoff and per-error-type handling.

#### Features

- **Exponential backoff**: `base_delay * (2 ** attempt)` with jitter
- **Per-error-type strategies**:
  - **Rate limit (429)**: Respects `Retry-After` header or default 60s wait
  - **Server errors (500-503)**: Retries with exponential backoff
  - **Auth errors (401/403)**: Never retries, escalates immediately
  - **Timeouts**: Retries once with doubled timeout
  - **Not found (404)**: Never retries, fails immediately
  - **Validation errors (400)**: Retries once, then fails
  - **Connection errors**: Retries with exponential backoff

#### Usage

```python
from error_recovery import retry_with_policy, RetryPolicy, ErrorType

# Use default policy (3 retries, 2-60s backoff)
result = await retry_with_policy(api_call_fn, arg1, arg2)

# Custom policy
policy = RetryPolicy(
    max_retries=5,
    base_delay=1.0,      # seconds
    max_delay=120.0,
    jitter=True,
)
result = await retry_with_policy(api_call_fn, arg1, arg2, policy=policy)

# Error type hints for better strategy selection
result = await retry_with_policy(
    api_call_fn,
    policy=policy,
    error_type=ErrorType.RATE_LIMIT,  # Use rate limit strategy
)
```

#### Backoff Examples

```
Attempt 0: 2.0s + jitter
Attempt 1: 4.0s + jitter
Attempt 2: 8.0s + jitter
Attempt 3: 16.0s + jitter (capped at max_delay=60s)
```

### 2. CircuitBreaker

Prevents cascading failures by tracking agent health and blocking calls to failing services.

#### States

```
       5 failures in 60s
              ↓
CLOSED ──────────────→ OPEN
 ↑                      │
 │         30s timeout   ↓
 └──────← HALF_OPEN ←───┘
       (test 1 call)

       Success         Failure
         ↓              ↓
      CLOSED          OPEN
```

#### Usage

```python
from error_recovery import CircuitBreaker

cb = CircuitBreaker(
    failure_threshold=5,          # Open after 5 failures
    failure_window_sec=60.0,      # Within 60 seconds
    half_open_timeout_sec=30.0,   # Wait 30s before testing recovery
)

# Check if agent is available
if await cb.is_available("coder_agent"):
    result = await call_agent("coder_agent")
    await cb.record_success("coder_agent")
else:
    # Use fallback agent or queue for retry
    await use_fallback_agent()

# On error
except Exception as e:
    await cb.record_failure("coder_agent", e)

# Manual reset (emergency only)
await cb.reset("coder_agent")

# Check status
state = await cb.get_state("coder_agent")
print(state)  # {"agent_key": "coder_agent", "state": "open", "failure_count": 5, ...}
```

#### State Transitions

1. **CLOSED → OPEN**: After 5 consecutive failures within 60s
2. **OPEN → HALF_OPEN**: After 30s timeout
3. **HALF_OPEN → CLOSED**: Success on test call (failure count resets)
4. **HALF_OPEN → OPEN**: Failure on test call (reopen immediately)

### 3. CrashRecovery

Detects jobs interrupted by gateway crashes and marks them for recovery.

#### How It Works

1. On startup, scans `/tmp/openclaw_job_runs/` for jobs with `phase_status: "running"`
2. These jobs were interrupted by a crash (e.g., deployment, hardware failure)
3. Marks them as "failed" with recovery information
4. Autonomous runner detects failed status and retries the entire job
5. Runner can optionally resume from last completed phase (future enhancement)

#### Usage

```python
from error_recovery import CrashRecovery

# Run on gateway startup
recovery_result = await CrashRecovery.recover_interrupted_jobs()

print(recovery_result)
# {
#     "recovered_count": 3,
#     "unrecoverable_count": 0,
#     "jobs": [
#         {
#             "job_id": "job-001",
#             "last_phase": "execute",
#             "action": "marked_for_recovery",
#             "reason": "Interrupted during execute phase (recovering)"
#         },
#         ...
#     ]
# }
```

#### Recovery Log

Each recovered job gets a `recovery.jsonl` log file:

```json
{
  "timestamp": "2026-02-19T18:00:00.000000+00:00",
  "action": "recovery_scheduled",
  "reason": "Interrupted at phase=execute, step=2",
  "original_phase_status": "running",
  "recovery_phase": "execute"
}
```

### 4. AlertSystem

Logs critical failures and system events to persistent alert file.

#### Alert Levels

- **WARNING**: Non-critical issue (e.g., agent temporarily unavailable)
- **CRITICAL**: Severe failure (e.g., all retries exhausted, circuit breaker opened)

#### Usage

```python
from error_recovery import AlertSystem, AlertLevel

# Log an alert
AlertSystem.log_alert(
    AlertLevel.CRITICAL,
    component="agent:coder_agent",
    message="Agent failed all retries",
    details={
        "job_id": "job-001",
        "phase": "execute",
        "error": "API error after 3 attempts",
        "cost_usd": 2.50,
    }
)

# Retrieve recent alerts
alerts = AlertSystem.get_recent_alerts(limit=100)
for alert in alerts:
    print(f"{alert['timestamp']} [{alert['level']}] {alert['component']}: {alert['message']}")
```

#### Alert Storage

Alerts are stored in `/tmp/openclaw_alerts.jsonl` (JSONL format):

```json
{"timestamp": "2026-02-19T18:00:00+00:00", "level": "critical", "component": "agent:coder_agent", "message": "Circuit breaker opened", "details": {...}}
```

### 5. HealthCheck

Comprehensive system health monitoring across all components.

#### Health Status Endpoints

```python
from error_recovery import get_error_recovery

recovery = get_error_recovery()

# Get full health
health = await recovery.health_check.get_system_health()

# {
#     "status": "healthy",
#     "timestamp": "2026-02-19T18:00:00+00:00",
#     "components": {
#         "runner": {
#             "status": "running",
#             "active_jobs": 2,
#             "total_cost": 15.50
#         },
#         "circuit_breakers": {
#             "total_agents": 5,
#             "open_breakers": 1,
#             "agents": {
#                 "coder_agent": {"state": "open", "failure_count": 5, ...},
#                 "elite_coder": {"state": "closed", ...},
#                 ...
#             }
#         },
#         "api": {
#             "anthropic": {"status": "unknown", ...},
#             "deepseek": {"status": "unknown", ...}
#         },
#         "disk": {
#             "total_gb": 100.0,
#             "used_gb": 45.3,
#             "free_gb": 54.7,
#             "percent_used": 45.3
#         },
#         "memory": {
#             "process_rss_mb": 512.5,
#             "system_total_gb": 32.0,
#             "system_used_gb": 18.5,
#             "system_percent": 57.8
#         }
#     }
# }
```

### 6. ErrorRecoveryManager

Central coordinator managing all error recovery components.

#### Setup

```python
from error_recovery import init_error_recovery, get_error_recovery
from fastapi import FastAPI

app = FastAPI()

# Initialize on startup
@app.on_event("startup")
async def startup():
    recovery = await init_error_recovery()
    app.include_router(recovery.create_routes())

# Shutdown gracefully
@app.on_event("shutdown")
async def shutdown():
    recovery = get_error_recovery()
    await recovery.shutdown()
```

## FastAPI Endpoints

All endpoints are provided by `ErrorRecoveryManager.create_routes()` under `/api/health`:

### GET /api/health/detailed

Full system health status including all components.

**Response:**

```json
{
  "status": "healthy",
  "timestamp": "2026-02-19T18:00:00+00:00",
  "components": {...}
}
```

### GET /api/health/circuit-breakers

All circuit breaker states.

**Response:**

```json
{
  "coder_agent": {
    "agent_key": "coder_agent",
    "state": "closed",
    "failure_count": 0,
    "success_count": 150,
    "last_failure_time": null,
    "last_success_time": 1708354800.123
  },
  ...
}
```

### GET /api/health/circuit-breakers/{agent_key}

Single agent circuit breaker state.

**Response:**

```json
{
  "agent_key": "coder_agent",
  "state": "closed",
  "failure_count": 0,
  "success_count": 150
}
```

### POST /api/health/circuit-breakers/{agent_key}/reset

Manually reset a circuit breaker to CLOSED (emergency use only).

**Response:**

```json
{
  "message": "Circuit breaker for coder_agent reset to CLOSED",
  "state": {...}
}
```

### GET /api/health/alerts?limit=100

Get recent alerts.

**Response:**

```json
{
  "alerts": [
    {
      "timestamp": "2026-02-19T18:00:00+00:00",
      "level": "warning",
      "component": "agent:coder_agent",
      "message": "Agent temporarily unavailable",
      "details": {}
    }
  ],
  "count": 1
}
```

## Integration with Autonomous Runner

### Error Handling Pattern

```python
from error_recovery import get_error_recovery, retry_with_policy

async def _call_agent(agent_key, prompt, tools=None):
    recovery = get_error_recovery()

    # Check circuit breaker first
    if not await recovery.circuit_breaker.is_available(agent_key):
        recovery.alert_system.log_alert(
            AlertLevel.WARNING,
            f"agent:{agent_key}",
            f"Agent is unavailable (circuit breaker open)"
        )
        raise Exception(f"Agent {agent_key} is unavailable")

    try:
        # Call agent with retry policy
        result = await retry_with_policy(
            lambda: api_call(agent_key, prompt),
            policy=recovery.retry_policy,
        )

        # Record success
        await recovery.circuit_breaker.record_success(agent_key)
        return result

    except Exception as e:
        # Record failure
        await recovery.circuit_breaker.record_failure(agent_key, e)

        # Log critical alert if circuit breaker opened
        state = await recovery.circuit_breaker.get_state(agent_key)
        if state["state"] == "open":
            recovery.alert_system.log_alert(
                AlertLevel.CRITICAL,
                f"agent:{agent_key}",
                f"Circuit breaker opened ({state['failure_count']} failures)",
                state
            )

        raise
```

### Job Failure Handling

```python
async def _run_job_pipeline(job):
    recovery = get_error_recovery()

    try:
        # ... run phases ...
        pass
    except Exception as e:
        # Log critical failure
        recovery.alert_system.log_alert(
            AlertLevel.CRITICAL,
            "runner",
            f"Job {job['id']} failed",
            {
                "job_id": job['id'],
                "error": str(e),
                "phase": progress.phase.value,
                "cost_usd": progress.cost_usd,
            }
        )
        raise
```

## Configuration

### RetryPolicy Defaults

```python
RetryPolicy(
    max_retries=3,           # Total attempts
    base_delay=2.0,          # Initial backoff (seconds)
    max_delay=60.0,          # Maximum backoff (seconds)
    jitter=True,             # Add ±10% random jitter
    rate_limit_wait=60.0,    # Default wait for rate limits
    timeout_multiplier=2.0,  # Double timeout on retry
    auth_retry=False,        # Never retry auth errors
)
```

### CircuitBreaker Defaults

```python
CircuitBreaker(
    failure_threshold=5,         # Open after N failures
    failure_window_sec=60.0,     # Time window for counting failures
    half_open_timeout_sec=30.0,  # Wait before testing recovery
)
```

## Monitoring & Observability

### Dashboards

View circuit breaker status and alerts:

```bash
# Monitor circuit breakers
curl http://localhost:8000/api/health/circuit-breakers | jq .

# Monitor recent alerts
curl http://localhost:8000/api/health/alerts?limit=50 | jq .

# Get full health
curl http://localhost:8000/api/health/detailed | jq .
```

### Logging

All errors are logged with context:

```
2026-02-19 18:00:00 [error_recovery] ERROR: Circuit breaker for coder_agent: CLOSED -> OPEN (5 failures in 60.0s)
2026-02-19 18:00:01 [error_recovery] WARNING: Retry attempt 1 failed: APIError. Retrying in 2.1s...
2026-02-19 18:00:03 [error_recovery] INFO: Circuit breaker for elite_coder: HALF_OPEN -> CLOSED (recovered)
```

### Alert File

Persistent alerts in `/tmp/openclaw_alerts.jsonl`:

```bash
# Tail recent alerts
tail -f /tmp/openclaw_alerts.jsonl | jq .

# Count alerts by level
cat /tmp/openclaw_alerts.jsonl | jq -r '.level' | sort | uniq -c

# Filter by component
cat /tmp/openclaw_alerts.jsonl | jq 'select(.component | contains("coder_agent"))'
```

## Best Practices

### 1. Always Use Circuit Breaker Checks

```python
# Good
if await recovery.circuit_breaker.is_available(agent_key):
    result = await call_agent(agent_key)

# Bad
result = await call_agent(agent_key)  # No check
```

### 2. Log Failures with Context

```python
recovery.alert_system.log_alert(
    AlertLevel.CRITICAL,
    "agent:coder_agent",
    "Agent failed",
    {
        "job_id": job_id,
        "phase": phase,
        "attempt": attempt,
        "error": str(error),
        "cost_usd": cost,
    }
)
```

### 3. Configure Per-Project Policies

```python
# Different projects may need different retry strategies
project_policies = {
    "barber-crm": RetryPolicy(max_retries=5, base_delay=1.0),
    "delhi-palace": RetryPolicy(max_retries=3, base_delay=2.0),
    "prestress-calc": RetryPolicy(max_retries=2, base_delay=1.0),
}

result = await retry_with_policy(
    fn,
    policy=project_policies.get(project, default_policy)
)
```

### 4. Monitor Disk Space

```python
health = await recovery.health_check.get_system_health()
disk = health["components"]["disk"]

if disk["percent_used"] > 80:
    recovery.alert_system.log_alert(
        AlertLevel.WARNING,
        "disk",
        f"Disk usage at {disk['percent_used']:.1f}%"
    )
```

### 5. React to Circuit Breaker Status

```python
# In a dashboard or monitoring system
breaker_states = await recovery.circuit_breaker.get_all_states()
open_agents = [
    agent for agent, state in breaker_states.items()
    if state["state"] == "open"
]

if open_agents:
    # Alert on-call engineer
    send_alert(f"Agents down: {open_agents}")
```

## Testing

Run the test suite:

```bash
pytest test_error_recovery.py -v

# Specific test
pytest test_error_recovery.py::TestRetryPolicy::test_policy_defaults -v

# With coverage
pytest test_error_recovery.py --cov=error_recovery
```

## File Structure

```
/root/openclaw/
├── error_recovery.py           # Main module (900+ LOC)
├── test_error_recovery.py      # Test suite
├── ERROR_RECOVERY.md           # This documentation
└── autonomous_runner.py        # Integration point
```

## Troubleshooting

### Circuit Breaker Stuck OPEN

If a circuit breaker is stuck in OPEN state and the service has recovered:

```bash
curl -X POST http://localhost:8000/api/health/circuit-breakers/coder_agent/reset
```

### High Alert Volume

If alerts are too frequent, adjust thresholds:

```python
# Increase failure threshold before opening breaker
cb = CircuitBreaker(failure_threshold=10)  # Was 5

# Increase failure window (more time to forget failures)
cb = CircuitBreaker(failure_window_sec=120.0)  # Was 60s
```

### Debugging Retry Logic

Enable debug logging:

```python
import logging
logging.getLogger("error_recovery").setLevel(logging.DEBUG)
```

## Performance

### Overhead

- **Circuit breaker checks**: < 1ms (in-memory dict lookup)
- **Alert logging**: ~5ms (file I/O)
- **Retry backoff**: Minimal (async sleep)
- **Health checks**: ~50ms (disk/memory stats)

### Scalability

- Handles 100+ concurrent jobs
- Supports 10+ agents with independent circuit breakers
- Alert file grows ~100 KB/day (can be archived)
- Circuit breaker state persisted to JSON (< 10 KB)

## Future Enhancements

1. **Per-phase retry policies** — Different strategies for each phase
2. **Adaptive backoff** — Learn optimal retry timing from success rates
3. **Fallback agents** — Automatically route to alternate agent when breaker opens
4. **Metrics export** — Prometheus metrics for monitoring
5. **Metrics dashboards** — Real-time metrics in web dashboard
6. **Smart recovery** — Resume from last completed phase instead of full restart
7. **Alert routing** — Send Slack/email on critical alerts
