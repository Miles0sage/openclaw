# Personal Assistant Approval System for OpenClaw Gateway

## Overview

The Personal Assistant Approval System provides a governance layer for the OpenClaw Gateway, enabling a personal assistant (running separately on Cloudflare Workers) to approve, monitor, and control task execution.

**Key Features:**

- Pre-execution approval workflow
- Constraint-based task execution limits
- Real-time abort signal handling
- Execution result reporting
- Intelligent fallback mode when assistant unavailable
- File-based task persistence
- Queue monitoring and status tracking

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    OpenClaw Gateway                          │
│                  (Northflank Container)                      │
│                  152.53.55.207:18789                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ├─→ approval_client.py
                     │   (Communicates with personal assistant)
                     │
                     ├─→ task_queue.py
                     │   (Manages task lifecycle)
                     │
                     └─→ gateway_approval_integration.py
                         (REST endpoints)
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              Personal Assistant Worker                       │
│              (Cloudflare Worker)                             │
│              /api/approve                                    │
│              /api/abort-signal/{taskId}                      │
│              /api/execution-report                           │
│              /health                                         │
└─────────────────────────────────────────────────────────────┘
```

## Task Lifecycle

```
PENDING
   │
   ├─→ Request Approval
   │
   ▼
PENDING_APPROVAL
   │
   ├─→ Approved
   │   │
   │   ▼
   │   APPROVED
   │   │
   │   ├─→ Start Execution
   │   │
   │   ▼
   │   RUNNING
   │   │
   │   ├─→ Success
   │   │   ▼
   │   │   COMPLETED
   │   │
   │   ├─→ Abort Signal
   │   │   ▼
   │   │   ABORTED
   │   │
   │   └─→ Error
   │       ▼
   │       FAILED
   │
   └─→ Rejected
       │
       ▼
       REJECTED
```

## Installation

### 1. Add Imports to gateway.py

```python
from approval_client import ApprovalClient, ExecutionSummary
from task_queue import TaskQueue, TaskStatus
```

### 2. Initialize Approval System

Add to your `@app.on_event("startup")`:

```python
# Initialize approval client
APPROVAL_CLIENT = ApprovalClient(
    assistant_url=os.getenv("APPROVAL_SYSTEM_URL", "http://localhost:8001"),
    api_key=os.getenv("APPROVAL_API_KEY", ""),
    timeout=10.0,
    fallback_strict=True
)

TASK_QUEUE = TaskQueue(
    persistence_dir=os.getenv("OPENCLAW_TASKS_DIR", "/tmp/openclaw_tasks"),
    auto_save=True
)

# Start health check task
asyncio.create_task(APPROVAL_CLIENT.periodic_health_check())

logger.info("✅ Approval system initialized")
```

### 3. Modify Chat Endpoint

Update `/api/chat` endpoint to use approval flow (see `gateway_approval_integration.py`).

### 4. Add Queue Endpoints

Add the endpoints from `gateway_approval_integration.py` to enable queue monitoring and manual approval/rejection.

### 5. Configure Environment Variables

```bash
# Personal Assistant Service
APPROVAL_SYSTEM_URL=http://localhost:8001
APPROVAL_API_KEY=your-secret-key

# Task Storage
OPENCLAW_TASKS_DIR=/tmp/openclaw_tasks

# Optional: Slack notifications
APPROVAL_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Core Components

### 1. approval_client.py

Handles communication with personal assistant.

**Main Classes:**

- **ApprovalClient**: Manages all interactions with personal assistant
  - `request_approval()`: Ask for approval before execution
  - `listen_for_abort()`: Monitor for abort signals
  - `report_execution()`: Send execution results
  - `get_health()`: Check assistant health
  - `periodic_health_check()`: Background health monitoring

- **ApprovalResponse**: Decision from personal assistant

  ```python
  {
      "approved": True,
      "reason": "Approved within daily limits",
      "constraints": [
          {
              "type": "cost_limit",
              "value": 5.0,
              "reason": "Daily limit remaining"
          }
      ]
  }
  ```

- **ExecutionSummary**: Report sent after task completion
  ```python
  ExecutionSummary(
      task_id="task-001",
      status="completed",
      result="Chat response",
      actual_cost=0.012,
      start_time="2026-02-18T10:00:00Z",
      end_time="2026-02-18T10:00:05Z",
      logs="execution logs"
  )
  ```

**Fallback Mode:**

When personal assistant is unavailable:

- Auto-switches to fallback mode
- Applies strict constraints by default
- Periodically retries connection
- Resumes normal mode when assistant recovers

### 2. task_queue.py

Manages task lifecycle and persistence.

**Main Classes:**

- **TaskQueue**: In-memory queue with file persistence
  - `enqueue()`: Add new task
  - `set_pending_approval()`: Transition to approval
  - `approve_task()`: Mark as approved
  - `reject_task()`: Mark as rejected
  - `start_task()`: Begin execution
  - `complete_task()`: Mark as complete
  - `fail_task()`: Mark as failed
  - `abort_task()`: Abort running task
  - `get_queue_status()`: Overall queue metrics

- **Task**: Individual task record

  ```python
  Task(
      task_id="task-001",
      task_type="chat",
      description="User query",
      status="pending_approval",
      estimated_cost=0.01,
      constraints=[...],
      ...
  )
  ```

- **TaskStatus**: Enum for status values
  - `PENDING`
  - `PENDING_APPROVAL`
  - `APPROVED`
  - `RUNNING`
  - `COMPLETED`
  - `FAILED`
  - `REJECTED`
  - `ABORTED`

### 3. gateway_approval_integration.py

Integration layer with FastAPI endpoints.

**Endpoints:**

| Endpoint                  | Method | Purpose                      |
| ------------------------- | ------ | ---------------------------- |
| `/api/queue/status`       | GET    | Get queue status summary     |
| `/api/queue/tasks`        | GET    | List all tasks (paginated)   |
| `/api/queue/task/{id}`    | GET    | Get specific task details    |
| `/api/queue/approve/{id}` | POST   | Manually approve task        |
| `/api/queue/reject/{id}`  | POST   | Manually reject task         |
| `/api/queue/abort/{id}`   | POST   | Abort running task           |
| `/api/approval/health`    | GET    | Check approval system health |

## Usage Examples

### Example 1: Basic Approval Flow

```python
# 1. Enqueue task
task = TASK_QUEUE.enqueue(
    task_id="task-001",
    task_type="chat",
    description="Process user query",
    estimated_cost=0.01
)

# 2. Request approval
TASK_QUEUE.set_pending_approval("task-001")
approval_response, in_fallback = await APPROVAL_CLIENT.request_approval(
    task_id="task-001",
    task_type="chat",
    description="Process user query",
    estimated_cost=0.01
)

# 3. Handle approval decision
if approval_response.approved:
    # Apply constraints
    task_config = APPROVAL_CLIENT.apply_constraints(
        {},
        approval_response.constraints
    )

    # Approve and run
    TASK_QUEUE.approve_task("task-001", approval_response.reason)
    TASK_QUEUE.start_task("task-001")

    # ... execute task ...

    # Report results
    TASK_QUEUE.complete_task("task-001", result="...", actual_cost=0.008)
    await APPROVAL_CLIENT.report_execution(
        ExecutionSummary(
            task_id="task-001",
            status="completed",
            result="...",
            actual_cost=0.008
        )
    )
else:
    TASK_QUEUE.reject_task("task-001", approval_response.reason)
```

### Example 2: Constraint Application

```python
# Get approval with constraints
approval_response, _ = await APPROVAL_CLIENT.request_approval(...)

# Apply to execution config
config = {
    "max_tokens": 4096,
    "max_duration_ms": 60000,
    "parallelism": 4
}

constrained_config = APPROVAL_CLIENT.apply_constraints(
    config,
    approval_response.constraints
)

# Now constrained_config has limits applied:
# {
#   "max_tokens": 2048,  # Limited by constraint
#   "max_duration_ms": 30000,  # Limited by constraint
#   "max_cost": 1.0,  # Added by constraint
#   "parallelism": 2,  # Limited by constraint
# }
```

### Example 3: Abort Handling

```python
# Start listening for abort in background
abort_task = asyncio.create_task(
    APPROVAL_CLIENT.listen_for_abort("task-001", timeout=300)
)

try:
    # Execute task
    result = await execute_task(...)

    # Check if aborted
    if abort_task.done() and abort_task.result():
        logger.warning("Task was aborted by personal assistant")
        TASK_QUEUE.abort_task("task-001")
        return

    # Complete normally
    TASK_QUEUE.complete_task("task-001", result=result)

finally:
    abort_task.cancel()
```

### Example 4: Fallback Mode

```python
# When personal assistant is unreachable:
approval_response, in_fallback = await APPROVAL_CLIENT.request_approval(...)

if in_fallback:
    logger.warning("Running in FALLBACK MODE with strict constraints")
    # Continue with strict constraints applied
    # Cost limit: $5.00
    # Time limit: 5 minutes
    # Resource limit: 0.5x
```

## Testing

Run the comprehensive test suite:

```bash
python test_approval_flow.py
```

This tests:

1. Task enqueueing
2. Approval requests (fallback mode)
3. Constraint application
4. Full approval workflow
5. Task completion and reporting
6. Task rejection
7. Task failure handling
8. Queue monitoring
9. Fallback mode behavior
10. Health checks

Expected output:

```
==============================
TEST SUMMARY
==============================
✅ PASS: Task Enqueueing
✅ PASS: Approval Request
✅ PASS: Constraint Application
✅ PASS: Task Approval Workflow
✅ PASS: Task Completion
✅ PASS: Task Rejection
✅ PASS: Task Failure Handling
✅ PASS: Queue Monitoring
✅ PASS: Fallback Mode
✅ PASS: Health Check
==============================
Results: 10/10 tests passed
==============================
```

## API Request/Response Examples

### Request Approval

**Request:**

```json
POST /api/approve HTTP/1.1
Content-Type: application/json
Authorization: Bearer your-api-key

{
  "task_id": "task-001",
  "task_type": "chat",
  "description": "Process user query about budget",
  "estimated_cost": 0.012,
  "estimated_duration_ms": 5000,
  "context": {
    "user_id": "user123",
    "session_id": "sess456",
    "project": "barber-crm"
  },
  "timestamp": "2026-02-18T10:00:00Z"
}
```

**Response (Approved):**

```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "approved": true,
  "reason": "Within daily budget limit",
  "constraints": [
    {
      "type": "cost_limit",
      "value": 4.5,
      "reason": "Daily limit: $20, used: $15.50, remaining: $4.50"
    },
    {
      "type": "time_limit",
      "value": 30000,
      "reason": "Standard execution timeout"
    }
  ],
  "retry_after_seconds": null
}
```

**Response (Rejected):**

```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "approved": false,
  "reason": "Exceeds monthly budget limit",
  "constraints": null,
  "retry_after_seconds": 3600
}
```

### Check Abort Signal

**Request:**

```
GET /api/abort-signal/task-001 HTTP/1.1
Authorization: Bearer your-api-key
```

**Response (No Abort):**

```json
{
  "should_abort": false,
  "reason": null
}
```

**Response (Abort Requested):**

```json
{
  "should_abort": true,
  "reason": "User cancelled operation"
}
```

### Report Execution

**Request:**

```json
POST /api/execution-report HTTP/1.1
Content-Type: application/json
Authorization: Bearer your-api-key

{
  "task_id": "task-001",
  "status": "completed",
  "result": "Chat response to user",
  "actual_cost": 0.0087,
  "start_time": "2026-02-18T10:00:00Z",
  "end_time": "2026-02-18T10:00:04Z",
  "logs": "execution completed successfully",
  "error_message": null,
  "duration_ms": 4000
}
```

**Response:**

```json
{
  "success": true,
  "message": "Execution report received"
}
```

## Monitoring

### Queue Status Endpoint

```bash
curl http://localhost:18789/api/queue/status \
  -H "X-Auth-Token: your-token"
```

Response:

```json
{
  "success": true,
  "timestamp": "2026-02-18T10:15:00Z",
  "data": {
    "total_tasks": 245,
    "by_status": {
      "completed": 200,
      "running": 3,
      "pending_approval": 2,
      "failed": 5,
      "rejected": 35
    },
    "total_cost_usd": 18.75,
    "total_execution_time_ms": 2845000,
    "pending_approval": 2,
    "running": 3,
    "timestamp": "2026-02-18T10:15:00Z"
  }
}
```

### Approval System Health

```bash
curl http://localhost:18789/api/approval/health \
  -H "X-Auth-Token: your-token"
```

Response:

```json
{
  "success": true,
  "timestamp": "2026-02-18T10:15:00Z",
  "approval_system": {
    "healthy": true,
    "fallback_mode": false,
    "assistant_url": "https://personal-assistant.example.com"
  }
}
```

## Configuration

### Environment Variables

```bash
# Required
APPROVAL_SYSTEM_URL=https://your-personal-assistant.workers.dev
APPROVAL_API_KEY=your-secret-api-key

# Optional
OPENCLAW_TASKS_DIR=/tmp/openclaw_tasks  # Task persistence directory
APPROVAL_TIMEOUT=10                      # Request timeout in seconds
APPROVAL_FALLBACK_STRICT=true            # Use strict constraints in fallback
APPROVAL_ENABLE_RETRIES=true             # Auto-retry on failures
APPROVAL_MAX_RETRIES=3                   # Max retry attempts
```

### config.json Extensions

You can add approval configuration to `config.json`:

```json
{
  "approval": {
    "enabled": true,
    "assistant_url": "${APPROVAL_SYSTEM_URL}",
    "api_key": "${APPROVAL_API_KEY}",
    "timeout_ms": 10000,
    "fallback_strict": true,
    "retry_policy": {
      "enabled": true,
      "max_attempts": 3,
      "backoff_multiplier": 1.5
    },
    "cost_limits": {
      "per_task": {
        "chat": 1.0,
        "workflow": 10.0,
        "batch": 50.0
      }
    }
  }
}
```

## Error Handling

### Common Scenarios

**1. Assistant Unavailable**

- Automatically switches to fallback mode
- Applies strict constraints
- Periodically retries connection
- Resumes normal operation when assistant recovers

**2. Approval Rejected**

- Task status set to `rejected`
- Request fails with 403 Forbidden
- User informed of rejection reason
- Task not executed

**3. Constraint Violation During Execution**

- Monitor actual cost/time during execution
- Abort if constraint violated
- Save partial results
- Report violation to assistant

**4. Abort Signal**

- Check abort signal periodically
- Gracefully stop execution
- Save state before halting
- Report abort to assistant

## Security Considerations

1. **API Key Security**
   - Store APPROVAL_API_KEY in secure environment (Vercel secrets, Northflank secrets)
   - Rotate keys regularly
   - Use Bearer token authentication

2. **HTTPS Only**
   - All communication with personal assistant over HTTPS
   - Verify TLS certificates

3. **Input Validation**
   - Validate task descriptions and context
   - Sanitize before logging

4. **Rate Limiting**
   - Implement rate limits on approval requests
   - Prevent approval endpoint abuse

5. **Audit Logging**
   - Log all approval decisions
   - Log all constraint applications
   - Maintain audit trail for compliance

## Troubleshooting

### Approval Requests Always Fall Back

**Symptom:** Approval system always in fallback mode

**Solutions:**

1. Check APPROVAL_SYSTEM_URL is correct and reachable
2. Verify APPROVAL_API_KEY is set correctly
3. Check network connectivity to assistant
4. Review logs for specific error messages

### Tasks Not Persisting Across Restarts

**Symptom:** Tasks lost after gateway restart

**Solution:**

1. Check OPENCLAW_TASKS_DIR is writable
2. Verify directory exists: `mkdir -p /tmp/openclaw_tasks`
3. Check file permissions: `chmod 755 /tmp/openclaw_tasks`

### High Latency on Approval Requests

**Symptom:** Slow response time when requesting approval

**Solutions:**

1. Reduce APPROVAL_TIMEOUT if assistant is slow
2. Check network latency to assistant
3. Enable response caching in assistant
4. Consider batch approval requests

### Constraints Not Applied

**Symptom:** Task executes beyond constraint limits

**Solution:**

1. Verify constraints are in response
2. Check apply_constraints() is called before execution
3. Validate constraint types are recognized
4. Add logging to debug constraint application

## Future Enhancements

1. **Constraint Presets**
   - Save common constraint sets
   - Apply presets by name

2. **Approval Delegation**
   - Escalate to human if auto-approval uncertain
   - Support approval queues

3. **Advanced Monitoring**
   - Real-time cost tracking dashboard
   - Spend alerts and notifications
   - Budget forecasting

4. **Workflow Integration**
   - Approval chains for complex tasks
   - Multi-stage approvals
   - Conditional approval logic

5. **Analytics**
   - Approval decision analytics
   - Cost trend analysis
   - Task success rate metrics

## Support & Documentation

- **GitHub Issues:** Report bugs and request features
- **Documentation:** See docs in `/openclaw/docs/approval/`
- **Examples:** See `/openclaw/examples/approval/`
- **Tests:** Run `python test_approval_flow.py`

## License

This approval system is part of OpenClaw and follows the same license.
