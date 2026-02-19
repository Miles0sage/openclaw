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
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import anthropic
import requests
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime

# Import orchestrator
from orchestrator import Orchestrator, AgentRole, Message as OrchMessage, MessageAudience

# Import cost tracker
from cost_tracker import log_cost_event, get_cost_metrics, get_cost_summary, get_cost_log_path

# Import deepseek client
from request_logger import RequestLogger, get_logger
from audit_routes import router as audit_router

from deepseek_client import DeepseekClient

# Import agent tools (GitHub, web search, job management)
from agent_tools import AGENT_TOOLS, execute_tool

# Import quota manager
from quota_manager import (
    check_daily_quota,
    check_monthly_quota,
    check_queue_size,
    check_all_quotas,
    get_quota_status,
    load_quota_config,
)

# Import complexity classifier (intelligent router)
from complexity_classifier import (
    classify as classify_query,
    ClassificationResult,
    MODEL_PRICING,
    MODEL_ALIASES,
    MODEL_RATE_LIMITS,
)

# Import metrics system
from metrics import metrics

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

# Import agent registry (auto-registration system)
from agent_registry import (
    init_agent_registry,
    get_agent_registry,
    register_agents_from_config,
)


# Import metrics
from metrics_collector import init_metrics_collector, get_metrics_collector, record_metric
from gateway_metrics_integration import setup_metrics, MetricsMiddleware
from cost_gates import (
    get_cost_gates, init_cost_gates, check_cost_budget,
    record_cost, BudgetStatus
)

# Import closed-loop engines
from proposal_engine import create_proposal, get_proposal, list_proposals, update_proposal_status, estimate_cost
from approval_engine import evaluate_proposal, auto_approve_and_execute, get_policy
from event_engine import init_event_engine, get_event_engine
from cron_scheduler import init_cron_scheduler, get_cron_scheduler
from memory_manager import init_memory_manager, get_memory_manager

load_dotenv()

# Slack Configuration
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_REPORT_CHANNEL = os.getenv("SLACK_REPORT_CHANNEL", "#general")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("openclaw_gateway")

# Session persistence - v2
SESSIONS_DIR = pathlib.Path(os.getenv("OPENCLAW_SESSIONS_DIR", "/tmp/openclaw_sessions"))
SESSIONS_DIR.mkdir(exist_ok=True)
logger.info(f"📁 Session storage: {SESSIONS_DIR}")

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
    """Call Claude with tool_use support. Loops until text response or max rounds."""
    for _ in range(max_rounds):
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=system_prompt,
            messages=messages,
            tools=AGENT_TOOLS
        )

        # Collect all tool uses and text blocks
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if not tool_uses:
            # No tool calls — return the text
            return text_blocks[0].text if text_blocks else "No response"

        # Execute tools and build tool_result messages
        # First add the assistant message with tool_use blocks
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tu in tool_uses:
            logger.info(f"🔧 Tool call: {tu.name}({json.dumps(tu.input)[:100]})")
            result = execute_tool(tu.name, tu.input)
            logger.info(f"🔧 Tool result: {result[:100]}...")
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

# Initialize and setup metrics
init_metrics_collector()
static_dir = os.path.join(os.path.dirname(__file__), 'src', 'static')
setup_metrics(app, static_dir=static_dir)

# Include audit routes
app.include_router(audit_router)
# Authentication token - read from environment for security
AUTH_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN", "f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # WEBHOOK & DASHBOARD EXEMPTIONS: Allow without auth
    exempt_paths = ["/", "/health", "/metrics", "/test-exempt", "/dashboard.html", "/telegram/webhook", "/slack/events", "/api/audit"]
    path = request.url.path

    # Dashboard APIs exempt from auth (for monitoring UI)
    dashboard_exempt_prefixes = ["/api/costs", "/api/heartbeat", "/api/quotas", "/api/agents", "/api/route/health", "/api/proposal", "/api/proposals", "/api/policy", "/api/events", "/api/memories", "/api/memory", "/api/cron"]

    # Debug logging (for troubleshooting only)
    is_exempt = (path in exempt_paths or
                 path.startswith(("/telegram/", "/slack/", "/api/audit")) or
                 any(path.startswith(prefix) for prefix in dashboard_exempt_prefixes))
    logger.info(f"AUTH_CHECK: path={path}, is_exempt={is_exempt}")

    # Exempt webhook paths
    if is_exempt:
        logger.info(f"✅ EXEMPT: {path}")
        return await call_next(request)

    # Check auth token
    token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
    if token != AUTH_TOKEN:
        logger.warning(f"❌ AUTH FAILED: {path} (no valid token)")
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    logger.info(f"✅ AUTH OK: {path}")
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

# Load config
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

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
chat_history: Dict[str, list] = {}

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


@app.on_event("shutdown")
async def shutdown_heartbeat_monitor():
    """Stop heartbeat monitor on FastAPI shutdown"""
    try:
        stop_heartbeat_monitor()
        logger.info("✅ Heartbeat monitor stopped")
    except Exception as err:
        logger.error(f"Failed to stop heartbeat monitor: {err}")

    try:
        cron = get_cron_scheduler()
        if cron:
            cron.stop()
        logger.info("✅ Cron scheduler stopped")
    except Exception as err:
        logger.error(f"Failed to stop cron scheduler: {err}")

# Load existing sessions from disk
def _load_all_sessions():
    """Load all existing sessions from disk on startup"""
    for session_file in SESSIONS_DIR.glob("*.json"):
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
                session_key = data.get('session_key', session_file.stem)
                chat_history[session_key] = data.get('messages', [])
                logger.info(f"✅ Restored session {session_key}: {len(chat_history[session_key])} messages")
        except Exception as e:
            logger.warning(f"Failed to load {session_file}: {e}")

_load_all_sessions()
logger.info(f"🎉 Loaded {len(chat_history)} sessions from disk")


class Message(BaseModel):
    content: str
    agent_id: Optional[str] = "pm"
    sessionKey: Optional[str] = None  # Support session memory
    project_id: Optional[str] = None  # For quota tracking


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

    # Full system prompt for Anthropic (handles long prompts well)
    anthropic_system = f"""You are {name} {emoji} in the Cybershield AI Agency.

{persona}

IMPORTANT RULES:
- ALWAYS end your messages with your signature: {signature}
- Be playful but professional
- Follow your character consistently
- Use emojis naturally

Remember: You ARE {name}. Stay in character!"""

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
        # For Anthropic, use system parameter
        if conversation:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=4096,
                system=anthropic_system,
                messages=conversation
            )
            response_text = response.content[0].text
            tokens_input = response.usage.input_tokens
            tokens_output = response.usage.output_tokens
        else:
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=4096,
                system=anthropic_system,
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
                max_tokens=4096,
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
    """Health check showing ACTUAL model configuration"""
    return {
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
    }

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

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "operational",
        "gateway": "OpenClaw-FIXED-2026-02-18",
        "version": "2.0.2-DEBUG-LOGGING",
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
        model = agent_config.get("model", "claude-3-5-sonnet-20241022")
        
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
        if session_key not in chat_history:
            chat_history[session_key] = load_session_history(session_key)

        # Add user message to history
        chat_history[session_key].append({
            "role": "user",
            "content": message.content
        })

        # Call model with last 10 messages for context
        response_text, tokens = call_model_for_agent(
            agent_id,
            message.content,
            chat_history[session_key][-10:]
        )

        # Record metrics
        metrics.record_agent_call(agent_id)
        metrics.record_session(session_key)

        # Update activity after getting response
        if heartbeat:
            heartbeat.update_activity(agent_id)

        # Add assistant response to history
        chat_history[session_key].append({
            "role": "assistant",
            "content": response_text
        })

        # Save session to disk
        save_session_history(session_key, chat_history[session_key])

        agent_config = get_agent_config(agent_id)

        return {
            "agent": agent_id,
            "response": response_text,
            "provider": agent_config.get("apiProvider"),
            "model": agent_config.get("model"),
            "tokens": tokens,
            "sessionKey": session_key,
            "historyLength": len(chat_history[session_key])
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Unregister agent when done
        if heartbeat:
            heartbeat.unregister_agent(agent_id)


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
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")

        # Verify Slack signature (security best practice)
        if SLACK_SIGNING_SECRET:
            # Check timestamp is within 5 minutes (prevent replay attacks)
            try:
                request_time = int(timestamp)
                current_time = int(time.time())
                if abs(current_time - request_time) > 300:
                    logger.warning("⚠️  Slack request timestamp too old (replay attack?)")
                    return JSONResponse({"error": "Invalid timestamp"}, status_code=403)
            except ValueError:
                logger.warning("⚠️  Invalid timestamp from Slack")
                return JSONResponse({"error": "Invalid timestamp"}, status_code=403)

            # Verify signature
            sig_basestring = f"v0:{timestamp}:{body_bytes.decode()}"
            expected_signature = "v0=" + hmac.new(
                SLACK_SIGNING_SECRET.encode(),
                sig_basestring.encode(),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_signature, signature):
                logger.warning("⚠️  Invalid Slack signature")
                return JSONResponse({"error": "Invalid signature"}, status_code=403)

        payload = json.loads(body_bytes)

        # Handle URL verification challenge (Slack requires this)
        if payload.get("type") == "url_verification":
            logger.info("✅ Slack verification challenge received")
            return {"challenge": payload.get("challenge")}

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
        summary = get_cost_summary()
        message = f"""💰 *Cost Summary*

Daily: ${summary.get('daily_total', 0):.2f} / $20.00
Monthly: ${summary.get('monthly_total', 0):.2f} / $1000.00

*Top Agents:*"""

        for agent, cost in list(summary.get('by_agent', {}).items())[:5]:
            message += f"\n  • {agent}: ${cost:.4f}"

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
            message = "⚠️  Heartbeat monitor not initialized"
        else:
            agent_statuses = monitor.agent_health_status()
            healthy = sum(1 for s in agent_statuses.values() if s.get("status") == "healthy")
            total = len(agent_statuses)

            message = f"""🏥 *Gateway Health*

Agents: {healthy}/{total} healthy
Active Sessions: {len(SESSIONS_DIR.glob('*.json'))}
API Status: ✅ OK"""

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
                        if session_key not in chat_history:
                            chat_history[session_key] = []

                        chat_history[session_key].append({
                            "role": "user",
                            "content": message_text
                        })

                        # Determine agent using intelligent routing
                        route_decision = agent_router.select_agent(message_text)
                        active_agent = route_decision["agentId"]

                        # Call CORRECT model
                        logger.info(f"🎯 Routing to agent: {active_agent} ({route_decision['reason']})")
                        response_text, tokens = call_model_for_agent(
                            active_agent,
                            message_text,
                            chat_history[session_key][-10:]  # Last 10 messages
                        )

                        timestamp = int(asyncio.get_event_loop().time() * 1000)

                        chat_history[session_key].append({
                            "role": "assistant",
                            "content": response_text
                        })

                        # Save session to disk
                        save_session_history(session_key, chat_history[session_key])

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
async def api_get_events(limit: int = 50, event_type: Optional[str] = None):
    """Get recent events"""
    try:
        engine = get_event_engine()
        if not engine:
            return {"events": [], "total": 0}
        events = engine.get_recent_events(limit=limit, event_type=event_type)
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
