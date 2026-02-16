# 🔗 Connect OpenClaw to Cloudflare Worker

## 📊 Worker Info

**URL:** https://oversserclaw-worker.amit-shah-5201.workers.dev/
**Token:** `7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d`

---

## ⚠️ Current Status

**Worker Response:** Empty (worker may need configuration)

The worker is accessible but returning empty responses. This could mean:

1. Worker is not properly deployed
2. Worker needs specific endpoints configured
3. Worker expects different request format

---

## 🔧 What the Worker Should Do

Your Cloudflare Worker should act as a **proxy/bridge** between:

- **OpenClaw Gateway** (this VPS)
- **External clients** (web, mobile, etc.)

### Required Worker Endpoints:

```javascript
// 1. Health check
GET  /
→ {"status": "online", "gateway": "connected"}

// 2. Connect to OpenClaw
POST /connect
Body: {"gateway": "http://your-openclaw-gateway:18789"}
→ {"status": "connected"}

// 3. Proxy chat requests
POST /api/chat
Headers: Authorization: Bearer <token>
Body: {"content": "message", "agent_id": "project_manager"}
→ Forwards to OpenClaw, returns response

// 4. Proxy WebSocket
WS   /ws
→ Connects to OpenClaw WebSocket
```

---

## 📝 Worker Code Template

```javascript
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Validate token
    const token =
      url.searchParams.get("token") || request.headers.get("Authorization")?.replace("Bearer ", "");

    if (token !== env.OPENCLAW_TOKEN) {
      return new Response("Unauthorized", { status: 401 });
    }

    // Health check
    if (url.pathname === "/") {
      return new Response(
        JSON.stringify({
          status: "online",
          gateway: env.OPENCLAW_GATEWAY || "not configured",
        }),
        {
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    // Proxy to OpenClaw
    if (url.pathname.startsWith("/api/")) {
      const openclawUrl = `${env.OPENCLAW_GATEWAY}${url.pathname}`;
      const response = await fetch(openclawUrl, {
        method: request.method,
        headers: request.headers,
        body: request.method !== "GET" ? await request.text() : undefined,
      });
      return response;
    }

    return new Response("Not Found", { status: 404 });
  },
};
```

### Environment Variables Needed:

```bash
OPENCLAW_TOKEN=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d
OPENCLAW_GATEWAY=http://your-vps-ip:18789
```

---

## 🚀 Option A: Direct Connection (No Worker)

If the worker isn't working, connect directly to OpenClaw:

### 1. Expose OpenClaw via Cloudflare Tunnel

```bash
cd /root/openclaw
./setup-cloudflare-tunnel.sh
```

This will give you a stable URL like:

```
https://openclaw.yourdomain.com/
```

### 2. Or use ngrok

```bash
# Install ngrok
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | \
  sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && \
  echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | \
  sudo tee /etc/apt/sources.list.d/ngrok.list && \
  sudo apt update && sudo apt install ngrok

# Expose OpenClaw
ngrok http 18789
```

---

## 🚀 Option B: Fix the Worker

### On Your Local Machine (where the worker code is):

1. **Update worker code** with the template above
2. **Set environment variables:**

   ```bash
   wrangler secret put OPENCLAW_TOKEN
   # Enter: 7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d

   wrangler secret put OPENCLAW_GATEWAY
   # Enter: http://YOUR_VPS_IP:18789
   ```

3. **Deploy:**

   ```bash
   wrangler deploy
   ```

4. **Test:**
   ```bash
   curl "https://oversserclaw-worker.amit-shah-5201.workers.dev/?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d"
   # Should return: {"status":"online","gateway":"http://..."}
   ```

---

## 🔗 Connect OpenClaw to Worker

Once the worker is working, update OpenClaw configuration:

```bash
cd /root/openclaw
nano config.json
```

Add worker endpoint:

```json
{
  "worker": {
    "enabled": true,
    "url": "https://oversserclaw-worker.amit-shah-5201.workers.dev",
    "token": "7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d"
  }
}
```

Restart gateway:

```bash
fuser -k 18789/tcp && python3 gateway.py &
```

---

## 🧪 Test Connection

```bash
# Through worker
curl -X POST "https://oversserclaw-worker.amit-shah-5201.workers.dev/api/chat?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello!", "agent_id": "project_manager"}'

# Direct to OpenClaw
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello!", "agent_id": "project_manager"}'
```

---

## 📊 Architecture

```
[Client/Browser]
       ↓
[Cloudflare Worker] (proxy/auth)
       ↓ (forwards requests)
[OpenClaw Gateway] (this VPS:18789)
       ↓
[Claude API / Ollama]
```

---

## 🎯 Quick Fix Steps

1. **Check if worker is deployed:**
   - Go to Cloudflare Dashboard
   - Workers & Pages
   - Check "oversserclaw-worker" status

2. **View worker logs:**

   ```bash
   wrangler tail oversserclaw-worker
   ```

3. **Update worker code** with template above

4. **Set secrets** (token + gateway URL)

5. **Redeploy** and test

---

**Need the worker code?** Let me know and I'll create the complete Worker!
