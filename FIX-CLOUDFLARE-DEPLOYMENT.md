# 🔧 Fix Cloudflare Workers Deployment Error

## ❌ Current Error

```
✘ [ERROR] Image "registry.cloudflare.com/***/overseer-spark-sparksandbox:8b8c68e3"
  does not belong to your account
  Image appears to belong to account: "***"
  Current account: "***"
```

**Cause:** The Docker image is being pushed to the wrong Cloudflare account's container registry.

---

## ✅ Solution

### Step 1: Get Your Cloudflare Account ID

1. Go to https://dash.cloudflare.com/
2. Select your account
3. Go to **Workers & Pages** → **Overview**
4. Your Account ID is shown on the right side
5. Copy it (format: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`)

---

### Step 2: Update Repository Secrets

In your GitHub repository: https://github.com/Miles0sage/moltbot-sandbox

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Update or create these secrets:

```
CLOUDFLARE_ACCOUNT_ID = your-account-id-from-step-1
CLOUDFLARE_API_TOKEN = your-cloudflare-api-token
```

---

### Step 3: Update wrangler.toml

In your repo, edit `wrangler.toml`:

```toml
name = "overseer-spark"
main = "dist/server/index.js"
compatibility_date = "2024-01-01"
account_id = "YOUR_ACTUAL_ACCOUNT_ID"  # ← UPDATE THIS

# ... rest of config
```

---

### Step 4: Clear Old Container Images

The old image with wrong account needs to be removed:

**Option A: Through Cloudflare Dashboard**

1. Go to https://dash.cloudflare.com/
2. Workers & Pages → Container Registry
3. Delete old `overseer-spark-sparksandbox` images

**Option B: Through wrangler CLI**

```bash
wrangler containers delete overseer-spark-sparksandbox:8b8c68e3
```

---

### Step 5: Update GitHub Actions Workflow

Check `.github/workflows/deploy.yml`:

```yaml
- name: Deploy to Cloudflare
  env:
    CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
    CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
  run: |
    npx wrangler deploy
```

Make sure:

- ✅ Secrets are correctly referenced
- ✅ wrangler version is up to date (`4.63.0` latest)
- ✅ Account ID matches your Cloudflare dashboard

---

### Step 6: Redeploy

```bash
git add .
git commit -m "Fix: Update Cloudflare account ID"
git push origin main
```

GitHub Actions will trigger and should deploy successfully!

---

## 🔍 Debugging Tips

### Check Current Configuration

```bash
# In your repo
cat wrangler.toml | grep account_id

# Should output:
# account_id = "your-correct-account-id"
```

### Verify Wrangler Auth

```bash
npx wrangler whoami
```

Should show your correct Cloudflare account.

### Check Container Registry

```bash
npx wrangler containers list
```

Lists all container images in your account.

---

## 🎯 Quick Fix Checklist

- [ ] Get Cloudflare Account ID from dashboard
- [ ] Update GitHub Secrets (CLOUDFLARE_ACCOUNT_ID)
- [ ] Update `wrangler.toml` with correct account_id
- [ ] Delete old container images
- [ ] Push changes to trigger redeploy
- [ ] Verify deployment succeeds

---

## 📚 Related Docs

- Cloudflare Workers: https://developers.cloudflare.com/workers/
- Container Registry: https://developers.cloudflare.com/workers/container-registry/
- Wrangler CLI: https://developers.cloudflare.com/workers/wrangler/

---

**After fixing Cloudflare, run the GPU VPS setup!** 🎮
