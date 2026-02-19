"""
Agent Tools — GitHub access, web search, job management
Available to agents via Claude tool_use for Slack/Telegram interactions
"""

import os
import subprocess
import json
import logging
import httpx

logger = logging.getLogger("agent_tools")

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
    }
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
