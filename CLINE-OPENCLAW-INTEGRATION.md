# 🔌 Cline ↔ OpenClaw Integration Guide

**Connect Cline (VS Code AI Assistant) to your OpenClaw multi-agent system!**

---

## 🎯 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                       VS Code + Cline                        │
│                                                              │
│  ┌──────────────┐      ┌──────────────────────────┐        │
│  │    Cline     │◄────►│  OpenClaw Skill/Plugin   │        │
│  │  Extension   │      │  (HTTP/WebSocket Client) │        │
│  └──────────────┘      └──────────────────────────┘        │
└────────────────────────────────┬─────────────────────────────┘
                                 │
                          HTTP/WebSocket
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenClaw Instance #1                        │
│                   (Gateway: 18789)                           │
│                                                              │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐           │
│  │   PM   │  │  Coder │  │Security│  │ Cline  │  ← New!   │
│  │  🎯   │  │  💻   │  │  🔒   │  │  📝   │           │
│  └────────┘  └────────┘  └────────┘  └────────┘           │
└────────────────────────┬─────────────────────────────────────┘
                         │
                  Gateway Protocol
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  OpenClaw Instance #2                        │
│                   (Gateway: 18790)                           │
│                                                              │
│  ┌────────┐  ┌────────┐  ┌────────┐                        │
│  │Research│  │ Deploy │  │ Monitor│                        │
│  │  🔍   │  │  🚀   │  │  📊   │                        │
│  └────────┘  └────────┘  └────────┘                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Prerequisites

### 1. Install VS Code

```bash
# Download from https://code.visualstudio.com/
# Or via package manager:
sudo snap install code --classic  # Linux
brew install --cask visual-studio-code  # macOS
```

### 2. Install Cline Extension

```bash
# Open VS Code
# Press Ctrl+P (Cmd+P on Mac)
# Type: ext install saoudrizwan.claude-dev
# Or search "Cline" in Extensions marketplace
```

### 3. OpenClaw Running

```bash
# Verify gateway is running
curl http://localhost:18789/

# If not running:
cd /root/openclaw
python3 gateway.py &
```

---

## 🚀 Option 1: Direct HTTP Integration (Quick Start)

### Step 1: Create Cline Skill for OpenClaw

Create `/root/openclaw/skills/cline-integration/SKILL.md`:

````markdown
---
name: cline_integration
description: Integrates with Cline VS Code extension for code editing
metadata:
  openclaw:
    requires:
      bins: ["curl"]
      env: ["OPENCLAW_GATEWAY_URL"]
---

# Cline Integration Skill

This skill allows OpenClaw agents to communicate with Cline running in VS Code.

## Available Commands

### Send Code to Cline

When you need to send code or instructions to Cline in VS Code, use this pattern:

**User:** "Send this code to Cline: [code block]"

**Action:**

1. Format the code properly
2. Send via HTTP POST to OpenClaw gateway endpoint
3. Cline picks it up via polling or webhook

## Example Usage

**Agent:** "I'll send this to Cline for implementation..."

```bash
curl -X POST http://localhost:18789/api/cline/send \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Implement user authentication",
    "code": "// your code here",
    "agent": "CodeGen Pro"
  }'
```
````

## Configuration

Set environment variable:

```bash
export OPENCLAW_GATEWAY_URL="http://localhost:18789"
```

````

### Step 2: Create OpenClaw Plugin for Cline

Create `/root/openclaw/cline-plugin/index.ts`:

```typescript
/**
 * Cline Integration Plugin for OpenClaw
 * Allows Cline to interact with OpenClaw agents
 */

import { Type } from "@sinclair/typebox";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

export default function (api: OpenClawPluginApi) {
  // Store pending messages for Cline to poll
  const clineQueue: Array<{
    id: string;
    timestamp: number;
    agent: string;
    message: string;
    code?: string;
  }> = [];

  // Tool: Send message to Cline
  api.registerTool({
    name: "cline_send",
    description: "Send a message or code snippet to Cline in VS Code",
    parameters: Type.Object({
      message: Type.String({ description: "Message to send to Cline" }),
      code: Type.Optional(Type.String({ description: "Code snippet to send" })),
      action: Type.Optional(Type.String({
        description: "Action for Cline to take: edit, review, implement, debug",
        enum: ["edit", "review", "implement", "debug"]
      }))
    }),
    async execute(_id, params) {
      const messageId = `msg_${Date.now()}`;

      clineQueue.push({
        id: messageId,
        timestamp: Date.now(),
        agent: "CodeGen Pro",
        message: params.message,
        code: params.code
      });

      return {
        content: [{
          type: "text",
          text: `Message queued for Cline (ID: ${messageId})`
        }]
      };
    }
  });

  // Tool: Get messages from OpenClaw (for Cline to poll)
  api.registerTool({
    name: "cline_receive",
    description: "Cline polls this to receive messages from OpenClaw agents",
    parameters: Type.Object({
      since: Type.Optional(Type.Number({ description: "Timestamp to get messages after" }))
    }),
    async execute(_id, params) {
      const since = params.since || 0;
      const messages = clineQueue.filter(m => m.timestamp > since);

      return {
        content: [{
          type: "text",
          text: JSON.stringify(messages, null, 2)
        }]
      };
    }
  });

  // Gateway HTTP endpoint for Cline to call
  api.registerHttpHandler(async (req, res) => {
    if (req.method === "POST" && req.url === "/api/cline/send") {
      const body = await readRequestBody(req);
      const data = JSON.parse(body);

      clineQueue.push({
        id: `msg_${Date.now()}`,
        timestamp: Date.now(),
        agent: data.agent || "Unknown",
        message: data.message,
        code: data.code
      });

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, queued: clineQueue.length }));
      return true;
    }

    if (req.method === "GET" && req.url?.startsWith("/api/cline/poll")) {
      const url = new URL(req.url, `http://${req.headers.host}`);
      const since = parseInt(url.searchParams.get("since") || "0");

      const messages = clineQueue.filter(m => m.timestamp > since);

      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, messages }));
      return true;
    }

    return false;  // Not handled
  });

  // Gateway WebSocket method
  api.registerGatewayMethod("cline.status", ({ respond }) => {
    respond(true, {
      ok: true,
      queueSize: clineQueue.length,
      latestMessage: clineQueue[clineQueue.length - 1]
    });
  });
}

function readRequestBody(req: any): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk: Buffer) => {
      body += chunk.toString();
    });
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}
````

Create `/root/openclaw/cline-plugin/openclaw.plugin.json`:

```json
{
  "id": "cline",
  "configSchema": {
    "type": "object",
    "properties": {
      "enabled": {
        "type": "boolean",
        "default": true
      },
      "pollInterval": {
        "type": "number",
        "default": 5000,
        "description": "How often Cline polls for messages (ms)"
      }
    }
  },
  "skills": ["./skills"]
}
```

### Step 3: Install Plugin in OpenClaw

```bash
# Create plugins directory
mkdir -p ~/.openclaw/extensions/cline

# Copy plugin
cp -r /root/openclaw/cline-plugin/* ~/.openclaw/extensions/cline/

# Restart gateway
fuser -k 18789/tcp
cd /root/openclaw && python3 gateway.py &
```

### Step 4: Configure Cline to Poll OpenClaw

Create VS Code task in `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Poll OpenClaw for Messages",
      "type": "shell",
      "command": "while true; do curl -s http://localhost:18789/api/cline/poll?since=$(date +%s)000 | jq; sleep 5; done",
      "isBackground": true,
      "problemMatcher": [],
      "presentation": {
        "reveal": "always",
        "panel": "dedicated"
      }
    }
  ]
}
```

### Step 5: Test Integration

```bash
# Send a message from OpenClaw to Cline
curl -X POST http://localhost:18789/api/cline/send \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "CodeGen Pro",
    "message": "Please implement user authentication",
    "code": "// Add JWT authentication here",
    "action": "implement"
  }'

# Cline polls and receives:
# {
#   "ok": true,
#   "messages": [
#     {
#       "id": "msg_1770637890123",
#       "timestamp": 1770637890123,
#       "agent": "CodeGen Pro",
#       "message": "Please implement user authentication",
#       "code": "// Add JWT authentication here"
#     }
#   ]
# }
```

---

## 🚀 Option 2: WebSocket Real-Time Integration (Advanced)

### Step 1: Create WebSocket Bridge

Create `/root/openclaw/cline-ws-bridge.js`:

```javascript
/**
 * WebSocket Bridge between Cline and OpenClaw
 * Runs as a separate service
 */

const WebSocket = require("ws");
const http = require("http");

// Connect to OpenClaw Gateway
const openclawWs = new WebSocket("ws://localhost:18789/ws");

// Create WebSocket server for Cline
const wss = new WebSocket.Server({ port: 8765 });

let clineClient = null;

// Handle OpenClaw connection
openclawWs.on("open", () => {
  console.log("✅ Connected to OpenClaw Gateway");

  // Send connect message
  openclawWs.send(
    JSON.stringify({
      type: "req",
      id: "connect-1",
      method: "connect",
      params: {
        minProtocol: 3,
        maxProtocol: 3,
        client: {
          id: "cline-bridge",
          version: "1.0.0",
          platform: "vscode",
        },
        role: "node",
        caps: ["code-edit"],
        auth: {},
      },
    }),
  );
});

openclawWs.on("message", (data) => {
  const msg = JSON.parse(data.toString());
  console.log("← OpenClaw:", msg.type, msg.method || msg.event);

  // Forward to Cline if connected
  if (clineClient && clineClient.readyState === WebSocket.OPEN) {
    clineClient.send(
      JSON.stringify({
        source: "openclaw",
        data: msg,
      }),
    );
  }
});

// Handle Cline connections
wss.on("connection", (ws) => {
  console.log("✅ Cline connected");
  clineClient = ws;

  ws.on("message", (data) => {
    const msg = JSON.parse(data.toString());
    console.log("← Cline:", msg);

    // Forward to OpenClaw
    if (openclawWs.readyState === WebSocket.OPEN) {
      openclawWs.send(
        JSON.stringify({
          type: "req",
          id: `cline-${Date.now()}`,
          method: "chat.send",
          params: {
            message: msg.message || msg.text,
            sessionKey: "cline",
          },
        }),
      );
    }
  });

  ws.on("close", () => {
    console.log("❌ Cline disconnected");
    clineClient = null;
  });
});

console.log("🌉 Cline ↔ OpenClaw Bridge running");
console.log("   OpenClaw: ws://localhost:18789/ws");
console.log("   Cline:    ws://localhost:8765");
```

### Step 2: Run the Bridge

```bash
# Install dependencies
npm install ws

# Run bridge
node cline-ws-bridge.js &

# Verify
curl http://localhost:8765
```

### Step 3: Configure Cline Extension

In VS Code, create `.vscode/settings.json`:

```json
{
  "cline.customInstructions": "You are connected to OpenClaw multi-agent system. You can collaborate with:\n- 🎯 Cybershield PM (project manager)\n- 💻 CodeGen Pro (developer)\n- 🔒 Pentest AI (security)\n\nWhen you receive messages from these agents, implement their requests and send updates back.",
  "cline.apiProvider": "anthropic",
  "cline.apiKey": "${ANTHROPIC_API_KEY}",
  "cline.enableWebSocket": true,
  "cline.webSocketUrl": "ws://localhost:8765"
}
```

---

## 🔄 Option 3: Multiple OpenClaw Instances (Agent-to-Agent)

### Architecture

```
Instance #1 (Port 18789)          Instance #2 (Port 18790)
┌─────────────────────┐          ┌─────────────────────┐
│  PM, Coder, Security│◄────────►│ Research, Deploy    │
└─────────────────────┘          └─────────────────────┘
         ▲                                   ▲
         │                                   │
         └───────────┬───────────────────────┘
                     │
              Cline (VS Code)
```

### Step 1: Configure Second OpenClaw Instance

```bash
# Create second instance directory
mkdir -p /root/openclaw-instance2
cd /root/openclaw-instance2

# Copy files
cp /root/openclaw/gateway.py .
cp /root/openclaw/orchestrator.py .
cp /root/openclaw/config.json .

# Edit config.json - change port to 18790
sed -i 's/"port": 8000/"port": 8001/g' config.json

# Add new agents (Research, Deploy, Monitor)
```

Edit `/root/openclaw-instance2/config.json`:

```json
{
  "name": "OpenClaw DevOps Team",
  "version": "1.0.0",
  "port": 18790,
  "agents": {
    "research_agent": {
      "name": "Research Bot",
      "emoji": "🔍",
      "model": "ollama/qwen2.5:14b",
      "persona": "I research technologies and provide summaries",
      "signature": "— 🔍 Research Bot"
    },
    "deploy_agent": {
      "name": "Deploy Bot",
      "emoji": "🚀",
      "model": "ollama/qwen2.5:14b",
      "persona": "I handle deployments and CI/CD",
      "signature": "— 🚀 Deploy Bot"
    },
    "monitor_agent": {
      "name": "Monitor Bot",
      "emoji": "📊",
      "model": "ollama/qwen2.5:14b",
      "persona": "I monitor systems and alert on issues",
      "signature": "— 📊 Monitor Bot"
    }
  }
}
```

### Step 2: Start Second Instance

```bash
cd /root/openclaw-instance2
nohup python3 gateway.py > gateway2.log 2>&1 &

# Verify
curl http://localhost:18790/
```

### Step 3: Create Instance-to-Instance Bridge

Create `/root/openclaw/instance-bridge.py`:

```python
"""
Bridge between two OpenClaw instances
Allows agents from different instances to communicate
"""

import asyncio
import websockets
import json
from typing import Dict, Any

# Instance configurations
INSTANCE_1 = {
    "url": "ws://localhost:18789/ws",
    "name": "Coding Team"
}

INSTANCE_2 = {
    "url": "ws://localhost:18790/ws",
    "name": "DevOps Team"
}


async def connect_and_forward(source_config: Dict, target_ws):
    """Connect to source instance and forward messages to target"""
    async with websockets.connect(source_config["url"]) as ws:
        print(f"✅ Connected to {source_config['name']}")

        # Send connect message
        await ws.send(json.dumps({
            "type": "req",
            "id": "connect-bridge",
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "instance-bridge",
                    "version": "1.0.0"
                },
                "role": "node"
            }
        }))

        # Forward messages
        async for message in ws:
            msg = json.loads(message)

            # Only forward chat messages
            if msg.get("type") == "event" and msg.get("event") == "chat":
                print(f"📨 Forwarding from {source_config['name']}")

                # Send to target instance
                if target_ws:
                    await target_ws.send(json.dumps({
                        "type": "req",
                        "id": f"fwd-{asyncio.get_event_loop().time()}",
                        "method": "chat.send",
                        "params": {
                            "message": f"[From {source_config['name']}] {msg['payload']['message']}",
                            "sessionKey": "bridge"
                        }
                    }))


async def bridge():
    """Main bridge loop"""
    print("🌉 Starting Instance Bridge...")

    # Connect to both instances
    ws1 = await websockets.connect(INSTANCE_1["url"])
    ws2 = await websockets.connect(INSTANCE_2["url"])

    # Bidirectional forwarding
    await asyncio.gather(
        connect_and_forward(INSTANCE_1, ws2),
        connect_and_forward(INSTANCE_2, ws1)
    )


if __name__ == "__main__":
    asyncio.run(bridge())
```

### Step 4: Run the Bridge

```bash
pip3 install websockets
python3 instance-bridge.py &

# Now messages from Instance 1 agents will appear in Instance 2 and vice versa!
```

---

## 🎯 Complete Integration Example

### Scenario: Cline → OpenClaw → Multi-Instance Workflow

1. **User in VS Code (Cline):** "Build a user authentication API"

2. **Cline** processes and sends to OpenClaw Instance 1:

   ```json
   {
     "message": "Need user authentication API with JWT",
     "context": "FastAPI project"
   }
   ```

3. **Cybershield PM (Instance 1)** receives and delegates:

   ```
   @CodeGen-Pro 💻 Cline needs auth API. Please implement!

   — 🎯 Cybershield PM
   ```

4. **CodeGen Pro** implements:

   ```python
   # Generated code...
   ```

5. **Message forwarded to Instance 2** via bridge

6. **Deploy Bot (Instance 2)** receives and deploys:

   ```
   🚀 Deploying auth API to staging...

   — 🚀 Deploy Bot
   ```

7. **Result sent back to Cline** via WebSocket bridge

8. **Cline** applies code to VS Code workspace

**Complete automated workflow!** 🎉

---

## 📊 Monitoring & Debugging

### Check Bridge Status

```bash
# View logs
tail -f /root/openclaw/cline-ws-bridge.log
tail -f /root/openclaw/instance-bridge.log

# Test connectivity
curl http://localhost:18789/  # Instance 1
curl http://localhost:18790/  # Instance 2
curl http://localhost:8765/   # Cline bridge
```

### Debug WebSocket Messages

```bash
# Monitor Instance 1
websocat ws://localhost:18789/ws

# Monitor Instance 2
websocat ws://localhost:18790/ws

# Monitor Cline bridge
websocat ws://localhost:8765
```

---

## 🎮 Usage Examples

### Example 1: Ask Cline to Implement via OpenClaw

In Telegram (connected to OpenClaw Instance 1):

```
@CodeGen-Pro 💻 Send this to Cline for implementation:

Create a REST API endpoint for user registration with:
- Email validation
- Password hashing (bcrypt)
- JWT token generation
- PostgreSQL storage

— User
```

CodeGen Pro calls `cline_send` tool → Cline receives → implements in VS Code!

### Example 2: Cline Asks OpenClaw Security for Review

Cline sends via WebSocket:

```json
{
  "action": "review",
  "code": "// Auth code here",
  "agent": "Pentest AI"
}
```

OpenClaw routes to Security agent → Security reviews → sends findings back to Cline!

### Example 3: Multi-Instance Research + Deploy

User in Cline: "Research best Node.js logging libraries and deploy winner"

1. **Research Bot (Instance 2)** researches options
2. **Cybershield PM (Instance 1)** coordinates
3. **CodeGen Pro (Instance 1)** implements winner
4. **Deploy Bot (Instance 2)** deploys to staging
5. **Monitor Bot (Instance 2)** watches metrics

All automatic via bridge!

---

## 🔒 Security Considerations

1. **Authentication:**

   ```bash
   # Add auth to bridge endpoints
   export BRIDGE_AUTH_TOKEN="your-secret-token"
   ```

2. **Rate Limiting:**

   ```javascript
   // In bridge code
   const rateLimit = require("express-rate-limit");
   ```

3. **Firewall:**
   ```bash
   # Only allow localhost
   sudo ufw allow from 127.0.0.1 to any port 8765
   sudo ufw allow from 127.0.0.1 to any port 18790
   ```

---

## 🎊 Summary

You now have:

✅ **Cline integrated** with OpenClaw agents
✅ **Multiple OpenClaw instances** communicating
✅ **WebSocket bridges** for real-time communication
✅ **HTTP endpoints** for polling
✅ **Complete workflow** automation

**Architecture:**

```
Cline (VS Code)
    ↕ WebSocket/HTTP
OpenClaw Instance 1 (Coding Team)
    ↕ Bridge
OpenClaw Instance 2 (DevOps Team)
    ↕
Your Phone (Telegram)
```

**Next Steps:**

1. Install Cline in VS Code
2. Run the bridge script
3. Test with a simple message
4. Scale to multiple instances

Happy coding! 🦞✨
