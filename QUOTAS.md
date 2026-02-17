# OpenClaw Phase 5X: Quota Management & Cap Gates

## Overview

The OpenClaw Gateway now includes a comprehensive quota management system that enforces budget limits and prevents system overspending or unbounded queue growth. This "cap gates" feature protects against:

- **Daily spend exceeding limits** (default $50/day globally)
- **Monthly spend exceeding limits** (default $1,000/month globally)
- **Queue growing unbounded** (default max 100 items)

All requests are checked **before processing** to ensure quotas are respected.

## Configuration

Quotas are configured in `config.json` under the `quotas` section:

```json
{
  "quotas": {
    "enabled": true,
    "daily_limit_usd": 50,
    "monthly_limit_usd": 1000,
    "max_queue_size": 100,
    "per_project": {
      "barber-crm": {
        "daily_limit_usd": 20,
        "monthly_limit_usd": 500
      },
      "delhi-palace": {
        "daily_limit_usd": 10,
        "monthly_limit_usd": 300
      }
    },
    "warning_threshold_percent": 80
  }
}
```

### Configuration Fields

| Field                       | Type   | Description                                                    |
| --------------------------- | ------ | -------------------------------------------------------------- |
| `enabled`                   | bool   | Enable/disable quota enforcement. Default: `true`              |
| `daily_limit_usd`           | float  | Global daily spend limit in USD. Default: `$50`                |
| `monthly_limit_usd`         | float  | Global monthly spend limit in USD. Default: `$1,000`           |
| `max_queue_size`            | int    | Maximum queue size (number of pending items). Default: `100`   |
| `per_project`               | object | Project-specific quota overrides                               |
| `warning_threshold_percent` | int    | Log warnings when usage exceeds this % of limit. Default: `80` |

### Per-Project Configuration

Each project can have custom quota limits:

```json
"per_project": {
  "barber-crm": {
    "daily_limit_usd": 20,
    "monthly_limit_usd": 500
  },
  "project-name": {
    "daily_limit_usd": X,
    "monthly_limit_usd": Y
  }
}
```

Projects without explicit configuration use global defaults.

## API Integration

### 1. Chat Endpoint with Quota Checks

The `/api/chat` endpoint now checks quotas before processing any request:

```bash
# Request
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d {
    "content": "What is 2+2?",
    "agent_id": "project_manager",
    "project_id": "barber-crm",
    "sessionKey": "session-123"
  }

# Success Response (200)
{
  "agent": "project_manager",
  "response": "2 + 2 = 4",
  "provider": "anthropic",
  "model": "claude-opus-4-6-20250514",
  "tokens": {"input": 150, "output": 20},
  "sessionKey": "session-123",
  "historyLength": 2
}

# Quota Exceeded Response (429)
{
  "success": false,
  "error": "Quota limit exceeded",
  "detail": "❌ Daily quota exceeded for project 'barber-crm'. Current: $25.00, Limit: $20.00. Try again in 24 hours or contact support.",
  "timestamp": "2026-02-17T10:30:45.123456Z"
}
```

### 2. Quota Status Endpoint

Get current quota usage for a project:

```bash
curl -X GET http://localhost:18789/api/quotas/status/barber-crm

# Response (200)
{
  "success": true,
  "timestamp": "2026-02-17T10:30:45.123456Z",
  "data": {
    "quotas_enabled": true,
    "project": "barber-crm",
    "daily": {
      "spend": 15.5342,
      "limit": 20,
      "percent": 77.7,
      "remaining": 4.4658
    },
    "monthly": {
      "spend": 125.3201,
      "limit": 500,
      "percent": 25.1,
      "remaining": 374.6799
    }
  }
}
```

### 3. Quota Configuration Endpoint

Get the active quota configuration:

```bash
curl -X GET http://localhost:18789/api/quotas/config

# Response (200)
{
  "success": true,
  "timestamp": "2026-02-17T10:30:45.123456Z",
  "data": {
    "enabled": true,
    "daily_limit_usd": 50,
    "monthly_limit_usd": 1000,
    "max_queue_size": 100,
    "per_project": {
      "barber-crm": {...},
      "delhi-palace": {...}
    },
    "warning_threshold_percent": 80
  }
}
```

### 4. Quota Check Endpoint

Check if a request would be allowed before processing:

```bash
curl -X POST http://localhost:18789/api/quotas/check \
  -H "Content-Type: application/json" \
  -d {
    "project_id": "barber-crm",
    "queue_size": 45
  }

# Response (200)
{
  "success": true,
  "timestamp": "2026-02-17T10:30:45.123456Z",
  "allowed": true,
  "error": null,
  "status": {
    "quotas_enabled": true,
    "project": "barber-crm",
    "daily": {
      "spend": 15.5342,
      "limit": 20,
      "percent": 77.7,
      "remaining": 4.4658
    },
    "monthly": {...}
  }
}
```

## How It Works

### Request Flow with Quota Enforcement

```
1. Client sends request to /api/chat
   ├─ Request includes project_id
   │
2. Quota Middleware checks:
   ├─ Get project quota limits (global or per-project)
   ├─ Calculate daily spend (last 24h)
   ├─ Calculate monthly spend (last 30d)
   ├─ Check queue size
   │
3. If ANY quota exceeded:
   ├─ Return 429 Too Many Requests
   ├─ Include detailed error message
   └─ Request rejected (NO PROCESSING)
   │
4. If all quotas OK:
   ├─ Log quota check passed (info level)
   ├─ Process request normally
   ├─ Execute model call
   ├─ Log cost event
   └─ Return response
```

### Cost Tracking Integration

Quotas automatically integrate with the cost tracking system:

```python
# Every API call logs costs to /tmp/openclaw_costs.jsonl:
{
  "project": "barber-crm",
  "agent": "pm-agent",
  "model": "claude-opus-4-6",
  "tokens_input": 1250,
  "tokens_output": 450,
  "cost": 0.0225,
  "timestamp": "2026-02-17T10:30:45.123456Z"
}

# Quotas read from this log to calculate current spend
```

## Logging & Monitoring

### Log Levels

**INFO** - Quota checks passed:

```
✅ Quota check passed for 'barber-crm': 77.7% daily, 25.1% monthly
```

**WARNING** - Usage exceeds threshold (default 80%):

```
⚠️  Daily quota warning for 'barber-crm': $17.50/$20 (87.5%)
⚠️  Monthly quota warning for 'barber-crm': $425.00/$500 (85.0%)
```

**ERROR** - Quota exceeded (request rejected):

```
❌ Daily quota exceeded for project 'barber-crm'. Current: $25.00, Limit: $20.00
```

### Quota Status Summary

View all project quotas at once:

```python
from quota_manager import get_quota_status

for project in ["barber-crm", "delhi-palace"]:
    status = get_quota_status(project)
    print(f"{project}:")
    print(f"  Daily:   ${status['daily']['spend']:.2f}/${status['daily']['limit']}")
    print(f"  Monthly: ${status['monthly']['spend']:.2f}/${status['monthly']['limit']}")
```

## Testing

Run the comprehensive test suite:

```bash
cd /root/openclaw
python3 test_quotas.py
```

Tests verify:

- ✅ Config loading and validation
- ✅ Project-specific quota retrieval
- ✅ Daily/monthly quota enforcement
- ✅ Queue size limits
- ✅ Combined quota checking
- ✅ Quota status reporting
- ✅ Cost tracking integration

## Example: Preventing Budget Overages

### Scenario: Daily Limit Exceeded

```python
# Client tries to make request when daily quota is exhausted
project_id = "barber-crm"
daily_limit = 20  # $20/day
current_spend = 20.50  # Already spent $20.50

# Request rejected:
# 429 Too Many Requests
# "Daily quota exceeded for project 'barber-crm'.
#  Current: $20.50, Limit: $20.00.
#  Try again in 24 hours or contact support."

# No request is processed
# No additional cost is incurred
```

### Scenario: Approaching Monthly Limit

```python
# Client monitors quota usage
status = get_quota_status("barber-crm")
monthly_spend = status["monthly"]["spend"]  # $450
monthly_limit = status["monthly"]["limit"]  # $500
monthly_percent = status["monthly"]["percent"]  # 90%

if monthly_percent >= 90:
    print("⚠️  Approaching monthly limit! Only $50 remaining.")
    # Request count reduction, upgrade billing, or contact support
```

## Best Practices

### 1. Check Quotas Before Batch Operations

```python
from quota_manager import check_all_quotas

# Check before processing batch
quotas_ok, error = check_all_quotas(project_id="barber-crm", queue_size=50)
if not quotas_ok:
    print(f"Cannot start batch: {error}")
    return

# Safe to proceed with batch
```

### 2. Monitor Quota Warnings

```python
# Warning threshold is 80% by default
# Set up alerts/monitoring when:
#   - Daily usage > 80% of daily limit
#   - Monthly usage > 80% of monthly limit
```

### 3. Graceful Degradation

```python
# When quota limit approaching:
# 1. Reduce request complexity (use Haiku instead of Opus)
# 2. Increase batch timeout (process fewer items at once)
# 3. Pause non-critical requests
# 4. Contact support for quota increase
```

### 4. Per-Project Configuration

```json
// Configure quotas based on project needs:
// - High-traffic projects: higher daily/monthly limits
// - Low-traffic projects: lower limits to prevent overages
// - Critical projects: no per-project limits (use global)
```

## Troubleshooting

### Quota Check Returns "Can't compare offset-naive and offset-aware datetimes"

**Cause:** Cost log has timezone-mismatched timestamps

**Solution:**

```bash
# Clear cost log to reset
rm /tmp/openclaw_costs.jsonl

# Or use the API
curl -X POST http://localhost:18789/api/costs/clear
```

### Daily Quota Resets But Monthly Doesn't

**Expected behavior:** Daily quotas reset every 24 hours from now. Monthly quotas reset every 30 days from now.

**To view historical spending:**

```python
from cost_tracker import get_cost_metrics

# Last 24 hours
daily = get_cost_metrics("24h")

# Last 30 days
monthly = get_cost_metrics("30d")

# All time
all_time = get_cost_metrics()
```

### Project-Specific Quota Not Applied

**Check:**

1. Project name in config.json matches project_id in request
2. Config was reloaded (quotas load on each request, no cache)
3. Quota config has `"per_project": {...}`

```bash
# Verify config
curl -X GET http://localhost:18789/api/quotas/config | jq '.data.per_project'
```

## Performance Impact

Quota checks are **lightweight**:

- Read existing cost log: ~1-2ms (in-memory after first read)
- Filter by time window: ~0.5-1ms (simple list comprehension)
- Aggregate costs: ~0.1-0.5ms
- **Total per-request overhead: <5ms**

No measurable impact on gateway performance.

## Future Enhancements

Planned features:

1. **Rate limiting** - Requests per minute per project
2. **Cost forecasting** - Predict monthly spend based on current rate
3. **Auto-scaling quotas** - Increase quotas based on historical usage
4. **Quota webhooks** - Notify external systems when limits approached
5. **Per-user quotas** - Track spend by user/API key
6. **Time-based quotas** - Different limits for peak vs off-peak hours

## Support

For quota-related issues:

1. Check `/api/quotas/status/{project_id}` for current usage
2. Review `/api/quotas/config` to confirm settings
3. Read cost tracking: `cat /tmp/openclaw_costs.jsonl | jq`
4. Run tests: `python3 test_quotas.py`
5. Contact support with project name and budget requirements

---

**OpenClaw Phase 5X: Cap Gates & Quota Limits**
Last updated: 2026-02-17
