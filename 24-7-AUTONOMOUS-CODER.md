# 🤖 24/7 Autonomous Coding Agent - Complete Setup Guide

## 🎯 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    VPS (GPU Instance)                        │
│                                                              │
│  ┌─────────────────┐      ┌──────────────────┐             │
│  │  Ollama Server  │◄────►│  OpenClaw        │             │
│  │  (Qwen2.5-Coder)│      │  Gateway         │             │
│  │  GPU Accelerated│      │  Port 18789      │             │
│  └─────────────────┘      └──────────────────┘             │
│                                   ▲                          │
│                                   │                          │
│  ┌──────────────────────────────┼──────────────────────┐   │
│  │     Autonomous Workflows      │                      │   │
│  │  ┌────────┐  ┌───────┐  ┌─────────┐  ┌─────────┐  │   │
│  │  │  PM    │→ │ Coder │→ │Security │→ │  Deliver│  │   │
│  │  └────────┘  └───────┘  └─────────┘  └─────────┘  │   │
│  └───────────────────────────────────────────────────┘   │
│                                                              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                    Tailscale Tunnel
                    (Encrypted)
                           │
                           ▼
                    ┌──────────────┐
                    │  Your Phone  │
                    │  (Telegram)  │
                    └──────────────┘
```

---

## 📋 Prerequisites

### VPS Requirements

- **GPU**: NVIDIA GPU with 16GB+ VRAM (RTX 4090, A100, etc.)
- **RAM**: 32GB minimum
- **Storage**: 100GB+ SSD
- **OS**: Ubuntu 22.04 or 24.04
- **Provider**: Vast.ai, RunPod, or Lambda Labs (cheap GPU rentals)

### Your Local Machine

- Telegram account (for receiving notifications)
- Tailscale account (free tier works)

---

## 🚀 Step 1: GPU VPS Setup

### 1.1 Rent GPU Instance

**Recommended Providers:**

- **Vast.ai** - $0.15-0.50/hr for RTX 4090
- **RunPod** - $0.30-0.70/hr for RTX 4090
- **Lambda Labs** - $1.10/hr for A100

**Template:**

```bash
Instance: RTX 4090 (24GB VRAM)
OS: Ubuntu 22.04 LTS with CUDA
RAM: 32GB
Storage: 100GB SSD
Port forwarding: 18789, 11434
```

### 1.2 Install NVIDIA Drivers & CUDA

```bash
# Check if NVIDIA drivers are installed
nvidia-smi

# If not installed:
sudo apt update
sudo apt install nvidia-driver-535 nvidia-cuda-toolkit -y
sudo reboot

# Verify
nvidia-smi
nvcc --version
```

---

## 🚀 Step 2: Install Ollama with GPU Support

### 2.1 Install Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Verify GPU is detected
ollama serve &  # Run in background
curl http://localhost:11434/api/version
```

### 2.2 Pull Coding Models

```bash
# Qwen2.5-Coder (best for coding, 14B params)
ollama pull qwen2.5-coder:14b

# CodeLlama (alternative, 13B params)
ollama pull codellama:13b

# DeepSeek-Coder-V2 (very good, 16B params)
ollama pull deepseek-coder-v2:16b

# Test it
ollama run qwen2.5-coder:14b "Write a Python function to calculate fibonacci"
```

### 2.3 Verify GPU Usage

```bash
# In one terminal
watch -n 1 nvidia-smi

# In another terminal
ollama run qwen2.5-coder:14b "Generate a React component"

# You should see GPU memory usage spike!
```

---

## 🚀 Step 3: Install OpenClaw

### 3.1 Install Node.js 22+

```bash
# Install Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify
node --version  # Should be v22.x.x
npm --version
```

### 3.2 Install OpenClaw

```bash
# Install globally
npm install -g openclaw@latest

# Verify
openclaw --version

# Run onboarding wizard
openclaw onboard --install-daemon
```

### 3.3 Configure for GPU Ollama

Edit `~/.openclaw/openclaw.json`:

```json5
{
  agents: {
    defaults: {
      model: {
        primary: "ollama/qwen2.5-coder:14b",
        fallbacks: ["ollama/deepseek-coder-v2:16b", "ollama/codellama:13b"],
      },
      sandbox: {
        mode: "non-main", // Sandbox for safety
        scope: "session",
        workspace: "rw",
      },
    },
  },
  models: {
    providers: {
      ollama: {
        baseUrl: "http://127.0.0.1:11434",
        apiKey: "ollama-local",
        api: "ollama",
      },
    },
  },
  gateway: {
    bind: "loopback",
    port: 18789,
    tailscale: {
      mode: "serve", // Secure tunnel
    },
    auth: {
      mode: "password",
      password: "${OPENCLAW_GATEWAY_PASSWORD}",
    },
  },
}
```

Set password:

```bash
export OPENCLAW_GATEWAY_PASSWORD="your-secure-password-here"
echo 'export OPENCLAW_GATEWAY_PASSWORD="your-secure-password-here"' >> ~/.bashrc
```

---

## 🚀 Step 4: Install Tailscale (Secure Tunnel)

### 4.1 Install Tailscale

```bash
# Install
curl -fsSL https://tailscale.com/install.sh | sh

# Login and enable
sudo tailscale up

# Note your Tailscale IP
tailscale ip -4
# Example: 100.64.1.23
```

### 4.2 Enable Tailscale Serve (HTTPS)

```bash
# Start gateway with Tailscale
openclaw gateway run --bind loopback --port 18789 --force &

# Enable Tailscale Serve
tailscale serve --bg https / http://127.0.0.1:18789

# Get your URL
tailscale status
# Your gateway is now at: https://<your-machine>.ts.net/
```

---

## 🚀 Step 5: Set Up Autonomous Workflows

### 5.1 Create Workflow Config

Edit your `/root/openclaw/config.json`:

```json
{
  "name": "24/7 Coding Agency",
  "version": "2.0.0",
  "agents": {
    "project_manager": {
      "name": "Cybershield PM",
      "emoji": "🎯",
      "model": "ollama/qwen2.5:14b",
      "apiProvider": "ollama",
      "persona": "Enthusiastic PM coordinating coding projects",
      "skills": ["task_decomposition", "timeline_estimation", "quality_assurance"],
      "signature": "— 🎯 Cybershield PM"
    },
    "coder_agent": {
      "name": "CodeGen Pro",
      "emoji": "💻",
      "model": "ollama/qwen2.5-coder:14b",
      "apiProvider": "ollama",
      "persona": "Expert coder writing production-ready code 24/7",
      "skills": ["nextjs", "fastapi", "typescript", "python", "react"],
      "signature": "— 💻 CodeGen Pro"
    },
    "hacker_agent": {
      "name": "Pentest AI",
      "emoji": "🔒",
      "model": "ollama/qwen2.5:14b",
      "apiProvider": "ollama",
      "persona": "Security expert finding vulnerabilities",
      "skills": ["security_scanning", "penetration_testing", "owasp"],
      "signature": "— 🔒 Pentest AI"
    }
  },
  "workflows": {
    "auto_code_24_7": {
      "name": "24/7 Autonomous Coding Pipeline",
      "trigger": "schedule",
      "schedule": {
        "kind": "every",
        "everyMs": 3600000 // Run every hour
      },
      "steps": [
        {
          "agent": "project_manager",
          "task": "check_github_issues",
          "timeout": "5m",
          "description": "Check for new GitHub issues tagged 'auto-code'"
        },
        {
          "agent": "coder_agent",
          "task": "implement_solution",
          "timeout": "30m",
          "description": "Write code to solve the issue"
        },
        {
          "agent": "hacker_agent",
          "task": "security_review",
          "timeout": "10m",
          "description": "Review code for vulnerabilities"
        },
        {
          "agent": "coder_agent",
          "task": "apply_fixes",
          "timeout": "15m",
          "description": "Fix any security issues found"
        },
        {
          "agent": "project_manager",
          "task": "create_pr",
          "timeout": "5m",
          "description": "Create pull request with changes"
        }
      ]
    },
    "daily_intelligence": {
      "name": "Daily AI News Briefing",
      "trigger": "schedule",
      "schedule": {
        "kind": "cron",
        "expr": "0 7 * * *", // Every day at 7 AM
        "tz": "America/New_York"
      },
      "steps": [
        {
          "agent": "project_manager",
          "task": "scrape_ai_news",
          "timeout": "10m",
          "description": "Scrape HN, Reddit, X for AI news"
        },
        {
          "agent": "project_manager",
          "task": "summarize_and_send",
          "timeout": "5m",
          "description": "Summarize and send to Telegram"
        }
      ]
    }
  }
}
```

### 5.2 Deploy Workflow Engine

Copy the workflow engine to OpenClaw:

```bash
# Copy our autonomous workflow engine
cp /root/openclaw/autonomous_workflows.py ~/.openclaw/workflows/

# Copy orchestrator
cp /root/openclaw/orchestrator.py ~/.openclaw/workflows/

# Make executable
chmod +x ~/.openclaw/workflows/*.py
```

### 5.3 Create Systemd Service (Auto-Start on Boot)

Create `/etc/systemd/system/openclaw-autonomous.service`:

```ini
[Unit]
Description=OpenClaw 24/7 Autonomous Coding Agent
After=network.target ollama.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/openclaw
Environment="OPENCLAW_GATEWAY_PASSWORD=your-secure-password"
Environment="ANTHROPIC_API_KEY=your-key-if-needed"
ExecStart=/usr/bin/python3 /root/openclaw/autonomous_workflows.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable openclaw-autonomous
sudo systemctl start openclaw-autonomous
sudo systemctl status openclaw-autonomous
```

---

## 🚀 Step 6: Connect Telegram Bot

### 6.1 Create Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow prompts to create bot
4. Save the **API token**

### 6.2 Configure OpenClaw for Telegram

```bash
# Install Telegram skill
openclaw channels add telegram

# Configure
openclaw config set channels.telegram.token "YOUR_BOT_TOKEN_HERE"
openclaw config set channels.telegram.allowedUsers "[\"your_telegram_username\"]"

# Restart gateway
pkill -f "openclaw gateway" && openclaw gateway run --bind loopback --force &
```

### 6.3 Test Connection

1. Open Telegram
2. Search for your bot by username
3. Send: `/start`
4. Bot should respond!

---

## 🚀 Step 7: Browser Automation (For Web Scraping)

### 7.1 Install Playwright

```bash
# Install Playwright system deps
sudo apt-get install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2

# Install Playwright
npx playwright install chromium

# Test
npx playwright codegen https://news.ycombinator.com
```

### 7.2 Configure Browser in OpenClaw

Edit `~/.openclaw/openclaw.json`:

```json5
{
  browser: {
    headless: true,
    userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    profile: {
      persistent: true,
      path: "~/.openclaw/browser-profiles/default",
    },
    sandbox: {
      enabled: true,
      mode: "docker", // Optional: run browser in Docker
    },
  },
}
```

---

## 🚀 Step 8: Set Up Daily Intelligence Workflow

### 8.1 Create Intelligence Script

Create `/root/openclaw/workflows/daily_intelligence.py`:

```python
"""
Daily AI News Intelligence Gathering
Scrapes HN, Reddit, X for AI news and sends summary via Telegram
"""

import asyncio
import os
from datetime import datetime
from playwright.async_api import async_playwright


async def scrape_hackernews():
    """Scrape top HN posts about AI"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto("https://news.ycombinator.com/")

        # Get top posts
        posts = []
        items = await page.query_selector_all(".athing")

        for i, item in enumerate(items[:20]):  # Top 20
            title_elem = await item.query_selector(".titleline > a")
            title = await title_elem.text_content()
            link = await title_elem.get_attribute("href")

            # Filter for AI-related
            if any(kw in title.lower() for kw in ["ai", "llm", "gpt", "claude", "agent", "ml"]):
                posts.append({
                    "title": title,
                    "link": link,
                    "source": "HackerNews"
                })

        await browser.close()
        return posts


async def scrape_reddit_ai():
    """Scrape r/LocalLLaMA and r/MachineLearning"""
    # Simplified - use Reddit RSS or API
    # For production, use PRAW or Reddit API
    return []


async def generate_summary(posts, ollama_url="http://localhost:11434"):
    """Use Ollama to summarize posts"""
    import httpx

    # Combine all posts
    posts_text = "\n\n".join([
        f"**{p['title']}** ({p['source']})\n{p.get('link', '')}"
        for p in posts
    ])

    # Send to Ollama
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ollama_url}/api/generate",
            json={
                "model": "qwen2.5:14b",
                "prompt": f"""Analyze these AI news posts and create a brief summary:

{posts_text}

Categorize into:
1. **Code to Try** - New tools/libraries
2. **Drama/Risk** - Controversies, safety concerns
3. **New Tools** - Product launches, updates

Keep it concise and actionable.""",
                "stream": False
            }
        )

        data = response.json()
        return data["response"]


async def send_to_telegram(summary, bot_token, chat_id):
    """Send summary to Telegram"""
    import httpx

    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": f"🌅 **Daily AI Intelligence** ({datetime.now().strftime('%Y-%m-%d')})\n\n{summary}",
                "parse_mode": "Markdown"
            }
        )


async def main():
    """Main workflow"""
    print("🔍 Scraping AI news...")
    hn_posts = await scrape_hackernews()
    reddit_posts = await scrape_reddit_ai()

    all_posts = hn_posts + reddit_posts

    print(f"📰 Found {len(all_posts)} AI-related posts")

    print("🤖 Generating summary with Ollama...")
    summary = await generate_summary(all_posts)

    print("📱 Sending to Telegram...")
    await send_to_telegram(
        summary,
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("TELEGRAM_CHAT_ID")
    )

    print("✅ Daily intelligence delivered!")


if __name__ == "__main__":
    asyncio.run(main())
```

### 8.2 Add to Cron

```bash
# Add to crontab
crontab -e

# Add this line (runs at 7 AM daily)
0 7 * * * cd /root/openclaw && /usr/bin/python3 workflows/daily_intelligence.py
```

---

## 🚀 Step 9: Monitoring & Logs

### 9.1 Set Up Log Monitoring

```bash
# Real-time gateway logs
tail -f ~/.openclaw/logs/gateway.log

# Workflow logs
tail -f /root/openclaw/gateway.log

# System logs
journalctl -u openclaw-autonomous -f
```

### 9.2 Create Status Dashboard

Create `/root/openclaw/status.sh`:

```bash
#!/bin/bash

echo "🦞 OpenClaw 24/7 Status Dashboard"
echo "=================================="
echo ""

echo "📊 Gateway Status:"
curl -s http://localhost:18789/ | jq

echo ""
echo "🔥 Ollama Status:"
curl -s http://localhost:11434/api/tags | jq '.models[] | {name, size}'

echo ""
echo "⚡ GPU Usage:"
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader

echo ""
echo "🤖 Active Workflows:"
ps aux | grep "autonomous_workflows.py" | grep -v grep

echo ""
echo "🌐 Tailscale Status:"
tailscale status | head -5
```

Make executable:

```bash
chmod +x /root/openclaw/status.sh

# Run it
./status.sh
```

---

## 🎯 Complete Startup Sequence

### Auto-Start Everything on Boot

Create `/root/openclaw/start-all.sh`:

```bash
#!/bin/bash

echo "🚀 Starting 24/7 Autonomous Coding System..."

# Start Ollama
echo "Starting Ollama..."
systemctl start ollama || ollama serve &
sleep 5

# Start Tailscale
echo "Starting Tailscale..."
systemctl start tailscaled
tailscale up

# Start OpenClaw Gateway
echo "Starting OpenClaw Gateway..."
cd /root/openclaw
export OPENCLAW_GATEWAY_PASSWORD="your-password-here"
nohup python3 gateway.py > gateway.log 2>&1 &

# Start Autonomous Workflows
echo "Starting Autonomous Workflows..."
nohup python3 autonomous_workflows.py > workflows.log 2>&1 &

# Enable Tailscale Serve
echo "Enabling Tailscale HTTPS..."
tailscale serve --bg https / http://127.0.0.1:18789

echo "✅ All systems online!"
echo ""
echo "🌐 Access via: https://$(hostname).ts.net/"
echo "📊 Status: ./status.sh"
```

Make executable and add to crontab:

```bash
chmod +x /root/openclaw/start-all.sh

# Add to crontab to run on reboot
crontab -e
# Add: @reboot /root/openclaw/start-all.sh
```

---

## 📱 Usage Examples

### Example 1: Ask the Agent to Code

Send to Telegram bot:

```
@CodeGen-Pro 💻 Build me a FastAPI endpoint for user authentication with JWT tokens.

Requirements:
- POST /auth/register
- POST /auth/login
- GET /auth/me (protected)
- Use bcrypt for passwords
- Return JWT on login

— User
```

Agent will:

1. Receive message via Telegram
2. Route to CodeGen Pro agent
3. Generate complete code with Ollama
4. Security agent reviews it
5. PM sends it back to you via Telegram

### Example 2: Daily News Briefing

Every morning at 7 AM, you'll receive:

```
🌅 Daily AI Intelligence (2026-02-09)

📦 Code to Try:
- New LangChain 0.3.0 with streaming improvements
- Ollama now supports function calling

⚠️ Drama/Risk:
- OpenAI CEO controversy continues
- EU AI Act enforcement begins

🛠️ New Tools:
- Claude 4.5 Sonnet released
- Anthropic announces prompt caching

— 🎯 Cybershield PM
```

### Example 3: Autonomous Coding Loop

Set up GitHub webhook → triggers workflow:

```
1. New issue created: "Add dark mode"
2. PM receives webhook, analyzes
3. CodeGen writes dark mode code
4. Pentest reviews for XSS
5. CodeGen fixes issues
6. PM creates PR
7. You get Telegram notification: "PR #123 ready!"
```

---

## 🔒 Security Checklist

- ✅ Gateway on loopback (127.0.0.1)
- ✅ Tailscale Serve (encrypted tunnel)
- ✅ Password auth enabled
- ✅ Sandboxing enabled for tool execution
- ✅ Telegram bot limited to your username
- ✅ No public IP exposure
- ✅ GPU instance firewall configured
- ✅ SSH key-only access
- ✅ Regular backups of `~/.openclaw/`

---

## 💰 Cost Estimate

**GPU VPS:**

- Vast.ai RTX 4090: $0.30/hr × 24hr × 30 days = **$216/month**
- RunPod RTX 4090: $0.50/hr × 24hr × 30 days = **$360/month**

**Free tier:**

- Ollama: Free
- Tailscale: Free (up to 3 users)
- Telegram: Free
- OpenClaw: Open source, free

**Total: $216-360/month for 24/7 autonomous coding!**

Compare to Claude API:

- 1M tokens = $3
- 10M tokens/day = $30/day = **$900/month**

**Savings: 60-75%!**

---

## 🎉 You're Done!

Your 24/7 autonomous coding agent is now:

- ✅ Running on GPU-accelerated VPS
- ✅ Using local Ollama models (free!)
- ✅ Accessible via encrypted Tailscale tunnel
- ✅ Sending notifications to your Telegram
- ✅ Auto-coding from GitHub issues
- ✅ Delivering daily AI news briefs
- ✅ Sandboxed for security
- ✅ Auto-starting on reboot

**Access it:**

```bash
# From your phone/laptop (Tailscale connected)
https://your-vps.ts.net/

# Or SSH in
ssh root@your-vps-ip
./status.sh
```

**Send your first autonomous task:**
Open Telegram → Message your bot:

```
@CodeGen-Pro Build me a TODO app with Next.js and FastAPI!
```

Watch the magic happen! 🎨✨
