# Router Deployment Checklist

Complete deployment guide for the OpenClaw Intelligent Router with 60-70% cost reduction.

## Pre-Deployment Verification (1-2 hours)

### Code Quality

- [ ] All TypeScript files compile: `pnpm build`
- [ ] Linting passes: `pnpm check`
- [ ] Type checking clean: `pnpm tsgo`
- [ ] No console errors or warnings

### Testing

- [ ] Unit tests pass: `pnpm test test/classifier.test.ts`
- [ ] Tests have >80% coverage
- [ ] All 150+ test cases passing
- [ ] No flaky tests

### Integration

- [ ] Router endpoint compiles with existing code
- [ ] ModelPool singleton doesn't conflict
- [ ] CostTracker integration doesn't break existing logging
- [ ] Cost tracker type definitions match existing interface

### Documentation

- [ ] ROUTER_README.md is comprehensive
- [ ] ROUTER_INTEGRATION.md has clear steps
- [ ] ROUTER_EXAMPLES.md covers main use cases
- [ ] API responses match documented schema

## Pre-Production Setup (30 minutes)

### Environment Configuration

- [ ] Set `OPENCLAW_COST_LOG=/tmp/openclaw_costs.jsonl`
- [ ] Verify cost log directory permissions (writable)
- [ ] Set appropriate log rotation if needed

### Database/Storage

- [ ] Cost log directory exists and is writable
- [ ] No database migrations needed (uses JSONL)
- [ ] Backup strategy for cost logs defined

### Monitoring

- [ ] Prometheus/metrics endpoint configured (if applicable)
- [ ] Log aggregation set up (ELK/Datadog/etc.)
- [ ] Cost tracking dashboard accessible
- [ ] Alerts configured for anomalies

## Staging Deployment (2-4 hours)

### 1. Deploy to Staging

```bash
# Copy files to staging
cp src/routing/complexity-classifier.ts staging/src/routing/
cp src/gateway/model-pool.ts staging/src/gateway/
cp src/routes/router-endpoint.ts staging/src/routes/
cp test/classifier.test.ts staging/test/

# Build staging
cd staging
pnpm install
pnpm build
```

### 2. Register Router Endpoint

In `src/gateway/server-http.ts` or router setup:

```typescript
import routerEndpoint from "../routes/router-endpoint.js";

// Register routes
app.use(routerEndpoint);
```

### 3. Verify Endpoints

```bash
# Health check
curl http://staging:18789/api/route/health

# Expected response:
# { "success": true, "status": "healthy", "models_available": 3 }

# Test routing
curl -X POST http://staging:18789/api/route \
  -H "Content-Type: application/json" \
  -d '{"query":"Hello, world!"}'

# Expected: Haiku model with low complexity
```

### 4. Load Testing

```bash
# Generate 1000 test queries
for i in {1..1000}; do
  curl -X POST http://staging:18789/api/route \
    -H "Content-Type: application/json" \
    -d '{"query":"Test query '$i'"}'
done

# Check performance
# Expected: < 100ms p95 latency, no errors
```

### 5. Monitor Staging Metrics

```bash
# Check router performance
curl http://staging:18789/api/route/health

# Check cost tracking
curl http://staging:18789/api/costs/summary

# Expected: Small cost log with test data
```

## Production Deployment Strategy

### Option A: Gradual Rollout (Recommended)

**Phase 1: Canary (10% of traffic, 2-4 hours)**

```bash
# Deploy router code
git push origin feature/router

# Enable routing for 10% of users
ROUTER_ENABLED_PERCENTAGE=10

# Monitor
- Check error rates (should be 0)
- Verify model distribution (70/20/10)
- Compare response quality (should be same)
- Verify cost tracking logs are populated
```

**Phase 2: Ramp-up (50% of traffic, 4-8 hours)**

```bash
ROUTER_ENABLED_PERCENTAGE=50

# Validate
- Check distribution accuracy
- Monitor cost savings (should be 60-70%)
- Verify no quality degradation
- Check latency (should be <100ms)
```

**Phase 3: Full Rollout (100% of traffic, 1-4 hours)**

```bash
ROUTER_ENABLED_PERCENTAGE=100

# Final checks
- All metrics nominal
- Cost tracking complete
- No error spikes
- Performance acceptable
```

### Option B: Feature Flag Approach

```typescript
// In dispatch.ts
if (process.env.ENABLE_ROUTER === "true") {
  const classification = classify(userMessage);
  const model = getModelPool().selectModel(classification.complexity);
} else {
  const model = "claude-3-5-sonnet-20241022"; // Fallback to Sonnet
}
```

Control via environment variable for instant disable if needed.

### Option C: Big Bang (Not Recommended)

Deploy all at once if:

- Staging tests are 100% successful
- You have quick rollback capability
- Off-peak deployment window

## Production Deployment Steps

### 1. Pre-Flight Check

```bash
# Verify all files present
ls -la src/routing/complexity-classifier.ts
ls -la src/gateway/model-pool.ts
ls -la src/routes/router-endpoint.ts
ls -la test/classifier.test.ts

# Verify no conflicts with existing code
grep -r "complexity-classifier" src/ | grep -v routing/
grep -r "model-pool" src/ | grep -v gateway/

# Run full test suite
pnpm test

# Build verification
pnpm build
```

### 2. Deploy Code

```bash
# Via git (recommended)
git checkout main
git pull origin main
git checkout -b deploy/router-$(date +%Y%m%d)
git add src/routing/complexity-classifier.ts
git add src/gateway/model-pool.ts
git add src/routes/router-endpoint.ts
git commit -m "feat: Deploy intelligent router (Phase 3)"
git push origin deploy/router-$(date +%Y%m%d)

# Create PR for review
gh pr create --title "Deploy Intelligent Router" \
  --body "Production deployment of 60-70% cost reduction router"

# After approval and merge, deploy
git checkout main
git pull origin main
npm run build
npm run deploy
```

### 3. Enable Routing

```bash
# Set environment variable
export ROUTER_ENABLED_PERCENTAGE=10  # Start with canary

# Restart gateway (method depends on your setup)
systemctl restart openclaw-gateway
# OR
docker restart openclaw-gateway
# OR
fly machines restart <machine-id>
```

### 4. Verify Production

```bash
# Health check
curl https://api.openclaw.example.com/api/route/health

# Test routing
curl -X POST https://api.openclaw.example.com/api/route \
  -H "Content-Type: application/json" \
  -d '{"query":"Hello from production!"}'

# Check cost logs
tail -f /var/log/openclaw/costs.jsonl

# Monitor metrics
# - Error rate should be 0%
# - Latency should be < 100ms
# - Distribution should be 70/20/10
```

### 5. Gradual Ramp-up

```bash
# After 2 hours at 10%:
export ROUTER_ENABLED_PERCENTAGE=50
systemctl restart openclaw-gateway

# After 4 hours at 50%:
export ROUTER_ENABLED_PERCENTAGE=100
systemctl restart openclaw-gateway
```

## Post-Deployment Monitoring (First 24-48 hours)

### Metrics to Monitor

**Cost Metrics:**

- [ ] Total cost trending down (60-70% savings)
- [ ] Model distribution: Haiku 70%, Sonnet 20%, Opus 10%
- [ ] Cost log populated with events
- [ ] No spike in Opus usage

**Quality Metrics:**

- [ ] Error rate stable (no increase)
- [ ] User complaints: 0 (or less than baseline)
- [ ] Response quality: Same or better
- [ ] Latency: < 100ms p95

**Performance Metrics:**

- [ ] Router latency: < 50ms
- [ ] No gateway/router timeouts
- [ ] Memory usage stable
- [ ] CPU usage stable

### Dashboards to Check

```bash
# Daily summary
curl https://api.openclaw.example.com/api/costs/summary

# Expected output:
{
  "total_cost": 12.45,
  "by_model": {
    "haiku": 2.10,    # ~70%
    "sonnet": 6.70,   # ~20%
    "opus": 3.65      # ~10%
  },
  "entries_count": 8342
}

# Calculate savings
# Without routing: 8342 × avg_tokens × sonnet_rate
# With routing: 12.45
# Savings: (baseline - 12.45) / baseline
```

## Rollback Plan

If issues arise, rollback immediately:

### Immediate Rollback

```bash
# Disable router
export ROUTER_ENABLED_PERCENTAGE=0

# Or, revert to Sonnet-only dispatch
export ENABLE_ROUTER=false

# Restart gateway
systemctl restart openclaw-gateway

# Verify
curl https://api.openclaw.example.com/api/route/health
```

### Reasons to Rollback

- [ ] Error rate spikes above baseline
- [ ] Cost tracking fails (logs not generated)
- [ ] Model routing clearly wrong (90%+ going to Opus)
- [ ] User complaints spike
- [ ] Gateway crashes/hangs
- [ ] Unexpected latency increase

### Rollback Verification

```bash
# Check error logs
tail -100 /var/log/openclaw/error.log | grep router

# Verify dispatch fallback
curl -X POST https://api.openclaw.example.com/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"test"}]}'

# Should work with Sonnet (fallback)
```

## Success Criteria

Mark deployment successful when:

- [ ] **Cost Reduction**: 60-70% savings vs Sonnet-only
- [ ] **Distribution**: 70% Haiku, 20% Sonnet, 10% Opus
- [ ] **Accuracy**: 90%+ correct model selection
- [ ] **Quality**: No degradation in response quality
- [ ] **Latency**: Router < 50ms, gateway < 100ms
- [ ] **Reliability**: 99.9% uptime
- [ ] **Tracking**: All costs logged correctly
- [ ] **Errors**: 0 routing-related errors

## Post-Deployment (Week 1)

### Daily Tasks

- [ ] Check cost metrics: `curl /api/costs/summary`
- [ ] Verify model distribution is 70/20/10
- [ ] Check error logs for router issues
- [ ] Monitor user feedback/complaints
- [ ] Adjust thresholds if needed

### Weekly Review

- [ ] Generate cost savings report
- [ ] Analyze misclassifications
- [ ] Review model performance
- [ ] Plan any adjustments
- [ ] Document learnings

### Optimization Opportunities

After week 1, consider:

1. **Fine-tune keywords** - Adjust HIGH_COMPLEXITY_KEYWORDS based on actual misclassifications
2. **Adjust thresholds** - If distribution is skewed, modify HAIKU_THRESHOLD
3. **Add domain-specific logic** - If certain query patterns are consistently misrouted
4. **Enable A/B testing** - Test different routing strategies
5. **Integrate with gateway metrics** - Use gateway's own latency metrics for decisions

## Maintenance

### Regular Tasks

**Daily:**

- Monitor cost logs
- Check error rate
- Verify distribution

**Weekly:**

- Review cost trends
- Check for anomalies
- Update documentation

**Monthly:**

- Performance review
- Model pricing updates (if changed)
- Keyword refinement
- User feedback analysis

### Updating Models/Pricing

If Claude API pricing changes:

1. Update `CLAUDE_PRICING` in `src/gateway/model-pool.ts`
2. Update documentation in `ROUTER_README.md`
3. Recalculate expected savings
4. No code changes needed (dynamic lookup)

```typescript
// Easy to update when prices change
const CLAUDE_PRICING = {
  haiku: {
    input: 0.8, // Updated here
    output: 4.0, // Updated here
  },
  // ...
};
```

## Troubleshooting Guide

### Problem: Low Cost Savings (< 40%)

**Diagnosis:**

```bash
curl /api/costs/summary | jq '.by_model'
# If too much Opus/Sonnet, classification is wrong
```

**Fix:**

1. Review misclassifications
2. Add domain-specific keywords
3. Adjust HAIKU_THRESHOLD lower

### Problem: Quality Complaints

**Diagnosis:**

```bash
# Check which model is being used
curl -X POST /api/route -d '{"query":"complaint query"}'
```

**Fix:**

1. If Haiku: increase HAIKU_THRESHOLD
2. If Sonnet: model is correct, might be unrelated
3. If Opus: investigate why Haiku was chosen

### Problem: High Latency

**Diagnosis:**

- Router latency > 100ms: Classifier is slow
- Gateway latency spike: Model API slow

**Fix:**

- Simplify keyword matching
- Reduce query length limits
- Check API provider status

## Success Stories

Expected outcomes after 1 month:

```
Before Router:
- All queries use Sonnet
- Cost: $1,000/month
- Distribution: 0/100/0

After Router (Week 1):
- Cost: $350/month (65% savings)
- Distribution: 68/20/12
- Quality: Same
- Errors: 0

After Router (Month 1):
- Cost: $320/month (68% savings)
- Distribution: 70/20/10
- Quality: Same+
- Errors: 0
- User satisfaction: Maintained
```

## Final Checklist

Before declaring success:

- [ ] Cost savings target achieved (60-70%)
- [ ] Model distribution correct (70/20/10)
- [ ] No error spikes
- [ ] Quality maintained or improved
- [ ] Cost tracking complete
- [ ] Documentation updated
- [ ] Team trained
- [ ] Monitoring alerts configured
- [ ] Rollback procedure tested
- [ ] Post-deployment cleanup done

---

**Deployment Summary:**

- **Estimated Downtime:** 0-5 minutes (graceful restart)
- **Rollback Time:** < 1 minute
- **Monitoring Period:** 24-48 hours
- **Expected ROI:** 60-70% API cost reduction
- **Team Size:** 1 engineer to deploy, 1 to monitor

**Success Criteria Met When:**

- Savings: 60-70% ✓
- Accuracy: 90%+ ✓
- Quality: Baseline ✓
- Errors: 0 ✓
- Uptime: 99.9%+ ✓
