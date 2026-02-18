# VPS Integration Guide

Complete guide to integrating VPS agents with the OpenClaw Gateway.

## Overview

The VPS Integration Bridge connects Cloudflare Workers to local/remote VPS agents with:

- HTTP/HTTPS communication
- Session persistence across systems
- Automatic fallback chains
- Health tracking and smart routing
- Error classification and recovery

## Architecture

```
Cloudflare Worker
    ↓
Gateway (port 18789)
    ↓
VPS Integration Bridge
    ├─→ VPS Agent 1 (primary)
    ├─→ VPS Agent 2 (fallback)
    └─→ Session Store
```

## Quick Start

### 1. Setup the Bridge

```python
from vps_integration_bridge import VPSIntegrationBridge, VPSAgentConfig

# Create bridge
bridge = VPSIntegrationBridge()

# Register primary agent
bridge.register_agent(VPSAgentConfig(
    name="pm-agent",
    host="192.168.1.100",
    port=5000,
    protocol="http",
    timeout_seconds=30,
    max_retries=3,
    fallback_agents=["sonnet-agent"]  # Fallback chain
))

# Register fallback agent
bridge.register_agent(VPSAgentConfig(
    name="sonnet-agent",
    host="192.168.1.101",
    port=5001
))
```

### 2. Call VPS Agents

```python
# Synchronous call
result = bridge.call_agent(
    agent_name="pm-agent",
    prompt="Plan a 3-phase project",
    session_id="user-123",
    user_id="user-123"
)

if result.success:
    print(f"Response: {result.response}")
    print(f"Latency: {result.latency_ms}ms")
else:
    print(f"Error: {result.error}")
    print(f"Fallback chain used: {result.fallback_chain}")
```

```python
# Asynchronous call
result = await bridge.call_agent_async(
    agent_name="pm-agent",
    prompt="Plan a 3-phase project",
    session_id="user-123",
    user_id="user-123"
)
```

### 3. Enable in Gateway

```python
from fastapi import FastAPI
from gateway_vps_integration import setup_vps_routes

app = FastAPI()
bridge = setup_vps_routes(app)

# Now /api/vps/* endpoints are available
```

## API Endpoints

### Register Agent

```bash
POST /api/vps/register
Content-Type: application/json

{
  "name": "pm-agent",
  "host": "192.168.1.100",
  "port": 5000,
  "protocol": "http",
  "auth_token": "optional-token",
  "timeout_seconds": 30,
  "max_retries": 3,
  "fallback_agents": ["sonnet-agent"]
}

Response: {
  "status": "registered",
  "agent_name": "pm-agent",
  "url": "http://192.168.1.100:5000"
}
```

### Call Agent with Fallback

```bash
POST /api/vps/call
Content-Type: application/json

{
  "agent_name": "pm-agent",
  "prompt": "Plan a 3-phase project",
  "session_id": "sess-123",
  "user_id": "user-123",
  "metadata": {
    "context": "planning",
    "priority": "high"
  }
}

Response: {
  "success": true,
  "agent_name": "pm-agent",
  "response": "Here is your 3-phase project plan...",
  "error": null,
  "fallback_chain": ["pm-agent", "sonnet-agent"],
  "latency_ms": 1234.56,
  "retried": false,
  "retry_count": 0
}
```

### Get Agent Health

```bash
GET /api/vps/health/pm-agent

Response: {
  "agent_name": "pm-agent",
  "status": "healthy",
  "success_rate": 98.5,
  "total_requests": 200,
  "total_failures": 3,
  "consecutive_failures": 0
}
```

### Get Health Summary

```bash
GET /api/vps/health

Response: {
  "total_agents": 2,
  "healthy_agents": 2,
  "unhealthy_agents": 0,
  "degraded_agents": 0,
  "error_rate": 1.5
}
```

### List Agents

```bash
GET /api/vps/agents

Response: {
  "total": 2,
  "agents": [
    {
      "name": "pm-agent",
      "host": "192.168.1.100",
      "port": 5000,
      "protocol": "http",
      "url": "http://192.168.1.100:5000"
    },
    {
      "name": "sonnet-agent",
      "host": "192.168.1.101",
      "port": 5001,
      "protocol": "http",
      "url": "http://192.168.1.101:5001"
    }
  ]
}
```

### Get Session

```bash
GET /api/vps/sessions/sess-123

Response: {
  "session_id": "sess-123",
  "user_id": "user-123",
  "created_at": "2026-02-18T21:30:00",
  "last_activity": "2026-02-18T21:35:00",
  "messages": [
    {
      "timestamp": "2026-02-18T21:30:00",
      "role": "user",
      "content": "Plan a 3-phase project",
      "agent": ""
    },
    {
      "timestamp": "2026-02-18T21:30:05",
      "role": "assistant",
      "content": "Here is your 3-phase project plan...",
      "agent": "pm-agent"
    }
  ],
  "metadata": {
    "context": "planning"
  }
}
```

### Delete Session

```bash
DELETE /api/vps/sessions/sess-123

Response: 204 No Content
```

### Cleanup Old Sessions

```bash
POST /api/vps/sessions/cleanup?max_age_hours=24

Response: {
  "cleaned_up": 3,
  "remaining_sessions": 12
}
```

### Gateway Status

```bash
GET /api/vps/status

Response: {
  "status": "operational",
  "agents": 2,
  "healthy_agents": 2,
  "unhealthy_agents": 0,
  "sessions": 15
}
```

## Fallback Chain

When a VPS agent fails, the bridge automatically falls back to configured agents:

```python
# Primary agent fails → tries fallback
config = VPSAgentConfig(
    name="primary",
    host="primary.host",
    port=5000,
    fallback_agents=["fallback1", "fallback2"]
)
```

Result includes:

- `fallback_chain`: List of agents tried in order
- `retried`: Whether fallback was used
- `retry_count`: Number of failovers

## Error Handling

Errors are classified and tracked:

```python
from error_handler import ErrorType

# Types of errors detected:
# - TIMEOUT: Request timeout
# - RATE_LIMIT: API rate limit
# - CONNECTION: Network connection error
# - INVALID_RESPONSE: Bad response format
# - UNKNOWN: Unknown error

result = bridge.call_agent(...)

if not result.success:
    print(f"Error type: {result.error_type}")
    print(f"Error message: {result.error}")

    # Check agent health
    health = bridge.get_agent_health("pm-agent")
    print(f"Agent status: {health['status']}")
```

## Health Status States

- **healthy**: Agent responding correctly (100% success rate)
- **degraded**: Some failures detected (50-99% success rate)
- **unhealthy**: Multiple consecutive failures (0-49% success rate)
- **unreachable**: Unable to connect

Agents become unhealthy when:

- 3+ consecutive failures
- Success rate drops below 50%

Health resets when:

- Agent succeeds
- Manual reset via monitoring system

## Session Management

Sessions persist across calls and store:

- Message history with timestamps
- Agent responses with agent attribution
- User metadata
- Created/updated timestamps

Auto-cleanup:

```python
# Remove sessions older than 24 hours
bridge.cleanup_sessions(max_age_hours=24)

# Export for backup
bridge.export_sessions("/tmp/sessions.json")

# Import from backup
bridge.import_sessions("/tmp/sessions.json")
```

## Testing

Run all tests:

```bash
# Error handler tests (43 tests)
pytest /root/openclaw/test_error_handler.py -v

# VPS bridge tests (29 tests)
pytest /root/openclaw/test_vps_bridge.py -v

# Integration tests with curl
./test_vps_integration_curl.sh
```

## Configuration Example

```python
from vps_integration_bridge import VPSIntegrationBridge, VPSAgentConfig

# Initialize
bridge = VPSIntegrationBridge(default_timeout=30)

# Agent 1: PM Agent (primary)
bridge.register_agent(VPSAgentConfig(
    name="pm-agent",
    host="192.168.1.100",
    port=5000,
    protocol="http",
    auth_token="pm-token",
    timeout_seconds=30,
    max_retries=3,
    fallback_agents=["sonnet-agent"]
))

# Agent 2: Sonnet (fallback)
bridge.register_agent(VPSAgentConfig(
    name="sonnet-agent",
    host="192.168.1.101",
    port=5001,
    protocol="http",
    timeout_seconds=30,
    max_retries=2,
    fallback_agents=[]
))

# Agent 3: Secure HTTPS agent
bridge.register_agent(VPSAgentConfig(
    name="secure-agent",
    host="agents.example.com",
    port=443,
    protocol="https",
    auth_token="secure-token",
    timeout_seconds=60,
    max_retries=3
))
```

## Performance Characteristics

- **Call latency**: 50-200ms (excluding network to VPS)
- **Fallback overhead**: ~30-100ms per failed agent
- **Session lookup**: <1ms (in-memory)
- **Health check**: ~5ms per agent
- **Batch operations**: Linear scaling with agent count

## Monitoring

Key metrics to track:

```python
# Per agent
health = bridge.get_agent_health("pm-agent")
print(f"Success rate: {health['success_rate']}%")
print(f"Response time: {health['avg_response_time_ms']}ms")

# Aggregate
summary = bridge.get_health_summary()
print(f"System health: {summary['status']}")
print(f"Healthy agents: {summary['healthy_agents']}/{summary['total_agents']}")
```

## Deployment Checklist

- [ ] Configure VPS agent endpoints
- [ ] Register agents via `/api/vps/register`
- [ ] Test fallback chains
- [ ] Monitor health via `/api/vps/health`
- [ ] Setup session cleanup schedule
- [ ] Configure timeout values appropriately
- [ ] Enable auth tokens for secure agents
- [ ] Setup alerting for unhealthy agents
- [ ] Backup sessions regularly
- [ ] Monitor error rates and types

## Troubleshooting

### Agent Unreachable

```python
# Check agent registration
config = bridge.get_agent_config("pm-agent")
print(f"URL: {config.get_url()}")

# Check network connectivity
# Test from gateway machine:
# curl -v http://192.168.1.100:5000/health
```

### High Error Rates

```python
# Check health status
health = bridge.get_agent_health("pm-agent")
print(f"Status: {health['status']}")
print(f"Last failure: {health['last_error']}")

# Check network latency
# Monitor timeout_seconds vs actual response times
```

### Sessions Not Persisting

```python
# Verify session is registered
session = bridge.get_session("sess-123")
print(f"Session exists: {session is not None}")

# Check session has messages
print(f"Messages: {len(session.messages) if session else 0}")
```

## Next Steps

1. Deploy to Northflank
2. Test with real VPS agent endpoints
3. Setup monitoring dashboard
4. Configure fallback routing policies
5. Integrate with Barber CRM system
