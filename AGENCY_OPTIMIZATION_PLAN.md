# OpenClaw Agency Optimization Plan

**Date**: 2026-03-03 | **Baseline**: v3.7 | **Success Rate**: 27% → Target 70%+

---

## Phase 1: Quick Wins (Today)

### 1.1 Switch tool execution from Haiku to Sonnet

- **File**: `autonomous_runner.py:533`
- Haiku fails on complex execute phases. Sonnet costs 3x more but succeeds 5x more.
- Keep Haiku for P3 (low priority) jobs only.

### 1.2 Reduce MAX_TOOL_ITERATIONS 25 → 15

- **File**: `autonomous_runner.py:62`
- Failed jobs average 24 iterations (spinning). Cut to 15, nudge at 10.

### 1.3 CoderClaw session fix

- Use deterministic `--session-id` per chat_id so sessions always resume
- Add `--mcp-config` so CoderClaw has access to all 67 OpenClaw tools
- Add `--max-budget-usd 2.00` per message

### 1.4 Auth exemption ✅ DONE

- Added `/coderclaw/webhook` to exempt_paths

---

## Phase 2: This Week

### 2.1 Smart context for execute phase

- Read actual files referenced in plan instead of dumping research text
- 30-40% reduction in input tokens

### 2.2 Verify phase must run tests

- Force `npm run build` or `pytest` instead of describing what to check

### 2.3 Add compaction hook

- Re-inject critical context (CLAUDE.md, key paths) when context compacts

### 2.4 Wire CoderClaw to job system

- Big tasks auto-create OpenClaw jobs with full pipeline (research→plan→execute→verify)

### 2.5 Budget tiers

- P0: $10 Sonnet | P1: $5 Sonnet | P2: $3 Haiku | P3: $1 Haiku

---

## Phase 3: Next 2 Weeks

### 3.1 Replace tool-use loop with Claude Code CLI

- Execute phase spawns `claude -p --resume` instead of manual tool loop
- Claude Code handles compaction, tools, MCP natively

### 3.2 Continuous learning (instincts)

- Auto-extract patterns from job outcomes
- Inject into future prompts

### 3.3 Unify Telegram bots

- Add `/cc` command to main bot → routes to Claude Code
- Single bot for everything

---

## Leads Found (Flagstaff Restaurants)

| #   | Business                  | Phone          | Notes                                |
| --- | ------------------------- | -------------- | ------------------------------------ |
| 1   | Fat Olives                | (928) 853-0056 | Award-winning pizzeria, DDD featured |
| 2   | Satchmo's Cajun & BBQ     | (928) 774-3274 | Best BBQ per Southern Living         |
| 3   | Salsa Brava               | (928) 779-5293 | DDD featured, salsa bar              |
| 4   | MartAnne's Burrito Palace | (928) 773-4701 | Best of Flag breakfast               |
| 5   | Nimarco's Pizza           | (928) 779-2691 | GF options, carry-out focused        |
| 6   | Diablo Burger             | (928) 774-3274 | Best of Flag burgers                 |
| 7   | El Tapatio Mexican        | (928) 774-3530 | Traditional, needs online presence   |
| 8   | La Fonda Mexican          | (928) 779-0296 | Needs website + CRM                  |
