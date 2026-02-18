# OpenClaw Request Logging & Audit Trail

Complete implementation of request logging and audit trail for OpenClaw with D1 database integration.

## Overview

The audit trail system logs every request with comprehensive metadata for debugging, monitoring, and compliance:

- **Request metadata**: message, model, agent, channel, user ID
- **Response metrics**: tokens (input/output), cost breakdown, latency
- **Status tracking**: HTTP code, success/error/timeout, error messages
- **Debugging info**: trace ID, routing confidence, cost calculation details

## Architecture

```
FastAPI Gateway → RequestLogger → D1 SQLite Database
                                    ├── request_logs table (primary)
                                    └── error_logs table (supplementary)
```

### Components

1. **`request_logger.py`** — Core logging module
   - `RequestLogger` class: thread-safe database operations
   - `RequestLog` dataclass: type-safe log entry
   - Global `get_logger()` function
   - Helper `log_request()` convenience function

2. **`audit_routes.py`** — FastAPI endpoints
   - `/api/audit/logs?limit=100` — Recent requests
   - `/api/audit/logs/{date}` — Daily summary
   - `/api/audit/costs?days=30` — Cost breakdown
   - `/api/audit/errors?days=30` — Error analysis
   - `/api/audit/agents?days=30` — Agent statistics
   - `/api/audit/slowest?limit=10` — Slowest requests
   - `/api/audit/health` — System health

3. **`audit_queries.sql`** — Sample SQL queries
   - Daily cost trends
   - Agent usage statistics
   - Model performance analysis
   - Error breakdown
   - Performance metrics
   - Cost optimization insights

## Integration with Gateway

### Step 1: Import modules

```python
from request_logger import log_request, create_trace_id, get_logger
from audit_routes import router as audit_router
```

### Step 2: Add audit routes to FastAPI

```python
app.include_router(audit_router)
```

### Step 3: Log requests in your endpoints

```python
@app.post("/api/chat")
async def chat(request: ChatRequest):
    trace_id = create_trace_id()
    start_time = time.time()

    try:
        # Your logic here...
        response = await call_agent(request.message)

        latency_ms = int((time.time() - start_time) * 1000)

        # Log successful request
        log_request(
            channel="telegram",
            user_id=request.user_id,
            message=request.message,
            agent_selected="pm_agent",
            model="claude-3-5-sonnet-20241022",
            response_text=response.text,
            output_tokens=response.usage.output_tokens,
            input_tokens=response.usage.input_tokens,
            cost=response.cost,
            status="success",
            http_code=200,
            routing_confidence=0.95,
            session_key=request.session_key,
            latency_ms=latency_ms,
        )

        return response

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)

        # Log failed request
        log_request(
            channel="telegram",
            user_id=request.user_id,
            message=request.message,
            agent_selected="pm_agent",
            model="claude-3-5-sonnet-20241022",
            response_text="",
            output_tokens=0,
            input_tokens=0,
            cost=0.0,
            status="error",
            http_code=500,
            error_message=str(e),
            latency_ms=latency_ms,
        )

        raise
```

## Database Schema

### `request_logs` table

```sql
CREATE TABLE request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identification
    trace_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,

    -- Request context
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_key TEXT,

    -- Request content
    message TEXT NOT NULL,
    message_length INTEGER,

    -- Routing
    agent_selected TEXT NOT NULL,
    routing_confidence REAL,

    -- Model info
    model TEXT NOT NULL,

    -- Response
    response_text TEXT,
    output_tokens INTEGER,
    input_tokens INTEGER,

    -- Costs (detailed breakdown)
    cost REAL,
    cost_breakdown_input REAL,
    cost_breakdown_output REAL,

    -- Status
    status TEXT NOT NULL,  -- "success", "error", "timeout"
    http_code INTEGER,
    error_message TEXT,

    -- Performance
    latency_ms INTEGER,

    -- Metadata (JSON)
    metadata TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### `error_logs` table

```sql
CREATE TABLE error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (trace_id) REFERENCES request_logs(trace_id)
);
```

## API Endpoints

### GET /api/audit/logs

Get recent request logs with pagination.

**Query Parameters:**

- `limit` (int, default 100, max 1000) — Number of logs to return
- `offset` (int, default 0) — Pagination offset

**Response:**

```json
{
  "status": "success",
  "count": 25,
  "limit": 100,
  "offset": 0,
  "logs": [
    {
      "trace_id": "550e8400-e29b-41d4-a716-446655440000",
      "timestamp": "2026-02-18T15:30:45.123456Z",
      "channel": "telegram",
      "user_id": "user123",
      "message": "What is the capital of France?",
      "agent_selected": "pm_agent",
      "model": "claude-3-5-sonnet-20241022",
      "output_tokens": 42,
      "input_tokens": 12,
      "cost": 0.000891,
      "status": "success",
      "http_code": 200,
      "latency_ms": 1250
    }
  ]
}
```

### GET /api/audit/logs/{date}

Get daily summary for a specific date (YYYY-MM-DD).

**Response:**

```json
{
  "status": "success",
  "date": "2026-02-18",
  "summary": {
    "total_requests": 234,
    "total_cost": 4.52,
    "total_input_tokens": 45230,
    "total_output_tokens": 8932,
    "avg_latency_ms": 1240,
    "successful": 231,
    "errors": 3,
    "timeouts": 0,
    "agents": {
      "pm_agent": { "count": 120, "cost": 2.4 },
      "codegen_agent": { "count": 114, "cost": 2.12 }
    },
    "channels": {
      "telegram": { "count": 150, "cost": 3.0 },
      "slack": { "count": 84, "cost": 1.52 }
    },
    "models": {
      "claude-3-5-sonnet-20241022": { "count": 180, "cost": 3.6 },
      "claude-3-5-haiku-20241022": { "count": 54, "cost": 0.92 }
    }
  }
}
```

### GET /api/audit/costs?days=30

Get cost breakdown for the last N days.

**Query Parameters:**

- `days` (int, default 30, range 1-365) — Number of days to analyze

**Response:**

```json
{
  "status": "success",
  "period_days": 30,
  "breakdown": {
    "daily": [
      {
        "date": "2026-02-18",
        "cost": 4.52,
        "requests": 234,
        "avg_confidence": 0.94
      },
      {
        "date": "2026-02-17",
        "cost": 5.1,
        "requests": 287,
        "avg_confidence": 0.92
      }
    ],
    "by_agent": {
      "pm_agent": { "cost": 64.2, "requests": 1200 },
      "codegen_agent": { "cost": 52.4, "requests": 980 }
    },
    "by_model": {
      "claude-3-5-sonnet-20241022": { "cost": 90.3, "requests": 1800 },
      "claude-3-5-haiku-20241022": { "cost": 26.3, "requests": 380 }
    }
  }
}
```

### GET /api/audit/errors?days=30

Analyze errors for the last N days.

**Response:**

```json
{
  "status": "success",
  "period_days": 30,
  "analysis": {
    "errors_by_type": [
      {
        "type": "RateLimitError",
        "count": 5,
        "sample": "Rate limit exceeded: 100 requests/minute"
      },
      {
        "type": "TimeoutError",
        "count": 3,
        "sample": "Request timeout after 30s"
      }
    ],
    "errors_by_agent": {
      "pm_agent": 5,
      "security_agent": 3
    },
    "http_errors": {
      "429": 5,
      "504": 3,
      "500": 2
    }
  }
}
```

### GET /api/audit/agents?days=30

Get agent usage statistics.

**Response:**

```json
{
  "status": "success",
  "period_days": 30,
  "agents": [
    {
      "agent_selected": "pm_agent",
      "requests": 1200,
      "total_cost": 64.2,
      "avg_cost": 0.0535,
      "avg_latency_ms": 1240,
      "successful": 1195,
      "errors": 5,
      "avg_confidence": 0.94
    },
    {
      "agent_selected": "codegen_agent",
      "requests": 980,
      "total_cost": 52.4,
      "avg_cost": 0.0534,
      "avg_latency_ms": 1560,
      "successful": 975,
      "errors": 5,
      "avg_confidence": 0.89
    }
  ]
}
```

### GET /api/audit/slowest?limit=10

Get slowest requests.

**Response:**

```json
{
  "status": "success",
  "count": 10,
  "limit": 10,
  "slowest_requests": [
    {
      "trace_id": "550e8400-e29b-41d4-a716-446655440000",
      "timestamp": "2026-02-18T14:20:30.000000Z",
      "agent_selected": "codegen_agent",
      "model": "claude-3-5-sonnet-20241022",
      "latency_ms": 8932,
      "cost": 0.15,
      "status": "success"
    }
  ]
}
```

### GET /api/audit/health

Health check for the audit system.

**Response:**

```json
{
  "status": "healthy",
  "message": "Audit trail system operational"
}
```

## Usage Examples

### Example 1: Get recent logs

```bash
curl "http://localhost:18789/api/audit/logs?limit=50"
```

### Example 2: Get today's summary

```bash
curl "http://localhost:18789/api/audit/logs/2026-02-18"
```

### Example 3: Get cost breakdown for last 30 days

```bash
curl "http://localhost:18789/api/audit/costs?days=30"
```

### Example 4: Analyze errors for last 7 days

```bash
curl "http://localhost:18789/api/audit/errors?days=7"
```

### Example 5: Get slowest requests (top 20)

```bash
curl "http://localhost:18789/api/audit/slowest?limit=20"
```

### Example 6: Get agent statistics

```bash
curl "http://localhost:18789/api/audit/agents?days=30"
```

## Key Features

### Thread-Safe Logging

- Uses `threading.RLock()` for concurrent access
- Safe for multi-threaded gateway

### Comprehensive Metrics

- **Request**: message, model, agent, channel
- **Response**: tokens (input/output), cost breakdown
- **Performance**: latency in milliseconds
- **Status**: HTTP code, success/error/timeout
- **Debugging**: trace ID, routing confidence, error messages

### Efficient Queries

- Indexed on: trace_id, timestamp, agent, channel, user_id, status
- Fast lookups and aggregations
- Date-range queries optimized

### Cost Analysis

- Detailed input/output cost breakdown
- Daily cost trends
- Cost by agent and model
- Identifies optimization opportunities

### Error Tracking

- Separate error_logs table
- Error type classification
- Stack trace storage
- Links to request_logs via trace_id

### Audit Trail

- Immutable timestamps (ISO 8601)
- Trace IDs for request correlation
- Complete request/response history
- User activity tracking

## Configuration

Set environment variable to customize database location:

```bash
export OPENCLAW_LOG_DB=/data/openclaw_audit.db
```

Default: `/tmp/openclaw_audit.db`

## Performance Considerations

- Database file is SQLite (single-process, no external server)
- Suitable for small-medium deployments (<1M requests/month)
- For large scale, migrate to Cloudflare D1 or PostgreSQL
- Indexes on common query patterns for fast lookups

## Compliance & Privacy

- All timestamps in UTC (ISO 8601)
- Immutable audit log (append-only)
- Trace IDs enable request correlation
- Support for user data retention policies

## Maintenance

### Backup the database

```bash
cp /tmp/openclaw_audit.db /backups/openclaw_audit_$(date +%Y%m%d_%H%M%S).db
```

### Archive old logs (example)

```sql
-- Delete logs older than 90 days
DELETE FROM request_logs
WHERE timestamp < datetime('now', '-90 days');

DELETE FROM error_logs
WHERE timestamp < datetime('now', '-90 days');
```

### Vacuum database (optimize)

```bash
sqlite3 /tmp/openclaw_audit.db "VACUUM;"
```

## Future Enhancements

- [ ] Export to CSV/JSON
- [ ] Grafana dashboard integration
- [ ] Real-time alerting on error thresholds
- [ ] Cost anomaly detection
- [ ] Automated backup to cloud storage
- [ ] Role-based access control for endpoints
- [ ] Integration with logging aggregation (e.g., ELK)
