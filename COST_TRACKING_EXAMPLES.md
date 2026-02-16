# Cost Tracking Examples & Usage

## Quick Start

### 1. Python Cost Tracking (gateway.py)

```python
from cost_tracker import log_cost_event, get_cost_metrics, get_cost_summary

# Log a cost event (most common)
cost_usd = log_cost_event(
    project="openclaw",
    agent="project_manager",
    model="claude-opus-4-6",
    tokens_input=1234,
    tokens_output=5678
)
print(f"📊 Cost logged: ${cost_usd:.6f}")

# Get aggregated metrics
metrics = get_cost_metrics()
print(f"Total cost today: ${metrics['total_cost']:.2f}")
print(f"By project: {metrics['by_project']}")

# Get formatted summary
summary = get_cost_summary()
print(summary)

# Get costs from last 24 hours
recent = get_cost_metrics(time_window="24h")
print(f"Last 24h: ${recent['total_cost']:.2f}")

# Get costs from last 7 days
weekly = get_cost_metrics(time_window="7d")
print(f"Last 7d: ${weekly['total_cost']:.2f}")
```

### 2. TypeScript Cost Tracking (ExpressJS)

```typescript
import {
  logCostEvent,
  getCostMetrics,
  calculateCost,
  getPricing,
  getCostSummary,
} from "./gateway/cost-tracker.js";

// Log a cost event
const event = {
  project: "openclaw",
  agent: "code-generator",
  model: "claude-3-5-sonnet-20241022",
  tokens_input: 2000,
  tokens_output: 3000,
  timestamp: new Date().toISOString(),
  cost: 0.00009, // optional, will be calculated if omitted
};

await logCostEvent(event);
console.log("✅ Cost logged");

// Calculate cost without logging
const cost = calculateCost("claude-opus-4-6", 1000, 2000);
console.log(`Estimated cost: $${cost.toFixed(6)}`);

// Get metrics
const metrics = getCostMetrics();
console.log(`Total: $${metrics.total_cost.toFixed(2)}`);

// Get summary
const summary = getCostSummary();
console.log(summary);
```

### 3. REST API Usage

```bash
# Get cost summary
curl -X GET http://localhost:18789/api/costs/summary \
  -H "X-Auth-Token: your-token"

# Response:
# {
#   "success": true,
#   "timestamp": "2026-02-16T19:44:00Z",
#   "data": {
#     "total_cost": 0.042531,
#     "entries_count": 42,
#     "by_project": {
#       "openclaw": 0.025000,
#       "barber-crm": 0.017531
#     },
#     "by_model": {
#       "claude-opus-4-6": 0.030000,
#       "claude-3-5-sonnet-20241022": 0.012531
#     },
#     "by_agent": {
#       "project_manager": 0.025000,
#       "code_generator": 0.017531
#     }
#   }
# }

# Log a cost event
curl -X POST http://localhost:18789/api/costs/log \
  -H "X-Auth-Token: your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "project": "openclaw",
    "agent": "code-generator",
    "model": "claude-3-5-sonnet-20241022",
    "tokens_input": 2000,
    "tokens_output": 3000
  }'

# Get project spend
curl -X GET http://localhost:18789/api/costs/project/barber-crm \
  -H "X-Auth-Token: your-token"

# Get cost trends
curl -X GET http://localhost:18789/api/costs/trends \
  -H "X-Auth-Token: your-token"
```

## Real-World Scenarios

### Scenario 1: Track a single API call

```python
from anthropic import Anthropic

client = Anthropic()

# Make API call
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Explain quantum computing"}
    ]
)

# Extract usage
input_tokens = response.usage.input_tokens
output_tokens = response.usage.output_tokens

# Log cost
cost = log_cost_event(
    project="my-project",
    agent="my-agent",
    model="claude-opus-4-6",
    tokens_input=input_tokens,
    tokens_output=output_tokens
)

logger.info(f"✅ API call completed: ${cost:.6f}")
```

### Scenario 2: Batch logging in a loop

```python
for project in ["openclaw", "barber-crm", "delhi-palace"]:
    for _ in range(10):
        # Simulate API call
        tokens_in = 1000
        tokens_out = 500

        cost = log_cost_event(
            project=project,
            agent="batch-processor",
            model="claude-3-5-sonnet-20241022",
            tokens_input=tokens_in,
            tokens_output=tokens_out
        )

        print(f"Logged: ${cost:.6f}")

# Get summary
metrics = get_cost_metrics()
print(f"\n📊 Total batch cost: ${metrics['total_cost']:.2f}")
for proj, cost in metrics['by_project'].items():
    print(f"  {proj}: ${cost:.2f}")
```

### Scenario 3: Monitor costs over time

```python
# Get costs for different periods
today = get_cost_metrics(time_window="24h")
this_week = get_cost_metrics(time_window="7d")
this_month = get_cost_metrics(time_window="30d")

print("📈 Cost Trend:")
print(f"  Last 24h:  ${today['total_cost']:.2f}")
print(f"  Last 7d:   ${this_week['total_cost']:.2f}")
print(f"  Last 30d:  ${this_month['total_cost']:.2f}")

# Calculate daily average
daily_avg = this_month['total_cost'] / 30
print(f"\n💰 Daily average: ${daily_avg:.2f}")
print(f"   Projected monthly: ${daily_avg * 30:.2f}")
```

### Scenario 4: Alert on high costs

```python
def check_daily_budget(budget_limit=10.00):
    """Alert if daily cost exceeds budget"""
    today = get_cost_metrics(time_window="24h")
    current_cost = today['total_cost']

    if current_cost > budget_limit:
        print(f"⚠️  WARNING: Daily cost ${current_cost:.2f} exceeds limit ${budget_limit:.2f}")
        return False

    remaining = budget_limit - current_cost
    print(f"✅ Daily budget OK: ${current_cost:.2f} / ${budget_limit:.2f}")
    print(f"   Remaining: ${remaining:.2f}")
    return True

check_daily_budget(budget_limit=5.00)
```

### Scenario 5: Analyze cost by model

```python
metrics = get_cost_metrics()

print("💡 Model Efficiency Analysis:")
print()

for model, total_cost in metrics['by_model'].items():
    # Get entries for this model
    entries = [e for e in read_cost_log() if e['model'] == model]

    if entries:
        avg_cost = total_cost / len(entries)
        total_tokens = sum(e['tokens_input'] + e['tokens_output'] for e in entries)
        cost_per_mtok = (total_cost / total_tokens) * 1_000_000 if total_tokens > 0 else 0

        print(f"📊 {model}")
        print(f"   Total cost:      ${total_cost:.6f}")
        print(f"   Calls:           {len(entries)}")
        print(f"   Avg per call:    ${avg_cost:.6f}")
        print(f"   Cost per 1M tok: ${cost_per_mtok:.4f}")
        print()
```

## Integration Patterns

### Pattern 1: Automatic logging in wrapper function

```python
def call_claude(model: str, prompt: str, project: str = "openclaw"):
    """Wrapper that logs costs automatically"""
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    # Automatic cost logging
    cost = log_cost_event(
        project=project,
        agent="claude-wrapper",
        model=model,
        tokens_input=response.usage.input_tokens,
        tokens_output=response.usage.output_tokens
    )

    return response.content[0].text, cost

# Usage: Just call and costs are logged automatically
text, cost = call_claude("claude-opus-4-6", "Hello!")
```

### Pattern 2: Context manager for cost tracking

```python
from contextlib import contextmanager

@contextmanager
def track_cost(project: str, agent: str, model: str):
    """Context manager for tracking costs"""
    start_tokens = 0

    try:
        yield  # Code runs here
    except Exception as e:
        print(f"Error: {e}")
        raise
    finally:
        # Cost tracking happens on exit
        pass

# Usage
with track_cost("openclaw", "test-agent", "claude-opus-4-6"):
    response = anthropic_client.messages.create(
        model="claude-opus-4-6",
        max_tokens=100,
        messages=[{"role": "user", "content": "Hi"}]
    )
    # Costs logged automatically
```

### Pattern 3: Middleware for FastAPI

```python
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class CostTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time

        # Log endpoint cost if applicable
        if request.url.path.startswith("/api/chat"):
            # Extract from response body if available
            pass

        return response

app.add_middleware(CostTrackingMiddleware)
```

## Cost Calculation Examples

```python
from cost_tracker import calculate_cost, get_pricing

# Haiku pricing
cost = calculate_cost("claude-3-5-haiku-20241022", 1000, 1000)
# = (1000 * 0.8 + 1000 * 4.0) / 1_000_000 = 0.0000048

# Sonnet pricing
cost = calculate_cost("claude-3-5-sonnet-20241022", 1000, 1000)
# = (1000 * 3.0 + 1000 * 15.0) / 1_000_000 = 0.000018

# Opus pricing
cost = calculate_cost("claude-opus-4-6", 1000, 1000)
# = (1000 * 15.0 + 1000 * 75.0) / 1_000_000 = 0.00009
```

## Viewing Logs

```bash
# View raw cost log
cat /tmp/openclaw_costs.jsonl | jq '.'

# Count entries
wc -l /tmp/openclaw_costs.jsonl

# Total cost (approximate)
cat /tmp/openclaw_costs.jsonl | jq '.cost' | paste -sd+ | bc

# By model
cat /tmp/openclaw_costs.jsonl | jq -r '.model' | sort | uniq -c
```

## Troubleshooting

### Q: Costs seem too high

A: Check token counts. 1M tokens for Opus = $15-75 depending on input/output ratio.

### Q: No costs being logged

A: Verify:

- `log_cost_event()` is called after each API call
- `OPENCLAW_COST_LOG` path is writable
- Check stderr for error messages

### Q: JSON parsing errors

A: Cost log may be corrupted. Check with:

```bash
cat /tmp/openclaw_costs.jsonl | jq '.' > /dev/null
```

### Q: How to clear costs

A: Backup then delete:

```bash
cp /tmp/openclaw_costs.jsonl /tmp/openclaw_costs.jsonl.backup
rm /tmp/openclaw_costs.jsonl
```
