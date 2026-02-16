# 🚀 Cloudflare Worker Deployment Guide

## ✅ Gateway Ready

Your OpenClaw Gateway is publicly accessible:

- **URL**: http://152.53.55.207:18789
- **Status**: ✅ Online
- **Test**: `curl http://152.53.55.207:18789/`

---

## 📋 Choose Your Deployment Method

### Method 1: Quick Deploy with API Token (Fastest)

**If you have a Cloudflare API Token:**

1. Get your token from: https://dash.cloudflare.com/profile/api-tokens
2. Set it on this VPS:
   ```bash
   export CLOUDFLARE_API_TOKEN="your-token-here"
   ```
3. Deploy:
   ```bash
   cd /root/openclaw
   echo "7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" | wrangler secret put OPENCLAW_TOKEN
   echo "http://152.53.55.207:18789" | wrangler secret put OPENCLAW_GATEWAY
   wrangler deploy
   ```

### Method 2: Deploy from Your Local Machine

**On your local computer:**

1. Copy worker files:

   ```bash
   # On your local machine
   mkdir -p ~/openclaw-worker
   scp root@152.53.55.207:/root/openclaw/cloudflare-worker.js ~/openclaw-worker/
   scp root@152.53.55.207:/root/openclaw/wrangler.toml ~/openclaw-worker/
   ```

2. Login to Cloudflare:

   ```bash
   cd ~/openclaw-worker
   wrangler login
   ```

3. Set secrets:

   ```bash
   # Token
   echo "7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" | wrangler secret put OPENCLAW_TOKEN

   # Gateway URL
   echo "http://152.53.55.207:18789" | wrangler secret put OPENCLAW_GATEWAY
   ```

4. Deploy:
   ```bash
   wrangler deploy
   ```

### Method 3: Use Automated Script

**Run the script:**

```bash
cd /root/openclaw
./DEPLOY-WORKER.sh
```

---

## 🧪 Test After Deployment

```bash
# Health check
curl "https://oversserclaw-worker.amit-shah-5201.workers.dev/?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d"

# Test coder agent
curl "https://oversserclaw-worker.amit-shah-5201.workers.dev/api/chat?token=7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"content":"Write hello world in Go","agent_id":"coder_agent"}'
```

---

## 🔑 Configuration

**Secrets to set:**

| Secret             | Value                                                              |
| ------------------ | ------------------------------------------------------------------ |
| `OPENCLAW_TOKEN`   | `7fca3b8d2e914a5c9d8f6b0a1c3e5d7f2a4b6c8d0e1f2a3b4c5d6e7f8a9b0c1d` |
| `OPENCLAW_GATEWAY` | `http://152.53.55.207:18789`                                       |

**Worker URL**: https://oversserclaw-worker.amit-shah-5201.workers.dev

---

## 📝 Files

- **Worker Code**: `/root/openclaw/cloudflare-worker.js`
- **Config**: `/root/openclaw/wrangler.toml`
- **Deploy Script**: `/root/openclaw/DEPLOY-WORKER.sh`

---

## 🆘 Need Help?

**Check if wrangler is logged in:**

```bash
wrangler whoami
```

**View existing secrets:**

```bash
wrangler secret list
```

**Logs:**

```bash
wrangler tail
```
