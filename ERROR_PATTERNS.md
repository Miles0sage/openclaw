# OpenClaw Error Handling - Code Patterns Reference

Quick copy-paste patterns for common error handling scenarios.

---

## Pattern 1: Protect External API Call with Timeout + Retry

```python
from error_handler import execute_with_retry_async, execute_with_timeout_async

async def call_external_api_safe(url: str, data: dict):
    """Call external API with timeout and retry protection"""
    async def api_call():
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data)
            response.raise_for_status()
            return response.json()

    # 30s timeout, max 3 retries with exponential backoff
    return await execute_with_retry_async(
        lambda: execute_with_timeout_async(api_call, timeout_seconds=30.0),
        max_retries=3
    )

# Usage:
result = await call_external_api_safe("https://api.example.com/data", {"key": "value"})
```

---

## Pattern 2: Track Agent Success/Failure

```python
from error_handler import track_agent_success, track_agent_error

async def call_agent_with_tracking(agent_id: str, prompt: str):
    """Call agent and track health status"""
    try:
        response = await agent.call(prompt)
        track_agent_success(agent_id)  # Record success
        return response
    except Exception as e:
        track_agent_error(agent_id, e)  # Record failure with error type
        raise

# Usage:
try:
    result = await call_agent_with_tracking("claude-opus", "Write a function")
except Exception as e:
    print(f"Agent failed: {e}")
```

---

## Pattern 3: Code Generation with Fallback Chain

```python
from error_handler import CodeGenerationFallback

def generate_code_with_fallback(prompt: str):
    """Generate code trying multiple models"""
    fallback = CodeGenerationFallback(model_clients={
        "deepseek-chat": deepseek_client,
        "deepseek-reasoner": deepseek_reasoner,
        "claude-opus-4-6": claude_client,
    })

    result = fallback.execute(
        prompt,
        timeout_seconds=30.0,
        max_retries_per_model=2
    )

    if result.success:
        print(f"✅ Generated with {result.model_used}")
        return result.code
    else:
        print(f"❌ All models failed")
        print(result.code)  # Error message
        return None

# Usage:
code = generate_code_with_fallback("Create a React component for a button")
```

---

## Pattern 4: Route to Healthy Agent Only

```python
from error_handler import get_health_tracker

async def call_healthy_agent(agents: list, prompt: str):
    """Call only healthy agents, fallback to others if needed"""
    tracker = get_health_tracker()

    # Filter to healthy agents first
    healthy_agents = tracker.get_healthy_agents(agents)

    # If no healthy agents, use all agents
    if not healthy_agents:
        logger.warning("No healthy agents, using all")
        healthy_agents = agents

    # Try each agent in order
    for agent_id in healthy_agents:
        try:
            result = await agent_dispatcher.call(agent_id, prompt)
            track_agent_success(agent_id)
            return result
        except Exception as e:
            track_agent_error(agent_id, e)
            # Continue to next agent

    raise Exception(f"All {len(agents)} agents failed")

# Usage:
result = await call_healthy_agent(["agent1", "agent2", "agent3"], prompt)
```

---

## Pattern 5: VPS Agent with Cloudflare Fallback

```python
from error_handler import VPSAgentFailover, VPSAgentConfig

async def generate_code_with_vps_fallback(prompt: str):
    """Generate code via VPS, fallback to Cloudflare if unavailable"""
    config = VPSAgentConfig(
        vps_endpoint="http://vps-agent:8000",
        cloudflare_endpoint="http://cf-gateway:18789"
    )
    failover = VPSAgentFailover(config)

    try:
        result = await failover.execute_with_fallback(
            vps_agent.generate_code,
            prompt,
            agent_id="vps_codegen"
        )
        return result
    except Exception as e:
        logger.error(f"VPS and Cloudflare both failed: {e}")
        raise

# Usage:
try:
    code = await generate_code_with_vps_fallback("Write a function")
except Exception as e:
    print("Service unavailable")
```

---

## Pattern 6: Retry Specific Model with Timeout

```python
from error_handler import execute_with_retry_async, execute_with_timeout_async, TimeoutException

async def call_model_with_retry(model_name: str, prompt: str):
    """Call model with timeout and retry"""
    async def call_fn():
        return await execute_with_timeout_async(
            lambda: client_for_model(model_name).generate(prompt),
            timeout_seconds=30.0
        )

    try:
        return await execute_with_retry_async(call_fn, max_retries=3)
    except TimeoutException:
        print(f"Model {model_name} timed out after all retries")
        raise

# Usage:
try:
    response = await call_model_with_retry("deepseek-chat", "Explain quantum computing")
except TimeoutException:
    print("Model is too slow, try again later")
```

---

## Pattern 7: Monitor Agent Health

```python
from error_handler import get_error_summary

async def get_health_dashboard():
    """Get current health of all agents"""
    summary = get_error_summary()

    # Print agent statuses
    for agent_id, status in summary["agent_statuses"].items():
        print(f"{agent_id}: {status['status']} ({status['success_rate']:.1f}%)")
        if status['consecutive_failures'] > 0:
            print(f"  Consecutive failures: {status['consecutive_failures']}")

    # Print error metrics
    print("\nError breakdown:")
    for error_type, count in summary["error_metrics"].items():
        print(f"  {error_type}: {count}")

    return summary

# Usage (in endpoint):
@app.get("/api/health")
async def health_endpoint():
    return await get_health_dashboard()
```

---

## Pattern 8: Classify & Handle Error by Type

```python
from error_handler import classify_error, ErrorType

async def call_with_error_handling(fn, *args, **kwargs):
    """Call function and handle error based on type"""
    try:
        return await fn(*args, **kwargs)

    except Exception as e:
        error_type = classify_error(e)

        if error_type == ErrorType.TIMEOUT:
            logger.warning("Timeout - request took too long")
            # Could retry with longer timeout
            return {"error": "timeout", "retry": True}

        elif error_type == ErrorType.RATE_LIMIT:
            logger.warning("Rate limited - backing off")
            # Implement exponential backoff
            return {"error": "rate_limit", "retry_after": 60}

        elif error_type == ErrorType.NETWORK:
            logger.warning("Network error - retryable")
            # Network issues are usually temporary
            return {"error": "network", "retry": True}

        elif error_type == ErrorType.AUTHENTICATION:
            logger.error("Auth failed - check credentials")
            # Don't retry auth failures
            return {"error": "auth", "retry": False}

        elif error_type == ErrorType.MODEL_ERROR:
            logger.error("Model not found or invalid")
            return {"error": "model", "retry": False}

        else:
            logger.error(f"Unknown error: {e}")
            return {"error": "unknown", "retry": False}

# Usage:
result = await call_with_error_handling(external_api_call)
```

---

## Pattern 9: Graceful Degradation on Failure

```python
async def get_data_with_fallback(primary_source: str, fallback_source: str):
    """Try primary source, fall back to secondary if fails"""
    try:
        # Try primary source with timeout
        return await execute_with_timeout_async(
            lambda: fetch_from(primary_source),
            timeout_seconds=5.0
        )
    except Exception as e:
        logger.warning(f"Primary source failed ({e}), using fallback")
        track_agent_error(primary_source, e)

    try:
        # Fall back to secondary source
        return await execute_with_timeout_async(
            lambda: fetch_from(fallback_source),
            timeout_seconds=10.0  # Longer timeout for fallback
        )
    except Exception as e:
        logger.error(f"Both sources failed: {e}")
        track_agent_error(fallback_source, e)
        # Return cached/default data
        return {"data": [], "source": "cache"}

# Usage:
data = await get_data_with_fallback("primary_api", "backup_api")
```

---

## Pattern 10: Health Check with Threshold

```python
from error_handler import get_health_tracker

def should_use_agent(agent_id: str, min_success_rate: float = 80.0) -> bool:
    """Check if agent's success rate meets threshold"""
    tracker = get_health_tracker()
    status = tracker.get_agent_status(agent_id)

    if status is None:
        return True  # Unknown agent assumed healthy

    if status["success_rate"] < min_success_rate:
        logger.warning(f"Agent {agent_id} below threshold: {status['success_rate']}%")
        return False

    return True

async def route_with_health_check(agent_id: str, prompt: str):
    """Route only if agent is healthy"""
    if not should_use_agent(agent_id, min_success_rate=80.0):
        # Use backup agent instead
        agent_id = "backup_agent"

    return await call_agent(agent_id, prompt)

# Usage:
result = await route_with_health_check("primary_agent", "Do something")
```

---

## Pattern 11: Async Callback on Retry

```python
from error_handler import execute_with_retry_async

async def on_retry_callback(attempt: int, delay: float, error: Exception):
    """Called when retry happens"""
    logger.warning(f"Retry #{attempt} after {delay}s: {type(error).__name__}")
    # Could send alert, update UI, etc.

async def api_call_with_retry_notifications(url: str):
    """Call API with retry notifications"""
    async def call_fn():
        async with httpx.AsyncClient() as client:
            return await client.get(url)

    return await execute_with_retry_async(
        call_fn,
        max_retries=3,
        on_retry=on_retry_callback
    )

# Usage:
result = await api_call_with_retry_notifications("https://api.example.com/data")
```

---

## Pattern 12: Record Metrics During Retry

```python
from error_handler import execute_with_retry_async
from datetime import datetime

retry_metrics = {"start_time": None, "end_time": None, "attempts": 0}

async def on_retry(attempt: int, delay: float, error: Exception):
    """Track retry metrics"""
    retry_metrics["attempts"] = attempt

async def measure_retry_performance(fn, *args, **kwargs):
    """Measure how long retries take"""
    retry_metrics["start_time"] = datetime.now()

    result = await execute_with_retry_async(
        fn,
        *args,
        max_retries=3,
        on_retry=on_retry,
        **kwargs
    )

    retry_metrics["end_time"] = datetime.now()
    duration = (retry_metrics["end_time"] - retry_metrics["start_time"]).total_seconds()

    logger.info(f"Completed in {duration}s after {retry_metrics['attempts']} attempts")
    return result

# Usage:
result = await measure_retry_performance(api_call, url="...")
```

---

## Quick Reference: Error Classification

```python
from error_handler import classify_error, ErrorType

error_classifications = {
    "timed out": ErrorType.TIMEOUT,
    "429": ErrorType.RATE_LIMIT,
    "Connection refused": ErrorType.NETWORK,
    "401 Unauthorized": ErrorType.AUTHENTICATION,
    "Model not found": ErrorType.MODEL_ERROR,
    "500 Internal": ErrorType.INTERNAL,
}

# Classify any exception
error_type = classify_error(some_exception)
```

---

## Quick Reference: Configuration

```python
from error_handler import RetryConfig, VPSAgentConfig

# Standard retry config (1s, 2s, 4s, 8s with jitter)
retry_config = RetryConfig(
    max_retries=3,
    initial_delay_seconds=1.0,
    max_delay_seconds=8.0,
    backoff_multiplier=2.0,
    jitter=True
)

# Custom retry config (faster retries)
fast_retry_config = RetryConfig(
    max_retries=5,
    initial_delay_seconds=0.1,
    max_delay_seconds=2.0,
    backoff_multiplier=1.5,
    jitter=False
)

# VPS failover config
vps_config = VPSAgentConfig(
    vps_endpoint="http://vps:8000",
    cloudflare_endpoint="http://cf:18789",
    health_check_timeout=5.0,
    fallback_to_cloudflare=True
)
```

---

## Testing These Patterns

```bash
# Run all tests
pytest test_error_handler.py -v

# Run specific pattern
pytest test_error_handler.py::TestRetryLogic::test_retry_success_after_failures -v

# With coverage
pytest test_error_handler.py --cov=error_handler --cov-report=html
```

---

## Common Mistakes to Avoid

❌ **DON'T** hardcode timeouts - use error_handler defaults

```python
# Bad
response = requests.get(url)  # No timeout!

# Good
response = await execute_with_timeout_async(fn, timeout_seconds=30.0)
```

❌ **DON'T** ignore errors - always track them

```python
# Bad
try:
    result = await api_call()
except:
    pass  # Errors disappear!

# Good
try:
    result = await api_call()
    track_agent_success("api")
except Exception as e:
    track_agent_error("api", e)
```

❌ **DON'T** retry forever - set max retries

```python
# Bad
while True:
    try:
        result = await api_call()
        break
    except:
        pass  # Infinite retry loop!

# Good
result = await execute_with_retry_async(api_call, max_retries=3)
```

❌ **DON'T** mix sync and async

```python
# Bad - mixing sync retry with async code
result = execute_with_retry(async_fn)  # Wrong!

# Good - use async retry for async code
result = await execute_with_retry_async(async_fn)
```

---

## Debugging Tips

1. **Check health summary**

   ```python
   from error_handler import get_error_summary
   summary = get_error_summary()
   print(summary)
   ```

2. **Monitor logs for error types**

   ```bash
   grep "timeout\|rate_limit\|network" /var/log/openclaw.log
   ```

3. **Test retry locally**

   ```python
   from error_handler import execute_with_retry

   def fail_then_succeed():
       if not hasattr(fail_then_succeed, 'called'):
           fail_then_succeed.called = True
           raise Exception("First call fails")
       return "success"

   result = execute_with_retry(fail_then_succeed)
   assert result == "success"
   ```

4. **Test timeout locally**

   ```python
   from error_handler import execute_with_timeout_async, TimeoutException

   async def slow_fn():
       await asyncio.sleep(10)

   try:
       await execute_with_timeout_async(slow_fn, timeout_seconds=1)
   except TimeoutException:
       print("Timeout working correctly")
   ```

---

## Support & Resources

- **Full Guide:** ERROR_HANDLING_GUIDE.md
- **Tests:** test_error_handler.py (47 tests)
- **Implementation:** IMPLEMENTATION_CHECKLIST.md
- **Source Code:** error_handler.py (518 LOC)
