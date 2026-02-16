# 🎉 Cloudflare Worker CONNECTED!

**Status**: ✅ **FULLY OPERATIONAL**
**Date**: 2026-02-09 13:09 UTC

---

## 🌐 Worker URLs

### ✅ Working Worker (NEW)

**URL**: https://openclaw-gateway-public.amit-shah-5201.workers.dev
**Token**: `7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d`
**Status**: ✅ ONLINE

### ⚠️ Old Worker (Blocked by Cloudflare Access)

**URL**: https://oversserclaw-worker.amit-shah-5201.workers.dev
**Status**: ❌ Blocked by Cloudflare Access
**Fix**: Disable Access in Zero Trust settings

---

## 🚀 How to Use

### Health Check

```bash
curl "https://openclaw-gateway-public.amit-shah-5201.workers.dev/?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d"
```

**Expected Response:**

```json
{
  "status": "online",
  "worker": "oversserclaw-worker",
  "gateway": "http://152.53.55.207:18789",
  "timestamp": "2026-02-09T13:09:13.350Z"
}
```

### Talk to CodeGen Pro (GPU 32B)

```bash
curl "https://openclaw-gateway-public.amit-shah-5201.workers.dev/api/chat?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"content":"Build a FastAPI login endpoint","agent_id":"coder_agent"}'
```

### Talk to Pentest AI (GPU 14B)

```bash
curl "https://openclaw-gateway-public.amit-shah-5201.workers.dev/api/chat?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"content":"Find security issues in: eval(user_input)","agent_id":"hacker_agent"}'
```

### Talk to Cybershield PM (Claude Sonnet)

```bash
curl "https://openclaw-gateway-public.amit-shah-5201.workers.dev/api/chat?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"content":"Plan a restaurant booking website","agent_id":"project_manager"}'
```

---

## 📊 Architecture

```
┌────────────────────────────────────────┐
│  Cloudflare Worker (Edge Network)     │
│  openclaw-gateway-public               │
│  https://...workers.dev                │
└─────────────────┬──────────────────────┘
                  │
                  │ HTTPS + Token Auth
                  │
                  ▼
┌─────────────────────────────────────────┐
│  OpenClaw Gateway (VPS)                 │
│  152.53.55.207:18789                    │
│  ├─ 🎯 PM: Claude Sonnet (Cloud)        │
│  ├─ 💻 Coder: Qwen 32B (GPU)            │
│  └─ 🔒 Security: Qwen 14B (GPU)         │
└─────────────────────────────────────────┘
```

---

## 🔐 Security

**Token Authentication**: Every request requires the token parameter

- Query string: `?token=YOUR_TOKEN`
- Header: `Authorization: Bearer YOUR_TOKEN`

**CORS**: Enabled for all origins (\*)

**Secrets** (Stored in Cloudflare):

- `OPENCLAW_TOKEN`: Your authentication token
- `OPENCLAW_GATEWAY`: http://152.53.55.207:18789

---

## 🛠️ Worker Configuration

**File**: `/root/openclaw/wrangler.toml`

```toml
name = "openclaw-gateway-public"
main = "cloudflare-worker.js"
compatibility_date = "2024-01-01"

[vars]
WORKER_VERSION = "1.0.0"
```

**Secrets**:

```bash
wrangler secret put OPENCLAW_TOKEN
wrangler secret put OPENCLAW_GATEWAY
```

---

## 🔄 Update Worker

```bash
cd /root/openclaw
export CLOUDFLARE_API_TOKEN="your-token"
wrangler deploy
```

---

## 📝 Example: Complete Workflow

```bash
TOKEN="7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d"
WORKER="https://openclaw-gateway-public.amit-shah-5201.workers.dev"

# 1. PM breaks down project
curl "$WORKER/api/chat?token=$TOKEN" \
  -X POST -H "Content-Type: application/json" \
  -d '{"content":"I need a blog platform","agent_id":"project_manager"}'

# 2. Coder builds it
curl "$WORKER/api/chat?token=$TOKEN" \
  -X POST -H "Content-Type: application/json" \
  -d '{"content":"Build the blog post editor","agent_id":"coder_agent"}'

# 3. Security audits it
curl "$WORKER/api/chat?token=$TOKEN" \
  -X POST -H "Content-Type: application/json" \
  -d '{"content":"Audit the blog editor for XSS","agent_id":"hacker_agent"}'
```

---

## ✅ What's Working

- ✅ Worker deployed to Cloudflare Edge
- ✅ Token authentication
- ✅ CORS enabled
- ✅ Proxying to OpenClaw Gateway
- ✅ All 3 agents accessible
- ✅ GPU models connected
- ✅ Public access (no Cloudflare Access blocking)

---

## 🌍 Access From Anywhere

Your OpenClaw AI agency is now accessible from anywhere in the world via:

**https://openclaw-gateway-public.amit-shah-5201.workers.dev**

Just include the token in every request! 🚀

---

**Last Updated**: 2026-02-09 13:09 UTC
**Status**: FULLY OPERATIONAL ✅
