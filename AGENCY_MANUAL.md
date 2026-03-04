# OpenClaw AI Agency — Operations Manual

> This document is the complete reference for the OpenClaw AI agency. Provide it as system context to any AI agent (Grok, Claude, Gemini, etc.) that needs to operate within the agency.

---

## 1. What Is OpenClaw?

OpenClaw is an autonomous AI agency that builds, deploys, and maintains software for clients. It runs on a VPS (152.53.55.207) with a FastAPI gateway, a multi-agent job execution pipeline, and 78 MCP tools. The agency serves multiple projects (Barber CRM, Delhi Palace restaurant, PrestressCalc engineering tool, etc.) and handles everything from code generation to security audits to sports betting analytics.

**Owner:** Miles (NAU civil engineering student, works 5pm-10pm Tue-Sun, Monday OFF)
**Gateway:** `gateway.overseerclaw.uk` (port 18789, systemd service `openclaw-gateway`)
**Dashboard:** `dashboard.overseerclaw.uk`
**Version:** v4.2 (March 2026)

---

## 2. Agent Roster

The agency has 9 specialized agents. Each has a specific model, cost profile, and domain expertise. Route tasks to the cheapest agent that won't compromise quality.

| Agent                     | Model               | Cost (in/out per 1M) | Domain                                                                           |
| ------------------------- | ------------------- | -------------------- | -------------------------------------------------------------------------------- |
| **Overseer** (PM)         | Claude Opus 4.6     | $15/$75              | Planning, coordination, decomposition, budget                                    |
| **CodeGen Pro**           | Kimi 2.5 (Deepseek) | $0.14/$0.28          | Routine code: buttons, endpoints, CSS, bug fixes                                 |
| **CodeGen Elite**         | MiniMax M2.5        | $0.30/$1.20          | Complex refactors, multi-file, architecture impl (80.2% SWE-Bench, 205K context) |
| **Pentest AI**            | Kimi Reasoner       | $0.27/$0.68          | Security audits, OWASP, RLS, threat modeling (extended thinking)                 |
| **SupabaseConnector**     | Claude Opus 4.6     | $15/$75              | Database queries, schema, migrations, data accuracy                              |
| **BettingBot**            | Kimi 2.5            | $0.14/$0.28          | Sports odds, arb scanning, XGBoost predictions, Kelly sizing                     |
| **Code Reviewer**         | Kimi 2.5            | $0.14/$0.28          | PR reviews, code audits, tech debt, pattern matching                             |
| **Architecture Designer** | MiniMax M2.5        | $0.30/$1.20          | System design, API contracts, scalability (205K context)                         |
| **Test Generator**        | Kimi 2.5            | $0.14/$0.28          | Unit/integration/E2E tests, edge cases, coverage gaps                            |
| **Debugger**              | Claude Opus 4.6     | $15/$75              | Race conditions, memory leaks, heisenbugs, deep root cause analysis              |

### Routing Rules

| Signal                                            | Route To              | Why                                  |
| ------------------------------------------------- | --------------------- | ------------------------------------ |
| Simple code (fix, add, build, CSS)                | CodeGen Pro           | Fast, cheap, reliable                |
| Complex code (refactor, architecture, multi-file) | CodeGen Elite         | Deep reasoning, 205K context         |
| Security (audit, vulnerability, pentest, RLS)     | Pentest AI            | Extended thinking catches subtleties |
| Data (query, fetch, schema, migration)            | SupabaseConnector     | Accuracy is non-negotiable           |
| Sports, odds, betting, NBA, EV, arb               | BettingBot            | Probability-first, disciplined       |
| Code review (PR, audit, tech debt)                | Code Reviewer         | Cheap, thorough, actionable          |
| System design (architecture, scalability)         | Architecture Designer | Holds entire systems in context      |
| Testing (tests, coverage, QA)                     | Test Generator        | Edge-case-focused                    |
| Deep bugs (race condition, memory leak)           | Debugger              | Opus reasoning for state analysis    |
| Planning, decomposition, ambiguous                | Overseer              | Judgment calls stay with the PM      |

**Cost rule:** Route to the cheapest agent that won't compromise quality. Escalate when in doubt.

---

## 3. Job Execution Pipeline

Every job goes through a 5-phase pipeline:

```
RESEARCH → PLAN → EXECUTE → CODE_REVIEW → VERIFY → DELIVER
```

### Phase Details

1. **RESEARCH** — Read task, load project context (CLAUDE.md, component manifest), inject past reflections (lessons learned), search codebase. Output: research summary with files, patterns, dependencies, risks.

2. **PLAN** — Create step-by-step ExecutionPlan (max 10 steps). Each step has description, tool hints, optional agent delegation. Output: ordered plan.

3. **EXECUTE** — For each plan step: agent uses tools (file_edit, shell_execute, git_operations, etc.). Loop detection breaks after 3 identical tool calls. Tool nudge at 10 iterations. Max 15 iterations per step. Output: execution results.

4. **CODE_REVIEW** (P0/P1 only) — Triple review: Code Reviewer (logic, patterns) + Static Analysis + Pentest AI (security). Blocks on "critical" or "major" severity. Output: review feedback or approval.

5. **VERIFY** — Verifier checks functionality, security, completeness against original requirements. Runs tests if applicable. Output: pass/fail.

6. **DELIVER** — Commit changes, push to GitHub, post summary to Slack, save reflection for future jobs. Mark job "done".

### Priority Levels

| Priority | Cost Cap  | Use Case                   |
| -------- | --------- | -------------------------- |
| P0       | Unlimited | Critical production issues |
| P1       | $5        | High-priority features     |
| P2       | $2        | Medium tasks (default)     |
| P3       | $0.50     | Low-priority, nice-to-have |

### Execution Backends (Fallback Chain)

1. **OpenCode** (Gemini 2.5 Flash) — ~$0.001/job, fastest and cheapest
2. **GitHub Actions** (Claude via Max Plan) — $0.00/job, uses `claude-code-action` on issue creation
3. **SDK Haiku** — ~$0.02/job, for P1-P3 when OpenCode fails
4. **SDK Sonnet** — ~$0.50/job, P0 only when Haiku fails

---

## 4. Projects

### OpenClaw (this agency)

- **Path:** `/root/openclaw/`
- **Repo:** `Miles0sage/openclaw`
- **Gateway:** systemd service, port 18789
- **Stack:** Python 3.13, FastAPI, Supabase, Cloudflare Workers

### Barber CRM (Surgeon Cuts)

- **Path:** `/root/Barber-CRM/`
- **Repo:** `Miles0sage/Barber-CRM`
- **Live:** https://nextjs-app-sandy-eight.vercel.app
- **Stack:** Next.js, Supabase (djdilkhedpnlercxggby), Vercel
- **AI Receptionist:** Vapi + ElevenLabs, phone +1 (928) 325-9472
- **Location:** 1000 E Butler Ave Suite #115, Flagstaff AZ 86001

### Delhi Palace (Restaurant)

- **Path:** `/root/Delhi-Palace/`
- **Repo:** `Miles0sage/Delhi-Palce-` (branch: master)
- **Stack:** Next.js, Supabase (banxtacevgopeczuzycz)
- **Features:** Online ordering, KDS (kitchen display), menu management

### PrestressCalc

- **Path:** `/root/Mathcad-Scripts/`
- **Status:** 1144 tests, Phase 13 complete (dual-code ACI+AASHTO)
- **Stack:** Python, 20+ engineering modules, 7 section types

### Concrete Canoe

- **Path:** `/root/concrete-canoe-project2026/`
- **Status:** Build phase

---

## 5. Gateway Endpoints (Key Routes)

### Job Management

- `POST /api/job/create` — Create job `{project, task, priority}`
- `GET /api/jobs` — List jobs (filterable by status)
- `GET /api/job/{job_id}` — Job details
- `POST /api/job/{job_id}/approve` — Approve job
- `DELETE /api/runner/cancel/{job_id}` — Cancel job
- `POST /api/jobs/{job_id}/kill` — Force kill

### AI Chat

- `POST /api/chat` — Text completion with tool use (SSE streaming)
- `POST /api/vision` — Image analysis
- `WebSocket /ws` — Bidirectional chat

### Cost Management

- `GET /api/costs/summary` — Spend breakdown, budget status
- `GET /api/costs/text` — Human-readable report

### Research

- `POST /api/research/deep` — Multi-step Perplexity research
- `GET /api/ai-news` — AI news RSS feeds

### Trading & Sports

- `POST /api/polymarket/*` — Polymarket prices, monitor, portfolio, trade
- `POST /api/kalshi/*` — Kalshi markets, trade, portfolio
- `POST /api/arb/scan` — Cross-platform arbitrage
- `POST /api/sportsbook/*` — Live odds, arb/EV scanning
- `POST /api/sports/*` — XGBoost predictions, betting pipeline

### Business

- `GET /api/leads/find` — Find local businesses
- `POST /api/calls/make` — AI outbound calls
- `POST /api/proposals/generate` — Client proposals

### Memory

- `GET /api/memories` — List memories
- `POST /api/memory/add` — Save memory
- `GET /api/reminders/due` — Due reminders

### Communications

- `POST /sms/send` — SMS via Twilio
- `POST /slack/events` — Slack webhooks
- `POST /telegram/webhook` — Telegram bot

### Browser Automation

- `POST /api/pinch/navigate` — Open URL
- `GET /api/pinch/snapshot` — Page DOM
- `POST /api/pinch/action` — Click/type/submit
- `GET /api/pinch/screenshot` — Screenshot

### Health

- `GET /health` — Liveness check
- `GET /api/health` — Detailed health
- `GET /api/runner/status` — Runner state

---

## 6. MCP Tools (78 Total)

### GitHub & Git

- `github_repo_info` — Fetch issues, PRs, status, commits
- `github_create_issue` — Create issues
- `git_operations` — Clone, push, pull, branch, checkout, log, diff

### Web

- `web_search` — Google search
- `web_fetch` — Fetch URL content
- `web_scrape` — Extract structured data
- `research_task` — Multi-step research

### File I/O

- `file_read` — Read files
- `file_write` — Write/overwrite files
- `file_edit` — Find-replace operations
- `glob_files` — Find files by pattern
- `grep_search` — Regex content search

### Shell & System

- `shell_execute` — Run commands (allowlisted)
- `install_package` — npm/pip/apt
- `process_manage` — List/kill processes, check ports
- `env_manage` — Environment variables

### Compute

- `compute_sort` — O(n log n) sorting
- `compute_stats` — Statistics (mean, median, std dev, percentiles)
- `compute_math` — Precise arithmetic
- `compute_search` — Binary/linear/regex search
- `compute_matrix` — Matrix operations
- `compute_hash` — SHA-256/512, MD5, BLAKE2
- `compute_convert` — Unit conversions
- `compute_prime` — Prime factorization, generation

### Job Management

- `create_job` — Create task in queue
- `list_jobs` — List by status
- `approve_job` — Approve for execution
- `kill_job` — Cancel running job
- `agency_status` — Overview dashboard
- `get_cost_summary` — Budget status
- `create_proposal` — Auto-approval proposal

### Memory & Context

- `save_memory` — Store facts with tags
- `search_memory` — Semantic search
- `blackboard_read` / `blackboard_write` — Shared agent state
- `get_reflections` — Past learnings
- `get_events` — Event log
- `flush_memory_before_compaction` — Save before context trim

### Trading

- `prediction_market` — Polymarket data
- `polymarket_prices` — Real-time prices
- `polymarket_monitor` — Mispricing/whale alerts
- `polymarket_portfolio` — Positions
- `polymarket_trade` — Orders (dry-run default)
- `kalshi_markets` — Kalshi data
- `kalshi_trade` — Kalshi orders
- `kalshi_portfolio` — Kalshi positions
- `arb_scanner` — Cross-platform arbitrage
- `trading_strategies` — Bonds, trending, expiring
- `trading_safety` — Kill switch, limits, audit

### Sports

- `sportsbook_odds` — 200+ bookmakers
- `sportsbook_arb` — Arb + EV scanner
- `sports_predict` — XGBoost NBA predictions
- `sports_betting` — Full pipeline
- `prediction_tracker` — Grade predictions

### Research

- `perplexity_research` — Sonar API
- `deep_research` — Multi-step synthesis
- `read_ai_news` — RSS feeds
- `read_tweets` — AI community posts

### Business

- `find_leads` — Google Maps scraping
- `sales_call` — AI outbound calls (Vapi)
- `generate_proposal` — HTML proposals

### Communication

- `send_slack_message` — Slack
- `send_sms` — Twilio SMS
- `sms_history` — SMS log

### Browser

- `browser_navigate` — Open URL
- `browser_snapshot` — Accessibility tree
- `browser_action` — Click/type/submit
- `browser_text` — Extract text
- `browser_screenshot` — JPEG capture
- `browser_tabs` — Tab management
- `browser_evaluate` — Execute JS

### Other

- `tmux_agents` — Spawn parallel agents
- `manage_reactions` — Auto-reaction rules
- `plan_my_day` — Daily planner
- `security_scan` — OXO penetration testing
- `create_event` — Custom events
- `vercel_deploy` — Deploy to Vercel

---

## 7. Key Files

| File                   | Lines | Purpose                                           |
| ---------------------- | ----- | ------------------------------------------------- |
| `gateway.py`           | 8,443 | FastAPI gateway, 150+ endpoints                   |
| `autonomous_runner.py` | 3,874 | 5-phase job execution pipeline                    |
| `agent_tools.py`       | 4,378 | 78 MCP tool definitions                           |
| `config.json`          | 911   | Agent configs, routing, quotas                    |
| `CLAUDE.md`            | 193   | Agent souls, routing rules, coordination protocol |
| `job_manager.py`       | 200+  | Job CRUD, lifecycle management                    |
| `cost_tracker.py`      | 150+  | Cost logging, pricing tables                      |
| `provider_chain.py`    | —     | Fallback chain: OpenCode → Haiku → Sonnet         |
| `opencode_executor.py` | —     | OpenCode CLI wrapper (Gemini, cheapest)           |
| `github_job_bridge.py` | 134   | Route jobs through GitHub Actions ($0 cost)       |
| `reflexion.py`         | 200+  | Learn from past failures                          |
| `error_handler.py`     | 902   | Error classification, recovery                    |
| `output_verifier.py`   | 1,366 | Post-execution validation                         |
| `.opencode.json`       | 40    | OpenCode CLI config (MUST exist)                  |

---

## 8. Cost Model

### Model Pricing

| Model            | Input/1M | Output/1M | When to Use                      |
| ---------------- | -------- | --------- | -------------------------------- |
| Kimi 2.5         | $0.14    | $0.28     | Default for code, reviews, tests |
| Kimi Reasoner    | $0.27    | $0.68     | Security (extended thinking)     |
| MiniMax M2.5     | $0.30    | $1.20     | Complex code, architecture       |
| Gemini 2.5 Flash | $0.30    | $2.50     | OpenCode execution               |
| Claude Haiku 4.5 | $0.80    | $4.00     | SDK fallback (simple)            |
| Claude Sonnet 4  | $3.00    | $15.00    | SDK fallback (P0 only)           |
| Claude Opus 4.6  | $15.00   | $75.00    | Planning, data, debugging        |

### Budget Limits

- **Daily budget:** $50
- **Monthly budget:** $1,000
- **Per-job caps:** P0=unlimited, P1=$5, P2=$2, P3=$0.50
- **Auto-approve:** Jobs under $0.50
- **Human approval:** Jobs over $5.00

### Cost Optimization Rules

1. Always use the cheapest capable model
2. OpenCode (Gemini) is the primary executor (~$0.001/job)
3. GitHub Actions (Claude Max Plan) is $0.00/job
4. SDK Haiku only when OpenCode fails
5. SDK Sonnet only for P0 critical tasks
6. Never use Opus for routine code

---

## 9. Data Storage

```
/root/openclaw/data/
├── jobs/
│   ├── jobs.jsonl           # Job queue (JSONL, Supabase primary)
│   └── runs/{job_id}/       # Per-job logs, progress, workspace
├── costs/costs.jsonl        # Cost tracking
├── memories/memories.jsonl  # Persistent memories
├── reflections/             # Lessons learned
├── predictions/             # Sports prediction tracking
├── research/                # Deep research audit logs
├── trading/config.json      # Trading safety config
├── models/nba_xgboost.pkl   # XGBoost NBA model
└── proposals/               # Generated client proposals
```

**Supabase tables (primary):** jobs, costs, memories, reflections, checkpoints, blackboard, events

---

## 10. Environment Variables (Essential)

```bash
# AI Providers
ANTHROPIC_API_KEY=...         # Claude models
GEMINI_API_KEY=...            # Gemini 2.5/3
DEEPSEEK_API_KEY=...          # Kimi 2.5, Kimi Reasoner

# Gateway
PORT=18789
GATEWAY_AUTH_TOKEN=...        # JWT secret

# Supabase
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...

# Communications
SLACK_BOT_TOKEN=...
TELEGRAM_BOT_TOKEN=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...

# Voice
ELEVENLABS_API_KEY=...
VAPI_API_KEY=...

# Research
PERPLEXITY_API_KEY=...

# Trading (Optional)
KALSHI_API_KEY_ID=...
ODDS_API_KEY=...
```

---

## 11. Operational Rules

### For Any Agent Operating in This Agency:

1. **Make decisions.** Don't ask "do you want me to X?" — just do it if it's clearly needed.
2. **Run things in parallel** whenever possible. Miles expects speed.
3. **Always add new tools to ALL layers** (gateway + MCP + PA worker) — never leave gaps.
4. **Commit and push after significant work** — don't wait to be asked.
5. **Restart gateway via systemd** after gateway.py changes: `systemctl restart openclaw-gateway`
6. **Test what you build** — don't just write code and report.
7. **Route to the cheapest capable agent** — cost optimization is core.
8. **Never manually start gateway** — systemd handles it.
9. **`.opencode.json` MUST exist** in project root for OpenCode to work.
10. **Supabase is primary, JSONL is fallback** — always try Supabase first.

### Error Recovery

- **Transient errors** (rate limit, timeout, 503): Retry up to 3 times with exponential backoff
- **Permanent errors** (404, 401, SyntaxError): Skip or escalate, never retry
- **Stalled jobs:** Watchdog detects after heartbeat miss, auto-requeues with checkpoint

### Reflexion System

After every job (success or failure), the system saves a reflection:

- What worked
- What failed
- What to do differently next time

Before starting a new job, relevant reflections are injected as context. This prevents repeating the same mistakes.

---

## 12. Coordination Protocol

1. Overseer receives all inbound messages first
2. Overseer evaluates: handle directly or delegate
3. Specialist completes work, reports back
4. Overseer verifies output quality before responding
5. All actions logged to event engine
6. Cost tracked per agent, per project, per session

---

## 13. GitHub Actions Integration

Jobs that would normally cost API money can be routed through GitHub Actions for $0:

1. **Workflow:** `.github/workflows/openclaw-jobs.yml`
2. **Trigger:** Issue labeled `openclaw-job`
3. **Action:** `anthropics/claude-code-action@v1` with Max Plan OAuth token
4. **Result:** Posted as issue comment, polled by `github_job_bridge.py`
5. **Cost:** $0.00 per job (included in Max Plan subscription)

---

## 14. Quick Reference

```bash
# Check gateway health
curl https://gateway.overseerclaw.uk/health

# Create a job
curl -X POST https://gateway.overseerclaw.uk/api/job/create \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project": "openclaw", "task": "Fix bug in X", "priority": "P2"}'

# Check costs
curl https://gateway.overseerclaw.uk/api/costs/summary \
  -H "Authorization: Bearer $AUTH_TOKEN"

# Restart gateway
systemctl restart openclaw-gateway

# View logs
journalctl -u openclaw-gateway -f

# Run tests
cd /root/openclaw && python3 -m pytest
```

---

_Generated by OpenClaw v4.2 — Last updated: 2026-03-04_
