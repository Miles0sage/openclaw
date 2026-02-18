# OpenClaw Dashboard API - Integration Guide

Complete integration instructions for the OpenClaw Gateway Dashboard API.

## Overview

The Dashboard API provides:

- **Real-time monitoring** of gateway and Cloudflare tunnel status
- **Log aggregation** from multiple sources
- **Service management** (restart capabilities)
- **Secret management** (encrypted key storage)
- **Health metrics** (CPU, memory, uptime, errors)
- **Configuration access** (without exposing secrets)

## Architecture

```
Frontend (3D Dashboard)
    ↓
HTTPS/CORS
    ↓
Dashboard API (FastAPI)
    :9000
    ↓
├─ Local System
│  ├─ Process monitoring (gateway, tunnel)
│  ├─ Log file reading (/tmp/*.log)
│  ├─ System metrics (free, top, netstat)
│  └─ Config reading (/root/openclaw/config.json)
│
└─ Gateway
   :18789
   ├─ Health checks
   └─ Status polling
```

## Installation

### Option 1: Automated Installation (Recommended)

```bash
sudo bash /root/openclaw/install-dashboard.sh
```

This automatically:

- Installs Python dependencies (FastAPI, uvicorn, etc.)
- Creates environment file from template
- Creates systemd service
- Sets up log directories
- Validates installation

### Option 2: Manual Installation

```bash
# 1. Install dependencies
pip3 install fastapi uvicorn python-dotenv pydantic --break-system-packages

# 2. Copy template config
cp /root/openclaw/.dashboard.env.template /root/openclaw/.dashboard.env

# 3. Edit configuration
nano /root/openclaw/.dashboard.env

# 4. Install systemd service
sudo cp /root/openclaw/openclaw-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload

# 5. Start service
sudo systemctl start openclaw-dashboard
sudo systemctl enable openclaw-dashboard

# 6. Verify
sudo systemctl status openclaw-dashboard
```

## Configuration

### Environment File

Create `/root/openclaw/.dashboard.env`:

```bash
# Server Configuration
OPENCLAW_DASHBOARD_PORT=9000
OPENCLAW_DASHBOARD_PASSWORD=openclaw-dashboard-2026
OPENCLAW_DASHBOARD_TOKEN=moltbot-secure-token-2026

# Gateway Configuration
OPENCLAW_GATEWAY_PORT=18789
OPENCLAW_GATEWAY_HOST=localhost

# Log Paths
OPENCLAW_GATEWAY_LOG_PATH=/tmp/openclaw-gateway.log
OPENCLAW_TUNNEL_LOG_PATH=/tmp/cloudflared-tunnel.log

# Config Paths
OPENCLAW_CONFIG_PATH=/root/openclaw/config.json
OPENCLAW_SECRETS_PATH=/tmp/openclaw_secrets.json

# Static Files
OPENCLAW_STATIC_DIR=/var/www/dashboard
```

### Change Security Credentials

**Generate secure token (32 characters):**

```bash
openssl rand -hex 16
# Output: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

**Update environment file:**

```bash
sudo nano /root/openclaw/.dashboard.env

# Change:
OPENCLAW_DASHBOARD_TOKEN=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

# Restart:
sudo systemctl restart openclaw-dashboard
```

## Frontend Integration

### Basic Setup

```html
<!-- index.html -->
<!DOCTYPE html>
<html>
  <head>
    <title>OpenClaw Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
  </head>
  <body>
    <div id="dashboard"></div>
    <script>
      const TOKEN = "moltbot-secure-token-2026";
      const API_URL = "http://localhost:9000";

      const api = axios.create({
        baseURL: API_URL,
        headers: {
          Authorization: `Bearer ${TOKEN}`,
        },
      });

      // Get status
      api.get("/api/status").then((r) => {
        console.log("Status:", r.data);
        document.getElementById("dashboard").innerHTML = `
                <h1>OpenClaw Status</h1>
                <p>Gateway: ${r.data.gateway_running ? "Running" : "Stopped"}</p>
                <p>Tunnel: ${r.data.tunnel_running ? "Active" : "Inactive"}</p>
                <p>Uptime: ${(r.data.uptime_seconds / 3600).toFixed(1)} hours</p>
            `;
      });
    </script>
  </body>
</html>
```

### React Integration

```jsx
import { useEffect, useState } from "react";
import axios from "axios";

export function Dashboard() {
  const [status, setStatus] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  const api = axios.create({
    baseURL: "http://localhost:9000",
    headers: {
      Authorization: "Bearer moltbot-secure-token-2026",
    },
  });

  useEffect(() => {
    const fetchData = async () => {
      try {
        const statusRes = await api.get("/api/status");
        const healthRes = await api.get("/api/health");

        setStatus(statusRes.data);
        setHealth(healthRes.data);
      } catch (error) {
        console.error("Error fetching data:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000); // Refresh every 5s
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div>Loading...</div>;

  return (
    <div className="dashboard">
      <h1>Gateway Status</h1>
      <div className="status-grid">
        <div className="card">
          <h3>Gateway</h3>
          <p className={status?.gateway_running ? "ok" : "error"}>
            {status?.gateway_running ? "✅ Running" : "❌ Offline"}
          </p>
          <p>Port: {status?.gateway_port}</p>
        </div>
        <div className="card">
          <h3>Tunnel</h3>
          <p className={status?.tunnel_running ? "ok" : "error"}>
            {status?.tunnel_running ? "✅ Active" : "❌ Inactive"}
          </p>
        </div>
        <div className="card">
          <h3>Health</h3>
          <p className={`status-${health?.status}`}>{health?.status}</p>
          <p>Memory: {health?.memory_usage_mb}MB</p>
          <p>CPU: {health?.cpu_usage_percent}%</p>
        </div>
      </div>
    </div>
  );
}
```

### Vue Integration

```vue
<template>
  <div class="dashboard">
    <h1>OpenClaw Gateway Dashboard</h1>

    <div class="status-grid">
      <div class="card">
        <h3>Gateway</h3>
        <p :class="status.gateway_running ? 'ok' : 'error'">
          {{ status.gateway_running ? "✅ Running" : "❌ Offline" }}
        </p>
        <p>Uptime: {{ (status.uptime_seconds / 3600).toFixed(1) }}h</p>
      </div>

      <div class="card">
        <h3>Tunnel</h3>
        <p :class="status.tunnel_running ? 'ok' : 'error'">
          {{ status.tunnel_running ? "✅ Active" : "❌ Inactive" }}
        </p>
        <p v-if="status.tunnel_url">{{ status.tunnel_url }}</p>
      </div>

      <div class="card">
        <h3>System Health</h3>
        <p :class="`status-${health.status}`">{{ health.status }}</p>
        <p>Memory: {{ health.memory_usage_mb }}MB</p>
        <p>CPU: {{ health.cpu_usage_percent }}%</p>
      </div>
    </div>
  </div>
</template>

<script>
import axios from "axios";

export default {
  data() {
    return {
      status: {},
      health: {},
      api: axios.create({
        baseURL: "http://localhost:9000",
        headers: {
          Authorization: "Bearer moltbot-secure-token-2026",
        },
      }),
    };
  },

  mounted() {
    this.fetchStatus();
    this.fetchHealth();
    setInterval(() => {
      this.fetchStatus();
      this.fetchHealth();
    }, 5000);
  },

  methods: {
    async fetchStatus() {
      try {
        const res = await this.api.get("/api/status");
        this.status = res.data;
      } catch (error) {
        console.error("Error fetching status:", error);
      }
    },

    async fetchHealth() {
      try {
        const res = await this.api.get("/api/health");
        this.health = res.data;
      } catch (error) {
        console.error("Error fetching health:", error);
      }
    },
  },
};
</script>

<style scoped>
.dashboard {
  padding: 20px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
  margin-top: 20px;
}

.card {
  border: 1px solid #ccc;
  border-radius: 8px;
  padding: 20px;
  background: #f9f9f9;
}

.ok {
  color: #22c55e;
  font-weight: bold;
}

.error {
  color: #ef4444;
  font-weight: bold;
}

.status-healthy {
  color: #22c55e;
}

.status-degraded {
  color: #f59e0b;
}

.status-unhealthy {
  color: #ef4444;
}
</style>
```

## Production Deployment

### Docker

**Dockerfile:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir fastapi uvicorn python-dotenv pydantic

# Copy application
COPY dashboard_api.py .
COPY config.json .

# Create config directory
RUN mkdir -p /tmp/openclaw_logs

# Expose port
EXPOSE 9000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:9000/health')"

# Run application
CMD ["uvicorn", "dashboard_api:app", "--host", "0.0.0.0", "--port", "9000"]
```

**Build and run:**

```bash
docker build -t openclaw-dashboard .

docker run -d \
  --name openclaw-dashboard \
  -p 9000:9000 \
  -e OPENCLAW_DASHBOARD_TOKEN=your-token \
  -v /root/openclaw/config.json:/app/config.json:ro \
  -v /tmp/openclaw-gateway.log:/tmp/openclaw-gateway.log:ro \
  openclaw-dashboard
```

### Kubernetes

**Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openclaw-dashboard
  labels:
    app: openclaw-dashboard
spec:
  replicas: 2
  selector:
    matchLabels:
      app: openclaw-dashboard
  template:
    metadata:
      labels:
        app: openclaw-dashboard
    spec:
      containers:
        - name: dashboard
          image: openclaw-dashboard:latest
          ports:
            - containerPort: 9000
          env:
            - name: OPENCLAW_DASHBOARD_TOKEN
              valueFrom:
                secretKeyRef:
                  name: openclaw-secrets
                  key: dashboard-token
            - name: OPENCLAW_GATEWAY_PORT
              value: "18789"
            - name: OPENCLAW_GATEWAY_HOST
              value: "openclaw-gateway"
          livenessProbe:
            httpGet:
              path: /health
              port: 9000
            initialDelaySeconds: 10
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /api/status
              port: 9000
            initialDelaySeconds: 5
            periodSeconds: 10

---
apiVersion: v1
kind: Service
metadata:
  name: openclaw-dashboard
spec:
  selector:
    app: openclaw-dashboard
  ports:
    - protocol: TCP
      port: 9000
      targetPort: 9000
  type: LoadBalancer
```

### Nginx Reverse Proxy (HTTPS)

**nginx.conf:**

```nginx
upstream openclaw_dashboard {
    server localhost:9000;
}

server {
    listen 80;
    server_name dashboard.openclaw.local;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name dashboard.openclaw.local;

    ssl_certificate /etc/ssl/certs/openclaw-dashboard.crt;
    ssl_certificate_key /etc/ssl/private/openclaw-dashboard.key;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    # Proxy settings
    location / {
        proxy_pass http://openclaw_dashboard;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # CORS headers
        add_header Access-Control-Allow-Origin "https://yourdomain.com" always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type" always;
    }
}
```

**Setup:**

```bash
sudo nano /etc/nginx/sites-available/openclaw-dashboard
sudo ln -s /etc/nginx/sites-available/openclaw-dashboard /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Monitoring & Alerts

### Prometheus Integration

**prometheus.yml:**

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "openclaw-dashboard"
    static_configs:
      - targets: ["localhost:9000"]
    relabel_configs:
      - source_labels: [__scheme__, __address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9000
```

### Alert Rules (Alertmanager)

**alerts.yml:**

```yaml
groups:
  - name: openclaw
    rules:
      - alert: GatewayDown
        expr: openclaw_gateway_running == 0
        for: 2m
        annotations:
          summary: "OpenClaw Gateway is down"

      - alert: TunnelDown
        expr: openclaw_tunnel_running == 0
        for: 5m
        annotations:
          summary: "Cloudflare tunnel is down"

      - alert: HighMemory
        expr: openclaw_memory_usage_mb > 1000
        for: 10m
        annotations:
          summary: "High memory usage detected"

      - alert: HighCPU
        expr: openclaw_cpu_usage_percent > 80
        for: 5m
        annotations:
          summary: "High CPU usage detected"
```

## Testing & Validation

### Unit Tests

```bash
pytest test_dashboard_api.py -v
```

### Integration Tests

```bash
# Test with real gateway
TOKEN="moltbot-secure-token-2026"

# Test all endpoints
for endpoint in /api/status /api/logs /api/health /api/webhooks /api/config; do
  echo "Testing $endpoint..."
  curl -H "Authorization: Bearer $TOKEN" http://localhost:9000$endpoint | jq .
done
```

### Load Testing

```bash
# Install ab (Apache Bench)
sudo apt-get install apache2-utils

# Run load test
ab -n 1000 -c 10 \
  -H "Authorization: Bearer moltbot-secure-token-2026" \
  http://localhost:9000/api/status
```

## Troubleshooting

See **DASHBOARD_QUICKREF.md** for common issues and solutions.

## Support

- **Issues:** Check logs: `sudo journalctl -u openclaw-dashboard -f`
- **Documentation:** `/root/openclaw/DASHBOARD_API.md`
- **Quick Reference:** `/root/openclaw/DASHBOARD_QUICKREF.md`
- **GitHub:** https://github.com/openclaw/openclaw/issues
