# OpenClaw Monitoring Dashboard - Quick Start

## Access the Dashboard

Once deployed and integrated with the gateway:

```
http://gateway-host:18789/dashboard.html
```

Or serve locally for development:

```bash
cd /root/openclaw
python -m http.server 8000
# Visit: http://localhost:8000/dashboard.html
```

## What You'll See

### Top Metrics (Update every 10s)

- **487 req/min** - Current request rate
- **234ms P50** - Median response time
- **0.32% error** - Current error rate
- **$4.23/hr** - Hourly cost

### Real-time Charts

1. **Requests Over Time** - 60-minute trend
2. **Latency Distribution** - P50/P95/P99 percentiles
3. **Daily Cost Trend** - Last 30 days
4. **Cost Distribution** - By agent pie chart

### Agent Status

- Green cards = Healthy (99%+ uptime)
- Yellow cards = Degraded (90-99% uptime)
- Red cards = Critical (<90% uptime)

### Cost Dashboard

- **30-day total:** $3,404 (optimized routing)
- **All-Claude baseline:** $11,245
- **Savings:** $7,841 (69.7% reduction)

### Error Breakdown (Last 24h)

| Error Type | Count | %     | Retry |
| ---------- | ----- | ----- | ----- |
| Timeouts   | 23    | 0.18% | 87%   |
| Auth Fails | 8     | 0.06% | 75%   |
| VPS Down   | 5     | 0.04% | 92%   |

## Common Tasks

### Check System Health

1. Verify "All Systems Operational" badge is green
2. Check all agents show green uptime (99%+)
3. Confirm error rate < 0.5%
4. Check latency P99 < 1,000ms

### Investigate High Latency

1. Check "Latency Distribution" chart
2. Look for spikes in P99 line
3. Identify slow agent in "Agent Health" cards
4. Check agent response time trend
5. May need to scale or restart

### Analyze Error Spike

1. Go to "Error Analysis" section
2. Check "Error Trends" chart for timing
3. See "Error Type Distribution"
4. Check retry success rate
5. If >90% retry success, likely self-healing

### Review Costs

1. Check "Daily Cost Trend" chart
2. Look at "Cost Distribution by Agent" pie
3. Review "Cost by Task Type"
4. Compare to "Intelligent Routing Savings"

## Key Metrics to Watch

### Red Flags

```
⚠️ Error rate > 1%              → System issue
⚠️ Latency P99 > 2000ms         → Performance problem
⚠️ Agent uptime < 95%           → Agent reliability issue
⚠️ Cost spike > 20%             → Unexpected usage
⚠️ "Last seen" > 2 min ago      → Agent not responding
```

### Good Signs

```
✅ Error rate < 0.5%            → Operating normally
✅ Latency P99 < 1000ms         → Good performance
✅ All agents 99%+ uptime       → Excellent reliability
✅ Cost stable/trending down    → Efficient routing
✅ 90%+ retry success rate      → Resilient error handling
```

## API Endpoints (for programmatic access)

Get real-time summary:

```bash
curl http://localhost:18789/api/metrics/summary \
  -H "X-Auth-Token: your-token"
```

Get agent health:

```bash
curl http://localhost:18789/api/metrics/agents \
  -H "X-Auth-Token: your-token"
```

Get error analysis (24h):

```bash
curl "http://localhost:18789/api/metrics/errors?hours=24" \
  -H "X-Auth-Token: your-token"
```

Get cost breakdown:

```bash
curl http://localhost:18789/api/metrics/costs \
  -H "X-Auth-Token: your-token"
```

Get all dashboard data:

```bash
curl http://localhost:18789/api/metrics/dashboard-data \
  -H "X-Auth-Token: your-token"
```

## Troubleshooting

### Dashboard shows no data

- Check gateway is running: `curl http://localhost:18789/health`
- Verify metrics API: `curl http://localhost:18789/api/metrics/summary`
- Check browser console (F12 → Console) for errors
- Ensure at least one request made to gateway

### Charts not updating

- Refresh page (F5)
- Check network tab (F12 → Network) for API calls
- Verify /api/metrics/\* endpoints accessible
- Look for CORS errors

### "Last seen" shows old timestamp

- System hasn't received requests recently
- Check if agent is being used
- Verify agent is running
- Send test request

### Cost numbers incorrect

- Verify cost_tracker.py is logging
- Check token pricing is up-to-date
- Compare to actual bill

## Integration Checklist

Before going live:

- [ ] Dashboard HTML deployed at `/root/openclaw/dashboard.html`
- [ ] `metrics_collector.py` in gateway directory
- [ ] `gateway_metrics_integration.py` routes in gateway
- [ ] Metrics middleware added to FastAPI
- [ ] Metrics file writable: `/tmp/openclaw_metrics.jsonl`
- [ ] API endpoints responding with data
- [ ] Dashboard loads and displays charts
- [ ] Charts update every 10 seconds
- [ ] All agents visible in health section
- [ ] At least 5 minutes data collected
- [ ] No console errors when loading
- [ ] Cost calculations correct

## Sample Data

Dashboard includes sample data by default:

- 487 req/min trending upward
- Latency P50: 234ms, P95: 487ms, P99: 892ms
- Error rate: 0.32%
- Cost: $4.23/hour, $3,404 for 30 days
- 4 agents with varying uptime (93-99%)

To generate real data:

```bash
for i in {1..100}; do
  curl http://localhost:18789/api/chat \
    -X POST \
    -H "X-Auth-Token: your-token" \
    -H "Content-Type: application/json" \
    -d '{"content":"hello","agent":"pm"}'
  sleep 0.1
done
```

## Advanced Usage

### Export Metrics to CSV

```python
import csv
import json

with open('/tmp/openclaw_metrics.jsonl') as f:
    lines = f.readlines()

with open('/tmp/metrics.csv', 'w', newline='') as out:
    writer = csv.writer(out)
    writer.writerow(['timestamp', 'agent', 'latency_ms', 'success', 'cost'])

    for line in lines:
        data = json.loads(line)
        writer.writerow([
            data.get('timestamp'),
            data.get('agent'),
            data.get('latency_ms'),
            data.get('success'),
            data.get('cost')
        ])
```

### Create Alert Script

```python
import requests
import time

while True:
    resp = requests.get('http://localhost:18789/api/metrics/summary')
    metrics = resp.json()

    if metrics['error_rate_percent'] > 1.0:
        print("ALERT: High error rate!")

    if metrics['latency_p99_ms'] > 2000:
        print("ALERT: High latency!")

    time.sleep(60)
```

## Resources

- Full documentation: [MONITORING_DASHBOARD.md](MONITORING_DASHBOARD.md)
- Metrics collector: [metrics_collector.py](metrics_collector.py)
- API integration: [gateway_metrics_integration.py](gateway_metrics_integration.py)
- Phase 5X deployment: See MEMORY.md
- Cost tracking: [cost_tracker.py](cost_tracker.py)
- Agent routing: [agent_router.py](agent_router.py)
