# 🚀 OpenClaw - QUICK START

## ✅ SYSTEM IS READY!

Your OpenClaw multi-agent system is **FULLY CONNECTED** to GPU VPS!

---

## 🎯 Try It Now

### Talk to CodeGen Pro (32B GPU Model)

```bash
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Build a FastAPI endpoint for user login", "agent_id": "coder_agent"}' \
  | jq -r '.response'
```

### Talk to Pentest AI (14B GPU Model)

```bash
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Security audit this code: eval(request.form.get(\"code\"))", "agent_id": "hacker_agent"}' \
  | jq -r '.response'
```

---

## 📊 What You Have

| Component      | Status       | Details             |
| -------------- | ------------ | ------------------- |
| Gateway        | ✅ Running   | Port 18789          |
| GPU Connection | ✅ Connected | 152.53.55.207:11434 |
| Coder (32B)    | ✅ Ready     | Qwen2.5-Coder 32B   |
| Security (14B) | ✅ Ready     | Qwen2.5-Coder 14B   |
| PM             | ✅ Ready     | Claude Sonnet 4.5   |

---

## 🔧 Management Commands

### Check Status

```bash
# Gateway status
curl -s http://localhost:18789/ && echo "Gateway OK"

# GPU models
curl -s http://152.53.55.207:11434/api/tags | jq -r '.models[].name'

# View logs
tail -f /tmp/openclaw-gateway.log
```

### Restart Gateway

```bash
fuser -k 18789/tcp && \
cd /root/openclaw && \
nohup python3 gateway.py > /tmp/openclaw-gateway.log 2>&1 &
```

---

## 📁 Important Files

- **Status**: `CONNECTION-STATUS.md` (full details)
- **Config**: `config.json` (agent settings)
- **Gateway**: `gateway.py` (main server)
- **Logs**: `/tmp/openclaw-gateway.log`

---

## 🌐 Cloudflare Worker (Optional)

**URL**: https://oversserclaw-worker.amit-shah-5201.workers.dev

Not configured yet. See `WHERE-TO-RUN-WHAT.md` if you need external access.

---

## 💡 Example Workflow

```bash
# 1. Ask PM to break down a project
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "I need a restaurant booking website with admin panel", "agent_id": "project_manager"}'

# 2. Get CodeGen to build it
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Build the restaurant booking form component", "agent_id": "coder_agent"}'

# 3. Let Pentest audit it
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Security audit the booking form", "agent_id": "hacker_agent"}'
```

---

## 🎉 You're All Set!

Your Cybershield Agency is ready to build **$500 websites in 24 hours**! 🚀

**Gateway**: http://localhost:18789
**Docs**: `CONNECTION-STATUS.md`
**Help**: Check logs if issues arise
