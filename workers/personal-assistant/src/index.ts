/**
 * OpenClaw Personal Assistant — Cloudflare Worker
 *
 * Hono-based edge proxy that sits in front of the VPS gateway
 * (https://gateway.overseerclaw.uk).  Adds bearer-token auth, KV-backed
 * session persistence, rate limiting, a /api/status dashboard
 * endpoint that aggregates all gateway subsystems into one payload,
 * WebSocket proxy at /ws, and a landing page chat UI.
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
 *   WS   /ws                      — real-time WebSocket proxy
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

/**
 * Simple in-memory rate limiter keyed by IP (resets per isolate).
 * The `internal` flag allows exempting server-side calls (e.g. /api/status
 * fan-out) from being counted against user limits.
 */
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

// Paths that are exempt from auth and rate limiting
const PUBLIC_PATHS = new Set(["/", "/health", "/ws"]);

// Paths whose handler issues internal gateway calls — exempt from rate limiting
// but NOT from auth
const INTERNAL_FANOUT_PATHS = new Set(["/api/status"]);

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

const app = new Hono<{ Bindings: Env }>();

// CORS
app.use("*", cors({ origin: "*", allowMethods: ["GET", "POST", "OPTIONS"] }));

// ---------------------------------------------------------------------------
// Auth middleware — skip health / landing / ws endpoints
// ---------------------------------------------------------------------------
app.use("*", async (c, next) => {
  const path = new URL(c.req.url).pathname;

  // Fully public endpoints — no auth, no rate limiting
  if (PUBLIC_PATHS.has(path)) return next();

  // If BEARER_TOKEN is set, enforce it
  const requiredToken = c.env.BEARER_TOKEN;
  if (requiredToken) {
    const auth = c.req.header("Authorization");
    const token = auth?.startsWith("Bearer ") ? auth.slice(7) : null;
    if (token !== requiredToken) {
      return c.json({ error: "unauthorized" }, 401);
    }
  }

  // Rate limit — skip for internal fan-out paths (they make many gateway
  // calls on behalf of the user but should only cost 1 rate-limit hit)
  if (!INTERNAL_FANOUT_PATHS.has(path)) {
    const ip = c.req.header("CF-Connecting-IP") || "unknown";
    const limit = parseInt(c.env.RATE_LIMIT_PER_MINUTE || "30", 10);
    if (!checkRateLimit(ip, limit)) {
      return c.json({ error: "rate_limited", retry_after_seconds: 60 }, 429);
    }
  }

  return next();
});

// ---------------------------------------------------------------------------
// GET / — Landing page with chat UI
// ---------------------------------------------------------------------------
app.get("/", (c) => {
  const html = LANDING_HTML;
  return new Response(html, {
    headers: { "Content-Type": "text/html; charset=utf-8" },
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
// (Rate-limit exempt: uses internal fan-out calls to gateway)
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
// Landing page HTML — Dark-themed chat UI
// ---------------------------------------------------------------------------
const LANDING_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenClaw Assistant</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  :root{
    --bg:#0d1117;--surface:#161b22;--border:#30363d;
    --text:#e6edf3;--text-muted:#8b949e;--accent:#58a6ff;
    --accent-hover:#79c0ff;--user-bg:#1f6feb33;--bot-bg:#21262d;
    --danger:#f85149;--success:#3fb950;
  }
  html,body{height:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}
  body{background:var(--bg);color:var(--text);display:flex;flex-direction:column}

  /* Header */
  .header{
    padding:14px 20px;background:var(--surface);border-bottom:1px solid var(--border);
    display:flex;align-items:center;gap:12px;flex-shrink:0;
  }
  .header .logo{
    width:32px;height:32px;border-radius:8px;background:var(--accent);
    display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;color:#fff;
  }
  .header h1{font-size:16px;font-weight:600;color:var(--text)}
  .header .badge{
    font-size:11px;padding:2px 8px;border-radius:10px;
    background:var(--success);color:#000;font-weight:600;margin-left:auto;
  }
  .header .status-dot{
    width:8px;height:8px;border-radius:50%;background:var(--success);
    animation:pulse 2s infinite;
  }
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

  /* Chat area */
  .chat{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px}
  .msg{max-width:720px;width:100%;padding:12px 16px;border-radius:12px;line-height:1.55;font-size:14px;white-space:pre-wrap;word-break:break-word}
  .msg.user{background:var(--user-bg);border:1px solid #1f6feb55;align-self:flex-end;border-bottom-right-radius:4px}
  .msg.bot{background:var(--bot-bg);border:1px solid var(--border);align-self:flex-start;border-bottom-left-radius:4px}
  .msg .meta{font-size:11px;color:var(--text-muted);margin-bottom:4px;font-weight:600}
  .msg code{background:#ffffff12;padding:1px 5px;border-radius:4px;font-size:13px}
  .msg pre{background:#0d1117;border:1px solid var(--border);border-radius:6px;padding:10px;overflow-x:auto;margin:6px 0;font-size:13px}
  .msg pre code{background:none;padding:0}

  /* Typing indicator */
  .typing{display:none;align-self:flex-start;padding:12px 16px;background:var(--bot-bg);border:1px solid var(--border);border-radius:12px;border-bottom-left-radius:4px;gap:4px;align-items:center}
  .typing.show{display:flex}
  .typing span{width:7px;height:7px;background:var(--text-muted);border-radius:50%;animation:bounce .6s infinite alternate}
  .typing span:nth-child(2){animation-delay:.2s}
  .typing span:nth-child(3){animation-delay:.4s}
  @keyframes bounce{to{opacity:.3;transform:translateY(-4px)}}

  /* Input area */
  .input-area{
    padding:16px 20px;background:var(--surface);border-top:1px solid var(--border);
    display:flex;gap:10px;flex-shrink:0;
  }
  .input-area textarea{
    flex:1;background:var(--bg);border:1px solid var(--border);border-radius:10px;
    padding:10px 14px;color:var(--text);font-size:14px;font-family:inherit;
    resize:none;outline:none;min-height:44px;max-height:160px;line-height:1.4;
    transition:border-color .15s;
  }
  .input-area textarea:focus{border-color:var(--accent)}
  .input-area textarea::placeholder{color:var(--text-muted)}
  .input-area button{
    background:var(--accent);color:#fff;border:none;border-radius:10px;
    padding:0 20px;font-size:14px;font-weight:600;cursor:pointer;
    transition:background .15s;flex-shrink:0;
  }
  .input-area button:hover{background:var(--accent-hover)}
  .input-area button:disabled{opacity:.4;cursor:not-allowed}

  /* Welcome */
  .welcome{text-align:center;padding:60px 20px;color:var(--text-muted)}
  .welcome h2{font-size:22px;color:var(--text);margin-bottom:8px}
  .welcome p{font-size:14px;max-width:480px;margin:0 auto 20px}
  .welcome .chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center}
  .welcome .chip{
    background:var(--surface);border:1px solid var(--border);border-radius:8px;
    padding:8px 14px;font-size:13px;cursor:pointer;transition:border-color .15s;color:var(--text);
  }
  .welcome .chip:hover{border-color:var(--accent)}

  /* Scrollbar */
  .chat::-webkit-scrollbar{width:6px}
  .chat::-webkit-scrollbar-track{background:transparent}
  .chat::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

  /* Mobile */
  @media(max-width:600px){
    .header{padding:10px 14px}
    .chat{padding:12px}
    .input-area{padding:10px 14px}
    .msg{font-size:13px;padding:10px 12px}
    .welcome{padding:40px 16px}
    .welcome h2{font-size:18px}
  }
</style>
</head>
<body>

<div class="header">
  <div class="logo">O</div>
  <h1>OpenClaw Assistant</h1>
  <div class="status-dot" id="statusDot" title="Gateway status"></div>
  <span class="badge" id="statusBadge">checking...</span>
</div>

<div class="chat" id="chat">
  <div class="welcome" id="welcome">
    <h2>OpenClaw Personal Assistant</h2>
    <p>Connected to the Overseer AI gateway. Ask anything — plan tasks, write code, check status, or manage your projects.</p>
    <div class="chips">
      <div class="chip" onclick="sendChip(this)">Show system status</div>
      <div class="chip" onclick="sendChip(this)">What can you do?</div>
      <div class="chip" onclick="sendChip(this)">List active agents</div>
      <div class="chip" onclick="sendChip(this)">Check costs</div>
    </div>
  </div>
</div>

<div class="typing" id="typing"><span></span><span></span><span></span></div>

<div class="input-area">
  <textarea id="input" placeholder="Message OpenClaw..." rows="1"></textarea>
  <button id="sendBtn" onclick="send()">Send</button>
</div>

<script>
const chatEl=document.getElementById('chat');
const inputEl=document.getElementById('input');
const sendBtn=document.getElementById('sendBtn');
const typingEl=document.getElementById('typing');
const welcomeEl=document.getElementById('welcome');
const statusDot=document.getElementById('statusDot');
const statusBadge=document.getElementById('statusBadge');

// Session key — persisted in localStorage
let sessionKey=localStorage.getItem('oc_session');
if(!sessionKey){sessionKey='web:'+crypto.randomUUID();localStorage.setItem('oc_session',sessionKey)}

// Auto-resize textarea
inputEl.addEventListener('input',()=>{
  inputEl.style.height='auto';
  inputEl.style.height=Math.min(inputEl.scrollHeight,160)+'px';
});

// Enter to send (Shift+Enter for newline)
inputEl.addEventListener('keydown',(e)=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}
});

function sendChip(el){inputEl.value=el.textContent;send()}

function escapeHtml(s){
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function formatMsg(text){
  // Code blocks
  text=text.replace(/\`\`\`(\\w*?)\\n([\\s\\S]*?)\`\`\`/g,(_,lang,code)=>'<pre><code>'+escapeHtml(code.trim())+'</code></pre>');
  // Inline code
  text=text.replace(/\`([^\`]+)\`/g,(_,c)=>'<code>'+escapeHtml(c)+'</code>');
  // Bold
  text=text.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');
  return text;
}

function addMsg(role,text){
  if(welcomeEl)welcomeEl.style.display='none';
  const div=document.createElement('div');
  div.className='msg '+role;
  const meta=document.createElement('div');
  meta.className='meta';
  meta.textContent=role==='user'?'You':'Overseer';
  div.appendChild(meta);
  const body=document.createElement('div');
  body.innerHTML=formatMsg(text);
  div.appendChild(body);
  chatEl.appendChild(div);
  chatEl.scrollTop=chatEl.scrollHeight;
}

let sending=false;
async function send(){
  const text=inputEl.value.trim();
  if(!text||sending)return;
  sending=true;
  sendBtn.disabled=true;
  inputEl.value='';
  inputEl.style.height='auto';
  addMsg('user',text);
  typingEl.classList.add('show');
  chatEl.appendChild(typingEl);
  chatEl.scrollTop=chatEl.scrollHeight;

  try{
    const resp=await fetch('/api/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text,sessionKey})
    });
    const data=await resp.json();
    if(data.sessionKey)sessionKey=data.sessionKey;
    localStorage.setItem('oc_session',sessionKey);
    const reply=data.response||data.message||data.reply||data.error||'No response';
    addMsg('bot',reply);
  }catch(err){
    addMsg('bot','Error: '+err.message);
  }finally{
    typingEl.classList.remove('show');
    sending=false;
    sendBtn.disabled=false;
    inputEl.focus();
  }
}

// Health check
(async()=>{
  try{
    const r=await fetch('/health');
    const d=await r.json();
    if(d.gateway==='ok'){
      statusBadge.textContent='online';
      statusBadge.style.background='#3fb950';
    }else{
      statusBadge.textContent='degraded';
      statusBadge.style.background='#d29922';
      statusDot.style.background='#d29922';
    }
  }catch{
    statusBadge.textContent='offline';
    statusBadge.style.background='#f85149';
    statusDot.style.background='#f85149';
  }
})();

// Focus input on load
inputEl.focus();
</script>
</body>
</html>`;

// ---------------------------------------------------------------------------
// WebSocket proxy at /ws
// ---------------------------------------------------------------------------
// Cloudflare Workers handle WebSocket upgrades via the fetch handler
// returning a WebSocket pair. We create a pair, connect to the upstream
// VPS gateway WebSocket, and relay frames in both directions.

async function handleWebSocket(request: Request, env: Env): Promise<Response> {
  // Derive upstream WS URL from GATEWAY_URL (http(s):// -> ws(s)://)
  const gwUrl = env.GATEWAY_URL.replace(/^http/, "ws");
  const upstreamUrl = `${gwUrl}/ws`;

  // Create the client<->worker pair
  const [client, server] = Object.values(new WebSocketPair());

  // Accept the server side so we can send/receive
  server.accept();

  // Connect to upstream VPS gateway WebSocket
  let upstream: WebSocket | null = null;
  try {
    const upstreamResp = await fetch(upstreamUrl, {
      headers: {
        Upgrade: "websocket",
        "X-Auth-Token": env.GATEWAY_TOKEN,
      },
    });
    upstream = upstreamResp.webSocket;
    if (!upstream) {
      server.send(
        JSON.stringify({
          error: "upstream_ws_unavailable",
          detail: "Gateway did not return a WebSocket",
        }),
      );
      server.close(1011, "Upstream unavailable");
      return new Response(null, { status: 101, webSocket: client });
    }
    upstream.accept();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    server.send(JSON.stringify({ error: "upstream_connect_failed", detail: msg }));
    server.close(1011, "Upstream connect failed");
    return new Response(null, { status: 101, webSocket: client });
  }

  // Relay: client -> upstream
  server.addEventListener("message", (evt) => {
    try {
      if (upstream && upstream.readyState === WebSocket.READY_STATE_OPEN) {
        upstream.send(typeof evt.data === "string" ? evt.data : evt.data);
      }
    } catch {
      // upstream gone
    }
  });

  server.addEventListener("close", (evt) => {
    try {
      upstream?.close(evt.code, evt.reason);
    } catch {
      // ignore
    }
  });

  // Relay: upstream -> client
  upstream.addEventListener("message", (evt) => {
    try {
      if (server.readyState === WebSocket.READY_STATE_OPEN) {
        server.send(typeof evt.data === "string" ? evt.data : evt.data);
      }
    } catch {
      // client gone
    }
  });

  upstream.addEventListener("close", (evt) => {
    try {
      server.close(evt.code, evt.reason);
    } catch {
      // ignore
    }
  });

  upstream.addEventListener("error", () => {
    try {
      server.close(1011, "Upstream error");
    } catch {
      // ignore
    }
  });

  return new Response(null, { status: 101, webSocket: client });
}

// ---------------------------------------------------------------------------
// Export — use object syntax so we can intercept WebSocket upgrades
// ---------------------------------------------------------------------------
export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // WebSocket upgrade at /ws
    if (url.pathname === "/ws" && request.headers.get("Upgrade") === "websocket") {
      return handleWebSocket(request, env);
    }

    // Everything else goes through Hono
    return app.fetch(request, env, ctx);
  },
};
