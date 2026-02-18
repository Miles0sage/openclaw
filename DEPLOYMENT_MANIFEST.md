# VPS Integration & Error Handling - Deployment Manifest

**Created:** 2026-02-18  
**Status:** ✅ PRODUCTION READY  
**Tests:** 72/72 PASSING

## File Manifest

### Production Code

```
/root/openclaw/
├── error_handler.py (32 KB, 902 LOC)
│   └── Core error handling framework
│       - Exponential backoff retry
│       - Timeout protection
│       - Error classification
│       - Agent health tracking
│       - Global error tracking
│
├── vps_integration_bridge.py (18 KB, 497 LOC)
│   └── VPS integration bridge
│       - HTTP/HTTPS communication
│       - Session persistence
│       - Fallback chains
│       - Health monitoring
│       - Async/await support
│
└── gateway_vps_integration.py (9.3 KB, 281 LOC)
    └── FastAPI routes
        - 9 REST API endpoints
        - Request/response models
        - Session management
        - Health tracking
```

### Test Code

```
/root/openclaw/
├── test_error_handler.py (23 KB, 577 LOC)
│   └── 43 comprehensive tests
│       Status: ✅ 43/43 PASSING
│
└── test_vps_bridge.py (14 KB, 434 LOC)
    └── 29 comprehensive tests
        Status: ✅ 29/29 PASSING
```

### Testing & Documentation

```
/root/openclaw/
├── test_vps_integration_curl.sh (4.2 KB, 140 LOC)
│   └── End-to-end curl testing script
│
├── VPS_INTEGRATION_GUIDE.md (9.6 KB, 488 LOC)
│   └── Complete implementation guide
│       - Architecture
│       - Quick start
│       - API reference
│       - Troubleshooting
│
├── VPS_INTEGRATION_QUICK_REFERENCE.md (5.6 KB, 248 LOC)
│   └── Quick reference
│       - Feature checklist
│       - Configuration examples
│       - Performance metrics
│       - Deployment steps
│
├── BUILD_STATUS_REPORT.md (7.6 KB, 282 LOC)
│   └── Detailed build report
│       - Test results
│       - Features implemented
│       - Performance characteristics
│
└── DEPLOYMENT_MANIFEST.md (This file)
    └── File listing and deployment instructions
```

## File Sizes Summary

| Category      | Files  | Size         | LOC       |
| ------------- | ------ | ------------ | --------- |
| Production    | 3      | 59.3 KB      | 1,680     |
| Tests         | 2      | 37 KB        | 1,011     |
| Documentation | 5      | 35.4 KB      | 1,206     |
| **TOTAL**     | **10** | **131.7 KB** | **3,897** |

## Checksums & Verification

To verify all files are present and correct:

```bash
cd /root/openclaw

# Count lines
wc -l error_handler.py vps_integration_bridge.py gateway_vps_integration.py \
    test_error_handler.py test_vps_bridge.py

# List all files
ls -lh error_handler.py vps_integration_bridge.py gateway_vps_integration.py \
       test_error_handler.py test_vps_bridge.py test_vps_integration_curl.sh \
       VPS_INTEGRATION_GUIDE.md VPS_INTEGRATION_QUICK_REFERENCE.md \
       BUILD_STATUS_REPORT.md DEPLOYMENT_MANIFEST.md

# Run tests
pytest test_error_handler.py test_vps_bridge.py -v
```

## Deployment Instructions

### Step 1: Copy Production Files

```bash
# Copy to your deployment directory
cp /root/openclaw/error_handler.py /path/to/gateway/
cp /root/openclaw/vps_integration_bridge.py /path/to/gateway/
cp /root/openclaw/gateway_vps_integration.py /path/to/gateway/
```

### Step 2: Update Gateway Code

In your main gateway file (e.g., `gateway.py`):

```python
from fastapi import FastAPI
from gateway_vps_integration import setup_vps_routes

app = FastAPI(
    title="OpenClaw Gateway",
    description="Multi-channel AI agent platform"
)

# Setup VPS integration
bridge = setup_vps_routes(app)

# Register agents at startup
from vps_integration_bridge import VPSAgentConfig

bridge.register_agent(VPSAgentConfig(
    name="pm-agent",
    host="192.168.1.100",
    port=5000,
    fallback_agents=["sonnet-agent"]
))

# Your existing routes...
```

### Step 3: Install Dependencies

```bash
pip install httpx fastapi pydantic
```

### Step 4: Test Integration

```bash
# Check if bridge is working
curl http://localhost:18789/api/vps/health

# Register an agent
curl -X POST http://localhost:18789/api/vps/register \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-agent",
    "host": "localhost",
    "port": 5000
  }'

# Call agent
curl -X POST http://localhost:18789/api/vps/call \
  -H "Content-Type: application/json" \
  -d '{
    "agent_name": "test-agent",
    "prompt": "Hello",
    "session_id": "test-1"
  }'
```

## Pre-Deployment Checklist

Before deploying to production:

- [ ] Copy all production files to deployment directory
- [ ] Update gateway.py with VPS routes setup
- [ ] Install required dependencies (httpx, pydantic)
- [ ] Test locally with `pytest test_*.py -v`
- [ ] Configure VPS agent endpoints
- [ ] Test API endpoints with curl
- [ ] Verify error handling works
- [ ] Check session persistence
- [ ] Test fallback chains
- [ ] Monitor health status
- [ ] Setup alerting for unhealthy agents
- [ ] Document any custom configuration

## Runtime Requirements

- **Python:** 3.10+
- **Dependencies:**
  - httpx (async HTTP client)
  - fastapi (web framework)
  - pydantic (request validation)
- **System:**
  - Memory: ~100MB per 100 sessions
  - CPU: Minimal (mostly I/O bound)
  - Network: Connectivity to VPS agents

## Configuration Variables

Key environment/config variables to set:

```python
# VPS Agent Configuration
VPS_AGENTS = [
    {
        "name": "pm-agent",
        "host": "192.168.1.100",
        "port": 5000,
        "timeout_seconds": 30,
        "max_retries": 3,
        "fallback_agents": ["sonnet-agent"]
    },
    {
        "name": "sonnet-agent",
        "host": "192.168.1.101",
        "port": 5001,
        "timeout_seconds": 30
    }
]

# Gateway Configuration
GATEWAY_HOST = "0.0.0.0"
GATEWAY_PORT = 18789
GATEWAY_TOKEN = "moltbot-secure-token-2026"

# Session Configuration
SESSION_CLEANUP_HOURS = 24
SESSION_EXPORT_PATH = "/tmp/sessions.json"
```

## API Endpoints Reference

After deployment, these endpoints are available:

| Method | Endpoint                  | Purpose        |
| ------ | ------------------------- | -------------- |
| POST   | /api/vps/call             | Call VPS agent |
| POST   | /api/vps/register         | Register agent |
| GET    | /api/vps/agents           | List agents    |
| GET    | /api/vps/health           | Overall health |
| GET    | /api/vps/health/{name}    | Agent health   |
| GET    | /api/vps/sessions/{id}    | Get session    |
| DELETE | /api/vps/sessions/{id}    | Delete session |
| POST   | /api/vps/sessions/cleanup | Cleanup old    |
| GET    | /api/vps/status           | Gateway status |

## Monitoring & Alerting

Key metrics to monitor:

```python
# Check overall health
GET /api/vps/health
→ Look for: unhealthy_agents count

# Check agent health
GET /api/vps/health/pm-agent
→ Watch: success_rate (should be >95%)

# Monitor sessions
GET /api/vps/sessions/stats
→ Track: total sessions, memory usage

# Gateway status
GET /api/vps/status
→ Alert on: status != "operational"
```

## Rollback Plan

If deployment has issues:

1. **Remove VPS routes** from gateway.py
2. **Stop using VPS endpoints** - revert to direct agent calls
3. **Keep error_handler.py** - useful for other error handling
4. **Check logs** - use logs to diagnose issues
5. **Restart gateway** - ensure clean state

## Logs & Debugging

Enable logging:

```python
import logging

logging.basicConfig(level=logging.DEBUG)

# Log VPS integration
vps_logger = logging.getLogger("vps_integration_bridge")
vps_logger.setLevel(logging.DEBUG)

# Log error handling
error_logger = logging.getLogger("openclaw_errors")
error_logger.setLevel(logging.DEBUG)
```

## Support & Questions

Refer to:

- **VPS_INTEGRATION_GUIDE.md** - Complete guide
- **VPS_INTEGRATION_QUICK_REFERENCE.md** - Quick reference
- **Test files** - Self-documenting tests
- **Inline comments** - Code comments explain logic

## Version Information

- **Release Date:** 2026-02-18
- **Python Version:** 3.13.5 (tested)
- **Test Framework:** pytest 9.0.2
- **Async Framework:** asyncio
- **HTTP Client:** httpx

## Success Criteria

Your deployment is successful when:

✅ All 72 tests pass  
✅ POST /api/vps/call returns 200  
✅ GET /api/vps/health shows healthy agents  
✅ Sessions persist across calls  
✅ Fallback chains work when primary fails  
✅ Error handling recovers gracefully  
✅ No memory leaks with long-running sessions

---

**Status:** Ready for deployment. All tests passing. Documentation complete.
