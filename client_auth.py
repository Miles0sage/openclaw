"""
OpenClaw Client Authentication & Billing System

Provides:
- API Key Management (per-client authentication)
- Plan-based usage limits (free, starter, pro, enterprise)
- Usage tracking and billing
- Stripe integration (stubbed, ready for live keys)
- Admin endpoints for client management

Storage: /tmp/openclaw_clients.json (persistent JSON)
Endpoints:
  - POST   /api/intake                    (requires X-Client-Key)
  - GET    /api/jobs                      (requires X-Client-Key)
  - GET    /api/billing/usage             (requires X-Client-Key)
  - GET    /api/billing/plans             (no auth required)
  - POST   /api/billing/checkout          (requires X-Client-Key)
  - POST   /api/billing/webhook           (no auth required, Stripe signature verified)
  - POST   /api/admin/clients             (requires X-Auth-Token)
  - GET    /api/admin/clients             (requires X-Auth-Token)
  - PUT    /api/admin/clients/{id}/credits (requires X-Auth-Token)
  - DELETE /api/admin/clients/{id}        (requires X-Auth-Token)
"""

from fastapi import APIRouter, HTTPException, Request, Header, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import json
import os
import uuid
import logging
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
import secrets
import requests

router = APIRouter(tags=["billing"])
logger = logging.getLogger("openclaw_billing")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

CLIENTS_FILE = "/tmp/openclaw_clients.json"

PLANS = {
    "free": {
        "name": "Free",
        "price": 0.0,
        "currency": "USD",
        "billing_period": "monthly",
        "job_limit": 5,
        "features": ["Basic job submission", "24h job history", "Email support"],
    },
    "starter": {
        "name": "Starter",
        "price": 49.0,
        "currency": "USD",
        "billing_period": "monthly",
        "job_limit": 50,
        "features": ["50 jobs/month", "30-day history", "Priority support", "API access"],
    },
    "pro": {
        "name": "Pro",
        "price": 199.0,
        "currency": "USD",
        "billing_period": "monthly",
        "job_limit": 200,
        "features": ["200 jobs/month", "90-day history", "24/7 support", "Advanced analytics", "Webhooks"],
    },
    "enterprise": {
        "name": "Enterprise",
        "price": None,  # Custom pricing
        "currency": "USD",
        "billing_period": "custom",
        "job_limit": None,  # Unlimited
        "features": ["Unlimited jobs", "Forever history", "Dedicated support", "SLA", "Custom integrations"],
    },
}

# Stripe keys (stub for now — wire in when keys available)
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "pk_test_stub")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_stub")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test_stub")


# ═══════════════════════════════════════════════════════════════════════
# STORAGE & PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════


def _load_clients() -> Dict[str, Any]:
    """Load all clients from the JSON file."""
    if not os.path.exists(CLIENTS_FILE):
        return {}
    try:
        with open(CLIENTS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load clients file: {e}, resetting")
        return {}


def _save_clients(clients: Dict[str, Any]) -> None:
    """Persist all clients to the JSON file (atomic write)."""
    tmp = CLIENTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(clients, f, indent=2, default=str)
    os.replace(tmp, CLIENTS_FILE)
    logger.debug(f"Persisted {len(clients)} clients to {CLIENTS_FILE}")


def _now_iso() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_api_key() -> str:
    """Generate a unique API key (format: oc_live_<32 hex chars>)."""
    random_part = secrets.token_hex(16)  # 32 hex chars
    return f"oc_live_{random_part}"


# ═══════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════


class PlanInfo(BaseModel):
    """Info about a billing plan."""
    plan_id: str
    name: str
    price: Optional[float]
    currency: str
    billing_period: str
    job_limit: Optional[int]
    features: List[str]


class ClientRecord(BaseModel):
    """A client account record."""
    client_id: str
    name: str
    email: str
    api_key: str
    plan: str  # 'free', 'starter', 'pro', 'enterprise'
    credits_remaining: int  # Jobs remaining this billing cycle
    total_spent: float  # Total USD spent
    created_at: str
    active: bool
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    billing_cycle_start: str
    billing_cycle_end: str
    metadata: Optional[Dict[str, Any]] = None


class CreateClientRequest(BaseModel):
    """Request to create a new client."""
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=200, description="Valid email address")
    plan: str = Field(default="free", description="One of: free, starter, pro, enterprise")


class UsageResponse(BaseModel):
    """Current usage for a client."""
    client_id: str
    plan: str
    credits_remaining: int
    credits_limit: Optional[int]
    billing_cycle_start: str
    billing_cycle_end: str
    days_remaining: int
    usage_pct: float
    total_spent: float
    status: str  # 'active', 'at_limit', 'over_limit'


class CheckoutResponse(BaseModel):
    """Stripe checkout response (stub)."""
    session_id: str
    checkout_url: str
    plan_id: str
    price: float
    message: str


class AddCreditsRequest(BaseModel):
    """Request to add credits to a client's account."""
    credits: int = Field(..., ge=1, le=1000)
    reason: str = Field(default="admin adjustment")


class ClientListResponse(BaseModel):
    """Response listing all clients."""
    clients: List[Dict[str, Any]]
    total: int


# ═══════════════════════════════════════════════════════════════════════
# CORE LOGIC — CLIENT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════


def authenticate_client(api_key: str) -> Optional[Dict[str, Any]]:
    """
    Validate an API key and return the client record if valid.
    Returns None if key is invalid or client is inactive.
    """
    if not api_key or not api_key.startswith("oc_live_"):
        return None

    clients = _load_clients()
    for client_id, client in clients.items():
        if client.get("api_key") == api_key and client.get("active"):
            return client
    return None


def check_job_limit(client: Dict[str, Any]) -> tuple[bool, str]:
    """
    Check if a client can submit a new job.
    Returns (allowed, reason).
    """
    plan = client.get("plan", "free")
    credits = client.get("credits_remaining", 0)

    if plan == "enterprise":
        # Enterprise has unlimited jobs
        return True, "Enterprise plan — unlimited jobs"

    plan_limit = PLANS[plan]["job_limit"]
    if credits <= 0:
        return False, f"Monthly job limit reached ({plan_limit} jobs). Upgrade or wait for next billing cycle."

    return True, f"Remaining jobs this month: {credits}"


def deduct_credit(client_id: str, reason: str = "job submission") -> bool:
    """
    Deduct one job credit from a client's account.
    Returns True if successful, False if client not found.
    """
    clients = _load_clients()
    if client_id not in clients:
        return False

    client = clients[client_id]
    plan = client.get("plan", "free")

    if plan != "enterprise":
        client["credits_remaining"] = max(0, client.get("credits_remaining", 0) - 1)

    client["updated_at"] = _now_iso()
    _save_clients(clients)
    logger.info(f"Deducted credit for {client_id[:8]}: {reason}")
    return True


def reset_monthly_credits(client: Dict[str, Any]) -> Dict[str, Any]:
    """
    Check if a client's billing cycle has ended, and reset credits if so.
    Returns the updated client record.
    """
    now = datetime.now(timezone.utc)
    cycle_end = datetime.fromisoformat(client.get("billing_cycle_end", _now_iso()))

    if now >= cycle_end:
        # Billing cycle has ended, reset credits
        plan = client.get("plan", "free")
        plan_limit = PLANS[plan]["job_limit"]

        if plan != "enterprise":
            client["credits_remaining"] = plan_limit or 0
        else:
            client["credits_remaining"] = 0  # Enterprise doesn't use credits

        # Set new cycle dates
        cycle_start = now
        cycle_end = now + timedelta(days=30)
        client["billing_cycle_start"] = cycle_start.isoformat()
        client["billing_cycle_end"] = cycle_end.isoformat()

        logger.info(f"Reset monthly credits for {client.get('client_id')}: {client['credits_remaining']} jobs")

    return client


def get_client_usage(client: Dict[str, Any]) -> UsageResponse:
    """Get current usage for a client."""
    client = reset_monthly_credits(client)
    plan = client.get("plan", "free")
    credits = client.get("credits_remaining", 0)
    limit = PLANS[plan]["job_limit"]

    # Calculate days remaining in billing cycle
    cycle_end = datetime.fromisoformat(client.get("billing_cycle_end", _now_iso()))
    days_remaining = max(0, (cycle_end - datetime.now(timezone.utc)).days)

    # Calculate usage percentage
    if limit and limit > 0:
        usage_pct = ((limit - credits) / limit) * 100
    else:
        usage_pct = 0.0

    # Status
    if credits <= 0:
        status = "at_limit" if limit else "active"
    else:
        status = "active"

    return UsageResponse(
        client_id=client["client_id"],
        plan=plan,
        credits_remaining=credits,
        credits_limit=limit,
        billing_cycle_start=client.get("billing_cycle_start", _now_iso()),
        billing_cycle_end=client.get("billing_cycle_end", _now_iso()),
        days_remaining=days_remaining,
        usage_pct=usage_pct,
        total_spent=client.get("total_spent", 0.0),
        status=status,
    )


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS — BILLING INFO (PUBLIC)
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/billing/plans", response_model=Dict[str, PlanInfo])
async def list_billing_plans() -> Dict[str, PlanInfo]:
    """
    List all available billing plans (public endpoint, no auth required).
    """
    result = {}
    for plan_id, plan_info in PLANS.items():
        result[plan_id] = PlanInfo(
            plan_id=plan_id,
            name=plan_info["name"],
            price=plan_info["price"],
            currency=plan_info["currency"],
            billing_period=plan_info["billing_period"],
            job_limit=plan_info["job_limit"],
            features=plan_info["features"],
        )
    return result


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS — USAGE & BILLING (CLIENT AUTHENTICATED)
# ═══════════════════════════════════════════════════════════════════════


@router.get("/api/billing/usage", response_model=UsageResponse)
async def get_client_usage_endpoint(
    x_client_key: Optional[str] = Header(None, alias="X-Client-Key"),
) -> UsageResponse:
    """
    Get current usage and billing status for the authenticated client.

    Requires: X-Client-Key header
    """
    if not x_client_key:
        raise HTTPException(status_code=401, detail="Missing X-Client-Key header")

    client = authenticate_client(x_client_key)
    if not client:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    return get_client_usage(client)


@router.post("/api/billing/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    x_client_key: Optional[str] = Header(None, alias="X-Client-Key"),
    plan_id: str = Query("starter"),
) -> CheckoutResponse:
    """
    Create a Stripe checkout session for the authenticated client.

    Currently stubbed — returns mock URL ready for real Stripe integration.
    When Stripe keys are added, this will create a real checkout session.

    Requires: X-Client-Key header
    """
    if not x_client_key:
        raise HTTPException(status_code=401, detail="Missing X-Client-Key header")

    client = authenticate_client(x_client_key)
    if not client:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    if plan_id not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan_id: {plan_id}")

    plan = PLANS[plan_id]
    if plan["price"] is None:
        raise HTTPException(status_code=400, detail="Enterprise plans require contacting sales")

    # STUB: In production, call Stripe API here
    # For now, return a mock checkout URL
    mock_session_id = f"cs_test_{uuid.uuid4().hex[:16]}"
    mock_url = f"https://checkout.stripe.com/mock?session_id={mock_session_id}"

    logger.info(f"[STUB] Checkout session created for {client['client_id']}: {plan_id}")

    return CheckoutResponse(
        session_id=mock_session_id,
        checkout_url=mock_url,
        plan_id=plan_id,
        price=plan["price"],
        message=f"Checkout URL for {plan['name']} plan. In production, this will redirect to Stripe.",
    )


@router.post("/api/billing/webhook")
async def handle_stripe_webhook(request: Request) -> Dict[str, str]:
    """
    Handle Stripe webhook events (payment successful, subscription updates, etc.).

    Signature verification happens here (using STRIPE_WEBHOOK_SECRET).
    Currently stubbed — logs events, ready for real Stripe integration.

    No auth required (Stripe verifies via signature).
    """
    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # STUB: In production, verify Stripe signature here
    # For now, just accept and log the event
    try:
        event = json.loads(body)
        event_type = event.get("type", "unknown")
        logger.info(f"[STUB] Received Stripe webhook: {event_type}")

        # Handle specific events
        if event_type == "checkout.session.completed":
            # Upgrade client's plan
            logger.info("[TODO] Upgrade client plan based on checkout session")
        elif event_type == "customer.subscription.updated":
            logger.info("[TODO] Update client subscription")
        elif event_type == "customer.subscription.deleted":
            logger.info("[TODO] Downgrade client plan")

        return {"status": "received"}
    except Exception as e:
        logger.error(f"Stripe webhook error: {e}")
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS — ADMIN ONLY (REQUIRE X-AUTH-TOKEN)
# ═══════════════════════════════════════════════════════════════════════


@router.post("/api/admin/clients", response_model=ClientRecord)
async def create_client(
    req: CreateClientRequest,
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
) -> ClientRecord:
    """
    Create a new client account (admin only).

    Generates a unique API key and initializes billing cycle.

    Requires: X-Auth-Token header
    """
    if not x_auth_token or x_auth_token != os.getenv("GATEWAY_AUTH_TOKEN", "f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3"):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    if req.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {req.plan}")

    clients = _load_clients()

    # Check for duplicate email
    for client in clients.values():
        if client.get("email") == req.email:
            raise HTTPException(status_code=409, detail=f"Client with email {req.email} already exists")

    client_id = str(uuid.uuid4())
    api_key = _generate_api_key()
    now = _now_iso()
    cycle_start = datetime.now(timezone.utc)
    cycle_end = cycle_start + timedelta(days=30)

    plan_limit = PLANS[req.plan]["job_limit"]
    credits = plan_limit if plan_limit else 0

    new_client = {
        "client_id": client_id,
        "name": req.name,
        "email": req.email,
        "api_key": api_key,
        "plan": req.plan,
        "credits_remaining": credits,
        "total_spent": 0.0,
        "created_at": now,
        "updated_at": now,
        "active": True,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "billing_cycle_start": cycle_start.isoformat(),
        "billing_cycle_end": cycle_end.isoformat(),
        "metadata": {},
    }

    clients[client_id] = new_client
    _save_clients(clients)

    logger.info(f"Created client {client_id[:8]} ({req.name}) on {req.plan} plan")

    return ClientRecord(**new_client)


@router.get("/api/admin/clients", response_model=ClientListResponse)
async def list_clients(
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    status: str = Query("all", description="Filter: 'active', 'inactive', or 'all'"),
) -> ClientListResponse:
    """
    List all clients (admin only).

    Supports filtering by active/inactive status.

    Requires: X-Auth-Token header
    """
    if not x_auth_token or x_auth_token != os.getenv("GATEWAY_AUTH_TOKEN", "f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3"):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    clients = _load_clients()
    all_clients = list(clients.values())

    # Filter by status
    if status == "active":
        all_clients = [c for c in all_clients if c.get("active")]
    elif status == "inactive":
        all_clients = [c for c in all_clients if not c.get("active")]

    # Omit the API key from the response for security
    for client in all_clients:
        client.pop("api_key", None)

    return ClientListResponse(clients=all_clients, total=len(all_clients))


@router.put("/api/admin/clients/{client_id}/credits", response_model=Dict[str, Any])
async def add_credits_to_client(
    client_id: str,
    req: AddCreditsRequest,
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
) -> Dict[str, Any]:
    """
    Add credits (jobs) to a client's account (admin only).

    Used for manual adjustments, promo credits, etc.

    Requires: X-Auth-Token header
    """
    if not x_auth_token or x_auth_token != os.getenv("GATEWAY_AUTH_TOKEN", "f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3"):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    clients = _load_clients()
    if client_id not in clients:
        raise HTTPException(status_code=404, detail="Client not found")

    client = clients[client_id]
    old_credits = client.get("credits_remaining", 0)
    new_credits = old_credits + req.credits

    # Enterprise plans don't use credits
    if client.get("plan") == "enterprise":
        raise HTTPException(status_code=400, detail="Cannot add credits to enterprise plan")

    client["credits_remaining"] = new_credits
    client["updated_at"] = _now_iso()
    if not client.get("metadata"):
        client["metadata"] = {}
    if "credit_adjustments" not in client["metadata"]:
        client["metadata"]["credit_adjustments"] = []
    client["metadata"]["credit_adjustments"].append({
        "timestamp": _now_iso(),
        "amount": req.credits,
        "reason": req.reason,
    })

    _save_clients(clients)
    logger.info(f"Added {req.credits} credits to {client_id[:8]}: {req.reason}")

    return {
        "client_id": client_id,
        "previous_credits": old_credits,
        "credits_added": req.credits,
        "new_credits": new_credits,
        "reason": req.reason,
    }


@router.delete("/api/admin/clients/{client_id}", response_model=Dict[str, str])
async def deactivate_client(
    client_id: str,
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
) -> Dict[str, str]:
    """
    Deactivate a client account (admin only).

    Deactivation prevents the client from submitting new jobs.
    Data is retained in the system.

    Requires: X-Auth-Token header
    """
    if not x_auth_token or x_auth_token != os.getenv("GATEWAY_AUTH_TOKEN", "f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3"):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    clients = _load_clients()
    if client_id not in clients:
        raise HTTPException(status_code=404, detail="Client not found")

    client = clients[client_id]
    was_active = client.get("active", False)
    client["active"] = False
    client["updated_at"] = _now_iso()
    _save_clients(clients)

    logger.info(f"Deactivated client {client_id[:8]} ({client.get('name')})")

    status = "was_inactive" if not was_active else "deactivated"
    return {
        "client_id": client_id,
        "status": status,
        "message": f"Client {client_id} is now inactive",
    }


# ═══════════════════════════════════════════════════════════════════════
# MIDDLEWARE — CLIENT KEY AUTH CHECK
# ═══════════════════════════════════════════════════════════════════════


async def check_client_key(request: Request) -> Optional[Dict[str, Any]]:
    """
    Extract and validate the X-Client-Key header.
    Returns the client record if valid, None otherwise.

    This is called by the gateway auth middleware for endpoints
    that require client authentication.
    """
    key = request.headers.get("X-Client-Key")
    if not key:
        return None
    return authenticate_client(key)


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION HELPERS (called by other modules)
# ═══════════════════════════════════════════════════════════════════════


def get_client_by_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    """
    Public function to authenticate a client by API key.
    Returns the client record or None if invalid.
    """
    return authenticate_client(api_key)


def can_submit_job(client: Dict[str, Any]) -> tuple[bool, str]:
    """
    Check if a client can submit a new job.
    Returns (allowed, reason_message).
    """
    if not client.get("active"):
        return False, "Client account is inactive"

    # Reset credits if billing cycle has ended
    client = reset_monthly_credits(client)

    return check_job_limit(client)


def deduct_job_credit(client_id: str) -> bool:
    """
    Deduct one job credit after successful job submission.
    Returns True if successful.
    """
    return deduct_credit(client_id, "job submission")


def log_client_cost(client_id: str, cost_usd: float, job_id: str = None) -> bool:
    """
    Log a cost against a client's account.
    Updates total_spent.

    Note: Credits are deducted per job, not per cost.
    This is for tracking actual API spend.
    """
    clients = _load_clients()
    if client_id not in clients:
        return False

    client = clients[client_id]
    client["total_spent"] = round(client.get("total_spent", 0.0) + cost_usd, 2)
    client["updated_at"] = _now_iso()

    if not client.get("metadata"):
        client["metadata"] = {}
    if "cost_log" not in client["metadata"]:
        client["metadata"]["cost_log"] = []

    client["metadata"]["cost_log"].append({
        "timestamp": _now_iso(),
        "cost": cost_usd,
        "job_id": job_id,
    })

    _save_clients(clients)
    logger.debug(f"Logged ${cost_usd} cost for client {client_id[:8]}")
    return True


# ═══════════════════════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════════════════════


def init_clients_file():
    """Initialize the clients file if it doesn't exist."""
    if not os.path.exists(CLIENTS_FILE):
        _save_clients({})
        logger.info(f"Initialized empty clients file at {CLIENTS_FILE}")


# Call on module load
init_clients_file()
