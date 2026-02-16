# 🚀 Quick GPU VPS Setup

## 📊 Your Setup

- **This VPS (OpenClaw):** Current location
- **GPU VPS:** 152.53.55.207 (has 5 Ollama models)

---

## ⚡ 2-Step Setup

### Step 1: On GPU VPS (152.53.55.207)

SSH into your GPU VPS and run:

```bash
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGta1s3rQseT0RHIj9YJWE6a+yltg/qGfkp+UndbHndB ollama-vps' >> ~/.ssh/authorized_keys
```

That's it for GPU VPS!

---

### Step 2: On This VPS (OpenClaw)

Run the automated setup:

```bash
cd /root/openclaw
./SETUP-GPU-VPS-CONNECTION.sh
```

**This script will:**

1. ✅ Test SSH connection to GPU VPS
2. ✅ Check Ollama is running (5 models)
3. ✅ Create SSH tunnel (localhost:11434 → GPU:11434)
4. ✅ Update OpenClaw to use GPU models
5. ✅ Restart gateway with new config
6. ✅ Test GPU-accelerated agents

**Duration:** ~2 minutes

---

## 🎮 Available GPU Models

```
✅ gemma2:9b
✅ qwen3:14b
✅ qwen2.5:32b           ← Security Agent
✅ qwen2.5-coder:32b     ← Coder Agent
✅ qwen2.5-coder:latest
```

---

## 📊 After Setup

**Configuration:**

```
🎯 PM:       Claude Sonnet 4.5  (cloud, $3/1M)
💻 Coder:    Qwen2.5-Coder 32B  (GPU, FREE) 🚀
🔒 Security: Qwen2.5 32B        (GPU, FREE) 🚀
```

**Performance:**

- Before: 120s timeout (CPU)
- After: 5-10s response (GPU) ✅

**Cost:**

- Before: $20-30/month (all cloud)
- After: $3-5/month (hybrid) ✅

---

## 🧪 Test Commands

```bash
# Test health
curl http://localhost:18789/

# Test coder (GPU)
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Write a hello world", "agent_id": "coder_agent"}'

# Test security (GPU)
curl -X POST http://localhost:18789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"content": "Security review tips", "agent_id": "hacker_agent"}'
```

---

## 🔧 Troubleshooting

### Tunnel Lost Connection

```bash
# Restart tunnel
ssh -f -N -L 11434:localhost:11434 root@152.53.55.207
```

### Check Tunnel Status

```bash
lsof -i :11434
# Should show ssh process
```

### Restart Everything

```bash
./SETUP-GPU-VPS-CONNECTION.sh
```

---

**Ready?** Run the setup script! 🚀
