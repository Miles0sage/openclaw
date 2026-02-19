# Error Recovery System — Usage Examples

Real-world examples of using the error recovery system in OpenClaw.

## Example 1: Safe Agent Calling Pattern

```python
from error_recovery import get_error_recovery, AlertLevel, ErrorType

async def call_agent_safely(agent_key: str, prompt: str, job_id: str):
    """Template for safe agent calling with all error handling."""
    recovery = get_error_recovery()

    # Step 1: Check if agent is available
    if not await recovery.circuit_breaker.is_available(agent_key):
        recovery.alert_system.log_alert(
            AlertLevel.WARNING,
            f"agent:{agent_key}",
            "Agent is currently unavailable (circuit breaker open)",
            {"job_id": job_id, "reason": "circuit_breaker_open"}
        )
        raise RuntimeError(f"Agent {agent_key} is unavailable")

    try:
        # Step 2: Call agent with retry policy
        result = await retry_with_policy(
            lambda: api.call_agent(agent_key, prompt),
            policy=recovery.retry_policy,
            error_type=ErrorType.SERVER_ERROR,  # Hint for strategy
        )

        # Step 3: Record success
        await recovery.circuit_breaker.record_success(agent_key)

        logger.info(f"Agent {agent_key} succeeded for job {job_id}")
        return result

    except Exception as e:
        # Step 4: Record failure and check breaker status
        await recovery.circuit_breaker.record_failure(agent_key, e)

        state = await recovery.circuit_breaker.get_state(agent_key)

        # Step 5: Log alert if breaker opened
        if state["state"] == "open":
            recovery.alert_system.log_alert(
                AlertLevel.CRITICAL,
                f"agent:{agent_key}",
                f"Circuit breaker OPEN after {state['failure_count']} failures",
                {
                    "job_id": job_id,
                    "failure_count": state["failure_count"],
                    "last_error": str(e),
                }
            )

        raise
```

## Example 2: Handling Rate Limits

```python
from error_recovery import retry_with_policy, RetryPolicy, ErrorType

async def call_api_with_rate_limit_handling(url: str, headers: dict):
    """API call that respects rate limit headers."""
    policy = RetryPolicy(
        max_retries=5,
        base_delay=1.0,
        max_delay=120.0,  # Allow up to 2 minutes for rate limit wait
        rate_limit_wait=60.0,  # Default to 60s if no Retry-After
    )

    return await retry_with_policy(
        lambda: requests.get(url, headers=headers),
        policy=policy,
        error_type=ErrorType.RATE_LIMIT,
    )
```

## Example 3: Multi-Agent Failover

```python
from error_recovery import get_error_recovery, AlertLevel

async def call_agent_with_failover(task: str, primary_agent: str, fallback_agent: str):
    """Try primary agent, fall back to secondary on unavailability."""
    recovery = get_error_recovery()

    # Try primary agent
    if await recovery.circuit_breaker.is_available(primary_agent):
        try:
            return await call_agent_safely(primary_agent, task, job_id="job-123")
        except Exception as e:
            logger.warning(f"Primary agent {primary_agent} failed: {e}, trying fallback...")

    # Fall back to secondary
    logger.info(f"Failing over to {fallback_agent}")
    recovery.alert_system.log_alert(
        AlertLevel.WARNING,
        "failover",
        f"Using fallback agent {fallback_agent} (primary {primary_agent} unavailable)"
    )

    return await call_agent_safely(fallback_agent, task, job_id="job-123")
```

## Example 4: Monitoring Circuit Breakers

```python
from error_recovery import get_error_recovery
import asyncio

async def monitor_agents():
    """Periodically check agent health."""
    recovery = get_error_recovery()

    while True:
        breaker_states = await recovery.circuit_breaker.get_all_states()

        for agent_key, state in breaker_states.items():
            if state["state"] == "open":
                logger.error(f"🚨 {agent_key} is DOWN ({state['failure_count']} failures)")
            elif state["state"] == "half_open":
                logger.warning(f"⚠️ {agent_key} is RECOVERING (testing...)")
            else:
                logger.debug(f"✅ {agent_key} is healthy ({state['success_count']} successes)")

        await asyncio.sleep(30)  # Check every 30 seconds
```

## Example 5: Structured Logging with Context

```python
from error_recovery import get_error_recovery, AlertLevel
from contextlib import contextmanager
import json

@contextmanager
def job_context(job_id: str, agent_key: str, phase: str):
    """Context manager for structured job logging."""
    recovery = get_error_recovery()
    context = {
        "job_id": job_id,
        "agent": agent_key,
        "phase": phase,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        yield context
    except Exception as e:
        context["error"] = str(e)
        context["ended_at"] = datetime.now(timezone.utc).isoformat()

        recovery.alert_system.log_alert(
            AlertLevel.CRITICAL,
            f"job:{job_id}",
            f"Failed in {phase} phase",
            context
        )
        raise

# Usage
async def execute_job(job_id: str, agent_key: str):
    with job_context(job_id, agent_key, "execute") as ctx:
        result = await call_agent_safely(agent_key, prompt, job_id)
        ctx["result"] = result
        return result
```

## Example 6: Custom Retry Strategy per Agent

```python
from error_recovery import RetryPolicy, get_error_recovery, retry_with_policy

# Different agents need different retry strategies
AGENT_RETRY_POLICIES = {
    "coder_agent": RetryPolicy(
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,  # Fast retries (cheaper)
    ),
    "elite_coder": RetryPolicy(
        max_retries=5,
        base_delay=2.0,
        max_delay=60.0,  # Slower, more patient (more complex tasks)
    ),
    "database_agent": RetryPolicy(
        max_retries=4,
        base_delay=2.0,
        max_delay=45.0,  # Medium (data is important)
    ),
}

async def call_agent_with_strategy(agent_key: str, prompt: str):
    """Call agent using agent-specific retry policy."""
    policy = AGENT_RETRY_POLICIES.get(agent_key, RetryPolicy())

    return await retry_with_policy(
        lambda: api.call_agent(agent_key, prompt),
        policy=policy,
    )
```

## Example 7: Graceful Degradation

```python
from error_recovery import get_error_recovery, AlertLevel

async def execute_task_gracefully(task_description: str, job_id: str):
    """Execute task with graceful degradation if some agents are down."""
    recovery = get_error_recovery()

    # Get available agents
    breaker_states = await recovery.circuit_breaker.get_all_states()
    available_agents = [
        agent for agent, state in breaker_states.items()
        if state["state"] != "open"
    ]

    if not available_agents:
        recovery.alert_system.log_alert(
            AlertLevel.CRITICAL,
            "system",
            "All agents are unavailable, queuing job for later",
            {"job_id": job_id}
        )
        # Queue for retry
        await queue_job_for_retry(job_id)
        return None

    # Use best available agent
    primary_agent = available_agents[0]
    logger.info(f"Using {primary_agent} for job {job_id} (other agents down)")

    return await call_agent_safely(primary_agent, task_description, job_id)
```

## Example 8: Alert-Driven Actions

```python
from error_recovery import get_error_recovery, AlertLevel
import asyncio

async def react_to_alerts():
    """React to critical alerts in real-time."""
    recovery = get_error_recovery()
    seen_alerts = set()

    while True:
        alerts = recovery.alert_system.get_recent_alerts(limit=100)

        for alert in alerts:
            alert_id = (alert["timestamp"], alert["component"])

            if alert_id in seen_alerts:
                continue

            seen_alerts.add(alert_id)

            # React based on alert type
            if alert["level"] == "critical":
                if "circuit breaker" in alert["message"]:
                    # Page on-call engineer
                    await page_engineer(alert)
                elif "all retries exhausted" in alert["message"]:
                    # Escalate to manual review
                    await escalate_to_human(alert)

        await asyncio.sleep(10)
```

## Example 9: Dashboard Data

```python
from error_recovery import get_error_recovery
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/dashboard/overview")
async def get_dashboard_overview():
    """Get data for error recovery dashboard."""
    recovery = get_error_recovery()

    # System health
    health = await recovery.health_check.get_system_health()

    # Circuit breaker summary
    breaker_states = await recovery.circuit_breaker.get_all_states()
    breaker_summary = {
        "total_agents": len(breaker_states),
        "healthy": sum(1 for s in breaker_states.values() if s["state"] == "closed"),
        "failing": sum(1 for s in breaker_states.values() if s["state"] == "open"),
        "recovering": sum(1 for s in breaker_states.values() if s["state"] == "half_open"),
    }

    # Recent alerts
    recent_alerts = recovery.alert_system.get_recent_alerts(limit=20)

    return JSONResponse({
        "health": health,
        "breakers": breaker_summary,
        "alerts": recent_alerts,
    })
```

## Example 10: Emergency Breach Reset

```python
from error_recovery import get_error_recovery

async def emergency_reset_all_breakers():
    """Reset all circuit breakers (use only in emergency)."""
    recovery = get_error_recovery()

    breaker_states = await recovery.circuit_breaker.get_all_states()

    logger.warning("🚨 EMERGENCY: Resetting all circuit breakers!")

    for agent_key in breaker_states.keys():
        await recovery.circuit_breaker.reset(agent_key)
        logger.warning(f"  Reset {agent_key}")

    recovery.alert_system.log_alert(
        AlertLevel.CRITICAL,
        "system",
        "Emergency reset of all circuit breakers performed",
        {"reason": "manual_intervention"}
    )
```

## Example 11: Backoff Verification

```python
from error_recovery import _calculate_backoff, RetryPolicy

# Verify backoff progression for tuning
policy = RetryPolicy(base_delay=1.0, max_delay=60.0, jitter=False)

print("Backoff progression (without jitter):")
for attempt in range(6):
    backoff = _calculate_backoff(attempt, 0.0, policy)
    print(f"  Attempt {attempt}: {backoff:.1f}s")

# Output:
# Attempt 0: 1.0s
# Attempt 1: 2.0s
# Attempt 2: 4.0s
# Attempt 3: 8.0s
# Attempt 4: 16.0s
# Attempt 5: 32.0s
```

## Example 12: Per-Phase Error Handling

```python
from error_recovery import RetryPolicy, retry_with_policy, ErrorType

# Different phases have different needs
PHASE_POLICIES = {
    "research": RetryPolicy(max_retries=3, base_delay=1.0),      # Fast
    "plan": RetryPolicy(max_retries=3, base_delay=1.0),          # Fast
    "execute": RetryPolicy(max_retries=5, base_delay=2.0),       # Patient
    "verify": RetryPolicy(max_retries=2, base_delay=1.0),        # Quick
    "deliver": RetryPolicy(max_retries=4, base_delay=1.5),       # Careful
}

async def execute_phase_safely(phase: str, phase_fn, job_id: str):
    """Execute a phase with appropriate error handling."""
    policy = PHASE_POLICIES[phase]

    try:
        result = await retry_with_policy(phase_fn, policy=policy)
        logger.info(f"Phase {phase} succeeded for job {job_id}")
        return result
    except Exception as e:
        logger.error(f"Phase {phase} failed for job {job_id}: {e}")
        recovery = get_error_recovery()
        recovery.alert_system.log_alert(
            AlertLevel.CRITICAL,
            f"phase:{phase}",
            f"Phase failed after {policy.max_retries} retries",
            {"job_id": job_id, "error": str(e)}
        )
        raise
```

## Example 13: Testing Error Handling

```python
import pytest
from unittest.mock import AsyncMock, patch
from error_recovery import retry_with_policy, RetryPolicy

@pytest.mark.asyncio
async def test_retry_on_temporary_failure():
    """Test that temporary failures are retried."""
    call_count = 0

    async def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("Temporary error")
        return "success"

    result = await retry_with_policy(flaky_function)

    assert result == "success"
    assert call_count == 3

@pytest.mark.asyncio
async def test_circuit_breaker_opens():
    """Test that circuit breaker opens after failures."""
    from error_recovery import CircuitBreaker

    cb = CircuitBreaker(failure_threshold=2)

    # Open the breaker
    await cb.record_failure("test-agent", Exception("error 1"))
    await cb.record_failure("test-agent", Exception("error 2"))

    # Verify it's open
    available = await cb.is_available("test-agent")
    assert available is False
```

## Best Practices Summary

1. **Always check circuit breaker** before calling agents
2. **Use retry_with_policy** for all external API calls
3. **Record success/failure** with the circuit breaker
4. **Log alerts with context** when things go wrong
5. **Monitor endpoints** for health and alerts
6. **Tune policies** based on actual failure patterns
7. **Implement graceful degradation** when agents are down
8. **Test error handling** as thoroughly as happy path
9. **React to critical alerts** in real-time
10. **Document agent-specific policies** for team reference
