#!/bin/bash

echo "🚀 OpenClaw Complete Deployment"
echo "================================"
echo ""

# Configuration
OPENCLAW_DIR="/root/openclaw"
GATEWAY_PORT="18789"
LOG_FILE="/tmp/openclaw-gateway.log"

cd $OPENCLAW_DIR

echo "📋 Step 1: Check Dependencies"
echo "=============================="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found! Installing..."
    apt-get update && apt-get install -y python3 python3-pip
fi
echo "✅ Python3: $(python3 --version)"

# Check required packages
echo ""
echo "📦 Installing Python packages..."
pip3 install fastapi uvicorn anthropic requests python-dotenv websockets jq -q

echo ""
echo "📋 Step 2: Check Configuration"
echo "=============================="

if [ ! -f "config.json" ]; then
    echo "❌ config.json not found!"
    exit 1
fi
echo "✅ config.json exists"

if [ ! -f "gateway.py" ]; then
    echo "❌ gateway.py not found!"
    exit 1
fi
echo "✅ gateway.py exists"

if [ ! -f ".env" ]; then
    echo "⚠️  .env not found, creating template..."
    cat > .env << 'ENVEOF'
ANTHROPIC_API_KEY=your-key-here
ENVEOF
    echo "❌ Please edit .env and add your ANTHROPIC_API_KEY"
    exit 1
fi
echo "✅ .env exists"

# Check API key
source .env
if [ "$ANTHROPIC_API_KEY" = "your-key-here" ] || [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ ANTHROPIC_API_KEY not configured in .env"
    exit 1
fi
echo "✅ ANTHROPIC_API_KEY configured"

echo ""
echo "📋 Step 3: Current Configuration"
echo "================================"

echo ""
echo "Agents configured:"
jq -r '.agents | to_entries[] | "  \(.value.emoji) \(.key): \(.value.apiProvider) → \(.value.model)"' config.json

echo ""
echo "📋 Step 4: Stop Existing Gateway"
echo "================================"

if lsof -i :$GATEWAY_PORT >/dev/null 2>&1; then
    echo "🛑 Stopping existing gateway on port $GATEWAY_PORT..."
    fuser -k $GATEWAY_PORT/tcp 2>/dev/null
    sleep 2
    echo "✅ Gateway stopped"
else
    echo "✅ No existing gateway running"
fi

echo ""
echo "📋 Step 5: Start OpenClaw Gateway"
echo "=================================="

# Start gateway
nohup python3 gateway.py > $LOG_FILE 2>&1 &
GATEWAY_PID=$!

echo "⏳ Starting gateway (PID: $GATEWAY_PID)..."
sleep 5

# Check if it's running
if lsof -i :$GATEWAY_PORT >/dev/null 2>&1; then
    echo "✅ Gateway started successfully!"
    echo ""
    echo "📊 Gateway Info:"
    echo "  Port: $GATEWAY_PORT"
    echo "  PID: $GATEWAY_PID"
    echo "  Logs: $LOG_FILE"
else
    echo "❌ Gateway failed to start!"
    echo ""
    echo "Last 20 lines of log:"
    tail -20 $LOG_FILE
    exit 1
fi

echo ""
echo "📋 Step 6: Test Gateway"
echo "======================="

sleep 2

# Test health endpoint
HEALTH_RESPONSE=$(curl -s http://localhost:$GATEWAY_PORT/ 2>&1)
if echo "$HEALTH_RESPONSE" | jq -e '.status' >/dev/null 2>&1; then
    echo "✅ Health check passed"
    echo ""
    echo "Gateway status:"
    echo "$HEALTH_RESPONSE" | jq '.'
else
    echo "❌ Health check failed"
    echo "Response: $HEALTH_RESPONSE"
fi

echo ""
echo "📋 Step 7: Test Agent"
echo "===================="

# Test PM agent
TEST_RESPONSE=$(curl -s -X POST http://localhost:$GATEWAY_PORT/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello! Status check.", "agent_id": "project_manager"}' 2>&1)

if echo "$TEST_RESPONSE" | jq -e '.response' >/dev/null 2>&1; then
    echo "✅ Agent test passed"
    echo ""
    echo "PM Agent response:"
    echo "$TEST_RESPONSE" | jq -r '.response' | head -5
    echo "..."
else
    echo "❌ Agent test failed"
    echo "Response: $TEST_RESPONSE"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 DEPLOYMENT COMPLETE!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📍 Access Points:"
echo "  Gateway:   http://localhost:$GATEWAY_PORT/"
echo "  API:       http://localhost:$GATEWAY_PORT/api/chat"
echo "  WebSocket: ws://localhost:$GATEWAY_PORT/ws"
echo "  Agents:    http://localhost:$GATEWAY_PORT/api/agents"
echo ""
echo "📊 Logs:"
echo "  tail -f $LOG_FILE"
echo ""
echo "🛑 Stop Gateway:"
echo "  fuser -k $GATEWAY_PORT/tcp"
echo ""
echo "🔄 Restart Gateway:"
echo "  ./DEPLOY-OPENCLAW.sh"
echo ""

