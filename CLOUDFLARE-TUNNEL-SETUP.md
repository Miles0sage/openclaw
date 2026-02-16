# 🌐 Cloudflare Tunnel for OpenClaw - Stable Connection Setup

**Expose your OpenClaw gateway securely via Cloudflare Tunnel (no port forwarding needed!)**

---

## 🎯 Why Cloudflare Tunnel?

### Advantages

✅ **No port forwarding** - Works behind NAT/firewall
✅ **Free tier** - Zero cost for small projects
✅ **Auto HTTPS** - SSL certificates automatically
✅ **DDoS protection** - Built-in Cloudflare protection
✅ **Stable** - More reliable than direct IP
✅ **Zero Trust** - Access control built-in
✅ **Global CDN** - Fast from anywhere

### vs Tailscale

| Feature           | Cloudflare Tunnel     | Tailscale            |
| ----------------- | --------------------- | -------------------- |
| **Cost**          | Free                  | Free (up to 3 users) |
| **Public Access** | ✅ Yes                | ❌ No (tailnet only) |
| **Setup**         | Medium                | Easy                 |
| **Security**      | Access control        | VPN-based            |
| **Best For**      | Public APIs, webhooks | Private team access  |

**Recommendation:** Use **both**!

- Cloudflare Tunnel for public access (webhooks, API)
- Tailscale for private admin access

---

## 📋 Prerequisites

### 1. Domain Name

You need a domain managed by Cloudflare (free):

- Buy domain from any registrar (Namecheap, GoDaddy, etc.)
- Add to Cloudflare (free plan works!)
- Or use Cloudflare Registrar directly

**Don't have a domain?** You can use Cloudflare's temporary subdomain for testing!

### 2. OpenClaw Running

```bash
# Verify gateway is running
curl http://localhost:18789/
```

### 3. Server Requirements

- Ubuntu/Debian Linux
- Root or sudo access
- Ports 18789 open locally

---

## 🚀 Step 1: Install Cloudflared

### Method 1: Official Script (Recommended)

```bash
# Download and install
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb

# Install
sudo dpkg -i cloudflared.deb

# Verify
cloudflared --version
```

### Method 2: Direct Binary

```bash
# Download
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

# Make executable
chmod +x cloudflared-linux-amd64

# Move to PATH
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# Verify
cloudflared --version
```

---

## 🚀 Step 2: Login to Cloudflare

```bash
# Login (opens browser)
cloudflared tunnel login

# This will:
# 1. Open browser to Cloudflare dashboard
# 2. Ask you to select a domain
# 3. Save credentials to ~/.cloudflared/cert.pem
```

**Output:**

```
You have successfully logged in.
Credentials saved to: /root/.cloudflared/cert.pem
```

---

## 🚀 Step 3: Create Tunnel

```bash
# Create tunnel named "openclaw"
cloudflared tunnel create openclaw

# Output:
# Tunnel credentials written to /root/.cloudflared/<TUNNEL-ID>.json
# Created tunnel openclaw with id <TUNNEL-ID>
```

**Save the Tunnel ID!** You'll need it.

Example output:

```
Created tunnel openclaw with id 12345678-1234-1234-1234-123456789abc
```

---

## 🚀 Step 4: Configure DNS

### Option A: Automatic (Recommended)

```bash
# Route your domain to the tunnel
cloudflared tunnel route dns openclaw openclaw.yourdomain.com

# This automatically creates a CNAME record
```

### Option B: Manual

1. Go to Cloudflare Dashboard
2. Select your domain
3. Go to DNS settings
4. Add CNAME record:
   - **Name:** `openclaw` (or whatever subdomain you want)
   - **Target:** `<TUNNEL-ID>.cfargotunnel.com`
   - **Proxied:** ✅ Yes

---

## 🚀 Step 5: Create Configuration File

Create `/root/.cloudflared/config.yml`:

```yaml
# Tunnel configuration for OpenClaw
tunnel: openclaw
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json

# Ingress rules (routes)
ingress:
  # Main OpenClaw Gateway
  - hostname: openclaw.yourdomain.com
    service: http://localhost:18789
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s

  # WebSocket support
  - hostname: openclaw.yourdomain.com
    path: /ws
    service: ws://localhost:18789/ws
    originRequest:
      noTLSVerify: true

  # Cline integration endpoint
  - hostname: openclaw.yourdomain.com
    path: /api/cline/*
    service: http://localhost:18789
    originRequest:
      noTLSVerify: true

  # Catch-all (return 404 for other requests)
  - service: http_status:404
```

**Replace:**

- `<TUNNEL-ID>` with your actual tunnel ID
- `yourdomain.com` with your actual domain

---

## 🚀 Step 6: Start the Tunnel

### Test Run First

```bash
# Test the tunnel
cloudflared tunnel run openclaw

# You should see:
# 2024-02-09 12:00:00 INF Connection established
# 2024-02-09 12:00:00 INF Registered tunnel connection
```

**Test it:**

```bash
# From another terminal or your phone
curl https://openclaw.yourdomain.com/

# Should return:
# {"name": "OpenClaw Gateway", "status": "online", ...}
```

If it works, proceed to install as a service!

### Install as System Service

```bash
# Install cloudflared as a service
sudo cloudflared service install

# This creates a systemd service at:
# /etc/systemd/system/cloudflared.service
```

### Start and Enable Service

```bash
# Start the service
sudo systemctl start cloudflared

# Enable on boot
sudo systemctl enable cloudflared

# Check status
sudo systemctl status cloudflared

# View logs
sudo journalctl -u cloudflared -f
```

---

## 🚀 Step 7: Secure with Access Control (Optional but Recommended)

### Enable Cloudflare Zero Trust

1. Go to https://one.dash.cloudflare.com/
2. Select your account
3. Go to **Access** → **Applications**
4. Click **Add an application**

### Create Access Policy

**Application Settings:**

- **Name:** OpenClaw Gateway
- **Subdomain:** openclaw
- **Domain:** yourdomain.com
- **Session Duration:** 24 hours

**Policy:**

- **Policy name:** Allow my team
- **Action:** Allow
- **Include:**
  - Emails: `you@email.com`, `teammate@email.com`
  - OR Email domain: `@yourcompany.com`

**Save and Deploy**

Now only authorized emails can access `https://openclaw.yourdomain.com`!

---

## 🚀 Step 8: Configure OpenClaw for Cloudflare

Edit `/root/openclaw/config.json`:

```json
{
  "name": "Cybershield Agency",
  "agents": { ... },
  "gateway": {
    "bind": "loopback",
    "port": 18789,
    "publicUrl": "https://openclaw.yourdomain.com",
    "cloudflare": {
      "enabled": true,
      "tunnel": "openclaw"
    },
    "cors": {
      "enabled": true,
      "origins": [
        "https://openclaw.yourdomain.com",
        "https://*.yourdomain.com"
      ]
    }
  }
}
```

Restart gateway:

```bash
fuser -k 18789/tcp
cd /root/openclaw && python3 gateway.py &
```

---

## 🎯 Complete Setup Example

### Your Setup Now Looks Like:

```
┌─────────────────────────────────────────────────┐
│          Internet (Anywhere in the World)       │
└────────────────────┬────────────────────────────┘
                     │
              HTTPS (encrypted)
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│              Cloudflare Network                  │
│  • DDoS Protection                              │
│  • SSL/TLS Termination                          │
│  • Global CDN                                   │
│  • Access Control (Zero Trust)                  │
└────────────────────┬────────────────────────────┘
                     │
           Cloudflare Tunnel
           (Encrypted WebSocket)
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│              Your VPS                            │
│                                                 │
│  cloudflared ──────► localhost:18789           │
│                          ▲                      │
│                          │                      │
│                   OpenClaw Gateway              │
│                                                 │
│  🎯 PM  💻 Coder  🔒 Security                  │
└─────────────────────────────────────────────────┘
```

### Access URLs:

- **Gateway:** `https://openclaw.yourdomain.com/`
- **WebSocket:** `wss://openclaw.yourdomain.com/ws`
- **Cline API:** `https://openclaw.yourdomain.com/api/cline/poll`
- **Health:** `https://openclaw.yourdomain.com/api/agents`

---

## 🧪 Testing Your Setup

### Test 1: Basic Connectivity

```bash
# From anywhere in the world
curl https://openclaw.yourdomain.com/

# Expected:
# {"name": "OpenClaw Gateway", "status": "online", "agents": 3}
```

### Test 2: WebSocket Connection

```bash
# Install websocat if not already
curl -L https://github.com/vi/websocat/releases/latest/download/websocat.x86_64-unknown-linux-musl -o websocat
chmod +x websocat

# Test WebSocket
./websocat wss://openclaw.yourdomain.com/ws

# Send:
{"type":"req","id":"test-1","method":"connect","params":{}}

# Should get hello-ok response
```

### Test 3: Cline Integration

```bash
# Send message to Cline
curl -X POST https://openclaw.yourdomain.com/api/cline/send \
  -H "Content-Type: application/json" \
  -d '{"message": "Test from Cloudflare!", "action": "implement"}'

# Poll messages
curl https://openclaw.yourdomain.com/api/cline/poll?since=0
```

### Test 4: From Mobile

Open on your phone:

```
https://openclaw.yourdomain.com/
```

Should work from anywhere! 🎉

---

## 🔒 Security Best Practices

### 1. Enable Access Control

```bash
# Restrict to specific IPs (in Cloudflare Dashboard)
# Firewall Rules → Create Rule
# Rule: Block all except:
#   - Your home IP
#   - Your office IP
#   - Your VPN IP
```

### 2. Rate Limiting

In Cloudflare Dashboard:

- **Security** → **WAF** → **Rate limiting rules**
- Create rule:
  - **If:** URI path contains `/api/`
  - **Then:** Challenge if rate > 100 requests/minute

### 3. Bot Protection

Enable:

- **Security** → **Bots** → **Bot Fight Mode**
- This blocks automated attacks

### 4. API Key Authentication

Add to your gateway (already has password auth):

```bash
export OPENCLAW_GATEWAY_PASSWORD="your-secure-password"
```

Update `gateway.py` to require auth header on all requests.

---

## 🎯 Advanced Configuration

### Multiple Services via One Tunnel

Edit `~/.cloudflared/config.yml`:

```yaml
tunnel: openclaw
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json

ingress:
  # OpenClaw Gateway
  - hostname: openclaw.yourdomain.com
    service: http://localhost:18789

  # Second OpenClaw Instance
  - hostname: openclaw2.yourdomain.com
    service: http://localhost:18790

  # UI Server (if you have one)
  - hostname: ui.yourdomain.com
    service: http://localhost:5173

  # Ollama API (optional)
  - hostname: ollama.yourdomain.com
    service: http://localhost:11434

  # Catch-all
  - service: http_status:404
```

Restart tunnel:

```bash
sudo systemctl restart cloudflared
```

### Load Balancing (Multiple Tunnels)

For high availability:

```bash
# Create multiple tunnels on different servers
cloudflared tunnel create openclaw-us
cloudflared tunnel create openclaw-eu

# Configure load balancing in Cloudflare Dashboard
# Traffic → Load Balancing
```

---

## 📱 Connect from Telegram/Discord/Slack

Now that you have a public URL, configure webhooks:

### Telegram Bot Webhook

```bash
# Set webhook to your Cloudflare tunnel
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://openclaw.yourdomain.com/api/telegram/webhook"
```

### Discord Bot

```javascript
// In your Discord bot config
{
  "webhookUrl": "https://openclaw.yourdomain.com/api/discord/webhook"
}
```

### Slack App

1. Go to Slack App settings
2. **Event Subscriptions** → Enable
3. **Request URL:** `https://openclaw.yourdomain.com/api/slack/events`

---

## 🎮 Update Cline Configuration

Now Cline can connect from anywhere!

In VS Code `.vscode/settings.json`:

```json
{
  "cline.openclawGateway": "https://openclaw.yourdomain.com",
  "cline.pollEndpoint": "https://openclaw.yourdomain.com/api/cline/poll",
  "cline.sendEndpoint": "https://openclaw.yourdomain.com/api/cline/send"
}
```

Create polling script `.vscode/tasks.json`:

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Poll OpenClaw (Cloudflare)",
      "type": "shell",
      "command": "while true; do curl -s 'https://openclaw.yourdomain.com/api/cline/poll?since='$(date +%s)000 | jq; sleep 5; done",
      "isBackground": true
    }
  ]
}
```

---

## 🐛 Troubleshooting

### Issue 1: Tunnel Not Connecting

```bash
# Check tunnel status
cloudflared tunnel info openclaw

# Check service logs
sudo journalctl -u cloudflared -n 100

# Common fix: Restart service
sudo systemctl restart cloudflared
```

### Issue 2: 502 Bad Gateway

**Cause:** OpenClaw gateway not running

**Fix:**

```bash
# Check if gateway is running
curl http://localhost:18789/

# If not, start it
cd /root/openclaw && python3 gateway.py &
```

### Issue 3: DNS Not Resolving

```bash
# Check DNS propagation
dig openclaw.yourdomain.com

# Should show CNAME to *.cfargotunnel.com

# If not, re-run:
cloudflared tunnel route dns openclaw openclaw.yourdomain.com
```

### Issue 4: Access Denied (Zero Trust)

**Cause:** Email not in allowed list

**Fix:**

1. Go to Cloudflare Zero Trust dashboard
2. Access → Applications → Edit policy
3. Add your email to allowed list

---

## 💰 Cost Comparison

### Cloudflare Tunnel (Free Tier)

- **Tunnel:** Free (unlimited bandwidth!)
- **DNS:** Free
- **DDoS Protection:** Free
- **SSL:** Free
- **Zero Trust (Basic):** Free (up to 50 users)

**Total: $0/month** 🎉

### Alternatives

| Service                | Cost/Month | Pros                 | Cons                |
| ---------------------- | ---------- | -------------------- | ------------------- |
| **Cloudflare Tunnel**  | $0         | Free, stable, global | Requires domain     |
| **Tailscale**          | $0         | Easy, private        | Tailnet only        |
| **ngrok**              | $8-25      | Quick setup          | Expensive, unstable |
| **VPS with Public IP** | $5-10      | Full control         | Manage firewall     |

---

## 🎊 Final Setup Checklist

✅ Domain registered and added to Cloudflare
✅ `cloudflared` installed on server
✅ Tunnel created and configured
✅ DNS CNAME record added
✅ Service installed and running
✅ OpenClaw gateway running on localhost:18789
✅ Tested from external internet
✅ (Optional) Zero Trust access control enabled
✅ (Optional) Webhooks configured for Telegram/Discord/Slack
✅ (Optional) Cline configured to use Cloudflare URL

---

## 🚀 Quick Setup Script

Save as `/root/openclaw/setup-cloudflare-tunnel.sh`:

```bash
#!/bin/bash

echo "🌐 Setting up Cloudflare Tunnel for OpenClaw"
echo "============================================"
echo ""

# Check if cloudflared is installed
if ! command -v cloudflared &> /dev/null; then
    echo "📦 Installing cloudflared..."
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    chmod +x cloudflared-linux-amd64
    sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
    echo "✅ cloudflared installed"
else
    echo "✅ cloudflared already installed"
fi

echo ""
echo "🔑 Login to Cloudflare (browser will open)"
cloudflared tunnel login

echo ""
echo "🔧 Creating tunnel..."
read -p "Enter tunnel name [openclaw]: " TUNNEL_NAME
TUNNEL_NAME=${TUNNEL_NAME:-openclaw}

cloudflared tunnel create $TUNNEL_NAME

echo ""
echo "📋 Getting tunnel ID..."
TUNNEL_ID=$(cloudflared tunnel list | grep $TUNNEL_NAME | awk '{print $1}')
echo "Tunnel ID: $TUNNEL_ID"

echo ""
read -p "Enter your domain (e.g., example.com): " DOMAIN
read -p "Enter subdomain [openclaw]: " SUBDOMAIN
SUBDOMAIN=${SUBDOMAIN:-openclaw}

echo ""
echo "🌍 Configuring DNS..."
cloudflared tunnel route dns $TUNNEL_NAME ${SUBDOMAIN}.${DOMAIN}

echo ""
echo "📝 Creating configuration file..."
mkdir -p ~/.cloudflared

cat > ~/.cloudflared/config.yml << EOF
tunnel: $TUNNEL_NAME
credentials-file: /root/.cloudflared/${TUNNEL_ID}.json

ingress:
  - hostname: ${SUBDOMAIN}.${DOMAIN}
    service: http://localhost:18789
  - hostname: ${SUBDOMAIN}.${DOMAIN}
    path: /ws
    service: ws://localhost:18789/ws
  - service: http_status:404
EOF

echo "✅ Configuration created"

echo ""
echo "🚀 Installing as service..."
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

echo ""
echo "✅ Setup complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 Your OpenClaw gateway is now accessible at:"
echo ""
echo "   https://${SUBDOMAIN}.${DOMAIN}/"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Check status:"
echo "   sudo systemctl status cloudflared"
echo ""
echo "📋 View logs:"
echo "   sudo journalctl -u cloudflared -f"
echo ""
echo "🧪 Test connection:"
echo "   curl https://${SUBDOMAIN}.${DOMAIN}/"
echo ""
echo "🎊 Happy tunneling!"
```
