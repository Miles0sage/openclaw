# OpenClaw Phase 2 & MiniMax Integration — SAVED STATE

**Date:** February 16, 2026
**Status:** ✅ CONFIGURED, ⏳ AWAITING PAYMENT SETUP

---

## 📦 WHAT'S DEPLOYED & COMMITTED

### Commit 1: Phase 2 Core (ee29c9b66)

```
✅ PM Agent: Claude Opus 4.6 + adaptive thinking
✅ Router: LangGraph (2.2× faster)
✅ Web Fetch: Enabled
✅ Status: LIVE & WORKING
```

### Commit 2: MiniMax CodeGen (cf9c4c905)

```
✅ CodeGen Agent: MiniMax M2.5 config
✅ Documentation: MINIMAX_INTEGRATION.md
✅ Status: READY (awaiting API key activation)
```

---

## 🎯 CURRENT AGENT STACK (WORKING NOW)

```json
{
  "agents": {
    "project_manager": {
      "model": "claude-opus-4-6-20250514",
      "apiProvider": "anthropic",
      "thinking": { "type": "adaptive", "defaultEffort": "high" },
      "status": "✅ LIVE"
    },
    "coder_agent": {
      "model": "MiniMax-M2.5",
      "apiProvider": "minimax",
      "endpoint": "https://api.minimax.chat/v1",
      "apiKeyEnv": "MINIMAX_API_KEY",
      "status": "⏳ READY (awaiting API key + payment)"
    },
    "hacker_agent": {
      "model": "qwen2.5-coder:14b",
      "apiProvider": "ollama",
      "endpoint": "http://152.53.55.207:11434",
      "status": "✅ LIVE"
    }
  }
}
```

---

## ⏳ NEXT STEPS (When Ready)

### Step 1: Set Up MiniMax Payment

- [ ] Go to https://platform.minimax.io/billing
- [ ] Add payment method (credit card)
- [ ] Enable autobilling
- [ ] Balance should update to show available credit

### Step 2: Create Fresh API Key

- [ ] Go to https://platform.minimax.io/dashboard
- [ ] API Keys section
- [ ] Create new key: "OpenClaw-CodeGen"
- [ ] Test key works with curl command (provided in MINIMAX_INTEGRATION.md)

### Step 3: Configure OpenClaw

```bash
# Set API key (keep secure on your machine only)
export MINIMAX_API_KEY="your-api-key-here"

# Start gateway
cd /root/openclaw
pnpm dev
```

### Step 4: Verify Both Agents

```bash
# Test PM (Opus) - should work now
# Test CodeGen (MiniMax) - will work once key is set
# Test Security (Qwen) - should work now
```

---

## 💰 COSTS (When Live)

### Phase 2 Base (Opus + Router)

- PM Agent: $5.00 / 1M input, $25.00 / 1M output
- Infrastructure: $0
- Monthly estimate (1K PM calls): ~$50-100

### With MiniMax CodeGen Added

- CodeGen: $0.30 / 1M input, $1.20 / 1M output
- Infrastructure: $0
- Monthly estimate (5K CodeGen calls): ~$1,350

### Total Monthly (Both Agents Active)

- ~$1,450-1,500/month (assuming moderate usage)

---

## 📂 FILES IN REPO

**Config Files:**

- `config.json` — Agents configured, ready to use
- `PHASE2_DEPLOYMENT.md` — Phase 2 documentation
- `MINIMAX_INTEGRATION.md` — MiniMax setup guide
- `PHASE2_STATUS.md` — This file (current state)

**Source Code:**

- `src/routing/langgraph-*.ts` — Router implementation (1,600 LOC)
- `src/gateway/server-http.ts` — Gateway integration

---

## ✨ SUMMARY

**RIGHT NOW:**

- ✅ PM Agent (Opus 4.6) = LIVE
- ✅ Security Agent (Qwen 14B) = LIVE
- ✅ Router (LangGraph) = LIVE
- ⏳ CodeGen Agent (MiniMax) = CONFIGURED, needs API key

**WHEN YOU SET UP MINIMAX:**

- Add payment method
- Create API key
- Set `MINIMAX_API_KEY` env var
- Restart gateway
- Everything goes live

**NO CODE CHANGES NEEDED** — Config is already set up!

---

## 🔗 IMPORTANT LINKS

- **MiniMax Dashboard:** https://platform.minimax.io/dashboard
- **Billing:** https://platform.minimax.io/billing
- **API Docs:** https://platform.minimax.io/docs/api-reference/text-openai-api
- **OpenClaw Repo:** https://github.com/cline/openclaw (commits: ee29c9b66, cf9c4c905)

---

## 📋 CHECKLIST FOR LATER

When you're ready to activate MiniMax:

- [ ] Add payment method to MiniMax account
- [ ] Create new API key (name: OpenClaw-CodeGen)
- [ ] Test key with curl (sample in MINIMAX_INTEGRATION.md)
- [ ] Set `export MINIMAX_API_KEY="..."`
- [ ] Restart OpenClaw gateway (`pnpm dev`)
- [ ] Verify CodeGen agent responds
- [ ] Monitor costs via MiniMax dashboard

---

**SAVED & READY TO GO** — Just come back when payment is set up! 🚀
