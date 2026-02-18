# OpenClaw Audit Trail - Quick Reference

## Files

| File                   | Purpose                | Lines |
| ---------------------- | ---------------------- | ----- |
| `request_logger.py`    | Core logging module    | 521   |
| `audit_routes.py`      | FastAPI endpoints      | 210   |
| `audit_queries.sql`    | SQL query examples     | 550   |
| `AUDIT_INTEGRATION.md` | Full integration guide | 500   |
| `test_audit_system.py` | Test & demo script     | 315   |

## Quick Integration (5 minutes)

### 1. Add to gateway.py imports

```python
from request_logger import log_request, create_trace_id
from audit_routes import router as audit_router
```

### 2. Include router

```python
app.include_router(audit_router)
```

### 3. Log request in handler

```python
import time

start = time.time()
try:
    response = await my_agent(message)

    log_request(
        channel="telegram",
        user_id=user_id,
        message=message,
        agent_selected="pm_agent",
        model="claude-3-5-sonnet-20241022",
        response_text=response.text,
        output_tokens=response.usage.output_tokens,
        input_tokens=response.usage.input_tokens,
        cost=0.0045,
        status="success",
        http_code=200,
        latency_ms=int((time.time() - start) * 1000)
    )
except Exception as e:
    log_request(..., status="error", http_code=500, error_message=str(e), ...)
```

## API Endpoints

| Endpoint                     | Purpose        | Example               |
| ---------------------------- | -------------- | --------------------- |
| `GET /api/audit/logs`        | Recent logs    | `?limit=100&offset=0` |
| `GET /api/audit/logs/{date}` | Daily summary  | `/logs/2026-02-18`    |
| `GET /api/audit/costs`       | Cost breakdown | `?days=30`            |
| `GET /api/audit/errors`      | Error analysis | `?days=30`            |
| `GET /api/audit/agents`      | Agent stats    | `?days=30`            |
| `GET /api/audit/slowest`     | Slow requests  | `?limit=10`           |
| `GET /api/audit/health`      | System health  | (no params)           |

## Common Queries

### Daily Cost

```sql
SELECT DATE(timestamp), COUNT(*), SUM(cost)
FROM request_logs
GROUP BY DATE(timestamp)
ORDER BY DATE DESC;
```

### Agent Stats

```sql
SELECT agent_selected, COUNT(*), SUM(cost), AVG(latency_ms)
FROM request_logs
WHERE timestamp >= datetime('now', '-30 days')
GROUP BY agent_selected;
```

### Error Rate

```sql
SELECT agent_selected,
       ROUND(100.0 * COUNT(CASE WHEN status='error' THEN 1 END) / COUNT(*), 2) as error_rate
FROM request_logs
GROUP BY agent_selected;
```

### Slowest Requests

```sql
SELECT timestamp, agent_selected, latency_ms, cost
FROM request_logs
ORDER BY latency_ms DESC
LIMIT 10;
```

### Cost by Model

```sql
SELECT model, SUM(cost), COUNT(*)
FROM request_logs
WHERE status = 'success'
GROUP BY model
ORDER BY SUM(cost) DESC;
```

## Fields Logged

| Field                   | Type     | Purpose                          |
| ----------------------- | -------- | -------------------------------- |
| `trace_id`              | UUID     | Unique request ID                |
| `timestamp`             | ISO 8601 | Request time (UTC)               |
| `channel`               | string   | telegram, slack, discord, etc    |
| `user_id`               | string   | User identifier                  |
| `message`               | text     | User message content             |
| `agent_selected`        | string   | pm_agent, codegen_agent, etc     |
| `model`                 | string   | Model used (haiku, sonnet, opus) |
| `output_tokens`         | int      | Response tokens                  |
| `input_tokens`          | int      | Request tokens                   |
| `cost`                  | float    | Total cost in USD                |
| `cost_breakdown_input`  | float    | Input cost                       |
| `cost_breakdown_output` | float    | Output cost                      |
| `status`                | string   | success, error, timeout          |
| `http_code`             | int      | HTTP response code               |
| `error_message`         | string   | Error details if failed          |
| `latency_ms`            | int      | Response time in ms              |
| `routing_confidence`    | float    | 0.0-1.0 confidence score         |

## curl Examples

```bash
# Get last 50 logs
curl http://localhost:18789/api/audit/logs?limit=50

# Get today's summary
curl http://localhost:18789/api/audit/logs/2026-02-18

# Get costs for last 30 days
curl http://localhost:18789/api/audit/costs?days=30

# Get errors in last 7 days
curl http://localhost:18789/api/audit/errors?days=7

# Get agent stats
curl http://localhost:18789/api/audit/agents?days=30

# Get slowest 20 requests
curl http://localhost:18789/api/audit/slowest?limit=20

# Health check
curl http://localhost:18789/api/audit/health

# Pretty print JSON
curl -s http://localhost:18789/api/audit/logs?limit=5 | jq .
```

## Configuration

```bash
# Use default location (/tmp/openclaw_audit.db)
# OR set environment variable:
export OPENCLAW_LOG_DB=/data/openclaw_audit.db
```

## Testing

Run test script to verify installation:

```bash
python3 test_audit_system.py
```

Expected output:

- 120 sample logs generated
- All queries demonstrate working system
- Shows cost breakdown, agent stats, error analysis
- Verifies database schema and indexes

## Database Maintenance

```bash
# Backup
cp /tmp/openclaw_audit.db /backups/audit_$(date +%Y%m%d).db

# Delete old logs (90+ days)
sqlite3 /tmp/openclaw_audit.db "DELETE FROM request_logs WHERE timestamp < datetime('now', '-90 days');"

# Optimize database size
sqlite3 /tmp/openclaw_audit.db "VACUUM;"

# Check database stats
sqlite3 /tmp/openclaw_audit.db "SELECT COUNT(*) FROM request_logs; SELECT AVG(LENGTH(message)) FROM request_logs;"
```

## Monitoring Tips

1. **Daily**: Check cost trends

   ```bash
   curl http://localhost:18789/api/audit/logs/$(date +%Y-%m-%d)
   ```

2. **Weekly**: Review agent performance

   ```bash
   curl http://localhost:18789/api/audit/agents?days=7
   ```

3. **Monthly**: Analyze costs and errors

   ```bash
   curl http://localhost:18789/api/audit/costs?days=30
   curl http://localhost:18789/api/audit/errors?days=30
   ```

4. **Ongoing**: Monitor slow requests
   ```bash
   curl http://localhost:18789/api/audit/slowest?limit=20
   ```

## Troubleshooting

**Database locked error?**

- Check for long-running queries
- Restart gateway if needed
- Verify disk space

**Missing data?**

- Verify log_request() calls in handlers
- Check environment variable OPENCLAW_LOG_DB
- Restart gateway to reinitialize DB

**Slow queries?**

- Run VACUUM to optimize
- Archive old logs
- Check available disk space

## Performance

- ~2-3 KB per log entry
- <100ms queries with indexes
- Thread-safe concurrent writes
- Suitable for 1M requests/month

## Future Enhancements

- [ ] CSV export
- [ ] Grafana dashboard
- [ ] Real-time alerts
- [ ] Anomaly detection
- [ ] Cloud backup integration
- [ ] Role-based access control

---

**Last Updated:** 2026-02-18
