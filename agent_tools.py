"""
Agent Tools — Full execution capabilities for OpenClaw agents
GitHub, git, shell, Vercel, file I/O, web scraping, package install, research
Available to agents via Claude tool_use in /api/chat, Slack, and Telegram
"""

import os
import subprocess
import json
import logging
import shutil
import httpx

logger = logging.getLogger("agent_tools")

# ═══════════════════════════════════════════════════════════════
# SAFETY: Sandboxed shell execution with allowlists
# ═══════════════════════════════════════════════════════════════

# Commands that are safe to run (no rm -rf, no format, etc.)
SAFE_COMMAND_PREFIXES = [
    "git ", "gh ", "npm ", "npx ", "pnpm ", "bun ", "pip ", "pip3 ",
    "python3 ", "python ", "node ", "deno ", "cargo ",
    "ls ", "cat ", "head ", "tail ", "wc ", "grep ", "find ", "tree ",
    "curl ", "wget ", "jq ", "yq ",
    "vercel ", "wrangler ", "netlify ",
    "docker ", "docker-compose ",
    "mkdir ", "cp ", "mv ", "touch ", "chmod ",
    "pytest ", "jest ", "vitest ", "mocha ",
    "tsc ", "eslint ", "prettier ",
    "echo ", "pwd", "whoami", "date", "env ",
    "tar ", "zip ", "unzip ", "gzip ",
]

# Commands that are NEVER allowed
BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){ :|:& };:",
    "shutdown", "reboot", "halt", "poweroff",
    "> /dev/sd", "chmod -R 777 /",
]

# Directories agents can write to
ALLOWED_WRITE_DIRS = [
    "/root/", "/tmp/", "/home/",
]

# Max output size from shell commands (chars)
MAX_SHELL_OUTPUT = 10000

# Max file read size
MAX_FILE_READ = 50000

# Tool definitions for Claude API
AGENT_TOOLS = [
    {
        "name": "github_repo_info",
        "description": "Get info about a GitHub repository (issues, PRs, status). Use this when the user asks about repo status, open issues, or PRs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format, e.g. 'Miles0sage/Barber-CRM'"
                },
                "action": {
                    "type": "string",
                    "enum": ["issues", "prs", "status", "commits"],
                    "description": "What to fetch: issues, prs, status (general info), or recent commits"
                }
            },
            "required": ["repo", "action"]
        }
    },
    {
        "name": "github_create_issue",
        "description": "Create a GitHub issue on a repository. Use when asked to file a bug, feature request, or task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/name format"
                },
                "title": {
                    "type": "string",
                    "description": "Issue title"
                },
                "body": {
                    "type": "string",
                    "description": "Issue body/description"
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply"
                }
            },
            "required": ["repo", "title"]
        }
    },
    {
        "name": "web_search",
        "description": "Search the web for current information. Use when the user asks about recent events, documentation, tutorials, or anything requiring up-to-date info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "create_job",
        "description": "Create a new job in the agency job queue. Use when someone asks to create a task, fix a bug, build a feature, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name: barber-crm, openclaw, delhi-palace, prestress-calc, concrete-canoe"
                },
                "task": {
                    "type": "string",
                    "description": "Description of the task"
                },
                "priority": {
                    "type": "string",
                    "enum": ["P0", "P1", "P2", "P3"],
                    "description": "Priority: P0=critical, P1=high, P2=medium, P3=low"
                }
            },
            "required": ["project", "task"]
        }
    },
    {
        "name": "list_jobs",
        "description": "List jobs in the agency queue, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "analyzing", "pr_ready", "approved", "done", "all"],
                    "description": "Filter by status, or 'all' to see everything"
                }
            },
            "required": []
        }
    },
    {
        "name": "create_proposal",
        "description": "Create a proposal that goes through auto-approval. Use this for non-trivial tasks that need cost estimation and approval before execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the proposal"},
                "description": {"type": "string", "description": "What needs to be done"},
                "agent_pref": {"type": "string", "enum": ["project_manager", "coder_agent", "hacker_agent", "database_agent"], "description": "Which agent should handle this"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags: routing, security, fix, feature, maintenance, etc."},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "description": "Priority level"}
            },
            "required": ["title", "description"]
        }
    },
    {
        "name": "get_cost_summary",
        "description": "Get current API cost summary and budget status. Use when asked about spending, budget, or costs.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "approve_job",
        "description": "Approve a job that's in pr_ready status for execution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job ID to approve"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "web_fetch",
        "description": "Fetch content from a URL and return readable text. Use for reading docs, articles, API responses.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
                "extract": {"type": "string", "enum": ["text", "links", "all"], "description": "What to extract: text content, links, or everything"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "get_events",
        "description": "Get recent system events (job completions, proposals, alerts). Use when asked about what's happening or recent activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of events to return (default 10)"},
                "event_type": {"type": "string", "description": "Filter by type: job.created, job.completed, job.failed, proposal.created, cost.alert"}
            },
            "required": []
        }
    },
    {
        "name": "save_memory",
        "description": "Save an important fact, decision, or preference to long-term memory. Use when the user tells you something worth remembering across conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact or information to remember"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for categorization: project name, topic, etc."},
                "importance": {"type": "integer", "description": "1-10 scale. 10=critical decision, 7=preference, 5=useful fact, 3=minor detail"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "search_memory",
        "description": "Search through saved memories for relevant context. Use when you need to recall past decisions, preferences, or facts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "limit": {"type": "integer", "description": "Max results (default 5)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "send_slack_message",
        "description": "Send a message to a Slack channel. Use to proactively notify the team about important updates, completions, or alerts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to send"},
                "channel": {"type": "string", "description": "Channel ID (default: report channel C0AFE4QHKH7)"}
            },
            "required": ["message"]
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # EXECUTION TOOLS — Shell, Git, Vercel, File I/O, Packages
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "shell_execute",
        "description": "Execute a shell command on the server. Sandboxed to safe commands only (git, npm, python, node, curl, docker, vercel, etc). Use for building, testing, deploying, and system operations. Returns stdout/stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run (e.g. 'npm run build', 'python3 test.py', 'git status')"},
                "cwd": {"type": "string", "description": "Working directory (default: /root)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 60, max: 300)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "git_operations",
        "description": "Perform git operations: status, add, commit, push, pull, branch, log, diff. Use for version control and deploying code to GitHub.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "add", "commit", "push", "pull", "branch", "log", "diff", "clone", "checkout"],
                    "description": "Git action to perform"
                },
                "repo_path": {"type": "string", "description": "Path to git repo (default: /root/openclaw)"},
                "args": {"type": "string", "description": "Additional arguments (e.g. commit message, branch name, file paths)"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to add (for 'add' action)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "vercel_deploy",
        "description": "Deploy a project to Vercel. Supports deploy, list deployments, set env vars, and check status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["deploy", "list", "env-set", "status", "logs"],
                    "description": "Vercel action"
                },
                "project_path": {"type": "string", "description": "Path to project to deploy"},
                "project_name": {"type": "string", "description": "Vercel project name (for status/logs)"},
                "env_key": {"type": "string", "description": "Environment variable key (for env-set)"},
                "env_value": {"type": "string", "description": "Environment variable value (for env-set)"},
                "production": {"type": "boolean", "description": "Deploy to production (default: true)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_read",
        "description": "Read contents of a file. Use to inspect code, configs, logs, or any text file on the server.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "lines": {"type": "integer", "description": "Max lines to read (default: all, max: 500)"},
                "offset": {"type": "integer", "description": "Start from this line number (0-based)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "file_write",
        "description": "Write or append to a file. Use to create new files, edit configs, or save output. Restricted to allowed directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "content": {"type": "string", "description": "Content to write"},
                "mode": {"type": "string", "enum": ["write", "append"], "description": "Write mode (default: write)"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "install_package",
        "description": "Install a package or tool. Supports npm, pip, apt, and binary installs. Auto-detects if tool is already installed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Package name (e.g. 'express', 'requests', 'vercel')"},
                "manager": {"type": "string", "enum": ["npm", "pip", "apt", "binary"], "description": "Package manager to use"},
                "global_install": {"type": "boolean", "description": "Install globally (default: true for CLI tools)"}
            },
            "required": ["name", "manager"]
        }
    },
    {
        "name": "research_task",
        "description": "Research a topic before executing. Searches the web, fetches relevant docs, and returns a synthesis. Use this BEFORE attempting complex tasks to gather context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to research (e.g. 'Next.js 16 deployment to Vercel', 'Supabase RLS best practices')"},
                "depth": {"type": "string", "enum": ["quick", "medium", "deep"], "description": "Research depth (default: medium)"}
            },
            "required": ["topic"]
        }
    },
    {
        "name": "web_scrape",
        "description": "Scrape structured data from a webpage. Extracts text, links, headings, code blocks, or specific CSS selectors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to scrape"},
                "extract": {"type": "string", "enum": ["text", "links", "headings", "code", "tables", "all"], "description": "What to extract (default: text)"},
                "selector": {"type": "string", "description": "CSS selector to target specific elements (optional)"}
            },
            "required": ["url"]
        }
    },
]


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return the result as a string."""
    try:
        if tool_name == "github_repo_info":
            return _github_repo_info(tool_input["repo"], tool_input["action"])
        elif tool_name == "github_create_issue":
            return _github_create_issue(
                tool_input["repo"],
                tool_input["title"],
                tool_input.get("body", ""),
                tool_input.get("labels", [])
            )
        elif tool_name == "web_search":
            return _web_search(tool_input["query"])
        elif tool_name == "create_job":
            return _create_job(
                tool_input["project"],
                tool_input["task"],
                tool_input.get("priority", "P1")
            )
        elif tool_name == "list_jobs":
            return _list_jobs(tool_input.get("status", "all"))
        elif tool_name == "create_proposal":
            return _create_proposal_tool(
                tool_input["title"],
                tool_input["description"],
                tool_input.get("agent_pref", "project_manager"),
                tool_input.get("tags"),
                tool_input.get("priority", "P1")
            )
        elif tool_name == "get_cost_summary":
            return _get_cost_summary()
        elif tool_name == "approve_job":
            return _approve_job_tool(tool_input["job_id"])
        elif tool_name == "web_fetch":
            return _web_fetch(tool_input["url"], tool_input.get("extract", "text"))
        elif tool_name == "get_events":
            return _get_events(tool_input.get("limit", 10), tool_input.get("event_type"))
        elif tool_name == "save_memory":
            return _save_memory(
                tool_input["content"],
                tool_input.get("tags"),
                tool_input.get("importance", 5)
            )
        elif tool_name == "search_memory":
            return _search_memory(tool_input["query"], tool_input.get("limit", 5))
        elif tool_name == "send_slack_message":
            return _send_slack_message(tool_input["message"], tool_input.get("channel"))
        # ═ Execution tools
        elif tool_name == "shell_execute":
            return _shell_execute(tool_input["command"], tool_input.get("cwd", "/root"), tool_input.get("timeout", 60))
        elif tool_name == "git_operations":
            return _git_operations(tool_input["action"], tool_input.get("repo_path", "/root/openclaw"),
                                   tool_input.get("args", ""), tool_input.get("files", []))
        elif tool_name == "vercel_deploy":
            return _vercel_deploy(tool_input["action"], tool_input.get("project_path", ""),
                                  tool_input.get("project_name", ""), tool_input.get("env_key", ""),
                                  tool_input.get("env_value", ""), tool_input.get("production", True))
        elif tool_name == "file_read":
            return _file_read(tool_input["path"], tool_input.get("lines"), tool_input.get("offset", 0))
        elif tool_name == "file_write":
            return _file_write(tool_input["path"], tool_input["content"], tool_input.get("mode", "write"))
        elif tool_name == "install_package":
            return _install_package(tool_input["name"], tool_input["manager"], tool_input.get("global_install", True))
        elif tool_name == "research_task":
            return _research_task(tool_input["topic"], tool_input.get("depth", "medium"))
        elif tool_name == "web_scrape":
            return _web_scrape(tool_input["url"], tool_input.get("extract", "text"), tool_input.get("selector", ""))
        else:
            return f"Unknown tool: {tool_name}"
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return f"Error: {str(e)}"


def _github_repo_info(repo: str, action: str) -> str:
    """Get GitHub repo info using gh CLI."""
    try:
        if action == "issues":
            result = subprocess.run(
                ["gh", "issue", "list", "--repo", repo, "--limit", "10", "--json", "number,title,state,labels"],
                capture_output=True, text=True, timeout=15
            )
        elif action == "prs":
            result = subprocess.run(
                ["gh", "pr", "list", "--repo", repo, "--limit", "10", "--json", "number,title,state,headRefName"],
                capture_output=True, text=True, timeout=15
            )
        elif action == "commits":
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/commits", "--jq", ".[0:5] | .[] | .sha[0:7] + \" \" + .commit.message[0:80]"],
                capture_output=True, text=True, timeout=15
            )
        else:  # status
            result = subprocess.run(
                ["gh", "repo", "view", repo, "--json", "name,description,stargazerCount,forkCount,defaultBranchRef,updatedAt"],
                capture_output=True, text=True, timeout=15
            )

        if result.returncode == 0:
            return result.stdout.strip() or "No results"
        else:
            return f"GitHub error: {result.stderr.strip()}"
    except FileNotFoundError:
        return "gh CLI not installed. Install with: curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg"
    except subprocess.TimeoutExpired:
        return "GitHub request timed out"


def _github_create_issue(repo: str, title: str, body: str, labels: list) -> str:
    """Create a GitHub issue."""
    try:
        cmd = ["gh", "issue", "create", "--repo", repo, "--title", title]
        if body:
            cmd.extend(["--body", body])
        if labels:
            cmd.extend(["--label", ",".join(labels)])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return f"Issue created: {result.stdout.strip()}"
        else:
            return f"Error: {result.stderr.strip()}"
    except Exception as e:
        return f"Error creating issue: {e}"


def _web_search(query: str) -> str:
    """Web search using DuckDuckGo HTML (no API key needed)."""
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"}
            )

            if resp.status_code != 200:
                return f"Search failed: HTTP {resp.status_code}"

            # Parse results from HTML (simple extraction)
            text = resp.text
            results = []
            # Extract result snippets between result__snippet class
            import re
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL)
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', text, re.DOTALL)
            urls = re.findall(r'class="result__url"[^>]*>(.*?)</a>', text, re.DOTALL)

            for i in range(min(5, len(titles))):
                title = re.sub(r'<[^>]+>', '', titles[i]).strip() if i < len(titles) else ""
                snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip() if i < len(snippets) else ""
                url = re.sub(r'<[^>]+>', '', urls[i]).strip() if i < len(urls) else ""
                results.append(f"• {title}\n  {url}\n  {snippet}")

            return "\n\n".join(results) if results else "No results found"
    except Exception as e:
        return f"Search error: {e}"


def _create_job(project: str, task: str, priority: str) -> str:
    """Create a job in the queue."""
    from job_manager import create_job
    job = create_job(project, task, priority)
    return f"Job created: {job.id} | Project: {project} | Priority: {priority} | Task: {task}"


def _list_jobs(status: str) -> str:
    """List jobs from the queue."""
    from job_manager import list_jobs
    jobs = list_jobs()

    if status != "all":
        jobs = [j for j in jobs if j.get("status") == status]

    if not jobs:
        return "No jobs found"

    lines = []
    for j in jobs[-10:]:
        lines.append(f"• {j['id']} | {j['project']} | {j.get('status','?')} | {j['task'][:60]}")

    return "\n".join(lines)


def _create_proposal_tool(title: str, description: str, agent_pref: str = "project_manager",
                          tags: list = None, priority: str = "P1") -> str:
    """Create a proposal that goes through auto-approval."""
    from proposal_engine import create_proposal as _create_prop
    from approval_engine import auto_approve_and_execute
    tokens_est = 5000 if agent_pref in ("coder_agent", "hacker_agent") else 10000
    p = _create_prop(title, description, agent_pref, tokens_est, tags or [])
    result = auto_approve_and_execute(p.to_dict())
    return f"Proposal {p.id} created (cost: ${p.cost_est_usd:.4f}). Approval: {result.get('decision', {}).get('reason', 'pending')}"


def _get_cost_summary() -> str:
    """Get current API cost summary and budget status."""
    try:
        import requests as req
        resp = req.get("http://localhost:18789/api/costs/summary", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return json.dumps(data, indent=2)
        return f"Cost API returned {resp.status_code}"
    except Exception as e:
        return f"Error: {e}"


def _approve_job_tool(job_id: str) -> str:
    """Approve a job that's in pr_ready status for execution."""
    from job_manager import get_job, update_job_status
    job = get_job(job_id)
    if not job:
        return f"Job {job_id} not found"
    if job.get("status") != "pr_ready":
        return f"Job {job_id} is '{job.get('status')}', not ready for approval"
    update_job_status(job_id, "approved", approved_by="agent")
    return f"Job {job_id} approved for execution"


def _web_fetch(url: str, extract: str = "text") -> str:
    """Fetch content from a URL and return readable text."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"})
            if resp.status_code != 200:
                return f"HTTP {resp.status_code}"
            import re
            text = re.sub(r'<script[^>]*>.*?</script>', '', resp.text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:3000]
    except Exception as e:
        return f"Fetch error: {e}"


def _get_events(limit: int = 10, event_type: str = None) -> str:
    """Get recent system events."""
    try:
        from event_engine import get_event_engine
        engine = get_event_engine()
        if not engine:
            return "Event engine not initialized"
        events = engine.get_recent_events(limit=limit, event_type=event_type)
        if not events:
            return "No recent events"
        lines = []
        for e in events:
            lines.append(f"[{e['timestamp'][:19]}] {e['event_type']}: {json.dumps(e.get('data', {}))[:100]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _save_memory(content: str, tags: list = None, importance: int = 5) -> str:
    """Save important information to long-term memory."""
    try:
        from memory_manager import get_memory_manager
        mm = get_memory_manager()
        if not mm:
            return "Memory manager not initialized"
        mem_id = mm.add_memory(content=content, tags=tags or [], source="agent_tool", importance=importance)
        return f"Memory saved: {mem_id} (importance: {importance})"
    except Exception as e:
        return f"Error saving memory: {e}"


def _search_memory(query: str, limit: int = 5) -> str:
    """Search through saved memories for relevant context."""
    try:
        from memory_manager import get_memory_manager
        mm = get_memory_manager()
        if not mm:
            return "Memory manager not initialized"
        results = mm.search_memories(query, limit=limit)
        if not results:
            return "No matching memories found"
        lines = []
        for m in results:
            tags_str = ", ".join(m.get("tags", []))
            lines.append(f"[{m.get('importance', '?')}/10] {m.get('content', '')[:150]} ({tags_str})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def _send_slack_message(message: str, channel: str = None) -> str:
    """Send a message to a Slack channel."""
    try:
        import requests as req
        channel = channel or os.getenv("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
        token = os.getenv("GATEWAY_AUTH_TOKEN", "")
        resp = req.post(
            "http://localhost:18789/slack/report/send",
            json={"text": message, "channel": channel},
            headers={"X-Auth-Token": token},
            timeout=10
        )
        return f"Message sent to Slack ({resp.status_code})"
    except Exception as e:
        return f"Error: {e}"


# ═══════════════════════════════════════════════════════════════════════════
# EXECUTION TOOLS — Shell, Git, Vercel, File I/O, Packages, Research
# ═══════════════════════════════════════════════════════════════════════════

def _is_command_safe(command: str) -> tuple[bool, str]:
    """Check if a command is safe to execute."""
    cmd_lower = command.strip().lower()

    # Check blocked commands
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"BLOCKED: '{blocked}' is not allowed"

    # Check if starts with a safe prefix
    for prefix in SAFE_COMMAND_PREFIXES:
        if cmd_lower.startswith(prefix.lower()) or cmd_lower == prefix.strip():
            return True, "OK"

    # Allow piped commands if each segment is safe
    if "|" in command:
        parts = [p.strip() for p in command.split("|")]
        for part in parts:
            safe, reason = _is_command_safe(part)
            if not safe:
                return False, f"Pipe segment blocked: {reason}"
        return True, "OK (piped)"

    # Allow chained commands (&&, ;)
    for sep in ["&&", ";"]:
        if sep in command:
            parts = [p.strip() for p in command.split(sep)]
            for part in parts:
                safe, reason = _is_command_safe(part)
                if not safe:
                    return False, f"Chained segment blocked: {reason}"
            return True, "OK (chained)"

    return False, f"Command not in allowlist. Allowed prefixes: git, npm, python3, node, curl, vercel, docker, etc."


def _is_path_writable(path: str) -> bool:
    """Check if path is in allowed write directories."""
    abs_path = os.path.abspath(path)
    return any(abs_path.startswith(d) for d in ALLOWED_WRITE_DIRS)


def _shell_execute(command: str, cwd: str = "/root", timeout: int = 60) -> str:
    """Execute a sandboxed shell command."""
    safe, reason = _is_command_safe(command)
    if not safe:
        return f"⛔ Command rejected: {reason}"

    timeout = min(timeout, 300)  # Max 5 minutes

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
            env={**os.environ, "PATH": f"/usr/local/bin:/usr/bin:/bin:/root/.bun/bin:/root/.local/bin:{os.environ.get('PATH', '')}"}
        )
        output = ""
        if result.stdout:
            output += result.stdout[:MAX_SHELL_OUTPUT]
        if result.stderr:
            output += f"\n[STDERR]: {result.stderr[:2000]}"
        output += f"\n[EXIT CODE]: {result.returncode}"
        return output.strip() or "[No output]"
    except subprocess.TimeoutExpired:
        return f"⏱️ Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def _git_operations(action: str, repo_path: str = "/root/openclaw", args: str = "", files: list = None) -> str:
    """Perform git operations."""
    if not os.path.isdir(repo_path):
        return f"Directory not found: {repo_path}"

    try:
        if action == "status":
            cmd = ["git", "status", "--short"]
        elif action == "add":
            if files:
                cmd = ["git", "add"] + files
            elif args:
                cmd = ["git", "add"] + args.split()
            else:
                cmd = ["git", "add", "-A"]
        elif action == "commit":
            if not args:
                return "Error: commit message required in 'args'"
            cmd = ["git", "commit", "-m", f"{args}\n\nCo-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"]
        elif action == "push":
            remote = args.split()[0] if args else "origin"
            branch = args.split()[1] if args and len(args.split()) > 1 else "main"
            cmd = ["git", "push", remote, branch]
        elif action == "pull":
            cmd = ["git", "pull"] + (args.split() if args else [])
        elif action == "branch":
            if args:
                cmd = ["git", "checkout", "-b", args]
            else:
                cmd = ["git", "branch", "-a"]
        elif action == "log":
            count = args if args else "10"
            cmd = ["git", "log", f"--oneline", f"-{count}"]
        elif action == "diff":
            cmd = ["git", "diff"] + (args.split() if args else [])
        elif action == "clone":
            if not args:
                return "Error: repository URL required in 'args'"
            cmd = ["git", "clone", args]
        elif action == "checkout":
            if not args:
                return "Error: branch name required in 'args'"
            cmd = ["git", "checkout", args]
        else:
            return f"Unknown git action: {action}"

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=repo_path)
        output = result.stdout.strip()
        if result.stderr:
            output += f"\n{result.stderr.strip()}"
        return output or f"git {action}: done"
    except subprocess.TimeoutExpired:
        return f"git {action} timed out"
    except Exception as e:
        return f"git error: {e}"


def _vercel_deploy(action: str, project_path: str = "", project_name: str = "",
                   env_key: str = "", env_value: str = "", production: bool = True) -> str:
    """Vercel deployment operations."""
    vercel_token = os.getenv("VERCEL_TOKEN", "")

    try:
        # Check if vercel CLI is available
        if not shutil.which("vercel"):
            # Try to install it
            result = subprocess.run(["npm", "install", "-g", "vercel"], capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                return "Vercel CLI not installed. Install with: npm install -g vercel"

        if action == "deploy":
            if not project_path:
                return "Error: project_path required for deploy"
            cmd = ["vercel", "deploy", "--yes"]
            if production:
                cmd.append("--prod")
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=project_path)
            return result.stdout.strip() + ("\n" + result.stderr.strip() if result.stderr else "")

        elif action == "list":
            cmd = ["vercel", "ls"]
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip()[:3000]

        elif action == "env-set":
            if not env_key or not env_value:
                return "Error: env_key and env_value required"
            cmd = f"printf '{env_value}' | vercel env add {env_key} production --force"
            if vercel_token:
                cmd += f" --token {vercel_token}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return result.stdout.strip() or f"Env var {env_key} set"

        elif action == "status":
            name = project_name or "current project"
            cmd = ["vercel", "inspect"]
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip()[:2000]

        elif action == "logs":
            cmd = ["vercel", "logs"]
            if project_name:
                cmd.append(project_name)
            if vercel_token:
                cmd.extend(["--token", vercel_token])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stdout.strip()[:3000]

        return f"Unknown vercel action: {action}"
    except subprocess.TimeoutExpired:
        return f"Vercel {action} timed out"
    except Exception as e:
        return f"Vercel error: {e}"


def _file_read(path: str, lines: int = None, offset: int = 0) -> str:
    """Read file contents with optional line limits."""
    try:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            return f"File not found: {path}"
        if os.path.isdir(abs_path):
            entries = os.listdir(abs_path)
            return f"Directory listing ({len(entries)} items):\n" + "\n".join(entries[:100])
        if os.path.getsize(abs_path) > MAX_FILE_READ * 4:
            return f"File too large ({os.path.getsize(abs_path)} bytes). Use 'lines' parameter to read a portion."

        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        if offset:
            all_lines = all_lines[offset:]
        if lines:
            all_lines = all_lines[:min(lines, 500)]

        content = "".join(all_lines)
        if len(content) > MAX_FILE_READ:
            content = content[:MAX_FILE_READ] + f"\n... [truncated at {MAX_FILE_READ} chars]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def _file_write(path: str, content: str, mode: str = "write") -> str:
    """Write or append to a file."""
    try:
        abs_path = os.path.abspath(path)
        if not _is_path_writable(abs_path):
            return f"⛔ Path not writable: {path}. Allowed dirs: {', '.join(ALLOWED_WRITE_DIRS)}"

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        file_mode = "a" if mode == "append" else "w"
        with open(abs_path, file_mode, encoding="utf-8") as f:
            f.write(content)

        size = os.path.getsize(abs_path)
        return f"✅ Written to {path} ({size} bytes, mode={mode})"
    except Exception as e:
        return f"Error writing file: {e}"


def _install_package(name: str, manager: str, global_install: bool = True) -> str:
    """Install a package using the specified manager."""
    try:
        # Check if already installed
        if manager in ("npm", "binary"):
            check = shutil.which(name)
            if check:
                return f"✅ {name} already installed at {check}"

        if manager == "npm":
            cmd = ["npm", "install"]
            if global_install:
                cmd.append("-g")
            cmd.append(name)
        elif manager == "pip":
            cmd = ["pip3", "install", "--break-system-packages", name]
        elif manager == "apt":
            cmd = ["apt-get", "install", "-y", name]
        elif manager == "binary":
            return f"Binary install not implemented for {name}. Use shell_execute with curl."
        else:
            return f"Unknown package manager: {manager}"

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        output = result.stdout.strip()[-1000:]
        if result.returncode != 0:
            output += f"\n[ERROR]: {result.stderr.strip()[-500:]}"
        return output or f"✅ {name} installed via {manager}"
    except subprocess.TimeoutExpired:
        return f"Install timed out for {name}"
    except Exception as e:
        return f"Install error: {e}"


def _research_task(topic: str, depth: str = "medium") -> str:
    """Research a topic by searching the web and fetching relevant pages."""
    results = []

    # Step 1: Web search
    search_result = _web_search(topic)
    results.append(f"=== SEARCH RESULTS ===\n{search_result}")

    if depth in ("medium", "deep"):
        # Step 2: Also search for code examples / tutorials
        code_search = _web_search(f"{topic} tutorial example code 2026")
        results.append(f"\n=== CODE/TUTORIAL SEARCH ===\n{code_search}")

    if depth == "deep":
        # Step 3: Search for best practices and common issues
        best_practices = _web_search(f"{topic} best practices common issues pitfalls")
        results.append(f"\n=== BEST PRACTICES ===\n{best_practices}")

        # Step 4: Search for official documentation
        docs_search = _web_search(f"{topic} official documentation API reference")
        results.append(f"\n=== OFFICIAL DOCS ===\n{docs_search}")

    # Try to fetch the first URL from search results
    import re
    urls = re.findall(r'https?://\S+', search_result)
    if urls and depth in ("medium", "deep"):
        first_url = urls[0].rstrip(')')
        fetched = _web_fetch(first_url, "text")
        results.append(f"\n=== FETCHED: {first_url} ===\n{fetched[:2000]}")

    return "\n".join(results)


def _web_scrape(url: str, extract: str = "text", selector: str = "") -> str:
    """Scrape structured data from a webpage."""
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"})
            if resp.status_code != 200:
                return f"HTTP {resp.status_code}"

            import re
            html = resp.text

            if extract == "links":
                links = re.findall(r'href=["\']([^"\']+)["\']', html)
                unique_links = list(dict.fromkeys(links))[:50]
                return "\n".join(unique_links)

            elif extract == "headings":
                headings = re.findall(r'<h[1-6][^>]*>(.*?)</h[1-6]>', html, re.DOTALL | re.IGNORECASE)
                clean = [re.sub(r'<[^>]+>', '', h).strip() for h in headings]
                return "\n".join(clean) if clean else "No headings found"

            elif extract == "code":
                # Extract code blocks
                code_blocks = re.findall(r'<code[^>]*>(.*?)</code>', html, re.DOTALL)
                pre_blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL)
                all_code = code_blocks + pre_blocks
                clean = [re.sub(r'<[^>]+>', '', c).strip() for c in all_code]
                return "\n---\n".join(clean[:20]) if clean else "No code blocks found"

            elif extract == "tables":
                tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
                result = []
                for table in tables[:5]:
                    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL | re.IGNORECASE)
                    for row in rows:
                        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, re.DOTALL | re.IGNORECASE)
                        clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                        result.append(" | ".join(clean_cells))
                    result.append("---")
                return "\n".join(result) if result else "No tables found"

            else:  # text or all
                # Remove script/style
                text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)

                if selector and extract == "all":
                    # Try to find elements matching a simple class/id selector
                    if selector.startswith("."):
                        pattern = rf'class=["\'][^"\']*{re.escape(selector[1:])}[^"\']*["\'][^>]*>(.*?)</'
                    elif selector.startswith("#"):
                        pattern = rf'id=["\'][^"\']*{re.escape(selector[1:])}[^"\']*["\'][^>]*>(.*?)</'
                    else:
                        pattern = rf'<{re.escape(selector)}[^>]*>(.*?)</{re.escape(selector)}>'
                    matches = re.findall(pattern, text, re.DOTALL)
                    if matches:
                        clean = [re.sub(r'<[^>]+>', ' ', m).strip() for m in matches[:20]]
                        return "\n".join(clean)

                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text[:5000]

    except Exception as e:
        return f"Scrape error: {e}"
