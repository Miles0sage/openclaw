# OpenClaw Parallel Execution - Quick Reference

## What Changed?

### Before (Serial)

```
User Request
    ↓
PM Receives → PM Decides
    ↓
CodeGen Builds → Returns
    ↓
Security Audits → Returns
    ↓
Database Sets Up → Returns
    ↓
PM Synthesizes → Sends to Client

Total Time: ~240 seconds
```

### After (Parallel)

```
User Request
    ↓
PM Receives → PM Decomposes into 4 parallel tasks
    ↓ ↓ ↓ ↓ (All 4 run simultaneously)
CodeGen | CodeGen | Security | Database
Frontend Backend  Audit    Schema
    ↓ ↓ ↓ ↓ (Results return as ready)
Results Aggregated
    ↓
PM Synthesizes (conflict-aware)
    ↓
Sends to Client

Total Time: ~150 seconds (37% faster)
```

---

## 5-Minute Overview

### What Tasks Can Parallelize?

**Good Candidates:**

- Building frontend + backend simultaneously
- Code review while building
- Database setup while coding
- Testing while features complete

**Not Parallelizable:**

- Creating database schema, then running migrations (schema first)
- Deploying, then configuring (config first)
- Authentication setup, then permission rules (auth first)

**Mixed:** Some tasks have dependencies, others don't

- "Build & test frontend" can run with "Design database" in parallel
- But "Migrate data" must wait for "Design schema"

### How It Works

1. **PM Agent Thinks**
   - "What independent work streams exist?"
   - "What can run in parallel vs what must sequence?"
   - "How to best use our 3 agents?"

2. **Tasks Distributed**
   - CodeGen queue: "Build frontend", "Build backend"
   - Security queue: "Audit security vulnerabilities"
   - Database queue: "Design schema"

3. **Parallel Execution**
   - All 4 tasks run concurrently
   - First task done at ~45s
   - Last task done at ~120s (bottleneck)
   - Result: 120s total (vs 240s serial)

4. **Results Merged**
   - Security audit finds: "Add CSRF protection"
   - CodeGen backend has: "No CSRF yet"
   - Merge: Add CSRF to backend code
   - Conflict resolved ✓

5. **PM Synthesizes**
   - Combine all agent outputs
   - Create client-facing response
   - Send completed project

---

## File Structure

```
/root/openclaw/

NEW FILES:
├── parallel_executor.py          ← Core orchestrator (manages parallel work)
├── worker_pools.py               ← 3 agent pools (CodeGen, Security, Database)
├── task_distributor.py           ← Routes tasks to pools (intent detection)
├── result_aggregator.py          ← Merges results (conflict resolution)
├── pm_coordinator.py             ← PM's new decomposition role
├── failure_handler.py            ← Timeout/error recovery
├── test_parallel_executor.py     ← All the tests
└── PARALLEL-EXECUTION-GUIDE.md   ← User documentation

MODIFIED FILES:
├── config.json                   ← Add parallel_execution section
├── gateway.py                    ← Add /api/execute-parallel endpoint
└── agent_router.py               ← Detect when to use parallel mode
```

---

## Task Distribution Logic

### Intent Classification Examples

**CodeGen Tasks:**

- "Build frontend with React"
- "Implement API endpoint"
- "Create database migration"
- "Fix bug in authentication"
- "Deploy to production"

**Security Tasks:**

- "Audit for vulnerabilities"
- "Test payment security"
- "Check OWASP compliance"
- "Penetration test"
- "Review code for XSS"

**Database Tasks:**

- "Design Supabase schema"
- "Optimize slow queries"
- "Setup real-time subscriptions"
- "Create backup strategy"
- "Migrate PostgreSQL data"

**Multi-Agent (Needs Decomposition):**

- "Build restaurant website" → CodeGen (frontend) + CodeGen (backend) + Database + Security
- "Audit and fix security" → Security (find) + CodeGen (fix) + Security (verify)
- "Full e-commerce setup" → CodeGen + Database + Security + CodeGen again

---

## Example Execution: Restaurant Website

### Request

```
User: "Build a restaurant website with online booking and secure payments"
```

### PM Decomposition

```
The PM agent (Claude Opus with extended thinking) analyzes:

"I see 4 independent work streams:
1. Frontend (Next.js with menu display, booking form)
   - Can start immediately
   - Depends on: Backend API ready (softer dependency)
   - Timeline: 60 minutes

2. Backend (FastAPI with booking API, payment processing)
   - Can start immediately
   - Depends on: Database schema (soft)
   - Timeline: 90 minutes

3. Database (Supabase schema for restaurants, menus, orders, payments)
   - Can start immediately
   - No hard dependencies
   - Timeline: 45 minutes

4. Security Audit (test payment flow, XSS, SQL injection, CSRF)
   - Depends on: Backend code available (for testing)
   - Timeline: 120 minutes after backend

Parallel Plan:
- t=0s: Start Frontend, Backend, Database in parallel
- t=45s: Database done, can inform Backend optimization
- t=60s: Frontend done, waiting on Backend API definitions
- t=90s: Backend done, now Security can audit
- t=210s: Security done
- CRITICAL: Can't parallelize everything!
  Backend must finish before Security can test it

Optimized:
- Start Frontend (60m)
- Start Backend (90m)
- Start Database (45m) - parallel with both
- Start Security AFTER Backend completes (120m)
  But Database ready early → Backend optimized

Timeline: Frontend, Backend, Database parallel = 90s wall clock
          Then Security = 120s more = 210s total
          Vs Serial: 60 + 90 + 45 + 120 = 315s
          Savings: 105 seconds (33% faster)
```

### Parallel Tasks Created

```json
{
  "tasks": [
    {
      "id": "task_1",
      "pool": "codegen",
      "description": "Build Next.js frontend with menu gallery, booking form",
      "priority": 1,
      "timeout_sec": 300
    },
    {
      "id": "task_2",
      "pool": "codegen",
      "description": "Build FastAPI backend with booking API, payment processing",
      "priority": 1,
      "timeout_sec": 300,
      "blocked_by": []
    },
    {
      "id": "task_3",
      "pool": "database",
      "description": "Design Supabase schema: restaurants, menus, orders, payments",
      "priority": 1,
      "timeout_sec": 180
    },
    {
      "id": "task_4",
      "pool": "security",
      "description": "Security audit: payment flow (fraud, injection), XSS, CSRF, OWASP",
      "priority": 2,
      "timeout_sec": 300,
      "blocked_by": ["task_2"],
      "context": {
        "focus": "payment_security",
        "required_audit": ["owasp_top_10", "sql_injection", "xss", "csrf"]
      }
    }
  ]
}
```

### Execution Timeline

```
t=0s    PM decomposes → 4 tasks queued

t=0s    [CODEGEN] Picks up task_1 (Frontend)
t=0s    [CODEGEN] Picks up task_2 (Backend) ← Can do both!
t=0s    [DATABASE] Picks up task_3 (Schema)

                Frontend building...
                Backend building...
                Schema designing...

t=45s   [DATABASE] ✅ DONE (task_3)
        - Returns: SQL schema with indexes
        - CodeGen Backend now has optimal schema
        - Security audit blocked until task_2 done

                Frontend: 50% done
                Backend: 45% done

t=60s   [CODEGEN] ✅ DONE (task_1)
        - Returns: Next.js component files, styles
        - Frontend complete!
        - Waiting on Backend API to integrate

t=90s   [CODEGEN] ✅ DONE (task_2)
        - Returns: FastAPI route definitions, models, auth
        - Backend complete!
        - task_4 unblocked!

t=90s   [SECURITY] Picks up task_4 (Audit)
        - Now has real backend code to audit
        - Begins: payment flow testing, injection testing

                Frontend: Complete ✅
                Backend: Complete ✅
                Schema: Complete ✅
                Security: Running...

t=150s  [SECURITY] Finds vulnerabilities:
        - CSRF tokens missing on booking form
        - No rate limiting on payment endpoint
        - SQL injection possible in menu search
        - XSS in review comments

        Returns: Findings + fixes (merge with CodeGen output)

t=151s  [AGGREGATOR] Merges results:
        ✅ Frontend code (task_1)
        ✅ Backend code (task_2)
        ✅ Database schema (task_3)
        ✅ Security audit (task_4)

        Conflicts found:
        - Security: "Add CSRF tokens"
        - CodeGen Backend: "No CSRF implemented"
        → Resolution: Merge CSRF protection into Backend code

        Conflicts found:
        - Security: "Add rate limiting"
        - CodeGen Backend: "No rate limiting"
        → Resolution: Add rate limiting middleware to FastAPI

        Dependencies:
        - Frontend needs Backend API definitions ✓ (both done)
        - Backend needs Database schema ✓ (both done)
        - Security audit needed Backend ✓ (audit happened last)

t=152s  [PM] Synthesizes final response:
        - Combine all 4 outputs
        - Create deployment instructions
        - Summarize timeline & cost
        - Highlight security measures

        Output:
        """
        🎯 **Restaurant Website Complete!**

        Built in parallel (3 min wall clock!):
        ✅ Frontend: Next.js app with real-time booking
        ✅ Backend: FastAPI with secure payment processing
        ✅ Database: Supabase schema optimized for queries
        ✅ Security: Audited & hardened (CSRF, rate limit, XSS protection)

        Timeline: 152 seconds (vs 315 serial)
        Cost: $3.20
        Status: Ready to deploy
        """

t=155s  Response sent to client
```

---

## Failure Scenarios

### Scenario 1: Backend Timeout

```
t=0s   All 4 tasks start
t=45s  Database done ✓
t=60s  Frontend done ✓
t=300s Backend TIMEOUT (5 min limit exceeded)

Action:
1. Backend task marked FAILED
2. Auto-retry begins (retry 1 of 2)
3. Retry runs from t=300s to t=450s
4. Still TIMEOUT - retry 2 of 2
5. Retry again - still fails
6. Task marked DEAD

At t=450s:
- Frontend: ✅ Done
- Database: ✅ Done
- Security: ❌ Blocked (needs backend)
- Backend: ❌ Dead

Result:
- Partial delivery: "Frontend & Database ready"
- Partial refund: 60% of project fee
- Note to client: "Backend generation failed - manual review needed"
```

### Scenario 2: Security Flags Critical Vulnerability

```
t=90s  Backend complete
t=90s  Security audit starts
t=150s Security finds: "CRITICAL: SQL injection in user search"

Action:
1. Dependency update: Task_2 (Backend) flagged for remediation
2. Execution paused - not fully complete
3. PM queues new task: "CodeGen: Fix SQL injection in user search"
4. CodeGen processes fix
5. Security re-audits fixed code
6. Conflict resolved

Total timeline: ~210 seconds (instead of 150s)
Cost: +$1.20 (additional CodeGen & Security tokens)
Quality: Higher (caught vulnerability)
```

### Scenario 3: Database Schema Rejected by CodeGen

```
t=45s  Database returns: "Tables: users, restaurants, menus, orders"
t=90s  CodeGen Backend reads schema and says:
       "This schema lacks proper indexing for performance"

Action:
1. Dependency detected: Database optimization needed
2. Database queues: "Optimize schema: add indexes on query columns"
3. Database re-analyzes (5 min)
4. Returns: "Updated schema with 8 new indexes"
5. CodeGen Backend regenerates API using optimized schema
6. Results merged

Result: Better performance, slightly higher cost
```

---

## Cost Comparison

### Small Project: "Build a contact form"

| Approach | Tasks        | Duration | Tokens | Cost  |
| -------- | ------------ | -------- | ------ | ----- |
| Serial   | PM + CodeGen | 120s     | 25K    | $0.40 |
| Parallel | PM + CodeGen | 120s     | 25K    | $0.40 |
| Overhead | +1%          | same     | same   | same  |

**Result:** No speedup (single agent sufficient)

### Medium Project: "REST API + frontend + security audit"

| Approach | Tasks                         | Duration       | Tokens     | Cost          |
| -------- | ----------------------------- | -------------- | ---------- | ------------- |
| Serial   | PM→CodeGen→CodeGen→Security   | 300s           | 65K        | $1.05         |
| Parallel | PM→[CodeGen,CodeGen,Security] | 180s           | 70K        | $1.10         |
| Speedup  | 4 agents                      | **40% faster** | +8% tokens | **4% more $** |

**Result:** Faster delivery, worth extra 4% cost

### Large Project: "Full website + backend + audit + database"

| Approach | Tasks                  | Duration       | Tokens     | Cost          |
| -------- | ---------------------- | -------------- | ---------- | ------------- |
| Serial   | PM→4 sequential agents | 600s           | 120K       | $2.40         |
| Parallel | PM→[4 parallel agents] | 220s           | 130K       | $2.50         |
| Speedup  | All 4 agents           | **63% faster** | +8% tokens | **4% more $** |

**Result:** Much faster, negligible cost increase, much better value

---

## Configuration Examples

### Basic (config.json)

```json
{
  "parallel_execution": {
    "enabled": true,
    "worker_pools": {
      "codegen": {
        "max_concurrent": 3,
        "timeout_sec": 300,
        "max_retries": 2
      },
      "security": {
        "max_concurrent": 2,
        "timeout_sec": 300,
        "max_retries": 2
      },
      "database": {
        "max_concurrent": 2,
        "timeout_sec": 180,
        "max_retries": 2
      }
    }
  }
}
```

### Advanced (Custom Timeouts)

```json
{
  "parallel_execution": {
    "enabled": true,
    "auto_fallback_to_serial": true,
    "worker_pools": {
      "codegen": {
        "max_concurrent": 5,
        "timeout_sec": 600,
        "max_retries": 3,
        "model": "MiniMax-M2.5"
      },
      "security": {
        "max_concurrent": 1,
        "timeout_sec": 900,
        "max_retries": 1,
        "model": "qwen2.5-coder:14b"
      }
    }
  }
}
```

---

## API Usage

### Start Parallel Execution

```bash
curl -X POST http://localhost:8000/api/execute-parallel \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Build a restaurant website with booking",
    "sessionKey": "user123",
    "project": "delhi-palace",
    "force_parallel": true
  }'
```

**Response:**

```json
{
  "execution_id": "exec_user123_1708157435",
  "status": "executing",
  "parallel_tasks": 4,
  "estimated_duration_sec": 150,
  "tasks": [
    { "id": "task_1", "pool": "codegen", "status": "running", "progress": 30 },
    { "id": "task_2", "pool": "codegen", "status": "queued" },
    { "id": "task_3", "pool": "security", "status": "queued" },
    { "id": "task_4", "pool": "database", "status": "running", "progress": 15 }
  ]
}
```

### Check Status

```bash
curl http://localhost:8000/api/execution/exec_user123_1708157435
```

**Response:**

```json
{
  "execution_id": "exec_user123_1708157435",
  "status": "completed",
  "duration_sec": 155,
  "tasks_completed": 4,
  "tasks_failed": 0,
  "cost": "$2.80",
  "final_response": "🎯 **Restaurant Website Ready!**\n\n✅ Frontend...",
  "quality_score": 0.98
}
```

---

## Troubleshooting

### "Tasks keep timing out"

**Check:**

1. `max_concurrent` too high (agents starving for resources)?
2. Model overloaded (check Anthropic/MiniMax API status)?
3. Network latency (check gateway logs)?

**Fix:** Reduce `max_concurrent`, increase `timeout_sec`, check external APIs

### "Results don't match serial execution"

**Expected:** Slightly different (parallel agents have different context)
**Check:** Are conflict resolutions correct? Aggregator decisions sound?

### "Security audit happened before backend done"

**This is a bug:** Task dependencies not being enforced
**Check:** `task_distributor` is setting `blocked_by` correctly

### "Cost higher than expected"

**Expected:** +5-10% overhead for parallel coordination
**Check:** Are retries happening? Is aggregator re-running agents?

---

## Monitoring

### Key Metrics

```
parallel_execution_duration_seconds
  - 50th percentile: ~150s (target)
  - 95th percentile: ~200s (acceptable)
  - 99th percentile: <300s

worker_pool_queue_length
  - CodeGen: should stay <5
  - Security: should stay <2
  - Database: should stay <2

parallel_execution_conflicts
  - 0-2 per day (normal)
  - >5 per day (aggregator logic review needed)
```

### Log Patterns

```
✅ Task completed quickly: "CODEGEN Completed task_1 (45s, 25K tokens)"
⚠️ Task slow: "CODEGEN Running task_2 (90s elapsed, 65K tokens, 3/5 retries)"
❌ Task failed: "SECURITY Failed task_3 (timeout after 300s + 2 retries)"
🔄 Conflict detected: "AGGREGATOR Conflict: Security vs CodeGen on CSRF"
✔️ Conflict resolved: "AGGREGATOR Merged: Added CSRF to backend code"
```

---

## When to Use Serial vs Parallel

### Use Serial (Single Agent)

- ✅ Small quick tasks (<60 seconds)
- ✅ Very specialized work (only one agent needed)
- ✅ High dependency chain (tasks must sequence)
- ✅ Cost-sensitive (slightly cheaper)

### Use Parallel (Multiple Agents)

- ✅ Large projects (>120 seconds)
- ✅ Multiple work streams (frontend + backend)
- ✅ Quality important (parallel review)
- ✅ Speed important (deliver faster)
- ✅ Complex (needs all 3 agent types)

### Auto-Detection

PM agent automatically decides:

```python
if project_size == "large" and can_parallelize:
    execute_parallel()
else:
    execute_serial()
```

---

## Summary Table

| Aspect         | Serial      | Parallel                 |
| -------------- | ----------- | ------------------------ |
| **Speed**      | 100%        | 40-60% faster            |
| **Cost**       | $X          | $X + 5%                  |
| **Quality**    | Good        | Better (parallel review) |
| **Complexity** | Low         | Medium                   |
| **Best for**   | Small tasks | Large projects           |
| **Setup**      | Default     | Enabled by config        |
