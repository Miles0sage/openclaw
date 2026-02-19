# Email Notification System — Quick Start

Get client email notifications working in 5 minutes.

## 30-Second Setup

### 1. Choose Your Backend

**Option A: SendGrid (Production) — 2 minutes**

```bash
# Get API key from https://app.sendgrid.com/settings/api_keys
export SENDGRID_API_KEY="SG.xxxxx"
export FROM_EMAIL="notifications@openclaw.agency"
export FROM_NAME="OpenClaw Agency"
```

**Option B: SMTP (Self-Hosted) — 2 minutes**

```bash
export SMTP_HOST="mail.example.com"
export SMTP_PORT="587"
export SMTP_USER="noreply@example.com"
export SMTP_PASS="secure-password"
export FROM_EMAIL="notifications@openclaw.agency"
export FROM_NAME="OpenClaw Agency"
```

**Option C: File Logging (Dev) — 0 minutes**
No setup. Just use it.

### 2. Verify It Works

```bash
# Test email backend
curl -X POST http://localhost:18789/api/notifications/test \
  -H "Content-Type: application/json" \
  -d '{"to": "your-email@example.com"}'
```

Expected response: `"success": true`

### 3. That's It!

When clients submit jobs with `contact_email`, they'll get notified automatically:

- ✅ When job starts
- ✅ When job completes
- ✅ If job fails
- ✅ If job gets cancelled
- ⚠️ If approaching budget limit

## Test It Now

### Submit a Test Job

```bash
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Test Project",
    "description": "Test email notifications",
    "task_type": "feature_build",
    "priority": "P2",
    "budget_limit": 50.0,
    "contact_email": "your-email@example.com"
  }'
```

Save the `job_id` from response.

### Simulate Job Completion

```bash
# Update job status to trigger email
python3 << 'EOF'
from intake_routes import update_job_status
job_id = "YOUR_JOB_ID_HERE"
update_job_status(job_id, "researching", "Job is now being researched")
EOF
```

Check your email! You should get: "🚀 Your job 'Test Project' has started"

### Check Notification History

```bash
curl http://localhost:18789/api/notifications/history?job_id=YOUR_JOB_ID
```

## How It Works

```
Job Status Changes (agent calls update_job_status)
        ↓
Email System Triggered Automatically
        ↓
Status Transition Check
        ├─ queued → researching: SEND "Job Started"
        ├─ * → done: SEND "Job Completed"
        ├─ * → failed: SEND "Job Failed"
        ├─ * → cancelled: SEND "Job Cancelled"
        └─ Cost ≥ 80% of budget: SEND "Budget Warning"
        ↓
Rate Limiting Check
        ├─ Max 10 emails per job (spam prevention)
        └─ Skip if sent within 5 minutes (dedup)
        ↓
Backend Send
        ├─ SendGrid API (production)
        ├─ SMTP (self-hosted)
        └─ Log to file (dev mode)
```

## Common Use Cases

### 1. Client Wants Job Updates

Ensure job includes `contact_email` when submitting:

```bash
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Build Feature X",
    "description": "Implement new dashboard",
    "task_type": "feature_build",
    "contact_email": "client@their-company.com",  # ← KEY
    "budget_limit": 100.0,
    "priority": "P1"
  }'
```

### 2. Monitor Job Progress

```bash
# Get live history
watch -n 5 'curl -s http://localhost:18789/api/notifications/history | jq .'

# Or filter by job
watch -n 5 'curl -s "http://localhost:18789/api/notifications/history?job_id=ABC123" | jq .'
```

### 3. Check What Went Wrong

```bash
# Find failed emails
curl -s http://localhost:18789/api/notifications/history | \
  jq '.notifications[] | select(.status == "failed")'
```

### 4. Test Before Production

```bash
# Send test email first
curl -X POST http://localhost:18789/api/notifications/test \
  -H "Content-Type: application/json" \
  -d '{"to": "admin@openclaw.agency"}'

# Check config
curl http://localhost:18789/api/notifications/config | jq .
```

## Email Formats

### What Client Sees

All emails are **dark-themed**, **professional**, **mobile-responsive**:

| Email Type    | Icon | When Sent                 | Key Info                    |
| ------------- | ---- | ------------------------- | --------------------------- |
| Job Started   | 🚀   | Job begins execution      | Job ID, Assigned Agent      |
| Job Completed | ✅   | Job finishes successfully | Cost incurred, Next steps   |
| Job Failed    | ⚠️   | Job encounters error      | Error details, Support info |
| Job Cancelled | ⏸️   | Client cancels job        | Partial cost refund info    |
| Budget Alert  | 💰   | Cost hits 80% of limit    | Current % used, Warning     |

## Troubleshooting

### Emails Not Arriving?

1. **Check email exists:**

   ```bash
   curl http://localhost:18789/api/jobs/{job_id} | jq .contact_email
   ```

2. **Check if sent:**

   ```bash
   curl http://localhost:18789/api/notifications/history | jq '.notifications[] | {timestamp, recipient, status, error}'
   ```

3. **Check backend:**

   ```bash
   curl http://localhost:18789/api/notifications/config | jq .
   ```

4. **Test backend directly:**
   ```bash
   curl -X POST http://localhost:18789/api/notifications/test \
     -d '{"to": "test@example.com"}'
   ```

### SendGrid Issues?

1. API key valid?

   ```bash
   curl -H "Authorization: Bearer $SENDGRID_API_KEY" \
     https://api.sendgrid.com/v3/scopes | jq .
   ```

2. Check SendGrid logs:
   ```bash
   # https://sendgrid.com/settings/mail_settings
   # Check "Email Activity" section
   ```

### SMTP Issues?

1. Can you reach the server?

   ```bash
   telnet $SMTP_HOST $SMTP_PORT
   # Should connect
   ```

2. Check credentials:
   ```bash
   python3 << 'EOF'
   import smtplib
   try:
       server = smtplib.SMTP('mail.example.com', 587)
       server.starttls()
       server.login('noreply@example.com', 'password')
       print("✓ Login successful")
       server.quit()
   except Exception as e:
       print(f"✗ Error: {e}")
   EOF
   ```

### Spam Folder?

1. Check DNS SPF record:

   ```bash
   nslookup -type=TXT example.com | grep v=spf
   ```

2. Add DKIM:
   - For SendGrid: auto-enabled
   - For SMTP: set up in mail server admin

3. Add DMARC:
   - Create `_dmarc.example.com` TXT record

## File Locations

| File                                       | Purpose                  | Size           |
| ------------------------------------------ | ------------------------ | -------------- |
| `/tmp/openclaw_emails.jsonl`               | Raw email log (dev mode) | ~1KB per email |
| `/tmp/openclaw_notification_dedup.json`    | Dedup cache              | ~1KB           |
| `/tmp/openclaw_notification_history.jsonl` | Email history            | ~1KB per email |

## Performance

- **Email rendering:** <10ms per template
- **Backend send:** <1s (SendGrid) or <2s (SMTP)
- **Rate limiting:** O(1) cache lookup
- **History storage:** Append-only JSONL (~1KB per email)

## Security

- **No plaintext storage** of passwords — uses env vars only
- **Secrets never logged** — config endpoint redacts keys
- **Email addresses hashed** for dedup — privacy-safe
- **TLS for SMTP** — starttls() enforced
- **API key auth** — SendGrid uses bearer tokens

## Next Steps

1. ✅ Choose backend (SendGrid/SMTP/File)
2. ✅ Set env vars
3. ✅ Test with `/api/notifications/test`
4. ✅ Create test job with contact_email
5. ✅ Verify email arrives
6. ✅ Go live!

## Support

For issues:

1. Check `/tmp/openclaw_notification_history.jsonl` for logs
2. Run `/api/notifications/config` to verify backend
3. Review `EMAIL_NOTIFICATIONS.md` for detailed docs
4. Check test suite: `python3 -m pytest test_email_notifications.py -v`

## Cost Estimate

| Backend  | Cost        | Best For                        |
| -------- | ----------- | ------------------------------- |
| SendGrid | $0-30/month | Production (millions of emails) |
| SMTP     | Self-hosted | Your own mail server            |
| File     | Free        | Development                     |

**OpenClaw Use Case:** ~50-200 notifications/month = SendGrid free tier ($0)
