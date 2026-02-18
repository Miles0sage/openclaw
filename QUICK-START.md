# OpenClaw Quick Start Guide

Get OpenClaw running in minutes with Docker or Docker Compose.

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+ (for compose setup)
- API keys: Anthropic, Slack, Discord, Telegram (optional)

## Option 1: Docker Compose (Recommended for Local Development)

### 1. Setup Environment

```bash
cd /root/openclaw

# Copy example env
cp .env.example .env

# Edit with your API keys
nano .env
# Required minimum:
# ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Start Services

```bash
# Start gateway + dashboard
docker-compose up -d

# Check status
docker-compose ps
```

### 3. Verify

```bash
# Health check
curl http://localhost:8000/health

# Dashboard (might need credentials setup)
open http://localhost:9000/dashboard

# View logs
docker-compose logs -f openclaw-gateway
```

### 4. Stop Services

```bash
docker-compose down

# Cleanup volumes
docker-compose down -v
```

## Option 2: Pure Docker (For CI/CD Integration)

### 1. Build Image

```bash
docker build -t openclaw-gateway:latest .
```

### 2. Run Container

```bash
docker run -d \
  --name openclaw-gateway \
  -p 8000:8000 \
  -v openclaw-sessions:/app/sessions \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  --restart unless-stopped \
  --memory 1g \
  openclaw-gateway:latest

# Check health
curl http://localhost:8000/health
```

## Option 3: Kubernetes (For Production)

### 1. Create Namespace & Secrets

```bash
kubectl apply -f kubernetes/namespace.yaml

kubectl create secret generic openclaw-secrets \
  --from-literal=anthropic-api-key=$ANTHROPIC_API_KEY \
  --from-literal=slack-bot-token=$SLACK_BOT_TOKEN \
  --from-literal=telegram-bot-token=$TELEGRAM_BOT_TOKEN \
  -n openclaw
```

### 2. Deploy Application

```bash
kubectl apply -f kubernetes/configmap.yaml -n openclaw
kubectl apply -f kubernetes/deployment.yaml -n openclaw
kubectl apply -f kubernetes/service.yaml -n openclaw
kubectl apply -f kubernetes/hpa.yaml -n openclaw
```

### 3. Monitor Deployment

```bash
# Watch pods
kubectl get pods -n openclaw -w

# Check service
kubectl get svc -n openclaw

# View logs
kubectl logs -f deployment/openclaw-gateway -n openclaw
```

## Verify Deployment

### Health Check Endpoint

```bash
curl http://localhost:8000/health

# Response:
# {
#   "status": "healthy",
#   "timestamp": "2026-02-18T20:45:30Z",
#   "version": "1.0.0"
# }
```

### Metrics Endpoint

```bash
curl http://localhost:8000/metrics

# Prometheus-formatted metrics
```

### Check Gateway Status

```bash
# Docker Compose
docker-compose ps
docker-compose logs -f openclaw-gateway

# Docker
docker ps | grep openclaw-gateway
docker logs openclaw-gateway -f

# Kubernetes
kubectl get pods -n openclaw
kubectl logs -f <pod-name> -n openclaw
```

## Common Tasks

### View Logs

```bash
# Docker Compose
docker-compose logs -f openclaw-gateway

# Docker
docker logs -f openclaw-gateway

# Kubernetes
kubectl logs -f deployment/openclaw-gateway -n openclaw
```

### Restart Gateway

```bash
# Docker Compose
docker-compose restart openclaw-gateway

# Docker
docker restart openclaw-gateway

# Kubernetes
kubectl rollout restart deployment/openclaw-gateway -n openclaw
```

### Update Configuration

```bash
# Edit .env (Docker Compose)
nano .env
docker-compose restart openclaw-gateway

# Edit ConfigMap (Kubernetes)
kubectl edit configmap openclaw-config -n openclaw
kubectl rollout restart deployment/openclaw-gateway -n openclaw
```

### Check Resource Usage

```bash
# Docker
docker stats openclaw-gateway

# Kubernetes
kubectl top pod -n openclaw
kubectl top node
```

### Troubleshoot

```bash
# Check if port is in use
lsof -i :8000

# Test endpoint directly
curl -v http://localhost:8000/health

# Check full logs
docker logs openclaw-gateway 2>&1 | tail -100

# Check environment
docker run -it openclaw-gateway:latest env | grep OPENCLAW
```

## Environment Variables

### Required

```bash
ANTHROPIC_API_KEY=sk-ant-...  # Anthropic API key
```

### Optional

```bash
SLACK_BOT_TOKEN=xoxb-...      # Slack bot token
SLACK_SIGNING_SECRET=...       # Slack signing secret
SLACK_APP_TOKEN=xapp-...       # Slack app token
DISCORD_BOT_TOKEN=...          # Discord bot token
TELEGRAM_BOT_TOKEN=...         # Telegram bot token
DEEPSEEK_API_KEY=...           # DeepSeek API key

# Supabase (Database)
BARBER_CRM_SUPABASE_ANON_KEY=...
BARBER_CRM_SUPABASE_SERVICE_ROLE_KEY=...
DELHI_PALACE_SUPABASE_ANON_KEY=...
DELHI_PALACE_SUPABASE_SERVICE_ROLE_KEY=...

# Logging
LOG_LEVEL=info  # debug, info, warning, error
```

## Image Details

- **Base Image:** python:3.13-slim
- **Size:** ~189MB
- **User:** Non-root (uid: 1000)
- **Port:** 8000
- **Health Check:** Built-in every 30s
- **Restart Policy:** Unless stopped

## File Structure

```
/root/openclaw/
├── Dockerfile                      # Multi-stage Docker build
├── docker-compose.yml              # Local development setup
├── kubernetes/
│   ├── namespace.yaml              # Namespace + network policies
│   ├── deployment.yaml             # Pod deployment
│   ├── service.yaml                # LoadBalancer + Ingress
│   ├── hpa.yaml                    # Auto-scaling rules
│   ├── configmap.yaml              # Configuration
│   └── secrets.yaml                # Secret template
├── .github/workflows/
│   └── deploy.yml                  # CI/CD pipeline
├── DEPLOYMENT.md                   # Detailed guide
└── QUICK-START.md                  # This file
```

## Common Issues

### Port Already in Use

```bash
lsof -i :8000
kill -9 <PID>

# Or use different port
docker run -p 9000:8000 openclaw-gateway:latest
```

### Container Won't Start

```bash
# Check logs
docker logs openclaw-gateway

# Ensure API keys are set
env | grep ANTHROPIC_API_KEY

# Check disk space
df -h
```

### High Memory Usage

```bash
# Restart container
docker restart openclaw-gateway

# Or increase memory limit
docker run --memory 2g openclaw-gateway:latest
```

## Getting Help

1. **Read:** DEPLOYMENT.md (comprehensive guide)
2. **Check:** GitHub Issues
3. **Report:** security@openclaw.ai (for security issues)

## Next Steps

- [ ] Set up API keys in `.env`
- [ ] Start services with Docker Compose
- [ ] Configure Slack/Discord/Telegram webhooks
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Deploy to production (Kubernetes)

---

For detailed configuration options, see [DEPLOYMENT.md](./DEPLOYMENT.md)

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
