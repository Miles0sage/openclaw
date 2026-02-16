#!/bin/bash

#############################################
# 24/7 Autonomous OpenClaw GPU VPS Setup
# Automated installation script
#############################################

set -e  # Exit on error

echo "🦞 OpenClaw 24/7 Autonomous Coder - VPS Setup"
echo "=============================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}This script must be run as root${NC}"
   exit 1
fi

echo -e "${GREEN}✓${NC} Running as root"

# Check for GPU
if command -v nvidia-smi &> /dev/null; then
    echo -e "${GREEN}✓${NC} NVIDIA GPU detected"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo -e "${YELLOW}⚠${NC} No NVIDIA GPU detected - will continue but models will run on CPU (slow!)"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Update system
echo ""
echo "📦 Updating system packages..."
apt update
apt upgrade -y

# Install essential packages
echo ""
echo "📦 Installing essential packages..."
apt install -y \
    curl \
    wget \
    git \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    jq \
    htop \
    tmux \
    ca-certificates \
    gnupg \
    lsb-release

echo -e "${GREEN}✓${NC} Essential packages installed"

# Install Node.js 22
echo ""
echo "📦 Installing Node.js 22..."
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

NODE_VERSION=$(node --version)
echo -e "${GREEN}✓${NC} Node.js installed: $NODE_VERSION"

# Install Ollama
echo ""
echo "📦 Installing Ollama..."
if command -v ollama &> /dev/null; then
    echo -e "${YELLOW}⚠${NC} Ollama already installed"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo -e "${GREEN}✓${NC} Ollama installed"
fi

# Start Ollama service
systemctl enable ollama || true
systemctl start ollama || ollama serve &
sleep 5

# Pull coding models
echo ""
echo "📦 Pulling Ollama models (this may take a while)..."
echo "   Downloading Qwen2.5-Coder 14B..."
ollama pull qwen2.5-coder:14b

echo "   Downloading Qwen2.5 14B (for PM/Security)..."
ollama pull qwen2.5:14b

echo -e "${GREEN}✓${NC} Models downloaded"

# Verify GPU usage
if command -v nvidia-smi &> /dev/null; then
    echo ""
    echo "🔥 Testing GPU acceleration..."
    ollama run qwen2.5:14b "Test: 2+2=" --verbose &
    sleep 3
    echo ""
    nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
    pkill -f "ollama run" || true
fi

# Install OpenClaw
echo ""
echo "📦 Installing OpenClaw..."
npm install -g openclaw@latest

OPENCLAW_VERSION=$(openclaw --version 2>&1 || echo "unknown")
echo -e "${GREEN}✓${NC} OpenClaw installed: $OPENCLAW_VERSION"

# Install Tailscale
echo ""
echo "📦 Installing Tailscale..."
if command -v tailscale &> /dev/null; then
    echo -e "${YELLOW}⚠${NC} Tailscale already installed"
else
    curl -fsSL https://tailscale.com/install.sh | sh
    echo -e "${GREEN}✓${NC} Tailscale installed"
fi

# Install Playwright for browser automation
echo ""
echo "📦 Installing Playwright..."
npm install -g playwright
npx playwright install --with-deps chromium
echo -e "${GREEN}✓${NC} Playwright installed"

# Create OpenClaw directory structure
echo ""
echo "📁 Creating directory structure..."
mkdir -p /root/openclaw/workflows
mkdir -p /root/openclaw/logs
mkdir -p ~/.openclaw

echo -e "${GREEN}✓${NC} Directories created"

# Create OpenClaw config
echo ""
echo "⚙️  Creating OpenClaw configuration..."

# Prompt for password
read -sp "Enter OpenClaw gateway password: " GATEWAY_PASSWORD
echo ""

cat > ~/.openclaw/openclaw.json << EOF
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "ollama/qwen2.5-coder:14b",
        "fallbacks": ["ollama/qwen2.5:14b"]
      },
      "sandbox": {
        "mode": "non-main",
        "scope": "session",
        "workspace": "rw"
      }
    }
  },
  "models": {
    "providers": {
      "ollama": {
        "baseUrl": "http://127.0.0.1:11434",
        "apiKey": "ollama-local",
        "api": "ollama"
      }
    }
  },
  "gateway": {
    "bind": "loopback",
    "port": 18789,
    "tailscale": {
      "mode": "serve"
    },
    "auth": {
      "mode": "password"
    }
  },
  "browser": {
    "headless": true,
    "profile": {
      "persistent": true
    }
  }
}
EOF

# Set environment variables
echo "export OPENCLAW_GATEWAY_PASSWORD='$GATEWAY_PASSWORD'" >> ~/.bashrc
export OPENCLAW_GATEWAY_PASSWORD="$GATEWAY_PASSWORD"

echo -e "${GREEN}✓${NC} Configuration created"

# Create systemd service for gateway
echo ""
echo "⚙️  Creating systemd service..."

cat > /etc/systemd/system/openclaw-gateway.service << EOF
[Unit]
Description=OpenClaw Gateway
After=network.target ollama.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/openclaw
Environment="OPENCLAW_GATEWAY_PASSWORD=$GATEWAY_PASSWORD"
Environment="NODE_ENV=production"
ExecStart=/usr/bin/env bash -c 'cd /root/openclaw && python3 gateway.py'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable openclaw-gateway

echo -e "${GREEN}✓${NC} Systemd service created"

# Create status check script
echo ""
echo "📊 Creating status script..."

cat > /root/openclaw/status.sh << 'EOF'
#!/bin/bash

echo "🦞 OpenClaw 24/7 Status Dashboard"
echo "=================================="
echo ""

echo "📊 Gateway Status:"
curl -s http://localhost:18789/ 2>/dev/null | jq || echo "Gateway not responding"

echo ""
echo "🔥 Ollama Status:"
curl -s http://localhost:11434/api/tags 2>/dev/null | jq '.models[] | {name, size}' || echo "Ollama not responding"

echo ""
if command -v nvidia-smi &> /dev/null; then
    echo "⚡ GPU Usage:"
    nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader
else
    echo "⚡ No GPU detected"
fi

echo ""
echo "🤖 Active Processes:"
ps aux | grep -E "(gateway.py|ollama)" | grep -v grep

echo ""
echo "🌐 Tailscale Status:"
tailscale status 2>/dev/null | head -5 || echo "Tailscale not connected"

echo ""
echo "💾 Disk Usage:"
df -h / | tail -1

echo ""
echo "🧠 Memory Usage:"
free -h | grep Mem
EOF

chmod +x /root/openclaw/status.sh

echo -e "${GREEN}✓${NC} Status script created"

# Final setup instructions
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ Installation Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1️⃣  Start Tailscale:"
echo "   sudo tailscale up"
echo "   Note your Tailscale URL and save it!"
echo ""
echo "2️⃣  Copy the multi-agent files to this VPS:"
echo "   scp /root/openclaw/gateway.py root@VPS_IP:/root/openclaw/"
echo "   scp /root/openclaw/orchestrator.py root@VPS_IP:/root/openclaw/"
echo "   scp /root/openclaw/autonomous_workflows.py root@VPS_IP:/root/openclaw/"
echo "   scp /root/openclaw/config.json root@VPS_IP:/root/openclaw/"
echo ""
echo "3️⃣  Start the gateway:"
echo "   sudo systemctl start openclaw-gateway"
echo "   sudo systemctl status openclaw-gateway"
echo ""
echo "4️⃣  Enable Tailscale Serve:"
echo "   tailscale serve --bg https / http://127.0.0.1:18789"
echo ""
echo "5️⃣  Check status:"
echo "   /root/openclaw/status.sh"
echo ""
echo "6️⃣  Configure Telegram (optional):"
echo "   openclaw channels add telegram"
echo "   Follow the prompts"
echo ""
echo "📚 Full guide: /root/openclaw/24-7-AUTONOMOUS-CODER.md"
echo ""
echo -e "${YELLOW}⚠️  IMPORTANT: Save your Tailscale URL - that's how you access the gateway!${NC}"
echo ""
