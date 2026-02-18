# OpenClaw Feature Implementation Roadmap

**Created:** 2026-02-18
**Status:** Ready to execute
**Total effort:** 70-90 hours across 10 features
**Expected cost savings:** 30-40% reduction ($7/month)

---

## Timeline Overview

```
Week 1 (Mon-Fri)
├── Mon: Streaming Responses (#2)
├── Tue: Prompt Caching (#3)
├── Wed: Semantic Memory (#1) — STARTS WEDNESDAY, CONTINUES TO FRIDAY
├── Thu: Semantic Memory continues + Observability (#4) STARTS
└── Fri: Testing + Deployment of #1-3

Week 2 (Mon-Fri)
├── Mon: Observability (#4) complete + Graceful Degradation (#5) STARTS
├── Tue: Graceful Degradation continues
├── Wed: Health Monitor (#6) STARTS
├── Thu: LangGraph Router (#9) STARTS
└── Fri: Testing + Deployment of #4-6

Week 3+ (Optional)
├── Agentic RAG + Web Search (#7) — 16-20 hours
├── Session Analytics (#10) — 8-10 hours
└── Multimodal RAG (#8) — 20+ hours
```

---

## PHASE 1: Week 1 (Mon-Wed) — Streaming + Caching + Semantic Memory

### Feature #2: Streaming Responses (Mon, 4-6h)

**What's happening:**

```
User query → Gateway → Agent → Token stream → SSE → Client UI
                                     ^
                                     └─ Streams tokens live
```

**Files to create:**

1. `src/utils/sse-stream.ts` (200 LOC)
   - SSE format encoder
   - Chunking utilities
   - Error handling

2. `src/routes/chat-stream.ts` (150 LOC)
   - `/api/chat/stream` endpoint
   - EventSource handler

**Files to modify:**

1. `src/gateway/api.ts` (add route)
2. `src/agents/` (yield tokens instead of return)

**Testing:**

```bash
# Test endpoint
curl -N "http://localhost:18789/api/chat/stream?query=hello%20world"

# Should output:
# data: {"token":"Hello","position":0}
# data: {"token":" ","position":1}
# data: {"token":"world","position":2}
```

**Success criteria:**

- [ ] First token arrives <100ms after request
- [ ] Complete response streams in <5s
- [ ] Works with Slack/Telegram/Discord
- [ ] Load test: 50 concurrent streams

**Estimated time:** 4-6h
**Easy/Medium/Hard:** Easy ⭐

---

### Feature #3: Prompt Caching (Tue, 3-4h)

**What's happening:**

```
Query → Hash(query + context) → Redis lookup → Hit? Return cached : Call agent → Cache result
```

**Files to create:**

1. `src/cache/prompt-cache.ts` (180 LOC)
   - Redis client wrapper
   - Cache key generation
   - TTL management (30s)

2. `src/cache/deduplication.ts` (120 LOC)
   - Query fingerprinting
   - Collision detection

**Files to modify:**

1. `src/gateway/api.ts` (check cache before agent call)

**Testing:**

```bash
# Send same query twice within 30s
curl -X POST http://localhost:18789/api/chat -d '{"query":"explain RAG"}'
curl -X POST http://localhost:18789/api/chat -d '{"query":"explain RAG"}'

# Check cache stats
curl http://localhost:18789/api/cache/stats
# {"hit_rate": 0.50, "hits": 1, "misses": 1}
```

**Success criteria:**

- [ ] Cache hit rate >15% after 1 hour load testing
- [ ] Redis latency <5ms
- [ ] TTL working (cached items expire after 30s)
- [ ] Cost reduction: 5-10% first day

**Estimated time:** 3-4h
**Easy/Medium/Hard:** Easy ⭐

---

### Feature #1: Semantic Session Memory (Wed-Fri, 8-12h)

**What's happening:**

```
Current: /tmp/openclaw_sessions/{key}.json (linear history)
         ↓ (problem: grows to 100k tokens, no semantic search)

After:   Zep Cloud (semantic graph, auto-summarization, memory search)
         ↓ (benefit: O(1) retrieval, 70% token savings)
```

**Phase A: Setup (Wed, 4h)**

1. `src/memory/zep-client.ts` (250 LOC)
   - Zep API wrapper
   - User/session lifecycle
   - Error handling

2. `src/memory/memory-indexer.ts` (180 LOC)
   - Semantic indexing
   - Metadata extraction
   - Source tracking

**Phase B: Migration (Thu, 4h)**

1. `src/gateway/session-manager.ts` (update existing ~150 LOC)
   - Replace JSON file calls with Zep calls
   - Backward compatibility layer

2. Migration script (100 LOC)
   - Migrate existing sessions from JSON → Zep
   - Verify data integrity

**Phase C: Testing (Fri, 2-3h)**

- Test 10+ conversations
- Verify token savings (target: 70% reduction)
- Load test with 100 concurrent sessions

**Files to modify:**

1. `src/gateway/session-manager.ts`
2. `config.json` (add Zep API key)

**Testing:**

```typescript
// After migration, should work the same externally
const sessionKey = "user_123:chat_456";
const messages = await sessionManager.getHistory(sessionKey);
// Messages have metadata: sources, timestamps, user preferences
```

**Success criteria:**

- [ ] All existing sessions migrated successfully
- [ ] Token usage: 70% reduction in long conversations
- [ ] Semantic search works (find old contexts by topic)
- [ ] Zep latency <500ms p95

**Estimated time:** 8-12h
**Easy/Medium/Hard:** Medium ⭐⭐

**Zep signup:**

```bash
# 1. Sign up at https://www.getzep.com
# 2. Create project → get API key
# 3. Export ZEP_API_KEY=<key>
# 4. Free tier: 100k messages/month
```

---

## PHASE 2: Week 2 (Wed-Fri) — Observability + Resilience

### Feature #4: Real-Time Observability (Wed-Fri, 10-14h)

**What's happening:**

```
Gateway metrics → Prometheus → Grafana dashboard
Cost tracking: tokens spent → USD conversion → daily budget alerts
Latency tracking: p50/p95/p99 per agent, per model
```

**Files to create:**

1. `src/observability/metrics-collector.ts` (300 LOC)
   - Prometheus client integration
   - Histogram: query latency
   - Counter: tokens, costs, errors

2. `src/observability/cost-tracker.ts` (200 LOC)
   - Token → USD conversion
   - Per-agent cost aggregation
   - Budget tracking

3. `src/routes/metrics.ts` (150 LOC)
   - `/api/metrics/dashboard` JSON endpoint
   - `/metrics` Prometheus scrape endpoint

**Files to modify:**

1. `src/gateway/api.ts` (measure latency + cost)
2. `docker-compose.yml` (add Prometheus + optional Grafana)

**Testing:**

```bash
# Check Prometheus metrics
curl http://localhost:9090/api/v1/query?query=openclaw_tokens_total

# Get cost dashboard
curl http://localhost:18789/api/metrics/dashboard
# {
#   "cost_24h_usd": 0.35,
#   "tokens_24h": 12500,
#   "avg_latency_ms": 280,
#   "queries_24h": 150
# }
```

**Success criteria:**

- [ ] All metrics exported to Prometheus
- [ ] Cost tracking accurate within 1% of API billing
- [ ] Latency metrics p95 <500ms per agent
- [ ] Dashboard available at `http://localhost:3000` (Grafana)
- [ ] Alerts trigger if cost >$20/day

**Estimated time:** 10-14h
**Easy/Medium/Hard:** Medium ⭐⭐

---

### Feature #5: Graceful Degradation (Thu-Fri, 12-15h)

**What's happening:**

```
Telegram timeout → Queue message → Retry every 30s
Agent Opus timeout → Fall back to Sonnet → Fall back to Haiku
All channels down → Queue requests → Retry when channels recover
```

**Files to create:**

1. `src/resilience/circuit-breaker.ts` (180 LOC)
   - State machine: closed → open → half-open
   - Failure tracking + reset
   - Per-channel circuit breakers

2. `src/resilience/fallback-router.ts` (150 LOC)
   - Agent fallback chain: Opus → Sonnet → Haiku
   - Automatic selection based on availability

3. `src/resilience/queue-manager.ts` (200 LOC)
   - Async message queue (use existing Upstash from Moltbot)
   - Retry with exponential backoff
   - DLQ (dead letter queue) for permanent failures

**Files to modify:**

1. `src/gateway/api.ts` (integrate circuit breaker + queue)
2. `config.json` (fallback routing rules)

**Testing:**

```bash
# Simulate Telegram failure
curl -X POST http://localhost:18789/api/test/fail/telegram

# Message should be queued, not lost
curl http://localhost:18789/api/queue/status
# {"pending": 3, "processing": 0, "dlq": 0}

# Recover Telegram
curl -X POST http://localhost:18789/api/test/recover/telegram

# Messages should retry and succeed
curl http://localhost:18789/api/queue/status
# {"pending": 0, "processing": 0, "dlq": 0}
```

**Success criteria:**

- [ ] Telegram failure → Message queued (not lost)
- [ ] Agent timeout → Fallback to next agent <100ms
- [ ] Circuit breaker prevents cascading failures
- [ ] Uptime >99.5% (even with channel failures)
- [ ] Message retention: 100% in queue (0% message loss)

**Estimated time:** 12-15h
**Easy/Medium/Hard:** Medium ⭐⭐

---

### Feature #6: Agent Health Monitor (Thu-Fri, 3-5h)

**Status:** Partially done (heartbeat_monitor.py exists)

**What's needed:**

1. Wire `heartbeat_monitor.py` into gateway
2. Expose status at `/api/health/agents`
3. Add alerting on failures

**Files to modify:**

1. `src/gateway/health.ts` (add agent status endpoint)
2. `heartbeat_monitor.py` (optional: improve logging)

**Testing:**

```bash
# Check agent health
curl http://localhost:18789/api/health/agents
# [
#   {"agent": "pm", "status": "healthy", "latency_ms": 145, "last_check": "2026-02-18T18:37:00Z"},
#   {"agent": "codegen", "status": "healthy", "latency_ms": 203, "last_check": "2026-02-18T18:37:00Z"},
#   {"agent": "security", "status": "timeout", "latency_ms": null, "last_check": "2026-02-18T18:36:45Z"}
# ]
```

**Success criteria:**

- [ ] Health checks every 30s
- [ ] Timeout detection <30s
- [ ] Auto-recovery on timeout
- [ ] 99.9% uptime

**Estimated time:** 3-5h (mostly integration, logic already exists)
**Easy/Medium/Hard:** Easy ⭐

---

## PHASE 3: Week 3+ (Optional Advanced Features)

### Feature #9: LangGraph Smart Router (Wed, 4-6h)

**Status:** Partially done (Phase 5X router exists as Python)

**What's needed:**

1. Expand `agent_router.py` with more rules
2. Add TypeScript wrapper at `src/routing/agent-selector.ts`
3. Integrate into gateway (replace hardcoded PM agent)

**Impact:** 50-70% cost reduction by routing to cheaper agents

- Simple FAQ → Haiku (10% cost)
- Regular question → Sonnet (30% cost)
- Complex code → CodeGen (0% API cost, local Ollama)
- Security analysis → Security agent

**Testing:**

```bash
# Route a simple query
curl -X POST http://localhost:18789/api/route -d '{"query":"what is RAG?"}'
# {"agent": "haiku", "model": "claude-3.5-haiku", "confidence": 0.95}

# Route complex query
curl -X POST http://localhost:18789/api/route -d '{"query":"write a WebAssembly module that..."}'
# {"agent": "codegen", "model": "ollama/qwen32b", "confidence": 0.88}
```

**Estimated time:** 4-6h
**Easy/Medium/Hard:** Medium ⭐⭐

---

### Feature #7: Agentic RAG + Web Search (Week 3+, 16-20h)

**What's needed:**

1. Integrate Linkup web search API
2. Agent checks confidence → if low, search web
3. Return results with sources

**Impact:** Current knowledge, cited sources, research-grade answers

**Files to create:**

- `src/agents/web-search-tool.ts`
- `src/agents/agentic-rag.ts`

**Effort:** 16-20 hours (complex integration)
**Cost:** +$5-15/month (web search API)

---

### Feature #10: Session Analytics (Week 3+, 8-10h)

**What's needed:**

1. Track events: query_received, response_generated, error_occurred
2. Export to Mixpanel or PostHog
3. Dashboard showing user engagement

**Impact:** Understand user behavior, optimize retention

**Files to create:**

- `src/analytics/event-tracker.ts`
- `src/routes/analytics.ts`

**Effort:** 8-10 hours
**Cost:** +$20-50/month (analytics platform)

---

## Implementation Commands

### Day 1: Setup

```bash
cd /root/openclaw

# Install dependencies
npm install ioredis prom-client zep-cloud

# Create directory structure
mkdir -p src/{utils,cache,memory,observability,resilience,analytics}

# Create feature branches
git checkout -b feature/streaming-responses
git checkout -b feature/prompt-caching
git checkout -b feature/semantic-memory
```

### Day 2-3: Development

```bash
# Build and test each feature
npm run build
npm run test

# Deploy to staging
vercel deploy --scope openclaw
```

### Day 4-5: Validation

```bash
# Run performance tests
npm run test:performance

# Monitor metrics
curl http://localhost:18789/api/metrics/dashboard

# Deploy to production
git merge && git push
# Northflank auto-deploys from GitHub
```

---

## Success Metrics Dashboard

Track these KPIs after deployment:

| Metric                  | Baseline | Target | Timeline |
| ----------------------- | -------- | ------ | -------- |
| **Monthly cost**        | $20      | $6-12  | Week 3   |
| **Uptime**              | 99%      | 99.9%  | Week 2   |
| **First-token latency** | 1500ms   | <100ms | Week 1   |
| **Cache hit rate**      | 0%       | >15%   | Week 1   |
| **Token savings**       | 0%       | 50-70% | Week 2   |
| **Error rate**          | 0.5%     | <0.1%  | Week 2   |

---

## Risk Mitigation

| Risk                            | Probability | Impact | Mitigation                        |
| ------------------------------- | ----------- | ------ | --------------------------------- |
| Zep API outage                  | Low         | High   | Fallback to JSON sessions         |
| Cache collision bugs            | Medium      | Medium | Extensive testing, manual clear   |
| Circuit breaker false positives | Medium      | Medium | Monitor metrics, tune thresholds  |
| Breaking changes in gateway     | High        | High   | Feature flags for gradual rollout |
| Agent model timeouts            | High        | Medium | Implement health check + fallback |

---

## Deployment Strategy

**Option A: Big Bang (Risky)**

- Deploy all features at once
- Faster to complete
- High risk of cascading failures

**Option B: Phased (Recommended)**

1. Deploy streaming (#2) → Measure UX improvement
2. Deploy caching (#3) → Measure cost savings
3. Deploy semantic memory (#1) → Measure token efficiency
4. Deploy observability (#4) → Measure everything
5. Deploy resilience (#5-6) → Stabilize

**Rollout approach:**

- Week 1: Deploy to staging only (test thoroughly)
- Friday: Deploy #1-3 to 10% production traffic
- Monday: Deploy #1-3 to 50% traffic (if no errors)
- Tuesday: Deploy #1-3 to 100% traffic
- Weeks 2-3: Repeat for #4-6

---

## Documentation & Handoff

After each phase, create:

1. **Architecture docs** — How each feature works
2. **API docs** — New endpoints (OpenAPI spec)
3. **Monitoring docs** — What metrics to watch
4. **Runbook** — How to troubleshoot
5. **Cost analysis** — Savings breakdown

---

## Questions for Implementation

**Before starting, clarify:**

1. Zep Cloud budget: Free tier adequate for pilot?
2. Redis persistence: Use managed Redis or self-hosted?
3. Prometheus/Grafana: Deploy new containers or use existing monitoring?
4. Web search: Budget for Linkup/Tavily API?
5. Feature flags: Priority for gradual rollout?

---

## Next Steps (Execute Now)

1. ✅ **Done:** Analysis complete (this document)
2. 🎯 **Next:** Prioritize features based on constraints
3. 🚀 **Start:** Monday morning — Feature #2 (Streaming)
4. 📊 **Measure:** Daily cost + uptime tracking
5. 🔄 **Iterate:** Based on metrics

**Estimated time to break-even:** 5-7 days (via caching + streaming)
**Estimated time for full implementation:** 3-4 weeks (all 10 features)

---

**Ready to start? Pick a feature from Week 1 and begin coding!**
