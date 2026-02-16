# Cost Tracking Integration Guide

This guide explains how to integrate the cost tracking module into the OpenClaw gateway.

## Files Created

1. **cost_tracker.py** - Cost tracking module for the gateway
2. **src/gateway/cost-tracker.ts** - TypeScript cost tracking module
3. **src/routes/cost-dashboard.ts** - REST API endpoints for cost dashboard
4. **Project settings files** - `.claude/settings.json` for each project

## Integration Steps

### Step 1: Import cost tracker in gateway.py

Add this import at the top of `gateway.py`:

```python
from cost_tracker import log_cost_event, get_cost_metrics, get_cost_summary
```

### Step 2: Log costs after API calls

In the `call_model_for_agent()` function (around line 186), after calling the model, add cost logging:

```python
def call_model_for_agent(agent_key: str, prompt: str, conversation: list = None) -> tuple[str, int]:
    # ... existing code ...

    # Route to correct provider
    if provider == "ollama":
        ollama_prompt = f"{full_prompt}{ollama_suffix}"
        response_text, tokens = call_ollama(model, ollama_prompt, endpoint)
        # No cost tracking for Ollama (local model)

    elif provider == "anthropic":
        # Call Anthropic
        if conversation:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=4096,
                system=anthropic_system,
                messages=conversation
            )
            response_text = response.content[0].text
            tokens_output = response.usage.output_tokens
            tokens_input = response.usage.input_tokens
        else:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=4096,
                system=anthropic_system,
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = response.content[0].text
            tokens_output = response.usage.output_tokens
            tokens_input = response.usage.input_tokens

        # Log cost event
        cost = log_cost_event(
            project="openclaw",
            agent=agent_key,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output
        )
        logger.info(f"💰 Cost logged: ${cost:.4f} ({agent_key} / {model})")

        return response_text, tokens_output
```

### Step 3: Log costs for REST endpoint (chat_endpoint)

In the `/api/chat` endpoint (around line 338), add cost logging:

```python
@app.post("/api/chat")
async def chat_endpoint(message: Message):
    """REST chat with optional session memory"""
    agent_id = message.agent_id or "project_manager"
    session_key = message.sessionKey or "default"

    try:
        # ... existing code ...

        # Call model with last 10 messages for context
        response_text, tokens = call_model_for_agent(
            agent_id,
            message.content,
            chat_history[session_key][-10:]
        )

        # (cost logging happens in call_model_for_agent now)

        # ... rest of function ...
```

### Step 4: Log costs for WebSocket (handle_websocket)

In the `handle_websocket()` function (around line 414), add cost logging:

```python
# After calling call_model_for_agent (line 507)
response_text, tokens = call_model_for_agent(
    active_agent,
    message_text,
    chat_history[session_key][-10:]
)

# (cost logging happens in call_model_for_agent now)
```

### Step 5: Add cost summary endpoint

Add this new endpoint to gateway.py:

```python
@app.get("/api/costs/summary")
async def costs_summary():
    """Get cost metrics summary"""
    try:
        metrics = get_cost_metrics()
        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat(),
            "data": metrics
        }
    except Exception as e:
        logger.error(f"Error getting cost metrics: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/costs/text")
async def costs_text():
    """Get cost summary as text"""
    try:
        summary = get_cost_summary()
        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat(),
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Error getting cost summary: {e}")
        return {"success": False, "error": str(e)}
```

### Step 6: Enable cost tracking (Optional: startup)

Add this to the `if __name__ == "__main__":` section:

```python
if __name__ == "__main__":
    import uvicorn
    from datetime import datetime

    print("🦞 OpenClaw Gateway FIXED - Now using ACTUAL models from config!")
    print(f"   Protocol: OpenClaw v{PROTOCOL_VERSION}")
    print("   WebSocket: ws://0.0.0.0:18789/ws")
    print(f"   Cost Log: {get_cost_log_path()}")
    print("")
    print("📊 Agent Configuration:")
    for agent_id, config in CONFIG.get("agents", {}).items():
        provider = config.get("apiProvider", "unknown")
        model = config.get("model", "unknown")
        emoji = config.get("emoji", "")
        print(f"   {emoji} {agent_id:20} → {provider:10} → {model}")
    print("")
    print("💰 Cost Tracking Enabled")
    print("")
    uvicorn.run(app, host="0.0.0.0", port=18789, log_level="info")
```

## Environment Variables

Set these environment variables to customize cost tracking:

```bash
# Custom cost log file location (default: /tmp/openclaw_costs.jsonl)
export OPENCLAW_COST_LOG="/path/to/costs.jsonl"

# Admin token for clearing costs (optional)
export ADMIN_TOKEN="your-secret-token"
```

## Pricing Constants

The following pricing is used (Feb 2026 Claude API rates):

| Model             | Input    | Output   |
| ----------------- | -------- | -------- |
| claude-3-5-haiku  | $0.80/M  | $4.00/M  |
| claude-3-5-sonnet | $3.00/M  | $15.00/M |
| claude-opus-4-6   | $15.00/M | $75.00/M |

## API Endpoints

### Get Cost Summary

```
GET /api/costs/summary
```

Returns JSON with total cost, breakdown by project/model/agent

### Get Cost Text Summary

```
GET /api/costs/text
```

Returns text-formatted cost summary

### Get Project Spend

```
GET /api/costs/project/{name}
```

Returns spend for a specific project

## Log File Format

Costs are logged to JSONL (newline-delimited JSON):

```json
{
  "project": "openclaw",
  "agent": "project_manager",
  "model": "claude-opus-4-6",
  "tokens_input": 150,
  "tokens_output": 250,
  "cost": 0.000009,
  "timestamp": "2026-02-16T19:44:00.000000Z"
}
```

## Troubleshooting

### No costs being logged

1. Check that `log_cost_event()` is called after API calls
2. Verify `OPENCLAW_COST_LOG` path is writable
3. Check logs for "Cost logged:" messages

### Incorrect costs

1. Verify model names match pricing constants
2. Check token counts from API response
3. Ensure timestamps are UTC

### Import errors

1. Verify `cost_tracker.py` is in the same directory as `gateway.py`
2. Check Python path includes the openclaw directory

## Testing

Test cost logging manually:

```python
from cost_tracker import log_cost_event, get_cost_metrics

# Log a test event
cost = log_cost_event(
    project="openclaw",
    agent="test",
    model="claude-3-5-sonnet-20241022",
    tokens_input=100,
    tokens_output=200
)
print(f"Logged cost: ${cost:.6f}")

# Get metrics
metrics = get_cost_metrics()
print(f"Total cost: ${metrics['total_cost']:.6f}")
```

## Notes

- Costs are calculated in USD
- All costs are rounded to 6 decimal places
- JSONL format allows easy parsing and streaming
- No breaking changes to existing gateway functionality
- Cost tracking is non-blocking (errors don't affect responses)
