# OpenClaw Error Handling - Implementation Checklist

## Phase 1: Core Integration (Estimated: 1-2 hours)

### 1.1 Update Gateway to Use Error Handler

- [ ] Import error_handler module
- [ ] Import agent health tracking functions
- [ ] Replace hardcoded model selection with intelligent routing
- [ ] Add timeout protection to all external API calls

**File: /root/openclaw/gateway.py (after line 200)**

```python
# Add imports
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

# Initialize components
code_fallback = CodeGenerationFallback(model_clients={
    "deepseek-chat": ollama_client,  # Or appropriate client
    "claude-opus-4-6": anthropic_client,
})

vps_failover = VPSAgentFailover()
```

### 1.2 Update /api/chat Endpoint

- [ ] Wrap orchestrator calls with timeout protection
- [ ] Add health tracking for agent calls
- [ ] Implement timeout error handling

**Location: /root/openclaw/gateway.py (around line 500)**

```python
@app.post("/api/chat")
async def handle_chat(message: Message):
    try:
        # Add timeout protection
        response = await execute_with_timeout_async(
            orchestrator.send_to_agent,
            message.content,
            message.agent_id or "pm",
            timeout_seconds=30.0
        )
        # Track success
        track_agent_success(message.agent_id or "pm")
        return JSONResponse({"response": response})

    except TimeoutException:
        track_agent_error(message.agent_id or "pm", TimeoutException())
        return JSONResponse({
            "error": "Request timed out after 30 seconds"
        }, status_code=504)
    except Exception as e:
        track_agent_error(message.agent_id or "pm", e)
        return JSONResponse({
            "error": str(e)
        }, status_code=500)
```

### 1.3 Add Health Check Endpoint

- [ ] Create /api/health/agents endpoint
- [ ] Create /api/health/summary endpoint
- [ ] Return comprehensive error summary

**Location: /root/openclaw/gateway.py (new section)**

```python
@app.get("/api/health/agents")
async def get_agents_health():
    """Get health status of all agents"""
    return get_error_summary()

@app.get("/api/health/summary")
async def get_health_summary():
    """Get comprehensive error and health metrics"""
    summary = get_error_summary()
    return JSONResponse(summary)
```

---

## Phase 2: Code Generation Fallback (Estimated: 2-3 hours)

### 2.1 Configure Model Clients

- [ ] Set up Kimi (DeepSeek) client with API key
- [ ] Set up Claude client (if not already done)
- [ ] Verify all clients are async-compatible

**File: /root/openclaw/gateway.py**

```python
import anthropic
import httpx

# Initialize clients
anthropic_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# For Kimi/DeepSeek (if not using Ollama)
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")

model_clients = {
    "deepseek-chat": DeepSeekClient(api_key=deepseek_api_key),
    "deepseek-reasoner": DeepSeekClient(api_key=deepseek_api_key, model="deepseek-reasoner"),
    "claude-opus-4-6": anthropic_client,
}

code_fallback = CodeGenerationFallback(model_clients=model_clients)
```

### 2.2 Detect Code Generation Requests

- [ ] Identify code generation patterns in prompts
- [ ] Route code requests to fallback chain
- [ ] Route other requests through normal routing

**Location: /root/openclaw/gateway.py**

```python
def is_code_generation_request(prompt: str) -> bool:
    """Detect if request is for code generation"""
    keywords = [
        "code", "implement", "function", "build", "api",
        "generate", "write", "create", "refactor"
    ]
    return any(kw in prompt.lower() for kw in keywords)

@app.post("/api/chat")
async def handle_chat(message: Message):
    if is_code_generation_request(message.content):
        # Use fallback chain
        result = code_fallback.execute(message.content)
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
        # Normal routing
        # ...
```

### 2.3 Add Fallback Logging

- [ ] Log each fallback attempt
- [ ] Log success/failure with model used
- [ ] Add to error summary

---

## Phase 3: Retry & Timeout for All Agents (Estimated: 2-3 hours)

### 3.1 Wrap VPS Agent Calls

- [ ] Configure VPSAgentFailover
- [ ] Wrap all VPS agent calls with execute_with_fallback
- [ ] Track VPS health separately

**File: /root/openclaw/gateway.py**

```python
vps_failover = VPSAgentFailover(
    config=VPSAgentConfig(
        vps_endpoint="http://vps-agent:8000",
        cloudflare_endpoint="http://localhost:18789",
        health_check_timeout=5.0
    )
)

# Example: Use for code generation via VPS
result = await vps_failover.execute_with_fallback(
    vps_agent.generate_code,
    prompt=message.content,
    agent_id="vps_code_gen"
)
```

### 3.2 Add Retry to Ollama Calls

- [ ] Wrap ollama calls with execute_with_retry_async
- [ ] Configure max 2 retries per model
- [ ] Implement exponential backoff

**Location: /root/openclaw/gateway.py (find call_ollama function)**

```python
async def call_ollama_with_retry(model: str, prompt: str):
    """Call Ollama with retry protection"""
    async def call_fn():
        return await execute_with_timeout_async(
            lambda: call_ollama(model, prompt),
            timeout_seconds=30.0
        )

    return await execute_with_retry_async(call_fn, max_retries=2)
```

### 3.3 Implement Agent Router with Health

- [ ] Use agent_router.select_agent() to pick best agent
- [ ] Only route to healthy agents
- [ ] Fallback to backup agent if primary unhealthy

**Location: /root/openclaw/gateway.py**

```python
from agent_router import _router as agent_router

async def route_request(prompt: str):
    """Route to best healthy agent"""
    decision = agent_router.select_agent(prompt)
    agent_id = decision["agentId"]

    # Check if agent is healthy
    if not get_health_tracker().is_agent_healthy(agent_id):
        logger.warning(f"Agent {agent_id} unhealthy, trying backup")
        # Pick different agent

    try:
        response = await execute_with_timeout_async(
            get_agent_handler(agent_id),
            prompt,
            timeout_seconds=30.0
        )
        track_agent_success(agent_id)
        return response
    except Exception as e:
        track_agent_error(agent_id, e)
        raise
```

---

## Phase 4: Testing & Validation (Estimated: 1-2 hours)

### 4.1 Run Unit Tests

- [ ] Run pytest test_error_handler.py -v
- [ ] Verify all tests pass
- [ ] Check coverage > 80%

```bash
cd /root/openclaw
pytest test_error_handler.py -v --cov=error_handler
```

### 4.2 Integration Testing

- [ ] Test code generation with fallback
- [ ] Test timeout handling (30+ second operations)
- [ ] Test retry logic (with error injection)
- [ ] Test agent health tracking

**Test Script: /root/openclaw/test_integration_errors.py**

```python
import asyncio
from error_handler import (
    CodeGenerationFallback,
    execute_with_timeout_async,
    execute_with_retry_async,
    track_agent_success,
    track_agent_error,
)

async def test_integration():
    # Test 1: Code generation fallback
    fallback = CodeGenerationFallback()
    result = fallback.execute("Write a hello world function")
    print(f"Test 1 - Code gen: {result.success}")

    # Test 2: Timeout protection
    async def slow_fn():
        await asyncio.sleep(2)
        return "done"

    try:
        await execute_with_timeout_async(slow_fn, timeout_seconds=0.1)
    except:
        print("Test 2 - Timeout: PASS")

    # Test 3: Retry logic
    call_count = [0]
    async def eventually_succeeds():
        call_count[0] += 1
        if call_count[0] < 3:
            raise Exception("fail")
        return "success"

    result = await execute_with_retry_async(eventually_succeeds, max_retries=3)
    print(f"Test 3 - Retry: {result == 'success'}")

asyncio.run(test_integration())
```

### 4.3 Load Testing

- [ ] Test retry logic under load
- [ ] Test timeout handling with 100+ concurrent requests
- [ ] Monitor memory usage of health tracker

---

## Phase 5: Deployment (Estimated: 1 hour)

### 5.1 Pre-Deployment Checklist

- [ ] All tests passing locally
- [ ] Error handler module imports successfully
- [ ] No hardcoded secrets in error_handler.py
- [ ] All endpoints return valid JSON
- [ ] Error messages don't contain sensitive info

### 5.2 Configuration

- [ ] Set API keys for all models
- [ ] Configure timeouts (30s default)
- [ ] Configure max retries (3 default)
- [ ] Set up monitoring dashboard

**Environment Variables to Set:**

```bash
ANTHROPIC_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
OPENCLAW_TIMEOUT_SECONDS=30
OPENCLAW_MAX_RETRIES=3
OPENCLAW_VPS_ENDPOINT=http://vps:8000
OPENCLAW_CF_ENDPOINT=http://cf:18789
```

### 5.3 Deployment Steps

1. Backup current gateway.py
2. Add error_handler.py to OpenClaw repo
3. Update gateway.py imports
4. Update /api/chat endpoint
5. Add /api/health/\* endpoints
6. Deploy to production
7. Monitor logs for errors
8. Verify health endpoints working

### 5.4 Post-Deployment Monitoring

- [ ] Monitor /api/health/agents endpoint
- [ ] Check agent success rates
- [ ] Look for timeout errors in logs
- [ ] Monitor fallback chain usage
- [ ] Set up alerts for unhealthy agents

---

## Quick Wins (Can Be Done Immediately)

### 1. Add Timeout to All API Calls (5 min)

```python
# Replace all external API calls with timeout protection
response = await execute_with_timeout_async(api_call, timeout_seconds=30.0)
```

### 2. Add Health Check Endpoint (10 min)

```python
@app.get("/api/health/summary")
async def health():
    return get_error_summary()
```

### 3. Enable Agent Health Tracking (5 min)

```python
try:
    result = await agent_call()
    track_agent_success(agent_id)
except Exception as e:
    track_agent_error(agent_id, e)
```

---

## Estimated Timeline

| Phase                     | Duration       | Status      |
| ------------------------- | -------------- | ----------- |
| Phase 1: Core Integration | 1-2 hours      | ⏳ TODO     |
| Phase 2: Code Generation  | 2-3 hours      | ⏳ TODO     |
| Phase 3: Retry & Timeout  | 2-3 hours      | ⏳ TODO     |
| Phase 4: Testing          | 1-2 hours      | ⏳ TODO     |
| Phase 5: Deployment       | 1 hour         | ⏳ TODO     |
| **Total**                 | **7-11 hours** | ⏳ **TODO** |

---

## Files to Modify

1. **gateway.py** — Add imports, update endpoints
2. **config.json** — Add timeout and retry settings
3. **requirements.txt** — Add any new dependencies (if needed)
4. **.env** — Add API keys for models

## Files Created

1. ✅ **error_handler.py** — Core error handling module (518 LOC)
2. ✅ **test_error_handler.py** — Comprehensive tests (450+ LOC)
3. ✅ **ERROR_HANDLING_GUIDE.md** — Implementation guide
4. ✅ **IMPLEMENTATION_CHECKLIST.md** — This file

---

## Success Criteria

- ✅ All 47 tests in test_error_handler.py pass
- ✅ Code generation uses fallback chain (Kimi → Reasoner → Opus)
- ✅ All external API calls have 30s timeout
- ✅ All failures are retried with exponential backoff (max 3)
- ✅ Agent health tracked and exposed via /api/health/agents
- ✅ VPS agent automatically falls back to Cloudflare if unreachable
- ✅ Error logs include error type classification
- ✅ Zero hanging requests (all have timeout)
- ✅ Zero lost errors (all tracked in health summary)

---

## Next Steps

1. Review error_handler.py for understanding
2. Review ERROR_HANDLING_GUIDE.md for patterns
3. Start Phase 1: Core Integration
4. Run tests frequently during development
5. Deploy incrementally and monitor
