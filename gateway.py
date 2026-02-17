"""
OpenClaw Gateway - ACTUALLY USES LOCAL MODELS
Fixed to properly route to Ollama based on config.json
WITH PERSISTENT MEMORY
"""

import os
import json
import asyncio
import uuid
import sys
import pathlib
from fastapi import FastAPI, WebSocket, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import anthropic
import requests
from dotenv import load_dotenv
import logging
from datetime import datetime

# Import orchestrator
from orchestrator import Orchestrator, AgentRole, Message as OrchMessage, MessageAudience

# Import cost tracker
from cost_tracker import log_cost_event, get_cost_metrics, get_cost_summary, get_cost_log_path

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

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("openclaw_gateway")

# Session persistence
SESSIONS_DIR = pathlib.Path(os.getenv("OPENCLAW_SESSIONS_DIR", "/tmp/openclaw_sessions"))
SESSIONS_DIR.mkdir(exist_ok=True)
logger.info(f"📁 Session storage: {SESSIONS_DIR}")

def load_session_history(session_key: str) -> list:
    """Load chat history for a session from disk"""
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

# Authentication token
AUTH_TOKEN = "f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3"

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Allow health check without auth
    if request.url.path == "/":
        return await call_next(request)

    # Check for token
    token = request.headers.get("X-Auth-Token") or request.query_params.get("token")

    if token != AUTH_TOKEN:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    return await call_next(request)

# Load config
with open('config.json', 'r') as f:
    CONFIG = json.load(f)

# Initialize Agent Router for intelligent task routing
agent_router = AgentRouter(config_path='config.json')

# Initialize Anthropic client
anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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
    try:
        config = HeartbeatMonitorConfig(
            check_interval_ms=30000,  # 30 seconds
            stale_threshold_ms=5 * 60 * 1000,  # 5 minutes
            timeout_threshold_ms=30 * 60 * 1000  # 30 minutes
        )
        monitor = await init_heartbeat_monitor(alert_manager=None, config=config)
        logger.info("✅ Heartbeat monitor initialized and started")
        return monitor
    except Exception as err:
        logger.error(f"Failed to initialize heartbeat monitor: {err}")
        return None


@app.on_event("shutdown")
async def shutdown_heartbeat_monitor():
    """Stop heartbeat monitor on FastAPI shutdown"""
    try:
        stop_heartbeat_monitor()
        logger.info("✅ Heartbeat monitor stopped")
    except Exception as err:
        logger.error(f"Failed to stop heartbeat monitor: {err}")

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
    else:
        raise ValueError(f"Unknown provider: {provider}")


def build_agent_system_prompt(agent_role: AgentRole) -> str:
    """Build system prompt with agent identity"""
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
    return base_prompt


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

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "operational",
        "gateway": "OpenClaw",
        "version": "2.0.0",
        "agents_active": len(CONFIG.get("agents", {})),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/dashboard.html")
async def dashboard():
    """Simple HTML dashboard"""
    return {
        "status": "ready",
        "dashboard_url": "Use /api/costs/summary for metrics",
        "endpoints": {
            "costs": "/api/costs/summary",
            "agents": "/api/agents",
            "chat": "POST /api/chat",
            "routing": "/api/route"
        }
    }


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

                        # Determine agent (default PM)
                        active_agent = "project_manager"

                        # Call CORRECT model
                        logger.info(f"🎯 Routing to agent: {active_agent}")
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


if __name__ == "__main__":
    import uvicorn
    print("🦞 OpenClaw Gateway FIXED - Now using ACTUAL models from config!")
    print(f"   Protocol: OpenClaw v{PROTOCOL_VERSION}")
    print("   WebSocket: ws://0.0.0.0:18789/ws")
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

    # Initialize heartbeat monitor for agent health checks
    _init_heartbeat_monitor()

    print("")
    uvicorn.run(app, host="0.0.0.0", port=18789, log_level="info")
