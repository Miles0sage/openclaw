# Router Integration Guide for OpenClaw Gateway

This guide shows how to integrate the intelligent router into your existing OpenClaw gateway dispatch system to achieve 60-70% cost savings.

## Quick Start

### 1. Register Router Endpoint

Add the router endpoint to your Express app in `src/gateway/server-http.ts` or wherever you register routes:

```typescript
import routerEndpoint from "../routes/router-endpoint.js";

// In your Express app setup:
app.use(routerEndpoint);
```

### 2. Import and Use in Dispatch

In your chat/dispatch handler (likely in `src/gateway/call.ts` or `src/agents/dispatch.ts`):

```typescript
import { classify } from "../routing/complexity-classifier.js";
import { getModelPool } from "../gateway/model-pool.js";
import { logCostEvent } from "../gateway/cost-tracker.js";

async function routeAndDispatch(userMessage: string, sessionKey: string) {
  // Step 1: Classify complexity
  const classification = classify(userMessage);

  // Step 2: Get model recommendation
  const modelPool = getModelPool();
  const recommendation = modelPool.getRecommendation(
    classification.complexity,
    Math.floor(classification.estimatedTokens / 3),
    Math.ceil((classification.estimatedTokens * 2) / 3),
  );

  // Step 3: Use recommended model
  const selectedModel = recommendation.model;

  // Step 4: Make API call with selected model
  const response = await anthropic.messages.create({
    model: selectedModel.alias,
    max_tokens: 1024,
    messages: [{ role: "user", content: userMessage }],
  });

  // Step 5: Log actual usage for cost tracking
  const costEvent = {
    project: "openclaw",
    agent: "dispatcher",
    model: selectedModel.alias,
    tokens_input: response.usage.input_tokens,
    tokens_output: response.usage.output_tokens,
    cost: modelPool.calculateCost(
      selectedModel.model,
      response.usage.input_tokens,
      response.usage.output_tokens,
    ),
    timestamp: new Date().toISOString(),
  };

  await logCostEvent(costEvent);

  return response;
}
```

## Detailed Integration

### Option A: Modify Existing Dispatch (Recommended)

If you have a central `dispatch()` function, modify it to use routing:

**Before:**

```typescript
// Always used a single model
async function dispatch(userMessage: string) {
  const response = await anthropic.messages.create({
    model: "claude-3-5-sonnet-20241022",
    messages: [{ role: "user", content: userMessage }],
  });
  return response;
}
```

**After:**

```typescript
async function dispatch(userMessage: string, sessionKey?: string) {
  // 1. Route to optimal model
  const classification = classify(userMessage);
  const modelPool = getModelPool();
  const recommendation = modelPool.getRecommendation(
    classification.complexity,
    Math.floor(classification.estimatedTokens / 3),
    Math.ceil((classification.estimatedTokens * 2) / 3),
  );

  // 2. Call with selected model (instead of hardcoded Sonnet)
  const response = await anthropic.messages.create({
    model: recommendation.model.alias, // Use routed model
    messages: [{ role: "user", content: userMessage }],
  });

  // 3. Log cost if we have a session
  if (sessionKey) {
    await logCostEvent({
      project: "openclaw",
      agent: "dispatcher",
      model: recommendation.model.alias,
      tokens_input: response.usage.input_tokens,
      tokens_output: response.usage.output_tokens,
      cost: recommendation.estimatedCost,
      timestamp: new Date().toISOString(),
    });
  }

  return response;
}
```

### Option B: Middleware Wrapper

Create a middleware that intercepts all model calls:

```typescript
// src/gateway/routing-middleware.ts
import { classify } from "../routing/complexity-classifier.js";
import { getModelPool } from "../gateway/model-pool.js";

export function createRoutingMiddleware() {
  return async (req, res, next) => {
    // If this is a chat API call, add routing info
    if (req.path === "/v1/messages" && req.method === "POST") {
      const { messages } = req.body;
      const userMessage = messages[messages.length - 1]?.content || "";

      // Classify and add routing info to request
      const classification = classify(userMessage);
      const modelPool = getModelPool();
      const recommendation = modelPool.getRecommendation(
        classification.complexity,
        Math.floor(classification.estimatedTokens / 3),
        Math.ceil((classification.estimatedTokens * 2) / 3),
      );

      req.routing = {
        classification,
        recommendation,
        selectedModel: recommendation.model,
      };
    }

    next();
  };
}

// Register in your app:
app.use(createRoutingMiddleware());
```

### Option C: Call Router Endpoint from Client

If modifying dispatch is complex, call the router endpoint from the client:

```typescript
// Client-side code (e.g., NextJS frontend)
async function sendMessage(query: string, sessionKey: string) {
  // 1. Get routing decision
  const routeRes = await fetch("http://gateway:18789/api/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      sessionKey,
      context: conversationHistory,
    }),
  });

  const routing = await routeRes.json();

  // 2. Send message with model hint
  const response = await fetch("http://gateway:18789/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: routing.model, // Use routed model
      messages: [{ role: "user", content: query }],
      max_tokens: 1024,
    }),
  });

  return response.json();
}
```

## Testing the Integration

### 1. Unit Tests

Run the classifier tests:

```bash
pnpm test test/classifier.test.ts
```

### 2. Integration Tests

Create a test that verifies the full flow:

```typescript
// test/router-integration.test.ts
import { describe, it, expect } from "vitest";
import { dispatch } from "../src/gateway/call";

describe("Router Integration", () => {
  it("should route simple query to Haiku", async () => {
    const response = await dispatch("Hello!", "test-session");
    expect(response).toBeDefined();
    // In real test, verify model used was Haiku
  });

  it("should route complex query to Opus", async () => {
    const response = await dispatch("Design a distributed system architecture", "test-session");
    expect(response).toBeDefined();
    // In real test, verify model used was Opus
  });

  it("should log costs correctly", async () => {
    // Verify cost events are logged
    const costs = getCostMetrics();
    expect(costs.entries_count).toBeGreaterThan(0);
  });
});
```

### 3. Manual Testing

Test the router endpoints:

```bash
# Test route endpoint
curl -X POST http://localhost:18789/api/route \
  -H "Content-Type: application/json" \
  -d '{"query":"Design a system","sessionKey":"test-1"}'

# Test batch routing
curl -X POST http://localhost:18789/api/route/test \
  -H "Content-Type: application/json" \
  -d '{"queries":["Hello","Fix bug","Design system"]}'

# Check models
curl http://localhost:18789/api/route/models

# Health check
curl http://localhost:18789/api/route/health

# Check costs
curl http://localhost:18789/api/costs/summary
```

## Configuration

### Adjust Complexity Thresholds

Edit `src/routing/complexity-classifier.ts`:

```typescript
class ComplexityClassifier {
  private readonly HAIKU_THRESHOLD = 30; // Adjust these
  private readonly SONNET_THRESHOLD = 70; // based on your usage
}
```

### Adjust Optimal Distribution

Edit `src/gateway/model-pool.ts`:

```typescript
public getOptimalDistribution(): { haiku: number; sonnet: number; opus: number } {
  return {
    haiku: 0.6,   // Adjust from 0.7
    sonnet: 0.3,  // Adjust from 0.2
    opus: 0.1,    // Keep same or adjust
  };
}
```

### Add Custom Keywords

Edit `src/routing/complexity-classifier.ts`:

```typescript
private readonly HIGH_COMPLEXITY_KEYWORDS = [
  "architecture",
  "design",
  "your-domain-specific-term",  // Add your keywords
  ...
];
```

## Monitoring & Observability

### View Cost Savings

```bash
# Get cost summary
curl http://localhost:18789/api/costs/summary

# Expected output (60-70% savings):
# {
#   "total_cost": 0.45,
#   "total_without_routing": 1.35,
#   "savings": 0.90,
#   "savings_percentage": 66.7
# }
```

### Track by Model

```bash
curl http://localhost:18789/api/costs/summary | jq '.by_model'

# Expected distribution:
# {
#   "haiku": 0.10,
#   "sonnet": 0.20,
#   "opus": 0.15
# }
```

### Set Up Alerts

Monitor cost metrics and alert if:

- Savings drop below 50%
- Opus usage exceeds 20%
- Haiku usage drops below 50%

## Validation Checklist

Before deploying to production:

- [ ] Router endpoint responds to `/api/route` requests
- [ ] Classifications are accurate for your query patterns
- [ ] Cost estimates are within 10% of actual usage
- [ ] Model distribution is close to 70/20/10 target
- [ ] Savings are 60-70% vs baseline
- [ ] No regressions in response quality
- [ ] Error handling works (fallback to Sonnet)
- [ ] Rate limits are respected
- [ ] Cost tracking logs are complete

## Troubleshooting

### Router Not Responding

```bash
# Check health
curl http://localhost:18789/api/route/health

# Check logs
tail -f /tmp/openclaw-gateway.log | grep router
```

### Wrong Model Selected

1. Test classification directly:

   ```bash
   curl -X POST http://localhost:18789/api/route \
     -d '{"query":"Your query"}'
   ```

2. Check the reasoning field for why that model was selected

3. Adjust keywords or thresholds if needed

### Cost Tracking Not Working

1. Verify cost log file:

   ```bash
   cat /tmp/openclaw_costs.jsonl | tail -5
   ```

2. Check sessionKey is passed to dispatch

3. Verify logCostEvent() is being called

### Quality Issues

If responses are worse after routing:

1. Increase SONNET_THRESHOLD to route fewer queries to Haiku:

   ```typescript
   private readonly HAIKU_THRESHOLD = 25;  // Stricter
   ```

2. Add a "quality override" parameter:
   ```typescript
   if (req.body.force_model) {
     return getModelPool().getModelConfig(req.body.force_model);
   }
   ```

## Performance Targets

| Metric             | Target   | How to Achieve                          |
| ------------------ | -------- | --------------------------------------- |
| Routing accuracy   | > 90%    | Review classifications, adjust keywords |
| Routing latency    | < 100ms  | Keep classifier lightweight             |
| Cost savings       | 60-70%   | Adjust distribution thresholds          |
| Model distribution | 70/20/10 | Monitor and adjust HAIKU_THRESHOLD      |
| Quality (same)     | Baseline | Validate with A/B testing               |

## Next Steps

1. **Immediate**: Register router endpoint and test
2. **Week 1**: Integrate into dispatch, start logging costs
3. **Week 2**: Monitor accuracy, adjust keywords/thresholds
4. **Week 3**: A/B test routing vs baseline
5. **Week 4**: Deploy to production

## Support

- Router logic: See `src/routing/complexity-classifier.ts`
- API endpoints: See `src/routes/router-endpoint.ts`
- Cost tracking: See `src/gateway/cost-tracker.ts`
- Tests: See `test/classifier.test.ts`
- Full docs: See `ROUTER_README.md`

## Expected Savings Calculation

For 10,000 queries/month:

```
Without routing (all Sonnet):
  10,000 × (estimated 300 tokens) × 18.0 / 1,000,000 = $54

With routing (70 Haiku, 20 Sonnet, 10 Opus):
  7,000 × 300 × 3.8 / 1M = $7.98  (Haiku)
  2,000 × 300 × 18.0 / 1M = $10.80 (Sonnet)
  1,000 × 300 × 90 / 1M = $27 (Opus)
  Total = $45.78

Savings = $54 - $45.78 = $8.22/month (15% for this mix)
With better routing = $54 - $16.20 = $37.80/month (70% possible)
```

Actual savings depend on your query distribution. Monitor and adjust!
