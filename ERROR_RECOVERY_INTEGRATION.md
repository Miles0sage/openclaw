# Error Recovery Integration Guide

How to integrate the error recovery system into the OpenClaw gateway and autonomous runner.

## Quick Start

### 1. Add to Gateway Startup

In `src/gateway.ts` or `gateway.py`:

```python
from error_recovery import init_error_recovery, get_error_recovery
from fastapi import FastAPI

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Initialize error recovery system."""
    recovery = await init_error_recovery()
    print(f"[OK] Error recovery initialized")

@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown recovery system gracefully."""
    recovery = get_error_recovery()
    if recovery:
        await recovery.shutdown()
        print(f"[OK] Error recovery shut down")

# Mount health check routes
if __name__ == "__main__":
    recovery = await init_error_recovery()
    app.include_router(recovery.create_routes())
```

### 2. Integrate with Agent Calls

In `autonomous_runner.py`, modify `_call_agent()`:

```python
from error_recovery import get_error_recovery, retry_with_policy, AlertLevel

async def _call_agent(agent_key: str, prompt: str, conversation: list = None,
                      tools: list = None, job_id: str = "", phase: str = "") -> dict:
    """Call an agent with error recovery."""
    recovery = get_error_recovery()

    # Check circuit breaker
    if recovery and not await recovery.circuit_breaker.is_available(agent_key):
        error_msg = f"Circuit breaker OPEN for {agent_key}"
        logger.error(error_msg)
        recovery.alert_system.log_alert(
            AlertLevel.WARNING,
            f"agent:{agent_key}",
            error_msg
        )
        raise RuntimeError(error_msg)

    try:
        # Wrap API call with retry policy
        result = await retry_with_policy(
            lambda: _call_agent_impl(agent_key, prompt, conversation, tools, job_id, phase),
            policy=recovery.retry_policy if recovery else RetryPolicy(),
        )

        # Record success
        if recovery:
            await recovery.circuit_breaker.record_success(agent_key)

        return result

    except Exception as e:
        # Record failure
        if recovery:
            await recovery.circuit_breaker.record_failure(agent_key, e)

            # Check if breaker opened
            state = await recovery.circuit_breaker.get_state(agent_key)
            if state["state"] == "open":
                recovery.alert_system.log_alert(
                    AlertLevel.CRITICAL,
                    f"agent:{agent_key}",
                    f"Circuit breaker OPEN after {state['failure_count']} failures",
                    {"job_id": job_id, "phase": phase, "error": str(e)}
                )

        raise


async def _call_agent_impl(agent_key, prompt, conversation, tools, job_id, phase):
    """Actual implementation (move current code here)."""
    # ... existing code ...
    pass
```

### 3. Handle Crash Recovery on Startup

In `autonomous_runner.py`, update `AutonomousRunner.start()`:

```python
async def start(self):
    """Start the background job polling loop."""
    if self._running:
        logger.warning("AutonomousRunner is already running")
        return

    # Run crash recovery
    logger.info("Checking for interrupted jobs...")
    from error_recovery import CrashRecovery, get_error_recovery
    recovery_result = await CrashRecovery.recover_interrupted_jobs()
    if recovery_result["recovered_count"] > 0:
        logger.warning(f"Recovered {recovery_result['recovered_count']} interrupted jobs")
        recovery = get_error_recovery()
        if recovery:
            from error_recovery import AlertLevel
            recovery.alert_system.log_alert(
                AlertLevel.WARNING,
                "crash_recovery",
                f"Recovered {recovery_result['recovered_count']} jobs",
                recovery_result
            )

    self._running = True
    self._semaphore = asyncio.Semaphore(self.max_concurrent)
    self._poll_task = asyncio.create_task(self._poll_loop())
    logger.info("AutonomousRunner STARTED — polling for jobs")
```

### 4. Add Endpoint to Router

In your FastAPI app:

```python
from error_recovery import get_error_recovery

@app.on_event("startup")
async def setup_routes():
    recovery = get_error_recovery()
    if recovery:
        app.include_router(recovery.create_routes())
```

Now these endpoints are available:

```
GET  /api/health/detailed
GET  /api/health/circuit-breakers
GET  /api/health/circuit-breakers/{agent_key}
POST /api/health/circuit-breakers/{agent_key}/reset
GET  /api/health/alerts?limit=100
```

## Integration Checklist

- [ ] Import error recovery module in gateway
- [ ] Call `init_error_recovery()` on startup
- [ ] Call `recovery.shutdown()` on shutdown
- [ ] Include health check routes
- [ ] Add circuit breaker check before agent calls
- [ ] Wrap agent calls with `retry_with_policy()`
- [ ] Record success/failure with circuit breaker
- [ ] Log critical failures with alert system
- [ ] Run crash recovery on startup
- [ ] Test circuit breaker with manual failure
- [ ] Monitor health endpoints
- [ ] Set up alert file rotation (optional)

## Testing the Integration

### 1. Test Circuit Breaker

```bash
# Simulate failure to open circuit breaker
python3 -c "
import asyncio
from error_recovery import CircuitBreaker, AlertLevel

async def test():
    cb = CircuitBreaker(failure_threshold=2, failure_window_sec=10)

    # Record 2 failures
    await cb.record_failure('test-agent', Exception('error 1'))
    await cb.record_failure('test-agent', Exception('error 2'))

    # Check if available
    available = await cb.is_available('test-agent')
    print(f'Available: {available}')

    # Get state
    state = await cb.get_state('test-agent')
    print(f'State: {state[\"state\"]}')

asyncio.run(test())
"
```

### 2. Test Retry Policy

```bash
python3 -c "
import asyncio
from error_recovery import retry_with_policy, RetryPolicy

async def test():
    attempt = 0

    async def flaky():
        nonlocal attempt
        attempt += 1
        if attempt < 3:
            raise Exception(f'Attempt {attempt} failed')
        return 'success'

    result = await retry_with_policy(flaky)
    print(f'Result: {result} (took {attempt} attempts)')

asyncio.run(test())
"
```

### 3. Test Health Endpoints

```bash
# Get full health
curl http://localhost:8000/api/health/detailed | jq .

# Get circuit breaker status
curl http://localhost:8000/api/health/circuit-breakers | jq .

# Get recent alerts
curl http://localhost:8000/api/health/alerts | jq .
```

## Monitoring & Dashboards

### Real-time Monitoring

```bash
# Watch circuit breaker status (updates every 5s)
watch -n 5 'curl -s http://localhost:8000/api/health/circuit-breakers | jq .'

# Watch recent alerts
watch -n 5 'curl -s "http://localhost:8000/api/health/alerts?limit=20" | jq .'

# Tail alert file
tail -f /tmp/openclaw_alerts.jsonl | jq .
```

### Alert Filtering

```bash
# Alerts in last hour
cat /tmp/openclaw_alerts.jsonl | jq 'select(.level=="critical")' | tail -20

# By component
cat /tmp/openclaw_alerts.jsonl | jq 'select(.component | contains("coder_agent"))'

# Count by level
cat /tmp/openclaw_alerts.jsonl | jq -r '.level' | sort | uniq -c
```

## Performance Tuning

### Retry Policy Tuning

For **high-latency APIs** (e.g., Deepseek with token limits):

```python
policy = RetryPolicy(
    max_retries=5,        # More attempts
    base_delay=3.0,       # Longer initial backoff
    max_delay=120.0,      # Longer max backoff
    jitter=True,
)
```

For **fast APIs** (e.g., Anthropic):

```python
policy = RetryPolicy(
    max_retries=3,        # Fewer attempts
    base_delay=1.0,       # Shorter backoff
    max_delay=30.0,
    jitter=True,
)
```

### Circuit Breaker Tuning

For **mission-critical agents** (route all jobs through them):

```python
cb = CircuitBreaker(
    failure_threshold=10,        # Open after 10 failures
    failure_window_sec=120.0,    # 2-minute window
    half_open_timeout_sec=60.0,  # Wait 1 minute before recovery test
)
```

For **non-critical agents** (can fail fast):

```python
cb = CircuitBreaker(
    failure_threshold=3,         # Open after 3 failures
    failure_window_sec=30.0,     # 30-second window
    half_open_timeout_sec=10.0,  # Quick recovery test
)
```

## Troubleshooting

### Alerts Not Appearing

1. Check that alert file is writable:

```bash
ls -la /tmp/openclaw_alerts.jsonl
```

2. Check logs for write errors:

```bash
grep "Failed to write alert" /var/log/openclaw.log
```

3. Verify alert system is initialized:

```bash
curl http://localhost:8000/api/health/alerts
```

### Circuit Breaker Not Opening

1. Check failure count and threshold:

```bash
curl http://localhost:8000/api/health/circuit-breakers/coder_agent | jq .
```

2. Verify failure window is correct (failures must be recent)

3. Check if it's in HALF_OPEN state and waiting to test recovery

### High Memory Usage

If memory grows due to alert file:

```bash
# Archive old alerts
gzip /tmp/openclaw_alerts.jsonl
mv /tmp/openclaw_alerts.jsonl.gz /archive/alerts-$(date +%Y%m%d).jsonl.gz
touch /tmp/openclaw_alerts.jsonl

# Restart gateway to load from fresh file
```

## Example: Custom Alert Handling

```python
from error_recovery import get_error_recovery, AlertLevel
import slack_sdk

async def send_slack_on_critical_alert():
    """Send Slack message when critical alert is logged."""
    recovery = get_error_recovery()

    # Check alerts periodically
    while True:
        alerts = recovery.alert_system.get_recent_alerts(limit=10)

        for alert in alerts:
            if alert["level"] == "critical" and not alert.get("_notified"):
                # Send Slack message
                client = slack_sdk.WebClient(token=SLACK_TOKEN)
                client.chat_postMessage(
                    channel="#alerts",
                    text=f"🚨 {alert['component']}: {alert['message']}"
                )

                # Mark as notified
                alert["_notified"] = True

        await asyncio.sleep(30)  # Check every 30s
```

## Next Steps

1. **Deploy** the error recovery system to production
2. **Monitor** circuit breakers and alerts via endpoints
3. **Tune** retry policies based on actual failure patterns
4. **Create** dashboards/alerts in your monitoring system
5. **Document** any custom retry policies for your projects
