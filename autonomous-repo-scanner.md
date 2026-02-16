# OpenClaw Autonomous Repo Scanner Task

**Goal:** Scan all Miles Sage GitHub repos and generate detailed summaries + implementation plans

## Repos to Analyze

1. `/root/Barber-CRM/` → Barber booking system
2. `/root/Delhi-Palace/` → Restaurant website
3. `/root/Mathcad-Scripts/` → PrestressCalc calculator
4. `/root/concrete-canoe-project2026/` → Structural design project
5. `/root/moltbot-sandbox/` → Cost-optimized AI agent

## For Each Repo Generate:

### 1. Project Overview

- Purpose + business goal
- Current status (% complete)
- Team/ownership
- Live URLs (if deployed)

### 2. Technical Stack

- Languages, frameworks, libraries
- Database/storage (Supabase, Firebase, etc)
- Deployment (Vercel, Cloudflare, etc)
- APIs/integrations

### 3. Current State

- Latest commit message + date
- Last 5 commits with summary
- Open PRs/issues
- Test coverage (if applicable)
- Known bugs/TODOs

### 4. Architecture Diagram

```
[Describe the system architecture in text]
Example:
Frontend (Next.js/React) → API (Node/Python) → Database (Supabase)
```

### 5. Feature Checklist

- ✅ Completed features
- 🔄 In-progress features
- ⏳ Planned features
- ❌ Known issues

### 6. Implementation Plan (Next Phase)

- Current phase vs next phase
- 3-5 actionable tasks
- Estimated timeline
- Blockers/dependencies
- Cost implications

### 7. Deployment Status

- Live URL (if applicable)
- Deployment method (auto-deploy, manual, CI/CD)
- Environment variables configured
- Monitoring/alerts

## Output Format

Create one summary file per repo:

- `repo-summary-barber-crm.md`
- `repo-summary-delhi-palace.md`
- `repo-summary-prestress-calc.md`
- `repo-summary-concrete-canoe.md`
- `repo-summary-moltbot.md`

Save to `/root/openclaw/repo-summaries/`

## Master Plan

After all summaries generated:

- Create `MASTER-DEVELOPMENT-PLAN.md` with:
  - All projects timeline (Gantt view in text)
  - Shared dependencies between projects
  - Resource allocation (which agent does what)
  - Risk assessment
  - Cost projections
  - Success metrics

## Success Criteria

✅ All 5 repos analyzed
✅ Detailed summaries generated
✅ Implementation plans for each
✅ Master coordinated development plan
✅ Saved to memory for future reference
