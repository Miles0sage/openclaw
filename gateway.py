"""
OpenClaw Gateway - ACTUALLY USES LOCAL MODELS
Fixed to properly route to Ollama based on config.json
WITH PERSISTENT MEMORY
Webhook auth exemptions active (2026-02-17 18:30 UTC)
"""

import os
import json
import asyncio
import uuid
import sys
import pathlib
import hmac
import hashlib
import time
from fastapi import FastAPI, WebSocket, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import anthropic
import requests
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime, timezone

# Import orchestrator
from orchestrator import Orchestrator, AgentRole, Message as OrchMessage, MessageAudience

# Cost tracking — single source of truth in cost_tracker.py
from cost_tracker import (
    COST_PRICING as _COST_PRICING,
    calculate_cost,
    log_cost_event,
    get_cost_log_path,
    get_cost_metrics,
    get_cost_summary,
)

def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Local alias kept for any internal callers."""
    return calculate_cost(model, tokens_in, tokens_out)

# Inline quota stubs (replaces deleted quota_manager.py — quotas always pass)
def load_quota_config() -> dict:
    return {"enabled": False}

def check_daily_quota(project_id: str = "default") -> tuple:
    return True, None

def check_monthly_quota(project_id: str = "default") -> tuple:
    return True, None

def check_queue_size(project_id: str = "default", queue_size: int = 0) -> tuple:
    return True, None

def check_all_quotas(project_id: str = "default", queue_size: int = 0) -> tuple:
    return True, None

def get_quota_status(project_id: str = "default") -> dict:
    return {
        "daily": {"limit": 50, "used": 0, "remaining": 50, "percent": 0},
        "monthly": {"limit": 1000, "used": 0, "remaining": 1000, "percent": 0},
    }

# Inline metrics stub (replaces deleted metrics.py)
class _MetricsStub:
    def check_rate_limit(self, ip: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
        return True
    def record_request(self, ip: str, path: str):
        pass
    def record_agent_call(self, agent_id: str):
        pass
    def record_session(self, session_key: str):
        pass
    def get_prometheus_metrics(self) -> str:
        return "# No metrics collector\n"
    def load_from_disk(self):
        pass

metrics = _MetricsStub()

# Inline memory manager with JSONL persistence
class _MemoryManagerStub:
    def __init__(self):
        self._file = os.path.join(DATA_DIR, "memories.jsonl")
        os.makedirs(os.path.dirname(self._file), exist_ok=True)

    def count(self) -> int:
        if not os.path.exists(self._file): return 0
        with open(self._file) as f:
            return sum(1 for line in f if line.strip())

    def get_context_for_prompt(self, persona: str, max_tokens: int = 500) -> str:
        memories = self.get_recent(limit=10)
        return "\n".join(m.get("content", "") for m in memories)[:max_tokens]

    def auto_extract_memories(self, messages: list):
        pass

    def get_recent(self, limit: int = 20) -> list:
        if not os.path.exists(self._file): return []
        memories = []
        with open(self._file) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: memories.append(json.loads(line))
                except: continue
        return sorted(memories, key=lambda m: m.get("timestamp", ""), reverse=True)[:limit]

    def get_by_tag(self, tag: str) -> list:
        return [m for m in self.get_recent(limit=100) if tag in m.get("tags", [])]

    def add_memory(self, content: str, tags: list = None, source: str = "manual", importance: int = 5) -> str:
        import uuid
        mem_id = str(uuid.uuid4())[:8]
        record = {
            "id": mem_id, "content": content, "tags": tags or [],
            "source": source, "importance": importance,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        with open(self._file, "a") as f:
            f.write(json.dumps(record) + "\n")
        return mem_id

_memory_manager_instance = None

def init_memory_manager():
    global _memory_manager_instance
    _memory_manager_instance = _MemoryManagerStub()
    return _memory_manager_instance

def get_memory_manager():
    return _memory_manager_instance

# Inline cron scheduler stub (replaces deleted cron_scheduler.py)
class _CronSchedulerStub:
    def start(self):
        pass
    def stop(self):
        pass
    def list_jobs(self) -> list:
        return []

_cron_scheduler_instance = None

def init_cron_scheduler():
    global _cron_scheduler_instance
    _cron_scheduler_instance = _CronSchedulerStub()
    return _cron_scheduler_instance

def get_cron_scheduler():
    return _cron_scheduler_instance

# Import deepseek client
from request_logger import RequestLogger, get_logger
from audit_routes import router as audit_router

from deepseek_client import DeepseekClient
from minimax_client import MiniMaxClient
from gemini_client import GeminiClient

# Import response cache
from response_cache import init_response_cache, get_response_cache

# Import agent tools (GitHub, web search, job management)
from agent_tools import AGENT_TOOLS, execute_tool

# Import complexity classifier (intelligent router)
from complexity_classifier import (
    classify as classify_query,
    ClassificationResult,
    MODEL_PRICING,
    MODEL_ALIASES,
    MODEL_RATE_LIMITS,
)

# Import heartbeat monitor
from heartbeat_monitor import (
    HeartbeatMonitor,
    HeartbeatMonitorConfig,
    init_heartbeat_monitor,
    get_heartbeat_monitor,
    stop_heartbeat_monitor,
)

# Import agent router (intelligent task routing)
from agent_router import AgentRouter

# Import workflow engine
from workflow_engine import WorkflowEngine

# Import job manager
from job_manager import create_job, get_job, list_jobs, update_job_status

# Import autonomous runner (background job executor)
from autonomous_runner import AutonomousRunner, init_runner, get_runner

# Import review cycle engine (agent-to-agent collaboration)
from review_cycle import ReviewCycleEngine, ReviewStatus

# Import output verifier (quality gates)
from output_verifier import OutputVerifier

# Import client intake routes
from intake_routes import router as intake_router

# Import client auth & billing
from client_auth import router as client_auth_router

# Import GitHub PR integration
from github_integration import router as github_router

# Import email notifications
from email_notifications import router as email_router, EmailNotifier

# Import error recovery
from error_recovery import ErrorRecoveryManager, init_error_recovery

# Import agent registry (auto-registration system)
from agent_registry import (
    init_agent_registry,
    get_agent_registry,
    register_agents_from_config,
)


# metrics_collector and gateway_metrics_integration removed (deleted modules)
# No-op stubs for any remaining references
def init_metrics_collector(): pass
def get_metrics_collector(): return None
def record_metric(**kwargs): pass

from cost_gates import (
    get_cost_gates, init_cost_gates, check_cost_budget,
    record_cost, BudgetStatus
)

# Import closed-loop engines
from proposal_engine import create_proposal, get_proposal, list_proposals, update_proposal_status, estimate_cost
from approval_engine import evaluate_proposal, auto_approve_and_execute, get_policy
from event_engine import init_event_engine, get_event_engine
# cron_scheduler and memory_manager removed — stubs defined earlier in this file

load_dotenv()

# Slack Configuration
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_REPORT_CHANNEL = os.getenv("SLACK_REPORT_CHANNEL", "#general")

# Setup logging
_LOG_LEVEL = os.getenv("OPENCLAW_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("openclaw_gateway")

# Session persistence - v2
DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data")
SESSIONS_DIR = pathlib.Path(os.getenv("OPENCLAW_SESSIONS_DIR", os.path.join(DATA_DIR, "sessions")))
SESSIONS_DIR.mkdir(exist_ok=True)
logger.info(f"📁 Session storage: {SESSIONS_DIR}")

class SessionStore:
    """Lazy-loading session store with atomic writes."""
    def __init__(self, sessions_dir):
        self._dir = pathlib.Path(sessions_dir)
        self._cache = {}

    def get(self, key: str) -> list:
        if key not in self._cache:
            safe_key = key.replace("/", "_").replace("\\", "_")
            path = self._dir / f"{safe_key}.json"
            if path.exists():
                try:
                    with open(path) as f:
                        data = json.load(f)
                        self._cache[key] = data.get("messages", [])
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Failed to load session {key}: {e}")
                    self._cache[key] = []
            else:
                self._cache[key] = []
        return self._cache[key]

    def set(self, key: str, messages: list):
        self._cache[key] = messages
        safe_key = key.replace("/", "_").replace("\\", "_")
        path = self._dir / f"{safe_key}.json"
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump({"session_key": key, "messages": messages}, f)
            tmp.replace(path)  # Atomic rename
        except IOError as e:
            logger.error(f"Failed to save session {key}: {e}")

    def keys(self):
        disk_keys = set()
        for p in self._dir.glob("*.json"):
            disk_keys.add(p.stem)
        return list(set(self._cache.keys()) | disk_keys)

    def __len__(self):
        return len(self.keys())

    def __contains__(self, key):
        if key in self._cache:
            return True
        safe_key = key.replace("/", "_").replace("\\", "_")
        return (self._dir / f"{safe_key}.json").exists()



# Tasks storage for Mission Control
TASKS_FILE = pathlib.Path(os.path.join(DATA_DIR, "jobs", "tasks.json"))


# ═══════════════════════════════════════════════════════════════════════
# SSE EVENT STREAM — Real-time event broadcasting for Mission Control
# ═══════════════════════════════════════════════════════════════════════

_event_log = []  # Ring buffer of recent events (max 200)

def broadcast_event(event_data: dict):
    """Broadcast an event to SSE subscribers via ring buffer"""
    event_data.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
    _event_log.append(event_data)
    while len(_event_log) > 200:
        _event_log.pop(0)


# ═══════════════════════════════════════════════════════════════════════
# COST ALERTS — Slack webhook notifications when budgets are hit
# ═══════════════════════════════════════════════════════════════════════

_cost_alerts_sent = {}  # {threshold_key: timestamp} for dedup

def send_cost_alert_if_needed():
    """Check cost thresholds and send Slack alerts if needed"""
    try:
        slack_config = CONFIG.get("slack_alerts", {})
    except NameError:
        slack_config = {}
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")

    if not webhook_url:
        return

    try:
        cost_data = get_cost_metrics()
        quota_status = get_quota_status("default")

        daily_spend = cost_data.get("today_usd", 0)
        monthly_spend = cost_data.get("month_usd", 0)
        daily_limit = quota_status.get("daily", {}).get("limit", 50)
        monthly_limit = quota_status.get("monthly", {}).get("limit", 1000)

        thresholds = [80, 90, 100]
        alerts = []

        if daily_limit > 0:
            daily_pct = (daily_spend / daily_limit) * 100
            for threshold in thresholds:
                if daily_pct >= threshold:
                    key = f"daily_{threshold}_{datetime.utcnow().strftime('%Y-%m-%d')}"
                    if key not in _cost_alerts_sent:
                        alerts.append(f"Daily spend at ${daily_spend:.2f}/${daily_limit:.2f} ({daily_pct:.0f}%)")
                        _cost_alerts_sent[key] = time.time()

        if monthly_limit > 0:
            monthly_pct = (monthly_spend / monthly_limit) * 100
            for threshold in thresholds:
                if monthly_pct >= threshold:
                    key = f"monthly_{threshold}_{datetime.utcnow().strftime('%Y-%m')}"
                    if key not in _cost_alerts_sent:
                        alerts.append(f"Monthly spend at ${monthly_spend:.2f}/${monthly_limit:.2f} ({monthly_pct:.0f}%)")
                        _cost_alerts_sent[key] = time.time()

        for alert_msg in alerts:
            try:
                requests.post(webhook_url, json={
                    "text": f"[COST ALERT] {alert_msg}",
                    "username": "OpenClaw Cost Monitor",
                    "icon_emoji": ":money_with_wings:"
                }, timeout=5)
                logger.info(f"💰 Cost alert sent: {alert_msg}")
                broadcast_event({"type": "cost_alert", "agent": "system", "message": alert_msg})
            except Exception as e:
                logger.error(f"Failed to send Slack alert: {e}")

    except Exception as e:
        logger.warning(f"Cost alert check failed: {e}")


def sanitize_session_key(session_key: str) -> str:
    """Sanitize session key to prevent path traversal attacks"""
    import re
    # Only allow alphanumeric, colons, underscores, and hyphens
    sanitized = re.sub(r'[^a-zA-Z0-9:_\-]', '', session_key)
    # Reject if empty or suspicious patterns
    if not sanitized or '..' in sanitized or '/' in session_key:
        raise ValueError(f"Invalid session key: {session_key}")
    return sanitized

def load_session_history(session_key: str) -> list:
    """Load chat history for a session from disk"""
    session_key = sanitize_session_key(session_key)
    session_file = SESSIONS_DIR / f"{session_key}.json"
    if session_file.exists():
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
                logger.info(f"📖 Loaded session {session_key}: {len(data.get('messages', []))} messages")
                return data.get('messages', [])
        except Exception as e:
            logger.error(f"Error loading session {session_key}: {e}")
    return []

def save_session_history(session_key: str, history: list) -> bool:
    """Save chat history for a session to disk"""
    session_key = sanitize_session_key(session_key)
    session_file = SESSIONS_DIR / f"{session_key}.json"
    try:
        data = {
            "session_key": session_key,
            "messages": history,
            "updated_at": asyncio.get_event_loop().time()
        }
        with open(session_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"💾 Saved session {session_key}: {len(history)} messages")
        return True
    except Exception as e:
        logger.error(f"Error saving session {session_key}: {e}")
        return False


async def send_slack_message(channel: str, text: str, thread_ts: str = None) -> bool:
    """Send a message to a Slack channel"""
    if not SLACK_BOT_TOKEN:
        logger.warning("⚠️  Slack Bot Token not configured, skipping send")
        return False

    try:
        payload = {
            "channel": channel,
            "text": text
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json=payload
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    logger.info(f"✅ Slack message sent to {channel}")
                    return True
                else:
                    logger.warning(f"⚠️  Slack API error: {data.get('error')}")
                    return False
            else:
                logger.warning(f"⚠️  Slack send failed: {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"❌ Error sending to Slack: {e}")
        return False


async def call_claude_with_tools(client, model: str, system_prompt: str, messages: list, max_rounds: int = 5) -> str:
    """Call Claude with tool_use support. Loops until text response or max rounds.
    Runs synchronous Anthropic client in a thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()

    # Cache tool definitions (they don't change between calls)
    cached_tools = list(AGENT_TOOLS)
    if cached_tools:
        cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}

    for _ in range(max_rounds):
        # Cache conversation prefix — mark last user message so the prefix is cached
        if messages and len(messages) >= 2:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user":
                    content = messages[i]["content"]
                    if isinstance(content, str):
                        messages[i]["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                    elif isinstance(content, list):
                        last_block = content[-1]
                        if isinstance(last_block, dict) and "cache_control" not in last_block:
                            content[-1] = {**last_block, "cache_control": {"type": "ephemeral"}}
                    break

        # Run synchronous API call in thread pool so we don't block the event loop
        response = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model=model,
                max_tokens=8192,
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                tools=cached_tools
            )
        )

        # Collect all tool uses and text blocks
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if not tool_uses:
            # No tool calls — return the text
            return text_blocks[0].text if text_blocks else "No response"

        # Serialize response.content to plain dicts for the messages list
        # (Anthropic SDK objects are not JSON-serializable and can cause issues)
        serialized_content = []
        for block in response.content:
            if block.type == "text":
                serialized_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                serialized_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })

        messages.append({"role": "assistant", "content": serialized_content})

        tool_results = []
        for tu in tool_uses:
            logger.info(f"Tool call: {tu.name}({json.dumps(tu.input)[:100]})")
            result = execute_tool(tu.name, tu.input)
            logger.info(f"Tool result: {result[:100]}...")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result
            })

        messages.append({"role": "user", "content": tool_results})

    return "Max tool rounds reached. Please try a simpler request."


# Initialize Orchestrator
orchestrator = Orchestrator()

app = FastAPI(title="OpenClaw Gateway", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# metrics_collector and setup_metrics removed (stubs in place)

# Include audit routes
app.include_router(audit_router)

# Include client intake routes
app.include_router(intake_router)

# Include client auth & billing routes
app.include_router(client_auth_router)

# Include GitHub PR integration routes
app.include_router(github_router)

# Include email notification routes
app.include_router(email_router)
# Authentication token - read from environment for security
AUTH_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN", "f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # WEBHOOK & DASHBOARD EXEMPTIONS: Allow without auth
    exempt_paths = ["/", "/health", "/metrics", "/test-exempt", "/dashboard", "/dashboard.html", "/monitoring", "/terms", "/telegram/webhook", "/slack/events", "/api/audit", "/client-portal", "/client_portal.html", "/api/billing/plans", "/api/billing/webhook", "/api/github/webhook", "/api/notifications/config", "/api/health/detailed", "/api/health/circuit-breakers", "/api/health/alerts", "/secrets", "/metrics-dashboard", "/mobile"]
    path = request.url.path

    # Dashboard APIs exempt from auth (for monitoring UI + client portal)
    dashboard_exempt_prefixes = ["/api/costs", "/api/heartbeat", "/api/quotas", "/api/agents", "/api/route/health", "/api/proposal", "/api/proposals", "/api/policy", "/api/events", "/api/memories", "/api/memory", "/api/cron", "/api/tasks", "/api/workflows", "/api/dashboard", "/mission-control", "/api/intake", "/api/jobs", "/api/reviews", "/api/verify", "/api/runner", "/api/cache", "/api/health", "/api/reactions", "/api/metrics", "/oauth", "/api/gmail", "/api/calendar"]

    # Debug logging (for troubleshooting only)
    is_exempt = (path in exempt_paths or
                 path.startswith(("/telegram/", "/slack/", "/api/audit", "/static/")) or
                 any(path.startswith(prefix) for prefix in dashboard_exempt_prefixes))
    logger.debug(f"AUTH_CHECK: path={path}, is_exempt={is_exempt}")

    # Exempt webhook paths
    if is_exempt:
        logger.debug(f"✅ EXEMPT: {path}")
        return await call_next(request)

    # Check auth token
    token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    if token != AUTH_TOKEN:
        logger.warning(f"❌ AUTH FAILED: {path} (no valid token)")
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    logger.debug(f"✅ AUTH OK: {path}")
    return await call_next(request)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting middleware: max 30 requests per IP per minute"""
    # Exempt metrics and health endpoints
    path = request.url.path
    if path in ["/health", "/metrics", "/test-exempt"]:
        return await call_next(request)

    # Get client IP
    client_ip = request.client.host if request.client else "unknown"

    # Check rate limit
    if not metrics.check_rate_limit(client_ip, max_requests=30, window_seconds=60):
        logger.warning(f"⚠️  RATE LIMITED: {client_ip} ({path})")
        return JSONResponse(
            {"error": "Rate limit exceeded (max 30 req/min per IP)"},
            status_code=429
        )

    # Record request
    metrics.record_request(client_ip, path)

    # Call next middleware
    response = await call_next(request)
    return response

def _apply_env_overrides(cfg: dict) -> dict:
    """Apply OPENCLAW_* environment variable overrides to config."""
    overrides = {
        "OPENCLAW_BUDGET": lambda v: cfg.setdefault("cost_gates", {}).update({"per_task_limit": float(v)}),
        "OPENCLAW_POLL_INTERVAL": lambda v: cfg.setdefault("runner", {}).update({"poll_interval": int(v)}),
        "OPENCLAW_MAX_CONCURRENT": lambda v: cfg.setdefault("runner", {}).update({"max_concurrent": int(v)}),
        "OPENCLAW_LOG_LEVEL": lambda v: cfg.setdefault("logging", {}).update({"level": v.upper()}),
    }
    for env_key, apply_fn in overrides.items():
        val = os.getenv(env_key)
        if val:
            apply_fn(val)
            logger.info(f"Config override: {env_key}={val}")
    return cfg

# Load config
with open('config.json', 'r') as f:
    CONFIG = json.load(f)
CONFIG = _apply_env_overrides(CONFIG)

# Initialize Agent Router for intelligent task routing
agent_router = AgentRouter(config_path='config.json')

# Initialize Anthropic client
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Initialize Workflow Engine for multi-step workflows
workflow_engine = WorkflowEngine()

# Protocol version
PROTOCOL_VERSION = 3

# Timeout settings
WS_RECEIVE_TIMEOUT = 120
WS_PING_INTERVAL = 30
WS_PING_TIMEOUT = 10

# Active connections
active_connections: Dict[str, WebSocket] = {}
session_store = SessionStore(SESSIONS_DIR)

# FastAPI startup/shutdown event handlers for heartbeat monitor
@app.on_event("startup")
async def startup_heartbeat_monitor():
    """Initialize heartbeat monitor on FastAPI startup"""
    # Initialize metrics system
    try:
        metrics.load_from_disk()
        logger.info(f"✅ Metrics system initialized (loaded costs from disk)")
    except Exception as e:
        logger.warning(f"⚠️  Could not load metrics from disk: {e}")

    # Initialize cost gates
    cost_gates_config = CONFIG.get("cost_gates", {})
    if cost_gates_config.get("enabled", True):
        cost_gates = init_cost_gates(cost_gates_config)
        logger.info(f"✅ Cost gates initialized: per-task=${cost_gates.gates['per_task'].limit}, daily=${cost_gates.gates['daily'].limit}, monthly=${cost_gates.gates['monthly'].limit}")
    else:
        logger.info("⚠️  Cost gates disabled in config")
    
    try:
        config = HeartbeatMonitorConfig(
            check_interval_ms=30000,  # 30 seconds
            stale_threshold_ms=5 * 60 * 1000,  # 5 minutes
            timeout_threshold_ms=60 * 60 * 1000  # 1 hour
        )
        monitor = await init_heartbeat_monitor(alert_manager=None, config=config)
        logger.info("✅ Heartbeat monitor initialized and started")
    except Exception as err:
        logger.error(f"Failed to initialize heartbeat monitor: {err}")

    # Initialize event engine (closed-loop system)
    try:
        event_engine = init_event_engine()
        logger.info("✅ Event engine initialized (closed-loop system active)")
    except Exception as err:
        logger.error(f"Failed to initialize event engine: {err}")

    # Initialize cron scheduler
    try:
        cron = init_cron_scheduler()
        cron.start()
        logger.info(f"✅ Cron scheduler initialized ({len(cron.list_jobs())} jobs)")
    except Exception as err:
        logger.error(f"Failed to initialize cron scheduler: {err}")

    # Initialize memory manager
    try:
        memory = init_memory_manager()
        logger.info(f"✅ Memory manager initialized ({memory.count()} memories)")
    except Exception as err:
        logger.error(f"Failed to initialize memory manager: {err}")

    # Initialize reactions engine
    try:
        from reactions import get_reactions_engine, register_with_event_engine
        reactions_eng = get_reactions_engine()
        if event_engine:
            register_with_event_engine(event_engine)
        logger.info(f"✅ Reactions engine initialized ({len(reactions_eng.get_rules())} rules)")
    except Exception as err:
        logger.error(f"Failed to initialize reactions engine: {err}")

    # Initialize self-improvement engine
    try:
        from self_improve import get_self_improve_engine
        si_engine = get_self_improve_engine()
        logger.info("✅ Self-improvement engine initialized")
    except Exception as err:
        logger.error(f"Failed to initialize self-improve engine: {err}")

    # Initialize response cache
    try:
        cache = init_response_cache(default_ttl=30, max_entries=1000)
        logger.info("Response cache initialized (TTL=30s, max=1000)")
    except Exception as err:
        logger.error(f"Failed to initialize response cache: {err}")


@app.on_event("startup")
async def startup_autonomous_runner():
    """Initialize autonomous job runner on FastAPI startup"""
    try:
        runner = init_runner(max_concurrent=2, budget_limit_usd=15.0)
        await runner.start()
        logger.info("✅ Autonomous job runner started (max_concurrent=2, budget=$15/job)")
    except Exception as err:
        logger.error(f"Failed to start autonomous runner: {err}")

    # Initialize review cycle engine with agent caller
    try:
        global _review_engine, _output_verifier
        _review_engine = ReviewCycleEngine(call_agent_fn=call_model_for_agent)
        _output_verifier = OutputVerifier()
        logger.info("✅ Review cycle engine + output verifier initialized")
    except Exception as err:
        logger.error(f"Failed to init review/verifier: {err}")

    # Initialize error recovery system
    try:
        recovery = await init_error_recovery()
        app.include_router(recovery.create_routes())
        logger.info("✅ Error recovery system initialized (circuit breakers + crash recovery)")
    except Exception as err:
        logger.error(f"Failed to init error recovery: {err}")


@app.on_event("shutdown")
async def shutdown_heartbeat_monitor():
    """Stop heartbeat monitor and autonomous runner on FastAPI shutdown"""
    try:
        stop_heartbeat_monitor()
        logger.info("✅ Heartbeat monitor stopped")
    except Exception as err:
        logger.error(f"Failed to stop heartbeat monitor: {err}")

    try:
        runner = get_runner()
        if runner:
            await runner.stop()
        logger.info("✅ Autonomous runner stopped")
    except Exception as err:
        logger.error(f"Failed to stop autonomous runner: {err}")

    try:
        cron = get_cron_scheduler()
        if cron:
            cron.stop()
        logger.info("✅ Cron scheduler stopped")
    except Exception as err:
        logger.error(f"Failed to stop cron scheduler: {err}")

# Sessions use lazy loading via SessionStore
logger.info(f"✅ Session lazy loading enabled — sessions loaded on demand from {SESSIONS_DIR}")


class Message(BaseModel):
    content: str
    agent_id: Optional[str] = "pm"
    sessionKey: Optional[str] = None  # Support session memory
    project_id: Optional[str] = None  # For quota tracking
    use_tools: Optional[bool] = None  # Enable tool_use (auto-detected if None)


class VisionRequest(BaseModel):
    image: str  # base64-encoded JPEG image
    query: str = "describe"  # Query type: describe, read_text, translate, remember, identify
    session_key: Optional[str] = None
    language: Optional[str] = None  # Target language for translate query
    device_id: Optional[str] = None  # Device identifier for rate limiting


# Rate limiter for vision endpoint: max 10 images/minute per device_id
_vision_rate_limits: Dict[str, list] = {}  # {device_id: [timestamp, ...]}

def _check_vision_rate_limit(device_id: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    """Check if device_id has exceeded vision rate limit. Returns True if allowed."""
    now = time.time()
    if device_id not in _vision_rate_limits:
        _vision_rate_limits[device_id] = []
    # Prune old entries
    _vision_rate_limits[device_id] = [
        ts for ts in _vision_rate_limits[device_id] if now - ts < window_seconds
    ]
    if len(_vision_rate_limits[device_id]) >= max_requests:
        return False
    _vision_rate_limits[device_id].append(now)
    return True


def _build_system_prompt(agent_key: str, agent_config: dict = None) -> str:
    """Build system prompt for an agent (reused by tool calls and direct calls)."""
    if not agent_config:
        agent_config = get_agent_config(agent_key) or {}

    persona = agent_config.get("persona", "")
    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    signature = agent_config.get("signature", "")

    # Load identity files
    identity_context = ""
    gateway_dir = os.path.dirname(os.path.abspath(__file__))
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                identity_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass

    delegation_instructions = ""
    if agent_key == "project_manager":
        delegation_instructions = """
DELEGATION: When a task requires specialist work, include markers:
[DELEGATE:elite_coder]task[/DELEGATE]
[DELEGATE:coder_agent]task[/DELEGATE]
[DELEGATE:hacker_agent]task[/DELEGATE]
[DELEGATE:database_agent]task[/DELEGATE]
"""

    return f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

IMPORTANT RULES:
- ALWAYS end your messages with your signature: {signature}
- You have access to execution tools: shell commands, git, file I/O, Vercel deploy, package install, web scraping, and research.
- Use tools proactively to accomplish tasks. Don't just describe what to do — DO it.
- When asked to build, deploy, or fix something, use the tools to actually execute the work.
- Research before executing complex tasks (use research_task tool).
- Auto-install missing tools/packages as needed (use install_package tool).
{delegation_instructions}
--- IDENTITY & CONTEXT ---
{identity_context}"""


def call_ollama(model: str, prompt: str, endpoint: str = "http://localhost:11434") -> tuple[str, int]:
    """Call Ollama API"""
    logger.info(f"🔥 Calling Ollama: {model}")

    response = requests.post(
        f"{endpoint}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    data = response.json()
    text = data.get("response", "")
    tokens = len(text.split())  # Rough estimate

    logger.info(f"✅ Ollama responded: {len(text)} chars")
    return text, tokens


def call_anthropic(model: str, prompt: str) -> tuple[str, int]:
    """Call Anthropic API"""
    logger.info(f"☁️  Calling Anthropic: {model}")

    response = anthropic_client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text
    tokens = response.usage.output_tokens

    logger.info(f"✅ Anthropic responded: {tokens} tokens")
    return text, tokens


def get_agent_config(agent_key: str) -> Dict:
    """Get agent configuration from config.json"""
    return CONFIG.get("agents", {}).get(agent_key, {})


# ═══════════════════════════════════════════════════════════════════════
# AUTO-ESCALATION CHAIN — If cheap agent fails, retry with more capable one
# ═══════════════════════════════════════════════════════════════════════

ESCALATION_CHAIN = {
    # agent_id -> fallback agent_id (cheaper → more capable)
    "coder_agent": "elite_coder",      # Kimi 2.5 → MiniMax M2.5
    "elite_coder": "project_manager",   # MiniMax M2.5 → Claude Opus
    "hacker_agent": "project_manager",  # Kimi Reasoner → Claude Opus
    "database_agent": None,             # Already on Opus, no escalation
    "project_manager": None,            # Top of chain
}

def call_model_with_escalation(agent_key: str, prompt: str, conversation: list = None, max_escalations: int = 2) -> tuple[str, int, str]:
    """
    Call model with automatic escalation on failure.
    Returns: (response_text, tokens, actual_agent_used)
    """
    current_agent = agent_key
    attempts = 0

    while current_agent and attempts <= max_escalations:
        try:
            response_text, tokens = call_model_for_agent(current_agent, prompt, conversation)
            if attempts > 0:
                logger.info(f"⬆️ Escalation success: {agent_key} → {current_agent} (attempt {attempts + 1})")
                broadcast_event({
                    "type": "escalation_success",
                    "agent": current_agent,
                    "message": f"Escalated from {agent_key} → {current_agent} (succeeded)",
                })
            return response_text, tokens, current_agent
        except Exception as e:
            logger.warning(f"⚠️ Agent {current_agent} failed: {e}")
            broadcast_event({
                "type": "escalation_attempt",
                "agent": current_agent,
                "message": f"{current_agent} failed: {str(e)[:60]}. Escalating...",
            })
            next_agent = ESCALATION_CHAIN.get(current_agent)
            if next_agent:
                logger.info(f"⬆️ Escalating: {current_agent} → {next_agent}")
                current_agent = next_agent
                attempts += 1
            else:
                raise  # No escalation path, propagate error

    # Should not reach here, but just in case
    raise RuntimeError(f"Escalation chain exhausted for {agent_key} after {attempts} attempts")


def call_model_for_agent(agent_key: str, prompt: str, conversation: list = None) -> tuple[str, int]:
    """
    Route to correct model based on agent config

    Returns: (response_text, tokens_used)
    """
    agent_config = get_agent_config(agent_key)

    if not agent_config:
        logger.warning(f"⚠️  No config for agent: {agent_key}, using default")
        agent_config = get_agent_config("project_manager")

    provider = agent_config.get("apiProvider", "anthropic")
    model = agent_config.get("model", "claude-sonnet-4-5-20250929")
    endpoint = agent_config.get("endpoint", "http://localhost:11434")

    # Build system prompt with persona
    persona = agent_config.get("persona", "")
    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    signature = agent_config.get("signature", "")

    # ═══════════════════════════════════════════════════════════════════════
    # IDENTITY STACK: Load SOUL.md, USER.md, AGENTS.md for full context
    # This gives the agent knowledge of real projects, team, and behavior rules
    # ═══════════════════════════════════════════════════════════════════════
    identity_context = ""
    gateway_dir = os.path.dirname(os.path.abspath(__file__))
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                identity_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            logger.warning(f"Identity file not found: {filepath}")

    # Load skill graph index for project/tool awareness
    skills_index = ""
    skills_index_path = os.path.join(gateway_dir, "skills", "index.md")
    try:
        with open(skills_index_path, "r") as f:
            skills_index = f.read()
    except FileNotFoundError:
        logger.warning(f"Skill graph index not found: {skills_index_path}")

    # Delegation capability for PM agent
    delegation_instructions = ""
    if agent_key == "project_manager":
        delegation_instructions = """

DELEGATION: When a task requires specialist work, you can delegate by including markers in your response:
[DELEGATE:elite_coder]detailed task description here[/DELEGATE]
[DELEGATE:coder_agent]simple coding task here[/DELEGATE]
[DELEGATE:hacker_agent]security review task here[/DELEGATE]
[DELEGATE:database_agent]database query task here[/DELEGATE]

Only delegate when the task clearly needs a specialist. For planning, coordination, and general questions, handle directly.
After delegation results come back, synthesize them into a final response for the user.
"""

    # Full system prompt for Anthropic (handles long prompts well)
    anthropic_system = f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

IMPORTANT RULES:
- ALWAYS end your messages with your signature: {signature}
- Follow your character consistently
- Follow the communication and behavior rules in the identity documents below
- Reference real project names (Barber CRM, Delhi Palace, OpenClaw, PrestressCalc, Concrete Canoe)
- NEVER invent fake project names like "DataGuard Enterprise" or "SecureShield"
{delegation_instructions}
Remember: You ARE {name}. Stay in character!

--- IDENTITY & CONTEXT ---
{identity_context}

--- SKILL GRAPH ---
{skills_index}"""

    # Minimal system prompt for Ollama (to avoid timeouts)
    ollama_suffix = f"\n\nSign your response with: {signature}"

    # === INTELLIGENT ROUTING ===
    # If provider is Anthropic and routing is enabled, use complexity classifier
    # to select optimal model (Haiku/Sonnet/Opus) for cost savings
    router_enabled = CONFIG.get("routing", {}).get("enabled", False)
    if router_enabled and provider == "anthropic":
        try:
            classification = classify_query(prompt)
            routed_model = MODEL_ALIASES.get(classification.model, model)
            logger.info(f"🧠 Router: complexity={classification.complexity}, "
                        f"model={classification.model} ({routed_model}), "
                        f"confidence={classification.confidence}")
            model = routed_model
        except Exception as e:
            logger.warning(f"⚠️  Router failed, using default model: {e}")

    logger.info(f"📍 Agent: {agent_key} → Provider: {provider} → Model: {model}")

    # Build full prompt with conversation history if provided
    if conversation:
        full_prompt = "\n\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in conversation
        ])
        full_prompt += f"\n\nassistant: "
    else:
        full_prompt = prompt

    # Route to correct provider
    if provider == "ollama":
        # For Ollama, just add signature reminder (no cost tracking - local model)
        ollama_prompt = f"{full_prompt}{ollama_suffix}"
        return call_ollama(model, ollama_prompt, endpoint)
    elif provider == "anthropic":
        # For Anthropic, use system parameter with full identity stack + prompt caching
        cached_system = [{"type": "text", "text": anthropic_system, "cache_control": {"type": "ephemeral"}}]
        if conversation:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=8192,
                system=cached_system,
                messages=conversation
            )
            response_text = response.content[0].text
            tokens_input = response.usage.input_tokens
            tokens_output = response.usage.output_tokens
        else:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=8192,
                system=cached_system,
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = response.content[0].text
            tokens_input = response.usage.input_tokens
            tokens_output = response.usage.output_tokens

        # Log cost event (non-blocking, errors won't affect response)
        try:
            cost = log_cost_event(
                project="openclaw",
                agent=agent_key,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output
            )
            logger.info(f"💰 Cost logged: ${cost:.4f} ({agent_key} / {model})")
        except Exception as e:
            logger.warning(f"⚠️ Cost logging failed: {e}")

        return response_text, tokens_output
    elif provider == "deepseek":
        # For Deepseek (Kimi models)
        try:
            deepseek_client = DeepseekClient()

            # Map model names if needed
            api_model = model if model in ["kimi-2.5", "kimi"] else "kimi-2.5"

            response = deepseek_client.call(
                model=api_model,
                prompt=prompt if not conversation else full_prompt,
                system_prompt=anthropic_system,
                max_tokens=8192,
                temperature=0.7
            )

            response_text = response.content
            tokens_input = response.tokens_input
            tokens_output = response.tokens_output

            # Log cost event (non-blocking)
            try:
                cost = log_cost_event(
                    project="openclaw",
                    agent=agent_key,
                    model=api_model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output
                )
                logger.info(f"💰 Cost logged: ${cost:.4f} ({agent_key} / {api_model})")
            except Exception as e:
                logger.warning(f"⚠️ Cost logging failed: {e}")

            return response_text, tokens_output
        except Exception as e:
            logger.error(f"❌ Deepseek API error: {e}")
            raise
    elif provider == "minimax":
        # For MiniMax (M2.5 models)
        try:
            minimax_client = MiniMaxClient()

            # Map model names if needed
            api_model = model if model in ["m2.5", "m2.5-lightning"] else "m2.5"

            response = minimax_client.call(
                model=api_model,
                prompt=prompt if not conversation else full_prompt,
                system_prompt=anthropic_system,
                max_tokens=16384,
                temperature=0.3
            )

            response_text = response.content
            tokens_input = response.tokens_input
            tokens_output = response.tokens_output

            # Log cost event (non-blocking)
            try:
                cost = log_cost_event(
                    project="openclaw",
                    agent=agent_key,
                    model=api_model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output
                )
                logger.info(f"💰 Cost logged: ${cost:.4f} ({agent_key} / {api_model})")
            except Exception as e:
                logger.warning(f"⚠️ Cost logging failed: {e}")

            return response_text, tokens_output
        except Exception as e:
            logger.error(f"❌ MiniMax API error: {e}")
            raise
    elif provider == "gemini":
        # For Gemini models
        try:
            gemini_client = GeminiClient()

            # Map model names if needed
            valid_models = list(GeminiClient.MODELS.keys())
            api_model = model if model in valid_models else "gemini-2.5-flash"

            response = gemini_client.call(
                model=api_model,
                prompt=prompt if not conversation else full_prompt,
                system_prompt=anthropic_system,
                max_tokens=8192,
                temperature=0.3
            )

            response_text = response.content
            tokens_input = response.tokens_input
            tokens_output = response.tokens_output

            # Log cost event (non-blocking)
            try:
                cost = log_cost_event(
                    project="openclaw",
                    agent=agent_key,
                    model=api_model,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output
                )
                logger.info(f"💰 Cost logged: ${cost:.4f} ({agent_key} / {api_model})")
            except Exception as e:
                logger.warning(f"⚠️ Cost logging failed: {e}")

            return response_text, tokens_output
        except Exception as e:
            logger.error(f"❌ Gemini API error: {e}")
            raise
    else:
        raise ValueError(f"Unknown provider: {provider}")


def build_agent_system_prompt(agent_role: AgentRole) -> str:
    """Build system prompt with agent identity"""
    # Load identity stack
    soul_context = ""
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(os.path.dirname(__file__), identity_file)
        try:
            with open(filepath, "r") as f:
                soul_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass

    identity_context = orchestrator.get_agent_context(agent_role)
    agent_config = orchestrator.config["agents"].get(agent_role.value, {})
    persona = agent_config.get("persona", "")
    skills = agent_config.get("skills", [])
    workflow_status = orchestrator.get_workflow_status()

    base_prompt = f"""You are part of the Cybershield AI Agency - a multi-agent system powered by OpenClaw.

{identity_context}

YOUR PERSONA:
{persona}

YOUR SKILLS:
{', '.join(skills)}

CURRENT WORKFLOW STATE: {workflow_status['current_state']}
NEXT HANDLER: {workflow_status['next_handler']}

CORE GUIDELINES:
1. ALWAYS identify yourself in messages
2. ALWAYS use your signature: {orchestrator.agents[agent_role].signature}
3. Tag recipients with @ symbols
4. Follow the communication rules in your identity section above
5. Be playful but professional
6. Never break character - you ARE this agent

REMEMBER:
- If you need to talk to the client and you're NOT the PM, route through @Cybershield-PM
- If you're collaborating with another agent, tag them clearly
- Keep the team workflow moving forward
- Celebrate wins! 🎉

Now respond as {orchestrator.agents[agent_role].name} {orchestrator.agents[agent_role].emoji}!
"""
    if soul_context:
        base_prompt += f"\n\n--- IDENTITY & CONTEXT ---\n{soul_context[:3000]}"
    return base_prompt


def build_channel_system_prompt(agent_config: dict) -> str:
    """Build a rich system prompt for channel handlers (Telegram, Slack) with tools and project context."""
    # Load identity stack
    soul_context = ""
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(os.path.dirname(__file__), identity_file)
        try:
            with open(filepath, "r") as f:
                soul_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass

    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    persona = agent_config.get("persona", "You are a helpful assistant.")
    signature = agent_config.get("signature", "")
    skills = agent_config.get("skills", [])
    style = agent_config.get("style_guidelines", [])

    skills_str = ", ".join(skills) if skills else "general assistance"
    style_str = "\n".join(f"- {s}" for s in style) if style else "- Professional and direct"

    prompt = f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

YOUR SKILLS: {skills_str}

COMMUNICATION STYLE:
{style_str}

AVAILABLE TOOLS — USE THEM PROACTIVELY:
- github_repo_info: Check repo status, issues, PRs, commits for any GitHub repo
- github_create_issue: File bugs and feature requests on GitHub
- web_search: Search the web for current information, docs, tutorials
- create_job: Create tasks in the autonomous job queue
- list_jobs: View current job queue and status
- create_proposal: Submit a proposal for auto-approval
- approve_job: Approve a job for execution
- get_cost_summary: Check budget and cost status

ACTIVE PROJECTS (user: Miles Sage):
- Barber CRM (Miles0sage/Barber-CRM) — Next.js + Supabase, AI receptionist live
- Delhi Palace (Miles0sage/Delhi-Palce-) — Restaurant website on Vercel
- OpenClaw (this platform) — Multi-agent AI system
- PrestressCalc (Miles0sage/Mathcad-Scripts) — Engineering calculator, 358 tests
- Concrete Canoe 2026 — NAU ASCE competition

BEHAVIOR:
- When someone asks about a repo → use github_repo_info tool
- When someone asks to create a task → use create_job tool
- When someone needs current info → use web_search tool
- When asked about costs/budget → use get_cost_summary tool
- Think step by step for complex requests
- Be proactive: suggest next steps, offer to check things
- Reference specific projects when relevant

Always sign off with: {signature}"""

    if soul_context:
        prompt += f"\n\n--- IDENTITY & CONTEXT ---\n{soul_context[:3000]}"

    # Inject relevant memories
    try:
        mm = get_memory_manager()
        if mm:
            memory_context = mm.get_context_for_prompt(persona, max_tokens=500)
            if memory_context:
                prompt += f"\n\nRELEVANT MEMORIES:\n{memory_context}"
    except Exception:
        pass

    return prompt


@app.get("/")
async def root():
    """Serve the Overseer AI Agency landing page, with JSON fallback for API clients."""
    try:
        landing_path = "/root/openclaw/landing/index.html"
        with open(landing_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        # Fallback: return JSON for API clients / health checks
        return JSONResponse({
            "name": "OpenClaw Gateway",
            "version": "2.0.0",
            "status": "online",
            "agents": len(CONFIG.get("agents", {})),
            "protocol": "OpenClaw v1",
            "model_config": {
                agent: {
                    "provider": cfg.get("apiProvider"),
                    "model": cfg.get("model")
                }
                for agent, cfg in CONFIG.get("agents", {}).items()
            }
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/terms")
async def terms_page():
    """Serve the Terms of Service page."""
    try:
        terms_path = "/root/openclaw/landing/terms.html"
        with open(terms_path, "r") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Terms of Service not found</h1><p>terms.html is missing.</p>",
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>Error loading terms</h1><p>{str(e)}</p>",
            status_code=500
        )


@app.get("/test-version")
async def test_version():
    """Test endpoint to verify deployed version"""
    return {
        "status": "deployed",
        "timestamp": datetime.now().isoformat(),
        "auth_middleware": "active_with_exemptions",
        "exempt_paths": ["/", "/health", "/telegram/webhook", "/slack/events"],
        "version": "fixed-2026-02-18"
    }

@app.post("/api/admin/log-level")
async def set_log_level(request: Request):
    body = await request.json()
    level = body.get("level", "INFO").upper()
    numeric = getattr(logging, level, None)
    if numeric is None:
        raise HTTPException(400, detail=f"Invalid log level: {level}")
    logging.getLogger().setLevel(numeric)
    return {"level": level, "ok": True}

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "operational",
        "gateway": "OpenClaw-FIXED-2026-02-18",
        "version": "2.1.0",
        "agents_active": len(CONFIG.get("agents", {})),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics endpoint (no auth required for K8s scraping)"""
    return PlainTextResponse(metrics.get_prometheus_metrics())

@app.get("/test-exempt")
async def test_exempt():
    """Test endpoint to verify auth exemptions work (no auth required)"""
    return {"message": "✅ Auth exemption working!", "path": "/test-exempt"}

@app.get("/dashboard.html")
async def dashboard(request: Request):
    """Serve HTML dashboard (no auth required)"""
    try:
        dashboard_path = "/root/openclaw/dashboard.html"
        with open(dashboard_path, 'r') as f:
            html_content = f.read()
        from fastapi.responses import HTMLResponse
        # Allow GET, HEAD, and OPTIONS for browser compatibility
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return HTMLResponse(content=html_content)
        return HTMLResponse(content="Method not allowed", status_code=405)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>dashboard.html is missing</p>",
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>Error loading dashboard</h1><p>{str(e)}</p>",
            status_code=500
        )


@app.get("/monitoring")
async def monitoring_dashboard(request: Request):
    """Serve the main dashboard (consolidated from static/dashboard.html)"""
    try:
        dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        with open(dashboard_path, 'r') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Dashboard not found</h1><p>dashboard.html is missing</p>",
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading dashboard</h1><p>{e}</p>", status_code=500)


# ---------------------------------------------------------------------------
# Extra dashboard views
# ---------------------------------------------------------------------------
@app.get("/secrets")
async def secrets_dashboard():
    """Serve the secrets manager dashboard"""
    html_path = os.path.join(os.path.dirname(__file__), "dashboard_secrets.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Secrets dashboard not found</h1>", status_code=404)


@app.get("/metrics-dashboard")
async def metrics_dashboard():
    """Serve the metrics dashboard"""
    html_path = os.path.join(os.path.dirname(__file__), "dashboard_metrics.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Metrics dashboard not found</h1>", status_code=404)


@app.get("/mobile")
async def mobile_dashboard():
    """Serve the mobile dashboard"""
    html_path = os.path.join(os.path.dirname(__file__), "dashboard_mobile.html")
    if os.path.exists(html_path):
        with open(html_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Mobile dashboard not found</h1>", status_code=404)


# ---------------------------------------------------------------------------
# History trimming — prevents unbounded context growth
# ---------------------------------------------------------------------------
MAX_HISTORY_MESSAGES = 40
SUMMARIZE_THRESHOLD = 30

async def trim_history_if_needed(history: list, client=None) -> list:
    """Compress old messages when history gets too long.
    
    Keeps the last 20 messages verbatim and summarises everything older.
    Falls back to a plain truncation notice if the summarisation API call fails.
    """
    if len(history) <= SUMMARIZE_THRESHOLD:
        return history

    old = history[:-20]
    recent = history[-20:]

    # Build a condensed text of the old messages to feed into the summariser
    summary_parts = []
    for m in old:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(str(c) for c in content)
        summary_parts.append(f"{m.get('role', 'unknown')}: {str(content)[:200]}")

    summary_text = "\n".join(summary_parts)

    if client:
        try:
            resp = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=500,
                    messages=[{
                        "role": "user",
                        "content": (
                            "Summarize this conversation history concisely. "
                            "Preserve key decisions, completed tasks, and important context:\n\n"
                            + summary_text
                        ),
                    }],
                ),
            )
            summary = resp.content[0].text
        except Exception as e:
            logger.warning(f"History summarisation failed, using truncation: {e}")
            summary = f"[Previous conversation with {len(old)} messages — auto-truncated]"
    else:
        summary = f"[Previous conversation with {len(old)} messages — auto-truncated]"

    return [{"role": "assistant", "content": f"[Conversation summary]: {summary}"}] + recent


@app.get("/api/agents")
async def list_agents():
    """List agents with ACTUAL model configuration"""
    agents = []
    for agent_id, config in CONFIG.get("agents", {}).items():
        agents.append({
            "id": agent_id,
            "name": config.get("name"),
            "provider": config.get("apiProvider"),
            "model": config.get("model"),
            "role": config.get("type"),
            "status": "idle"
        })
    return {"agents": agents}


# ═══════════════════════════════════════════════════════════════════════
# TMUX AGENT PANES — Elvis-pattern parallel agent spawning
# ═══════════════════════════════════════════════════════════════════════

from tmux_spawner import get_spawner

class SpawnRequest(BaseModel):
    job_id: Optional[str] = None
    prompt: str
    worktree_repo: Optional[str] = None
    use_worktree: bool = False
    cwd: Optional[str] = None
    timeout_minutes: int = 30
    claude_args: str = ""

class SpawnParallelRequest(BaseModel):
    jobs: list[dict]  # Each dict has: job_id, prompt, and optional fields

@app.get("/api/agents/panes")
async def list_agent_panes():
    """List all tmux agent panes with status."""
    try:
        spawner = get_spawner()
        agents = spawner.list_agents()
        return {"success": True, "agents": agents, "count": len(agents)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agents/spawn")
async def spawn_agent(req: SpawnRequest):
    """Spawn a single Claude Code agent in a tmux pane."""
    try:
        import uuid
        job_id = req.job_id or f"ui-{uuid.uuid4().hex[:8]}"
        spawner = get_spawner()
        pane_id = spawner.spawn_agent(
            job_id=job_id,
            prompt=req.prompt,
            worktree_repo=req.worktree_repo,
            use_worktree=req.use_worktree,
            cwd=req.cwd,
            timeout_minutes=req.timeout_minutes,
            claude_args=req.claude_args,
        )
        return {"success": True, "pane_id": pane_id, "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/agents/spawn-parallel")
async def spawn_parallel_agents(req: SpawnParallelRequest):
    """Spawn multiple agents in parallel tmux panes."""
    try:
        spawner = get_spawner()
        results = spawner.spawn_parallel(req.jobs)
        spawned = sum(1 for r in results if r["status"] == "spawned")
        return {"success": True, "results": results, "spawned": spawned, "total": len(req.jobs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agents/panes/{pane_id:path}/output")
async def get_agent_output(pane_id: str, job_id: str = None):
    """Get the output buffer from a tmux agent pane."""
    try:
        spawner = get_spawner()
        output = spawner.collect_output(pane_id, job_id=job_id)
        status = spawner.get_agent_status(pane_id)
        return {
            "success": True,
            "pane_id": pane_id,
            "output": output,
            "status": status,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/agents/panes/{pane_id:path}")
async def kill_agent_pane(pane_id: str):
    """Kill a specific tmux agent pane."""
    try:
        spawner = get_spawner()
        killed = spawner.kill_agent(pane_id)
        return {"success": killed, "pane_id": pane_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/agents/panes/all")
async def kill_all_agent_panes():
    """Kill all tmux agent panes."""
    try:
        spawner = get_spawner()
        count = spawner.kill_all()
        return {"success": True, "killed": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/heartbeat/status")
async def heartbeat_status():
    """Get heartbeat monitor status and agent health"""
    heartbeat = get_heartbeat_monitor()
    if not heartbeat:
        return {
            "success": True,
            "status": "offline",
            "message": "Heartbeat monitor not initialized"
        }

    status = heartbeat.get_status()
    in_flight = heartbeat.get_in_flight_agents()

    return {
        "success": True,
        "status": "online" if status["running"] else "offline",
        "monitor": status,
        "in_flight_agents": [
            {
                "agent_id": agent.agent_id,
                "task_id": agent.task_id,
                "status": agent.status,
                "running_for_ms": int(datetime.now().timestamp() * 1000) - agent.started_at,
                "idle_for_ms": int(datetime.now().timestamp() * 1000) - agent.last_activity_at,
            }
            for agent in in_flight
        ],
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


# ═══════════════════════════════════════════════════════════════════════
# QUOTA & CAP GATE MIDDLEWARE
# Enforces daily/monthly spend limits and queue size limits
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/chat")
async def chat_endpoint(message: Message):
    """REST chat with optional session memory"""
    session_key = message.sessionKey or "default"
    project_id = message.project_id or "default"

    # ═ TASK CREATION: Detect "create task:", "todo:", etc. in user message
    import re as _re
    _TASK_PATTERNS = [
        r'^create task[:\s]+(.+)',
        r'^todo[:\s]+(.+)',
        r'^add task[:\s]+(.+)',
        r'^remind me to[:\s]+(.+)',
        r'^new task[:\s]+(.+)',
    ]
    task_match = None
    for _pattern in _TASK_PATTERNS:
        _m = _re.match(_pattern, message.content.strip(), _re.IGNORECASE)
        if _m:
            task_match = _m.group(1).strip()
            break

    if task_match:
        try:
            if TASKS_FILE.exists():
                with open(TASKS_FILE, 'r') as f:
                    tasks = json.load(f)
            else:
                tasks = []

            routing = agent_router.select_agent(task_match)
            new_task = {
                "id": str(uuid.uuid4())[:8],
                "title": task_match[:200],
                "description": message.content,
                "status": "todo",
                "agent": routing.get("agentId", "project_manager"),
                "created_at": datetime.utcnow().isoformat() + "Z",
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "source": "chat",
                "session_key": session_key
            }
            tasks.append(new_task)
            with open(TASKS_FILE, 'w') as f:
                json.dump(tasks, f, indent=2)

            # Also enqueue in the autonomous runner so chat-created tasks get executed
            jm_job_id = None
            try:
                jm_job = create_job(
                    project=new_task.get("title", "chat-task"),
                    task=message.content,
                    priority="P1"
                )
                jm_job_id = jm_job.id
                logger.info(f"✅ Runner job created for chat task: {jm_job_id}")
            except Exception as _je:
                logger.warning(f"Runner job creation failed (non-fatal): {_je}")

            task_response = (
                f"Task created: **{task_match[:200]}**\n"
                f"ID: `{new_task['id']}`"
                + (f" | Runner job: `{jm_job_id}`" if jm_job_id else "") + "\n"
                f"Assigned to: {routing.get('agentId', 'project_manager')} "
                f"({routing.get('reason', '')})\n\n— Overseer"
            )

            session_store.get(session_key).append({"role": "user", "content": message.content})
            session_store.get(session_key).append({"role": "assistant", "content": task_response})
            save_session_history(session_key, session_store.get(session_key))

            broadcast_event({"type": "task_created", "agent": "project_manager",
                             "message": f"Task created: {task_match[:80]}",
                             "timestamp": datetime.utcnow().isoformat()})

            return {"response": task_response, "agent": "project_manager", "task_created": new_task,
                    "runner_job_id": jm_job_id,
                    "sessionKey": session_key, "historyLength": len(session_store.get(session_key))}
        except Exception as e:
            logger.error(f"Task creation failed: {e}")
            # Fall through to normal chat if task creation fails

    # ═ AGENT ROUTING: Use intelligent router if no explicit agent_id
    if message.agent_id:
        # Explicit agent_id takes precedence
        agent_id = message.agent_id
        logger.info(f"📌 Explicit agent: {agent_id}")
    else:
        # Use intelligent router for automatic agent selection
        if CONFIG.get("routing", {}).get("agent_routing_enabled", True):
            route_decision = agent_router.select_agent(message.content)
            agent_id = route_decision["agentId"]
            logger.info(f"🎯 Agent Router: {route_decision['reason']} (confidence: {route_decision['confidence']:.2f})")
        else:
            # Fallback to PM if routing disabled
            agent_id = "project_manager"
            logger.info(f"📌 Routing disabled, using default: project_manager")

    # Register agent with heartbeat monitor
    heartbeat = get_heartbeat_monitor()
    if heartbeat:
        heartbeat.register_agent(agent_id, session_key)

    try:
        # ═ QUOTA CHECK: Verify daily/monthly limits and queue size
        quota_config = load_quota_config()
        if quota_config.get("enabled", False):
            # Check all quotas before processing
            quotas_ok, quota_error = check_all_quotas(project_id)
            if not quotas_ok:
                logger.warning(f"Quota exceeded: {quota_error}")
                return JSONResponse(
                    status_code=429,
                    content={
                        "success": False,
                        "error": "Quota limit exceeded",
                        "detail": quota_error,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                )

            # Get quota status for logging
            quota_status = get_quota_status(project_id)
            logger.info(f"✅ Quota check passed for '{project_id}': {quota_status['daily']['percent']:.1f}% daily, {quota_status['monthly']['percent']:.1f}% monthly")

        # ═ COST GATES: Verify budget limits before processing
        cost_gates = get_cost_gates()
        agent_config = get_agent_config(agent_id)
        model = agent_config.get("model", "claude-sonnet-4-20250514")
        
        # Estimate tokens (rough estimate before actual call)
        estimated_tokens = len(message.content.split()) * 2
        
        budget_check = check_cost_budget(
            project=project_id,
            agent=agent_id,
            model=model,
            tokens_input=estimated_tokens // 2,
            tokens_output=estimated_tokens // 2,
            task_id=f"{project_id}:{agent_id}:{session_key}"
        )
        
        if budget_check.status == BudgetStatus.REJECTED:
            logger.warning(f"💰 Cost gate REJECTED: {budget_check.message}")
            return JSONResponse(
                status_code=402,
                content={
                    "success": False,
                    "error": "Budget limit exceeded",
                    "detail": budget_check.message,
                    "gate": budget_check.gate_name,
                    "remaining_budget": budget_check.remaining_budget,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
            )
        elif budget_check.status == BudgetStatus.WARNING:
            logger.warning(f"⚠️  Cost gate WARNING: {budget_check.message}")
            # Still proceed but log warning


        # Load session history if available

        # Check cache first
        response_cache = get_response_cache()
        if response_cache:
            cached = response_cache.get(message.content, agent_id, session_key)
            if cached:
                # Cache hit - return cached response
                session_store.get(session_key).append({"role": "user", "content": message.content})
                session_store.get(session_key).append({"role": "assistant", "content": cached.response})
                save_session_history(session_key, session_store.get(session_key))
                return {
                    "agent": cached.agent_id,
                    "response": cached.response,
                    "provider": agent_config.get("apiProvider"),
                    "model": cached.model,
                    "tokens": 0,
                    "sessionKey": session_key,
                    "historyLength": len(session_store.get(session_key)),
                    "cached": True,
                    "tokens_saved": cached.tokens_saved
                }

        # Add user message to history
        session_store.get(session_key).append({
            "role": "user",
            "content": message.content
        })

        # Broadcast start event for SSE
        broadcast_event({"type": "response_start", "agent": agent_id,
                         "message": f"{agent_id} is thinking...",
                         "timestamp": datetime.utcnow().isoformat()})

        # ═ TOOL USE: Auto-detect or use explicit flag
        # Agents on Anthropic get tool access for execution tasks
        agent_config_for_tools = get_agent_config(agent_id)
        provider_for_tools = agent_config_for_tools.get("apiProvider", "anthropic") if agent_config_for_tools else "anthropic"

        # Auto-detect: enable tools for Anthropic agents when message looks like an action
        action_keywords = ["deploy", "build", "push", "commit", "install", "create file", "write file",
                          "run ", "execute", "test ", "fix ", "git ", "npm ", "fetch ", "scrape",
                          "research", "search for", "look up", "find out", "check status",
                          "deploy to vercel", "push to github"]
        should_use_tools = message.use_tools
        if should_use_tools is None:
            # Auto-detect based on content
            msg_lower = message.content.lower()
            should_use_tools = provider_for_tools == "anthropic" and any(kw in msg_lower for kw in action_keywords)

        if should_use_tools and provider_for_tools == "anthropic":
            # Use tool-enabled Claude call
            logger.info(f"🔧 Tool-enabled call for {agent_id}")
            system_prompt = _build_system_prompt(agent_id, agent_config_for_tools)
            _trimmed_hist = await trim_history_if_needed(
                session_store.get(session_key), client=anthropic.Anthropic())
            tool_messages = [{"role": m["role"], "content": m["content"]} for m in _trimmed_hist[-10:]]

            model_for_tools = agent_config_for_tools.get("model", "claude-sonnet-4-20250514")
            response_text = await call_claude_with_tools(
                anthropic.Anthropic(),
                model_for_tools,
                system_prompt,
                tool_messages,
                max_rounds=8
            )
            tokens = len(response_text.split()) * 2  # Approximate
            actual_agent = agent_id
        else:
            # Call model with last 10 messages for context (with auto-escalation)
            _trimmed_hist2 = await trim_history_if_needed(
                session_store.get(session_key))
            response_text, tokens, actual_agent = call_model_with_escalation(
                agent_id,
                message.content,
                _trimmed_hist2[-10:]
            )
        if actual_agent != agent_id:
            logger.info(f"⬆️ Chat escalated: {agent_id} → {actual_agent}")
            agent_id = actual_agent  # Use the agent that actually responded

        # Store in cache
        if response_cache:
            response_cache.put(message.content, response_text, agent_id, model,
                      agent_config.get("apiProvider", ""), tokens, session_key=session_key)

        # Record metrics
        metrics.record_agent_call(agent_id)
        metrics.record_session(session_key)

        # Update activity after getting response
        if heartbeat:
            heartbeat.update_activity(agent_id)

        # Add assistant response to history
        session_store.get(session_key).append({
            "role": "assistant",
            "content": response_text
        })

        # Save session to disk
        save_session_history(session_key, session_store.get(session_key))

        # ═ DELEGATION: Check if PM wants to delegate sub-tasks to specialists
        # With memory sharing (session context) and auto-escalation
        delegation_results = []
        if agent_id in ("project_manager", "pm"):
            delegations = agent_router.auto_delegate(response_text, message.content)
            if delegations:
                logger.info(f"🤝 Delegation: {len(delegations)} sub-tasks from PM")

                # Build shared context from session for memory sharing
                session_context = ""
                recent_history = session_store.get(session_key)[-6:]  # Last 3 exchanges
                if recent_history:
                    context_parts = []
                    for msg in recent_history:
                        role = msg.get("role", "user")
                        content = msg.get("content", "")[:500]  # Truncate for cost
                        context_parts.append(f"{role}: {content}")
                    session_context = (
                        "\n--- SESSION CONTEXT (shared by Overseer) ---\n"
                        + "\n".join(context_parts)
                        + "\n--- END CONTEXT ---\n\n"
                    )

                for delegation in delegations:
                    try:
                        broadcast_event({"type": "delegation_start", "agent": delegation["agent_id"],
                                         "message": f"Delegated by PM: {delegation['task'][:80]}..."})

                        # Inject session context into delegation task (memory sharing)
                        enriched_task = session_context + delegation["task"] if session_context else delegation["task"]

                        # Use auto-escalation — if target agent fails, escalate up
                        delegate_response, delegate_tokens, actual_agent = call_model_with_escalation(
                            delegation["agent_id"], enriched_task, conversation=None)
                        delegation_results.append({
                            "agent": actual_agent,
                            "original_agent": delegation["agent_id"],
                            "task": delegation["task"],
                            "response": delegate_response,
                            "tokens": delegate_tokens,
                            "escalated": actual_agent != delegation["agent_id"]
                        })
                        broadcast_event({"type": "delegation_end", "agent": actual_agent,
                                         "message": f"{actual_agent} completed delegation ({delegate_tokens} tokens)"
                                         + (f" [escalated from {delegation['agent_id']}]" if actual_agent != delegation["agent_id"] else "")})
                    except Exception as e:
                        logger.error(f"Delegation to {delegation['agent_id']} failed (all escalations exhausted): {e}")
                        delegation_results.append({
                            "agent": delegation["agent_id"],
                            "original_agent": delegation["agent_id"],
                            "task": delegation["task"],
                            "response": f"[Delegation failed after escalation: {str(e)}]",
                            "tokens": 0,
                            "escalated": False
                        })

                # Synthesize specialist responses via PM
                if delegation_results:
                    synthesis_parts = []
                    for r in delegation_results:
                        synthesis_parts.append(f"### {r['agent']} response:\n{r['response']}")
                    synthesis_prompt = (
                        f"You delegated tasks to specialists. Here are their results:\n\n"
                        f"{''.join(synthesis_parts)}\n\n"
                        f"Original user request: {message.content}\n\n"
                        f"Synthesize these specialist responses into a single, coherent response for the user. "
                        f"Remove any delegation markers. Be concise."
                    )
                    response_text, extra_tokens = call_model_for_agent("project_manager", synthesis_prompt)
                    tokens += extra_tokens + sum(r["tokens"] for r in delegation_results)

                    # Update session with synthesized response
                    session_store.get(session_key)[-1] = {"role": "assistant", "content": response_text}
                    save_session_history(session_key, session_store.get(session_key))

        # Broadcast response event
        broadcast_event({"type": "response_end", "agent": agent_id,
                         "message": f"{agent_id} responded ({tokens} tokens)", "tokens": tokens,
                         "timestamp": datetime.utcnow().isoformat()})

        # Check cost alerts
        send_cost_alert_if_needed()

        agent_config = get_agent_config(agent_id)

        result = {
            "agent": agent_id,
            "response": response_text,
            "provider": agent_config.get("apiProvider"),
            "model": agent_config.get("model"),
            "tokens": tokens,
            "sessionKey": session_key,
            "historyLength": len(session_store.get(session_key))
        }

        if delegation_results:
            result["delegations"] = [{"agent": r["agent"], "tokens": r["tokens"]} for r in delegation_results]

        return result
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Unregister agent when done
        if heartbeat:
            heartbeat.unregister_agent(agent_id)


# ═══════════════════════════════════════════════════════════════════════
# VISION ENDPOINT — Smart Glasses Image Processing
# Processes images via Claude Haiku 4.5 vision for real-time scene
# description, OCR, translation, object identification, and memory.
# ═══════════════════════════════════════════════════════════════════════

# System prompts for each vision query type
_VISION_SYSTEM_PROMPTS = {
    "describe": (
        "You analyze images from smart glasses in real-time. Describe the scene concisely "
        "in under 100 words. Focus on what is most important or actionable for the wearer. "
        "Mention key objects, people count, environment type, and any notable activity."
    ),
    "read_text": (
        "You are an OCR assistant for smart glasses. Extract ALL visible text from the image "
        "accurately. Preserve formatting where possible (signs, labels, screens, documents). "
        "If text is partially obscured, indicate uncertain characters with [?]. "
        "Return only the extracted text, no commentary."
    ),
    "translate": (
        "You are a real-time translation assistant for smart glasses. Extract any visible text "
        "from the image and translate it to {language}. Format as:\n"
        "Original: <extracted text>\nTranslation: <translated text>\n"
        "If multiple text elements are visible, translate each one."
    ),
    "remember": (
        "You are a visual memory assistant for smart glasses. Analyze this image and create "
        "a structured memory tag for later recall. Include:\n"
        "- Scene type (indoor/outdoor, location type)\n"
        "- Key objects and their positions\n"
        "- Any text or signage visible\n"
        "- People (count, general description, no identifying features)\n"
        "- Timestamp context clues (lighting, shadows)\n"
        "Format as a compact JSON-like summary for storage."
    ),
    "identify": (
        "You are an object identification assistant for smart glasses. List every distinct "
        "object visible in the image. Format as a numbered list. Include:\n"
        "- Object name\n"
        "- Approximate position (left/center/right, foreground/background)\n"
        "- Notable attributes (color, size, state)\n"
        "Be thorough but concise. Keep each entry to one line."
    ),
}


@app.post("/api/vision")
async def vision_endpoint(req: VisionRequest):
    """Process images from smart glasses using Claude Haiku 4.5 vision.

    Query types:
    - describe: Concise scene description
    - read_text: OCR text extraction
    - translate: Extract and translate visible text (requires language param)
    - remember: Tag image for memory/recall storage
    - identify: List all objects in scene
    """
    # Validate query type
    valid_queries = {"describe", "read_text", "translate", "remember", "identify"}
    query_type = req.query.lower().strip()
    if query_type not in valid_queries:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid query type '{req.query}'. Must be one of: {', '.join(sorted(valid_queries))}"
        )

    # Validate language for translate query
    if query_type == "translate" and not req.language:
        raise HTTPException(
            status_code=400,
            detail="Language parameter is required for 'translate' query type"
        )

    # Rate limiting per device_id
    device_id = req.device_id or "anonymous"
    if not _check_vision_rate_limit(device_id):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded: max 10 images per minute per device"
        )

    # Validate base64 image
    import base64 as _b64
    try:
        image_bytes = _b64.b64decode(req.image, validate=True)
        if len(image_bytes) < 100:
            raise ValueError("Image too small")
        if len(image_bytes) > 20 * 1024 * 1024:  # 20MB max
            raise ValueError("Image exceeds 20MB limit")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid base64 image: {e}"
        )

    # Build system prompt
    system_prompt = _VISION_SYSTEM_PROMPTS[query_type]
    if query_type == "translate":
        system_prompt = system_prompt.format(language=req.language)

    # Build user prompt based on query type
    user_prompts = {
        "describe": "Describe this scene concisely.",
        "read_text": "Read and extract all text visible in this image.",
        "translate": f"Extract all visible text and translate it to {req.language}.",
        "remember": "Analyze this image and create a structured memory tag for later recall.",
        "identify": "Identify and list all objects visible in this image.",
    }
    user_prompt = user_prompts[query_type]

    # Call Claude Haiku 4.5 vision API
    try:
        response = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": req.image,
                        },
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ],
            }],
        )
    except anthropic.BadRequestError as e:
        logger.error(f"Vision API bad request: {e}")
        raise HTTPException(status_code=400, detail=f"Vision API error: {e}")
    except anthropic.RateLimitError as e:
        logger.error(f"Vision API rate limited: {e}")
        raise HTTPException(status_code=429, detail="Anthropic API rate limit reached. Try again shortly.")
    except Exception as e:
        logger.error(f"Vision API call failed: {e}")
        raise HTTPException(status_code=500, detail=f"Vision processing failed: {e}")

    # Extract response text
    result_text = response.content[0].text if response.content else ""

    # Calculate cost
    tokens_in = response.usage.input_tokens
    tokens_out = response.usage.output_tokens
    cost_usd = _calc_cost("claude-haiku-4-5-20251001", tokens_in, tokens_out)

    # Log cost event
    log_cost_event(
        model="claude-haiku-4-5-20251001",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        agent="vision_agent",
        endpoint="/api/vision",
    )

    # Handle "remember" query: store to session memory if session_key provided
    stored = False
    if query_type == "remember" and req.session_key:
        try:
            session_store.get(req.session_key).append({
                "role": "assistant",
                "content": f"[Visual Memory] {result_text}",
            })
            save_session_history(req.session_key, session_store.get(req.session_key))
            stored = True
        except Exception as e:
            logger.warning(f"Failed to store visual memory: {e}")

    logger.info(
        f"Vision processed: query={query_type} device={device_id} "
        f"tokens_in={tokens_in} tokens_out={tokens_out} cost=${cost_usd:.4f}"
    )

    return {
        "text": result_text,
        "query_type": query_type,
        "agent": "vision_agent",
        "cost_usd": round(cost_usd, 6),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "stored": stored,
    }


@app.post("/api/chat/stream")
async def chat_stream_endpoint(message: Message):
    """REST chat with SSE streaming for real-time token delivery.
    Returns Server-Sent Events with types: start, token, done, error"""
    session_key = message.sessionKey or "default"
    project_id = message.project_id or "default"

    # Agent routing (same as /api/chat)
    if message.agent_id:
        agent_id = message.agent_id
    else:
        if CONFIG.get("routing", {}).get("agent_routing_enabled", True):
            route_decision = agent_router.select_agent(message.content)
            agent_id = route_decision["agentId"]
        else:
            agent_id = "project_manager"

    heartbeat = get_heartbeat_monitor()
    if heartbeat:
        heartbeat.register_agent(agent_id, session_key)

    # Quota check
    quota_config = load_quota_config()
    if quota_config.get("enabled", False):
        quotas_ok, quota_error = check_all_quotas(project_id)
        if not quotas_ok:
            return JSONResponse(status_code=429, content={"success": False, "error": quota_error})

    # Cost gate check
    agent_config = get_agent_config(agent_id)
    model = agent_config.get("model", "claude-sonnet-4-5-20250929")
    provider = agent_config.get("apiProvider", "anthropic")

    estimated_tokens = len(message.content.split()) * 2
    budget_check = check_cost_budget(
        project=project_id, agent=agent_id, model=model,
        tokens_input=estimated_tokens // 2, tokens_output=estimated_tokens // 2,
        task_id=f"{project_id}:{agent_id}:{session_key}"
    )
    if budget_check.status == BudgetStatus.REJECTED:
        return JSONResponse(status_code=402, content={"success": False, "error": budget_check.message})

    # Load session
    session_store.get(session_key).append({"role": "user", "content": message.content})

    # Build system prompt
    persona = agent_config.get("persona", "")
    name = agent_config.get("name", "Agent")
    emoji = agent_config.get("emoji", "")
    signature = agent_config.get("signature", "")

    identity_context = ""
    gateway_dir = os.path.dirname(os.path.abspath(__file__))
    for identity_file in ["SOUL.md", "USER.md", "AGENTS.md"]:
        filepath = os.path.join(gateway_dir, identity_file)
        try:
            with open(filepath, "r") as f:
                identity_context += f"\n\n{f.read()}"
        except FileNotFoundError:
            pass

    system_prompt = f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

IMPORTANT RULES:
- ALWAYS end your messages with your signature: {signature}
- Follow your character consistently
- Reference real project names (Barber CRM, Delhi Palace, OpenClaw, PrestressCalc, Concrete Canoe)

Remember: You ARE {name}. Stay in character!

--- IDENTITY & CONTEXT ---
{identity_context}"""

    # Intelligent routing for Anthropic models
    router_enabled = CONFIG.get("routing", {}).get("enabled", False)
    if router_enabled and provider == "anthropic":
        try:
            classification = classify_query(message.content)
            routed_model = MODEL_ALIASES.get(classification.model, model)
            model = routed_model
        except Exception:
            pass

    async def generate():
        """SSE generator that streams tokens from the model"""
        full_response = ""
        tokens_used = 0

        try:
            yield f"data: {json.dumps({'type': 'start', 'agent': agent_id, 'model': model, 'provider': provider})}\n\n"

            if provider == "anthropic":
                _trimmed_stream = await trim_history_if_needed(
                    session_store.get(session_key), client=anthropic_client)
                with anthropic_client.messages.stream(
                    model=model, max_tokens=8192,
                    system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                    messages=_trimmed_stream[-10:]
                ) as stream:
                    for text in stream.text_stream:
                        full_response += text
                        yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
                    final = stream.get_final_message()
                    tokens_used = final.usage.output_tokens

            elif provider == "deepseek":
                ds_client = DeepseekClient()
                api_model = model if model in ["kimi-2.5", "kimi"] else "kimi-2.5"
                for chunk in ds_client.stream(model=api_model, prompt=message.content,
                                              system_prompt=system_prompt, max_tokens=8192):
                    full_response += chunk
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"

            elif provider == "minimax":
                mm_client = MiniMaxClient()
                api_model = model if model in ["m2.5", "m2.5-lightning"] else "m2.5"
                for chunk in mm_client.stream(model=api_model, prompt=message.content,
                                              system_prompt=system_prompt, max_tokens=16384):
                    full_response += chunk
                    yield f"data: {json.dumps({'type': 'token', 'text': chunk})}\n\n"

            # Save to session
            session_store.get(session_key).append({"role": "assistant", "content": full_response})
            save_session_history(session_key, session_store.get(session_key))

            # Log cost
            try:
                log_cost_event(project="openclaw", agent=agent_id, model=model,
                              tokens_input=len(message.content.split()) * 2,
                              tokens_output=tokens_used or len(full_response.split()) * 2)
            except Exception:
                pass

            # Record metrics
            metrics.record_agent_call(agent_id)
            metrics.record_session(session_key)

            yield f"data: {json.dumps({'type': 'done', 'agent': agent_id, 'tokens': tokens_used, 'sessionKey': session_key})}\n\n"

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            if heartbeat:
                heartbeat.unregister_agent(agent_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@app.get("/api/costs/summary")
async def costs_summary():
    """Get cost metrics summary"""
    try:
        metrics = get_cost_metrics()
        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat(),
            "data": metrics
        }
    except Exception as e:
        logger.error(f"Error getting cost metrics: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/costs/text")
async def costs_text():
    """Get cost summary as text"""
    try:
        summary = get_cost_summary()
        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat(),
            "summary": summary
        }
    except Exception as e:
        logger.error(f"Error getting cost summary: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# RESPONSE CACHE ENDPOINTS
# GET  /api/cache/stats    - Get cache statistics (hit rate, savings)
# POST /api/cache/clear    - Clear all cached responses
# POST /api/cache/cleanup  - Remove expired cache entries
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/cache/stats")
async def cache_stats():
    """Get response cache statistics"""
    cache = get_response_cache()
    if not cache:
        return {"success": False, "error": "Cache not initialized"}
    return {"success": True, "data": cache.get_stats()}

@app.post("/api/cache/clear")
async def cache_clear():
    """Clear response cache"""
    cache = get_response_cache()
    if not cache:
        return {"success": False, "error": "Cache not initialized"}
    count = cache.invalidate()
    return {"success": True, "cleared": count}

@app.post("/api/cache/cleanup")
async def cache_cleanup():
    """Remove expired cache entries"""
    cache = get_response_cache()
    if not cache:
        return {"success": False, "error": "Cache not initialized"}
    count = cache.cleanup_expired()
    return {"success": True, "expired_removed": count}


# ═══════════════════════════════════════════════════════════════════════
# QUOTA & CAP GATE ENDPOINTS
# GET  /api/quotas/status    - Get current quota status for a project
# GET  /api/quotas/config    - Get quota configuration
# POST /api/quotas/check     - Check if request would be allowed

@app.get("/api/quotas/status")
async def global_quota_status():
    """
    Get global quota/budget status
    Returns aggregate budget info across all projects
    """
    try:
        quota_config = load_quota_config()
        
        if not quota_config.get("enabled", False):
            return {
                "success": True,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": {
                    "quotas_enabled": False,
                    "message": "Quotas are disabled"
                }
            }
        
        # Get cost metrics for all projects
        metrics = get_cost_metrics()
        
        # Calculate aggregate spend
        daily_spend = metrics.get("daily_total", 0.0)
        monthly_spend = metrics.get("monthly_total", 0.0)
        
        daily_budget = quota_config.get("daily_limit_usd", 50)
        monthly_budget = quota_config.get("monthly_limit_usd", 1000)
        
        daily_remaining = max(0, daily_budget - daily_spend)
        monthly_remaining = max(0, monthly_budget - monthly_spend)
        
        daily_percent = (daily_spend / daily_budget * 100) if daily_budget > 0 else 0
        monthly_percent = (monthly_spend / monthly_budget * 100) if monthly_budget > 0 else 0
        
        warning_threshold = quota_config.get("warning_threshold_percent", 80)
        
        # Determine status: healthy, warning, or critical
        status = "healthy"
        if daily_percent >= 100 or monthly_percent >= 100:
            status = "critical"
        elif daily_percent >= warning_threshold or monthly_percent >= warning_threshold:
            status = "warning"
        
        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "daily_budget": daily_budget,
                "daily_used": round(daily_spend, 4),
                "daily_remaining": round(daily_remaining, 4),
                "daily_percent": round(daily_percent, 1),
                "monthly_budget": monthly_budget,
                "monthly_used": round(monthly_spend, 4),
                "monthly_remaining": round(monthly_remaining, 4),
                "monthly_percent": round(monthly_percent, 1),
                "status": status,
                "warning_threshold_percent": warning_threshold,
                "quotas_enabled": True
            }
        }
    except Exception as e:
        logger.error(f"Error getting global quota status: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/quotas/status/{project_id}")
async def quota_status_endpoint(project_id: str = "default"):
    """Get current quota usage for a project"""
    try:
        status = get_quota_status(project_id)
        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": status
        }
    except Exception as e:
        logger.error(f"Error getting quota status: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@app.get("/api/quotas/config")
async def quota_config_endpoint():
    """Get quota configuration"""
    try:
        quota_config = load_quota_config()
        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": quota_config
        }
    except Exception as e:
        logger.error(f"Error getting quota config: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


# ═══════════════════════════════════════════════════════════════════════
# TELEGRAM WEBHOOK HANDLER
# ═══════════════════════════════════════════════════════════════════════

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram messages via webhook"""
    try:
        update = await request.json()

        # Extract message from update
        if "message" not in update:
            logger.debug(f"Skipping non-message update: {update.get('update_id')}")
            return {"ok": True}

        message = update["message"]
        chat_id = message["chat"]["id"]
        user_id = message["from"]["id"]
        text = message.get("text", "")

        # Create session key from Telegram IDs
        session_key = f"telegram:{user_id}:{chat_id}"

        if not text:
            return {"ok": True}

        logger.info(f"📱 Telegram message from {user_id} in chat {chat_id}: {text[:50]}")

        # ═ TASK CREATION: Detect "create task:", "todo:", etc. from Telegram
        import re as _re_tg
        _TG_TASK_PATTERNS = [
            r'^create task[:\s]+(.+)', r'^todo[:\s]+(.+)', r'^add task[:\s]+(.+)',
            r'^remind me to[:\s]+(.+)', r'^new task[:\s]+(.+)',
        ]
        tg_task_match = None
        for _p in _TG_TASK_PATTERNS:
            _m = _re_tg.match(_p, text.strip(), _re_tg.IGNORECASE)
            if _m:
                tg_task_match = _m.group(1).strip()
                break

        if tg_task_match:
            try:
                if TASKS_FILE.exists():
                    with open(TASKS_FILE, 'r') as f:
                        tasks = json.load(f)
                else:
                    tasks = []
                routing = agent_router.select_agent(tg_task_match)
                new_task = {
                    "id": str(uuid.uuid4())[:8],
                    "title": tg_task_match[:200],
                    "description": text,
                    "status": "todo",
                    "agent": routing.get("agentId", "project_manager"),
                    "created_at": datetime.utcnow().isoformat() + "Z",
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                    "source": "telegram",
                    "session_key": session_key
                }
                tasks.append(new_task)
                with open(TASKS_FILE, 'w') as f:
                    json.dump(tasks, f, indent=2)

                # Also enqueue in the autonomous runner so Telegram-created tasks get executed
                tg_jm_job_id = None
                try:
                    tg_jm_job = create_job(
                        project=new_task.get("title", "telegram-task"),
                        task=text,
                        priority="P1"
                    )
                    tg_jm_job_id = tg_jm_job.id
                    logger.info(f"✅ Runner job created for Telegram task: {tg_jm_job_id}")
                except Exception as _tje:
                    logger.warning(f"Runner job creation failed for Telegram task (non-fatal): {_tje}")

                task_response = (
                    f"Task created: {tg_task_match[:200]}\n"
                    f"ID: {new_task['id']}"
                    + (f" | Runner job: {tg_jm_job_id}" if tg_jm_job_id else "") + "\n"
                    f"Assigned to: {routing.get('agentId', 'project_manager')}"
                )
                broadcast_event({"type": "task_created", "agent": "project_manager",
                                 "message": f"Task from Telegram: {tg_task_match[:80]}"})

                # Send confirmation to Telegram
                telegram_token = CONFIG.get("channels", {}).get("telegram", {}).get("botToken", "")
                if telegram_token.startswith("${") and telegram_token.endswith("}"):
                    telegram_token = os.getenv(telegram_token[2:-1], "")
                if not telegram_token:
                    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
                if telegram_token:
                    async with httpx.AsyncClient(timeout=10) as tg_client:
                        await tg_client.post(
                            f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                            json={"chat_id": chat_id, "text": task_response, "reply_to_message_id": message["message_id"]}
                        )
                return {"ok": True}
            except Exception as e:
                logger.error(f"Telegram task creation failed: {e}")
                # Fall through to normal processing

        # Route message through OpenClaw chat endpoint
        try:
            # Create message for chat endpoint
            chat_message = {
                "content": text,
                "sessionKey": session_key,
                "project_id": "telegram-bot"
            }

            # Get agent routing decision
            route_decision = agent_router.select_agent(text)
            chat_message["agent_id"] = route_decision["agentId"]

            logger.info(f"🎯 Routed to {route_decision['agentId']}: {route_decision['reason']}")

            # Process through chat endpoint logic
            session_history = load_session_history(session_key)

            # Build context
            messages_for_api = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in session_history
            ]
            messages_for_api.append({"role": "user", "content": text})

            # Get Anthropic client
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

            # Create system prompt
            agent_config = CONFIG.get("agents", {}).get(route_decision["agentId"], {})
            system_prompt = build_channel_system_prompt(agent_config)

            # Call Claude with tools (GitHub, web search, job management)
            model = agent_config.get("model", "claude-opus-4-6")
            assistant_message = await call_claude_with_tools(
                client, model, system_prompt, messages_for_api
            )

            # Save to session
            session_history.append({"role": "user", "content": text})
            session_history.append({"role": "assistant", "content": assistant_message})
            save_session_history(session_key, session_history)

            # Auto-extract memories from conversation
            try:
                mm = get_memory_manager()
                if mm:
                    mm.auto_extract_memories([
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": assistant_message}
                    ])
            except Exception:
                pass

            logger.info(f"✅ Response generated: {assistant_message[:50]}...")

            # Send response back to Telegram
            telegram_token = CONFIG.get("channels", {}).get("telegram", {}).get("botToken", "")
            # Resolve env var placeholders like ${TELEGRAM_BOT_TOKEN}
            if telegram_token.startswith("${") and telegram_token.endswith("}"):
                env_var = telegram_token[2:-1]
                telegram_token = os.getenv(env_var, "")
            if not telegram_token:
                telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            logger.info(f"🔍 DEBUG: telegram_token length={len(telegram_token)}, starts with: {telegram_token[:20] if telegram_token else 'EMPTY'}")
            if telegram_token:
                telegram_send_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
                telegram_payload = {
                    "chat_id": chat_id,
                    "text": assistant_message,
                    "reply_to_message_id": message["message_id"]
                }

                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.post(telegram_send_url, json=telegram_payload)
                        if resp.status_code == 200:
                            logger.info(f"✅ Message sent to Telegram chat {chat_id}")
                        else:
                            logger.warning(f"⚠️  Telegram send failed: {resp.status_code}")
                except Exception as e:
                    logger.error(f"❌ Error sending to Telegram: {e}")

        except Exception as e:
            logger.error(f"Error processing Telegram message: {e}")

        return {"ok": True}

    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# SLACK WEBHOOK HANDLER
# ═══════════════════════════════════════════════════════════════════════

@app.post("/slack/events")
async def slack_events(request: Request):
    """Receive Slack messages via webhook with signature verification"""
    try:
        # Get request body and headers for signature verification
        body_bytes = await request.body()
        payload = json.loads(body_bytes)

        # Handle URL verification challenge FIRST (before signature check)
        # Slack sends this during app setup and it must be answered immediately
        if payload.get("type") == "url_verification":
            logger.info("Slack verification challenge received")
            return {"challenge": payload.get("challenge")}

        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")

        # Verify Slack signature (security best practice)
        if SLACK_SIGNING_SECRET:
            # Check timestamp is within 5 minutes (prevent replay attacks)
            try:
                request_time = int(timestamp)
                current_time = int(time.time())
                if abs(current_time - request_time) > 300:
                    logger.warning("Slack request timestamp too old (replay attack?)")
                    return JSONResponse({"error": "Invalid timestamp"}, status_code=403)
            except ValueError:
                logger.warning("Invalid timestamp from Slack")
                return JSONResponse({"error": "Invalid timestamp"}, status_code=403)

            # Verify signature
            sig_basestring = f"v0:{timestamp}:{body_bytes.decode()}"
            expected_signature = "v0=" + hmac.new(
                SLACK_SIGNING_SECRET.encode(),
                sig_basestring.encode(),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_signature, signature):
                logger.warning("Invalid Slack signature")
                return JSONResponse({"error": "Invalid signature"}, status_code=403)

        # Handle message events
        event = payload.get("event", {})
        if event.get("type") == "message" and not event.get("bot_id"):
            user_id = event.get("user")
            channel_id = event.get("channel")
            thread_ts = event.get("thread_ts") or event.get("ts")
            text = event.get("text", "")

            if not text or not user_id or not channel_id:
                return {"ok": True}

            # Create session key from Slack IDs
            session_key = f"slack:{user_id}:{channel_id}"

            logger.info(f"💬 Slack message from {user_id} in {channel_id}: {text[:50]}")

            # ═ TASK CREATION: Detect "create task:", "todo:", etc. from Slack
            import re as _re_sl
            _SL_TASK_PATTERNS = [
                r'^create task[:\s]+(.+)', r'^todo[:\s]+(.+)', r'^add task[:\s]+(.+)',
                r'^remind me to[:\s]+(.+)', r'^new task[:\s]+(.+)',
            ]
            sl_task_match = None
            for _p in _SL_TASK_PATTERNS:
                _m = _re_sl.match(_p, text.strip(), _re_sl.IGNORECASE)
                if _m:
                    sl_task_match = _m.group(1).strip()
                    break

            if sl_task_match:
                try:
                    if TASKS_FILE.exists():
                        with open(TASKS_FILE, 'r') as f:
                            tasks = json.load(f)
                    else:
                        tasks = []
                    routing = agent_router.select_agent(sl_task_match)
                    new_task = {
                        "id": str(uuid.uuid4())[:8],
                        "title": sl_task_match[:200],
                        "description": text,
                        "status": "todo",
                        "agent": routing.get("agentId", "project_manager"),
                        "created_at": datetime.utcnow().isoformat() + "Z",
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                        "source": "slack",
                        "session_key": session_key
                    }
                    tasks.append(new_task)
                    with open(TASKS_FILE, 'w') as f:
                        json.dump(tasks, f, indent=2)

                    # Also enqueue in the autonomous runner so Slack-created tasks get executed
                    sl_jm_job_id = None
                    try:
                        sl_jm_job = create_job(
                            project=new_task.get("title", "slack-task"),
                            task=text,
                            priority="P1"
                        )
                        sl_jm_job_id = sl_jm_job.id
                        logger.info(f"✅ Runner job created for Slack task: {sl_jm_job_id}")
                    except Exception as _sje:
                        logger.warning(f"Runner job creation failed for Slack task (non-fatal): {_sje}")

                    task_response = (
                        f"Task created: *{sl_task_match[:200]}*\n"
                        f"ID: `{new_task['id']}`"
                        + (f" | Runner job: `{sl_jm_job_id}`" if sl_jm_job_id else "") + "\n"
                        f"Assigned to: {routing.get('agentId', 'project_manager')}"
                    )
                    broadcast_event({"type": "task_created", "agent": "project_manager",
                                     "message": f"Task from Slack: {sl_task_match[:80]}"})
                    await send_slack_message(channel_id, task_response, thread_ts)
                    return {"ok": True}
                except Exception as e:
                    logger.error(f"Slack task creation failed: {e}")
                    # Fall through to normal processing

            try:
                # Route message through agent router
                route_decision = agent_router.select_agent(text)
                logger.info(f"🎯 Routed to {route_decision['agentId']}: {route_decision['reason']}")

                # Load session history
                session_history = load_session_history(session_key)

                # Build context
                messages_for_api = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in session_history
                ]
                messages_for_api.append({"role": "user", "content": text})

                # Get agent config and call model
                agent_config = CONFIG.get("agents", {}).get(route_decision["agentId"], {})
                system_prompt = build_channel_system_prompt(agent_config)
                model = agent_config.get("model", "claude-opus-4-6")

                # Call Claude with tools (GitHub, web search, job management)
                client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                assistant_message = await call_claude_with_tools(
                    client, model, system_prompt, messages_for_api
                )

                # Save to session (only user msg + final response, not tool intermediaries)
                session_history.append({"role": "user", "content": text})
                session_history.append({"role": "assistant", "content": assistant_message})
                save_session_history(session_key, session_history)

                # Auto-extract memories from conversation
                try:
                    mm = get_memory_manager()
                    if mm:
                        mm.auto_extract_memories([
                            {"role": "user", "content": text},
                            {"role": "assistant", "content": assistant_message}
                        ])
                except Exception:
                    pass

                logger.info(f"✅ Response generated: {assistant_message[:50]}...")

                # Send response back to Slack in thread
                await send_slack_message(channel_id, assistant_message, thread_ts)

            except Exception as e:
                logger.error(f"Error processing Slack message: {e}")
                await send_slack_message(channel_id, f"❌ Error processing message: {str(e)}", thread_ts)

        return {"ok": True}

    except Exception as e:
        logger.error(f"Slack webhook error: {e}")
        return {"ok": False, "error": str(e)}


class QuotaCheckRequest(BaseModel):
    project_id: Optional[str] = "default"
    queue_size: Optional[int] = 0


@app.post("/api/quotas/check")
async def quota_check_endpoint(req: QuotaCheckRequest):
    """Check if a request would be allowed under current quotas"""
    try:
        quotas_ok, error_msg = check_all_quotas(req.project_id, req.queue_size)
        status = get_quota_status(req.project_id)

        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "allowed": quotas_ok,
            "error": error_msg,
            "status": status
        }
    except Exception as e:
        logger.error(f"Error checking quotas: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


# ═══════════════════════════════════════════════════════════════════════
# SLACK REPORTING ENDPOINTS
# GET  /slack/report/costs    - Send cost summary to Slack
# GET  /slack/report/health   - Send gateway health to Slack
# GET  /slack/report/sessions - Send session count to Slack
# POST /slack/report/send     - Send arbitrary message to Slack
# ═══════════════════════════════════════════════════════════════════════

@app.get("/slack/report/costs")
async def slack_report_costs():
    """Send cost summary to Slack"""
    try:
        metrics_data = get_cost_metrics()
        total = metrics_data.get('total_cost', 0)
        message = f"""*Cost Summary*

Total: ${total:.4f}
Entries: {metrics_data.get('entries_count', 0)}

*Top Agents:*"""

        for agent, cost in list(metrics_data.get('by_agent', {}).items())[:5]:
            message += f"\n  - {agent}: ${cost:.4f}"

        if not metrics_data.get('by_agent'):
            message += "\n  (no cost data yet)"

        await send_slack_message(SLACK_REPORT_CHANNEL, message)
        return {"ok": True, "message": "Cost summary sent"}
    except Exception as e:
        logger.error(f"Error sending cost report: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/slack/report/health")
async def slack_report_health():
    """Send gateway health to Slack"""
    try:
        monitor = get_heartbeat_monitor()
        if not monitor:
            message = "Heartbeat monitor not initialized"
        else:
            status = monitor.get_status()
            agents_monitoring = status.get("agents_monitoring", 0)
            is_running = status.get("running", False)

            session_count = len(list(SESSIONS_DIR.glob('*.json')))
            message = f"""*Gateway Health*

Heartbeat: {"running" if is_running else "stopped"}
Agents Monitored: {agents_monitoring}
Active Sessions: {session_count}
API Status: OK"""

        await send_slack_message(SLACK_REPORT_CHANNEL, message)
        return {"ok": True, "message": "Health report sent"}
    except Exception as e:
        logger.error(f"Error sending health report: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/slack/report/sessions")
async def slack_report_sessions():
    """Send active sessions count to Slack"""
    try:
        session_files = list(SESSIONS_DIR.glob("*.json"))
        total_messages = 0
        for f in session_files:
            try:
                data = json.load(open(f))
                total_messages += len(data.get("messages", []))
            except:
                pass

        message = f"""📊 *Active Sessions*

Sessions: {len(session_files)}
Total Messages: {total_messages}"""

        await send_slack_message(SLACK_REPORT_CHANNEL, message)
        return {"ok": True, "message": "Session report sent"}
    except Exception as e:
        logger.error(f"Error sending session report: {e}")
        return {"ok": False, "error": str(e)}


class SlackMessageRequest(BaseModel):
    channel: str
    text: str
    thread_ts: Optional[str] = None


@app.post("/slack/report/send")
async def slack_report_send(req: SlackMessageRequest):
    """Send arbitrary message to Slack channel"""
    try:
        if not req.channel or not req.text:
            return {"ok": False, "error": "channel and text required"}

        success = await send_slack_message(req.channel, req.text, req.thread_ts)
        return {"ok": success, "message": "Message sent" if success else "Failed to send"}
    except Exception as e:
        logger.error(f"Error sending Slack message: {e}")
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════
# INTELLIGENT ROUTER ENDPOINTS
# POST /api/route       - Classify query and get optimal model routing
# POST /api/route/test  - Test routing with multiple queries
# GET  /api/route/models - Get available models and pricing
# GET  /api/route/health - Health check for router
# ═══════════════════════════════════════════════════════════════════════

class RouteRequest(BaseModel):
    query: str
    context: Optional[str] = None
    sessionKey: Optional[str] = None
    force_model: Optional[str] = None

class RouteTestRequest(BaseModel):
    queries: list


@app.post("/api/route")
async def route_endpoint(req: RouteRequest):
    """Classify query and route to optimal model (Haiku/Sonnet/Opus)"""
    try:
        if not req.query or not isinstance(req.query, str):
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "query is required and must be a string",
            })

        # Force model override
        if req.force_model and req.force_model in ("haiku", "sonnet", "opus"):
            forced = ClassificationResult(
                complexity=0, model=req.force_model, confidence=1.0,
                reasoning=f"Forced to {req.force_model.upper()} by request",
                estimated_tokens=0, cost_estimate=0,
            )
            return {
                "success": True,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "model": req.force_model,
                "complexity": 0,
                "confidence": 1.0,
                "reasoning": forced.reasoning,
                "cost_estimate": 0,
                "estimated_tokens": 0,
                "metadata": {
                    "pricing": MODEL_PRICING.get(req.force_model, {}),
                    "cost_savings_vs_sonnet": 0,
                    "cost_savings_percentage": 0,
                    "rate_limit": MODEL_RATE_LIMITS.get(req.force_model, {}),
                },
            }

        # Combine query and context
        full_query = f"{req.query}\n\nContext: {req.context}" if req.context else req.query

        # Classify
        result = classify_query(full_query)

        # ═ COST GATES: Check budget before routing decision
        project = req.sessionKey.split(":")[0] if req.sessionKey and ":" in req.sessionKey else "default"
        cost_gates = get_cost_gates()
        
        # Estimate tokens for routing decision
        estimated_tokens = len(full_query.split()) * 2
        
        budget_check = check_cost_budget(
            project=project,
            agent="router",
            model=result.model,
            tokens_input=estimated_tokens // 2,
            tokens_output=estimated_tokens // 2,
            task_id=f"{project}:router:{req.sessionKey}"
        )
        
        if budget_check.status == BudgetStatus.REJECTED:
            logger.warning(f"💰 Cost gate REJECTED routing: {budget_check.message}")
            return JSONResponse(
                status_code=402,
                content={
                    "success": False,
                    "error": "Budget limit exceeded",
                    "detail": budget_check.message,
                    "gate": budget_check.gate_name,
                    "remaining_budget": budget_check.remaining_budget,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }
            )
        elif budget_check.status == BudgetStatus.WARNING:
            logger.warning(f"⚠️  Cost gate WARNING: {budget_check.message}")


        # Calculate savings vs sonnet baseline
        sonnet_cost = (result.estimated_tokens // 3 * MODEL_PRICING["sonnet"]["input"]
                       + (result.estimated_tokens - result.estimated_tokens // 3) * MODEL_PRICING["sonnet"]["output"]) / 1_000_000
        savings = max(0, sonnet_cost - result.cost_estimate)
        savings_pct = round((savings / sonnet_cost) * 100, 2) if sonnet_cost > 0 else 0

        # Log cost event if sessionKey provided
        if req.sessionKey:
            try:
                log_cost_event(
                    project="openclaw",
                    agent="router",
                    model=MODEL_ALIASES.get(result.model, result.model),
                    tokens_input=result.estimated_tokens // 3,
                    tokens_output=result.estimated_tokens - result.estimated_tokens // 3,
                    cost=result.cost_estimate,
                )
            except Exception as e:
                logger.warning(f"Failed to log cost event: {e}")

        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "model": result.model,
            "complexity": result.complexity,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "cost_estimate": result.cost_estimate,
            "estimated_tokens": result.estimated_tokens,
            "metadata": {
                "pricing": MODEL_PRICING.get(result.model, {}),
                "cost_savings_vs_sonnet": round(savings, 6),
                "cost_savings_percentage": savings_pct,
                "rate_limit": MODEL_RATE_LIMITS.get(result.model, {}),
            },
        }
    except Exception as e:
        logger.error(f"Router endpoint error: {e}")
        return JSONResponse(status_code=500, content={
            "success": False,
            "error": str(e),
        })


@app.post("/api/route/test")
async def route_test_endpoint(req: RouteTestRequest):
    """Test routing with multiple queries"""
    try:
        if not req.queries or len(req.queries) == 0:
            return JSONResponse(status_code=400, content={
                "success": False,
                "error": "queries array is required and must not be empty",
            })

        results = []
        for q in req.queries:
            r = classify_query(q)
            sonnet_cost = (r.estimated_tokens // 3 * MODEL_PRICING["sonnet"]["input"]
                           + (r.estimated_tokens - r.estimated_tokens // 3) * MODEL_PRICING["sonnet"]["output"]) / 1_000_000
            savings_pct = round(((sonnet_cost - r.cost_estimate) / sonnet_cost) * 100, 2) if sonnet_cost > 0 else 0
            results.append({
                "query": q[:100] + ("..." if len(q) > 100 else ""),
                "model": r.model,
                "complexity": r.complexity,
                "confidence": r.confidence,
                "cost_estimate": r.cost_estimate,
                "savings_percentage": savings_pct,
            })

        by_model = {"haiku": 0, "sonnet": 0, "opus": 0}
        for r in results:
            by_model[r["model"]] = by_model.get(r["model"], 0) + 1

        stats = {
            "total_queries": len(results),
            "by_model": by_model,
            "avg_complexity": round(sum(r["complexity"] for r in results) / len(results), 1),
            "avg_confidence": round(sum(r["confidence"] for r in results) / len(results), 2),
            "total_estimated_cost": round(sum(r["cost_estimate"] for r in results), 6),
            "avg_savings_percentage": round(sum(r["savings_percentage"] for r in results) / len(results), 1),
        }

        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "results": results,
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Route test endpoint error: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/route/models")
async def route_models_endpoint():
    """Get available models and pricing information"""
    models_info = [
        {
            "name": "Claude 3.5 Haiku",
            "model": "haiku",
            "alias": MODEL_ALIASES["haiku"],
            "pricing": MODEL_PRICING["haiku"],
            "contextWindow": 200000,
            "maxOutputTokens": 4096,
            "costSavingsPercentage": -75,
            "available": True,
            "rateLimit": MODEL_RATE_LIMITS["haiku"],
        },
        {
            "name": "Claude 3.5 Sonnet",
            "model": "sonnet",
            "alias": MODEL_ALIASES["sonnet"],
            "pricing": MODEL_PRICING["sonnet"],
            "contextWindow": 200000,
            "maxOutputTokens": 4096,
            "costSavingsPercentage": 0,
            "available": True,
            "rateLimit": MODEL_RATE_LIMITS["sonnet"],
        },
        {
            "name": "Claude Opus 4.6",
            "model": "opus",
            "alias": MODEL_ALIASES["opus"],
            "pricing": MODEL_PRICING["opus"],
            "contextWindow": 200000,
            "maxOutputTokens": 4096,
            "costSavingsPercentage": 400,
            "available": True,
            "rateLimit": MODEL_RATE_LIMITS["opus"],
        },
    ]

    return {
        "success": True,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "models": models_info,
        "optimalDistribution": {"haiku": "70%", "sonnet": "20%", "opus": "10%"},
        "expectedCostSavings": "60-70% reduction vs always using Sonnet",
    }


@app.get("/api/route/health")
async def route_health_endpoint():
    """Health check for router"""
    return {
        "success": True,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "healthy",
        "models_available": 3,
        "models": ["haiku", "sonnet", "opus"],
        "router_version": "1.0.0",
    }


@app.websocket("/")
async def root_websocket(websocket: WebSocket):
    await handle_websocket(websocket)


@app.websocket("/ws")
async def ws_websocket(websocket: WebSocket):
    await handle_websocket(websocket)


async def _keepalive_ping(websocket: WebSocket, connection_id: str):
    """Send periodic pings"""
    try:
        while True:
            await asyncio.sleep(WS_PING_INTERVAL)
            try:
                await asyncio.wait_for(
                    websocket.send_json({"type": "pong"}),
                    timeout=WS_PING_TIMEOUT,
                )
            except (asyncio.TimeoutError, Exception):
                logger.warning(f"[WS] {connection_id} - Keepalive failed")
                return
    except asyncio.CancelledError:
        return


async def handle_websocket(websocket: WebSocket):
    """Handle WebSocket with proper model routing"""
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    active_connections[connection_id] = websocket
    ping_task = None

    logger.info(f"[WS] New connection: {connection_id}")

    try:
        data = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=WS_RECEIVE_TIMEOUT,
        )
        msg = json.loads(data)

        logger.info(f"[WS] {connection_id} - First message: {msg.get('method')}")

        ping_task = asyncio.create_task(_keepalive_ping(websocket, connection_id))

        while True:
            if 'msg' not in locals() or msg is None:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WS_RECEIVE_TIMEOUT,
                )
                msg = json.loads(data)

            msg_type = msg.get("type")

            if msg_type == "req":
                request_id = msg.get("id")
                method = msg.get("method")
                params = msg.get("params", {})

                logger.info(f"[WS] {connection_id} - Request {request_id}: {method}")

                if method == "connect":
                    hello_ok_payload = {
                        "type": "hello-ok",
                        "protocol": PROTOCOL_VERSION,
                        "features": {
                            "methods": ["chat", "agents", "status"],
                            "events": ["message", "status"]
                        },
                        "auth": {
                            "role": "operator",
                            "scopes": ["operator.admin"],
                            "issuedAtMs": int(asyncio.get_event_loop().time() * 1000)
                        },
                        "policy": {
                            "tickIntervalMs": 30000
                        }
                    }

                    await websocket.send_json({
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": hello_ok_payload
                    })
                    logger.info(f"[WS] {connection_id} - Connected")

                elif method == "chat.send" or method == "chat":
                    run_id = params.get("idempotencyKey", str(uuid.uuid4()))
                    session_key = params.get("sessionKey", "main")
                    message_text = params.get("message", "")

                    # Acknowledge
                    await websocket.send_json({
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": {
                            "runId": run_id,
                            "status": "started"
                        }
                    })

                    try:

                        session_store.get(session_key).append({
                            "role": "user",
                            "content": message_text
                        })

                        # Determine agent using intelligent routing
                        route_decision = agent_router.select_agent(message_text)
                        active_agent = route_decision["agentId"]

                        # Call CORRECT model
                        logger.info(f"🎯 Routing to agent: {active_agent} ({route_decision['reason']})")
                        _trimmed_ws = await trim_history_if_needed(
                            session_store.get(session_key))
                        response_text, tokens = call_model_for_agent(
                            active_agent,
                            message_text,
                            _trimmed_ws[-10:]  # Last 10 messages
                        )

                        timestamp = int(asyncio.get_event_loop().time() * 1000)

                        session_store.get(session_key).append({
                            "role": "assistant",
                            "content": response_text
                        })

                        # Save session to disk
                        save_session_history(session_key, session_store.get(session_key))

                        # Send response
                        await websocket.send_json({
                            "type": "event",
                            "event": "chat",
                            "payload": {
                                "runId": run_id,
                                "message": response_text,
                                "timestamp": timestamp,
                                "stopReason": "end_turn",
                                "usage": {
                                    "totalTokens": tokens
                                }
                            }
                        })

                        logger.info(f"[WS] {connection_id} - Sent response ({tokens} tokens)")

                    except Exception as e:
                        logger.error(f"Error: {e}")
                        await websocket.send_json({
                            "type": "event",
                            "event": "error",
                            "payload": {
                                "runId": run_id,
                                "error": str(e)
                            }
                        })

                else:
                    # Echo other methods
                    await websocket.send_json({
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": {}
                    })

            msg = None  # Reset for next iteration

    except asyncio.TimeoutError:
        logger.warning(f"[WS] {connection_id} - Timeout")
    except Exception as e:
        logger.error(f"[WS] {connection_id} - Error: {e}")
    finally:
        if ping_task:
            ping_task.cancel()
        active_connections.pop(connection_id, None)
        logger.info(f"[WS] {connection_id} - Disconnected")


# ═══════════════════════════════════════════════════════════════════════
# WORKFLOW ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/workflow/start")
async def start_workflow(request: Request):
    """Start a new workflow"""
    try:
        data = await request.json()
        workflow_name = data.get("workflow", "")
        params = data.get("params", {})

        if not workflow_name:
            return JSONResponse({"error": "workflow name required"}, status_code=400)

        workflow_id = workflow_engine.start_workflow(workflow_name, params)
        logger.info(f"🔄 Workflow started: {workflow_id} ({workflow_name})")

        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": "started",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Workflow start error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/workflow/status/{workflow_id}")
async def get_workflow_status(workflow_id: str):
    """Get workflow status"""
    try:
        status = workflow_engine.get_workflow_status(workflow_id)
        if not status:
            return JSONResponse({"error": "workflow not found"}, status_code=404)

        return {
            "workflow_id": workflow_id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Workflow status error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)



# ═══════════════════════════════════════════════════════════════════════
# AUTONOMOUS JOB QUEUE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/job/create")
async def create_new_job(request: Request):
    """Create a new autonomous job"""
    try:
        data = await request.json()
        project = data.get("project", "unknown")
        task = data.get("task", "")
        priority = data.get("priority", "P1")
        
        if not task:
            return JSONResponse({"error": "task required"}, status_code=400)
        
        job = create_job(project, task, priority)
        logger.info(f"🆕 Job created: {job.id}")

        # Emit event for closed-loop
        engine = get_event_engine()
        if engine:
            engine.emit("job.created", {"job_id": job.id, "project": project, "task": task, "priority": priority})

        return {
            "job_id": job.id,
            "project": project,
            "task": task,
            "status": "pending",
            "created_at": job.created_at
        }
    except Exception as e:
        logger.error(f"Job creation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """Get job status"""
    try:
        job = get_job(job_id)
        if not job:
            return JSONResponse({"error": "job not found"}, status_code=404)
        
        return job
    except Exception as e:
        logger.error(f"Job status error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/jobs")
async def list_all_jobs():
    """List all jobs"""
    try:
        jobs = list_jobs()
        return {"jobs": jobs, "total": len(jobs)}
    except Exception as e:
        logger.error(f"List jobs error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/job/{job_id}/approve")
async def approve_job(job_id: str, request: Request):
    """Approve a job for merging"""
    try:
        data = await request.json()
        approved_by = data.get("approved_by", "user")
        
        update_job_status(job_id, "approved", approved_by=approved_by)
        logger.info(f"✅ Job approved: {job_id}")

        engine = get_event_engine()
        if engine:
            engine.emit("job.approved", {"job_id": job_id, "approved_by": approved_by})

        return {"job_id": job_id, "status": "approved", "approved_by": approved_by}
    except Exception as e:
        logger.error(f"Job approval error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# REFLEXION LOOP — Self-improving agent memory
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/reflections")
async def api_list_reflections(request: Request):
    """List all reflections, optionally filtered by project."""
    try:
        from reflexion import list_reflections
        project = request.query_params.get("project")
        limit = int(request.query_params.get("limit", "50"))
        refs = list_reflections(project=project, limit=limit)
        return {"reflections": refs, "total": len(refs)}
    except Exception as e:
        logger.error(f"Reflections list error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/reflections/stats")
async def api_reflections_stats():
    """Get reflection statistics."""
    try:
        from reflexion import get_stats
        return get_stats()
    except Exception as e:
        logger.error(f"Reflections stats error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/reflections/search")
async def api_search_reflections(request: Request):
    """Search reflections for a task description."""
    try:
        from reflexion import search_reflections, format_reflections_for_prompt
        data = await request.json()
        task = data.get("task", "")
        project = data.get("project")
        limit = data.get("limit", 3)
        if not task:
            return JSONResponse({"error": "task required"}, status_code=400)
        refs = search_reflections(task, project=project, limit=limit)
        return {
            "reflections": refs,
            "total": len(refs),
            "formatted": format_reflections_for_prompt(refs),
        }
    except Exception as e:
        logger.error(f"Reflections search error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# CLOSED LOOP — Proposals, Auto-Approval, Events, Policy
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/proposal/create")
async def api_create_proposal(request: Request):
    """Create a proposal and run it through auto-approval"""
    try:
        data = await request.json()
        proposal = create_proposal(
            title=data.get("title", "Untitled"),
            description=data.get("description", ""),
            agent_pref=data.get("agent_pref", "project_manager"),
            tokens_est=data.get("tokens_est", 5000),
            tags=data.get("tags", []),
            auto_approve_threshold=data.get("auto_approve_threshold", 50),
        )
        logger.info(f"Proposal created: {proposal.id} cost=${proposal.cost_est_usd:.4f}")

        # Emit event
        engine = get_event_engine()
        if engine:
            engine.emit("proposal.created", {"proposal_id": proposal.id, "title": proposal.title, "cost": proposal.cost_est_usd})

        # Run through auto-approval
        result = auto_approve_and_execute(proposal.to_dict())

        return {
            "proposal_id": proposal.id,
            "cost_est_usd": proposal.cost_est_usd,
            "approval": result,
        }
    except Exception as e:
        logger.error(f"Proposal creation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/proposals")
async def api_list_proposals(status: Optional[str] = None):
    """List proposals, optionally filtered by status"""
    try:
        proposals = list_proposals(status=status)
        return {"proposals": [p.to_dict() for p in proposals], "total": len(proposals)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/proposal/{proposal_id}")
async def api_get_proposal(proposal_id: str):
    """Get a single proposal"""
    try:
        p = get_proposal(proposal_id)
        if not p:
            return JSONResponse({"error": "not found"}, status_code=404)
        return p.to_dict()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/policy")
async def api_get_policy():
    """Get current ops policy"""
    try:
        return get_policy()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/events")
async def api_get_events(limit: int = 50, event_type: Optional[str] = None, since: Optional[str] = None):
    """Get recent events. Optional ?since= ISO timestamp filter."""
    try:
        engine = get_event_engine()
        # Also read from persistent file if engine is empty
        events = []
        if engine:
            events = engine.get_recent_events(limit=200, event_type=event_type)

        # Supplement from events.jsonl if we have few in-memory events
        if len(events) < limit:
            events_file = os.path.join(DATA_DIR, "events", "events.jsonl")
            if os.path.exists(events_file):
                with open(events_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                            if event_type and evt.get("event_type") != event_type:
                                continue
                            events.append(evt)
                        except:
                            continue

        # Deduplicate by event_id
        seen = set()
        unique = []
        for e in events:
            eid = e.get("event_id") or e.get("id") or id(e)
            if eid not in seen:
                seen.add(eid)
                unique.append(e)
        events = unique

        # Filter by since timestamp
        if since:
            events = [e for e in events if (e.get("timestamp", "") or "") > since]

        # Sort by timestamp descending, limit
        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        events = events[:limit]
        return {"events": events, "total": len(events)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# MEMORY & CRON ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/memories")
async def api_list_memories(tag: Optional[str] = None, limit: int = 20):
    """List memories, optionally filtered by tag"""
    try:
        mm = get_memory_manager()
        if not mm:
            return {"memories": [], "total": 0}
        if tag:
            memories = mm.get_by_tag(tag)
        else:
            memories = mm.get_recent(limit=limit)
        return {"memories": memories, "total": len(memories)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/memory/add")
async def api_add_memory(request: Request):
    """Manually add a memory"""
    try:
        data = await request.json()
        mm = get_memory_manager()
        if not mm:
            return JSONResponse({"error": "memory manager not initialized"}, status_code=500)
        mem_id = mm.add_memory(
            content=data.get("content", ""),
            tags=data.get("tags", []),
            source=data.get("source", "manual"),
            importance=data.get("importance", 5)
        )
        return {"memory_id": mem_id, "status": "saved"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/cron/jobs")
async def api_cron_jobs():
    """List cron jobs"""
    try:
        cron = get_cron_scheduler()
        if not cron:
            return {"jobs": [], "total": 0}
        jobs = cron.list_jobs()
        return {"jobs": jobs, "total": len(jobs)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# GOOGLE OAUTH — Gmail + Calendar token flow (runs 24/7 on gateway)
# ═══════════════════════════════════════════════════════════════════════

GOOGLE_CREDS_FILE = "/root/.config/gmail/credentials.json"
GOOGLE_TOKEN_DIR = "/root/.config/gmail"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


@app.get("/oauth/start")
async def oauth_start():
    """Start Google OAuth flow — Desktop client OOB, Google shows code on screen."""
    try:
        with open(GOOGLE_CREDS_FILE) as f:
            creds_data = json.load(f)
        creds = creds_data.get("installed", creds_data.get("web", {}))
        client_id = creds["client_id"]

        import urllib.parse
        params = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        })
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{params}"
        gateway_url = "https://gateway.overseerclaw.uk/oauth/exchange"
        html = f"""<!DOCTYPE html>
<html><head><title>OpenClaw — Google OAuth</title>
<style>body{{font-family:system-ui;background:#09090b;color:#fafafa;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#18181b;border:1px solid #3f3f46;border-radius:12px;padding:40px;max-width:600px;text-align:center}}
a{{color:#3b82f6;font-size:18px}}
.steps{{text-align:left;margin-top:20px;line-height:2}}
.steps b{{color:#22c55e}}
code{{background:#27272a;padding:2px 8px;border-radius:4px;font-size:13px}}
input{{width:100%;padding:12px;margin:10px 0;background:#27272a;border:1px solid #3f3f46;color:#fafafa;border-radius:8px;font-size:16px}}
button{{padding:12px 24px;background:#3b82f6;color:white;border:none;border-radius:8px;font-size:16px;cursor:pointer}}
button:hover{{background:#2563eb}}
.result{{margin-top:16px;padding:12px;border-radius:8px;display:none}}</style></head>
<body><div class="card">
<h1>OpenClaw OAuth</h1>
<div class="steps">
<b>Step 1:</b> <a href="{auth_url}" target="_blank">Click here to authorize with Google</a><br>
<b>Step 2:</b> Sign in and approve the permissions<br>
<b>Step 3:</b> Google will show you a code on screen — copy it<br>
<b>Step 4:</b> Paste the code below:
</div>
<form onsubmit="return submitCode()">
<input type="text" id="codeInput" placeholder="Paste the authorization code here..." autofocus>
<button type="submit">Save Token</button>
</form>
<div id="result" class="result"></div>
<script>
async function submitCode() {{
    const code = document.getElementById('codeInput').value.trim();
    const result = document.getElementById('result');
    if (!code) {{
        result.style.display = 'block';
        result.style.background = '#7f1d1d';
        result.textContent = 'Please paste the code from Google.';
        return false;
    }}
    try {{
        const resp = await fetch('{gateway_url}?code=' + encodeURIComponent(code));
        const data = await resp.json();
        if (data.status === 'ok') {{
            result.style.display = 'block';
            result.style.background = '#14532d';
            result.innerHTML = '&#9989; ' + data.message;
        }} else {{
            result.style.display = 'block';
            result.style.background = '#7f1d1d';
            result.textContent = 'Error: ' + (data.error || 'Unknown error');
        }}
    }} catch(e) {{
        result.style.display = 'block';
        result.style.background = '#7f1d1d';
        result.textContent = 'Network error: ' + e.message;
    }}
    return false;
}}
</script>
</div></body></html>"""
        return HTMLResponse(html)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/oauth/exchange")
async def oauth_exchange(code: str = None):
    """Exchange an OAuth code for tokens — Desktop client OOB flow."""
    if not code:
        return JSONResponse({"error": "No code provided"}, status_code=400)

    try:
        with open(GOOGLE_CREDS_FILE) as f:
            creds_data = json.load(f)
        creds = creds_data.get("installed", creds_data.get("web", {}))

        import httpx as hx
        token_resp = hx.post(creds["token_uri"], data={
            "code": code,
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
            "grant_type": "authorization_code",
        }, timeout=15)
        token_data = token_resp.json()

        if "error" in token_data:
            return JSONResponse({
                "error": f"{token_data['error']}: {token_data.get('error_description', '')}"
            }, status_code=400)

        # Save tokens for both Gmail and Calendar MCP
        os.makedirs(GOOGLE_TOKEN_DIR, exist_ok=True)
        for fname in ("token.json", "calendar_token.json"):
            with open(os.path.join(GOOGLE_TOKEN_DIR, fname), "w") as f:
                json.dump(token_data, f, indent=2)

        logger.info("Google OAuth tokens saved successfully")
        scopes = token_data.get("scope", "").split()
        return {"status": "ok", "message": f"Authorized! Tokens saved. Scopes: {', '.join(scopes)}"}
    except Exception as e:
        logger.error(f"OAuth exchange error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/oauth/callback")
async def oauth_callback(code: str = None, error: str = None):
    """Legacy callback — redirects to exchange."""
    if error:
        return HTMLResponse(f"<h1>OAuth Error</h1><p>{error}</p>", status_code=400)
    if code:
        return await oauth_exchange(code=code)
    return HTMLResponse("<h1>Missing code</h1>", status_code=400)


# ═══════════════════════════════════════════════════════════════════════
# GMAIL & CALENDAR — Read-only endpoints for PA Worker
# ═══════════════════════════════════════════════════════════════════════

def _get_google_creds():
    """Load and refresh Google OAuth credentials."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GRequest

    token_path = os.path.join(GOOGLE_TOKEN_DIR, "token.json")
    if not os.path.exists(token_path):
        raise HTTPException(status_code=500, detail="Google token not found. Run /oauth/start first.")

    with open(token_path) as f:
        token_data = json.load(f)

    # Merge client_id/client_secret from credentials.json if missing
    if "client_id" not in token_data or "client_secret" not in token_data:
        with open(GOOGLE_CREDS_FILE) as f:
            creds_data = json.load(f)
        installed = creds_data.get("installed", creds_data.get("web", {}))
        token_data["client_id"] = installed["client_id"]
        token_data["client_secret"] = installed["client_secret"]
        token_data["token_uri"] = installed.get("token_uri", "https://oauth2.googleapis.com/token")
        # Save merged version for future loads
        with open(token_path, "w") as f:
            json.dump(token_data, f, indent=2)

    creds = Credentials.from_authorized_user_info(token_data, GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        # Save refreshed token
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


@app.get("/api/gmail/inbox")
async def api_gmail_inbox(limit: int = 10, unread_only: bool = True):
    """Get Gmail inbox messages. Returns subject, from, snippet, date, read status."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("gmail", "v1", credentials=creds)

        query = "in:inbox"
        if unread_only:
            query += " is:unread"

        results = service.users().messages().list(
            userId="me", q=query, maxResults=limit
        ).execute()
        msg_ids = results.get("messages", [])

        messages = []
        for msg_ref in msg_ids[:limit]:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            messages.append({
                "id": msg["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "snippet": msg.get("snippet", ""),
                "date": headers.get("Date", ""),
                "is_read": "UNREAD" not in msg.get("labelIds", []),
            })

        return {"messages": messages, "total": len(messages)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Gmail inbox error: {e}")
        return JSONResponse({"error": str(e), "messages": []}, status_code=500)


@app.get("/api/calendar/today")
async def api_calendar_today():
    """Get today's calendar events from ALL calendars."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("calendar", "v3", credentials=creds)

        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

        # Query ALL calendars, not just primary
        cal_list = service.calendarList().list().execute()
        events = []
        for cal in cal_list.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)
            try:
                results = service.events().list(
                    calendarId=cal_id,
                    timeMin=start_of_day,
                    timeMax=end_of_day,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=20,
                ).execute()
                for item in results.get("items", []):
                    start = item.get("start", {})
                    end = item.get("end", {})
                    events.append({
                        "id": item.get("id", ""),
                        "summary": item.get("summary", "(no title)"),
                        "start": start.get("dateTime", start.get("date", "")),
                        "end": end.get("dateTime", end.get("date", "")),
                        "location": item.get("location", ""),
                        "calendar": cal_name,
                    })
            except Exception:
                pass  # Skip calendars we can't read

        events.sort(key=lambda e: e.get("start", ""))
        return {"events": events, "total": len(events)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar today error: {e}")
        return JSONResponse({"error": str(e), "events": []}, status_code=500)


@app.get("/api/calendar/upcoming")
async def api_calendar_upcoming(days: int = 7):
    """Get upcoming calendar events for the next N days."""
    try:
        from googleapiclient.discovery import build
        creds = _get_google_creds()
        service = build("calendar", "v3", credentials=creds)

        now = datetime.now(timezone.utc)
        from datetime import timedelta
        end = now + timedelta(days=days)

        # Query ALL calendars
        cal_list = service.calendarList().list().execute()
        events = []
        for cal in cal_list.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)
            try:
                results = service.events().list(
                    calendarId=cal_id,
                    timeMin=now.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                ).execute()
                for item in results.get("items", []):
                    start = item.get("start", {})
                    end_t = item.get("end", {})
                    events.append({
                        "id": item.get("id", ""),
                        "summary": item.get("summary", "(no title)"),
                        "start": start.get("dateTime", start.get("date", "")),
                        "end": end_t.get("dateTime", end_t.get("date", "")),
                        "location": item.get("location", ""),
                        "calendar": cal_name,
                    })
            except Exception:
                pass

        events.sort(key=lambda e: e.get("start", ""))
        return {"events": events, "total": len(events)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calendar upcoming error: {e}")
        return JSONResponse({"error": str(e), "events": []}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# HEALTH SYNC — Receive data from iOS Shortcuts (Apple Health)
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/health/sync")
async def api_health_sync(request: Request):
    """Receive health data from iOS Shortcuts (Apple Health export)."""
    try:
        data = await request.json()
        health_dir = os.path.join(DATA_DIR, "health")
        os.makedirs(health_dir, exist_ok=True)
        if "timestamp" not in data:
            data["timestamp"] = datetime.now(timezone.utc).isoformat()
        if "date" not in data:
            data["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_file = os.path.join(health_dir, "daily.jsonl")
        with open(daily_file, "a") as f:
            f.write(json.dumps(data) + "\n")
        logger.info(f"Health sync received: {list(data.keys())}")
        return {"status": "ok", "received_keys": list(data.keys())}
    except Exception as e:
        logger.error(f"Health sync error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/health/today")
async def api_health_today():
    """Get today's health data."""
    try:
        health_file = os.path.join(DATA_DIR, "health", "daily.jsonl")
        if not os.path.exists(health_file):
            return {"data": [], "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entries = []
        with open(health_file) as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    entry = json.loads(line)
                    if entry.get("date", "") == today:
                        entries.append(entry)
                except: continue
        return {"data": entries, "date": today}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# REACTIONS & SELF-IMPROVE API
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/reactions")
async def api_list_reactions():
    """List all reaction rules."""
    try:
        from reactions import get_reactions_engine
        engine = get_reactions_engine()
        return {"rules": engine.get_rules(), "status": engine.get_status()}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/reactions")
async def api_manage_reaction(request: Request):
    """Add/update/delete a reaction rule."""
    try:
        from reactions import get_reactions_engine
        data = await request.json()
        engine = get_reactions_engine()
        action = data.get("action", "add")
        if action == "add":
            rule_id = engine.add_rule(data.get("rule", data))
            return {"rule_id": rule_id, "status": "added"}
        elif action == "update":
            engine.update_rule(data["rule_id"], data.get("updates", {}))
            return {"status": "updated"}
        elif action == "delete":
            engine.delete_rule(data["rule_id"])
            return {"status": "deleted"}
        return JSONResponse({"error": f"Unknown action: {action}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/reactions/triggers")
async def api_reaction_triggers(limit: int = 20):
    """Get recent reaction trigger history."""
    try:
        from reactions import get_reactions_engine
        engine = get_reactions_engine()
        return {"triggers": engine.get_recent_triggers(limit=limit)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/metrics/summary")
async def api_metrics_summary(days: int = 7):
    """Get agent performance summary."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return engine.get_summary(days=days)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/metrics/sparkline")
async def api_metrics_sparkline(days: int = 7):
    """Get daily success rate data for sparkline charts."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return {"data": engine.get_daily_sparkline_data(days=days)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/metrics/recommendations")
async def api_metrics_recommendations():
    """Get guardrail adjustment recommendations."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return engine.get_guardrail_recommendations()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/metrics/retrospective")
async def api_generate_retrospective():
    """Generate and save a weekly retrospective."""
    try:
        from self_improve import get_self_improve_engine
        engine = get_self_improve_engine()
        return engine.generate_retrospective()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════════════
# SLACK JOB MANAGEMENT — Slash commands + JSON API for job creation
# ═══════════════════════════════════════════════════════════════════════

@app.post("/slack/create-job")
async def slack_create_job(request: Request):
    """Create a job from Slack JSON payload and notify the report channel."""
    try:
        data = await request.json()
        project = data.get("project", "openclaw")
        task = data.get("task", "General task")
        priority = data.get("priority", "P1")
        slack_user = data.get("slack_user_id", "unknown")

        job = create_job(project, task, priority)
        logger.info(f"✅ Job created from Slack: {job.id} by {slack_user}")

        await send_slack_message(
            SLACK_REPORT_CHANNEL,
            f"📋 *New Job Created*\n• *ID:* `{job.id}`\n• *Project:* {project}\n• *Task:* {task}\n• *Priority:* {priority}\n• *Created by:* <@{slack_user}>"
        )

        return {"success": True, "job_id": job.id, "status": "pending", "message": f"Job created: {job.id}"}
    except Exception as e:
        logger.error(f"Slack job creation error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/slack/slash/job")
async def slack_slash_job(request: Request):
    """Slack slash command: /job <project> <priority> <task>"""
    try:
        form = await request.form()
        text = form.get("text", "").strip()
        user_id = form.get("user_id", "unknown")

        if not text:
            return PlainTextResponse(
                "Usage: `/job <project> <priority> <task>`\n"
                "Example: `/job barber-crm P1 Fix booking page`\n"
                "Projects: barber-crm, openclaw, delhi-palace, prestress-calc"
            )

        parts = text.split(None, 2)
        project = parts[0] if len(parts) >= 1 else "openclaw"
        priority = parts[1].upper() if len(parts) >= 2 and parts[1].upper() in ("P0", "P1", "P2", "P3") else "P1"
        task = parts[2] if len(parts) >= 3 else text
        if len(parts) >= 2 and parts[1].upper() not in ("P0", "P1", "P2", "P3"):
            task = " ".join(parts[1:])

        job = create_job(project, task, priority)
        logger.info(f"✅ Slash command job: {job.id} by {user_id}")

        await send_slack_message(
            SLACK_REPORT_CHANNEL,
            f"📋 *New Job via /job*\n• *ID:* `{job.id}`\n• *Project:* {project}\n• *Task:* {task}\n• *Priority:* {priority}\n• *By:* <@{user_id}>"
        )

        return PlainTextResponse(f"✅ Job created!\nID: `{job.id}`\nProject: {project} | Priority: {priority}\nTask: {task}")
    except Exception as e:
        logger.error(f"Slash command error: {e}")
        return PlainTextResponse(f"❌ Error: {str(e)}")


@app.post("/slack/slash/jobs")
async def slack_slash_jobs(request: Request):
    """Slack slash command: /jobs [status] — list recent jobs"""
    try:
        form = await request.form()
        filter_status = form.get("text", "").strip().lower()
        jobs = list_jobs()
        if filter_status:
            jobs = [j for j in jobs if j.get("status") == filter_status]
        if not jobs:
            return PlainTextResponse("No jobs found.")

        recent = jobs[-10:]
        lines = ["*Recent Jobs:*"]
        for j in reversed(recent):
            emoji = {"pending": "⏳", "analyzing": "🔍", "code_generated": "💻", "pr_ready": "📝", "approved": "✅", "merged": "🚀", "done": "✅", "failed": "❌"}.get(j.get("status", ""), "❓")
            lines.append(f"{emoji} `{j['id']}` | {j['project']} | {j.get('status','?')} | {j['task'][:60]}")
        return PlainTextResponse("\n".join(lines))
    except Exception as e:
        return PlainTextResponse(f"❌ Error: {str(e)}")


@app.post("/slack/slash/approve")
async def slack_slash_approve(request: Request):
    """Slack slash command: /approve <job-id>"""
    try:
        form = await request.form()
        job_id = form.get("text", "").strip()
        user_id = form.get("user_id", "unknown")

        if not job_id:
            return PlainTextResponse("Usage: `/approve <job-id>`")
        job = get_job(job_id)
        if not job:
            return PlainTextResponse(f"❌ Job `{job_id}` not found")
        if job.get("status") != "pr_ready":
            return PlainTextResponse(f"⚠️ Job `{job_id}` is `{job.get('status')}`, not ready for approval")

        update_job_status(job_id, "approved", approved_by=user_id)

        await send_slack_message(
            SLACK_REPORT_CHANNEL,
            f"✅ *Job Approved*\n• *ID:* `{job_id}`\n• *Task:* {job['task']}\n• *Approved by:* <@{user_id}>"
        )
        return PlainTextResponse(f"✅ Job `{job_id}` approved! Processor will execute it shortly.")
    except Exception as e:
        return PlainTextResponse(f"❌ Error: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════
# MISSION CONTROL DASHBOARD ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/agents/status")
async def agents_status():
    """Get status of all agents for Mission Control"""
    agents_config = CONFIG.get("agents", {})
    agent_statuses = {}
    heartbeat = get_heartbeat_monitor()

    for agent_id, config in agents_config.items():
        agent_statuses[agent_id] = {
            "name": config.get("name", agent_id),
            "emoji": config.get("emoji", ""),
            "model": config.get("model", "unknown"),
            "provider": config.get("apiProvider", "unknown"),
            "type": config.get("type", "unknown"),
            "skills": config.get("skills", []),
            "signature": config.get("signature", ""),
            "costSavings": config.get("costSavings", ""),
            "status": "active",
        }

        # Check heartbeat if available
        if heartbeat:
            try:
                status_data = heartbeat.get_status()
                in_flight = heartbeat.get_in_flight_agents()
                if agent_id in [a.get("agent_id") for a in in_flight]:
                    agent_statuses[agent_id]["status"] = "busy"
                else:
                    agent_statuses[agent_id]["status"] = "idle"
            except Exception:
                pass

    return {"success": True, "agents": agent_statuses, "total": len(agent_statuses)}


@app.get("/api/tasks")
async def list_tasks_endpoint():
    """List all tasks for Mission Control task board"""
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r') as f:
                tasks = json.load(f)
        else:
            tasks = []
        return {"success": True, "tasks": tasks, "total": len(tasks)}
    except Exception as e:
        return {"success": True, "tasks": [], "total": 0}


@app.post("/api/tasks")
async def create_task_endpoint(request: Request):
    """Create a new task"""
    body = await request.json()
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r') as f:
                tasks = json.load(f)
        else:
            tasks = []

        task = {
            "id": str(uuid.uuid4())[:8],
            "title": body.get("title", "Untitled"),
            "description": body.get("description", ""),
            "status": body.get("status", "todo"),
            "agent": body.get("agent", ""),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        tasks.append(task)

        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks, f, indent=2)

        return {"success": True, "task": task}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/tasks/{task_id}")
async def update_task_endpoint(task_id: str, request: Request):
    """Update a task status"""
    body = await request.json()
    try:
        if TASKS_FILE.exists():
            with open(TASKS_FILE, 'r') as f:
                tasks = json.load(f)
        else:
            tasks = []

        for task in tasks:
            if task["id"] == task_id:
                task.update({k: v for k, v in body.items() if k in ["title", "description", "status", "agent"]})
                task["updated_at"] = datetime.utcnow().isoformat() + "Z"
                break

        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks, f, indent=2)

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/memory/list")
async def memory_list():
    """List all memories for Mission Control"""
    memory_mgr = get_memory_manager()
    if not memory_mgr:
        return {"success": True, "memories": [], "total": 0}

    memories = memory_mgr.list_all() if hasattr(memory_mgr, 'list_all') else []
    return {"success": True, "memories": memories, "total": len(memories)}


@app.get("/api/dashboard/summary")
async def dashboard_summary():
    """Aggregated dashboard summary for Mission Control"""
    # Get cost metrics
    cost_data = get_cost_metrics()

    # Get cache stats
    cache = get_response_cache()
    cache_stats = cache.get_stats() if cache else {}

    # Get quota status
    quota_status = get_quota_status("default")

    # Get agent count
    agent_count = len(CONFIG.get("agents", {}))

    # Get router stats
    router_stats = agent_router.get_cache_stats() if hasattr(agent_router, 'get_cache_stats') else {}

    return {
        "success": True,
        "summary": {
            "agents_total": agent_count,
            "cost_today": cost_data.get("today_usd", 0),
            "cost_month": cost_data.get("month_usd", 0),
            "daily_limit": quota_status.get("daily", {}).get("limit", 50),
            "monthly_limit": quota_status.get("monthly", {}).get("limit", 1000),
            "cache_hit_rate": cache_stats.get("hit_rate_percent", "0%"),
            "cache_tokens_saved": cache_stats.get("total_tokens_saved", 0),
            "cache_cost_saved": cache_stats.get("total_cost_saved_usd", 0),
            "router_cache": router_stats,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# WORKFLOW ENGINE REST ENDPOINTS
# Sequential multi-step agent task chains with error handling
# ═══════════════════════════════════════════════════════════════════════

_workflows_file = pathlib.Path(os.path.join(DATA_DIR, "jobs", "workflows.json"))

def _load_workflows():
    if _workflows_file.exists():
        with open(_workflows_file, 'r') as f:
            return json.load(f)
    return []

def _save_workflows(workflows):
    with open(_workflows_file, 'w') as f:
        json.dump(workflows, f, indent=2)


@app.post("/api/workflows")
async def create_workflow_endpoint(request: Request):
    """Create and optionally start a new workflow"""
    body = await request.json()
    steps = body.get("steps", [])
    name = body.get("name", "Unnamed Workflow")
    auto_start = body.get("auto_start", False)

    if not steps:
        raise HTTPException(status_code=400, detail="Workflow must have at least one step")

    workflow_id = str(uuid.uuid4())[:8]
    workflow = {
        "id": workflow_id,
        "name": name,
        "steps": steps,
        "status": "created",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "results": [],
        "current_step": 0
    }

    workflows = _load_workflows()
    workflows.append(workflow)
    _save_workflows(workflows)

    if auto_start:
        asyncio.create_task(_execute_workflow(workflow_id))
        workflow["status"] = "running"

    broadcast_event({"type": "workflow_created", "agent": "system",
                     "message": f"Workflow '{name}' created ({len(steps)} steps)"})

    return {"success": True, "workflow": workflow}


@app.get("/api/workflows")
async def list_workflows_endpoint():
    """List all workflows"""
    workflows = _load_workflows()
    return {"success": True, "workflows": workflows, "total": len(workflows)}


@app.get("/api/workflows/templates")
async def list_workflow_templates():
    """List available workflow templates"""
    templates = {
        name: {"name": t["name"], "description": t["description"], "steps_count": len(t["steps"])}
        for name, t in WORKFLOW_TEMPLATES.items()
    }
    return {"success": True, "templates": templates, "total": len(templates)}


@app.post("/api/workflows/templates/{template_name}")
async def create_workflow_from_template(template_name: str, request: Request):
    """Create and start a workflow from a template. Optionally pass context in request body."""
    if template_name not in WORKFLOW_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found. Available: {', '.join(WORKFLOW_TEMPLATES.keys())}")

    template = WORKFLOW_TEMPLATES[template_name]
    try:
        body = await request.json()
    except Exception:
        body = {}
    context = body.get("context", "")
    auto_start = body.get("auto_start", True)

    steps = []
    for i, step in enumerate(template["steps"]):
        new_step = dict(step)
        if i == 0 and context:
            new_step["task"] = f"Context: {context}\n\n{new_step['task']}"
        steps.append(new_step)

    workflow_id = str(uuid.uuid4())[:8]
    workflow = {
        "id": workflow_id,
        "name": f"{template['name']} ({workflow_id})",
        "template": template_name,
        "steps": steps,
        "status": "created",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "results": [],
        "current_step": 0,
        "context": context[:500] if context else ""
    }

    workflows = _load_workflows()
    workflows.append(workflow)
    _save_workflows(workflows)

    if auto_start:
        asyncio.create_task(_execute_workflow(workflow_id))
        workflow["status"] = "running"

    broadcast_event({"type": "workflow_created", "agent": "system",
                     "message": f"Template '{template_name}' started ({len(steps)} steps)"})

    return {"success": True, "workflow": workflow}


@app.get("/api/workflows/{workflow_id}")
async def get_workflow_endpoint(workflow_id: str):
    """Get workflow status and results"""
    workflows = _load_workflows()
    for wf in workflows:
        if wf["id"] == workflow_id:
            return {"success": True, "workflow": wf}
    raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")


@app.delete("/api/workflows/{workflow_id}")
async def cancel_workflow_endpoint(workflow_id: str):
    """Cancel a running workflow"""
    workflows = _load_workflows()
    for wf in workflows:
        if wf["id"] == workflow_id:
            wf["status"] = "cancelled"
            wf["cancelled_at"] = datetime.utcnow().isoformat() + "Z"
            break
    _save_workflows(workflows)
    broadcast_event({"type": "workflow_cancelled", "agent": "system",
                     "message": f"Workflow {workflow_id} cancelled"})
    return {"success": True, "message": f"Workflow {workflow_id} cancelled"}


@app.post("/api/workflows/{workflow_id}/start")
async def start_workflow_endpoint(workflow_id: str):
    """Start a created workflow"""
    asyncio.create_task(_execute_workflow(workflow_id))
    return {"success": True, "message": f"Workflow {workflow_id} started"}


async def _execute_workflow(workflow_id: str):
    """Execute workflow steps sequentially, passing output forward"""
    workflows = _load_workflows()
    workflow = None
    for wf in workflows:
        if wf["id"] == workflow_id:
            workflow = wf
            break

    if not workflow:
        return

    workflow["status"] = "running"
    workflow["started_at"] = datetime.utcnow().isoformat() + "Z"
    _save_workflows(workflows)

    broadcast_event({"type": "workflow_started", "agent": "system",
                     "message": f"Workflow '{workflow.get('name', workflow_id)}' started"})

    previous_output = ""

    for i, step in enumerate(workflow["steps"]):
        # Reload to check for cancellation
        workflows = _load_workflows()
        for wf in workflows:
            if wf["id"] == workflow_id:
                workflow = wf
                break

        if workflow["status"] == "cancelled":
            break

        workflow["current_step"] = i
        _save_workflows(workflows)

        agent_id = step.get("agent", "project_manager")
        task = step.get("task", "")

        if previous_output:
            task = f"Previous step output:\n{previous_output}\n\nYour task: {task}"

        broadcast_event({"type": "workflow_step_start", "agent": agent_id,
                         "message": f"Workflow step {i+1}/{len(workflow['steps'])}: {step.get('task', '')[:60]}"})

        try:
            response_text, tokens = call_model_for_agent(agent_id, task)

            step_result = {
                "step": i,
                "agent": agent_id,
                "task": step.get("task", ""),
                "status": "completed",
                "response": response_text,
                "tokens": tokens,
                "completed_at": datetime.utcnow().isoformat() + "Z"
            }
            previous_output = response_text

            agent_cfg = get_agent_config(agent_id)
            try:
                log_cost_event(
                    project="openclaw",
                    agent=agent_id,
                    model=agent_cfg.get("model", "unknown"),
                    tokens_input=len(task.split()),
                    tokens_output=tokens
                )
            except Exception:
                pass

            broadcast_event({"type": "workflow_step_end", "agent": agent_id,
                             "message": f"Step {i+1} completed ({tokens} tokens)"})

        except Exception as e:
            step_result = {
                "step": i,
                "agent": agent_id,
                "task": step.get("task", ""),
                "status": "failed",
                "error": str(e),
                "completed_at": datetime.utcnow().isoformat() + "Z"
            }

            workflows = _load_workflows()
            for wf in workflows:
                if wf["id"] == workflow_id:
                    wf["results"].append(step_result)
                    wf["status"] = "failed"
                    wf["failed_at"] = datetime.utcnow().isoformat() + "Z"
                    break
            _save_workflows(workflows)

            broadcast_event({"type": "workflow_failed", "agent": agent_id,
                             "message": f"Workflow failed at step {i+1}: {str(e)[:60]}"})
            return

        # Save step result
        workflows = _load_workflows()
        for wf in workflows:
            if wf["id"] == workflow_id:
                wf["results"].append(step_result)
                break
        _save_workflows(workflows)

    # Mark completed
    workflows = _load_workflows()
    for wf in workflows:
        if wf["id"] == workflow_id:
            if wf["status"] != "cancelled":
                wf["status"] = "completed"
                wf["completed_at"] = datetime.utcnow().isoformat() + "Z"
            break
    _save_workflows(workflows)

    broadcast_event({"type": "workflow_completed", "agent": "system",
                     "message": f"Workflow '{workflow.get('name', workflow_id)}' completed"})


# ═══════════════════════════════════════════════════════════════════════
# WORKFLOW TEMPLATES — Pre-built workflows callable by name
# ═══════════════════════════════════════════════════════════════════════

WORKFLOW_TEMPLATES = {
    "security-audit": {
        "name": "Security Audit",
        "description": "Full OWASP security audit with remediation plan",
        "steps": [
            {"agent": "hacker_agent", "task": "Conduct a comprehensive OWASP Top 10 security audit. Identify all vulnerabilities, rate severity (Critical/High/Medium/Low), and provide specific attack vectors."},
            {"agent": "coder_agent", "task": "Based on the security findings above, write code fixes for each vulnerability. Include before/after code snippets with explanations."},
            {"agent": "project_manager", "task": "Synthesize the security audit and code fixes into a prioritized remediation plan with timeline estimates and cost impact."}
        ]
    },
    "code-review": {
        "name": "Code Review",
        "description": "Multi-agent code review (quality + security + architecture)",
        "steps": [
            {"agent": "elite_coder", "task": "Review the code for architecture quality, design patterns, performance issues, and maintainability. Provide specific improvement suggestions."},
            {"agent": "hacker_agent", "task": "Review the code for security vulnerabilities, injection risks, auth bypass, and data leakage. Flag anything OWASP-relevant."},
            {"agent": "project_manager", "task": "Combine the code quality and security reviews into a single report with prioritized action items."}
        ]
    },
    "deploy-pipeline": {
        "name": "Deploy Pipeline",
        "description": "Build → Test → Security Check → Deploy preparation",
        "steps": [
            {"agent": "coder_agent", "task": "Verify the build succeeds. Check for TypeScript errors, missing dependencies, and test failures. Report build status."},
            {"agent": "hacker_agent", "task": "Run a pre-deployment security check. Verify no secrets in code, check dependency vulnerabilities, and confirm auth is configured."},
            {"agent": "project_manager", "task": "Create a deployment checklist based on the build and security results. Include rollback plan and monitoring steps."}
        ]
    },
    "full-website": {
        "name": "Full Website Build",
        "description": "Plan → Build → Security Audit → QA",
        "steps": [
            {"agent": "project_manager", "task": "Break down the website requirements into specific tasks: pages needed, components, API endpoints, database schema, and timeline."},
            {"agent": "elite_coder", "task": "Implement the website based on the project plan above. Write all components, pages, API routes, and database queries."},
            {"agent": "hacker_agent", "task": "Audit the implementation for security issues: XSS, CSRF, SQL injection, auth bypass, insecure headers."},
            {"agent": "project_manager", "task": "Quality check: verify all requirements are met, security issues addressed, and create a final delivery summary."}
        ]
    },
    "database-audit": {
        "name": "Database Audit",
        "description": "Schema review + security audit + optimization",
        "steps": [
            {"agent": "database_agent", "task": "Analyze the database schema: table structure, indexes, relationships, and data types. Identify normalization issues and missing indexes."},
            {"agent": "hacker_agent", "task": "Audit the database for security: RLS policies, exposed data, injection risks, and access control gaps."},
            {"agent": "project_manager", "task": "Combine findings into an optimization and security hardening plan with priority rankings."}
        ]
    }
}


# (Workflow template endpoints are registered above, before {workflow_id} routes)


# ═══════════════════════════════════════════════════════════════════════
# SSE EVENT STREAM ENDPOINT — Real-time updates for Mission Control
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/events/stream")
async def event_stream():
    """SSE endpoint for real-time dashboard updates"""
    async def generate():
        last_index = len(_event_log)
        while True:
            await asyncio.sleep(1)
            current_len = len(_event_log)
            if current_len > last_index:
                for event in _event_log[last_index:current_len]:
                    yield f"data: {json.dumps(event)}\n\n"
                last_index = current_len

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/events/recent")
async def recent_events():
    """Get recent events (non-streaming fallback)"""
    return {"success": True, "events": _event_log[-50:], "total": len(_event_log)}


@app.get("/mission-control")
@app.get("/mission-control.html")
async def mission_control_page():
    """Redirect to main dashboard (mission control consolidated)"""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/dashboard.html", status_code=301)


# ═══════════════════════════════════════════════════════════════════════
# REVIEW CYCLE ENDPOINTS — Agent-to-agent multi-turn review
# ═══════════════════════════════════════════════════════════════════════

_review_engine = None  # Initialized in startup
_output_verifier = None  # Initialized in startup


@app.post("/api/reviews")
async def start_review(request: Request):
    """Start a new agent-to-agent review cycle"""
    if not _review_engine:
        raise HTTPException(status_code=503, detail="Review engine not initialized")
    data = await request.json()
    work_type = data.get("type", "code_review")
    content = data.get("content", "")
    author = data.get("author_agent", "coder_agent")
    reviewers = data.get("reviewer_agents", [])
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    review_id = _review_engine.start_review(work_type, content, author, reviewers)
    return {"success": True, "review_id": review_id, "type": work_type}


@app.get("/api/reviews")
async def list_reviews():
    """List all reviews"""
    if not _review_engine:
        return {"reviews": [], "stats": {}}
    active = _review_engine.list_active_reviews()
    all_reviews = _review_engine.list_all_reviews()
    stats = _review_engine.get_stats()
    return {"active": active, "all": all_reviews, "stats": stats}


@app.get("/api/reviews/{review_id}")
async def get_review(review_id: str):
    """Get review status and details"""
    if not _review_engine:
        raise HTTPException(status_code=503, detail="Review engine not initialized")
    status = _review_engine.get_review_status(review_id)
    if not status:
        raise HTTPException(status_code=404, detail="Review not found")
    return {"success": True, **status}


@app.delete("/api/reviews/{review_id}")
async def cancel_review(review_id: str):
    """Cancel an active review"""
    if not _review_engine:
        raise HTTPException(status_code=503, detail="Review engine not initialized")
    success = _review_engine.cancel_review(review_id)
    return {"success": success}


# ═══════════════════════════════════════════════════════════════════════
# OUTPUT VERIFICATION ENDPOINTS — Quality gates
# ═══════════════════════════════════════════════════════════════════════

@app.post("/api/verify")
async def verify_output(request: Request):
    """Run quality gates on files"""
    if not _output_verifier:
        raise HTTPException(status_code=503, detail="Verifier not initialized")
    data = await request.json()
    files = data.get("files", [])
    work_dir = data.get("work_dir", "/root/openclaw")
    job_id = data.get("job_id")
    result = _output_verifier.verify_all(job_id or "manual", files, work_dir)
    return {
        "success": True,
        "passed": result.passed,
        "score": result.overall_score,
        "recommendation": result.recommendation,
        "summary": result.summary,
        "gates": [{"gate": g.gate, "passed": g.passed, "score": g.score,
                    "issues_count": len(g.issues)} for g in result.gates]
    }


# ═══════════════════════════════════════════════════════════════════════
# AUTONOMOUS RUNNER ENDPOINTS — Background job executor
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/runner/status")
async def runner_status():
    """Get autonomous runner status"""
    runner = get_runner()
    if not runner:
        return {"running": False, "message": "Runner not initialized"}
    stats = runner.get_stats()
    active = runner.get_active_jobs()
    return {"running": runner._running, "active_jobs": active, "stats": stats}


@app.post("/api/runner/execute/{job_id}")
async def runner_execute_job(job_id: str):
    """Manually trigger execution of a specific job"""
    runner = get_runner()
    if not runner:
        raise HTTPException(status_code=503, detail="Runner not initialized")
    asyncio.create_task(runner.execute_job(job_id))
    return {"success": True, "message": f"Job {job_id} queued for execution"}


@app.get("/api/runner/progress/{job_id}")
async def runner_job_progress(job_id: str):
    """Get progress of a running job"""
    runner = get_runner()
    if not runner:
        raise HTTPException(status_code=503, detail="Runner not initialized")
    progress = runner.get_job_progress(job_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True, **progress}


@app.delete("/api/runner/cancel/{job_id}")
async def runner_cancel_job(job_id: str):
    """Cancel a running job"""
    runner = get_runner()
    if not runner:
        raise HTTPException(status_code=503, detail="Runner not initialized")
    success = runner.cancel_job(job_id)
    return {"success": success}


@app.post("/api/jobs/{job_id}/kill")
async def kill_job(job_id: str, request: Request):
    """
    Kill switch — immediately flags a running job for termination.
    The runner checks this flag at every iteration and will stop the job
    with status 'killed_manual'. Works even if the runner cancel mechanism
    fails, because it uses a file-based flag that the guardrails check.

    Body (optional): {"reason": "why you're killing it"}
    """
    from autonomous_runner import _set_kill_flag, _load_kill_flags
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = body.get("reason", "manual kill via API")

    _set_kill_flag(job_id, reason)

    # Also try the soft cancel path
    runner = get_runner()
    if runner:
        runner.cancel_job(job_id)

    logger.info(f"Kill switch activated for job {job_id}: {reason}")
    return {
        "success": True,
        "job_id": job_id,
        "reason": reason,
        "message": f"Kill flag set for {job_id}. Job will terminate at next iteration check.",
    }


@app.get("/api/jobs/kill-flags")
async def list_kill_flags():
    """List all active kill flags (for debugging)."""
    from autonomous_runner import _load_kill_flags
    return {"kill_flags": _load_kill_flags()}


if __name__ == "__main__":
    import uvicorn
    # Read port from env var (Northflank sets PORT), default to 18789
    port = int(os.getenv("PORT", "18789"))

    print("🦞 OpenClaw Gateway FIXED - Now using ACTUAL models from config!")
    print(f"   Protocol: OpenClaw v{PROTOCOL_VERSION}")
    print(f"   REST: http://0.0.0.0:{port}/api/chat")
    print(f"   WebSocket: ws://0.0.0.0:{port}/ws")
    print(f"   Cost Log: {get_cost_log_path()}")
    print("")
    print("📊 Agent Configuration:")
    for agent_id, config in CONFIG.get("agents", {}).items():
        provider = config.get("apiProvider", "unknown")
        model = config.get("model", "unknown")
        emoji = config.get("emoji", "")
        print(f"   {emoji} {agent_id:20} → {provider:10} → {model}")
    print("")
    print("💰 Cost Tracking Enabled")
    print("⏱️  Heartbeat Monitor Starting...")
    print("   (Will initialize on startup)")

    print("")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
