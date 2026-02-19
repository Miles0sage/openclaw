# Email Notification System — OpenClaw Agency

A production-ready email notification system for OpenClaw AI agency that alerts clients when jobs complete, fail, or need attention.

## Features

- **Multi-backend support:**
  - SendGrid API (production) via `SENDGRID_API_KEY` env var
  - SMTP (self-hosted) via `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
  - File logging (dev mode) to `/tmp/openclaw_emails.jsonl` if neither configured

- **Smart Notifications:**
  - Job lifecycle: queued → researching → executing → done
  - Status transitions trigger appropriate emails
  - Budget warnings at 80% threshold
  - Cost tracking per job and agent

- **Rate Limiting & Deduplication:**
  - Max 10 emails per job (prevent spam on rapid status changes)
  - Dedup window: don't send same notification type within 5 minutes
  - Persistent history in `/tmp/openclaw_notification_history.jsonl`

- **Professional HTML Templates:**
  - Dark theme with inline CSS (email-safe, no external assets)
  - Responsive design for mobile and desktop
  - Gradient headers by notification type
  - Clear call-to-action elements

- **RESTful API:**
  - `POST /api/notifications/test` — Test email backend
  - `GET /api/notifications/history` — View sent notifications
  - `GET /api/notifications/config` — Check backend status

## Installation

### 1. Copy Files

```bash
cp email_notifications.py /root/openclaw/
cp test_email_notifications.py /root/openclaw/
```

### 2. Update intake_routes.py

The system is already integrated into `intake_routes.py`. Status updates automatically trigger notifications:

```python
# In update_job_status() and cancel_job():
from email_notifications import notify_status_change
notify_status_change(job_id, old_status, new_status, job)
```

### 3. Mount Router in gateway.py

If not already done:

```python
from email_notifications import router as email_router

app = FastAPI()
app.include_router(email_router)
```

## Configuration

### Environment Variables

Set one of these to activate email sending:

**SendGrid (Production):**

```bash
export SENDGRID_API_KEY="SG.xxxxx"
export FROM_EMAIL="notifications@openclaw.agency"
export FROM_NAME="OpenClaw Agency"
```

**SMTP (Self-Hosted):**

```bash
export SMTP_HOST="mail.example.com"
export SMTP_PORT="587"
export SMTP_USER="noreply@example.com"
export SMTP_PASS="secure-password"
export FROM_EMAIL="notifications@openclaw.agency"
export FROM_NAME="OpenClaw Agency"
```

**File Logging (Dev Mode):**
No env vars needed. Emails will be logged to `/tmp/openclaw_emails.jsonl` as JSON records.

## Usage

### Automatic Notifications (Integrated)

When `intake_routes.update_job_status()` is called, the system automatically:

1. **Checks if job has contact_email** — skips if not set
2. **Maps status transitions to notification types:**
   - `queued → researching` → "job_started" email
   - `* → done` → "job_completed" email
   - `* → failed` → "job_failed" email
   - `* → cancelled` → "job_cancelled" email
3. **Checks budget threshold** — sends "budget_warning" at 80%
4. **Enforces rate limiting** — max 10 emails per job, 5-minute dedup window
5. **Records in history** — persists to `/tmp/openclaw_notification_history.jsonl`

### Example: Submit a Job with Email

```bash
curl -X POST http://localhost:18789/api/intake \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "Build Dashboard",
    "description": "Create a monitoring dashboard for OpenClaw metrics",
    "task_type": "feature_build",
    "priority": "P1",
    "budget_limit": 100.0,
    "contact_email": "client@example.com"
  }'
```

Response:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "estimated_start": "~5 minutes",
  "message": "Job queued successfully. Assigned to CodeGen Pro."
}
```

When status changes to `researching`:

- Email sent to `client@example.com` with subject "🚀 Your job 'Build Dashboard' has started"
- Recipient sees: job ID, assigned agent, estimated timeline

### Test Email Backend

```bash
curl -X POST http://localhost:18789/api/notifications/test \
  -H "Content-Type: application/json" \
  -d '{"to": "test@example.com"}'
```

Response:

```json
{
  "success": true,
  "backend": "sendgrid",
  "recipient": "test@example.com",
  "message": "Test email sent via SENDGRID"
}
```

### View Notification History

```bash
# All notifications
curl http://localhost:18789/api/notifications/history

# Filter by job
curl http://localhost:18789/api/notifications/history?job_id=550e8400-e29b-41d4-a716-446655440000

# Limit results
curl http://localhost:18789/api/notifications/history?limit=10
```

Response:

```json
{
  "count": 3,
  "limit": 50,
  "notifications": [
    {
      "job_id": "550e8400-e29b-41d4-a716-446655440000",
      "notification_type": "job_started",
      "recipient": "client@example.com",
      "subject": "🚀 Your job 'Build Dashboard' has started",
      "timestamp": "2026-02-19T16:30:45.123456+00:00",
      "status": "sent",
      "error": null
    },
    ...
  ]
}
```

### Check Backend Configuration

```bash
curl http://localhost:18789/api/notifications/config
```

Response:

```json
{
  "backend": "sendgrid",
  "configured": true,
  "from_email": "notifications@openclaw.agency",
  "from_name": "OpenClaw Agency",
  "sendgrid_api_key_present": true
}
```

## Email Templates

### 1. Job Started (🚀)

- **Trigger:** `queued → researching`
- **Theme:** Purple gradient
- **Content:**
  - Project name, job ID, assigned agent
  - Confirmation that job is queued and being executed

### 2. Job Completed (✅)

- **Trigger:** `* → done`
- **Theme:** Green gradient
- **Content:**
  - Project name, job ID, agent name
  - Total cost incurred
  - Invitation to review deliverables

### 3. Job Failed (⚠️)

- **Trigger:** `* → failed`
- **Theme:** Red gradient
- **Content:**
  - Project name, job ID
  - Last 3 error log entries
  - Next steps and contact info

### 4. Job Cancelled (⏸️)

- **Trigger:** `* → cancelled`
- **Theme:** Indigo gradient
- **Content:**
  - Project name, job ID
  - Cost incurred before cancellation
  - Confirmation no further charges

### 5. Budget Warning (💰)

- **Trigger:** Cost reaches 80% of budget_limit
- **Theme:** Amber gradient
- **Content:**
  - Budget limit and current usage
  - Visual progress bar
  - Percentage used
  - Warning about further charges

## Architecture

```
Client Portal (intake_routes.py)
    ↓
submit_intake() → job created with contact_email
    ↓
update_job_status() [called by agents]
    ↓
notify_status_change(job_id, old_status, new_status, job)
    ↓
EmailNotifier.notify_on_status_change()
    ├─ Check contact_email exists
    ├─ Check rate limiting (max 10 emails/job)
    ├─ Check dedup cache (5-min window)
    ├─ Determine notification type (status transition)
    ├─ Render email template
    ├─ Send via backend (SendGrid/SMTP/file)
    ├─ Update dedup cache
    └─ Record in history
```

## Data Files

### `/tmp/openclaw_emails.jsonl`

File-backend log of all emails sent (dev mode):

```json
{
  "timestamp": "2026-02-19T16:30:45.123456+00:00",
  "to": "client@example.com",
  "subject": "🚀 Your job 'Build Dashboard' has started",
  "html_body": "..."
}
```

### `/tmp/openclaw_notification_dedup.json`

Dedup cache to prevent duplicate notifications:

```json
{
  "550e8400-e29b-41d4-a716-446655440000:job_started": "2026-02-19T16:30:45.123456+00:00",
  "550e8400-e29b-41d4-a716-446655440000:budget_warning": "2026-02-19T17:00:00.000000+00:00"
}
```

### `/tmp/openclaw_notification_history.jsonl`

Persistent history of all notifications sent:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "notification_type": "job_started",
  "recipient": "client@example.com",
  "subject": "🚀 Your job 'Build Dashboard' has started",
  "timestamp": "2026-02-19T16:30:45.123456+00:00",
  "status": "sent",
  "error": null
}
```

## Testing

Run the full test suite:

```bash
python3 -m pytest test_email_notifications.py -v
```

Expected output:

```
test_email_notifications.py::TestEmailNotifierInitialization::test_notifier_creates_instance PASSED
test_email_notifications.py::TestTemplateRendering::test_template_job_started PASSED
test_email_notifications.py::TestRateLimitingAndDedup::test_dedup_key_generation PASSED
test_email_notifications.py::TestFileBackend::test_log_to_file PASSED
...
============================== 27 passed in 0.42s ==============================
```

### Test Coverage

- **Initialization:** Backend selection, singleton pattern, cache loading
- **Templates:** All 5 email templates render correctly with dynamic content
- **Rate Limiting:** Max emails per job, dedup within 5-minute window
- **File Backend:** Logging to JSONL, history tracking
- **Notification History:** Filtering, limits, retrieval
- **Status Transitions:** Correct email types for each transition
- **Budget Warnings:** Triggered at 80% threshold
- **Backend Status:** Configuration reporting (secrets redacted)
- **Integration:** Works with intake_routes notify_status_change

## Integration with Existing Systems

### intake_routes.py

Already integrated. When `update_job_status()` is called:

```python
# Inside update_job_status()
from email_notifications import notify_status_change
notify_status_change(job_id, old_status, status, job)
```

Similarly for `cancel_job()`.

### gateway.py

Already registered (if not, add):

```python
from email_notifications import router as email_router
app.include_router(email_router)
```

## Cost Impact

### File Backend (Dev Mode)

Free — just logs to disk.

### SMTP Backend (Self-Hosted)

Free or cost of your mail server.

### SendGrid (Production)

- Free tier: 100 emails/day
- Paid: $10-30/month for millions of emails
- Recommended for production

## Troubleshooting

### Emails Not Sending

1. **Check backend status:**

   ```bash
   curl http://localhost:18789/api/notifications/config
   ```

2. **Check if job has contact_email:**

   ```bash
   curl http://localhost:18789/api/jobs/{job_id} | jq .contact_email
   ```

3. **Check notification history:**

   ```bash
   curl http://localhost:18789/api/notifications/history?job_id={job_id}
   ```

4. **Test email backend:**
   ```bash
   curl -X POST http://localhost:18789/api/notifications/test \
     -H "Content-Type: application/json" \
     -d '{"to": "test@example.com"}'
   ```

### Rate Limiting Too Strict

The system prevents 2 identical notifications within 5 minutes. To adjust:

Edit `/root/openclaw/email_notifications.py`:

```python
DEDUP_WINDOW_MINUTES = 5  # Change this value
```

### Missing Emails in History

Check `/tmp/openclaw_notification_history.jsonl`:

```bash
tail -50 /tmp/openclaw_notification_history.jsonl | python3 -m json.tool
```

## Future Enhancements

1. **Weekly Digest Emails** — Summarize all jobs and costs
2. **Custom Email Templates** — Per-client branding
3. **Webhook Notifications** — Instead of email (Slack, Discord, etc.)
4. **Email Preferences** — Clients can choose which notifications to receive
5. **Analytics Dashboard** — View email open rates, click tracking

## Production Checklist

- [ ] Set `SENDGRID_API_KEY` or SMTP credentials
- [ ] Test with `POST /api/notifications/test`
- [ ] Verify jobs include `contact_email` in submissions
- [ ] Check `/tmp/openclaw_notification_history.jsonl` for logs
- [ ] Monitor `/tmp/openclaw_notification_dedup.json` size (should stay small)
- [ ] Set up log rotation for large history files
- [ ] Add email alerts to monitoring system

## Code Files

| File                          | Lines | Purpose                                              |
| ----------------------------- | ----- | ---------------------------------------------------- |
| `email_notifications.py`      | 784   | Main notifier class, backends, templates, API routes |
| `test_email_notifications.py` | 476   | 27 unit tests, full coverage                         |
| `intake_routes.py`            | +20   | Integration hooks (update_job_status, cancel_job)    |

## API Reference

### `POST /api/notifications/test`

Send a test email to verify backend.

**Request:**

```json
{
  "to": "test@example.com",
  "subject": "Optional custom subject"
}
```

**Response (200):**

```json
{
  "success": true,
  "backend": "sendgrid|smtp|file",
  "recipient": "test@example.com",
  "message": "Test email sent via SENDGRID"
}
```

### `GET /api/notifications/history`

Retrieve notification history with optional filtering.

**Query Parameters:**

- `job_id` (optional): Filter by job UUID
- `limit` (default: 50, max: 500): Max notifications to return

**Response (200):**

```json
{
  "count": 5,
  "limit": 50,
  "job_id_filter": null,
  "notifications": [
    {
      "job_id": "550e8400...",
      "notification_type": "job_started",
      "recipient": "client@example.com",
      "subject": "🚀 Your job...",
      "timestamp": "2026-02-19T16:30:45...",
      "status": "sent",
      "error": null
    }
  ]
}
```

### `GET /api/notifications/config`

Get email backend configuration (secrets redacted).

**Response (200):**

```json
{
  "backend": "sendgrid",
  "configured": true,
  "from_email": "notifications@openclaw.agency",
  "from_name": "OpenClaw Agency",
  "sendgrid_api_key_present": true
}
```

## License

Part of OpenClaw Agency — proprietary system.
