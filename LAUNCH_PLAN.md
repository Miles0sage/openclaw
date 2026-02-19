# OpenClaw AI Agency — Launch Plan

## STATUS: Ready to execute. All research done. No more building from scratch.

---

## The Problem We Solved

We spent a week building ~8,000 LOC of Python that duplicates what OpenClaw ships natively.
OpenClaw already has 53 installed skills, 30 extensions, 5,700+ ClawHub community skills.

## Architecture Decision: HYBRID

```
Native OpenClaw TS Gateway (port 18789)     ← runs 70+ skills, channels, cron, memory
  └── Python Sidecar (port 18790)           ← runs YOUR unique agency features only
       ├── intake_routes.py                 ← client portal + job submission
       ├── autonomous_runner.py             ← 5-phase execution pipeline
       ├── output_verifier.py               ← 6 quality gates
       ├── review_cycle.py                  ← agent-to-agent reviews
       ├── client_auth.py                   ← billing/plans/Stripe
       └── client_portal.html               ← client-facing UI
```

---

## Phase 1: Enable What Already Exists (30 min)

### 1A. Install ClawHub skills (5 min)

```bash
npm i -g clawhub
clawhub install stripe
clawhub install pr-reviewer
clawhub install vercel
clawhub install mailchannels
clawhub install clawdo
```

### 1B. Enable bundled extensions in config.json (5 min)

Add to `/root/openclaw/config.json` or `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "lobster": { "enabled": true },
      "llm-task": { "enabled": true },
      "memory-lancedb": { "enabled": true }
    }
  }
}
```

### 1C. Verify skills load (5 min)

```bash
openclaw skills list
openclaw gateway run --port 18789
```

### 1D. Wire agency routes to real Upstash (15 min)

Files to edit:

- `src/gateway/agency-routes/trigger.ts` — replace `// TODO` with real Upstash `lpush`
- `src/gateway/agency-routes/status.ts` — replace hardcoded data with `lrange`
- `src/gateway/agency-routes/costs.ts` — call `initCostTracker()` with Upstash client
- `src/gateway/agency-routes/config.ts` — add filesystem write

Upstash credentials already configured:

- URL: check `UPSTASH_REDIS_REST_URL` env var
- Token: check `UPSTASH_REDIS_REST_TOKEN` env var

---

## Phase 2: Python Sidecar (20 min)

### 2A. Extract unique modules to standalone FastAPI app

Create `/root/openclaw/agency_sidecar.py`:

```python
# Runs on port 18790, proxies to TS gateway on 18789
# Only serves: /api/intake, /api/jobs, /api/billing, /client-portal
# /api/runner, /api/verify, /api/reviews
```

### 2B. Keep these Python files (UNIQUE value):

- `intake_routes.py` — client portal + job API
- `autonomous_runner.py` — 5-phase pipeline (Research→Plan→Execute→Verify→Deliver)
- `output_verifier.py` — 6 quality gates (syntax, security, tests, lint, diff, cost)
- `review_cycle.py` — agent-to-agent collaboration
- `client_auth.py` — billing plans + Stripe stubs
- `client_portal.html` — client-facing intake UI
- `email_notifications.py` — lifecycle emails (or replace with himalaya skill)

### 2C. DELETE these Python files (replaced by native TS):

- `cost_tracker.py` → use `agency-cost-tracker.ts`
- `cost_gates.py` → use native cost tracking
- `quota_manager.py` → use native rate limiting
- `cron_scheduler.py` → use native `src/cron/`
- `heartbeat_monitor.py` → use native `src/monitoring/`
- `memory_manager.py` → use `memory-lancedb` extension
- `metrics.py`, `metrics_collector.py` → use native monitoring
- `error_recovery.py` → use native `src/infra/backoff.ts`

---

## Phase 3: Persistent Storage (15 min)

Move from `/tmp/` (lost on reboot) to persistent dirs:

```bash
mkdir -p /root/openclaw/data/jobs
mkdir -p /root/openclaw/data/clients
mkdir -p /root/openclaw/data/sessions
mkdir -p /root/openclaw/data/costs
```

Update file paths in:

- `intake_routes.py`: `/tmp/openclaw_intake.json` → `/root/openclaw/data/jobs/intake.json`
- `job_manager.py`: `/tmp/openclaw_jobs/` → `/root/openclaw/data/jobs/`
- `client_auth.py`: `/tmp/openclaw_clients.json` → `/root/openclaw/data/clients/clients.json`
- `autonomous_runner.py`: `/tmp/openclaw_job_runs/` → `/root/openclaw/data/jobs/runs/`

---

## Phase 4: Launch Prep (1 hour)

### 4A. Landing page for overseerclaw.uk (30 min)

- What the agency does
- Pricing (Free/Starter/Pro/Enterprise)
- "Submit a Job" button → client portal
- Built with Tailwind, deployed to Cloudflare Pages

### 4B. Stripe live keys (10 min)

- Create Stripe account if not done
- Add `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY` env vars
- Update `client_auth.py` checkout endpoint with real Stripe

### 4C. Terms of Service (10 min)

- AI-generated code disclaimer
- Liability limits
- Refund policy
- Data handling

### 4D. Domain routing (10 min)

```
overseerclaw.uk          → Landing page (Cloudflare Pages)
dashboard.overseerclaw.uk → Mission Control + Client Portal
gateway.overseerclaw.uk   → API gateway (TS + Python sidecar)
```

---

## Phase 5: Test & Go Live (30 min)

### 5A. End-to-end test

1. Submit job via Telegram: "create task: build a hello world Next.js app"
2. Verify runner picks it up
3. Watch 5 phases execute with Haiku tool_use
4. Verify GitHub PR created
5. Verify Slack notification posted
6. Verify email sent to contact_email
7. Check client portal shows progress

### 5B. Smoke test billing

1. Create free tier client
2. Submit 5 jobs (should work)
3. Submit 6th (should reject — free limit)
4. Upgrade to starter, submit again (should work)

### 5C. Push & announce

```bash
git add -A && git commit -m "feat: Launch OpenClaw AI Agency - hybrid TS+Python architecture"
git push origin main
```

---

## Key Files Reference

| File                     | Purpose                       | Keep/Delete                       |
| ------------------------ | ----------------------------- | --------------------------------- |
| `gateway.py`             | Python FastAPI (current main) | REFACTOR → sidecar                |
| `intake_routes.py`       | Client job submission         | KEEP (unique)                     |
| `autonomous_runner.py`   | 5-phase execution             | KEEP (unique)                     |
| `output_verifier.py`     | Quality gates                 | KEEP (unique)                     |
| `review_cycle.py`        | Agent reviews                 | KEEP (unique)                     |
| `client_auth.py`         | Billing/plans                 | KEEP (unique)                     |
| `client_portal.html`     | Client UI                     | KEEP (unique)                     |
| `email_notifications.py` | Email alerts                  | KEEP or replace with himalaya     |
| `github_integration.py`  | PR delivery                   | KEEP or replace with github skill |
| `cost_tracker.py`        | Cost tracking                 | DELETE → native TS                |
| `cron_scheduler.py`      | Scheduling                    | DELETE → native TS                |
| `heartbeat_monitor.py`   | Health checks                 | DELETE → native TS                |
| `memory_manager.py`      | Memory                        | DELETE → memory-lancedb           |
| `error_recovery.py`      | Error handling                | DELETE → native TS                |

## Credentials & Config

- **Gateway auth**: `f981afbc4a94f50a87cd0184cf560ec646e8f8a65a7234f603b980e43775f1a3`
- **MiniMax API**: `sk-cp-5cmx4OmXEq3yfUV6TjDUcIac--MLy-zKxuCTgwscz0FCqzOwGLnlGrQ4cIevAF1DRqRupwokrirf3_jEdZqqS9EMKMuivy3JfmVjqZUFg3BDGa4_KsEqii0`
- **VPS**: 152.53.55.207:18789
- **Tunnel**: Cloudflare `31cb849a-60c9-4631-846f-fe1aa12bce69`
- **Domains**: gateway.overseerclaw.uk, dashboard.overseerclaw.uk

## Timeline

| Phase     | Time           | What                                |
| --------- | -------------- | ----------------------------------- |
| 1         | 30 min         | Enable existing skills + extensions |
| 2         | 20 min         | Extract Python sidecar              |
| 3         | 15 min         | Persistent storage                  |
| 4         | 1 hour         | Landing page, Stripe, ToS, domains  |
| 5         | 30 min         | Test + go live                      |
| **Total** | **~2.5 hours** | **Full launch**                     |

---

## IMPORTANT: Don't Build From Scratch Anymore

Before writing ANY new code, check:

1. `ls /root/openclaw/skills/` — 53 installed skills
2. `ls /root/openclaw/extensions/` — 30 bundled extensions
3. `clawhub search <keyword>` — 5,700+ community skills
4. Only build custom if it truly doesn't exist anywhere
