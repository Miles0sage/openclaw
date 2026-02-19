# OpenClaw Next Build Phase — Full Implementation Plan

## Instructions for Claude

You are implementing 5 phases for the OpenClaw multi-agent AI gateway. Read all referenced files before modifying them. Execute each phase sequentially. After all phases, restart the gateway and verify.

**Auth token:** `f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3`
**Gateway port:** 18789
**Start command:** `MINIMAX_API_KEY='${MINIMAX_API_KEY}' nohup python3 /root/openclaw/gateway.py > /tmp/gateway.log 2>&1 &`
**Kill command:** `fuser -k -9 18789/tcp`
**Commit suffix:** `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>`
**Push to:** `origin main`

---

## Codebase Context (from file reads)

### gateway.py (~2877 lines)

- **Line 519:** `call_model_for_agent(agent_key, prompt, conversation)` — Routes to correct model per agent config. Returns `(response_text, tokens_used)`. Supports anthropic, deepseek (Kimi), minimax, ollama providers.
- **Line 1009:** `@app.post("/api/chat")` — Main chat endpoint. Takes `Message(content, agent_id, sessionKey, project_id)`.
- **Lines 2726-2792:** Task CRUD — `GET /api/tasks`, `POST /api/tasks`, `PATCH /api/tasks/{task_id}`. Tasks stored in `TASKS_FILE` as JSON array. Task format: `{id, title, description, status, agent, created_at, updated_at}`.
- **Lines 2806-2839:** `GET /api/dashboard/summary` — Aggregated dashboard data.
- **Lines 2842-2850:** `GET /mission-control` — Serves `mission_control.html`.
- **Line 468:** `Message` Pydantic model: `content: str, agent_id: Optional[str], sessionKey: Optional[str], project_id: Optional[str]`
- Cost tracking via `log_cost_event()` and `get_cost_metrics()` already imported.
- Quota system via `check_all_quotas()` and `get_quota_status()` already imported.
- `agent_router = AgentRouter()` already instantiated globally.
- `CONFIG` dict loaded from `config.json` at startup.
- `TASKS_FILE` is a `pathlib.Path` pointing to tasks JSON file.

### agent_router.py (~400 lines)

- **Line 37:** `class AgentRouter` — Routes queries to `project_manager`, `coder_agent`, `elite_coder`, `hacker_agent`, `database_agent`.
- **Line 198:** `select_agent(query, session_state)` — Returns dict with `{agentId, confidence, reason, intent, keywords, cost_score, semantic_score, cached}`.
- Has `AGENTS` dict with cost info per agent.
- Has keyword-based + semantic scoring + cost optimization + caching.

### workflow_engine.py (exists, ~400+ lines)

- Already has `WorkflowEngine` class with JSON-based workflow definitions.
- Has multi-step sequences, conditional branching, parallel execution, error handling.
- Storage in `/tmp/openclaw_workflows/`.
- **But:** It's not wired into gateway.py with REST endpoints yet.

### config.json (~610 lines)

- 5 agents: `project_manager` (Opus), `coder_agent` (Kimi 2.5), `elite_coder` (MiniMax M2.5), `hacker_agent` (Kimi Reasoner), `database_agent` (Opus).
- Has `quotas` section with daily/monthly limits and warning thresholds.
- Has `workflows` section with predefined workflow templates.
- Has `ops_policy.reaction_matrix` including `cost.alert → notify_slack`.

### mission_control.html (~1100 lines)

- 5-tab dashboard: Overview, Agents, Tasks, Memory, Costs.
- Tasks tab currently uses localStorage (needs to be wired to `/api/tasks` API).

---

## Phase 1: Agent-to-Agent Delegation (30 min)

**Goal:** Overseer can hand off sub-tasks to specialists mid-conversation and return combined results.

### Step 1: Add `auto_delegate()` to agent_router.py

Add this method to the `AgentRouter` class (after `select_agent` method, around line 268):

```python
def auto_delegate(self, overseer_response: str, original_query: str) -> list:
    """
    Parse Overseer's response for delegation markers and return delegation tasks.

    Delegation markers in Overseer response:
    [DELEGATE:agent_id]task description[/DELEGATE]

    Returns: list of {"agent_id": str, "task": str, "routing": dict}
    """
    import re
    pattern = r'\[DELEGATE:(\w+)\](.*?)\[/DELEGATE\]'
    matches = re.findall(pattern, overseer_response, re.DOTALL)

    delegations = []
    for agent_id, task in matches:
        agent_id = agent_id.strip()
        task = task.strip()

        # Validate agent exists
        if agent_id not in self.AGENTS and agent_id not in (self.config.get("agents", {}) or {}):
            continue

        delegations.append({
            "agent_id": agent_id,
            "task": task,
            "routing": {
                "source": "delegation",
                "delegated_by": "project_manager",
                "original_query": original_query[:200]
            }
        })

    return delegations
```

### Step 2: Add delegation instruction to Overseer's system prompt

In `gateway.py`, find where the system prompt is built in `call_model_for_agent()` (around line 536-570). After the persona is set, add delegation instructions specifically for the project_manager agent.

Find the section in `call_model_for_agent()` where the system prompt is assembled (look for where `persona` and `identity_context` are combined into `system_prompt`). Add this block:

```python
# Add delegation capability for PM agent
delegation_instructions = ""
if agent_key == "project_manager":
    delegation_instructions = """

DELEGATION: When a task requires specialist work, you can delegate by including markers in your response:
[DELEGATE:elite_coder]detailed task description here[/DELEGATE]
[DELEGATE:coder_agent]simple coding task here[/DELEGATE]
[DELEGATE:hacker_agent]security review task here[/DELEGATE]
[DELEGATE:database_agent]database query task here[/DELEGATE]

Only delegate when the task clearly needs a specialist. For planning, coordination, and general questions, handle directly.
After delegation results come back, synthesize them into a final response for the user.
"""
```

Include `delegation_instructions` in the system prompt string.

### Step 3: Add delegation handling in `/api/chat` endpoint

In `gateway.py`, find the `/api/chat` handler (line 1009). After the agent responds, add delegation processing. Find where the response is returned (look for the return statement with `response_text`). Before that return, add:

```python
# Check for delegation markers in PM response
if agent_key == "project_manager" or agent_id == "pm":
    delegations = agent_router.auto_delegate(response_text, msg.content)

    if delegations:
        delegation_results = []
        for delegation in delegations:
            try:
                delegate_response, delegate_tokens = call_model_for_agent(
                    delegation["agent_id"],
                    delegation["task"],
                    conversation=None
                )
                delegation_results.append({
                    "agent": delegation["agent_id"],
                    "task": delegation["task"],
                    "response": delegate_response,
                    "tokens": delegate_tokens
                })

                # Log delegation cost
                agent_cfg = get_agent_config(delegation["agent_id"])
                log_cost_event(
                    agent_id=delegation["agent_id"],
                    model=agent_cfg.get("model", "unknown"),
                    input_tokens=len(delegation["task"].split()),
                    output_tokens=delegate_tokens,
                    cost_usd=0,  # Will be calculated by cost tracker
                    operation="delegation",
                    metadata={"delegated_by": "project_manager", "original_query": msg.content[:100]}
                )
            except Exception as e:
                delegation_results.append({
                    "agent": delegation["agent_id"],
                    "task": delegation["task"],
                    "response": f"[Delegation failed: {str(e)}]",
                    "tokens": 0
                })

        # If we got delegation results, ask PM to synthesize
        if delegation_results:
            synthesis_prompt = f"""You delegated tasks to specialists. Here are their results:

{chr(10).join(f'### {r["agent"]} response:{chr(10)}{r["response"]}' for r in delegation_results)}

Original user request: {msg.content}

Synthesize these specialist responses into a single, coherent response for the user. Remove any delegation markers. Be concise."""

            response_text, extra_tokens = call_model_for_agent("project_manager", synthesis_prompt)
            total_tokens += extra_tokens + sum(r["tokens"] for r in delegation_results)
```

Make sure `agent_key` is available in scope (it should be derived from `msg.agent_id` or the router decision earlier in the handler).

---

## Phase 2: Workflow Engine REST Endpoints (45 min)

**Goal:** Wire the existing `workflow_engine.py` into gateway.py with REST endpoints.

### Step 1: Read workflow_engine.py fully

Read the full file to understand the existing API. Key classes/methods to look for:

- `WorkflowEngine` class
- `create_workflow()`, `execute_workflow()`, `get_workflow_status()`, `cancel_workflow()`
- How it stores state

### Step 2: Add workflow endpoints to gateway.py

Add these endpoints after the task CRUD endpoints (around line 2793):

```python
# ═══════════════════════════════════════════════════════════════════════
# WORKFLOW ENGINE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

# Initialize workflow engine with agent executor
workflow_engine_instance = None

def get_workflow_engine():
    global workflow_engine_instance
    if workflow_engine_instance is None:
        workflow_engine_instance = WorkflowEngine()
    return workflow_engine_instance

@app.post("/api/workflows")
async def create_workflow_endpoint(request: Request):
    """Create and optionally start a new workflow"""
    body = await request.json()
    engine = get_workflow_engine()

    steps = body.get("steps", [])
    name = body.get("name", "Unnamed Workflow")
    auto_start = body.get("auto_start", False)

    if not steps:
        raise HTTPException(status_code=400, detail="Workflow must have at least one step")

    # Create workflow
    workflow_id = str(uuid.uuid4())[:8]
    workflow = {
        "id": workflow_id,
        "name": name,
        "steps": steps,
        "status": "created",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "results": [],
        "current_step": 0
    }

    # Save to disk
    workflows_file = pathlib.Path("/tmp/openclaw_workflows.json")
    existing = []
    if workflows_file.exists():
        with open(workflows_file, 'r') as f:
            existing = json.load(f)
    existing.append(workflow)
    with open(workflows_file, 'w') as f:
        json.dump(existing, f, indent=2)

    # Auto-start if requested
    if auto_start:
        asyncio.create_task(_execute_workflow(workflow_id))
        workflow["status"] = "running"

    return {"success": True, "workflow": workflow}


@app.get("/api/workflows")
async def list_workflows_endpoint():
    """List all workflows"""
    workflows_file = pathlib.Path("/tmp/openclaw_workflows.json")
    if workflows_file.exists():
        with open(workflows_file, 'r') as f:
            workflows = json.load(f)
    else:
        workflows = []
    return {"success": True, "workflows": workflows, "total": len(workflows)}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow_endpoint(workflow_id: str):
    """Get workflow status and results"""
    workflows_file = pathlib.Path("/tmp/openclaw_workflows.json")
    if not workflows_file.exists():
        raise HTTPException(status_code=404, detail="No workflows found")

    with open(workflows_file, 'r') as f:
        workflows = json.load(f)

    for wf in workflows:
        if wf["id"] == workflow_id:
            return {"success": True, "workflow": wf}

    raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")


@app.delete("/api/workflows/{workflow_id}")
async def cancel_workflow_endpoint(workflow_id: str):
    """Cancel a running workflow"""
    workflows_file = pathlib.Path("/tmp/openclaw_workflows.json")
    if not workflows_file.exists():
        raise HTTPException(status_code=404, detail="No workflows found")

    with open(workflows_file, 'r') as f:
        workflows = json.load(f)

    for wf in workflows:
        if wf["id"] == workflow_id:
            wf["status"] = "cancelled"
            wf["cancelled_at"] = datetime.utcnow().isoformat() + "Z"
            break

    with open(workflows_file, 'w') as f:
        json.dump(workflows, f, indent=2)

    return {"success": True, "message": f"Workflow {workflow_id} cancelled"}


@app.post("/api/workflows/{workflow_id}/start")
async def start_workflow_endpoint(workflow_id: str):
    """Start a created workflow"""
    asyncio.create_task(_execute_workflow(workflow_id))
    return {"success": True, "message": f"Workflow {workflow_id} started"}


async def _execute_workflow(workflow_id: str):
    """Execute workflow steps sequentially, passing output forward"""
    workflows_file = pathlib.Path("/tmp/openclaw_workflows.json")

    def _load():
        with open(workflows_file, 'r') as f:
            return json.load(f)

    def _save(wfs):
        with open(workflows_file, 'w') as f:
            json.dump(wfs, f, indent=2)

    workflows = _load()
    workflow = None
    for wf in workflows:
        if wf["id"] == workflow_id:
            workflow = wf
            break

    if not workflow:
        return

    workflow["status"] = "running"
    workflow["started_at"] = datetime.utcnow().isoformat() + "Z"
    _save(workflows)

    previous_output = ""

    for i, step in enumerate(workflow["steps"]):
        # Reload to check for cancellation
        workflows = _load()
        for wf in workflows:
            if wf["id"] == workflow_id:
                workflow = wf
                break

        if workflow["status"] == "cancelled":
            break

        workflow["current_step"] = i
        _save(workflows)

        agent_id = step.get("agent", "project_manager")
        task = step.get("task", "")

        # Inject previous step output as context
        if previous_output:
            task = f"Previous step output:\n{previous_output}\n\nYour task: {task}"

        try:
            response_text, tokens = call_model_for_agent(agent_id, task)

            step_result = {
                "step": i,
                "agent": agent_id,
                "task": step.get("task", ""),
                "status": "completed",
                "response": response_text,
                "tokens": tokens,
                "completed_at": datetime.utcnow().isoformat() + "Z"
            }
            previous_output = response_text

            # Log cost
            agent_cfg = get_agent_config(agent_id)
            log_cost_event(
                agent_id=agent_id,
                model=agent_cfg.get("model", "unknown"),
                input_tokens=len(task.split()),
                output_tokens=tokens,
                cost_usd=0,
                operation="workflow",
                metadata={"workflow_id": workflow_id, "step": i}
            )

        except Exception as e:
            step_result = {
                "step": i,
                "agent": agent_id,
                "task": step.get("task", ""),
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.utcnow().isoformat() + "Z"
            }

            # On failure, mark workflow as failed and stop
            workflows = _load()
            for wf in workflows:
                if wf["id"] == workflow_id:
                    wf["results"].append(step_result)
                    wf["status"] = "failed"
                    wf["failed_at"] = datetime.utcnow().isoformat() + "Z"
                    break
            _save(workflows)
            return

        # Save step result
        workflows = _load()
        for wf in workflows:
            if wf["id"] == workflow_id:
                wf["results"].append(step_result)
                break
        _save(workflows)

    # Mark completed
    workflows = _load()
    for wf in workflows:
        if wf["id"] == workflow_id:
            if wf["status"] != "cancelled":
                wf["status"] = "completed"
                wf["completed_at"] = datetime.utcnow().isoformat() + "Z"
            break
    _save(workflows)
```

---

## Phase 3: Slack/Telegram Task Creation from Chat (30 min)

**Goal:** Users can create tasks by saying "create task: ..." in chat.

### Step 1: Add task detection in `/api/chat` handler

In gateway.py, inside the `/api/chat` handler, **before** sending the message to the agent, add task-intent detection:

```python
# Task creation detection
TASK_PATTERNS = [
    r'^create task[:\s]+(.+)',
    r'^todo[:\s]+(.+)',
    r'^add task[:\s]+(.+)',
    r'^remind me to[:\s]+(.+)',
    r'^new task[:\s]+(.+)',
]

import re as _re

task_match = None
for pattern in TASK_PATTERNS:
    m = _re.match(pattern, msg.content.strip(), _re.IGNORECASE)
    if m:
        task_match = m.group(1).strip()
        break

if task_match:
    # Auto-create task
    if TASKS_FILE.exists():
        with open(TASKS_FILE, 'r') as f:
            tasks = json.load(f)
    else:
        tasks = []

    # Use router to determine best agent for the task
    routing = agent_router.select_agent(task_match)

    new_task = {
        "id": str(uuid.uuid4())[:8],
        "title": task_match[:200],
        "description": msg.content,
        "status": "todo",
        "agent": routing.get("agentId", "project_manager"),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "source": "chat",
        "session_key": msg.sessionKey or ""
    }
    tasks.append(new_task)

    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=2)

    # Return task confirmation (skip sending to agent)
    task_response = f"Task created: **{task_match[:200]}**\nID: `{new_task['id']}`\nAssigned to: {routing.get('agentId', 'project_manager')} ({routing.get('reason', '')})\n\n— Overseer"

    # Add to session if applicable
    if msg.sessionKey:
        if msg.sessionKey not in chat_history:
            chat_history[msg.sessionKey] = []
        chat_history[msg.sessionKey].append({"role": "user", "content": msg.content})
        chat_history[msg.sessionKey].append({"role": "assistant", "content": task_response})
        _save_session(msg.sessionKey)

    return {"response": task_response, "agent": "project_manager", "task_created": new_task}
```

Place this **early** in the handler, before the agent routing and model call.

### Step 2: Wire Mission Control Tasks tab to API

In `mission_control.html`, find the Tasks tab JavaScript. Replace localStorage usage with fetch calls:

Find the tasks loading function and replace with:

```javascript
async function loadTasks() {
  try {
    const response = await fetch("/api/tasks");
    const data = await response.json();
    if (data.success) {
      renderTasks(data.tasks);
    }
  } catch (e) {
    console.error("Failed to load tasks:", e);
  }
}
```

Find the task creation function and replace with:

```javascript
async function createTask(title, description, agent) {
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, description, agent, status: "todo" }),
    });
    const data = await response.json();
    if (data.success) {
      loadTasks(); // Refresh
    }
  } catch (e) {
    console.error("Failed to create task:", e);
  }
}
```

Find task status update and replace with:

```javascript
async function updateTaskStatus(taskId, status) {
  try {
    await fetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    loadTasks();
  } catch (e) {
    console.error("Failed to update task:", e);
  }
}
```

---

## Phase 4: Cost Alerts to Slack (20 min)

**Goal:** Automatic Slack notifications when budget thresholds hit.

### Step 1: Add Slack webhook config

Add to `config.json` at the top level:

```json
"slack_alerts": {
    "webhook_url": "${SLACK_WEBHOOK_URL}",
    "enabled": true,
    "thresholds": [80, 90, 100],
    "dedupe_hours": 24
}
```

### Step 2: Add cost alert function to gateway.py

Add this function near the top of gateway.py (after imports):

```python
# ═══════════════════════════════════════════════════════════════════════
# COST ALERTS — Slack webhook notifications
# ═══════════════════════════════════════════════════════════════════════

_cost_alerts_sent = {}  # {threshold_key: timestamp} for dedup

def send_cost_alert_if_needed():
    """Check cost thresholds and send Slack alerts if needed"""
    slack_config = CONFIG.get("slack_alerts", {})
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", slack_config.get("webhook_url", ""))

    if not webhook_url or not slack_config.get("enabled", False):
        return

    try:
        cost_data = get_cost_metrics()
        quota_status = get_quota_status("default")

        daily_spend = cost_data.get("today_usd", 0)
        monthly_spend = cost_data.get("month_usd", 0)
        daily_limit = quota_status.get("daily", {}).get("limit", 50)
        monthly_limit = quota_status.get("monthly", {}).get("limit", 1000)

        thresholds = slack_config.get("thresholds", [80, 90, 100])
        dedupe_hours = slack_config.get("dedupe_hours", 24)

        alerts = []

        # Check daily
        if daily_limit > 0:
            daily_pct = (daily_spend / daily_limit) * 100
            for threshold in thresholds:
                if daily_pct >= threshold:
                    key = f"daily_{threshold}_{datetime.utcnow().strftime('%Y-%m-%d')}"
                    if key not in _cost_alerts_sent:
                        alerts.append(f"Daily spend at ${daily_spend:.2f}/${daily_limit:.2f} ({daily_pct:.0f}%)")
                        _cost_alerts_sent[key] = time.time()

        # Check monthly
        if monthly_limit > 0:
            monthly_pct = (monthly_spend / monthly_limit) * 100
            for threshold in thresholds:
                if monthly_pct >= threshold:
                    key = f"monthly_{threshold}_{datetime.utcnow().strftime('%Y-%m')}"
                    if key not in _cost_alerts_sent:
                        alerts.append(f"Monthly spend at ${monthly_spend:.2f}/${monthly_limit:.2f} ({monthly_pct:.0f}%)")
                        _cost_alerts_sent[key] = time.time()

        # Send alerts
        for alert_msg in alerts:
            try:
                requests.post(webhook_url, json={
                    "text": f"[COST ALERT] {alert_msg}",
                    "username": "OpenClaw Cost Monitor",
                    "icon_emoji": ":money_with_wings:"
                }, timeout=5)
                logger.info(f"💰 Cost alert sent: {alert_msg}")
            except Exception as e:
                logger.error(f"Failed to send Slack alert: {e}")

    except Exception as e:
        logger.error(f"Cost alert check failed: {e}")
```

### Step 3: Wire into cost tracking

In the `/api/chat` handler, after `log_cost_event()` is called, add:

```python
send_cost_alert_if_needed()
```

Also add it to the cron scheduler if one exists (look for cron job registration).

---

## Phase 5: Dashboard SSE Integration (20 min)

**Goal:** Mission Control shows real-time streaming responses.

### In mission_control.html, add SSE client

Find the Overview tab's activity log section. Add this JavaScript:

```javascript
// SSE Real-time Activity Stream
let eventSource = null;

function connectActivityStream() {
  if (eventSource) eventSource.close();

  // Listen for activity events
  eventSource = new EventSource("/api/events/stream");

  eventSource.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      addActivityItem(data);
    } catch (e) {}
  };

  eventSource.onerror = function () {
    // Reconnect after 5s
    setTimeout(connectActivityStream, 5000);
  };
}

function addActivityItem(data) {
  const log = document.getElementById("activity-log");
  if (!log) return;

  const item = document.createElement("div");
  item.className = "activity-item";
  item.innerHTML = `
        <span class="activity-time">${new Date().toLocaleTimeString()}</span>
        <span class="activity-agent">${data.agent || "system"}</span>
        <span class="activity-text">${data.message || data.event || ""}</span>
    `;
  log.prepend(item);

  // Keep max 50 items
  while (log.children.length > 50) {
    log.removeChild(log.lastChild);
  }

  // Update agent status card if agent is active
  if (data.agent && data.type === "response_start") {
    setAgentStatus(data.agent, "typing");
  } else if (data.agent && data.type === "response_end") {
    setAgentStatus(data.agent, "idle");
  }
}

function setAgentStatus(agentId, status) {
  const card = document.querySelector(`[data-agent="${agentId}"]`);
  if (card) {
    const badge = card.querySelector(".status-badge");
    if (badge) {
      badge.textContent = status === "typing" ? "⚡ Active" : "✅ Idle";
      badge.className = `status-badge ${status}`;
    }
  }
}

// Connect on page load
connectActivityStream();
```

### Add SSE event endpoint to gateway.py

Add this endpoint (near the other API endpoints):

```python
# ═══════════════════════════════════════════════════════════════════════
# SSE EVENT STREAM for Mission Control real-time updates
# ═══════════════════════════════════════════════════════════════════════

_event_subscribers = []

def broadcast_event(event_data: dict):
    """Broadcast an event to all SSE subscribers"""
    _event_subscribers.append(event_data)
    # Keep last 100 events
    while len(_event_subscribers) > 100:
        _event_subscribers.pop(0)

@app.get("/api/events/stream")
async def event_stream():
    """SSE endpoint for real-time dashboard updates"""
    async def generate():
        last_index = len(_event_subscribers)
        while True:
            await asyncio.sleep(1)
            current_len = len(_event_subscribers)
            if current_len > last_index:
                for event in _event_subscribers[last_index:current_len]:
                    yield f"data: {json.dumps(event)}\n\n"
                last_index = current_len

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
```

### Wire broadcast into `/api/chat` handler

In the chat handler, add event broadcasts:

```python
# Before calling agent
broadcast_event({"type": "response_start", "agent": agent_key, "message": f"{agent_key} is thinking...", "timestamp": datetime.utcnow().isoformat()})

# After agent responds
broadcast_event({"type": "response_end", "agent": agent_key, "message": f"{agent_key} responded ({total_tokens} tokens)", "tokens": total_tokens, "timestamp": datetime.utcnow().isoformat()})
```

---

## Verification Steps (after all phases)

1. Kill existing gateway: `fuser -k -9 18789/tcp`
2. Start gateway: `MINIMAX_API_KEY='${MINIMAX_API_KEY}' nohup python3 /root/openclaw/gateway.py > /tmp/gateway.log 2>&1 &`
3. Wait 3s, check logs: `tail -20 /tmp/gateway.log`
4. Health check: `curl -s http://localhost:18789/health`
5. Test delegation: `curl -s -X POST http://localhost:18789/api/chat -H 'Content-Type: application/json' -H 'Authorization: Bearer f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3' -d '{"content":"Review the security of a Next.js login page and write the fix","agent_id":"pm"}'`
6. Test workflow: `curl -s -X POST http://localhost:18789/api/workflows -H 'Content-Type: application/json' -H 'Authorization: Bearer f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3' -d '{"name":"test","steps":[{"agent":"coder_agent","task":"Write a hello world Python function"},{"agent":"hacker_agent","task":"Review the code for security issues"}],"auto_start":true}'`
7. Test task creation: `curl -s -X POST http://localhost:18789/api/chat -H 'Content-Type: application/json' -H 'Authorization: Bearer f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3' -d '{"content":"create task: fix the login page CSS","agent_id":"pm"}'`
8. Check tasks: `curl -s http://localhost:18789/api/tasks -H 'Authorization: Bearer f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3'`
9. Check dashboard: `curl -s http://localhost:18789/api/dashboard/summary -H 'Authorization: Bearer f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3'`
10. Check SSE stream: `curl -s -N http://localhost:18789/api/events/stream &` then send a chat message
11. Open Mission Control: verify all 5 tabs load at `https://dashboard.overseerclaw.uk/mission-control`

## Git

After all tests pass:

```bash
cd /root/openclaw
git add gateway.py agent_router.py config.json mission_control.html workflow_engine.py
git commit -m "feat: Add agent delegation, workflow API, chat task creation, cost alerts, SSE dashboard

- Phase 1: Agent-to-agent delegation with [DELEGATE:agent] markers
- Phase 2: Workflow engine REST endpoints (CRUD + sequential execution)
- Phase 3: Task creation from chat messages (create task:, todo:, etc.)
- Phase 4: Slack cost alerts with deduplication
- Phase 5: SSE event stream for real-time Mission Control updates

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git push origin main
```
