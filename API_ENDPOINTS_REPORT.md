# OpenClaw API Endpoints Report

## Analysis Date

2026-03-03

## Summary

This report documents the API endpoints defined in gateway.py.

## Endpoint Count

**Total API Endpoints: 154**

## Breakdown by HTTP Method

- GET: 61 endpoints
- POST: 81 endpoints
- DELETE: 7 endpoints
- PATCH: 1 endpoint
- PUT/OPTIONS/HEAD: 0 endpoints

## Key Endpoint Categories

1. **Core APIs** (chat, vision, agents)
2. **Workflow Management** (workflow, job, task)
3. **Financial/Trading** (polymarket, kalshi, sports betting)
4. **Integration APIs** (slack, telegram, gmail, calendar)
5. **Analytics** (costs, metrics, quotas)
6. **Administrative** (security scan, health, logs)
7. **Data Management** (memories, events, leads, calls)
8. **OAuth & Authentication** (oauth routes)
9. **Dashboard & UI** (mission-control, dashboards)

## Verification Method

Pattern matching with regex: `@app\.(get|post|put|delete|patch|options|head)`
Total matches found: 154

---

_Analysis completed with automatic endpoint detection from gateway.py source code_
