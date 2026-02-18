# OpenClaw Dashboard API - Quick Reference

## 🚀 Quick Start (5 minutes)

```bash
# 1. Install (as root)
sudo bash /root/openclaw/install-dashboard.sh

# 2. Review config
nano /root/openclaw/.dashboard.env

# 3. Start service
sudo systemctl start openclaw-dashboard

# 4. Check status
sudo systemctl status openclaw-dashboard

# 5. Test API
curl -H "Authorization: Bearer moltbot-secure-token-2026" http://localhost:9000/health
```

## 📊 Common Commands

### Check Status

```bash
TOKEN="moltbot-secure-token-2026"
curl -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/status
```

**Output:**

```json
{
  "gateway_running": true,
  "gateway_port": 18789,
  "tunnel_running": true,
  "uptime_seconds": 7200,
  "version": "1.0.0"
}
```

### Get Recent Logs

```bash
TOKEN="moltbot-secure-token-2026"
curl -H "Authorization: Bearer $TOKEN" "http://localhost:9000/api/logs?lines=30"
```

### Get Webhook URLs

```bash
TOKEN="moltbot-secure-token-2026"
curl -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/health
```

### Get System Health

```bash
TOKEN="moltbot-secure-token-2026"
curl -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/health
```

**Output:**

```json
{
  "status": "healthy",
  "memory_usage_mb": 256.5,
  "cpu_usage_percent": 15.2,
  "uptime_hours": 2.5,
  "errors_last_hour": 0
}
```

### Save API Key

```bash
TOKEN="moltbot-secure-token-2026"
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key":"api_key_name",
    "value":"sk-ant-v4-...",
    "service":"anthropic"
  }' \
  http://localhost:9000/api/secrets
```

### Restart Gateway

```bash
TOKEN="moltbot-secure-token-2026"
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:9000/api/restart
```

## 🔧 Service Management

### Start

```bash
sudo systemctl start openclaw-dashboard
```

### Stop

```bash
sudo systemctl stop openclaw-dashboard
```

### Restart

```bash
sudo systemctl restart openclaw-dashboard
```

### Check Status

```bash
sudo systemctl status openclaw-dashboard
```

### View Live Logs

```bash
sudo journalctl -u openclaw-dashboard -f
```

### View Last 50 Lines

```bash
sudo journalctl -u openclaw-dashboard -n 50
```

### Enable Auto-Start

```bash
sudo systemctl enable openclaw-dashboard
```

### Disable Auto-Start

```bash
sudo systemctl disable openclaw-dashboard
```

## ⚙️ Configuration

### Change Dashboard Token

```bash
# Edit config
sudo nano /root/openclaw/.dashboard.env

# Find this line:
OPENCLAW_DASHBOARD_TOKEN=moltbot-secure-token-2026

# Change to something secure:
OPENCLAW_DASHBOARD_TOKEN=your-new-secure-token-here

# Restart service
sudo systemctl restart openclaw-dashboard
```

### Change Dashboard Port

```bash
# Edit config
sudo nano /root/openclaw/.dashboard.env

# Find:
OPENCLAW_DASHBOARD_PORT=9000

# Change to:
OPENCLAW_DASHBOARD_PORT=9001

# Restart service
sudo systemctl restart openclaw-dashboard
```

### View Current Config

```bash
TOKEN="moltbot-secure-token-2026"
curl -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/config
```

## 📡 Gateway Integration

### Get Webhook URLs

```bash
TOKEN="moltbot-secure-token-2026"
curl -H "Authorization: Bearer $TOKEN" http://localhost:9000/api/webhooks
```

**Example Output:**

```json
{
  "telegram_webhook": "http://localhost:18789/telegram/webhook",
  "slack_webhook": "http://localhost:18789/slack/events",
  "telegram_enabled": true,
  "slack_enabled": true
}
```

### Test Telegram Webhook

```bash
curl -X POST http://localhost:18789/telegram/webhook \
  -H "Content-Type: application/json" \
  -d '{"update_id":1,"message":{"text":"test"}}'
```

## 🔍 Troubleshooting

### Dashboard Not Running

```bash
# Check if port is in use
lsof -i :9000

# Check service status
sudo systemctl status openclaw-dashboard

# View error logs
sudo journalctl -u openclaw-dashboard -n 100
```

### Cannot Connect to Gateway

```bash
# Check gateway status
curl http://localhost:18789/health

# Check if gateway is listening
ss -tlnp | grep 18789

# Check firewall
sudo ufw status
sudo ufw allow 18789/tcp
```

### Permission Denied Errors

```bash
# Fix log file permissions
sudo chmod 644 /tmp/openclaw-*.log

# Fix config permissions
sudo chmod 644 /root/openclaw/config.json

# Fix secrets file
sudo chmod 644 /tmp/openclaw_secrets.json
```

### Can't Read Log Files

```bash
# Create missing log files
sudo touch /tmp/openclaw-gateway.log
sudo touch /tmp/cloudflared-tunnel.log
sudo chmod 644 /tmp/openclaw-*.log

# Restart service
sudo systemctl restart openclaw-dashboard
```

### Health Check Fails

```bash
# Verify all dependencies
python3 -c "import fastapi, uvicorn, pydantic; print('✅ All imports OK')"

# Check if gateway is running
curl http://localhost:18789/health

# Check system resources
free -h
top -bn1 | head -20
```

## 📚 Environment Variables Quick Reference

| Variable                   | Default                    | Purpose            |
| -------------------------- | -------------------------- | ------------------ |
| `OPENCLAW_DASHBOARD_PORT`  | 9000                       | Dashboard API port |
| `OPENCLAW_DASHBOARD_TOKEN` | moltbot-secure-token-2026  | Bearer token       |
| `OPENCLAW_GATEWAY_PORT`    | 18789                      | Gateway port       |
| `OPENCLAW_GATEWAY_HOST`    | localhost                  | Gateway hostname   |
| `OPENCLAW_CONFIG_PATH`     | /root/openclaw/config.json | Gateway config     |
| `OPENCLAW_SECRETS_PATH`    | /tmp/openclaw_secrets.json | Secrets storage    |
| `OPENCLAW_STATIC_DIR`      | /var/www/dashboard         | Frontend files     |

## 🔐 Security

### Change Credentials

```bash
# Edit environment file
sudo nano /root/openclaw/.dashboard.env

# Update token (use 32+ character random string)
OPENCLAW_DASHBOARD_TOKEN=your-secure-token-$(date +%s)

# Restart service
sudo systemctl restart openclaw-dashboard
```

### Enable HTTPS (Recommended)

Use nginx reverse proxy:

```bash
sudo apt-get install nginx-full

# Create nginx config with SSL/TLS
sudo nano /etc/nginx/sites-available/openclaw-dashboard

# Enable it
sudo ln -s /etc/nginx/sites-available/openclaw-dashboard /etc/nginx/sites-enabled/
sudo systemctl reload nginx
```

### View Audit Log

```bash
# Check for failed auth attempts
sudo journalctl -u openclaw-dashboard | grep -i "invalid\|error\|401\|403"
```

## 📊 Performance Tuning

### Increase File Descriptors

```bash
# Edit systemd service
sudo nano /etc/systemd/system/openclaw-dashboard.service

# Add to [Service] section:
# LimitNOFILE=65536

sudo systemctl daemon-reload
sudo systemctl restart openclaw-dashboard
```

### Run with Gunicorn (Production)

```bash
pip install gunicorn

# Create startup script
cat > /tmp/start-dashboard.sh << 'EOF'
#!/bin/bash
cd /root/openclaw
gunicorn dashboard_api:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:9000 \
  --access-logfile /var/log/openclaw/dashboard-access.log \
  --error-logfile /var/log/openclaw/dashboard-error.log
EOF

chmod +x /tmp/start-dashboard.sh
```

## 🧪 Testing

### Health Check Test

```bash
# No auth required
curl http://localhost:9000/health
```

### Full Test Suite

```bash
pip install pytest
pytest /root/openclaw/test_dashboard_api.py -v
```

### Load Test (using Apache Bench)

```bash
TOKEN="moltbot-secure-token-2026"
ab -n 1000 -c 10 \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:9000/api/status
```

## 📞 Support

**Issues?** Check:

1. Logs: `sudo journalctl -u openclaw-dashboard -f`
2. Gateway: `curl http://localhost:18789/health`
3. Firewall: `sudo ufw status`
4. Config: `cat /root/openclaw/.dashboard.env`

**Documentation:** `/root/openclaw/DASHBOARD_API.md`
