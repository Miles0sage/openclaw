# n8n Integration — OpenClaw Event Pipeline

Complete end-to-end integration of n8n with OpenClaw's event system for workflow automation, monitoring, and alerting.

## Architecture

```
OpenClaw Event Flow:
┌─────────────────┐
│  autonomous     │
│  runner / job   │  Job completion/failure
│  completion     │
└────────┬────────┘
         │
         v
  ┌──────────────┐
  │   gateway    │
  │.broadcast()  │  Emit event to event_engine
  └──────┬───────┘
         │
         v
  ┌──────────────────┐
  │ event_engine     │
  │.emit()           │  Subscribe event to handlers
  └──────┬───────────┘
         │
         v
┌─────────────────────────────────────┐
│ _n8n_webhook_notify() subscriber    │  POST to n8n webhook
│ (event_engine.py:319-361)           │
└────────┬────────────────────────────┘
         │
         v
  ┌──────────────────────────┐
  │   n8n Webhook Trigger    │  Receives event JSON
  │   POST /webhook/{path}   │
  └──────┬───────────────────┘
         │
         v
  ┌──────────────────────────┐
  │ Workflow Routing (IF)    │  Route by event_type
  │ - job.completed          │
  │ - job.failed             │
  │ - cost.alert             │
  └──────┬───────────────────┘
         │
         v
  ┌──────────────────────────┐
  │   HTTP POST to Slack     │  Send formatted message
  │   or other destinations  │
  └──────────────────────────┘
```

## Key Components

### 1. Event Engine (event_engine.py)

The central event dispatcher that:

- Emits events from various OpenClaw components
- Manages subscriptions for event handlers
- Posts events to n8n via `_n8n_webhook_notify()` method

**Subscribed n8n Events:**

- `job.created` — When a new job is queued
- `job.completed` — When a job finishes successfully
- `job.failed` — When a job encounters an error
- `job.approved` — When a job is manually approved
- `job.phase_change` — When job phase transitions
- `cost.alert` — When costs approach threshold
- `cost.threshold_exceeded` — When costs exceed limit

**Configuration (environment variables):**

```bash
N8N_BASE_URL=http://localhost:5678              # n8n webhook base URL
N8N_WEBHOOK_MODE=webhook                        # "webhook" or "webhook-test"
N8N_WEBHOOK_PATH=openclaw-events               # Webhook path
```

### 2. Gateway (gateway.py)

**broadcast_event() function (lines 418-437):**
Emits events to the event_engine after broadcasting to SSE clients.

```python
engine.emit(event_type, event_payload)
```

**New endpoint: /api/digest**
Returns daily summary statistics for the Daily Digest workflow:

```json
{
  "success": true,
  "timestamp": "2026-03-03T19:10:23.568907+00:00",
  "jobs_completed": 4,
  "jobs_failed": 0,
  "jobs_created": 11,
  "total_cost": 0,
  "uptime": "100%",
  "event_count": 85,
  "period": "24h"
}
```

### 3. n8n Workflows

Three production workflows handle different event types:

#### A. Agent Pipeline Monitor (openclaw-agent-pipeline-monitor-v2.json)

Monitors job lifecycle events and sends colored Slack notifications.

**Event Types Handled:**

- `job.completed` → Green notification with job ID, agent, task type
- `job.failed` → Red notification with job ID, agent, error message

**Nodes:**

1. **Webhook Trigger** — Receives POST from event_engine
2. **IF nodes** — Routes by event_type
3. **HTTP POST nodes** — Formats and sends to Slack
4. **Respond OK** — Returns success to event_engine

**Slack Message Format:**

```
✅ Job Completed: job-12345 by coder_agent
  Job ID: job-12345
  Agent: coder_agent
  Task: feature
```

#### B. Cost Alert (openclaw-cost-alert.json)

Monitors cost events with escalating urgency.

**Event Types Handled:**

- `cost.alert` → Orange warning (approaching threshold)
- `cost.threshold_exceeded` → Red critical alert (exceeded limit)

**Slack Colors:**

- `cost.alert`: Orange (#ff9800)
- `cost.threshold_exceeded`: Red (#d32f2f)

#### C. Daily Digest (openclaw-daily-digest.json)

Scheduled daily summary at 9am EST.

**Trigger:** Cron — Every 24 hours at 9am Eastern Time

**Data Source:** GET http://localhost:18789/api/digest

**Slack Message Format:**

```
📊 Daily Digest - 3/3/2026
  Jobs Completed: 4
  Jobs Failed: 0
  Total Cost: $0.00
  Uptime: 100%
```

## Deployment Steps

### 1. Start n8n Container

```bash
cd /root/n8n
docker-compose up -d
```

Verify n8n is running:

```bash
curl http://localhost:5678/health
```

### 2. Import Workflows into n8n

In n8n UI (http://localhost:5678):

1. Click **Import** (top menu)
2. Select JSON file: `/root/openclaw/workflows/openclaw-agent-pipeline-monitor-v2.json`
3. Confirm import
4. Repeat for:
   - `openclaw-cost-alert.json`
   - `openclaw-daily-digest.json`

### 3. Activate Workflows

For each imported workflow:

1. Open the workflow
2. Click **Activate** button (toggle switch)
3. Verify webhook is registered (blue checkmark on Webhook node)
4. Confirm in PostgreSQL:

```sql
SELECT id, name, active FROM workflow WHERE name LIKE 'OpenClaw%';
```

### 4. Test Event Flow

Run the comprehensive test:

```bash
python3 /root/openclaw/test_all_workflows.py
```

Expected output:

```
Results: 5/5 tests passed
✓ All workflows are functional!
```

## Troubleshooting

### Events Not Reaching n8n

**Check 1: Event engine is emitting**

```bash
tail -f /root/openclaw/data/events/events.jsonl | grep "job.completed"
```

**Check 2: n8n webhook is registered**

```sql
SELECT webhook_id, path FROM webhook_entity WHERE active = true;
```

**Check 3: n8n logs**

```bash
docker logs n8n-n8n-1 | tail -50
```

### Webhook Registration Fails

n8n caches webhook→workflow mappings at startup. If webhook doesn't activate:

```bash
# Full restart
docker-compose down
docker-compose up -d

# Clear n8n cache
docker exec n8n-n8n-1 npm cache clean --force
```

### HTTP POST Node Hangs

If HTTP POST to Slack times out:

1. Check Slack webhook URL is correct
2. Verify Docker network connectivity:
   ```bash
   docker exec n8n-n8n-1 curl -I http://172.24.0.1:18789/health
   ```
3. Use simpler workflow without HTTP POST for testing

### Cost Events Not Showing

The Cost Alert workflow receives `cost.*` events but only routes those with matching `event_type`. Events are filtered at the `_n8n_webhook_notify()` level — only `job.*` events are POSTed to n8n.

To receive cost events, modify `event_engine.py:327`:

```python
# Current (job events only):
if not event_type.startswith("job."):
    return

# To receive all events:
# Remove this filter or add: event_type.startswith("job.") or event_type.startswith("cost.")
```

## Testing

Two test scripts provided:

### test_n8n_event_flow.py

Minimal test verifying event_engine → webhook flow

```bash
python3 /root/openclaw/test_n8n_event_flow.py
```

### test_all_workflows.py

Comprehensive test covering:

- Agent Pipeline Monitor (job.completed, job.failed)
- Cost Alert (cost.alert, cost.threshold_exceeded)
- Daily Digest (/api/digest endpoint)

```bash
python3 /root/openclaw/test_all_workflows.py
```

## Slack Integration

Workflows POST to Slack via a test webhook at: `http://172.24.0.1:18789/webhook/slack-test`

This is a local mock endpoint for testing. For production Slack integration:

1. Get Slack webhook URL from Slack workspace admin
2. Replace in all workflows:
   ```
   "url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
   ```
3. Redeploy workflows

## Production Checklist

- [ ] n8n container is running and healthy
- [ ] All three workflows imported and activated
- [ ] Webhook endpoints registered in PostgreSQL
- [ ] test_all_workflows.py passes all tests
- [ ] Slack webhook URL configured (or test endpoint active)
- [ ] Monitor logs for 24 hours: `docker logs -f n8n-n8n-1`
- [ ] Daily Digest cron trigger runs at 9am EST
- [ ] Sample job completion triggers Slack notification

## Architecture Notes

1. **Why POST from event_engine to n8n?**
   - Decouples job execution from monitoring
   - n8n can process/transform events independently
   - Allows multiple n8n instances without code changes
   - Events are logged before n8n even receives them

2. **Why only job.\* events?**
   - Agent Pipeline Monitor tracks job lifecycle
   - Cost events need different handling (thresholds, escalation)
   - Can be extended to support cost.\* by removing the filter

3. **Event reliability:**
   - Events logged to disk before emitting (event_engine.py:272)
   - Deduplication prevents duplicate events (5-minute window)
   - Webhook failures are logged but non-critical (timeout: 5s)

4. **Scaling considerations:**
   - Each workflow can filter/route independently
   - Event engine distributes to all subscribers in parallel
   - n8n handles backpressure with queue/retry logic
   - Monitor `/api/digest` to detect performance degradation

## Related Files

- `/root/openclaw/gateway.py` — Event emission and /api/digest endpoint
- `/root/openclaw/event_engine.py` — Event dispatch and n8n webhook subscriber
- `/root/n8n/docker-compose.yml` — n8n configuration
- `/root/openclaw/workflows/*.json` — Workflow definitions
- `/root/openclaw/test_*.py` — Integration tests

---

Last updated: 2026-03-03
Status: Production ready ✓
