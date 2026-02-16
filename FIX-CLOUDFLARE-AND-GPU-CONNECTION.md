# 🔧 Fix Plan

## Issue 1: Cloudflare Container Registry Error

**Problem:** Container image pushed to wrong account registry
**Solution:** Update wrangler.toml to use correct account ID

### Fix Steps:

1. Get your Cloudflare Account ID from dashboard
2. Update `wrangler.toml`:
   ```toml
   account_id = "YOUR_ACTUAL_ACCOUNT_ID"
   ```
3. Clear old container images
4. Redeploy

## Issue 2: Connect OpenClaw to GPU VPS Ollama

**Problem:** Current VPS has NO GPU, Ollama is slow
**Solution:** Configure OpenClaw to use REMOTE Ollama on GPU VPS

### Architecture:

```
┌─────────────────────────┐
│ Current VPS (No GPU)    │
│ - OpenClaw Gateway      │
│ - Claude API            │
└──────────┬──────────────┘
           │ HTTP
           │ Port 11434
           ▼
┌─────────────────────────┐
│ GPU VPS                 │
│ - Ollama Server         │
│ - Qwen2.5-Coder Models  │
└─────────────────────────┘
```

### Configuration Steps:

1. **On GPU VPS:** Expose Ollama to network
2. **On Current VPS:** Point OpenClaw to GPU VPS Ollama
3. **Test:** Verify connection works
