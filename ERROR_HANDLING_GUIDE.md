# OpenClaw Error Handling Implementation Guide

## Overview

Comprehensive error handling system for OpenClaw with 4 key components:

1. **Fallback Chains** — Automatic model fallback (Kimi 2.5 → Reasoner → Opus → error)
2. **Retry Logic** — Exponential backoff (1s, 2s, 4s, 8s) with max 3 retries
3. **Timeout Handling** — 30-second max per request with graceful degradation
4. **Agent Health Tracking** — Auto-failover and unhealthy agent detection

---

## 1. FALLBACK CHAINS FOR CODE GENERATION

### Fallback Priority Order

```
Primary:    Kimi 2.5 (deepseek-chat) — fastest, good quality
Secondary:  Kimi Reasoner (deepseek-reasoner) — slower, better thinking
Tertiary:   Claude Opus (claude-opus-4-6) — most capable, most expensive
Quaternary: Claude Sonnet (claude-sonnet-4-20250514) — balanced
Fallback:   Return detailed error message with debugging info
```

### Basic Usage

```python
from error_handler import CodeGenerationFallback, ModelProvider

# Initialize with model clients
clients = {
    "deepseek-chat": deepseek_client,
    "claude-opus-4-6": anthropic_client,
    # ... other models
}

fallback = CodeGenerationFallback(model_clients=clients)

# Execute with automatic fallback
result = fallback.execute(
    prompt="Generate a React component...",
    timeout_seconds=30.0,
    max_retries_per_model=2
)

# Check result
if result.success:
    print(f"✅ Generated with {result.model_used}")
    print(f"Code:\n{result.code}")
else:
    print(f"❌ All models failed:")
    for error in result.errors_encountered:
        print(f"  - {error['model']}: {error['error_type']}")
```

### How It Works

1. **Try Kimi 2.5 (deepseek-chat)**
   - Fastest model for most tasks
   - 2 retries with exponential backoff
   - 30-second timeout per attempt

2. **If Kimi 2.5 fails → Try Kimi Reasoner**
   - Better reasoning for complex code
   - Same retry/timeout settings
   - Use when logic reasoning needed

3. **If Reasoner fails → Try Claude Opus**
   - Most capable, handles edge cases
   - Higher cost but nearly 100% success rate
   - Reserved for complex code generation

4. **If all models fail → Return Error Message**
   - Detailed error report showing all attempts
   - Error types (timeout, rate limit, network, auth, etc.)
   - Suggests debugging steps

### Response Format

```python
@dataclass
class CodeGenerationResult:
    code: str                           # Generated code or error message
    model_used: str                     # Which model succeeded (or "none")
    attempt_number: int                 # Which fallback attempt succeeded
    total_attempts: int                 # Total models tried
    errors_encountered: List[Dict]      # All errors from failed attempts
    duration_ms: float                  # Total time spent
    success: bool                       # True if generation succeeded
```

### Integration with Gateway

```python
# In gateway.py, replace hardcoded model selection:

@app.post("/api/chat")
async def handle_chat(message: Message):
    prompt = message.content

    # OLD: Always use hardcoded PM agent
    # response = orchestrator.send_to_agent(prompt, "pm")

    # NEW: Use fallback chain for code generation
    if "code" in prompt.lower() or "implement" in prompt.lower():
        fallback = CodeGenerationFallback(model_clients={
            "deepseek-chat": deepseek_client,
            "claude-opus-4-6": anthropic_client,
        })
        result = fallback.execute(prompt)

        if result.success:
            return JSONResponse({
                "response": result.code,
                "model": result.model_used,
                "attempts": result.attempt_number
            })
        else:
            # All models failed, return error
            return JSONResponse({
                "error": result.code,
                "attempts": result.total_attempts
            }, status_code=503)

    # Non-code requests use normal routing
    return orchestrator.handle_request(prompt)
```

---

## 2. RETRY LOGIC WITH EXPONENTIAL BACKOFF

### Configuration

```python
from error_handler import RetryConfig, execute_with_retry

# Default: 3 retries with delays 1s, 2s, 4s, 8s
config = RetryConfig(
    max_retries=3,
    initial_delay_seconds=1.0,
    max_delay_seconds=8.0,
    backoff_multiplier=2.0,
    jitter=True  # Add ±10% randomness to avoid thundering herd
)
```

### Backoff Sequence

```
Attempt 1: No delay (try immediately)
Attempt 2: 1 second (1 × 2^0)
Attempt 3: 2 seconds (1 × 2^1)
Attempt 4: 4 seconds (1 × 2^2)
Max delay: 8 seconds (capped)
```

### Synchronous Usage

```python
from error_handler import execute_with_retry

def unreliable_api_call():
    response = requests.get("https://api.example.com/data", timeout=5)
    if response.status_code != 200:
        raise Exception(f"API error: {response.status_code}")
    return response.json()

# Automatic retry with exponential backoff
try:
    data = execute_with_retry(
        unreliable_api_call,
        max_retries=3
    )
    print(f"✅ Got data: {data}")
except Exception as e:
    print(f"❌ Failed after retries: {e}")
```

### Asynchronous Usage

```python
from error_handler import execute_with_retry_async

async def unreliable_async_api_call():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/data")
        if response.status_code != 200:
            raise Exception(f"API error: {response.status_code}")
        return response.json()

# Async retry with exponential backoff
try:
    data = await execute_with_retry_async(
        unreliable_async_api_call,
        max_retries=3
    )
    print(f"✅ Got data: {data}")
except Exception as e:
    print(f"❌ Failed after retries: {e}")
```

### With Callbacks

```python
def on_retry(attempt_number, delay_seconds, error):
    print(f"⚠️  Retry {attempt_number} after {delay_seconds}s delay")
    print(f"   Previous error: {error}")

result = execute_with_retry(
    unreliable_api_call,
    max_retries=3,
    on_retry=on_retry
)
```

### Retry with Custom Arguments

```python
def api_call_with_args(endpoint, timeout=5):
    response = requests.get(endpoint, timeout=timeout)
    return response.json()

# Pass args/kwargs to execute_with_retry
data = execute_with_retry(
    api_call_with_args,
    endpoint="https://api.example.com/data",
    timeout=10,
    max_retries=3
)
```

---

## 3. TIMEOUT HANDLING

### 30-Second Max Per Request

All requests to external APIs should have a 30-second timeout to prevent hanging.

### Asynchronous Timeout

```python
from error_handler import execute_with_timeout_async, TimeoutException

async def slow_operation():
    # Simulate slow API call
    await asyncio.sleep(5)
    return "result"

# With timeout protection
try:
    result = await execute_with_timeout_async(
        slow_operation,
        timeout_seconds=30.0
    )
    print(f"✅ Got result: {result}")
except TimeoutException as e:
    print(f"⏱️  Operation timed out: {e}")
```

### Timeout with Callback

```python
async def on_timeout():
    # Cleanup on timeout (close connections, cancel tasks, etc.)
    print("⏱️  Timeout reached, cleaning up...")
    await asyncio.gather(*tasks, return_exceptions=True)

try:
    result = await execute_with_timeout_async(
        slow_operation,
        timeout_seconds=30.0,
        on_timeout=on_timeout
    )
except TimeoutException:
    print("Operation timed out")
```

### Timeout Integration in Gateway

```python
@app.post("/api/chat")
async def handle_chat(message: Message):
    try:
        # All API calls protected with 30-second timeout
        response = await execute_with_timeout_async(
            lambda: orchestrator.send_to_agent(
                message.content,
                agent_id=message.agent_id
            ),
            timeout_seconds=30.0
        )
        return JSONResponse({"response": response})

    except TimeoutException:
        logger.error(f"Agent {message.agent_id} timed out")
        return JSONResponse({
            "error": "Request timed out after 30 seconds",
            "agent": message.agent_id
        }, status_code=504)
```

---

## 4. AGENT HEALTH TRACKING

### How It Works

Each agent is tracked with:

- **Total requests**: Number of API calls
- **Total failures**: Number of failed requests
- **Consecutive failures**: Current streak of failures
- **Success rate**: Percentage of successful requests
- **Status**: healthy / degraded / unhealthy / unreachable

### Status Thresholds

| Status          | Condition                                    |
| --------------- | -------------------------------------------- |
| **healthy**     | 0 consecutive failures, >90% success rate    |
| **degraded**    | 1 consecutive failure OR <90% success rate   |
| **unhealthy**   | 3+ consecutive failures OR <50% success rate |
| **unreachable** | 5+ consecutive failures                      |

### Basic Usage

```python
from error_handler import (
    track_agent_success,
    track_agent_error,
    get_health_tracker
)

# Track successful request
try:
    response = call_external_api()
    track_agent_success("deepseek-chat")
except Exception as e:
    # Track failed request
    track_agent_error("deepseek-chat", e)

# Get agent status
tracker = get_health_tracker()
status = tracker.get_agent_status("deepseek-chat")
print(f"Status: {status['status']}")
print(f"Success rate: {status['success_rate']}%")
print(f"Failures: {status['consecutive_failures']}")
```

### Health Status Response

```python
{
    "agent_id": "deepseek-chat",
    "status": "healthy",  # or degraded/unhealthy
    "last_check_at": "2026-02-18T15:30:45",
    "last_success_at": "2026-02-18T15:30:30",
    "consecutive_failures": 0,
    "total_failures": 2,
    "total_requests": 45,
    "success_rate": 95.6,
    "is_unhealthy": False
}
```

### Automatic Failover Based on Health

```python
from error_handler import get_health_tracker

async def call_model_with_failover(prompt: str):
    tracker = get_health_tracker()
    models = ["deepseek-chat", "claude-opus-4-6", "claude-sonnet-4-20250514"]

    # Filter to healthy models only
    healthy_models = tracker.get_healthy_agents(models)

    if not healthy_models:
        logger.warning("No healthy models available!")
        # Use all models anyway, or return error
        healthy_models = models

    # Try models in order
    for model in healthy_models:
        try:
            result = await call_model(model, prompt, timeout_seconds=30.0)
            track_agent_success(model)
            return result
        except Exception as e:
            track_agent_error(model, e)
            # Continue to next model

    raise Exception("All models failed")
```

### Get Comprehensive Error Summary

```python
from error_handler import get_error_summary

summary = get_error_summary()

# Returns:
{
    "health_summary": {
        "total_agents": 5,
        "healthy_agents": 3,
        "degraded_agents": 1,
        "unhealthy_agents": 1,
        "unreachable_agents": 0,
        "total_requests": 1234,
        "total_failures": 12,
        "error_metrics": {
            "timeout": 5,
            "rate_limit": 4,
            "network": 2,
            "auth": 1
        }
    },
    "agent_statuses": {
        "deepseek-chat": { ... },
        "claude-opus-4-6": { ... },
        # ... other agents
    },
    "error_metrics": {
        "timeout": { "count": 5, "avg_retry_count": 1.2, ... },
        "rate_limit": { "count": 4, ... },
        # ... other error types
    },
    "timestamp": "2026-02-18T15:35:00"
}
```

### Add Health Check Endpoint

```python
@app.get("/api/health/agents")
async def get_agents_health():
    """Get health status of all agents"""
    from error_handler import get_error_summary
    return get_error_summary()

# Response:
{
    "health_summary": { ... },
    "agent_statuses": { ... },
    "error_metrics": { ... },
    "timestamp": "..."
}
```

---

## 5. VPS AGENT FAILOVER

### Automatic Cloudflare Fallback

When VPS agent is unreachable, automatically fallback to Cloudflare gateway.

### Configuration

```python
from error_handler import VPSAgentConfig, VPSAgentFailover

config = VPSAgentConfig(
    vps_endpoint="http://vps-agent:8000",
    cloudflare_endpoint="http://cloudflare-gateway:18789",
    health_check_timeout=5.0,
    fallback_to_cloudflare=True
)

failover = VPSAgentFailover(config)
```

### Usage

```python
async def execute_agent_task(task: str):
    failover = VPSAgentFailover()

    # Automatically tries VPS first, falls back to Cloudflare
    result = await failover.execute_with_fallback(
        agent_task_fn,
        task,
        agent_id="vps_agent"
    )

    return result
```

### Integration in Gateway

```python
@app.post("/api/code-generation")
async def generate_code(request: Message):
    failover = VPSAgentFailover()

    try:
        # Try VPS agent, fallback to Cloudflare if unavailable
        result = await failover.execute_with_fallback(
            vps_agent.generate_code,
            request.prompt,
            agent_id="vps_code_generator"
        )
        return JSONResponse({"code": result})

    except Exception as e:
        logger.error(f"Both VPS and Cloudflare failed: {e}")
        return JSONResponse({
            "error": "Code generation unavailable",
            "message": str(e)
        }, status_code=503)
```

### Health Check

```python
# Periodic health check
failover = VPSAgentFailover()

# Check VPS health
is_healthy = await failover.check_vps_health()

# Get failover status
status = failover.get_status()
print(f"VPS health: {status['vps_healthy']}")
print(f"Last check: {status['last_vps_check']}")
```

---

## 6. ERROR CLASSIFICATION

### Error Types

All errors are classified into categories for intelligent handling:

```python
from error_handler import ErrorType, classify_error

error_types = {
    ErrorType.TIMEOUT: "Request exceeded time limit",
    ErrorType.RATE_LIMIT: "429 Too Many Requests",
    ErrorType.NETWORK: "Connection refused, reset, no route",
    ErrorType.AUTHENTICATION: "401 Unauthorized, 403 Forbidden",
    ErrorType.MODEL_ERROR: "Model not found, invalid model",
    ErrorType.INTERNAL: "500 Internal Server Error",
    ErrorType.UNKNOWN: "Unclassified error"
}

# Classify an exception
error_type = classify_error(Exception("429 Too Many Requests"))
# Returns: ErrorType.RATE_LIMIT
```

### Using Error Classification

```python
from error_handler import classify_error, ErrorType

try:
    result = await api_call()
except Exception as e:
    error_type = classify_error(e)

    if error_type == ErrorType.RATE_LIMIT:
        # Exponential backoff, notify admin
        logger.warning("Rate limited, backing off")
    elif error_type == ErrorType.TIMEOUT:
        # Retry with longer timeout
        logger.warning("Timeout, retrying with longer limit")
    elif error_type == ErrorType.AUTHENTICATION:
        # Check API keys, don't retry
        logger.error("Auth failed, check credentials")
    elif error_type == ErrorType.NETWORK:
        # Network issue, retry
        logger.warning("Network error, will retry")
```

---

## 7. COMPLETE INTEGRATION EXAMPLE

### Gateway with All Error Handling

```python
from fastapi import FastAPI, HTTPException
from error_handler import (
    CodeGenerationFallback,
    execute_with_retry_async,
    execute_with_timeout_async,
    track_agent_success,
    track_agent_error,
    get_error_summary,
    TimeoutException,
    VPSAgentFailover
)

app = FastAPI()

# Initialize error handling
code_fallback = CodeGenerationFallback(model_clients={
    "deepseek-chat": deepseek_client,
    "claude-opus-4-6": anthropic_client,
})

vps_failover = VPSAgentFailover()

@app.post("/api/chat")
async def handle_chat(message: Message):
    """Handle chat with comprehensive error handling"""

    try:
        # Route based on intent
        if "code" in message.content.lower():
            # Use fallback chain for code generation
            result = code_fallback.execute(
                prompt=message.content,
                timeout_seconds=30.0,
                max_retries_per_model=2
            )

            if result.success:
                return JSONResponse({
                    "response": result.code,
                    "model": result.model_used,
                    "attempts": result.attempt_number
                })
            else:
                return JSONResponse({
                    "error": result.code,
                    "attempts": result.total_attempts
                }, status_code=503)

        else:
            # Use normal agent routing with timeout protection
            response = await execute_with_timeout_async(
                agent_router.route_and_execute,
                message.content,
                timeout_seconds=30.0
            )

            track_agent_success("agent_router")
            return JSONResponse({"response": response})

    except TimeoutException:
        logger.error(f"Request timeout: {message.content[:60]}")
        track_agent_error("agent_router", TimeoutException())
        return JSONResponse({
            "error": "Request timed out after 30 seconds",
            "message": "Try a simpler request or try again later"
        }, status_code=504)

    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        track_agent_error("agent_router", e)
        return JSONResponse({
            "error": "Internal server error",
            "message": str(e)[:100]
        }, status_code=500)


@app.get("/api/health/summary")
async def get_health_summary():
    """Get comprehensive error and health summary"""
    return get_error_summary()


@app.post("/api/code-generation")
async def generate_code(request: CodeRequest):
    """Generate code with VPS failover"""
    try:
        result = await vps_failover.execute_with_fallback(
            code_generator.generate,
            request.prompt,
            agent_id="code_generator"
        )
        return JSONResponse({"code": result})
    except Exception as e:
        logger.error(f"Code generation failed: {e}")
        return JSONResponse({
            "error": "Code generation unavailable"
        }, status_code=503)
```

---

## 8. TESTING

### Run Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run all error handler tests
pytest test_error_handler.py -v

# Run specific test class
pytest test_error_handler.py::TestRetryLogic -v

# Run with coverage
pytest test_error_handler.py --cov=error_handler --cov-report=html
```

### Test Coverage

- ✅ Retry logic (exponential backoff, exhaustion, callbacks)
- ✅ Timeout handling (async, callbacks)
- ✅ Error classification (all error types)
- ✅ Agent health tracking (status, metrics, filtering)
- ✅ Code generation fallback (chain, exhaustion)
- ✅ VPS failover (health check, status)
- ✅ Integration scenarios (retry + timeout, timeout + health)
- ✅ Performance tests (backoff, classification)

---

## 9. MONITORING & ALERTS

### Dashboard Endpoint

```python
@app.get("/dashboard.html")
async def dashboard():
    """Real-time error dashboard"""
    summary = get_error_summary()

    html = f"""
    <h1>OpenClaw Error Dashboard</h1>
    <h2>Agent Health</h2>
    <table>
        <tr><th>Agent</th><th>Status</th><th>Success Rate</th><th>Failures</th></tr>
    """

    for agent_id, status in summary["agent_statuses"].items():
        html += f"""
        <tr>
            <td>{agent_id}</td>
            <td>{status['status']}</td>
            <td>{status['success_rate']}%</td>
            <td>{status['consecutive_failures']}</td>
        </tr>
        """

    html += """
    </table>
    <h2>Error Metrics</h2>
    <ul>
    """

    for error_type, count in summary["error_metrics"].items():
        html += f"<li>{error_type}: {count}</li>"

    html += "</ul>"
    return HTMLResponse(html)
```

### Alert Rules

```
- Agent success rate < 80% → WARN (degraded)
- Agent success rate < 50% → CRITICAL (unhealthy)
- Consecutive failures >= 3 → WARN
- Consecutive failures >= 5 → CRITICAL (unreachable)
- Timeout errors > 10/hour → WARN
- Rate limit errors → WARN (may need quotas increase)
```

---

## 10. DEPLOYMENT CHECKLIST

- [ ] Import error_handler module in gateway.py
- [ ] Configure model clients in CodeGenerationFallback
- [ ] Add timeout protection to all external API calls
- [ ] Implement agent health tracking for each model
- [ ] Add /api/health/agents endpoint
- [ ] Configure VPS failover if using VPS agent
- [ ] Set up monitoring dashboard
- [ ] Run error_handler tests locally
- [ ] Deploy and monitor logs for errors
- [ ] Adjust backoff/retry settings based on production metrics
- [ ] Document error handling in API docs

---

## Quick Reference

### Key Functions

```python
# Retry with exponential backoff
result = execute_with_retry(fn, max_retries=3)

# Async retry
result = await execute_with_retry_async(fn, max_retries=3)

# Timeout protection
result = await execute_with_timeout_async(fn, timeout_seconds=30.0)

# Code generation with fallback
result = CodeGenerationFallback().execute(prompt)

# Agent health tracking
track_agent_success(agent_id)
track_agent_error(agent_id, error)

# Get comprehensive summary
summary = get_error_summary()
```

### Configuration

```python
RetryConfig(max_retries=3, initial_delay_seconds=1.0, max_delay_seconds=8.0)
VPSAgentConfig(vps_endpoint="...", cloudflare_endpoint="...")
HeartbeatMonitorConfig(check_interval_ms=30000, stale_threshold_ms=300000)
```

### Error Classification

```python
classify_error(exception) → ErrorType.{TIMEOUT, RATE_LIMIT, NETWORK, ...}
```

---

## Support

For issues or questions:

1. Check test_error_handler.py for usage examples
2. Review logs for error classification and retry attempts
3. Monitor /api/health/summary for agent status
4. Verify model clients are properly configured
5. Check network connectivity to external APIs
