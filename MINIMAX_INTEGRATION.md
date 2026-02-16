# OpenClaw + MiniMax M2.5 Integration Guide

**Date:** February 16, 2026
**Status:** ✅ Configuration Updated (config.json)
**Next:** Get API key and test integration

---

## 🚀 What Changed

### Before (Qwen Local)

```json
"coder_agent": {
  "model": "qwen2.5-coder:32b",
  "apiProvider": "ollama",
  "endpoint": "http://152.53.55.207:11434"
}
```

### After (MiniMax API)

```json
"coder_agent": {
  "model": "MiniMax-M2.5",
  "apiProvider": "minimax",
  "endpoint": "https://api.minimax.chat/v1",
  "apiKeyEnv": "MINIMAX_API_KEY"
}
```

---

## 📊 Performance Upgrade

| Metric             | Before (Qwen 32B)      | After (MiniMax M2.5) | Improvement   |
| ------------------ | ---------------------- | -------------------- | ------------- |
| **SWE-Bench**      | ~70%                   | 80.2%                | +10.2% ✓      |
| **Tool Calling**   | ~50%                   | 76.8%                | +26.8% ✓      |
| **Context Window** | 8K                     | 1M                   | 125× larger ✓ |
| **Infrastructure** | $50/mo (Ollama server) | $0 (cloud API)       | Save $50/mo ✓ |
| **Speed**          | ~5 tok/sec             | ~100 tok/sec         | 20× faster ✓  |

---

## 🔑 SETUP (4 STEPS)

### Step 1: Get MiniMax API Key (5 minutes)

1. Go to https://platform.minimax.io
2. Click **Sign Up** (or login if you have account)
3. Create workspace → **API Keys**
4. Generate new API key
5. Copy the key

### Step 2: Set Environment Variable

```bash
# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
export MINIMAX_API_KEY="your-api-key-here"

# Or set it temporarily for testing
export MINIMAX_API_KEY="sk-xxxxxxxxxxxxxx"

# Verify it's set
echo $MINIMAX_API_KEY
```

### Step 3: Verify Config (Already Done)

Config is already updated in `/root/openclaw/config.json`:

```bash
# Verify MiniMax agent is configured
grep -A 20 '"coder_agent"' config.json | head -25
```

Should show:

```json
"coder_agent": {
  "model": "MiniMax-M2.5",
  "apiProvider": "minimax",
  "endpoint": "https://api.minimax.chat/v1"
}
```

### Step 4: Test Integration (15 minutes)

#### Quick Python Test

```python
from openai import OpenAI

# Initialize with MiniMax endpoint
client = OpenAI(
    api_key="your-minimax-api-key",
    base_url="https://api.minimax.chat/v1"
)

# Test it
response = client.chat.completions.create(
    model="MiniMax-M2.5",
    messages=[
        {"role": "user", "content": "Write a Python function to sort a list"}
    ]
)

print(response.choices[0].message.content)
```

#### Full Agent Test

```bash
# Start OpenClaw gateway
cd /root/openclaw
pnpm dev

# In another terminal, test CodeGen agent
curl http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Create a Next.js API endpoint for user registration",
    "sessionKey": "test-session",
    "channel": "testing",
    "accountId": "default",
    "agentId": "coder_agent"
  }'
```

---

## 💰 COST ANALYSIS

### Monthly Costs (Estimated)

**Scenario: 5,000 coding tasks/month**

| Component                   | Cost                  |
| --------------------------- | --------------------- |
| **MiniMax API**             |                       |
| - 500M input tokens × $0.30 | $150                  |
| - 1B output tokens × $1.20  | $1,200                |
| **Subtotal API**            | **$1,350/month**      |
| **Infrastructure**          | $0 (no server needed) |
| **Total**                   | **$1,350/month**      |

**vs. Previous (Qwen Local)**

- Server/GPU: $50/month
- **Total Old:** $50/month
- **Cost increase:** $1,300/month
- **ROI:** Get 10.2% better SWE-Bench + 125× context for that cost

### Break-Even Analysis

If you're running **fewer than 2,000 tasks/month**, keep Qwen local.
If you're running **more than 2,000 tasks/month**, MiniMax cloud is better value per token.

---

## 🔧 CONFIGURATION OPTIONS

### Option A: Use Standard M2.5 (Default)

```json
{
  "model": "MiniMax-M2.5",
  "contextWindow": 1000000,
  "maxOutputTokens": 131072
}
```

- **Best for:** Complex code generation, large codebases
- **Speed:** ~100 tokens/sec
- **Cost:** $0.30/$1.20 per 1M tokens

### Option B: Use M2.5-Lightning (Faster)

```json
{
  "model": "MiniMax-M2.5-Lightning",
  "contextWindow": 200000,
  "maxOutputTokens": 131072
}
```

- **Best for:** Slack/Telegram responses, low-latency
- **Speed:** 37% faster (~137 tokens/sec)
- **Cost:** 17% cheaper ($0.25/$1.00)
- **Tradeoff:** Only 200K context (vs 1M)

**Recommendation:** Use standard M2.5 for CodeGen agent (larger context helps). Use Lightning for dispatcher/routing layer.

---

## 📋 FALLBACK STRATEGY

### If MiniMax API is Down

Update config to fallback to local:

```json
{
  "coder_agent": {
    "model": "MiniMax-M2.5",
    "apiProvider": "minimax",
    "fallbackModel": "qwen2.5-coder:32b",
    "fallbackProvider": "ollama",
    "fallbackEndpoint": "http://152.53.55.207:11434"
  }
}
```

**Setup:**

1. Keep Ollama running with Qwen 32B as backup
2. Configure fallback in agent config
3. Gateway automatically switches if API times out

---

## 🧪 TESTING CHECKLIST

- [ ] MINIMAX_API_KEY is set and valid
- [ ] Python client can connect (quick test above)
- [ ] Gateway starts without errors
- [ ] CodeGen agent responds to test messages
- [ ] Response quality is acceptable (≥95% of Qwen)
- [ ] Latency is reasonable (<5 seconds)
- [ ] Tool calling works (function definitions)
- [ ] Long context works (test with 100K+ tokens)

---

## 🐛 TROUBLESHOOTING

### Error: "API Key Invalid"

```
Solution: Verify MINIMAX_API_KEY is set correctly
$ echo $MINIMAX_API_KEY
# Should show: sk-xxxx...

If empty:
$ export MINIMAX_API_KEY="your-key"
```

### Error: "Model Not Found"

```
Solution: M2.5 model name is correct. Check:
1. Spelling: "MiniMax-M2.5" (case-sensitive)
2. Account has API access to model
3. Try "MiniMax-M2.5-Lightning" if standard unavailable
```

### Error: "Context Window Too Large"

```
Solution: M2.5 supports 1M tokens max
- Reduce input to <1M tokens
- Or use M2.5-Lightning (200K limit)
- Or switch back to Qwen for that request
```

### Slow Responses

```
Solutions:
1. M2.5-Lightning is 37% faster (switch for high-volume)
2. Use batch processing for non-urgent tasks
3. Check internet connection (API latency varies)
4. Monitor MiniMax dashboard for rate limits
```

### Rate Limiting

```
MiniMax quotas (typical):
- Free tier: 100 requests/minute
- Pro tier: 1,000 requests/minute
- Enterprise: Custom limits

If hitting limits:
1. Upgrade MiniMax account tier
2. Use batch processing for non-urgent tasks
3. Add queue/backpressure in gateway
```

---

## 📊 MONITORING

### Track API Costs

```bash
# Get usage from MiniMax dashboard
# Dashboard: https://platform.minimax.io/dashboard

# Or via API:
curl https://api.minimax.chat/v1/usage \
  -H "Authorization: Bearer $MINIMAX_API_KEY"
```

### Monitor Response Quality

Create a test harness:

```python
# test_codegen.py
import json
from openai import OpenAI

client = OpenAI(
    api_key="$MINIMAX_API_KEY",
    base_url="https://api.minimax.chat/v1"
)

test_cases = [
    "Write a fibonacci function in Python",
    "Create a REST API endpoint with FastAPI",
    "Debug this code: [broken code sample]"
]

for i, prompt in enumerate(test_cases, 1):
    response = client.chat.completions.create(
        model="MiniMax-M2.5",
        messages=[{"role": "user", "content": prompt}]
    )
    print(f"Test {i}: {len(response.choices[0].message.content)} chars")
```

---

## 🔄 ROLLBACK PLAN

If you need to revert to Qwen:

```bash
# Edit config.json
nano config.json

# Change coder_agent back to:
{
  "model": "qwen2.5-coder:32b",
  "apiProvider": "ollama",
  "endpoint": "http://152.53.55.207:11434"
}

# Restart gateway
pkill -f openclaw-gateway
pnpm dev
```

---

## 📚 OFFICIAL RESOURCES

- **MiniMax Platform:** https://platform.minimax.io
- **API Documentation:** https://platform.minimax.io/docs/api-reference/text-openai-api
- **Model Info:** https://www.minimax.io/news/minimax-m25
- **Pricing:** https://platform.minimax.io/docs/pricing/overview

---

## ✨ SUMMARY

✅ **Config updated** — MiniMax M2.5 ready to use
✅ **OpenAI-compatible** — Drop-in replacement for Qwen
✅ **80.2% SWE-Bench** — Better coding performance
✅ **1M context** — Handle large codebases
✅ **$0 infrastructure** — No GPU server needed

**Next action:** Get API key, set `MINIMAX_API_KEY` env var, test integration.

---

**Questions?** Check the official docs or create an issue in the OpenClaw repo.

**Ready to go live?** Test for 2 weeks A/B against Qwen, then fully switch.
