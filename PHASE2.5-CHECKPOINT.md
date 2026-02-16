# OpenClaw Phase 2.5: Agent Routing + Discord Implementation

**Status:** CHECKPOINT SAVED (2026-02-16 23:45 UTC)
**Next Action:** Resume tomorrow with task #1

---

## What Was Done This Session

1. ✅ Analyzed existing codebase
   - LangGraph router exists at `src/routing/langgraph-router.ts` (fully implemented, 663 LOC)
   - Gateway hardcodes "project_manager" agent at line 503 in `gateway.py`
   - Discord code ready (needs bot token + intent config)
   - Config structure verified in `config.json`

2. ✅ Created 7-task implementation plan in TaskList
   - Phase 1: Router integration (3 tasks)
   - Phase 2: Discord testing (2 tasks)
   - Phase 3: Workflow automation (2 tasks)

3. ✅ Updated memory with checkpoint and timeline

---

## What To Do Tomorrow

### Phase 1: Router Integration (2 hours)

**Task #1:** Create `router-service.ts` HTTP server

```bash
# Create file at /root/openclaw/router-service.ts
# Implements Express HTTP server with:
# - POST /api/route → route message, returns agentId + decision
# - GET /api/stats → router statistics
# - Graceful error handling with timeouts
```

**Task #2:** Modify `gateway.py` to use router

```python
# Edit /root/openclaw/gateway.py line 503
# Replace: active_agent = "project_manager"
# With: active_agent = route_message(message_text, session_key)
# Implement: route_message() function with HTTP call to :3001
```

**Task #3:** Test router integration

```bash
# Start router-service.ts on :3001
# Test via curl to /api/route endpoint
# Verify routing decisions are returned correctly
# Check gateway calls router and falls back gracefully
```

---

### Phase 2: Discord Testing (1 hour)

**Task #4:** Set up Discord bot

```bash
# 1. Retrieve Discord bot token from wrangler secrets
# 2. Enable message content intent in Discord Developer Portal
# 3. Configure DISCORD_BOT_TOKEN environment variable
# 4. Invite bot to test server
# 5. Verify connection in logs
```

**Task #5:** Test message routing in Discord

```bash
# Send test messages in Discord:
# - Simple message → PM Agent
# - Code request → CodeGen Agent
# - Security request → Security Agent
# Verify agent signatures visible (🎯, 💻, etc)
```

---

### Phase 3: Workflow Automation (4 hours)

**Task #6:** Implement `workflow_engine.py`

```python
# Create /root/openclaw/workflow_engine.py
# Classes/methods needed:
# - WorkflowEngine class with orchestrator
# - execute_workflow(workflow_name, context)
# - _execute_step(agent_id, task, context, timeout)
# - deploy_to_vercel(project_path, vercel_token)
# - Load workflows from config.json
```

**Task #7:** Test end-to-end workflow

```bash
# Execute "fiverr_5star" workflow with test context
# Verify all steps complete:
# - PM coordinates
# - CodeGen builds
# - Security audits
# - Vercel deployment succeeds
```

---

## Key Implementation Details

### Router Service (`router-service.ts`)

```typescript
// HTTP request to :3001/api/route
POST /api/route
{
  "message": "Build a Next.js dashboard",
  "sessionKey": "user-session-id",
  "channel": "discord",
  "accountId": "default"
}

// Returns routing decision
{
  "agentId": "coder_agent",
  "agentName": "CodeGen Pro",
  "effortLevel": "high",
  "confidence": 0.9,
  "selectedSkills": ["nextjs", "typescript"],
  "fallbackAgentId": "project_manager"
}
```

### Gateway Integration (`gateway.py` line 503)

```python
ROUTER_SERVICE_URL = os.getenv("ROUTER_SERVICE_URL", "http://localhost:3001")

def route_message(message_text: str, session_key: str) -> str:
    try:
        response = requests.post(
            f"{ROUTER_SERVICE_URL}/api/route",
            json={"message": message_text, "sessionKey": session_key, ...},
            timeout=2.0
        )
        if response.status_code == 200:
            return response.json()['agentId']
        else:
            return "project_manager"  # fallback
    except:
        return "project_manager"  # fallback on error

active_agent = route_message(message_text, session_key)
```

### Workflow Engine Usage

```python
engine = WorkflowEngine()
result = await engine.execute_workflow('fiverr_5star', {
    'client': 'Restaurant Owner',
    'requirements': 'Restaurant website',
    'tech_stack': 'Next.js, Tailwind, Supabase'
})
# Returns workflow status with all steps completed
```

---

## Files to Modify/Create

| File                 | Action          | Size     | Effort  |
| -------------------- | --------------- | -------- | ------- |
| `router-service.ts`  | CREATE          | ~200 LOC | 30 mins |
| `gateway.py`         | MODIFY line 503 | 10 lines | 30 mins |
| `workflow_engine.py` | CREATE          | ~300 LOC | 2 hours |
| Test files           | CREATE          | ~150 LOC | 1 hour  |

---

## Testing Checklist

### Router Service

- [ ] `npx tsx router-service.ts` starts on :3001
- [ ] `curl -X POST http://localhost:3001/api/route` returns valid decision
- [ ] Router stats endpoint working

### Gateway Integration

- [ ] `python3 gateway.py` starts without errors
- [ ] Logs show "🎯 Router → CodeGen Pro" for code requests
- [ ] Fallback to PM agent if router unavailable

### Discord

- [ ] Bot connects (check logs for "Discord bot connected")
- [ ] Test message routes to correct agent
- [ ] Agent signatures visible in response

### Workflow Engine

- [ ] `workflow_engine.py` imports successfully
- [ ] `execute_workflow('fiverr_5star', {...})` runs without errors
- [ ] Vercel deployment integration works

---

## Environment Setup (If Needed)

```bash
# Set router service URL
export ROUTER_SERVICE_URL="http://localhost:3001"

# Discord bot token
export DISCORD_BOT_TOKEN="your-token-from-wrangler"

# OpenClaw gateway (already running on :18789)
ssh exe.dev
# Then: ssh vm-name (or use web terminal)
```

---

## Success Criteria

✅ Router integration working (99% uptime)
✅ Discord bot routing messages to correct agents
✅ Workflow engine executing multi-step workflows
✅ Vercel deployments automated
✅ Cost savings verified (~34% reduction)

---

## Time Budget

- Phase 1: 2 hours
- Phase 2: 1 hour
- Phase 3: 4 hours
- **Total: 7 hours**

**Recommended:** Tackle Phase 1 + 2 tomorrow (3 hours), Phase 3 next day (4 hours)

---

## Questions for Tomorrow

- Should router service run as separate process or integrated into gateway?
- Which workflows to implement first (website, API, mobile)?
- Discord test server setup — already ready, or need to create?

---

**Next Action:** Run `TaskList` to see all 7 tasks, then start with task #1.
