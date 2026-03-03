# OpenClaw Tools Reference — Quick Index

67 tools available via MCP. Organized by category. Use `--mcp-config /root/.claude/mcp.json` to enable.

## Code & Development (12 tools)

- `git_operations` — Clone, branch, commit, push, pull, diff, log, checkout
- `file_read` — Read files (max 500 lines, supports offset)
- `file_write` — Write or append to files
- `file_edit` — Surgical find-replace in existing files
- `glob_files` — Find files by pattern (e.g., `**/*.py`)
- `grep_search` — Regex search with context (rg-based)
- `shell_execute` — Run any shell command (git, npm, python, docker, etc.)
- `install_package` — npm/pip/apt/binary installs with auto-detection
- `vercel_deploy` — Deploy projects to Vercel (list, status, logs, env-set)
- `github_repo_info` — Get repo status, issues, PRs, recent commits
- `github_create_issue` — File bugs, features, tasks
- `web_scrape` — Extract structured data from URLs (text, links, headings, tables, code)

## Data & Supabase (1 tool via native MCP)

- `supabase` — Query databases, RLS policies, migrations, real-time subscriptions (via supabase-mcp-server)

## Research & Information (5 tools)

- `web_search` — Search the web, returns markdown links
- `web_fetch` — Fetch URL content, extract text/links/all
- `perplexity_research` — Deep research via Perplexity Sonar (web/academic/news modes)
- `deep_research` — Multi-step autonomous research with sub-question decomposition
- `research_task` — Quick topic research (quick/medium/deep depth)

## Job Management (4 tools)

- `create_job` — Create tasks (P0–P3, projects: barber-crm, openclaw, delhi-palace, prestress-calc, concrete-canoe)
- `list_jobs` — List pending, analyzing, pr_ready, approved, done, or all jobs
- `approve_job` — Auto-approve pr_ready jobs
- `kill_job` — Cancel running or pending jobs

## Workspace & Memory (3 tools)

- `save_memory` — Save facts to long-term memory with importance (1–10) and tags
- `search_memory` — Query saved memories (returns top 5 by default)
- `blackboard_read` / `blackboard_write` — Shared state (project-scoped, TTL support)

## Cost & Analytics (3 tools)

- `get_cost_summary` — Current API spend and budget status
- `get_events` — Recent system events (job.created, job.completed, job.failed, etc.)
- `get_reflections` — Learn from past job outcomes (stats, list, search by task)

## Agent Orchestration (1 tool)

- `tmux_agents` — Spawn parallel Claude Code agents in isolated tmux panes with optional worktrees

## Communication (2 tools)

- `send_slack_message` — Post to Slack channel (default: report channel C0AFE4QHKH7)
- `create_event` — Emit custom events to event engine (job.created, deploy.complete, etc.)

## Planning & Admin (2 tools)

- `plan_my_day` — Fetch calendar events, pending jobs, agency status, emails
- `manage_reactions` — Auto-reaction rules (list, add, update, delete, triggers)

## Polymarket (4 tools)

- `prediction_market` — Search markets, get details, list events
- `polymarket_prices` — Real-time prices (snapshot, spread, midpoint, book, last_trade, history)
- `polymarket_monitor` — Mispricing detector, open interest, volume, holders, leaderboard
- `polymarket_trade` — Buy/sell/market_buy/market_sell, cancel, cancel_all, list_orders (dry-run default)
- `polymarket_portfolio` — View positions, closed, trades, value, activity, profile

## Kalshi (3 tools)

- `kalshi_markets` — Search/get markets, orderbook, trades, candlesticks, events
- `kalshi_trade` — Buy/sell/market operations, cancel, list_orders (dry-run default)
- `kalshi_portfolio` — Balance, positions, fills, settlements, summary

## Arbitrage & Trading (3 tools)

- `arb_scanner` — Cross-platform arb detector (scan, compare, bonds >90%, mispricing)
- `trading_strategies` — Auto-scanners (bonds, mispricing, whale_alerts, trending, expiring, summary)
- `trading_safety` — Config, kill switch, position limits, trade audit log

## Sports & Betting (4 tools)

- `sportsbook_odds` — Live odds from 200+ bookmakers (sports, odds, event, compare, best_odds)
- `sportsbook_arb` — Arb + EV scanner (scan, calculate, ev_scan)
- `sports_predict` — XGBoost NBA predictions (predict, evaluate, train, features, compare)
- `sports_betting` — Full pipeline (recommend, bankroll, dashboard)
- `prediction_tracker` — Track predictions vs actual results (log, check, record, yesterday)

## Computation (5 tools)

- `compute_sort` — Sort numbers/strings, O(n log n) (auto/mergesort/heapsort/quicksort/timsort)
- `compute_stats` — Precise statistics (mean, median, mode, std dev, percentiles, etc.)
- `compute_math` — Math expressions (arithmetic, trig, factorial, gcd, etc.)
- `compute_search` — Search/filter (binary, linear, filter, regex)
- `compute_matrix` — Linear algebra (multiply, transpose, determinant, inverse, eigenvalues, solve)

## Cryptography (2 tools)

- `compute_hash` — SHA-256/512, MD5, BLAKE2b, SHA-1
- `compute_prime` — Factorize, is_prime, generate primes, nth_prime

## Utilities (5 tools)

- `compute_convert` — Units, bases, temperatures, timestamps (binary/hex/celsius/fahrenheit/etc.)
- `env_manage` — Read/set/list env vars, load/save .env files
- `process_manage` — List/kill processes, check ports, top resource users
- `security_scan` — OXO scan (quick/full/web) against IP/domain/URL

## Business & Outreach (3 tools)

- `find_leads` — Search local businesses (Google Maps) by type and location
- `sales_call` — AI outbound sales calls via Vapi + ElevenLabs
- `generate_proposal` — Create branded HTML proposals (restaurant/barbershop/dental/auto/realestate/other)

## News & Social (2 tools)

- `read_ai_news` — RSS feeds from OpenAI, DeepMind, Hugging Face, ArXiv, etc.
- `read_tweets` — Recent posts from AI community (Reddit, Bluesky, Twitter, RSSHub)

---

## Usage Tips

**To use all tools**: Add `--mcp-config /root/.claude/mcp.json` to your Claude Code command.

**Cost order** (cheapest to most expensive):

1. Computation tools (free, local)
2. Bash commands (free, local)
3. File operations (free, local)
4. Kimi 2.5 / Deepseek (cheapest LLM)
5. Perplexity Research ($1/M Sonar, $3/$15 Sonar-Pro)
6. Claude Opus 4.6 (most expensive)

**Before calling**: Always think about:

1. Is this the right tool for the job?
2. What data do I already have?
3. Could I solve this faster with a cheaper tool?
4. Am I making multiple calls when one would suffice?

**Error handling**: Most tools return structured data. Check for errors in response before proceeding.

---

Last updated: 2026-03-03
