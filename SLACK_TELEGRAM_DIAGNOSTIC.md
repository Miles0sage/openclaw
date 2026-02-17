# Slack & Telegram Diagnostic Report — 2026-02-17

## Current Status

### ✅ Available Secrets (Northflank)

```
openclaw-secrets:
  - GITHUB_PAT: ghp_*****[REDACTED]*****
  - SLACK_BOT_TOKEN: xoxb-*****[REDACTED]*****
  - FAST_IO_API_KEY: pc69cc5h*****[REDACTED]*****

athorpic (typo - should be "anthropic"):
  - ANTHROPIC_API_KEY: sk-ant-api03-*****[REDACTED]*****
```

### ❌ Missing Secrets

1. **TELEGRAM_BOT_TOKEN** — Needed for Telegram webhook
   - Currently hardcoded in config.json (line 8)
   - Not reloadable without restart
   - Should move to Northflank secrets

2. **SLACK_SIGNING_SECRET** — Needed for request verification
   - Must get from Slack App settings → **Settings** → **Basic Information** → **Signing Secret**
   - Required for security (prevents replay attacks)

3. **SLACK_REPORT_CHANNEL** — Optional, defaults to #general
   - Current: Not set (defaults to #general)
   - Can be: #alerts, #billing, #agents, etc.

## Why Telegram is Not Working

### Issue 1: Token Not in Environment

- Telegram token is hardcoded in `config.json` line 8
- Gateway doesn't have `TELEGRAM_BOT_TOKEN` env var
- Gateway uses `CONFIG.get("channels", {}).get("telegram", {}).get("botToken")`
- **This actually SHOULD work**, but...

### Issue 2: Telegram Webhook Not Configured

- Telegram needs webhook URL set via API
- Current webhook URL in code: `/telegram/webhook`
- **Northflank public URL:** `http://152.53.55.207:18789/telegram/webhook`
- **Cloudflare tunnel:** `https://api--openclaw-api--gjb9ygmxnk48.code.run/telegram/webhook`

### Issue 3: Telegram Bot Not Receiving Messages

- Telegram webhook must be registered with Telegram API
- Need to call: `https://api.telegram.org/botTOKEN/setWebhook?url=...`

## Solution Steps

### Step 1: Verify Telegram Webhook is Registered

```bash
# Check current webhook
curl https://api.telegram.org/bot8327486359:AAGECiQ1DsVUuBtrMgGzXnANhI_B9nfQZIQ/getWebhookInfo

# If empty/null, set webhook:
curl https://api.telegram.org/bot8327486359:AAGECiQ1DsVUuBtrMgGzXnANhI_B9nfQZIQ/setWebhook \
  -d url="https://api--openclaw-api--gjb9ygmxnk48.code.run/telegram/webhook"
```

### Step 2: Get Slack Signing Secret

1. Go to https://api.slack.com/apps
2. Select "OpenClaw Bot" (or create if missing)
3. Click **Settings** → **Basic Information**
4. Scroll to **Signing Secret**
5. Copy the value (starts with `whsec_` or similar)

### Step 3: Add Secrets to Northflank

```bash
# Add Telegram token
northflank update secret --project Overseer-Openclaw --secret openclaw-secrets \
  --variable TELEGRAM_BOT_TOKEN="8327486359:AAGECiQ1DsVUuBtrMgGzXnANhI_B9nfQZIQ"

# Add Slack Signing Secret (REPLACE with actual value from Step 2)
northflank update secret --project Overseer-Openclaw --secret openclaw-secrets \
  --variable SLACK_SIGNING_SECRET="<YOUR_SIGNING_SECRET_HERE>"

# Add Slack Report Channel
northflank update secret --project Overseer-Openclaw --secret openclaw-secrets \
  --variable SLACK_REPORT_CHANNEL="#general"
```

### Step 4: Restart Gateway (Northflank)

- The service will automatically redeploy when secrets change
- Or manually restart via: `northflank restart service --project Overseer-Openclaw --service openclaw-api`

### Step 5: Test Both Integrations

```bash
# Test Telegram in Telegram app (send a message to the bot)

# Test Slack reporting
curl http://152.53.55.207:18789/slack/report/health \
  -H "X-Auth-Token: f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3"
```

## Files Already Updated

- ✅ `gateway.py` — Added Slack webhook + reporting endpoints
- ✅ `config.json` — Added Slack channel config
- ❌ Secrets — Still need to add to Northflank

## Next Actions (For User)

1. Get Slack Signing Secret from Slack app settings
2. Run northflank commands to add secrets
3. Restart gateway
4. Test both Telegram and Slack
5. Verify sessions are being saved
