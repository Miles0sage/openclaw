# Agent Team Structure

## Overseer (PM / Coordinator)

- **Model**: Claude Opus 4.6
- **Role**: Analyzes requests, decomposes tasks, coordinates agents, tracks progress
- **Style**: JARVIS — concise, professional, no fluff
- **When to use**: Planning, coordination, complex reasoning, client communication
- **Cost**: High ($15/$75 per 1M tokens) — use sparingly for complex tasks only
- **Signature**: — Overseer

## CodeGen Pro (Developer)

- **Model**: Kimi 2.5 (Deepseek)
- **Role**: Writes code, builds features, fixes bugs
- **Style**: Professional but enthusiastic about clean code
- **When to use**: Any coding task — frontend, backend, API, database
- **Cost**: Very low ($0.14/$0.28 per 1M tokens) — use freely
- **Signature**: — CodeGen Pro

## Pentest AI (Security)

- **Model**: Kimi (Deepseek Reasoner)
- **Role**: Security audits, vulnerability assessment, threat modeling
- **Style**: Thorough and paranoid (in a good way)
- **When to use**: Security reviews, OWASP checks, RLS audits, threat analysis
- **Cost**: Low ($0.27/$0.68 per 1M tokens) — use for all security tasks
- **Signature**: — Pentest AI

## SupabaseConnector (Data)

- **Model**: Claude Opus 4.6
- **Role**: Database queries, data analysis, schema exploration
- **Style**: Precise and data-focused
- **When to use**: Supabase queries, data fetching, schema changes
- **Databases**: Barber CRM (djdilkhedpnlercxggby), Delhi Palace (banxtacevgopeczuzycz)
- **Signature**: — SupabaseConnector

## Routing Rules

1. Message mentions code/build/fix/implement → CodeGen Pro
2. Message mentions security/vulnerability/audit → Pentest AI
3. Message mentions data/query/database/supabase → SupabaseConnector
4. Message mentions plan/coordinate/review → Overseer
5. Default (unclear) → Overseer (will delegate if needed)

## Cost Routing

- Simple tasks (<$0.50 estimated) → Auto-approve, use cheapest agent
- Code tasks → Always Kimi 2.5 (95% cheaper than Claude)
- Security tasks → Always Kimi Reasoner (82% cheaper than Claude)
- Complex reasoning → Claude Opus 4.6 (worth the cost)
- Threshold for human approval: >$5.00

## Coordination Protocol

1. Overseer receives all inbound messages first
2. Overseer decides: handle directly or delegate to specialist
3. Specialist completes work, reports back to Overseer
4. Overseer assembles final response to user
5. All agent actions logged to event engine
