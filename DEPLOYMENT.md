# OpenClaw Production Deployment Guide

Complete guide for deploying OpenClaw in production using Docker, Docker Compose, or Kubernetes.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Docker Setup](#docker-setup)
3. [Docker Compose Setup](#docker-compose-setup)
4. [Kubernetes Setup](#kubernetes-setup)
5. [Environment Configuration](#environment-configuration)
6. [Monitoring & Observability](#monitoring--observability)
7. [Troubleshooting](#troubleshooting)
8. [Security Best Practices](#security-best-practices)

---

## Quick Start

### Local Development

```bash
# Clone the repository
git clone https://github.com/cline/openclaw.git
cd openclaw

# Copy example env
cp .env.example .env
# Edit .env with your API keys
nano .env

# Run with Docker Compose (includes gateway + dashboard)
docker-compose up -d

# Verify deployment
docker-compose ps
curl http://localhost:8000/health
open http://localhost:9000/dashboard
```

### Verify Running Services

```bash
# Check gateway health
curl http://localhost:8000/health

# Check metrics endpoint
curl http://localhost:8000/metrics

# View logs
docker-compose logs -f openclaw-gateway
```

---

## Docker Setup

### Build Docker Image

```bash
# Build with default settings
docker build -t openclaw-gateway:latest .

# Build with custom Python version
docker build \
  --build-arg PYTHON_VERSION=3.13-slim \
  -t openclaw-gateway:latest .

# Verify image size (should be ~400-500MB)
docker images openclaw-gateway
```

### Run Single Container

```bash
# Basic run (development)
docker run -d \
  --name openclaw-gateway \
  -p 8000:8000 \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  openclaw-gateway:latest

# Production run with volumes and resource limits
docker run -d \
  --name openclaw-gateway \
  -p 8000:8000 \
  -v openclaw-sessions:/app/sessions \
  -v openclaw-logs:/app/logs \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -e SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
  --restart unless-stopped \
  --memory 1g \
  --cpus 2 \
  openclaw-gateway:latest

# Check health
docker exec openclaw-gateway curl http://localhost:8000/health
```

### Push to Registry

```bash
# Log in to your registry
docker login ghcr.io

# Tag image
docker tag openclaw-gateway:latest ghcr.io/username/openclaw-gateway:latest

# Push
docker push ghcr.io/username/openclaw-gateway:latest

# Verify
docker inspect ghcr.io/username/openclaw-gateway:latest
```

---

## Docker Compose Setup

### Local Development

```bash
# Start all services (gateway + dashboard)
docker-compose up -d

# View status
docker-compose ps

# View logs
docker-compose logs -f openclaw-gateway
docker-compose logs -f openclaw-dashboard

# Stop services
docker-compose down

# Clean up volumes
docker-compose down -v
```

### Environment Configuration

Create `.env` file in the project root:

```bash
# API Keys
ANTHROPIC_API_KEY=sk-ant-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APP_TOKEN=xapp-...
DISCORD_BOT_TOKEN=...
TELEGRAM_BOT_TOKEN=...
DEEPSEEK_API_KEY=...

# Supabase Keys
BARBER_CRM_SUPABASE_ANON_KEY=...
BARBER_CRM_SUPABASE_SERVICE_ROLE_KEY=...
DELHI_PALACE_SUPABASE_ANON_KEY=...
DELHI_PALACE_SUPABASE_SERVICE_ROLE_KEY=...

# Configuration
SLACK_REPORT_CHANNEL=#general
LOG_LEVEL=info
```

### Scale Services

```bash
# Scale gateway to 3 instances (requires Docker Swarm or orchestration)
docker-compose up -d --scale openclaw-gateway=3

# Or modify docker-compose.yml and recreate
docker-compose up -d --force-recreate
```

### Troubleshooting Docker Compose

```bash
# Check container status
docker-compose ps

# View detailed logs
docker-compose logs --tail 100 openclaw-gateway

# Rebuild image
docker-compose build --no-cache openclaw-gateway

# Recreate containers
docker-compose down && docker-compose up -d

# Check resource usage
docker stats openclaw-gateway
```

---

## Kubernetes Setup

### Prerequisites

```bash
# Install kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Install helm (optional, for package management)
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Verify cluster access
kubectl cluster-info
kubectl get nodes
```

### Create Namespace and Configure Secrets

```bash
# Create namespace with network policies
kubectl apply -f kubernetes/namespace.yaml

# Create secrets from environment variables
kubectl create secret generic openclaw-secrets \
  --from-literal=anthropic-api-key=$ANTHROPIC_API_KEY \
  --from-literal=slack-bot-token=$SLACK_BOT_TOKEN \
  --from-literal=slack-signing-secret=$SLACK_SIGNING_SECRET \
  --from-literal=slack-app-token=$SLACK_APP_TOKEN \
  --from-literal=discord-bot-token=$DISCORD_BOT_TOKEN \
  --from-literal=telegram-bot-token=$TELEGRAM_BOT_TOKEN \
  --from-literal=deepseek-api-key=$DEEPSEEK_API_KEY \
  --from-literal=barber-crm-supabase-anon-key=$BARBER_CRM_SUPABASE_ANON_KEY \
  --from-literal=barber-crm-supabase-service-role-key=$BARBER_CRM_SUPABASE_SERVICE_ROLE_KEY \
  --from-literal=delhi-palace-supabase-anon-key=$DELHI_PALACE_SUPABASE_ANON_KEY \
  --from-literal=delhi-palace-supabase-service-role-key=$DELHI_PALACE_SUPABASE_SERVICE_ROLE_KEY \
  --namespace openclaw

# Verify secrets are created
kubectl get secrets -n openclaw
```

### Deploy Application

```bash
# Apply ConfigMap
kubectl apply -f kubernetes/configmap.yaml -n openclaw

# Deploy application with zero-downtime strategy
kubectl apply -f kubernetes/deployment.yaml -n openclaw

# Expose service
kubectl apply -f kubernetes/service.yaml -n openclaw

# Set up auto-scaling
kubectl apply -f kubernetes/hpa.yaml -n openclaw

# Verify deployment
kubectl get pods -n openclaw -w
kubectl get svc -n openclaw
```

### Monitor Deployment

```bash
# Watch pods during rollout
kubectl get pods -n openclaw -w

# Check pod status details
kubectl describe pod <pod-name> -n openclaw

# View logs from pod
kubectl logs -f <pod-name> -n openclaw

# Check deployment history
kubectl rollout history deployment/openclaw-gateway -n openclaw

# View resource usage
kubectl top pod -n openclaw
```

### Scaling in Kubernetes

```bash
# Manual scaling
kubectl scale deployment openclaw-gateway --replicas=5 -n openclaw

# Check HPA status
kubectl get hpa -n openclaw
kubectl describe hpa openclaw-gateway-hpa -n openclaw

# Monitor autoscaling in action
watch kubectl get hpa -n openclaw
```

### Rolling Updates

```bash
# Update image
kubectl set image deployment/openclaw-gateway \
  gateway=ghcr.io/username/openclaw-gateway:v2.0 \
  -n openclaw \
  --record

# Monitor rollout
kubectl rollout status deployment/openclaw-gateway -n openclaw

# Rollback if needed
kubectl rollout undo deployment/openclaw-gateway -n openclaw
```

### Ingress Configuration

```bash
# Install ingress controller (nginx example)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml

# Apply ingress rules
kubectl apply -f kubernetes/service.yaml -n openclaw

# Check ingress status
kubectl get ingress -n openclaw
kubectl describe ingress openclaw-gateway -n openclaw
```

---

## Environment Configuration

### Required Environment Variables

```bash
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-...

# Slack Integration
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APP_TOKEN=xapp-...
SLACK_REPORT_CHANNEL=#general

# Discord Integration
DISCORD_BOT_TOKEN=...

# Telegram Integration
TELEGRAM_BOT_TOKEN=...

# Alternative LLM Providers
DEEPSEEK_API_KEY=...
MINIMAX_API_KEY=...

# Supabase Keys (Database)
BARBER_CRM_SUPABASE_ANON_KEY=...
BARBER_CRM_SUPABASE_SERVICE_ROLE_KEY=...
DELHI_PALACE_SUPABASE_ANON_KEY=...
DELHI_PALACE_SUPABASE_SERVICE_ROLE_KEY=...
```

### Optional Configuration

```bash
# Logging
LOG_LEVEL=info  # Options: debug, info, warning, error
OPENCLAW_LOGS_DIR=/app/logs

# Sessions
OPENCLAW_SESSIONS_DIR=/app/sessions

# Gateway
OPENCLAW_HTTP_GATEWAY_URL=http://openclaw-gateway:8000
OPENCLAW_HTTP_GATEWAY_TOKEN=your-token

# Python
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
```

### Secrets Management

#### Option 1: Docker Secrets (Swarm)

```bash
# Create secret
echo "sk-ant-..." | docker secret create anthropic_api_key -

# Use in compose
docker service create \
  --secret anthropic_api_key \
  openclaw-gateway:latest
```

#### Option 2: Kubernetes Secrets

See Kubernetes setup section above.

#### Option 3: External Secrets Operator

```bash
# Install ESO
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets -n external-secrets-system --create-namespace

# Configure with your secret backend (AWS Secrets Manager, Vault, etc)
```

#### Option 4: HashiCorp Vault

```bash
# Configure Vault auth
kubectl patch serviceaccount openclaw -n openclaw \
  -p '{"automountServiceAccountToken": true}'

# Use Vault agent to inject secrets
kubectl apply -f vault-agent-config.yaml -n openclaw
```

---

## Monitoring & Observability

### Health Checks

```bash
# HTTP health check
curl http://localhost:8000/health

# Expected response
{
  "status": "healthy",
  "timestamp": "2026-02-18T20:45:30Z",
  "version": "1.0.0"
}
```

### Metrics Endpoint

```bash
# Prometheus metrics
curl http://localhost:8000/metrics

# Includes:
# - Request counts and latencies
# - Gateway uptime
# - Session counts
# - Error rates
```

### Logging

```bash
# View logs locally
tail -f /app/logs/openclaw.log

# Docker Compose
docker-compose logs -f openclaw-gateway

# Kubernetes
kubectl logs -f deployment/openclaw-gateway -n openclaw

# Structured logging (JSON)
# All logs are JSON formatted for easy parsing
cat /app/logs/openclaw.log | jq '.level == "error"'
```

### Monitoring Stack (Optional)

```bash
# Install Prometheus
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring --create-namespace

# Install Grafana
helm install grafana grafana/grafana -n monitoring

# Forward port to access Grafana
kubectl port-forward svc/grafana 3000:80 -n monitoring

# Import dashboard (Dashboard ID: openclaw-gateway)
```

### Key Metrics to Monitor

- **Request latency** (p50, p95, p99)
- **Error rate** (4xx, 5xx responses)
- **Throughput** (requests/second)
- **Memory usage** (should be stable)
- **CPU usage** (scale if >70%)
- **Session count** (active connections)
- **Queue depth** (pending tasks)

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs openclaw-gateway

# Common issues:
# 1. Port already in use
lsof -i :8000
# 2. Missing environment variables
docker-compose config | grep ANTHROPIC_API_KEY
# 3. Insufficient disk space
df -h
```

### Health Check Failing

```bash
# Check endpoint directly
curl -v http://localhost:8000/health

# Check application logs
docker logs openclaw-gateway

# Verify port is listening
netstat -tulpn | grep 8000

# Check resource limits
docker stats openclaw-gateway
```

### High Memory Usage

```bash
# Monitor memory
docker stats --no-stream

# If leaking:
# 1. Restart container: docker restart openclaw-gateway
# 2. Check for unbounded growth in sessions
# 3. Review cost_tracker for memory issues
```

### Kubernetes Pod Crashes

```bash
# Check pod status
kubectl describe pod <pod-name> -n openclaw

# Check logs
kubectl logs <pod-name> -n openclaw --previous

# Check resource quotas
kubectl describe resourcequota -n openclaw

# Check node resources
kubectl describe node <node-name>
```

### Network Issues

```bash
# Test connectivity from pod
kubectl exec -it <pod-name> -n openclaw -- curl http://openclaw-gateway:8000/health

# Check DNS
kubectl exec -it <pod-name> -n openclaw -- nslookup kubernetes.default

# Check network policy
kubectl get networkpolicy -n openclaw
kubectl describe networkpolicy openclaw-network-policy -n openclaw
```

---

## Security Best Practices

### 1. Secret Management

- Never commit secrets to git
- Use `.env.example` with placeholder values
- Rotate API keys regularly
- Use short-lived credentials when possible
- Audit secret access logs

### 2. Network Security

```bash
# Only expose necessary ports
docker run -p 8000:8000  # Not 0.0.0.0

# Use network policies in K8s
kubectl apply -f kubernetes/namespace.yaml

# Enable TLS for external traffic
# See service.yaml ingress configuration
```

### 3. Container Security

- Run as non-root user (already configured)
- Use read-only root filesystem where possible
- Scan images for vulnerabilities
- Use minimal base images (slim variants)
- Keep dependencies updated

```bash
# Scan image for vulnerabilities
trivy image openclaw-gateway:latest

# Check for outdated packages
pip-audit -r requirements.txt

# Update dependencies
pip install --upgrade -r requirements.txt
```

### 4. Access Control

```bash
# Kubernetes RBAC (already configured)
kubectl apply -f kubernetes/secrets.yaml

# Check role bindings
kubectl get rolebindings -n openclaw
kubectl get clusterrolebindings

# Audit access
kubectl logs -n kube-apiserver --tail=100 | grep openclaw
```

### 5. Monitoring & Alerting

- Enable audit logging
- Set up alerts for:
  - Deployment failures
  - High error rates
  - Security policy violations
  - Resource exhaustion

```bash
# Example alert (Prometheus)
alert: OpenClawDown
expr: up{job="openclaw-gateway"} == 0
for: 5m
```

### 6. Backup & Disaster Recovery

```bash
# Backup sessions
docker cp openclaw-gateway:/app/sessions ./backup-sessions-$(date +%s)

# Backup config
cp config.json config.json.backup

# Test restore procedure regularly
```

---

## Deployment Checklist

### Pre-Deployment

- [ ] All API keys configured
- [ ] Environment variables set
- [ ] Database connections verified
- [ ] TLS certificates configured
- [ ] Backup taken
- [ ] Security scan passed (no critical vulns)

### Deployment

- [ ] Image built successfully
- [ ] All tests passing
- [ ] Secrets created in cluster
- [ ] Manifests applied
- [ ] Pods transitioning to ready
- [ ] Service endpoints responding

### Post-Deployment

- [ ] Health checks passing
- [ ] Metrics endpoint accessible
- [ ] Logs being collected
- [ ] Monitoring alerts configured
- [ ] Rollback plan documented
- [ ] Stakeholders notified

---

## Support & References

- GitHub Issues: https://github.com/cline/openclaw/issues
- Documentation: https://docs.openclaw.ai
- Status Page: https://status.openclaw.ai

For security issues, please report privately to security@openclaw.ai
