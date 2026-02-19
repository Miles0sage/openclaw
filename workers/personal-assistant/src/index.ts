/**
 * OpenClaw Personal Assistant — Cloudflare Worker
 *
 * Hono-based edge proxy that sits in front of the VPS gateway
 * (http://152.53.55.207:18789).  Adds bearer-token auth, KV-backed
 * session persistence, rate limiting, and a /api/status dashboard
 * endpoint that aggregates all gateway subsystems into one payload.
 *
 * Gateway APIs proxied:
 *   POST /api/chat               — conversational gateway (session memory)
 *   POST /api/proposal/create    — create a proposal
 *   GET  /api/proposals           — list proposals
 *   GET  /api/proposal/:id        — get single proposal
 *   GET  /api/jobs                — list jobs
 *   POST /api/job/create          — create a job
 *   GET  /api/job/:id             — get single job
 *   POST /api/job/:id/approve     — approve a job
 *   GET  /api/events              — system events
 *   GET  /api/memories            — memory search
 *   POST /api/memory/add          — add a memory
 *   GET  /api/cron/jobs           — cron status
 *   GET  /api/costs/summary       — budget / cost summary
 *   GET  /api/policy              — ops policy
 *   GET  /api/quotas/status       — quota status
 *   POST /api/route               — intelligent routing
 *   GET  /api/route/models        — available models
 *   GET  /api/route/health        — router health
 *   GET  /api/heartbeat/status    — agent heartbeat
 *   GET  /api/agents              — registered agents
 */

import { Hono } from "hono";
import { cors } from "hono/cors";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Env {
  GATEWAY_URL: string;
  GATEWAY_TOKEN: string;
  BEARER_TOKEN?: string; // optional extra auth for this worker
  ENVIRONMENT: string;
  RATE_LIMIT_PER_MINUTE: string;
  DB: D1Database;
  KV_CACHE: KVNamespace;
  KV_SESSIONS: KVNamespace;
}

interface ChatRequest {
  message: string;
  sessionKey?: string;
  agent?: string;
  model?: string;
}

interface SessionData {
  messages: Array<{ role: string; content: string; timestamp: string }>;
  created: string;
  updated: string;
  messageCount: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Forward a request to the VPS gateway, returning the parsed JSON. */
async function gatewayFetch(env: Env, path: string, options: RequestInit = {}): Promise<Response> {
  const url = `${env.GATEWAY_URL}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Auth-Token": env.GATEWAY_TOKEN,
    ...(options.headers as Record<string, string> | undefined),
  };

  try {
    const resp = await fetch(url, { ...options, headers });
    return resp;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return new Response(JSON.stringify({ error: "gateway_unreachable", detail: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}

/** Simple in-memory rate limiter keyed by IP (resets per isolate). */
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();

function checkRateLimit(ip: string, maxPerMinute: number): boolean {
  const now = Date.now();
  const entry = rateLimitMap.get(ip);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + 60_000 });
    return true;
  }
  entry.count++;
  return entry.count <= maxPerMinute;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

const app = new Hono<{ Bindings: Env }>();

// CORS
app.use("*", cors({ origin: "*", allowMethods: ["GET", "POST", "OPTIONS"] }));

// ---------------------------------------------------------------------------
// Auth middleware — skip health endpoint
// ---------------------------------------------------------------------------
app.use("*", async (c, next) => {
  const path = new URL(c.req.url).pathname;
  if (path === "/health" || path === "/") return next();

  // If BEARER_TOKEN is set, enforce it
  const requiredToken = c.env.BEARER_TOKEN;
  if (requiredToken) {
    const auth = c.req.header("Authorization");
    const token = auth?.startsWith("Bearer ") ? auth.slice(7) : null;
    if (token !== requiredToken) {
      return c.json({ error: "unauthorized" }, 401);
    }
  }

  // Rate limit
  const ip = c.req.header("CF-Connecting-IP") || "unknown";
  const limit = parseInt(c.env.RATE_LIMIT_PER_MINUTE || "30", 10);
  if (!checkRateLimit(ip, limit)) {
    return c.json({ error: "rate_limited", retry_after_seconds: 60 }, 429);
  }

  return next();
});

// ---------------------------------------------------------------------------
// GET / — landing
// ---------------------------------------------------------------------------
app.get("/", (c) => {
  return c.json({
    service: "OpenClaw Personal Assistant",
    version: "2.0.0",
    environment: c.env.ENVIRONMENT,
    endpoints: [
      "GET  /health",
      "POST /api/chat",
      "GET  /api/status",
      "POST /api/proposal/create",
      "GET  /api/proposals",
      "GET  /api/jobs",
      "POST /api/job/create",
      "GET  /api/events",
      "GET  /api/memories",
      "POST /api/memory/add",
      "GET  /api/cron/jobs",
      "GET  /api/costs/summary",
      "GET  /api/policy",
      "GET  /api/quotas/status",
      "POST /api/route",
      "GET  /api/route/models",
      "GET  /api/route/health",
      "GET  /api/heartbeat/status",
      "GET  /api/agents",
    ],
  });
});

// ---------------------------------------------------------------------------
// GET /health
// ---------------------------------------------------------------------------
app.get("/health", async (c) => {
  // Quick gateway ping
  let gatewayOk = false;
  try {
    const resp = await fetch(`${c.env.GATEWAY_URL}/health`, {
      signal: AbortSignal.timeout(3000),
    });
    gatewayOk = resp.ok;
  } catch {
    gatewayOk = false;
  }

  return c.json({
    status: gatewayOk ? "ok" : "degraded",
    worker: "ok",
    gateway: gatewayOk ? "ok" : "unreachable",
    timestamp: new Date().toISOString(),
    environment: c.env.ENVIRONMENT,
  });
});

// ---------------------------------------------------------------------------
// POST /api/chat — proxy to gateway with KV session persistence
// ---------------------------------------------------------------------------
app.post("/api/chat", async (c) => {
  const body = await c.req.json<ChatRequest>();
  const { message, sessionKey, agent, model } = body;

  if (!message) {
    return c.json({ error: "message is required" }, 400);
  }

  const key = sessionKey || `worker:${crypto.randomUUID()}`;

  // Load session from KV
  let session: SessionData | null = null;
  try {
    const raw = await c.env.KV_SESSIONS.get(key);
    if (raw) session = JSON.parse(raw);
  } catch {
    // ignore parse errors, start fresh
  }

  if (!session) {
    session = {
      messages: [],
      created: new Date().toISOString(),
      updated: new Date().toISOString(),
      messageCount: 0,
    };
  }

  // Append user message to local session
  session.messages.push({
    role: "user",
    content: message,
    timestamp: new Date().toISOString(),
  });

  // Forward to gateway
  const gatewayResp = await gatewayFetch(c.env, "/api/chat", {
    method: "POST",
    body: JSON.stringify({
      content: message,
      sessionKey: key,
      agent_id: agent || "pm",
    }),
  });

  if (!gatewayResp.ok) {
    const errText = await gatewayResp.text();
    return c.json({ error: "gateway_error", status: gatewayResp.status, detail: errText }, 502);
  }

  const gatewayData = (await gatewayResp.json()) as Record<string, unknown>;

  // Append assistant response to local session
  const reply =
    (gatewayData.response as string) ||
    (gatewayData.message as string) ||
    (gatewayData.reply as string) ||
    "";
  if (reply) {
    session.messages.push({
      role: "assistant",
      content: reply,
      timestamp: new Date().toISOString(),
    });
  }

  session.updated = new Date().toISOString();
  session.messageCount = session.messages.length;

  // Save session to KV (24h TTL)
  try {
    await c.env.KV_SESSIONS.put(key, JSON.stringify(session), {
      expirationTtl: 86400,
    });
  } catch {
    // non-fatal
  }

  return c.json({
    ...gatewayData,
    sessionKey: key,
    sessionMessageCount: session.messageCount,
  });
});

// ---------------------------------------------------------------------------
// GET /api/status — aggregated dashboard view of all gateway subsystems
// ---------------------------------------------------------------------------
app.get("/api/status", async (c) => {
  const endpoints: Record<string, { path: string; method: string }> = {
    health: { path: "/health", method: "GET" },
    agents: { path: "/api/agents", method: "GET" },
    heartbeat: { path: "/api/heartbeat/status", method: "GET" },
    costs: { path: "/api/costs/summary", method: "GET" },
    quotas: { path: "/api/quotas/status", method: "GET" },
    policy: { path: "/api/policy", method: "GET" },
    events: { path: "/api/events?limit=10", method: "GET" },
    memories: { path: "/api/memories?limit=5", method: "GET" },
    cronJobs: { path: "/api/cron/jobs", method: "GET" },
    jobs: { path: "/api/jobs", method: "GET" },
    proposals: { path: "/api/proposals", method: "GET" },
    routerHealth: { path: "/api/route/health", method: "GET" },
    routerModels: { path: "/api/route/models", method: "GET" },
  };

  const results: Record<string, unknown> = {};
  const statuses: Record<string, string> = {};

  // Fire all requests in parallel
  const entries = Object.entries(endpoints);
  const responses = await Promise.allSettled(
    entries.map(([, cfg]) => gatewayFetch(c.env, cfg.path, { method: cfg.method })),
  );

  for (let i = 0; i < entries.length; i++) {
    const [name] = entries[i];
    const result = responses[i];
    if (result.status === "fulfilled" && result.value.ok) {
      try {
        results[name] = await result.value.json();
        statuses[name] = "ok";
      } catch {
        results[name] = null;
        statuses[name] = "parse_error";
      }
    } else {
      results[name] = null;
      statuses[name] = result.status === "rejected" ? "error" : `http_${result.value.status}`;
    }
  }

  const okCount = Object.values(statuses).filter((s) => s === "ok").length;
  const totalCount = Object.keys(statuses).length;

  return c.json({
    overall:
      okCount === totalCount ? "healthy" : okCount > totalCount / 2 ? "degraded" : "critical",
    subsystems: statuses,
    summary: `${okCount}/${totalCount} subsystems healthy`,
    data: results,
    timestamp: new Date().toISOString(),
  });
});

// ---------------------------------------------------------------------------
// Proxy helpers — GET and POST pass-through to gateway
// ---------------------------------------------------------------------------

/** Create a GET proxy route */
function proxyGet(workerPath: string, gatewayPath?: string) {
  app.get(workerPath, async (c) => {
    // Forward query string
    const url = new URL(c.req.url);
    const qs = url.search;
    const target = (gatewayPath || workerPath) + qs;
    const resp = await gatewayFetch(c.env, target);
    const data = await resp.text();
    return new Response(data, {
      status: resp.status,
      headers: { "Content-Type": "application/json" },
    });
  });
}

/** Create a POST proxy route */
function proxyPost(workerPath: string, gatewayPath?: string) {
  app.post(workerPath, async (c) => {
    const body = await c.req.text();
    const resp = await gatewayFetch(c.env, gatewayPath || workerPath, {
      method: "POST",
      body,
    });
    const data = await resp.text();
    return new Response(data, {
      status: resp.status,
      headers: { "Content-Type": "application/json" },
    });
  });
}

// ---------------------------------------------------------------------------
// Proxy routes — Proposals
// ---------------------------------------------------------------------------
proxyPost("/api/proposal/create");
proxyGet("/api/proposals");

// Parameterized routes need custom handlers (can't use proxyGet helper)
app.get("/api/proposal/:id", async (c) => {
  const id = c.req.param("id");
  const resp = await gatewayFetch(c.env, `/api/proposal/${id}`);
  const data = await resp.text();
  return new Response(data, {
    status: resp.status,
    headers: { "Content-Type": "application/json" },
  });
});

// ---------------------------------------------------------------------------
// Proxy routes — Jobs
// ---------------------------------------------------------------------------
proxyGet("/api/jobs");
proxyPost("/api/job/create");

app.get("/api/job/:id", async (c) => {
  const id = c.req.param("id");
  const resp = await gatewayFetch(c.env, `/api/job/${id}`);
  const data = await resp.text();
  return new Response(data, {
    status: resp.status,
    headers: { "Content-Type": "application/json" },
  });
});

app.post("/api/job/:id/approve", async (c) => {
  const id = c.req.param("id");
  const body = await c.req.text();
  const resp = await gatewayFetch(c.env, `/api/job/${id}/approve`, {
    method: "POST",
    body,
  });
  const data = await resp.text();
  return new Response(data, {
    status: resp.status,
    headers: { "Content-Type": "application/json" },
  });
});

// ---------------------------------------------------------------------------
// Proxy routes — Events, Memories, Cron, Costs, Policy, Quotas
// ---------------------------------------------------------------------------
proxyGet("/api/events");
proxyGet("/api/memories");
proxyPost("/api/memory/add");
proxyGet("/api/cron/jobs");
proxyGet("/api/costs/summary");
proxyGet("/api/policy");
proxyGet("/api/quotas/status");

// ---------------------------------------------------------------------------
// Proxy routes — Router
// ---------------------------------------------------------------------------
proxyPost("/api/route");
proxyGet("/api/route/models");
proxyGet("/api/route/health");

// ---------------------------------------------------------------------------
// Proxy routes — Agents, Heartbeat
// ---------------------------------------------------------------------------
proxyGet("/api/agents");
proxyGet("/api/heartbeat/status");

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export default app;
