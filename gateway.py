"""
OpenClaw Gateway — Thin shell that wires routers + middleware.

All route handlers live in routers/*.py.
All shared code lives in routers/shared.py.
"""

import os
import sys
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Shared infrastructure (config, stubs, helpers, model callers) ────────
from routers.shared import (
    CONFIG, metrics, logger,
    init_memory_manager, get_memory_manager,
    init_cron_scheduler, get_cron_scheduler,
    call_model_for_agent,
    # Re-exports for backward compatibility (other modules import from gateway)
    anthropic_client, get_agent_config, send_slack_message, broadcast_event,
    SLACK_REPORT_CHANNEL,
)

# ── Lifespan-only imports (startup/shutdown) ─────────────────────────────
from response_cache import init_response_cache
from cost_gates import init_cost_gates
from heartbeat_monitor import HeartbeatMonitorConfig, init_heartbeat_monitor, stop_heartbeat_monitor
from event_engine import init_event_engine
from autonomous_runner import init_runner, get_runner
from error_recovery import init_error_recovery
from review_cycle import ReviewCycleEngine
from output_verifier import OutputVerifier

# ── External router modules (pre-existing, not in routers/) ─────────────
from audit_routes import router as audit_router
from intake_routes import router as intake_router
from client_auth import router as client_auth_router
from github_integration import router as github_router
from email_notifications import router as email_router

# ── New router modules ──────────────────────────────────────────────────
from routers.health import router as health_router
from routers.chat import router as chat_router
from routers.telegram import router as telegram_router
from routers.slack import router as slack_router
from routers.cost_quota import router as cost_quota_router
from routers.agent_manage import router as agent_manage_router
from routers.intelligent_routing import router as ir_router
from routers.websocket import router as ws_router
from routers.twilio import router as twilio_router
from routers.workflows import router as workflows_router
from routers.trading import router as trading_router
from routers.google_auth import router as google_auth_router
from routers.advanced import router as advanced_router
from routers.admin import router as admin_router
from routers.extra import router as extra_router

# Optional: research router
try:
    from routers.research import router as research_router
except ImportError:
    research_router = None


# ═════════════════════════════════════════════════════════════════════════
# LIFESPAN — startup & shutdown
# ═════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(application):
    # ── STARTUP ──────────────────────────────────────────────────────
    # Metrics
    try:
        metrics.load_from_disk()
        logger.info("Metrics system initialized (loaded costs from disk)")
    except Exception as e:
        logger.warning(f"Could not load metrics from disk: {e}")

    # Cost gates
    cost_gates_config = CONFIG.get("cost_gates", {})
    if cost_gates_config.get("enabled", True):
        cg = init_cost_gates(cost_gates_config)
        logger.info(f"Cost gates initialized: per-task=${cg.gates['per_task'].limit}, daily=${cg.gates['daily'].limit}, monthly=${cg.gates['monthly'].limit}")
    else:
        logger.info("Cost gates disabled in config")

    # Heartbeat monitor
    try:
        hb_config = HeartbeatMonitorConfig(
            check_interval_ms=30000,
            stale_threshold_ms=5 * 60 * 1000,
            timeout_threshold_ms=60 * 60 * 1000,
        )
        await init_heartbeat_monitor(alert_manager=None, config=hb_config)
        logger.info("Heartbeat monitor initialized and started")
    except Exception as err:
        logger.error(f"Failed to initialize heartbeat monitor: {err}")

    # Event engine
    try:
        event_engine = init_event_engine()
        logger.info("Event engine initialized (closed-loop system active)")
    except Exception as err:
        logger.error(f"Failed to initialize event engine: {err}")
        event_engine = None

    # Cron scheduler
    try:
        cron = init_cron_scheduler()
        cron.start()
        logger.info(f"Cron scheduler initialized ({len(cron.list_jobs())} jobs)")
    except Exception as err:
        logger.error(f"Failed to initialize cron scheduler: {err}")

    # Memory manager
    try:
        memory = init_memory_manager()
        logger.info(f"Memory manager initialized ({memory.count()} memories)")
    except Exception as err:
        logger.error(f"Failed to initialize memory manager: {err}")

    # Reactions engine
    try:
        from reactions import get_reactions_engine, register_with_event_engine
        reactions_eng = get_reactions_engine()
        if event_engine:
            register_with_event_engine(event_engine)
        logger.info(f"Reactions engine initialized ({len(reactions_eng.get_rules())} rules)")
    except Exception as err:
        logger.error(f"Failed to initialize reactions engine: {err}")

    # Self-improvement engine
    try:
        from self_improve import get_self_improve_engine
        get_self_improve_engine()
        logger.info("Self-improvement engine initialized")
    except Exception as err:
        logger.error(f"Failed to initialize self-improve engine: {err}")

    # Response cache
    try:
        init_response_cache(default_ttl=30, max_entries=1000)
        logger.info("Response cache initialized (TTL=30s, max=1000)")
    except Exception as err:
        logger.error(f"Failed to initialize response cache: {err}")

    # Autonomous runner
    try:
        runner = init_runner(max_concurrent=3, budget_limit_usd=15.0)
        await runner.start()
        logger.info("Autonomous job runner started (max_concurrent=3, budget=$15/job)")
    except Exception as err:
        logger.error(f"Failed to start autonomous runner: {err}")

    # AI CEO Engine
    try:
        from ceo_engine import get_ceo_engine
        ceo = get_ceo_engine()
        if ceo:
            await ceo.start()
            logger.info(f"AI CEO Engine started ({len(ceo.get_active_goals())} goals, 4 autonomous loops)")
    except Exception as err:
        logger.error(f"Failed to start CEO engine: {err}")

    # Scheduled Hands (autonomous workers)
    try:
        from scheduled_hands import get_scheduler
        hands_scheduler = get_scheduler()
        hands_scheduler.start()
        status = hands_scheduler.get_status()
        logger.info(f"Scheduled Hands started ({len(status['hands'])} hands registered)")
    except Exception as err:
        logger.error(f"Failed to start Scheduled Hands: {err}")

    # Review cycle + output verifier — inject into extra router
    try:
        import routers.extra as _extra_mod
        _extra_mod._review_engine = ReviewCycleEngine(call_agent_fn=call_model_for_agent)
        _extra_mod._output_verifier = OutputVerifier()
        logger.info("Review cycle engine + output verifier initialized")
    except Exception as err:
        logger.error(f"Failed to init review/verifier: {err}")

    # Error recovery
    try:
        recovery = await init_error_recovery()
        application.include_router(recovery.create_routes())
        logger.info("Error recovery system initialized (circuit breakers + crash recovery)")
    except Exception as err:
        logger.error(f"Failed to init error recovery: {err}")

    yield  # ── APP RUNNING ──

    # ── SHUTDOWN ─────────────────────────────────────────────────────
    try:
        from scheduled_hands import get_scheduler
        hs = get_scheduler()
        hs.stop()
        logger.info("Scheduled Hands stopped")
    except Exception as err:
        logger.error(f"Failed to stop Scheduled Hands: {err}")

    try:
        stop_heartbeat_monitor()
        logger.info("Heartbeat monitor stopped")
    except Exception as err:
        logger.error(f"Failed to stop heartbeat monitor: {err}")

    try:
        r = get_runner()
        if r:
            await r.stop()
        logger.info("Autonomous runner stopped")
    except Exception as err:
        logger.error(f"Failed to stop autonomous runner: {err}")

    try:
        from ceo_engine import get_ceo_engine
        ceo = get_ceo_engine()
        if ceo:
            await ceo.stop()
        logger.info("AI CEO Engine stopped")
    except Exception as err:
        logger.error(f"Failed to stop CEO engine: {err}")

    try:
        c = get_cron_scheduler()
        if c:
            c.stop()
        logger.info("Cron scheduler stopped")
    except Exception as err:
        logger.error(f"Failed to stop cron scheduler: {err}")


# ═════════════════════════════════════════════════════════════════════════
# APP CREATION + MIDDLEWARE
# ═════════════════════════════════════════════════════════════════════════

app = FastAPI(title="OpenClaw Gateway", version="4.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Include routers ─────────────────────────────────────────────────────
# Pre-existing external routers
app.include_router(audit_router)
app.include_router(intake_router)
app.include_router(client_auth_router)
app.include_router(github_router)
app.include_router(email_router)

# New modular routers
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(telegram_router)
app.include_router(slack_router)
app.include_router(cost_quota_router)
app.include_router(agent_manage_router)
app.include_router(ir_router)
app.include_router(ws_router)
app.include_router(twilio_router)
app.include_router(workflows_router)
app.include_router(trading_router)
app.include_router(google_auth_router)
app.include_router(advanced_router)
app.include_router(admin_router)
app.include_router(extra_router)
if research_router:
    app.include_router(research_router)

# Static files
app.mount("/static", StaticFiles(directory="/root/openclaw/static"), name="static")


# ── Auth middleware ──────────────────────────────────────────────────────
AUTH_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN")
if not AUTH_TOKEN:
    raise RuntimeError("GATEWAY_AUTH_TOKEN environment variable is required. Set it in .env or systemd unit.")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    exempt_paths = [
        "/", "/health", "/metrics", "/test-exempt", "/test-version",
        "/dashboard", "/dashboard.html", "/monitoring", "/terms", "/intake",
        "/telegram/webhook", "/coderclaw/webhook", "/slack/events",
        "/api/audit", "/client-portal", "/client_portal.html",
        "/api/billing/plans", "/api/billing/webhook", "/api/github/webhook",
        "/api/notifications/config", "/secrets", "/metrics-dashboard", "/mobile",
        "/sales", "/nightowl", "/visionclaw", "/oz", "/oz-status",
        "/webhook/twilio", "/webhook/openclaw-jobs", "/webhook/slack-test",
        "/api/digest", "/api/ping", "/api/version",
    ]
    path = request.url.path

    dashboard_exempt_prefixes = [
        "/api/costs", "/api/heartbeat", "/api/quotas", "/api/agents",
        "/api/route/health", "/api/proposal", "/api/proposals", "/api/policy",
        "/api/events", "/api/memories", "/api/memory", "/api/cron", "/api/tasks",
        "/api/workflows", "/api/dashboard", "/mission-control", "/job-viewer",
        "/api/intake", "/api/jobs", "/api/reviews", "/api/verify", "/api/runner",
        "/api/cache", "/api/health", "/api/reactions", "/api/metrics",
        "/oauth", "/api/gmail", "/api/calendar", "/api/polymarket",
        "/api/prediction", "/api/kalshi", "/api/arb", "/api/trading",
        "/api/sportsbook", "/api/sports", "/api/research", "/api/leads",
        "/api/calls", "/api/security", "/api/reflections", "/api/reminders",
        "/api/ai-news", "/api/tweets", "/api/perplexity-research",
        "/api/monitoring", "/api/pa", "/api/oz", "/api/ceo", "/api/pinch",
        "/api/mcp", "/api/eval", "/api/onboard", "/api/billing", "/api/hands",
    ]

    is_exempt = (
        path in exempt_paths
        or path.startswith(("/telegram/", "/slack/", "/api/audit", "/static/", "/control/", "/prestress/", "/ws/"))
        or any(path.startswith(prefix) for prefix in dashboard_exempt_prefixes)
    )

    if is_exempt:
        return await call_next(request)

    token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    if token != AUTH_TOKEN:
        logger.warning(f"AUTH FAILED: {path} (no valid token)")
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path in ["/health", "/metrics", "/test-exempt"]:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    if not metrics.check_rate_limit(client_ip, max_requests=30, window_seconds=60):
        logger.warning(f"RATE LIMITED: {client_ip} ({path})")
        return JSONResponse(
            {"error": "Rate limit exceeded (max 30 req/min per IP)"},
            status_code=429,
        )

    metrics.record_request(client_ip, path)
    return await call_next(request)


# ═════════════════════════════════════════════════════════════════════════
# MAIN — uvicorn entry point
# ═════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "18789"))
    print(f"🦞 OpenClaw Gateway v4.2 starting on port {port}")
    print(f"   REST: http://0.0.0.0:{port}/api/chat")
    print(f"   WebSocket: ws://0.0.0.0:{port}/ws")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
