# Client Authentication & Billing System Integration Guide

## Overview

The new client authentication and billing system (`client_auth.py`) provides:

1. **API Key Management** — Per-client unique keys (format: `oc_live_<32 hex>`)
2. **Plan-Based Limits** — Free (5), Starter (50), Pro (200), Enterprise (unlimited) jobs/month
3. **Usage Tracking** — Credits deducted per job, billing cycles reset monthly
4. **Stripe Integration** — Stubbed and ready for live keys
5. **Admin Endpoints** — Create clients, manage credits, deactivate accounts

## Files Added

```
/root/openclaw/client_auth.py           — 600+ LOC, production-quality
/root/openclaw/test_client_auth.py      — 900+ LOC, 50+ unit tests
/root/openclaw/CLIENT_AUTH_INTEGRATION.md — This file
```

## Step 1: Import in gateway.py

Add this import near the top of `gateway.py` (after other imports):

```python
# Client authentication & billing
from client_auth import (
    router as client_auth_router,
    authenticate_client,
    can_submit_job,
    deduct_job_credit,
    log_client_cost,
    get_client_by_api_key,
)
```

## Step 2: Include Router in FastAPI App

After creating the FastAPI app instance in `gateway.py`, add:

```python
# Include client auth router
app.include_router(client_auth_router)
```

Typical location (after other routers):

```python
# Include routers
app.include_router(intake_router)
app.include_router(audit_router)
app.include_router(client_auth_router)  # Add this line
```

## Step 3: Protect /api/intake Endpoint

Modify the `POST /api/intake` endpoint in `intake_routes.py` to check client auth:

**Before:**

```python
@router.post("/api/intake", response_model=IntakeResponse)
async def submit_intake(req: IntakeRequest) -> IntakeResponse:
    # Existing code...
```

**After:**

```python
@router.post("/api/intake", response_model=IntakeResponse)
async def submit_intake(
    req: IntakeRequest,
    x_client_key: Optional[str] = Header(None, alias="X-Client-Key"),
) -> IntakeResponse:
    # Check client auth (optional for backward compatibility, required for new clients)
    if x_client_key:
        client = get_client_by_api_key(x_client_key)
        if not client:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Check job limit
        allowed, reason = can_submit_job(client)
        if not allowed:
            raise HTTPException(status_code=403, detail=reason)

    # Existing intake logic...
    job = { ... }

    # Deduct credit after job creation (only if client provided key)
    if x_client_key:
        deduct_job_credit(client["client_id"])

    return IntakeResponse(...)
```

## Step 4: Update Auth Middleware

The existing auth middleware in `gateway.py` (around line 387) should exempt client endpoints:

**Update the auth middleware to:**

```python
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Webhook & Dashboard Exemptions
    if request.url.path.startswith("/telegram/") or \
       request.url.path.startswith("/slack/") or \
       request.url.path == "/health" or \
       request.url.path == "/metrics" or \
       request.url.path.startswith("/dashboard"):
        return await call_next(request)

    # Client billing endpoints (public)
    if request.url.path == "/api/billing/plans" or \
       request.url.path == "/api/billing/webhook":
        return await call_next(request)

    # Protected endpoints — require X-Auth-Token
    token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    if not token or token != os.getenv("OPENCLAW_ADMIN_TOKEN", "admin-token-secret"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    return await call_next(request)
```

## Step 5: Set Environment Variables

Add these to your `.env` file or deployment config:

```bash
# Required
OPENCLAW_ADMIN_TOKEN=your-secret-admin-token

# Optional — Stripe keys (add when you enable live Stripe)
STRIPE_PUBLIC_KEY=pk_test_xxxx
STRIPE_SECRET_KEY=sk_test_xxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxx
```

## Step 6: Test the Integration

Run the test suite:

```bash
cd /root/openclaw
pytest test_client_auth.py -v
```

Expected output:

```
test_client_auth.py::test_api_key_generation PASSED
test_client_auth.py::test_authenticate_valid_key PASSED
test_client_auth.py::test_job_limit_free_plan PASSED
test_client_auth.py::test_list_billing_plans PASSED
test_client_auth.py::test_create_client_success PASSED
...
50 passed in 2.15s
```

## Usage Examples

### 1. Admin: Create a New Client

```bash
curl -X POST http://localhost:18789/api/admin/clients \
  -H "X-Auth-Token: admin-token-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Acme Corp",
    "email": "api@acmecorp.com",
    "plan": "pro"
  }'
```

Response:

```json
{
  "client_id": "uuid-here",
  "name": "Acme Corp",
  "email": "api@acmecorp.com",
  "api_key": "oc_live_abc123def456...",
  "plan": "pro",
  "credits_remaining": 200,
  "total_spent": 0.0,
  "created_at": "2026-02-19T...",
  "active": true
}
```

### 2. Client: Check Billing Usage

```bash
curl -H "X-Client-Key: oc_live_abc123def456..." \
  http://localhost:18789/api/billing/usage
```

Response:

```json
{
  "client_id": "uuid-here",
  "plan": "pro",
  "credits_remaining": 199,
  "credits_limit": 200,
  "billing_cycle_start": "2026-02-19T...",
  "billing_cycle_end": "2026-03-21T...",
  "days_remaining": 29,
  "usage_pct": 0.5,
  "total_spent": 0.0,
  "status": "active"
}
```

### 3. Client: Submit a Job

```bash
curl -X POST http://localhost:18789/api/intake \
  -H "X-Client-Key: oc_live_abc123def456..." \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Feature Build",
    "description": "Add user authentication",
    "task_type": "feature_build",
    "priority": "P1"
  }'
```

### 4. Admin: List All Clients

```bash
curl -H "X-Auth-Token: admin-token-secret" \
  http://localhost:18789/api/admin/clients?status=active
```

### 5. Admin: Add Credits (Promo/Adjustment)

```bash
curl -X PUT http://localhost:18789/api/admin/clients/uuid-here/credits \
  -H "X-Auth-Token: admin-token-secret" \
  -H "Content-Type: application/json" \
  -d '{
    "credits": 50,
    "reason": "promotional credit for Q1"
  }'
```

### 6. Client: View Available Plans

```bash
curl http://localhost:18789/api/billing/plans
```

Response:

```json
{
  "free": {
    "plan_id": "free",
    "name": "Free",
    "price": 0.0,
    "currency": "USD",
    "billing_period": "monthly",
    "job_limit": 5,
    "features": ["Basic job submission", "24h history", "Email support"]
  },
  "starter": {...},
  "pro": {...},
  "enterprise": {...}
}
```

## Database Schema

Clients stored in `/tmp/openclaw_clients.json`:

```json
{
  "client-uuid-123": {
    "client_id": "client-uuid-123",
    "name": "Acme Corp",
    "email": "api@acmecorp.com",
    "api_key": "oc_live_abcdef123456...",
    "plan": "pro",
    "credits_remaining": 198,
    "total_spent": 5.5,
    "created_at": "2026-02-19T10:30:00+00:00",
    "updated_at": "2026-02-19T11:45:00+00:00",
    "active": true,
    "stripe_customer_id": null,
    "stripe_subscription_id": null,
    "billing_cycle_start": "2026-02-19T...",
    "billing_cycle_end": "2026-03-21T...",
    "metadata": {
      "credit_adjustments": [
        {
          "timestamp": "2026-02-19T11:00:00+00:00",
          "amount": 25,
          "reason": "promotional credit"
        }
      ],
      "cost_log": [
        {
          "timestamp": "2026-02-19T11:30:00+00:00",
          "cost": 5.5,
          "job_id": "job-uuid-456"
        }
      ]
    }
  }
}
```

## Plans & Limits

| Plan       | Price  | Jobs/Month | Features                                                     |
| ---------- | ------ | ---------- | ------------------------------------------------------------ |
| Free       | $0     | 5          | Basic submission, 24h history, email support                 |
| Starter    | $49    | 50         | Priority support, API access, 30-day history                 |
| Pro        | $199   | 200        | 24/7 support, advanced analytics, webhooks, 90-day history   |
| Enterprise | Custom | Unlimited  | Dedicated support, SLA, custom integrations, forever history |

## Billing Cycle

- **Duration:** 30 days from creation date
- **Credits Reset:** Automatically when billing cycle ends
- **Enterprise Plan:** No credit deduction (unlimited jobs)
- **Free Tier:** 5 jobs per cycle, free forever

## Stripe Integration (Ready to Activate)

The system includes stubbed Stripe endpoints ready for production:

1. **POST /api/billing/checkout** — Creates checkout session (currently returns mock URL)
2. **POST /api/billing/webhook** — Handles Stripe webhooks (logs events)

To enable live Stripe:

1. Get Stripe API keys from https://dashboard.stripe.com/
2. Set environment variables: `STRIPE_SECRET_KEY`, `STRIPE_PUBLIC_KEY`, `STRIPE_WEBHOOK_SECRET`
3. Uncomment the Stripe API calls in `client_auth.py` (search for `# STUB:`)
4. Deploy webhook handler URL to Stripe dashboard

## Security Notes

- API keys are stored in plain text in JSON (use encrypted storage for production)
- Admin token is configurable via env var (`OPENCLAW_ADMIN_TOKEN`)
- Stripe webhooks should verify signature (stubbed for now)
- API keys prefixed with `oc_live_` for easy identification
- No API keys returned in list endpoints (security best practice)

## Monitoring & Logging

All operations logged to `logging.getLogger("openclaw_billing")`:

```
2026-02-19 11:30:45 - openclaw_billing - INFO - Created client uuid-123 (Acme Corp) on pro plan
2026-02-19 11:31:00 - openclaw_billing - INFO - Deducted credit for uuid-123: job submission
2026-02-19 11:31:05 - openclaw_billing - INFO - Logged $5.50 cost for client uuid-123
2026-02-19 11:32:00 - openclaw_billing - INFO - Reset monthly credits for uuid-123: 200 jobs
```

## Troubleshooting

### Issue: "Invalid or inactive API key"

- Verify the key with: `curl http://localhost:18789/api/admin/clients -H "X-Auth-Token: ..."`
- Check if client is `active: true`
- Ensure key format: `oc_live_<32-hex-chars>`

### Issue: "Monthly job limit reached"

- Check remaining credits: `curl -H "X-Client-Key: ..." http://localhost:18789/api/billing/usage`
- Wait for billing cycle to reset (or admin adds credits)
- Check `billing_cycle_end` date

### Issue: Stripe webhook not working

- Current implementation logs events (stubbed)
- Activate real Stripe by setting `STRIPE_SECRET_KEY` env var
- Configure webhook URL in Stripe dashboard

## Future Enhancements

1. **Encrypted Storage** — Use KMS/Vault for API keys
2. **Audit Logging** — Detailed audit trail for compliance
3. **Usage Quotas** — Per-second rate limiting per client
4. **Webhook Events** — Notify clients of cost thresholds, billing events
5. **Metered Billing** — Charge by API tokens consumed (beyond credits)
6. **Team Accounts** — Multiple users per client organization
7. **Custom Branding** — White-label client portals

## Support

For issues or questions:

- Review test suite: `test_client_auth.py`
- Check logs: `grep openclaw_billing /tmp/openclaw_*.log`
- Monitor data: `cat /tmp/openclaw_clients.json | jq .`
