# ⚡ Cloudflare Tunnel - Quick Start

**Get your OpenClaw instance online in 5 minutes!**

---

## 🎯 What You Need

1. **✅ Domain name** (any registrar - Namecheap, GoDaddy, etc.)
   - Add to Cloudflare (free account)
   - Or use Cloudflare Registrar directly

2. **✅ OpenClaw running** on this VPS

   ```bash
   curl http://localhost:18789/
   ```

3. **✅ 5 minutes** of your time

**Don't have a domain?** See "Alternative: Cloudflare Quick Tunnel" below

---

## 🚀 One-Command Setup

```bash
# Run the automated installer
cd /root/openclaw
./setup-cloudflare-tunnel.sh
```

**This will:**

1. Install `cloudflared`
2. Login to Cloudflare (opens browser)
3. Create tunnel
4. Configure DNS
5. Install as system service
6. Test connection

**Done in 5 minutes!** ✨

---

## 📋 What You'll Be Asked

### 1. Tunnel Name

```
Enter tunnel name [openclaw]:
```

**Just press Enter** to use default `openclaw`

### 2. Your Domain

```
Enter your domain (e.g., example.com): yourdomain.com
```

**Enter your domain** (the one you added to Cloudflare)

### 3. Subdomain

```
Enter subdomain [openclaw]:
```

**Just press Enter** to use `openclaw.yourdomain.com`

**That's it!** The script does the rest.

---

## 🎉 After Setup

Your gateway is accessible at:

```
Gateway:    https://openclaw.yourdomain.com/
WebSocket:  wss://openclaw.yourdomain.com/ws
Cline API:  https://openclaw.yourdomain.com/api/cline/poll
```

### Test It

```bash
# From anywhere in the world!
curl https://openclaw.yourdomain.com/

# Expected response:
# {"name": "OpenClaw Gateway", "status": "online", "agents": 3}
```

---

## 🔧 Managing the Tunnel

### Check Status

```bash
sudo systemctl status cloudflared
```

### View Logs

```bash
sudo journalctl -u cloudflared -f
```

### Restart

```bash
sudo systemctl restart cloudflared
```

### Stop

```bash
sudo systemctl stop cloudflared
```

---

## 🌐 Update Cline to Use Cloudflare

Now Cline can connect from anywhere!

### VS Code Settings (`.vscode/settings.json`)

```json
{
  "cline.openclawGateway": "https://openclaw.yourdomain.com",
  "cline.pollEndpoint": "https://openclaw.yourdomain.com/api/cline/poll"
}
```

### Polling Script

```bash
# Poll every 5 seconds
while true; do
  curl -s https://openclaw.yourdomain.com/api/cline/poll?since=$(date +%s)000 | jq
  sleep 5
done
```

---

## 🔒 Secure It (Recommended)

### Enable Zero Trust Access Control

1. Go to https://one.dash.cloudflare.com/
2. **Access** → **Applications** → **Add application**
3. **Self-hosted** → Enter `openclaw.yourdomain.com`
4. **Create policy:**
   - **Name:** Allow my team
   - **Include:** Emails: `you@email.com`
5. **Save**

Now only you can access the gateway! 🔐

### Enable Rate Limiting

In Cloudflare Dashboard:

1. **Security** → **WAF** → **Rate limiting rules**
2. **Create rule:**
   - **Name:** API rate limit
   - **If:** URI contains `/api/`
   - **Then:** Block if > 100 requests/minute

---

## 🆚 Cloudflare vs Tailscale

| Feature           | Cloudflare Tunnel | Tailscale |
| ----------------- | ----------------- | --------- |
| **Public Access** | ✅ Yes            | ❌ No     |
| **Setup Time**    | 5 min             | 2 min     |
| **Cost**          | Free              | Free      |
| **Security**      | Zero Trust        | VPN       |
| **Webhooks**      | ✅ Yes            | ❌ No     |
| **Global CDN**    | ✅ Yes            | ❌ No     |

**Use Both:**

- **Cloudflare:** Public API, webhooks, Cline
- **Tailscale:** Private admin access

---

## ⚠️ Troubleshooting

### "502 Bad Gateway"

**Cause:** OpenClaw not running

**Fix:**

```bash
cd /root/openclaw && python3 gateway.py &
```

### "Tunnel not connecting"

**Fix:**

```bash
sudo systemctl restart cloudflared
sudo journalctl -u cloudflared -n 50
```

### "DNS not resolving"

**Wait 5 minutes** for DNS propagation, then:

```bash
dig openclaw.yourdomain.com
# Should show CNAME to *.cfargotunnel.com
```

---

## 💡 Alternative: Cloudflare Quick Tunnel (No Domain Needed!)

If you **don't have a domain**, use Quick Tunnel:

```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# Run quick tunnel (gets temporary URL)
cloudflared tunnel --url http://localhost:18789
```

**Output:**

```
Your quick Tunnel has been created! Visit it at:
https://random-name-1234.trycloudflare.com
```

**Use this URL for testing!**

**Note:** Quick Tunnel URL changes on every restart. For production, use a real domain.

---

## 📚 Full Documentation

- **Complete Guide:** `/root/openclaw/CLOUDFLARE-TUNNEL-SETUP.md`
- **Config File:** `~/.cloudflared/config.yml`
- **Cloudflare Docs:** https://developers.cloudflare.com/cloudflare-one/connections/connect-apps

---

## 🎯 Summary

**What you get:**

✅ **Stable HTTPS connection** from anywhere
✅ **Free** (Cloudflare free tier)
✅ **DDoS protection** built-in
✅ **Global CDN** for fast access worldwide
✅ **Zero Trust** access control
✅ **Webhooks support** for Telegram/Discord/Slack
✅ **WebSocket support** for real-time communication
✅ **Cline integration** from anywhere

**Setup time:** 5 minutes

**Cost:** $0/month

**Command:** `./setup-cloudflare-tunnel.sh`

**Access:** `https://openclaw.yourdomain.com`

🎊 **That's it! You're globally connected!** 🌐
