"""
OpenClaw Gateway Bridge - Proper Protocol Implementation
Connects OpenClaw UI to Python agents via proper OpenClaw protocol
"""

import os
import json
import asyncio
import uuid
import sys
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import anthropic
from dotenv import load_dotenv
import logging

# Import our orchestrator
from orchestrator import Orchestrator, AgentRole, Message as OrchMessage, MessageAudience

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("openclaw_gateway")

# Initialize Orchestrator for message routing and agent identity
orchestrator = Orchestrator()

app = FastAPI(title="OpenClaw Gateway", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Anthropic client
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Protocol version matching OpenClaw (MUST be 3)
PROTOCOL_VERSION = 3

# Timeout settings (seconds)
WS_RECEIVE_TIMEOUT = 120      # Max time to wait for a message from client
WS_PING_INTERVAL = 30         # How often to send keepalive pings
WS_PING_TIMEOUT = 10          # How long to wait for a pong reply

# Active connections tracking
active_connections: Dict[str, WebSocket] = {}

# Simple in-memory chat history (sessionKey -> list of messages)
chat_history: Dict[str, list] = {}

class Message(BaseModel):
    content: str
    agent_id: Optional[str] = "pm"


def build_agent_system_prompt(agent_role: AgentRole) -> str:
    """
    Build a comprehensive system prompt for an agent with:
    1. Their identity from the orchestrator
    2. Communication rules
    3. Capabilities and persona
    """
    # Get identity context from orchestrator
    identity_context = orchestrator.get_agent_context(agent_role)

    # Get agent config
    agent_config = orchestrator.config["agents"].get(agent_role.value, {})
    persona = agent_config.get("persona", "")
    skills = agent_config.get("skills", [])

    # Get workflow status
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

# ============================================
# REST API Endpoints (non-WebSocket)
# ============================================

@app.get("/")
async def root():
    return {
        "name": "OpenClaw Gateway",
        "version": "1.0.0",
        "status": "online",
        "agents": 3,
        "protocol": "OpenClaw v1"
    }

@app.get("/api/agents")
async def list_agents():
    """List all available agents"""
    return {
        "agents": [
            {"id": "pm", "name": "Project Manager", "model": "claude-sonnet-4-5-20250929", "role": "coordinator", "status": "idle"},
            {"id": "dev", "name": "Developer", "model": "ollama/qwen2.5-coder:14b", "role": "coder", "status": "idle"},
            {"id": "sec", "name": "Security Expert", "model": "ollama/qwen2.5:14b", "role": "security", "status": "idle"}
        ]
    }

@app.post("/api/chat")
async def chat_endpoint(message: Message):
    """Simple REST chat endpoint"""
    agent_id = message.agent_id or "pm"
    
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": message.content}]
        )

        return {
            "agent": agent_id,
            "response": response.content[0].text,
            "model": "claude-haiku-4-5-20251001"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# OpenClaw WebSocket Protocol Implementation
# ============================================

@app.websocket("/")
async def root_websocket(websocket: WebSocket):
    """Root WebSocket endpoint - delegate to main handler"""
    await handle_websocket(websocket)

@app.websocket("/ws")
async def ws_websocket(websocket: WebSocket):
    """Named WebSocket endpoint"""
    await handle_websocket(websocket)

async def _keepalive_ping(websocket: WebSocket, connection_id: str):
    """Send periodic pings to detect dead connections early."""
    try:
        while True:
            await asyncio.sleep(WS_PING_INTERVAL)
            try:
                await asyncio.wait_for(
                    websocket.send_json({"type": "pong"}),
                    timeout=WS_PING_TIMEOUT,
                )
            except (asyncio.TimeoutError, Exception):
                logger.warning(f"[WS] {connection_id} - Keepalive ping failed, closing")
                try:
                    await websocket.close(code=1000)
                except Exception:
                    pass
                return
    except asyncio.CancelledError:
        return


async def handle_websocket(websocket: WebSocket):
    """
    OpenClaw Gateway Protocol Implementation
    
    OpenClaw protocol flow:
    1. Client connects to WebSocket
    2. Client sends {type: "req", id: UUID, method: "connect", params: {...}}
    3. Gateway responds {type: "res", id: UUID, ok: true, payload: {hello-ok data}}
    4. Client can then send other req messages
    5. Gateway responds with res messages
    """
    
    await websocket.accept()
    connection_id = str(uuid.uuid4())
    active_connections[connection_id] = websocket
    ping_task: asyncio.Task | None = None
    
    logger.info(f"[WS] New connection: {connection_id}")
    
    try:
        # Wait for first message (should be a connect request)
        data = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=WS_RECEIVE_TIMEOUT,
        )
        msg = json.loads(data)
        msg_type = msg.get("type")
        
        logger.info(f"[WS] {connection_id} - First message type: {msg_type}, method: {msg.get('method')}")
        
        # Start keepalive ping task
        ping_task = asyncio.create_task(_keepalive_ping(websocket, connection_id))
        
        # Handle request messages
        while True:
            # If this is the first iteration and we already have the data
            if 'msg' not in locals() or msg is None:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WS_RECEIVE_TIMEOUT,
                )
                msg = json.loads(data)
            else:
                # Data is already loaded from previous iteration
                pass
            
            msg_type = msg.get("type")
            
            if msg_type == "req":
                request_id = msg.get("id")
                method = msg.get("method")
                params = msg.get("params", {})
                
                logger.info(f"[WS] {connection_id} - Request {request_id}: {method}")
                
                # Handle different methods
                if method == "connect":
                    # Connection request - respond with hello-ok
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
                    
                    response_frame = {
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": hello_ok_payload
                    }
                    
                    await websocket.send_json(response_frame)
                    logger.info(f"[WS] {connection_id} - Responded to connect request")
                
                elif method == "chat.send" or method == "chat":
                    # Handle chat.send with event-based response
                    run_id = params.get("idempotencyKey", str(uuid.uuid4()))
                    session_key = params.get("sessionKey", "main")
                    message_text = params.get("message", "")
                    
                    # 1. Immediately respond with "started" status
                    ack_response = {
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": {
                            "runId": run_id,
                            "status": "started"
                        }
                    }
                    await websocket.send_json(ack_response)
                    logger.info(f"[WS] {connection_id} - Ack chat.send: {run_id}")
                    
                    # 2. Process message and send events
                    try:
                        # Initialize session history if needed
                        if session_key not in chat_history:
                            chat_history[session_key] = []
                        
                        # Store user message
                        user_message = {
                            "role": "user",
                            "content": [{"type": "text", "text": message_text}],
                            "timestamp": int(asyncio.get_event_loop().time() * 1000)
                        }
                        chat_history[session_key].append(user_message)
                        
                        # Build conversation history for context
                        conversation = []
                        for msg in chat_history[session_key][-10:]:  # Last 10 messages for context
                            if msg["role"] == "user":
                                conversation.append({
                                    "role": "user",
                                    "content": msg["content"][0]["text"] if isinstance(msg["content"], list) else msg["content"]
                                })
                            elif msg["role"] == "assistant":
                                conversation.append({
                                    "role": "assistant",
                                    "content": msg["content"][0]["text"] if isinstance(msg["content"], list) else msg["content"]
                                })
                        
                        # Add current message if not already in history
                        if not conversation or conversation[-1]["content"] != message_text:
                            conversation.append({"role": "user", "content": message_text})
                        
                        # Determine which agent should handle this (for now, default to PM)
                        # TODO: Add agent routing logic based on message content
                        active_agent = AgentRole.PM

                        # Build agent-specific system prompt with identity
                        agent_system_prompt = build_agent_system_prompt(active_agent)

                        # Call Claude API with agent identity
                        response = client.messages.create(
                            model="claude-sonnet-4-5-20250929",  # Claude 4.5 Sonnet
                            max_tokens=2048,
                            system=agent_system_prompt,
                            messages=conversation
                        )
                        
                        assistant_text = response.content[0].text
                        timestamp = int(asyncio.get_event_loop().time() * 1000)
                        
                        # 3. Create and store assistant message
                        message_obj = {
                            "role": "assistant",
                            "content": [{"type": "text", "text": assistant_text}],
                            "timestamp": timestamp,
                            "stopReason": "end_turn",
                            "usage": {
                                "input": response.usage.input_tokens,
                                "output": response.usage.output_tokens,
                                "totalTokens": response.usage.input_tokens + response.usage.output_tokens
                            }
                        }
                        chat_history[session_key].append(message_obj)
                        
                        # 4. Send chat.final event with message
                        chat_event = {
                            "type": "event",
                            "event": "chat",
                            "payload": {
                                "runId": run_id,
                                "sessionKey": session_key,
                                "seq": 1,
                                "state": "final",
                                "message": message_obj
                            },
                            "seq": 1
                        }
                        
                        await websocket.send_json(chat_event)
                        logger.info(f"[WS] {connection_id} - Sent chat.final event for {run_id}")
                        
                    except Exception as e:
                        logger.error(f"[WS] {connection_id} - Chat error: {e}")
                        
                        # Send error event
                        error_event = {
                            "type": "event",
                            "event": "chat",
                            "payload": {
                                "runId": run_id,
                                "sessionKey": session_key,
                                "seq": 1,
                                "state": "error",
                                "errorMessage": str(e)
                            },
                            "seq": 1
                        }
                        await websocket.send_json(error_event)
                
                else:
                    # Other methods (agents, status, etc.)
                    result = await handle_request(method, params)
                    
                    response_frame = {
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": result
                    }
                    
                    await websocket.send_json(response_frame)
                    logger.info(f"[WS] {connection_id} - Responded to {method}")
            
            elif msg_type == "event":
                # Handle events if needed
                logger.info(f"[WS] {connection_id} - Event: {msg.get('event')}")
            
            elif msg_type == "ping":
                # Respond to ping
                await websocket.send_json({"type": "pong"})
            
            # Reset for next iteration
            msg = None
    
    except asyncio.TimeoutError:
        logger.warning(f"[WS] {connection_id} - Timed out after {WS_RECEIVE_TIMEOUT}s of inactivity, closing")
        try:
            await websocket.close(code=1000)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[WS] {connection_id} - Error: {type(e).__name__}: {e}")
        try:
            await websocket.close(code=1000)
        except Exception:
            pass
    
    finally:
        if ping_task is not None:
            ping_task.cancel()
        if connection_id in active_connections:
            del active_connections[connection_id]
        logger.info(f"[WS] {connection_id} - Disconnected")


async def handle_request(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Handle OpenClaw protocol requests"""
    
    logger.info(f"Handling method: {method}")
    
    # Chat-related methods
    if method == "chat" or method == "chat.send":
        # Chat request
        message = params.get("message", "")
        agent_id = params.get("agent_id", "pm")
        
        try:
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2048,
                messages=[{"role": "user", "content": message}]
            )
            
            return {
                "role": "assistant",
                "content": response.content[0].text,
                "agent_id": agent_id,
                "model": "claude-3-haiku-20240307",
                "timestamp": int(asyncio.get_event_loop().time() * 1000)
            }
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {"error": str(e), "agent_id": agent_id}
    
    elif method == "chat.history":
        # Return chat history for session
        session_key = params.get("sessionKey", "main")
        messages = chat_history.get(session_key, [])
        return {
            "messages": messages,
            "total": len(messages)
        }
    
    # Agent-related methods
    elif method == "agent.identity.get":
        # Return agent identity
        return {
            "id": "cybershield-agent",
            "name": "Cybershield AI Agency",
            "version": "1.0.0",
            "capabilities": ["chat", "code", "security"]
        }
    
    elif method == "agents.list" or method == "agents":
        # List agents
        return {
            "agents": [
                {"id": "pm", "name": "Project Manager", "role": "coordinator", "status": "idle", "model": "claude-3-haiku"},
                {"id": "dev", "name": "Developer", "role": "coder", "status": "idle", "model": "claude-3-haiku"},
                {"id": "sec", "name": "Security Expert", "role": "security", "status": "idle", "model": "claude-3-haiku"}
            ]
        }
    
    # Node/instance methods
    elif method == "node.list":
        # Return list of nodes (our single node)
        return {
            "nodes": [
                {
                    "id": "local",
                    "name": "Cybershield Gateway",
                    "status": "online",
                    "connections": len(active_connections)
                }
            ]
        }
    
    # Session methods
    elif method == "sessions.list":
        # Return sessions
        return {
            "sessions": [
                {
                    "id": "main",
                    "name": "Main Session",
                    "created": int(asyncio.get_event_loop().time() * 1000),
                    "active": True
                }
            ]
        }
    
    # Device pairing methods
    elif method == "device.pair.list":
        # Return paired devices (none for now)
        return {
            "devices": []
        }
    
    # System status
    elif method == "status":
        return {
            "status": "healthy",
            "connections": len(active_connections),
            "uptime": "running"
        }
    
    # Unknown method - return empty object (OpenClaw will handle gracefully)
    else:
        logger.warning(f"Unknown method: {method}")
        return {}


if __name__ == "__main__":
    import uvicorn
    print("🦞 OpenClaw Gateway starting on port 18789...")
    print(f"   Protocol: OpenClaw v{PROTOCOL_VERSION}")
    print("   WebSocket: ws://0.0.0.0:18789/ws")
    uvicorn.run(app, host="0.0.0.0", port=18789, log_level="info")
