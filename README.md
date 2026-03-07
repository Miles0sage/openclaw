# OpenClaw

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

**Multi-agent AI job pipeline with 12 agent souls, 75+ MCP tools, and 4-tier LLM fallback.**

OpenClaw is a production-grade autonomous agent framework built on FastAPI, Cloudflare Workers, and Supabase. It decomposes complex tasks, routes them to specialist agents, executes with 75+ integrated tools, and verifies results before reporting.

---

## What It Does

**Workflow:**
```
Task → FastAPI Gateway → Overseer (PM) → Specialist Agents → Verification → Response
```

1. **Receive**: API, Telegram, Slack, or direct Python calls
2. **Decompose**: Overseer analyzes task complexity and scope
3. **Route**: Send to the optimal specialist (CodeGen Pro, Pentest AI, Researcher, etc.)
4. **Execute**: Agent uses 75+ MCP tools (code, database, browser, security, trading, sports, etc.)
5. **Verify**: Results validated, costs tracked, learning saved
6. **Respond**: Final output delivered with execution cost and duration

---

## Architecture

**Multi-Agent System (v4.2)**

| Agent | Model | Cost | Use Case |
|-------|-------|------|----------|
| **Overseer** | Claude Opus 4.6 | $15/1M | Task decomposition, routing, verification |
| **CodeGen Pro** | Kimi 2.5 | $0.14/1M | Frontend, backend, API, testing, bug fixes |
| **CodeGen Elite** | MiniMax M2.5 | $0.30/1M | Complex refactors, system redesign, algorithms |
| **Pentest AI** | Kimi Reasoner | $0.27/1M | Security audits, RLS, vulnerability assessment |
| **SupabaseConnector** | Claude Opus 4.6 | $15/1M | Database queries, schema, migrations |
| **BettingBot** | Kimi 2.5 | $0.14/1M | Sports odds, arbitrage, +EV picks, Kelly sizing |
| **Code Reviewer** | Kimi 2.5 | $0.14/1M | PR reviews, code audits, tech debt assessment |
| **Architecture Designer** | MiniMax M2.5 | $0.30/1M | System design, API contracts, scalability |
| **Test Generator** | Kimi 2.5 | $0.14/1M | Unit/integration/E2E tests, coverage analysis |
| **Debugger** | Claude Opus 4.6 | $15/1M | Race conditions, memory leaks, root cause analysis |
| **Researcher** | Kimi 2.5 | $0.14/1M | Market research, tech deep dives, lit reviews |
| **Content Creator** | Kimi 2.5 | $0.14/1M | Blog posts, documentation, proposals, emails |
| **Financial Analyst** | Kimi 2.5 | $0.14/1M | Revenue tracking, cost analysis, pricing research |

**Infrastructure**

- **Gateway**: FastAPI on VPS 152.53.55.207:18789 (systemd service)
- **Workers**: Cloudflare Workers (PA + AI CEO agents)
- **Data**: Supabase (separate databases per agent)
- **MCP Servers**: 9 integrations (shared tools across agents)
- **LLM Fallback**: 4-tier routing
  1. Bailian (Alibaba DashScope) — $0.00003/call
  2. Kimi/DeepSeek — $0.14/1M tokens
  3. MiniMax — $0.30/1M tokens
  4. Claude Opus — $15/1M tokens (quality fallback)

**Tools & Integrations (75+)**

Code: file_read, file_edit, file_write, shell_execute
Database: query_data_sources, update_data_source, run_sql
Browser: navigate, screenshot, click, type, evaluate JavaScript
Security: vulnerability_scan, RLS_audit, pentest_runner
Sports: sportsbook_odds, sportsbook_arb, xgboost_predict, kelly_sizing
Research: perplexity_sonar, deep_research, web_scrape, web_fetch
Trading: polymarket_prices, kalshi_trade, arb_scanner
Finance: revenue_tracking, cost_analysis, invoice_generator
Content: blog_writer, social_posts, proposal_generator
Monitoring: cost_tracker, job_viewer, mission_control_dashboard

---

## Quick Start

**Requirements:**
- Python ≥3.11
- Supabase account + API key
- At least one LLM API key (Claude, Bailian, or other)
- (Optional) Telegram/Slack tokens for integrations

**Installation:**

```bash
git clone https://github.com/cybershield-agency/openclaw
cd openclaw
pip install -e '.[dev]'

# Copy and configure environment
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY, etc.

# Start gateway (systemd handles auto-restart)
systemctl start openclaw-gateway
systemctl status openclaw-gateway

# Verify gateway is running
curl http://localhost:18789/health
```

**Send a Task (Python):**

```python
import httpx

task = {
    "description": "Analyze DBNull.Value handling in C# DataFrame operations",
    "priority": "high",
    "tags": ["csharp", "dataframe"]
}

response = httpx.post(
    "http://localhost:18789/job",
    json=task,
    headers={"Authorization": "Bearer YOUR_API_KEY"}
)

print(response.json())  # Job ID, status, result when complete
```

**Telegram Integration:**

```bash
openclaw telegram --token YOUR_BOT_TOKEN --webhook-url https://gateway.overseerclaw.uk/telegram
```

---

## Testing

```bash
# Run all tests
pytest

# Run specific test category
pytest tests/ -k "agent_routing"

# With coverage
pytest --cov=openclaw tests/

# 199 tests covering:
# - Agent routing and specialization
# - Error recovery (3-tier cascade)
# - Cost gating (per-agent limits)
# - LLM fallback chain
# - Tool execution and mocking
# - Job pipeline phases (decompose → execute → verify)
# - Reflexion (error → diagnosis → retry)
# - Data validation and RLS policies
```

---

## Development

**Add a New Tool:**

1. Implement tool in `tools/` folder
2. Register in agent's `allowed_tools` (CLAUDE.md)
3. Add MCP server integration if external
4. Write tests in `tests/test_tools/`
5. Deploy via systemd: `systemctl restart openclaw-gateway`

**Add a New Agent Soul:**

1. Define identity and constraints in `CLAUDE.md`
2. Register routing rules in `agent_router.py`
3. Configure allowed tools per agent
4. Test with `test_agent_routing.py`
5. Restart gateway

**Environment Variables:**

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ0eXA...

# Optional (fallback chains)
BAILIAN_API_KEY=sk-sp-...
KIMI_API_KEY=xxx
MINIMAX_API_KEY=xxx
GROK_API_KEY=xxx

# Integrations
TELEGRAM_BOT_TOKEN=xxx
SLACK_BOT_TOKEN=xxx
STRIPE_API_KEY=sk_live_...
```

---

## Performance & Costs

**Typical Task Costs:**

- Simple code fix → CodeGen Pro → $0.02
- Complex refactor → CodeGen Elite → $0.15
- Security audit → Pentest AI → $0.10
- Database query → SupabaseConnector → $0.30
- Market research → Researcher → $0.05

**Fallback Strategy:**

Tasks automatically cascade down cost tiers on failure:
1. Try cheap model (Bailian)
2. If latency timeout → Kimi 2.5
3. If reasoning fails → MiniMax
4. If still failing → Opus (quality guarantee)

**Recent Results (v4.2):**

- **Success Rate**: 90%+ across all job types
- **Avg Job Duration**: 12s (short tasks) to 3min (complex refactors)
- **Monthly Cost**: ~$40 (including fallback chain + testing)
- **Test Coverage**: 170+ tests (0.23s full suite)

---

## Deployments

**Running Instances:**

- **Gateway**: gateway.overseerclaw.uk (FastAPI)
- **AI CEO Worker**: assistant.overseerclaw.uk (DeepSeek V3)
- **Personal Assistant Worker**: pa.overseerclaw.uk (DeepSeek V3)
- **Dashboard**: dashboard.overseerclaw.uk (Job viewer + cost analytics)

**Systemd Service:**

```bash
# View logs
journalctl -u openclaw-gateway -f

# Restart (auto-loads .env)
systemctl restart openclaw-gateway

# Check status
systemctl status openclaw-gateway
```

---

## Project Status

| Aspect | Status |
|--------|--------|
| Core Pipeline | ✅ Production (v4.2) |
| 12 Agent Souls | ✅ Deployed |
| 75+ MCP Tools | ✅ Integrated |
| Cost Gating | ✅ Per-agent limits enforced |
| Error Recovery | ✅ 3-tier fallback + reflexion |
| Testing | ✅ 199 tests (0.23s) |
| Documentation | ✅ CLAUDE.md, ARCHITECTURE.md |
| Stripe Integration | ⏳ In progress (commercialization) |
| Self-Improvement | ⏳ Reflexion + learning logs |

---

## License

[MIT](LICENSE) — Built and maintained by Miles (Cybershield Agency)

---

## Resources

- [CLAUDE.md](CLAUDE.md) — Agent identities, routing rules, protocols
- [ARCHITECTURE.md](ARCHITECTURE.md) — System design, pipeline phases, tool ecosystem
- [Error Patterns](https://github.com/cybershield-agency/openclaw/wiki/Error-Patterns) — Hard-won debugging lessons
- [v4.2 Roadmap](https://github.com/cybershield-agency/openclaw/wiki/v4.2-Roadmap) — Current features + next steps

---

**OpenClaw v4.2** • Last updated: 2026-03-07
