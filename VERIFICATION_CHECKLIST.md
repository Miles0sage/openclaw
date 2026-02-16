# Quality Gates Verification Checklist

**Purpose:** Ensure code quality, security, performance, and compliance before shipping Phase 4 deliverables.

**Usage:** Use this checklist with **Max Effort Reasoning** (Claude Opus 4.6) before creating any commit or PR.

**Last Updated:** 2026-02-16
**Status:** Phase 4 Quality Gates Framework

---

## 1. Security Verification (8 items)

- [ ] **No secrets in code** — Check for API keys, tokens, credentials
  - Pattern: `ANTHROPIC_API_KEY`, `STRIPE_SECRET_KEY`, `SUPABASE_PASSWORD`
  - Tool: `grep -r "sk_", "pk_", "secret", "password" src/`
  - Reference: See [barber-crm-errors.md](./barber-crm-errors.md) for credential fixes

- [ ] **Environment variables properly configured** — All secrets in `.env.local` or Vercel
  - Action: `vercel env list` confirms all vars exist
  - Confirm: `.env.example` documents all required vars
  - Reference: [setup.md](./setup.md) (Barber CRM)

- [ ] **SQL injection prevention** — No raw SQL queries, use parameterized queries
  - Pattern: `supabase.from(table).select(fields)` (safe)
  - Anti-pattern: `SELECT * FROM ${table}` (unsafe)
  - Reference: OWASP Top 10 A03:2021

- [ ] **XSS prevention** — User input sanitized before rendering
  - Action: Use React's built-in XSS escaping
  - Check: No `dangerouslySetInnerHTML` without sanitization
  - Reference: React security docs

- [ ] **Authentication & authorization** — Session management correct
  - Action: Test login/logout flows
  - Check: Protected routes validate session
  - Reference: NextAuth docs, `/middleware.ts`

- [ ] **Rate limiting on sensitive endpoints** — API abuse prevention
  - Action: Implement rate limits on auth, payment endpoints
  - Tool: Check `/api/payments`, `/api/auth` routes
  - Reference: OWASP A04:2021

- [ ] **No hardcoded IPs or ports** — Configuration externalized
  - Pattern: Use environment variables for all addresses
  - Check: No `localhost:3000` in production code
  - Reference: 12-factor app principles

- [ ] **Webhook signatures verified** — Stripe, Vapi webhooks authenticated
  - Pattern: Verify `stripe-signature` header before processing
  - Action: Check `POST /api/payments/webhook`
  - Reference: Stripe docs, signature verification

---

## 2. Architecture & Design (8 items)

- [ ] **Code organization follows project structure** — Files in correct directories
  - Reference: CLAUDE.md for each project (Components, API routes, etc.)
  - Action: New files follow naming conventions (`component.tsx`, `route.ts`)
  - Check: No orphaned files in wrong directories

- [ ] **Type safety maintained** — TypeScript strict mode, no `any` types
  - Action: `npx tsc --noEmit` (check for type errors)
  - Reference: `tsconfig.json` (`"strict": true`)
  - Tool: Run ESLint with TypeScript plugin

- [ ] **Component composition correct** — Server/client components properly marked
  - Pattern: Client components start with `'use client'`
  - Check: No `useEffect` in server components
  - Reference: Next.js 15 App Router docs

- [ ] **API route error handling** — All routes have try/catch + proper status codes
  - Pattern: Return `NextResponse.json()` with status codes
  - Check: 400 for bad input, 500 for server error, 401 for auth
  - Reference: HTTP status codes (RFC 7231)

- [ ] **No circular dependencies** — Modules don't import each other circularly
  - Action: Check import chains (A→B→A)
  - Tool: `npm ls` or `pnpm ls` (spot circular deps)
  - Reference: Modular design principles

- [ ] **Database schemas are documented** — Supabase tables have clear structure
  - Action: Document all columns, types, constraints
  - Check: RLS policies configured per table
  - Reference: Supabase docs, schema comments

- [ ] **State management is centralized** — No prop drilling, use React Context/hooks
  - Pattern: Use custom hooks (`useBooking`, `useAuth`) instead of props
  - Check: Max 3 levels of prop drilling
  - Reference: React patterns

- [ ] **Third-party dependencies are up-to-date** — No critical vulnerabilities
  - Action: `npm audit` (all issues resolved or accepted)
  - Check: `package.json` versions reasonable
  - Reference: npm security advisories

---

## 3. Testing & Coverage (8 items)

- [ ] **Unit tests pass** — All test suites run successfully
  - Command (Python): `python -m pytest -v` → 358/358 passed (PrestressCalc)
  - Command (TS/Node): `pnpm test --run` → All suites passing (Barber CRM, Delhi Palace)
  - Reference: `.claude/settings.json` test_command

- [ ] **Integration tests cover critical paths** — Booking, payments, auth tested end-to-end
  - Check: User flows tested (book → pay → confirm)
  - Action: Verify API integrations (Stripe, Supabase, Vapi)
  - Reference: Integration test files

- [ ] **Coverage meets minimum threshold** — 85%+ code coverage on critical modules
  - Command (Python): `python -m pytest --cov=prestressed --cov-report=term-missing`
  - Expected: 85%+ coverage on `src/`, `prestressed/`, `app/api/`
  - Reference: `.claude/settings.json` coverage_target

- [ ] **Edge cases are tested** — Empty states, null values, boundary conditions
  - Examples: Empty booking list, invalid phone number, negative amounts
  - Action: Add parametrized tests for edge cases
  - Reference: `@pytest.mark.parametrize` or `test.each()`

- [ ] **Error scenarios are handled** — Network failures, API errors, timeouts
  - Check: Tests for network errors, API 500s, timeouts
  - Action: Mock external services in tests
  - Reference: Jest mocking, pytest fixtures

- [ ] **Database queries are tested** — Supabase queries validated in test DB
  - Action: Use test database for integration tests
  - Check: RLS policies work correctly
  - Reference: Supabase test mode

- [ ] **Performance baselines established** — Response times acceptable
  - API response time target: <200ms (p95)
  - Page load target: <3s (LCP)
  - Reference: Web Vitals, performance benchmarks

- [ ] **Tests are deterministic** — No flaky tests, consistent results
  - Action: Run tests 5x, verify 100% pass rate
  - Check: No timing dependencies, proper cleanup
  - Reference: Test reliability best practices

---

## 4. Performance & Optimization (8 items)

- [ ] **Bundle size is optimized** — No large dependencies unnecessarily included
  - Check: `npm bundle-report` (if available) or Vercel Analytics
  - Target: JS bundle < 200KB gzipped
  - Action: Code split large components
  - Reference: Next.js performance guide

- [ ] **Rendering is optimized** — No unnecessary re-renders, proper memoization
  - Pattern: Use `React.memo()` for expensive components
  - Check: DevTools Profiler for render times
  - Action: Verify component isolation

- [ ] **Database queries are efficient** — No N+1 queries, proper indexing
  - Check: Supabase query logs for slow queries
  - Action: Add database indexes on frequently queried columns
  - Reference: Database optimization guide

- [ ] **Lighthouse scores are acceptable** — Performance, Accessibility, SEO passing
  - Target: 80+ for Performance, 90+ for Accessibility
  - Command: `lhci autorun` (Delhi Palace)
  - Reference: QUALITY_GATES_README.md

- [ ] **Images are optimized** — Compressed, lazy-loaded, WebP format where possible
  - Action: Use `next/image` component (automatic optimization)
  - Check: Image sizes in DevTools Network tab
  - Reference: Next.js Image component

- [ ] **API rate limiting is configured** — Prevents abuse and ensures stability
  - Action: Implement per-user rate limits
  - Check: Redis/cache layer for rate limiting
  - Reference: Common rate limits (100 req/min per user)

- [ ] **Caching strategy is in place** — Browser cache, API cache, database cache
  - Pattern: Use cache headers (`Cache-Control`, `ETag`)
  - Check: Vercel Edge Caching configured
  - Reference: HTTP caching, Vercel docs

- [ ] **Monitoring is configured** — Logs, metrics, alerting for production issues
  - Action: Vercel Analytics enabled
  - Check: Error tracking (Sentry or built-in)
  - Reference: Observability best practices

---

## 5. Documentation & Maintainability (8 items)

- [ ] **README is up-to-date** — Quick-start guide accurate, commands work
  - Check: Installation, setup, running commands all tested
  - Action: Test every command in README
  - Reference: Project README files

- [ ] **Code comments explain complex logic** — Not self-evident from code
  - Pattern: Comment the "why", not the "what"
  - Check: No commenting obvious code (`i += 1 // increment i`)
  - Reference: Code review guidelines

- [ ] **Function signatures have docstrings** — Parameters, return types, exceptions documented
  - Pattern: Triple-quoted docstrings with Parameters/Returns/Raises
  - Check: PyDoc/JSDoc comments present
  - Reference: CLAUDE.md for each project

- [ ] **API endpoints are documented** — Request/response examples, status codes
  - Action: Add OpenAPI/Swagger comments to routes
  - Check: Example requests in code comments
  - Reference: API documentation best practices

- [ ] **Configuration is documented** — Environment variables explained
  - Action: Maintain `.env.example` with all required vars
  - Check: Config file (config.json) has comments
  - Reference: 12-factor app

- [ ] **Error messages are helpful** — Users understand what went wrong and how to fix
  - Pattern: Include error codes, context, next steps
  - Check: No generic "Error" messages
  - Reference: Error handling guide

- [ ] **Breaking changes are documented** — Migration guide for updates
  - Action: Document any API changes, schema migrations
  - Check: CHANGELOG updated
  - Reference: Semantic versioning (semver)

- [ ] **Team workflows documented** — Contributing guidelines, PR process, deployment steps
  - Action: CONTRIBUTING.md exists and is clear
  - Check: PR template configured
  - Reference: CLAUDE.md in each project repo

---

## Pre-Commit Checklist

**Run this before `git commit`:**

```bash
# 1. Run all quality gates
python -m pytest -v --cov=prestressed --cov-report=term-missing  # Python
pnpm test --run && pnpm lint                                      # TypeScript

# 2. Check for secrets
git diff --cached | grep -E "(secret|password|key)" && echo "BLOCKED: Secrets found!"

# 3. Type check
npx tsc --noEmit  # TypeScript projects

# 4. Code format
pnpm prettier --write .  # Format all code

# 5. Final verification
git status  # Review changes before commit
```

**Exit criteria:**

- All tests passing
- Coverage ≥ 85%
- No secrets detected
- Type checking passes
- Code formatted

---

## Pre-PR Verification Checklist

**Run this before pushing to GitHub:**

1. **Run full test suite** (10-15 minutes)

   ```bash
   pnpm test --run  # or pytest -v
   ```

2. **Verify all quality gates pass**
   - Coverage ≥ 85%
   - Linting passes (ESLint, Black)
   - No type errors

3. **Manual testing in local environment**
   - Critical user paths work
   - Error cases handled gracefully
   - No console errors/warnings

4. **Performance check** (if modified rendering)
   - Lighthouse scores acceptable (80+)
   - No new slow queries
   - Bundle size unchanged or decreased

5. **Security check**
   - No secrets in code
   - No SQL injection vulnerabilities
   - External APIs properly authenticated

6. **Documentation updated**
   - Comments added for complex logic
   - README reflects changes
   - API docs updated (if applicable)

---

## Project-Specific References

| Project            | CLAUDE.md                                            | Settings                                                             | Tests                         |
| ------------------ | ---------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------- |
| **PrestressCalc**  | [CLAUDE.md](../Mathcad-Scripts/CLAUDE.md)            | [settings.json](../Mathcad-Scripts/.claude/settings.json)            | `tests/test_*.py` (358 tests) |
| **Barber CRM**     | [CLAUDE.md](../Barber-CRM/CLAUDE.md)                 | [settings.json](../Barber-CRM/.claude/settings.json)                 | `tests/` (Jest)               |
| **Delhi Palace**   | [CLAUDE.md](../Delhi-Palace/CLAUDE.md)               | [settings.json](../Delhi-Palace/.claude/settings.json)               | `tests/` + Lighthouse         |
| **Concrete Canoe** | [CLAUDE.md](../concrete-canoe-project2026/CLAUDE.md) | [settings.json](../concrete-canoe-project2026/.claude/settings.json) | Spec validation               |
| **OpenClaw**       | [AGENTS.md](./AGENTS.md)                             | [config.json](./config.json)                                         | `tests/` (Mocha)              |

---

## Tips for Success

1. **Use this checklist as a conversation prompt** — Run with Claude Opus 4.6 + Extended Thinking for complex reviews
2. **Automate what you can** — Quality gates in `.claude/settings.json` run automatically
3. **Document everything** — Future you (and your team) will appreciate it
4. **Fail fast** — Catch issues early (pre-commit > pre-PR > production)
5. **Review thoroughly** — Max Effort reasoning catches subtle bugs

---

## Questions?

Refer to:

- [QUALITY_GATES_README.md](./QUALITY_GATES_README.md) — How quality gates work
- [PROMPT_CACHING_SETUP.md](./PROMPT_CACHING_SETUP.md) — Performance optimization
- [CLAUDE.md](./AGENTS.md) — OpenClaw architecture

**Generated:** 2026-02-16 | **Framework Version:** Phase 4 Quality Gates
