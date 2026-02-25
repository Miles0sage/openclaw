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
  GEMINI_API_KEY: string;
  GEMINI_MODEL: string;
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

// ---------------------------------------------------------------------------
// Gemini Function Declarations — OpenClaw tools
// ---------------------------------------------------------------------------

const OPENCLAW_TOOLS = [
  {
    functionDeclarations: [
      {
        name: "list_jobs",
        description: "List agency jobs, optionally filtered by status",
        parameters: {
          type: "OBJECT",
          properties: {
            status: {
              type: "STRING",
              description: "Filter: pending, analyzing, pr_ready, approved, done, all",
            },
          },
        },
      },
      {
        name: "create_job",
        description: "Create a new autonomous job in the agency queue",
        parameters: {
          type: "OBJECT",
          properties: {
            project: {
              type: "STRING",
              description:
                "Project: barber-crm, openclaw, delhi-palace, prestress-calc, concrete-canoe",
            },
            task: { type: "STRING", description: "Description of the task" },
            priority: { type: "STRING", description: "P0=critical, P1=high, P2=medium, P3=low" },
          },
          required: ["project", "task"],
        },
      },
      {
        name: "get_job",
        description: "Get status of a specific job by ID",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "kill_job",
        description: "Kill a running job",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to kill" },
          },
          required: ["job_id"],
        },
      },
      {
        name: "get_cost_summary",
        description: "Get current API spend and budget status",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "get_agency_status",
        description: "Get combined agency overview: active jobs, costs, agents, alerts",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "list_proposals",
        description: "List proposals in the agency",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "create_proposal",
        description: "Create a proposal for a non-trivial task that needs approval",
        parameters: {
          type: "OBJECT",
          properties: {
            title: { type: "STRING", description: "Short title" },
            description: { type: "STRING", description: "What needs to be done" },
            priority: { type: "STRING", description: "P0-P3" },
            agent_pref: {
              type: "STRING",
              description: "project_manager, coder_agent, hacker_agent, database_agent",
            },
          },
          required: ["title", "description"],
        },
      },
      {
        name: "search_memory",
        description: "Search persistent memories for relevant context",
        parameters: {
          type: "OBJECT",
          properties: {
            tag: { type: "STRING", description: "Tag to filter by" },
            limit: { type: "NUMBER", description: "Max results (default 10)" },
          },
        },
      },
      {
        name: "save_memory",
        description: "Save an important fact or decision to long-term memory",
        parameters: {
          type: "OBJECT",
          properties: {
            content: { type: "STRING", description: "The fact to remember" },
            importance: { type: "NUMBER", description: "1-10 scale" },
            tags: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Tags for categorization",
            },
          },
          required: ["content"],
        },
      },
      {
        name: "get_events",
        description: "Get recent system events (job completions, proposals, alerts)",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: { type: "NUMBER", description: "Number of events (default 20)" },
          },
        },
      },
      {
        name: "list_agents",
        description: "List registered agents and their status",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "get_runner_status",
        description: "Get runner status and active job count",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "spawn_agent",
        description: "Spawn a new tmux Claude Code agent",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "Job identifier" },
            prompt: { type: "STRING", description: "Agent instruction/prompt" },
            use_worktree: { type: "BOOLEAN", description: "Create isolated git worktree" },
          },
          required: ["prompt"],
        },
      },
      {
        name: "send_chat_to_gateway",
        description:
          "Delegate a complex question to the VPS gateway (Claude Opus specialist agent)",
        parameters: {
          type: "OBJECT",
          properties: {
            message: { type: "STRING", description: "The message to send" },
            agent_id: { type: "STRING", description: "Target agent: coder, hacker, database" },
          },
          required: ["message"],
        },
      },
      {
        name: "get_gmail_inbox",
        description: "Read recent Gmail messages",
        parameters: {
          type: "OBJECT",
          properties: {
            limit: { type: "NUMBER", description: "Number of emails (default 10)" },
          },
        },
      },
      {
        name: "get_calendar_today",
        description: "Get today's Google Calendar events",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "create_calendar_event",
        description: "Create a new Google Calendar event. Use Arizona time (MST, UTC-7).",
        parameters: {
          type: "OBJECT",
          properties: {
            summary: { type: "STRING", description: "Event title" },
            start: {
              type: "STRING",
              description: "Start time ISO format e.g. 2026-02-26T09:00:00",
            },
            end: { type: "STRING", description: "End time ISO format e.g. 2026-02-26T10:00:00" },
            location: { type: "STRING", description: "Event location (optional)" },
            description: { type: "STRING", description: "Event description (optional)" },
          },
          required: ["summary", "start", "end"],
        },
      },
      {
        name: "get_calendar_upcoming",
        description: "Get upcoming calendar events for the next N days",
        parameters: {
          type: "OBJECT",
          properties: {
            days: { type: "NUMBER", description: "Number of days to look ahead (default 7)" },
          },
        },
      },
      {
        name: "list_calendars",
        description: "List all Google Calendar calendars available",
        parameters: { type: "OBJECT", properties: {} },
      },
      {
        name: "trash_emails",
        description: "Move emails to trash/delete them. Requires message IDs from get_gmail_inbox.",
        parameters: {
          type: "OBJECT",
          properties: {
            message_ids: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "List of Gmail message IDs to trash",
            },
          },
          required: ["message_ids"],
        },
      },
      {
        name: "label_emails",
        description:
          "Add or remove labels on emails. Common labels: STARRED, IMPORTANT, UNREAD, INBOX, SPAM, TRASH",
        parameters: {
          type: "OBJECT",
          properties: {
            message_ids: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "List of Gmail message IDs",
            },
            add_labels: { type: "ARRAY", items: { type: "STRING" }, description: "Labels to add" },
            remove_labels: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Labels to remove",
            },
          },
          required: ["message_ids"],
        },
      },
      {
        name: "send_email",
        description: "Send an email via Gmail",
        parameters: {
          type: "OBJECT",
          properties: {
            to: { type: "STRING", description: "Recipient email address" },
            subject: { type: "STRING", description: "Email subject" },
            body: { type: "STRING", description: "Email body text" },
          },
          required: ["to", "subject", "body"],
        },
      },
      {
        name: "get_gmail_labels",
        description: "List all Gmail labels/folders",
        parameters: { type: "OBJECT", properties: {} },
      },
      // --- GitHub ---
      {
        name: "github_repo_info",
        description: "Get info about a GitHub repository (issues, PRs, status, commits)",
        parameters: {
          type: "OBJECT",
          properties: {
            repo: { type: "STRING", description: "Repository in owner/name format" },
            action: { type: "STRING", description: "What to fetch: issues, prs, status, commits" },
          },
          required: ["repo", "action"],
        },
      },
      {
        name: "github_create_issue",
        description: "Create a GitHub issue on a repository",
        parameters: {
          type: "OBJECT",
          properties: {
            repo: { type: "STRING", description: "Repository in owner/name format" },
            title: { type: "STRING", description: "Issue title" },
            body: { type: "STRING", description: "Issue body/description" },
            labels: { type: "ARRAY", items: { type: "STRING" }, description: "Labels to apply" },
          },
          required: ["repo", "title"],
        },
      },
      // --- Web Research ---
      {
        name: "web_search",
        description: "Search the web for current information",
        parameters: {
          type: "OBJECT",
          properties: {
            query: { type: "STRING", description: "Search query" },
          },
          required: ["query"],
        },
      },
      {
        name: "web_fetch",
        description: "Fetch content from a URL and return readable text",
        parameters: {
          type: "OBJECT",
          properties: {
            url: { type: "STRING", description: "The URL to fetch" },
            extract: { type: "STRING", description: "What to extract: text, links, or all" },
          },
          required: ["url"],
        },
      },
      {
        name: "web_scrape",
        description: "Scrape structured data from a webpage (text, links, headings, code, tables)",
        parameters: {
          type: "OBJECT",
          properties: {
            url: { type: "STRING", description: "URL to scrape" },
            extract: {
              type: "STRING",
              description: "What to extract: text, links, headings, code, tables, all",
            },
            selector: { type: "STRING", description: "CSS selector to target specific elements" },
          },
          required: ["url"],
        },
      },
      {
        name: "research_task",
        description:
          "Research a topic before executing — searches web, fetches docs, returns synthesis",
        parameters: {
          type: "OBJECT",
          properties: {
            topic: { type: "STRING", description: "What to research" },
            depth: { type: "STRING", description: "Research depth: quick, medium, deep" },
          },
          required: ["topic"],
        },
      },
      // --- File Operations ---
      {
        name: "file_read",
        description: "Read contents of a file on the server",
        parameters: {
          type: "OBJECT",
          properties: {
            path: { type: "STRING", description: "Absolute path to file" },
            lines: { type: "NUMBER", description: "Max lines to read" },
            offset: { type: "NUMBER", description: "Start from this line number" },
          },
          required: ["path"],
        },
      },
      {
        name: "file_write",
        description: "Write or append to a file on the server",
        parameters: {
          type: "OBJECT",
          properties: {
            path: { type: "STRING", description: "Absolute path to file" },
            content: { type: "STRING", description: "Content to write" },
            mode: { type: "STRING", description: "Write mode: write or append" },
          },
          required: ["path", "content"],
        },
      },
      {
        name: "file_edit",
        description: "Edit a file by finding and replacing a specific string",
        parameters: {
          type: "OBJECT",
          properties: {
            path: { type: "STRING", description: "Absolute path to file" },
            old_string: { type: "STRING", description: "The exact string to find" },
            new_string: { type: "STRING", description: "The replacement string" },
            replace_all: { type: "BOOLEAN", description: "Replace all occurrences" },
          },
          required: ["path", "old_string", "new_string"],
        },
      },
      {
        name: "glob_files",
        description: "Find files matching a glob pattern",
        parameters: {
          type: "OBJECT",
          properties: {
            pattern: { type: "STRING", description: "Glob pattern (e.g. **/*.py)" },
            path: { type: "STRING", description: "Root directory to search in" },
            max_results: { type: "NUMBER", description: "Max files to return" },
          },
          required: ["pattern"],
        },
      },
      {
        name: "grep_search",
        description: "Search file contents using regex patterns across a codebase",
        parameters: {
          type: "OBJECT",
          properties: {
            pattern: { type: "STRING", description: "Regex pattern to search for" },
            path: { type: "STRING", description: "File or directory to search in" },
            file_pattern: { type: "STRING", description: "Filter files by glob" },
            max_results: { type: "NUMBER", description: "Max matches to return" },
            context_lines: { type: "NUMBER", description: "Lines of context around matches" },
          },
          required: ["pattern"],
        },
      },
      // --- Shell & System ---
      {
        name: "shell_execute",
        description: "Execute a shell command on the server (sandboxed to safe commands)",
        parameters: {
          type: "OBJECT",
          properties: {
            command: { type: "STRING", description: "The shell command to run" },
            cwd: { type: "STRING", description: "Working directory" },
            timeout: { type: "NUMBER", description: "Timeout in seconds" },
          },
          required: ["command"],
        },
      },
      {
        name: "git_operations",
        description:
          "Perform git operations: status, add, commit, push, pull, branch, log, diff, clone, checkout",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Git action: status, add, commit, push, pull, branch, log, diff, clone, checkout",
            },
            args: { type: "STRING", description: "Additional arguments" },
            files: { type: "ARRAY", items: { type: "STRING" }, description: "Files to add" },
            repo_path: { type: "STRING", description: "Path to git repo" },
          },
          required: ["action"],
        },
      },
      {
        name: "install_package",
        description: "Install a package or tool (npm, pip, apt, binary)",
        parameters: {
          type: "OBJECT",
          properties: {
            name: { type: "STRING", description: "Package name" },
            manager: { type: "STRING", description: "Package manager: npm, pip, apt, binary" },
            global_install: { type: "BOOLEAN", description: "Install globally" },
          },
          required: ["name", "manager"],
        },
      },
      {
        name: "process_manage",
        description: "Manage running processes: list, kill, check ports, show top resource users",
        parameters: {
          type: "OBJECT",
          properties: {
            action: { type: "STRING", description: "Action: list, kill, check_port, top" },
            target: { type: "STRING", description: "PID, process name, or port number" },
            signal: { type: "STRING", description: "Signal for kill: TERM, KILL, HUP" },
          },
          required: ["action"],
        },
      },
      // --- Deployment ---
      {
        name: "vercel_deploy",
        description: "Deploy a project to Vercel or manage deployments",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Vercel action: deploy, list, env-set, status, logs",
            },
            project_path: { type: "STRING", description: "Path to project to deploy" },
            production: { type: "BOOLEAN", description: "Deploy to production" },
            project_name: { type: "STRING", description: "Vercel project name" },
            env_key: { type: "STRING", description: "Environment variable key" },
            env_value: { type: "STRING", description: "Environment variable value" },
          },
          required: ["action"],
        },
      },
      // --- Compute Tools ---
      {
        name: "compute_math",
        description:
          "Evaluate mathematical expressions precisely (arithmetic, trig, log, factorial, etc.)",
        parameters: {
          type: "OBJECT",
          properties: {
            expression: {
              type: "STRING",
              description: "Math expression (e.g. 2**64 - 1, math.factorial(20))",
            },
            precision: { type: "NUMBER", description: "Decimal places for float results" },
          },
          required: ["expression"],
        },
      },
      {
        name: "compute_stats",
        description: "Calculate statistics: mean, median, mode, std dev, variance, percentiles",
        parameters: {
          type: "OBJECT",
          properties: {
            data: { type: "ARRAY", items: { type: "NUMBER" }, description: "List of numbers" },
            percentiles: {
              type: "ARRAY",
              items: { type: "NUMBER" },
              description: "Percentiles to calculate",
            },
          },
          required: ["data"],
        },
      },
      {
        name: "compute_sort",
        description: "Sort a list of numbers or strings using O(n log n) algorithms",
        parameters: {
          type: "OBJECT",
          properties: {
            data: { type: "ARRAY", items: { type: "STRING" }, description: "List to sort" },
            reverse: { type: "BOOLEAN", description: "Sort descending" },
            algorithm: {
              type: "STRING",
              description: "Algorithm: auto, mergesort, heapsort, quicksort, timsort",
            },
            key: { type: "STRING", description: "For dicts: key to sort by" },
          },
          required: ["data"],
        },
      },
      {
        name: "compute_search",
        description: "Search/filter data using binary search, linear scan, or regex",
        parameters: {
          type: "OBJECT",
          properties: {
            data: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Data to search through",
            },
            target: { type: "STRING", description: "Value to find" },
            method: { type: "STRING", description: "Search method: binary, linear, filter, regex" },
            condition: { type: "STRING", description: "For filter: Python expression using x" },
          },
          required: ["data"],
        },
      },
      {
        name: "compute_matrix",
        description:
          "Matrix operations: multiply, transpose, determinant, inverse, eigenvalues, solve",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description:
                "Operation: multiply, transpose, determinant, inverse, eigenvalues, solve",
            },
            matrix_a: {
              type: "ARRAY",
              items: { type: "ARRAY", items: { type: "NUMBER" } },
              description: "First matrix (2D array)",
            },
            matrix_b: {
              type: "ARRAY",
              items: { type: "ARRAY", items: { type: "NUMBER" } },
              description: "Second matrix or vector",
            },
          },
          required: ["action", "matrix_a"],
        },
      },
      {
        name: "compute_prime",
        description:
          "Prime number operations: factorize, primality test, generate primes, find nth prime",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "What to compute: factorize, is_prime, generate, nth_prime",
            },
            n: { type: "NUMBER", description: "The number to test/factorize" },
            limit: { type: "NUMBER", description: "Upper bound for generate action" },
          },
          required: ["action", "n"],
        },
      },
      {
        name: "compute_hash",
        description: "Compute cryptographic hashes: SHA-256, SHA-512, MD5, BLAKE2",
        parameters: {
          type: "OBJECT",
          properties: {
            data: { type: "STRING", description: "String to hash" },
            file_path: { type: "STRING", description: "Hash a file instead" },
            algorithm: {
              type: "STRING",
              description: "Hash algorithm: sha256, sha512, md5, blake2b, sha1",
            },
          },
        },
      },
      {
        name: "compute_convert",
        description:
          "Unit and base conversions: number bases, temperatures, distances, data sizes, timestamps",
        parameters: {
          type: "OBJECT",
          properties: {
            value: { type: "STRING", description: "Value to convert" },
            from_unit: { type: "STRING", description: "Source unit/base" },
            to_unit: { type: "STRING", description: "Target unit/base" },
          },
          required: ["value", "from_unit", "to_unit"],
        },
      },
      // --- Communication & Integrations ---
      {
        name: "send_slack_message",
        description: "Send a message to a Slack channel",
        parameters: {
          type: "OBJECT",
          properties: {
            message: { type: "STRING", description: "The message to send" },
            channel: { type: "STRING", description: "Channel ID" },
          },
          required: ["message"],
        },
      },
      {
        name: "manage_reactions",
        description: "Manage auto-reaction rules (list, add, update, delete, get trigger history)",
        parameters: {
          type: "OBJECT",
          properties: {
            action: { type: "STRING", description: "Action: list, add, update, delete, triggers" },
            rule_id: { type: "STRING", description: "Rule ID for update/delete" },
            rule_data: { type: "OBJECT", description: "Rule fields for add/update" },
          },
          required: ["action"],
        },
      },
      // --- Security ---
      {
        name: "security_scan",
        description: "Run an OXO security scan against a target (IP, domain, or URL)",
        parameters: {
          type: "OBJECT",
          properties: {
            target: { type: "STRING", description: "Target to scan: IP, domain, or URL" },
            scan_type: { type: "STRING", description: "Scan profile: quick, full, web" },
            agents: {
              type: "ARRAY",
              items: { type: "STRING" },
              description: "Override: explicit list of OXO agent keys",
            },
          },
          required: ["target"],
        },
      },
      // --- Prediction Markets ---
      {
        name: "prediction_market",
        description: "Query Polymarket prediction markets — search, get details, list events",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: search, get_market, list_markets, list_events",
            },
            query: { type: "STRING", description: "Search query" },
            market_id: { type: "STRING", description: "Market ID or slug" },
            tag: { type: "STRING", description: "Event tag filter" },
            limit: { type: "NUMBER", description: "Max results to return" },
          },
          required: ["action"],
        },
      },
      // --- Environment ---
      {
        name: "env_manage",
        description: "Manage environment variables and .env files",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: get, set, list, load_dotenv, save_dotenv",
            },
            key: { type: "STRING", description: "Env var name" },
            value: { type: "STRING", description: "Value to set" },
            filter: { type: "STRING", description: "Filter pattern for list" },
            env_file: { type: "STRING", description: "Path to .env file" },
          },
          required: ["action"],
        },
      },
      // --- Job Approval ---
      {
        name: "approve_job",
        description: "Approve a job that is in pr_ready status for execution",
        parameters: {
          type: "OBJECT",
          properties: {
            job_id: { type: "STRING", description: "The job ID to approve" },
          },
          required: ["job_id"],
        },
      },
      // --- Reflexion (Agency Learning) ---
      {
        name: "get_reflections",
        description:
          "Get past job reflections — the agency's learning memory. Use to check what worked/failed before.",
        parameters: {
          type: "OBJECT",
          properties: {
            action: {
              type: "STRING",
              description: "Action: stats (summary), list (recent), search (find similar)",
            },
            task: {
              type: "STRING",
              description: "Task description to search for (for search action)",
            },
            project: { type: "STRING", description: "Filter by project name" },
            limit: { type: "NUMBER", description: "Max results" },
          },
          required: ["action"],
        },
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Tool dispatcher — maps function names to gateway API calls
// ---------------------------------------------------------------------------

async function executeTool(
  env: Env,
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  switch (name) {
    case "list_jobs":
      return (
        await gatewayFetch(env, `/api/jobs${args.status ? `?status=${args.status}` : ""}`)
      ).json();
    case "create_job":
      return (
        await gatewayFetch(env, "/api/job/create", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "get_job":
      return (await gatewayFetch(env, `/api/job/${args.job_id}`)).json();
    case "kill_job":
      return (await gatewayFetch(env, `/api/jobs/${args.job_id}/kill`, { method: "POST" })).json();
    case "get_cost_summary":
      return (await gatewayFetch(env, "/api/costs/summary")).json();
    case "get_agency_status":
      return (await gatewayFetch(env, "/api/dashboard/summary")).json();
    case "list_proposals":
      return (await gatewayFetch(env, "/api/proposals")).json();
    case "create_proposal":
      return (
        await gatewayFetch(env, "/api/proposal/create", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "search_memory":
      return (
        await gatewayFetch(
          env,
          `/api/memories?limit=${args.limit || 10}${args.tag ? `&tag=${args.tag}` : ""}`,
        )
      ).json();
    case "save_memory":
      return (
        await gatewayFetch(env, "/api/memory/add", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "get_events":
      return (await gatewayFetch(env, `/api/events?limit=${args.limit || 20}`)).json();
    case "list_agents":
      return (await gatewayFetch(env, "/api/agents")).json();
    case "get_runner_status":
      return (await gatewayFetch(env, "/api/runner/status")).json();
    case "spawn_agent":
      return (
        await gatewayFetch(env, "/api/agents/spawn", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    case "send_chat_to_gateway":
      return (
        await gatewayFetch(env, "/api/chat", {
          method: "POST",
          body: JSON.stringify({ content: args.message, agent_id: args.agent_id }),
        })
      ).json();
    case "get_gmail_inbox":
      return (await gatewayFetch(env, `/api/gmail/inbox?limit=${args.limit || 10}`)).json();
    case "get_calendar_today":
      return (await gatewayFetch(env, "/api/calendar/today")).json();
    case "create_calendar_event":
      return (
        await gatewayFetch(env, "/api/calendar/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            summary: args.summary,
            start: args.start,
            end: args.end,
            location: args.location || "",
            description: args.description || "",
          }),
        })
      ).json();
    case "get_calendar_upcoming":
      return (await gatewayFetch(env, `/api/calendar/upcoming?days=${args.days || 7}`)).json();
    case "list_calendars":
      return (await gatewayFetch(env, "/api/calendar/list")).json();
    case "trash_emails":
      return (
        await gatewayFetch(env, "/api/gmail/trash", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_ids: args.message_ids }),
        })
      ).json();
    case "label_emails":
      return (
        await gatewayFetch(env, "/api/gmail/label", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message_ids: args.message_ids,
            add_labels: args.add_labels || [],
            remove_labels: args.remove_labels || [],
          }),
        })
      ).json();
    case "send_email":
      return (
        await gatewayFetch(env, "/api/gmail/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ to: args.to, subject: args.subject, body: args.body }),
        })
      ).json();
    case "get_gmail_labels":
      return (await gatewayFetch(env, "/api/gmail/labels")).json();
    // --- GitHub ---
    case "github_repo_info":
      return (
        await gatewayFetch(env, "/api/github/repo-info", {
          method: "POST",
          body: JSON.stringify({ repo: args.repo, action: args.action }),
        })
      ).json();
    case "github_create_issue":
      return (
        await gatewayFetch(env, "/api/github/create-issue", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    // --- Web Research ---
    case "web_search":
      return (
        await gatewayFetch(env, "/api/web/search", {
          method: "POST",
          body: JSON.stringify({ query: args.query }),
        })
      ).json();
    case "web_fetch":
      return (
        await gatewayFetch(env, "/api/web/fetch", {
          method: "POST",
          body: JSON.stringify({ url: args.url, extract: args.extract }),
        })
      ).json();
    case "web_scrape":
      return (
        await gatewayFetch(env, "/api/web/scrape", {
          method: "POST",
          body: JSON.stringify({ url: args.url, extract: args.extract, selector: args.selector }),
        })
      ).json();
    case "research_task":
      return (
        await gatewayFetch(env, "/api/research", {
          method: "POST",
          body: JSON.stringify({ topic: args.topic, depth: args.depth }),
        })
      ).json();
    // --- File Operations ---
    case "file_read":
      return (
        await gatewayFetch(env, "/api/file/read", {
          method: "POST",
          body: JSON.stringify({ path: args.path, lines: args.lines, offset: args.offset }),
        })
      ).json();
    case "file_write":
      return (
        await gatewayFetch(env, "/api/file/write", {
          method: "POST",
          body: JSON.stringify({ path: args.path, content: args.content, mode: args.mode }),
        })
      ).json();
    case "file_edit":
      return (
        await gatewayFetch(env, "/api/file/edit", {
          method: "POST",
          body: JSON.stringify({
            path: args.path,
            old_string: args.old_string,
            new_string: args.new_string,
            replace_all: args.replace_all,
          }),
        })
      ).json();
    case "glob_files":
      return (
        await gatewayFetch(env, "/api/file/glob", {
          method: "POST",
          body: JSON.stringify({
            pattern: args.pattern,
            path: args.path,
            max_results: args.max_results,
          }),
        })
      ).json();
    case "grep_search":
      return (
        await gatewayFetch(env, "/api/file/grep", {
          method: "POST",
          body: JSON.stringify({
            pattern: args.pattern,
            path: args.path,
            file_pattern: args.file_pattern,
            max_results: args.max_results,
            context_lines: args.context_lines,
          }),
        })
      ).json();
    // --- Shell & System ---
    case "shell_execute":
      return (
        await gatewayFetch(env, "/api/shell/execute", {
          method: "POST",
          body: JSON.stringify({ command: args.command, cwd: args.cwd, timeout: args.timeout }),
        })
      ).json();
    case "git_operations":
      return (
        await gatewayFetch(env, "/api/git", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            args: args.args,
            files: args.files,
            repo_path: args.repo_path,
          }),
        })
      ).json();
    case "install_package":
      return (
        await gatewayFetch(env, "/api/install", {
          method: "POST",
          body: JSON.stringify({
            name: args.name,
            manager: args.manager,
            global_install: args.global_install,
          }),
        })
      ).json();
    case "process_manage":
      return (
        await gatewayFetch(env, "/api/process", {
          method: "POST",
          body: JSON.stringify({ action: args.action, target: args.target, signal: args.signal }),
        })
      ).json();
    // --- Deployment ---
    case "vercel_deploy":
      return (
        await gatewayFetch(env, "/api/vercel", {
          method: "POST",
          body: JSON.stringify(args),
        })
      ).json();
    // --- Compute ---
    case "compute_math":
      return (
        await gatewayFetch(env, "/api/compute/math", {
          method: "POST",
          body: JSON.stringify({ expression: args.expression, precision: args.precision }),
        })
      ).json();
    case "compute_stats":
      return (
        await gatewayFetch(env, "/api/compute/stats", {
          method: "POST",
          body: JSON.stringify({ data: args.data, percentiles: args.percentiles }),
        })
      ).json();
    case "compute_sort":
      return (
        await gatewayFetch(env, "/api/compute/sort", {
          method: "POST",
          body: JSON.stringify({
            data: args.data,
            reverse: args.reverse,
            algorithm: args.algorithm,
            key: args.key,
          }),
        })
      ).json();
    case "compute_search":
      return (
        await gatewayFetch(env, "/api/compute/search", {
          method: "POST",
          body: JSON.stringify({
            data: args.data,
            target: args.target,
            method: args.method,
            condition: args.condition,
          }),
        })
      ).json();
    case "compute_matrix":
      return (
        await gatewayFetch(env, "/api/compute/matrix", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            matrix_a: args.matrix_a,
            matrix_b: args.matrix_b,
          }),
        })
      ).json();
    case "compute_prime":
      return (
        await gatewayFetch(env, "/api/compute/prime", {
          method: "POST",
          body: JSON.stringify({ action: args.action, n: args.n, limit: args.limit }),
        })
      ).json();
    case "compute_hash":
      return (
        await gatewayFetch(env, "/api/compute/hash", {
          method: "POST",
          body: JSON.stringify({
            data: args.data,
            file_path: args.file_path,
            algorithm: args.algorithm,
          }),
        })
      ).json();
    case "compute_convert":
      return (
        await gatewayFetch(env, "/api/compute/convert", {
          method: "POST",
          body: JSON.stringify({
            value: args.value,
            from_unit: args.from_unit,
            to_unit: args.to_unit,
          }),
        })
      ).json();
    // --- Communication ---
    case "send_slack_message":
      return (
        await gatewayFetch(env, "/api/slack/send", {
          method: "POST",
          body: JSON.stringify({ message: args.message, channel: args.channel }),
        })
      ).json();
    case "manage_reactions":
      return (
        await gatewayFetch(env, "/api/reactions/manage", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            rule_id: args.rule_id,
            rule_data: args.rule_data,
          }),
        })
      ).json();
    // --- Security ---
    case "security_scan":
      return (
        await gatewayFetch(env, "/api/security/scan", {
          method: "POST",
          body: JSON.stringify({
            target: args.target,
            scan_type: args.scan_type,
            agents: args.agents,
          }),
        })
      ).json();
    // --- Prediction Markets ---
    case "prediction_market":
      return (
        await gatewayFetch(env, "/api/prediction", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            query: args.query,
            market_id: args.market_id,
            tag: args.tag,
            limit: args.limit,
          }),
        })
      ).json();
    // --- Environment ---
    case "env_manage":
      return (
        await gatewayFetch(env, "/api/env", {
          method: "POST",
          body: JSON.stringify({
            action: args.action,
            key: args.key,
            value: args.value,
            filter: args.filter,
            env_file: args.env_file,
          }),
        })
      ).json();
    // --- Job Approval ---
    case "approve_job":
      return (
        await gatewayFetch(env, `/api/job/${args.job_id}/approve`, { method: "POST" })
      ).json();
    case "get_reflections":
      if (args.action === "stats") {
        return (await gatewayFetch(env, "/api/reflections/stats")).json();
      } else if (args.action === "search") {
        return (
          await gatewayFetch(env, "/api/reflections/search", {
            method: "POST",
            body: JSON.stringify({ task: args.task, project: args.project, limit: args.limit }),
          })
        ).json();
      } else {
        return (
          await gatewayFetch(
            env,
            `/api/reflections?limit=${args.limit || 10}${args.project ? `&project=${args.project}` : ""}`,
          )
        ).json();
      }
    default:
      return { error: `Unknown tool: ${name}` };
  }
}

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
// System prompt for the personal assistant
// ---------------------------------------------------------------------------

const SYSTEM_PROMPT = `You are Overseer — Miles's personal AI agency assistant, running on Gemini 2.5 Flash at the Cloudflare edge.

CAPABILITIES: You have live access to the OpenClaw agency via 47 function calls. You can:
- **Jobs & Proposals**: Create, list, kill, approve, and monitor autonomous jobs and proposals
- **GitHub**: Get repo info (issues, PRs, commits), create issues
- **Web Research**: Search the web, fetch/scrape URLs, deep research topics
- **File Operations**: Read, write, edit files; glob search; grep across codebases
- **Shell & System**: Execute commands, manage processes, check ports, install packages
- **Git**: Full git operations (status, commit, push, pull, branch, diff, clone, checkout)
- **Deployment**: Vercel deploy, env vars, status, logs
- **Compute**: Math expressions, statistics, sorting, search, matrix ops, primes, hashing, unit conversion
- **Communication**: Send Slack messages, manage auto-reaction rules
- **Security**: Run OXO security scans (Nmap, Nuclei, ZAP)
- **Predictions**: Query Polymarket prediction markets
- **Environment**: Manage env vars and .env files
- **Memory**: Search and save persistent memory
- **Agents**: List, spawn, and monitor agents
- **Personal**: Gmail inbox, Google Calendar
- **Costs & Budget**: Real-time spending and budget status
- **Delegation**: Route complex tasks to specialist agents (coder, hacker, database)

PERSONALITY: Direct, concise, action-first. Miles is busy — get to the point.
No fluff, no celebrations, no unnecessary markdown. If a tool call is needed, call it immediately without narrating the intention.

PROJECTS: OpenClaw (AI agency platform), Delhi Palace (restaurant site), Barber CRM, PrestressCalc (engineering), Concrete Canoe (university project).

ROUTING:
- When Miles says "create a job to X", call create_job immediately.
- When Miles asks about costs/spending/budget, call get_cost_summary.
- When Miles says "what's running" or "status", call get_runner_status or get_agency_status.
- When Miles asks about agents, call list_agents.
- When Miles asks about email/inbox, call get_gmail_inbox. To clean up, use trash_emails. To organize, use label_emails.
- When Miles asks about calendar/schedule, call get_calendar_today or get_calendar_upcoming.
- To create events or plan the day, use create_calendar_event. Always use Arizona time (MST).
- When asked to send email, use send_email. Always confirm recipient before sending.
- For email cleanup: read inbox first, identify junk/spam, then trash them in one call.
- When Miles asks about events/activity, call get_events.
- When Miles asks about a GitHub repo, call github_repo_info.
- When Miles asks to search the web or look something up, call web_search or research_task.
- When Miles asks to read/edit/write a file, use file_read/file_edit/file_write.
- When Miles asks to run a command, use shell_execute.
- When Miles asks about git status/commits/push, use git_operations.
- When Miles asks to deploy, use vercel_deploy.
- When Miles asks to calculate something, use compute_math or compute_stats.
- When Miles asks about predictions/markets, use prediction_market.
- When Miles asks to send a Slack message, use send_slack_message.
- When Miles asks about security scanning, use security_scan.
- For complex coding/security/database questions, use send_chat_to_gateway to delegate to a specialist.`;

// ---------------------------------------------------------------------------
// POST /api/chat — Gemini-powered chat with tool calling + KV sessions
// ---------------------------------------------------------------------------
app.post("/api/chat", async (c) => {
  const body = await c.req.json<ChatRequest>();
  const { message, sessionKey } = body;

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

  // Build Gemini conversation history (last 20 messages for context)
  const recentMessages = session.messages.slice(-20);
  const geminiContents: Array<Record<string, unknown>> = recentMessages.map((m) => ({
    role: m.role === "assistant" ? "model" : "user",
    parts: [{ text: m.content }],
  }));

  const geminiModel = c.env.GEMINI_MODEL || "gemini-2.5-flash-lite";
  // Note: Free tier limits are 10 req/min, 20 req/day for flash-lite.
  // Tool calls consume 2 requests (call + response). Enable billing for production use.
  const geminiUrl = `https://generativelanguage.googleapis.com/v1beta/models/${geminiModel}:generateContent?key=${c.env.GEMINI_API_KEY}`;

  let reply = "";
  let toolUsed: string | null = null;
  const MAX_TOOL_ITERATIONS = 3;

  try {
    for (let iteration = 0; iteration < MAX_TOOL_ITERATIONS; iteration++) {
      const requestBody: Record<string, unknown> = {
        contents: geminiContents,
        systemInstruction: {
          parts: [{ text: SYSTEM_PROMPT }],
        },
        generationConfig: {
          maxOutputTokens: 4096,
          temperature: 0.7,
          thinkingConfig: { thinkingBudget: 0 },
        },
        tools: OPENCLAW_TOOLS,
      };

      const geminiResp = await fetch(geminiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      if (!geminiResp.ok) {
        const errText = await geminiResp.text();
        return c.json({ error: "gemini_error", status: geminiResp.status, detail: errText }, 502);
      }

      const geminiData = (await geminiResp.json()) as Record<string, unknown>;
      const candidates = geminiData.candidates as Array<Record<string, unknown>> | undefined;

      if (!candidates || candidates.length === 0) {
        reply = "No response from Gemini.";
        break;
      }

      const content = candidates[0].content as Record<string, unknown> | undefined;
      const parts = content?.parts as Array<Record<string, unknown>> | undefined;

      if (!parts || parts.length === 0) {
        reply = "No response from Gemini.";
        break;
      }

      // Check if the model wants to call a function
      const functionCallPart = parts.find((p) => p.functionCall);

      if (functionCallPart) {
        const functionCall = functionCallPart.functionCall as {
          name: string;
          args: Record<string, unknown>;
        };
        toolUsed = functionCall.name;

        // Execute the tool
        let toolResult: unknown;
        try {
          toolResult = await executeTool(c.env, functionCall.name, functionCall.args || {});
        } catch (err: unknown) {
          const errMsg = err instanceof Error ? err.message : String(err);
          toolResult = { error: errMsg };
        }

        // Append model's function call turn
        geminiContents.push({
          role: "model",
          parts: [{ functionCall: { name: functionCall.name, args: functionCall.args || {} } }],
        });

        // Append function response turn (Gemini expects response as an object with content)
        const responsePayload =
          typeof toolResult === "object" && toolResult !== null
            ? toolResult
            : { result: toolResult };
        geminiContents.push({
          role: "function",
          parts: [{ functionResponse: { name: functionCall.name, response: responsePayload } }],
        });

        // Continue the loop — Gemini will process the tool result and respond
        continue;
      }

      // No function call — extract text reply (check ALL parts for text)
      for (const p of parts) {
        if (p.text) {
          reply = p.text as string;
          break;
        }
      }
      break;
    }

    // If no text reply after tool calls, format the raw tool result as fallback
    if (!reply && toolUsed) {
      const lastFnResponse = geminiContents
        .filter((c) => (c.parts as Array<Record<string, unknown>>)?.[0]?.functionResponse)
        .pop();
      if (lastFnResponse) {
        const fnParts = lastFnResponse.parts as Array<Record<string, unknown>>;
        const fnResp = fnParts[0].functionResponse as Record<string, unknown>;
        const data = fnResp.response;
        try {
          reply = JSON.stringify(data, null, 2).slice(0, 3000);
        } catch {
          reply = `Tool ${toolUsed} executed.`;
        }
      } else {
        reply = `Tool ${toolUsed} executed.`;
      }
    } else if (!reply) {
      reply = "No response generated.";
    }
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return c.json({ error: "gemini_fetch_failed", detail: errMsg }, 502);
  }

  // Append assistant response to local session
  session.messages.push({
    role: "assistant",
    content: reply,
    timestamp: new Date().toISOString(),
  });

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
    response: reply,
    model: geminiModel,
    tool_used: toolUsed,
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
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,viewport-fit=cover">
<title>Overseer — OpenClaw</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@300;400;500;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#08090c;--surface:#0f1116;--surface-2:#151820;--surface-3:#1a1e28;
  --border:#1e2230;--border-active:#2a3045;
  --text:#d4d8e8;--text-bright:#eef0f8;--text-muted:#6a7094;--text-dim:#3d4260;
  --amber:#e8a832;--amber-dim:#e8a83225;--amber-glow:#e8a83215;
  --red:#e84545;--red-dim:#e8454520;
  --green:#45c882;--green-dim:#45c88220;
  --blue:#4588e8;--blue-dim:#4588e820;
  --purple:#8b5cf6;--purple-dim:#8b5cf620;
  --cyan:#22d3ee;--cyan-dim:#22d3ee20;
  --font-mono:'JetBrains Mono',monospace;
  --font-body:'Outfit',sans-serif;
  --radius:10px;
}
html,body{height:100%;font-family:var(--font-body);-webkit-font-smoothing:antialiased}
body{background:var(--bg);color:var(--text);display:flex;flex-direction:column;overflow:hidden}

/* Noise texture overlay */
body::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
  background-size:128px 128px;
}

/* Header */
.header{
  padding:0 20px;height:56px;background:var(--surface);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:14px;flex-shrink:0;
  position:relative;z-index:10;
}
.header::after{
  content:'';position:absolute;bottom:-1px;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--amber-dim),transparent);
}
.logo-mark{
  width:34px;height:34px;border-radius:8px;position:relative;
  background:linear-gradient(135deg,var(--amber),#c88520);
  display:flex;align-items:center;justify-content:center;
  font-family:var(--font-mono);font-weight:700;font-size:15px;color:var(--bg);
  box-shadow:0 0 20px var(--amber-dim);
}
.logo-mark::after{
  content:'';position:absolute;inset:-2px;border-radius:10px;
  background:linear-gradient(135deg,var(--amber),transparent);
  opacity:.25;z-index:-1;
}
.header-title{
  font-family:var(--font-mono);font-size:14px;font-weight:600;
  color:var(--text-bright);letter-spacing:-.3px;
}
.header-title span{color:var(--text-muted);font-weight:400}
.header-right{margin-left:auto;display:flex;align-items:center;gap:12px}
.session-info{
  font-family:var(--font-mono);font-size:10px;color:var(--text-dim);
  display:flex;align-items:center;gap:6px;
}
.session-info .count{color:var(--text-muted)}
.status-pill{
  display:flex;align-items:center;gap:6px;
  padding:4px 10px 4px 8px;border-radius:20px;
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  text-transform:uppercase;letter-spacing:.5px;
  background:var(--green-dim);color:var(--green);
  border:1px solid transparent;
  transition:all .3s;
}
.status-pill.offline{background:var(--red-dim);color:var(--red)}
.status-pill.degraded{background:#d2992220;color:#d29922}
.status-pill .dot{
  width:6px;height:6px;border-radius:50%;background:currentColor;
  animation:pulse 2s ease-in-out infinite;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* Chat */
.chat{
  flex:1;overflow-y:auto;padding:24px 20px;
  display:flex;flex-direction:column;gap:4px;
  position:relative;z-index:1;
  scroll-behavior:smooth;
}
.chat::-webkit-scrollbar{width:5px}
.chat::-webkit-scrollbar-track{background:transparent}
.chat::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.chat::-webkit-scrollbar-thumb:hover{background:var(--border-active)}

/* Messages */
.msg-group{display:flex;flex-direction:column;gap:2px;max-width:780px;width:100%}
.msg-group.user{align-self:flex-end}
.msg-group.bot{align-self:flex-start}
.msg-label{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  text-transform:uppercase;letter-spacing:.8px;
  padding:0 4px;margin-bottom:4px;margin-top:16px;
}
.msg-group.user .msg-label{color:var(--blue);text-align:right}
.msg-group.bot .msg-label{color:var(--amber)}

.msg{
  padding:14px 18px;line-height:1.65;font-size:14px;
  word-break:break-word;position:relative;
}
.msg-group.user .msg{
  background:var(--blue-dim);border:1px solid #4588e830;
  border-radius:var(--radius) var(--radius) 4px var(--radius);
  color:var(--text-bright);
}
.msg-group.bot .msg{
  background:var(--surface-2);border:1px solid var(--border);
  border-radius:var(--radius) var(--radius) var(--radius) 4px;
}

/* Tool badge */
.tool-badge{
  display:inline-flex;align-items:center;gap:5px;
  padding:3px 10px 3px 7px;border-radius:6px;
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  letter-spacing:.3px;text-transform:uppercase;
  margin-bottom:10px;
  animation:badgeFade .4s ease;
}
@keyframes badgeFade{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.tool-badge.jobs{background:var(--purple-dim);color:var(--purple);border:1px solid #8b5cf630}
.tool-badge.costs{background:var(--green-dim);color:var(--green);border:1px solid #45c88230}
.tool-badge.agents{background:var(--cyan-dim);color:var(--cyan);border:1px solid #22d3ee30}
.tool-badge.memory{background:var(--amber-dim);color:var(--amber);border:1px solid #e8a83230}
.tool-badge.github{background:#24292e;color:#e6edf3;border:1px solid #30363d}
.tool-badge.system{background:var(--surface-3);color:var(--text-muted);border:1px solid var(--border)}
.tool-badge .tool-icon{font-size:12px}

/* Markdown in messages */
.msg h1,.msg h2,.msg h3{color:var(--text-bright);margin:12px 0 6px;font-family:var(--font-body)}
.msg h1{font-size:18px} .msg h2{font-size:16px} .msg h3{font-size:14px;color:var(--amber)}
.msg p{margin:4px 0}
.msg strong{color:var(--text-bright);font-weight:600}
.msg em{color:var(--text-muted);font-style:italic}
.msg a{color:var(--amber);text-decoration:none;border-bottom:1px solid var(--amber-dim)}
.msg a:hover{border-color:var(--amber)}
.msg ul,.msg ol{margin:6px 0 6px 20px}
.msg li{margin:3px 0;line-height:1.5}
.msg li::marker{color:var(--text-dim)}
.msg blockquote{
  border-left:3px solid var(--amber);padding:6px 14px;margin:8px 0;
  background:var(--amber-glow);border-radius:0 6px 6px 0;
  color:var(--text-muted);font-style:italic;
}
.msg hr{border:none;border-top:1px solid var(--border);margin:12px 0}
.msg code{
  font-family:var(--font-mono);font-size:12px;
  background:#ffffff08;padding:2px 6px;border-radius:4px;
  color:var(--amber);border:1px solid #ffffff08;
}
.msg pre{
  background:var(--bg);border:1px solid var(--border);border-radius:8px;
  padding:14px 16px;overflow-x:auto;margin:10px 0;position:relative;
}
.msg pre code{
  background:none;padding:0;border:none;color:var(--text);
  font-size:12px;line-height:1.6;
}
.msg pre .lang-tag{
  position:absolute;top:6px;right:10px;
  font-family:var(--font-mono);font-size:9px;font-weight:600;
  color:var(--text-dim);text-transform:uppercase;letter-spacing:.5px;
}
.msg table{
  width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;
  font-family:var(--font-mono);
}
.msg th{
  text-align:left;padding:8px 12px;border-bottom:2px solid var(--border);
  color:var(--amber);font-weight:600;font-size:11px;
  text-transform:uppercase;letter-spacing:.5px;
}
.msg td{
  padding:7px 12px;border-bottom:1px solid var(--border);
  color:var(--text);
}
.msg tr:hover td{background:var(--surface-3)}

/* Typing indicator */
.typing{
  display:none;align-self:flex-start;max-width:780px;
  padding:14px 18px;background:var(--surface-2);
  border:1px solid var(--border);border-radius:var(--radius) var(--radius) var(--radius) 4px;
  gap:6px;align-items:center;margin-top:4px;
}
.typing.show{display:flex}
.typing-dots{display:flex;gap:4px;align-items:center}
.typing-dots span{
  width:6px;height:6px;background:var(--amber);border-radius:50%;
  animation:typeBounce .8s infinite alternate;opacity:.4;
}
.typing-dots span:nth-child(2){animation-delay:.15s}
.typing-dots span:nth-child(3){animation-delay:.3s}
@keyframes typeBounce{to{opacity:1;transform:translateY(-3px)}}
.typing-label{
  font-family:var(--font-mono);font-size:11px;color:var(--text-muted);
  margin-left:6px;
}

/* Input area */
.input-area{
  padding:16px 20px;background:var(--surface);
  border-top:1px solid var(--border);
  display:flex;gap:10px;flex-shrink:0;
  position:relative;z-index:10;
}
.input-area::before{
  content:'';position:absolute;top:-1px;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--amber-dim),transparent);
}
.input-wrap{
  flex:1;position:relative;display:flex;align-items:flex-end;
  background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);
  transition:border-color .2s,box-shadow .2s;
}
.input-wrap:focus-within{
  border-color:var(--amber);
  box-shadow:0 0 0 3px var(--amber-dim);
}
.input-wrap textarea{
  flex:1;background:transparent;border:none;
  padding:12px 14px;color:var(--text-bright);font-size:14px;
  font-family:var(--font-body);resize:none;outline:none;
  min-height:44px;max-height:160px;line-height:1.45;
}
.input-wrap textarea::placeholder{color:var(--text-dim)}
.send-btn{
  background:linear-gradient(135deg,var(--amber),#c88520);
  color:var(--bg);border:none;border-radius:var(--radius);
  padding:0 22px;height:44px;font-size:13px;font-weight:700;
  font-family:var(--font-mono);cursor:pointer;
  transition:all .2s;flex-shrink:0;
  text-transform:uppercase;letter-spacing:.5px;
}
.send-btn:hover{box-shadow:0 0 24px var(--amber-dim);transform:translateY(-1px)}
.send-btn:active{transform:translateY(0)}
.send-btn:disabled{opacity:.3;cursor:not-allowed;transform:none;box-shadow:none}

/* Welcome screen */
.welcome{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:80px 24px 40px;text-align:center;
  animation:welcomeFade .8s ease;
}
@keyframes welcomeFade{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.welcome-logo{
  width:64px;height:64px;border-radius:16px;margin-bottom:28px;
  background:linear-gradient(135deg,var(--amber),#c88520);
  display:flex;align-items:center;justify-content:center;
  font-family:var(--font-mono);font-weight:700;font-size:28px;color:var(--bg);
  box-shadow:0 0 60px var(--amber-dim),0 0 120px var(--amber-glow);
  position:relative;
}
.welcome-logo::before{
  content:'';position:absolute;inset:-4px;border-radius:20px;
  background:conic-gradient(from 0deg,var(--amber),transparent,var(--amber));
  opacity:.2;animation:logoSpin 8s linear infinite;
}
@keyframes logoSpin{to{transform:rotate(360deg)}}
.welcome h2{
  font-family:var(--font-mono);font-size:20px;font-weight:700;
  color:var(--text-bright);margin-bottom:10px;letter-spacing:-.3px;
}
.welcome p{
  font-size:14px;color:var(--text-muted);max-width:440px;line-height:1.6;
  margin-bottom:32px;
}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:520px}
.chip{
  background:var(--surface-2);border:1px solid var(--border);border-radius:8px;
  padding:10px 16px;font-size:12px;font-family:var(--font-mono);font-weight:500;
  cursor:pointer;transition:all .2s;color:var(--text);
  display:flex;align-items:center;gap:7px;
}
.chip:hover{border-color:var(--amber);color:var(--amber);background:var(--amber-dim)}
.chip .chip-icon{font-size:14px;opacity:.7}

/* Session bar */
.session-bar{
  padding:6px 20px;background:var(--bg);
  border-bottom:1px solid var(--border);
  font-family:var(--font-mono);font-size:10px;color:var(--text-dim);
  display:flex;align-items:center;gap:16px;flex-shrink:0;
}
.session-bar .sep{color:var(--border)}

/* Mobile */
@media(max-width:640px){
  .header{padding:0 14px;height:50px;gap:10px}
  .logo-mark{width:28px;height:28px;font-size:13px;border-radius:6px}
  .header-title{font-size:13px}
  .session-info{display:none}
  .chat{padding:16px 12px}
  .msg{padding:12px 14px;font-size:13px}
  .msg pre{padding:10px 12px}
  .input-area{padding:12px}
  .welcome{padding:50px 16px 30px}
  .welcome-logo{width:52px;height:52px;font-size:22px}
  .welcome h2{font-size:17px}
  .chips{gap:6px}
  .chip{padding:8px 12px;font-size:11px}
  .session-bar{padding:5px 14px;font-size:9px}
}
</style>
</head>
<body>

<div class="header">
  <div class="logo-mark">O</div>
  <div class="header-title">OVERSEER <span>/ personal assistant</span></div>
  <div class="header-right">
    <div class="session-info">
      <span id="sessionId">---</span>
      <span class="count" id="msgCount">0 msgs</span>
    </div>
    <div class="status-pill" id="statusPill">
      <span class="dot"></span>
      <span id="statusText">INIT</span>
    </div>
  </div>
</div>

<div class="session-bar" id="sessionBar">
  <span>MODEL: <span id="modelName">gemini-2.5-flash</span></span>
  <span class="sep">/</span>
  <span>SESSION: <span id="sessionDisplay">---</span></span>
  <span class="sep">/</span>
  <span>EDGE: cloudflare</span>
</div>

<div class="chat" id="chat">
  <div class="welcome" id="welcome">
    <div class="welcome-logo">O</div>
    <h2>OVERSEER</h2>
    <p>Your AI agency command interface. Connected to the OpenClaw gateway with 48 live tools — jobs, agents, costs, memory, deployments, and more.</p>
    <div class="chips">
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#9881;</span> Agency status</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#9733;</span> What's running?</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#36;</span> Cost summary</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#128218;</span> Search memory</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#128640;</span> Create a job</div>
      <div class="chip" onclick="sendChip(this)"><span class="chip-icon">&#128274;</span> List agents</div>
    </div>
  </div>
</div>

<div class="typing" id="typing">
  <div class="typing-dots"><span></span><span></span><span></span></div>
  <span class="typing-label" id="typingLabel">thinking...</span>
</div>

<div class="input-area">
  <div class="input-wrap">
    <textarea id="input" placeholder="Ask Overseer anything..." rows="1"></textarea>
  </div>
  <button class="send-btn" id="sendBtn" onclick="send()">SEND</button>
</div>

<script>
const $=id=>document.getElementById(id);
const chatEl=$('chat'),inputEl=$('input'),sendBtn=$('sendBtn');
const typingEl=$('typing'),welcomeEl=$('welcome');
const statusPill=$('statusPill'),statusText=$('statusText');
const typingLabel=$('typingLabel');
const sessionDisplay=$('sessionDisplay'),msgCountEl=$('msgCount'),sessionIdEl=$('sessionId');
const modelNameEl=$('modelName');

let sessionKey=localStorage.getItem('oc_session');
if(!sessionKey){sessionKey='web:'+crypto.randomUUID();localStorage.setItem('oc_session',sessionKey)}
sessionDisplay.textContent=sessionKey.slice(0,12)+'...';
sessionIdEl.textContent=sessionKey.slice(4,12);
let totalMsgs=0;

inputEl.addEventListener('input',()=>{
  inputEl.style.height='auto';
  inputEl.style.height=Math.min(inputEl.scrollHeight,160)+'px';
});
inputEl.addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}
});

function sendChip(el){inputEl.value=el.textContent.replace(/^[^\\w]+/,'').trim();send()}

function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function renderMd(text){
  // Code blocks with language tags
  text=text.replace(/\`\`\`(\\w*?)\\n([\\s\\S]*?)\`\`\`/g,(_,lang,code)=>{
    const tag=lang?'<span class="lang-tag">'+esc(lang)+'</span>':'';
    return '<pre>'+tag+'<code>'+esc(code.trim())+'</code></pre>';
  });
  // Inline code
  text=text.replace(/\`([^\`]+)\`/g,(_,c)=>'<code>'+esc(c)+'</code>');
  // Headers
  text=text.replace(/^### (.+)$/gm,'<h3>$1</h3>');
  text=text.replace(/^## (.+)$/gm,'<h2>$1</h2>');
  text=text.replace(/^# (.+)$/gm,'<h1>$1</h1>');
  // Bold & italic
  text=text.replace(/\\*\\*\\*(.+?)\\*\\*\\*/g,'<strong><em>$1</em></strong>');
  text=text.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');
  text=text.replace(/\\*(.+?)\\*/g,'<em>$1</em>');
  // Links
  text=text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  // Blockquotes
  text=text.replace(/^> (.+)$/gm,'<blockquote>$1</blockquote>');
  // Horizontal rules
  text=text.replace(/^---$/gm,'<hr>');
  // Unordered lists
  text=text.replace(/^[\\-\\*] (.+)$/gm,'<li>$1</li>');
  text=text.replace(/(<li>.*<\\/li>)/gs,m=>'<ul>'+m+'</ul>');
  text=text.replace(/<\\/ul>\\s*<ul>/g,'');
  // Ordered lists
  text=text.replace(/^\\d+\\. (.+)$/gm,'<li>$1</li>');
  // Tables
  text=text.replace(/^\\|(.+)\\|$/gm,(_,row)=>{
    const cells=row.split('|').map(c=>c.trim());
    return '<tr>'+cells.map(c=>'<td>'+c+'</td>').join('')+'</tr>';
  });
  text=text.replace(/(<tr>.*<\\/tr>)/gs,m=>{
    let rows=m;
    // Convert separator row to nothing, first row to th
    rows=rows.replace(/<tr><td>[-:\\s|]+<\\/td>(<td>[-:\\s|]+<\\/td>)*<\\/tr>/g,'');
    rows=rows.replace(/<tr>(.*?)<\\/tr>/,(_, r)=>'<thead><tr>'+r.replace(/<td>/g,'<th>').replace(/<\\/td>/g,'</th>')+'</tr></thead>');
    return '<table>'+rows+'</table>';
  });
  // Paragraphs (lines not already wrapped)
  text=text.replace(/^(?!<[hupoltbr])(\\S.+)$/gm,'<p>$1</p>');
  return text;
}

const TOOL_CATEGORIES={
  list_jobs:'jobs',create_job:'jobs',get_job:'jobs',kill_job:'jobs',approve_job:'jobs',
  get_cost_summary:'costs',
  get_agency_status:'system',get_runner_status:'system',get_events:'system',
  list_agents:'agents',spawn_agent:'agents',
  search_memory:'memory',save_memory:'memory',get_reflections:'memory',
  list_proposals:'jobs',create_proposal:'jobs',
  github_repo_info:'github',github_create_issue:'github',
  web_search:'system',web_fetch:'system',web_scrape:'system',research_task:'system',
  send_chat_to_gateway:'agents',
  get_gmail_inbox:'system',get_calendar_today:'system',create_calendar_event:'system',get_calendar_upcoming:'system',list_calendars:'system',trash_emails:'system',label_emails:'system',send_email:'system',get_gmail_labels:'system',
  shell_execute:'system',git_operations:'github',
  vercel_deploy:'system',
  file_read:'system',file_write:'system',file_edit:'system',
  glob_files:'system',grep_search:'system',
  compute_sort:'system',compute_stats:'system',compute_math:'system',
  compute_search:'system',compute_matrix:'system',compute_prime:'system',
  compute_hash:'system',compute_convert:'system',
  send_slack_message:'system',security_scan:'system',
  prediction_market:'system',env_manage:'system',
  process_manage:'system',install_package:'system',
};
const TOOL_ICONS={
  jobs:'&#9654;',costs:'&#36;',agents:'&#9881;',
  memory:'&#128218;',github:'&#128025;',system:'&#9881;',
};
const TOOL_LABELS={
  list_jobs:'JOBS',create_job:'CREATE JOB',get_job:'JOB',kill_job:'KILL JOB',
  approve_job:'APPROVE',get_cost_summary:'COSTS',get_agency_status:'STATUS',
  get_runner_status:'RUNNER',get_events:'EVENTS',list_agents:'AGENTS',
  spawn_agent:'SPAWN',search_memory:'MEMORY',save_memory:'SAVE MEM',
  get_reflections:'REFLECT',list_proposals:'PROPOSALS',create_proposal:'PROPOSAL',
  github_repo_info:'GITHUB',github_create_issue:'NEW ISSUE',
  web_search:'SEARCH',web_fetch:'FETCH',web_scrape:'SCRAPE',
  research_task:'RESEARCH',send_chat_to_gateway:'DELEGATE',
  get_gmail_inbox:'GMAIL',get_calendar_today:'CALENDAR',create_calendar_event:'CALENDAR',get_calendar_upcoming:'CALENDAR',list_calendars:'CALENDAR',trash_emails:'GMAIL',label_emails:'GMAIL',send_email:'GMAIL',get_gmail_labels:'GMAIL',
  shell_execute:'SHELL',git_operations:'GIT',vercel_deploy:'DEPLOY',
  file_read:'FILE',file_write:'WRITE',file_edit:'EDIT',
  glob_files:'GLOB',grep_search:'GREP',
  send_slack_message:'SLACK',security_scan:'SECURITY',
  prediction_market:'MARKETS',env_manage:'ENV',
  process_manage:'PROCESS',install_package:'INSTALL',
};

function toolBadgeHtml(toolName){
  if(!toolName)return '';
  const cat=TOOL_CATEGORIES[toolName]||'system';
  const icon=TOOL_ICONS[cat]||'&#9881;';
  const label=TOOL_LABELS[toolName]||toolName.toUpperCase().replace(/_/g,' ');
  return '<div class="tool-badge '+cat+'"><span class="tool-icon">'+icon+'</span>'+label+'</div>';
}

function addMsg(role,text,meta){
  if(welcomeEl)welcomeEl.style.display='none';
  const group=document.createElement('div');
  group.className='msg-group '+role;
  const label=document.createElement('div');
  label.className='msg-label';
  label.textContent=role==='user'?'YOU':'OVERSEER';
  group.appendChild(label);
  const bubble=document.createElement('div');
  bubble.className='msg';
  let content='';
  if(role==='bot'&&meta&&meta.tool_used){
    content+=toolBadgeHtml(meta.tool_used);
  }
  content+=renderMd(text);
  bubble.innerHTML=content;
  group.appendChild(bubble);
  chatEl.appendChild(group);
  chatEl.scrollTop=chatEl.scrollHeight;
  totalMsgs++;
  msgCountEl.textContent=totalMsgs+' msgs';
}

let sending=false;
async function send(){
  const text=inputEl.value.trim();
  if(!text||sending)return;
  sending=true;sendBtn.disabled=true;
  inputEl.value='';inputEl.style.height='auto';
  addMsg('user',text);
  typingLabel.textContent='thinking...';
  typingEl.classList.add('show');
  chatEl.appendChild(typingEl);
  chatEl.scrollTop=chatEl.scrollHeight;

  try{
    const resp=await fetch('/api/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:text,sessionKey})
    });
    const data=await resp.json();
    if(data.sessionKey){sessionKey=data.sessionKey;localStorage.setItem('oc_session',sessionKey)}
    if(data.model)modelNameEl.textContent=data.model;
    if(data.sessionMessageCount)msgCountEl.textContent=data.sessionMessageCount+' in session';
    if(data.tool_used)typingLabel.textContent='called '+data.tool_used+'...';
    const reply=data.response||data.message||data.reply||data.error||'No response';
    addMsg('bot',reply,{tool_used:data.tool_used});
  }catch(err){
    addMsg('bot','Connection error: '+err.message,{});
  }finally{
    typingEl.classList.remove('show');
    sending=false;sendBtn.disabled=false;inputEl.focus();
  }
}

// Health check
(async()=>{
  try{
    const r=await fetch('/health');
    const d=await r.json();
    if(d.gateway==='ok'){
      statusText.textContent='ONLINE';
      statusPill.className='status-pill';
    }else{
      statusText.textContent='DEGRADED';
      statusPill.className='status-pill degraded';
    }
  }catch{
    statusText.textContent='OFFLINE';
    statusPill.className='status-pill offline';
  }
})();

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
