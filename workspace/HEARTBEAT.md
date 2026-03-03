# HEARTBEAT — Periodic Health Checks

Run this checklist at the start of each shift (or when explicitly requested).
Each item should take <1 second. Skip if you don't have the tools or permissions.

## Gateway & Infrastructure (60 seconds)

- [ ] **Gateway service alive**: `systemctl status openclaw-gateway` → active (running)
- [ ] **Gateway listening**: `curl -s http://localhost:8789/health` → {"status": "ok"}
- [ ] **Recent gateway errors**: `journalctl -u openclaw-gateway --lines=20` → no CRITICAL or ERROR
- [ ] **Disk space**: `df -h /root` → more than 10% free
- [ ] **Memory usage**: `free -h` → at least 1GB available
- [ ] **VPS connectivity**: `curl -s https://gateway.overseerclaw.uk/health` → {"status": "ok"}

## Supabase & Data (30 seconds)

- [ ] **Supabase connection**: Can I reach supabase_client? Test with small query
- [ ] **Cost budget**: `get_cost_summary` → current spend < $150/mo ($200 max plan)
- [ ] **Recent errors**: Check event log for data.\* errors in past hour
- [ ] **RLS policies**: No data leakage incidents reported

## Job Queue & Automation (30 seconds)

- [ ] **Pending jobs**: `list_jobs --status pending` → queue not stuck
- [ ] **Failed jobs**: `list_jobs --status done` → check last 3 for errors
- [ ] **Agent watchdog**: No agent processes stuck (>30 min runtime)
- [ ] **Tmux panes**: `tmux list-panes -a` → no orphaned agents

## SSL & Domain Certificates (15 seconds)

- [ ] **gateway.overseerclaw.uk**: SSL valid for >7 days
- [ ] **dashboard.overseerclaw.uk**: SSL valid for >7 days
- [ ] **assistant.overseerclaw.uk**: SSL valid for >7 days

## Integrations (30 seconds)

- [ ] **GitHub token**: Still valid? Check last successful git_operations call
- [ ] **Supabase API key**: Env var set? `env_manage --action get --key SUPABASE_SERVICE_ROLE_KEY`
- [ ] **Anthropic API key**: Env var set? (used by PA worker)
- [ ] **Telegram token**: Recent CoderClaw messages processed?

## Cost & Budget (15 seconds)

- [ ] **API spend**: `get_cost_summary` → trending OK?
- [ ] **Top cost drivers**: Which tools cost most this month?
- [ ] **Budget alerts**: Any cost alerts in past 24h?

## Recent Activity (30 seconds)

- [ ] **Last successful deployment**: When? Which project?
- [ ] **Last failed job**: What went wrong? Is it fixed?
- [ ] **Last git commit**: When? What was it?
- [ ] **Recent alerts**: Any security, cost, or error alerts?

---

## If Anything Fails

| Issue                  | Quick Fix                                            | Escalate If                 |
| ---------------------- | ---------------------------------------------------- | --------------------------- |
| Gateway not responding | `systemctl restart openclaw-gateway`                 | Still down after 30s        |
| Disk full              | Delete old logs: `rm /root/openclaw/data/logs/*.old` | <2GB free after cleanup     |
| Supabase unreachable   | Check `/root/openclaw/.env` for credentials          | Down for >10 min            |
| Job queue stuck        | Kill oldest: `kill_job [job_id]`                     | Queue still full after kill |
| SSL cert expiring      | Run `certbot renew` on VPS                           | Already expired             |

---

## Heartbeat Frequency

- **Automatic**: Run at start of each session (before handling user requests)
- **On-demand**: User can request anytime via `heartbeat` or `/health`
- **Scheduled**: (Future) Every 6 hours if in autonomous mode

---

Last updated: 2026-03-03
