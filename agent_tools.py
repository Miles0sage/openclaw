"""
Agent Tools — Full execution capabilities for OpenClaw agents
GitHub, git, shell, Vercel, file I/O, web scraping, package install, research
Available to agents via Claude tool_use in /api/chat, Slack, and Telegram
"""

import os
import re
import subprocess
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
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
    "oxo ",
    "mkdir ", "cp ", "mv ", "touch ", "chmod ",
    "pytest ", "jest ", "vitest ", "mocha ",
    "tsc ", "eslint ", "prettier ",
    "echo ", "pwd", "whoami", "date", "env ",
    "tar ", "zip ", "unzip ", "gzip ",
    "polymarket ",
]

# Commands that are NEVER allowed
BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){ :|:& };:",
    "shutdown", "reboot", "halt", "poweroff",
    "> /dev/sd", "chmod -R 777 /",
    # Interpreter inline-execution bypasses
    "python3 -c", "python -c",
    "node -e", "node --eval",
    "perl -e", "perl -E",
    "ruby -e",
    "bash -c", "sh -c", "zsh -c",
    # Dangerous file targets
    "/etc/shadow", "/etc/passwd",
    "~/.ssh", "/root/.ssh",
]

# Patterns for subshell / backtick injection with dangerous payloads
_DANGEROUS_SUBSHELL_PATTERNS = [
    re.compile(r'\$\(.*(?:rm|mkfs|dd|shutdown|reboot|halt|poweroff|chmod\s+-R|curl.*\|\s*(?:bash|sh)).*\)', re.IGNORECASE),
    re.compile(r'`.*(?:rm|mkfs|dd|shutdown|reboot|halt|poweroff|chmod\s+-R|curl.*\|\s*(?:bash|sh)).*`', re.IGNORECASE),
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
            "required": ["repo", "action"],
            "additionalProperties": False
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
            "required": ["repo", "title"],
            "additionalProperties": False
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
            "required": ["query"],
            "additionalProperties": False
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
            "required": ["project", "task"],
            "additionalProperties": False
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
            "required": [],
            "additionalProperties": False
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
            "required": ["title", "description"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_cost_summary",
        "description": "Get current API cost summary and budget status. Use when asked about spending, budget, or costs.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
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
            "required": ["job_id"],
            "additionalProperties": False
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
            "required": ["url"],
            "additionalProperties": False
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
            "required": [],
            "additionalProperties": False
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
            "required": ["content"],
            "additionalProperties": False
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
            "required": ["query"],
            "additionalProperties": False
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
            "required": ["message"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # AGENCY MANAGEMENT TOOLS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "kill_job",
        "description": "Cancel a running or pending job. Sets kill flag and terminates any tmux agent running it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The job ID to cancel"}
            },
            "required": ["job_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "agency_status",
        "description": "Get combined agency overview: active jobs, recent completions, costs, active agents, alerts.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "manage_reactions",
        "description": "Manage auto-reaction rules (list, add, update, delete, get triggers history).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "add", "update", "delete", "triggers"], "description": "Action to perform"},
                "rule_id": {"type": "string", "description": "Rule ID (for update/delete)"},
                "rule_data": {"type": "object", "description": "Rule fields (for add/update)"}
            },
            "required": ["action"],
            "additionalProperties": False
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
            "required": ["command"],
            "additionalProperties": False
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
            "required": ["action"],
            "additionalProperties": False
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
            "required": ["action"],
            "additionalProperties": False
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
            "required": ["path"],
            "additionalProperties": False
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
            "required": ["path", "content"],
            "additionalProperties": False
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
            "required": ["name", "manager"],
            "additionalProperties": False
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
            "required": ["topic"],
            "additionalProperties": False
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
            "required": ["url"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # CODE EDITING TOOLS — Edit, Glob, Grep, Process, Env
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "file_edit",
        "description": "Edit a file by finding and replacing a specific string. Like surgical find-replace — doesn't overwrite the whole file. Use this to modify existing code, fix bugs, update configs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "old_string": {"type": "string", "description": "The exact string to find (must be unique in the file)"},
                "new_string": {"type": "string", "description": "The replacement string"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false, only first)"}
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False
        }
    },
    {
        "name": "glob_files",
        "description": "Find files matching a glob pattern. Use to discover project structure, find all files of a type, locate configs. Returns file paths sorted by modification time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts', '*.json')"},
                "path": {"type": "string", "description": "Root directory to search in (default: /root)"},
                "max_results": {"type": "integer", "description": "Max files to return (default: 50)"}
            },
            "required": ["pattern"],
            "additionalProperties": False
        }
    },
    {
        "name": "grep_search",
        "description": "Search file contents using regex patterns. Find function definitions, variable usage, imports, error messages, etc. across a codebase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for (e.g. 'def main', 'import.*fastapi', 'TODO|FIXME')"},
                "path": {"type": "string", "description": "File or directory to search in (default: /root)"},
                "file_pattern": {"type": "string", "description": "Filter files by glob (e.g. '*.py', '*.ts')"},
                "context_lines": {"type": "integer", "description": "Lines of context around matches (default: 2)"},
                "max_results": {"type": "integer", "description": "Max matches to return (default: 20)"}
            },
            "required": ["pattern"],
            "additionalProperties": False
        }
    },
    {
        "name": "process_manage",
        "description": "Manage running processes: list, kill, check ports. Use to manage servers, check what's running, free up ports.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "kill", "check_port", "top"],
                    "description": "Action: list processes, kill by PID/name, check what's on a port, or show top resource users"
                },
                "target": {"type": "string", "description": "PID, process name, or port number depending on action"},
                "signal": {"type": "string", "enum": ["TERM", "KILL", "HUP"], "description": "Signal for kill (default: TERM)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "env_manage",
        "description": "Manage environment variables and .env files. Read, set, list env vars. Load/save .env files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "list", "load_dotenv", "save_dotenv"],
                    "description": "Action to perform"
                },
                "key": {"type": "string", "description": "Env var name (for get/set)"},
                "value": {"type": "string", "description": "Value to set (for set)"},
                "env_file": {"type": "string", "description": "Path to .env file (default: /root/.env)"},
                "filter": {"type": "string", "description": "Filter pattern for list (e.g. 'API', 'TOKEN')"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },

    # ═══════════════════════════════════════════════════════════════
    # COMPUTE TOOLS — Precise algorithms, math, data processing
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "compute_sort",
        "description": "Sort a list of numbers or strings using O(n log n) algorithms. Returns sorted result with timing. Use when the user needs data sorted precisely — never approximate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "description": "List of numbers or strings to sort"},
                "algorithm": {
                    "type": "string",
                    "enum": ["auto", "mergesort", "heapsort", "quicksort", "timsort"],
                    "description": "Sorting algorithm (default: auto picks optimal)"
                },
                "reverse": {"type": "boolean", "description": "Sort descending (default: false)"},
                "key": {"type": "string", "description": "For dicts: key to sort by (e.g. 'price', 'name')"}
            },
            "required": ["data"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_stats",
        "description": "Calculate statistics on a list of numbers: mean, median, mode, std dev, variance, percentiles, min, max, sum. Precise — no LLM approximation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "items": {"type": "number"}, "description": "List of numbers"},
                "percentiles": {"type": "array", "items": {"type": "number"}, "description": "Percentiles to calculate (e.g. [25, 50, 75, 90, 99])"}
            },
            "required": ["data"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_math",
        "description": "Evaluate mathematical expressions precisely. Supports arithmetic, trig, log, factorial, combinations, GCD, LCM, modular arithmetic. Use instead of mental math.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression (e.g. '2**64 - 1', 'math.factorial(20)', 'math.gcd(48, 18)')"},
                "precision": {"type": "integer", "description": "Decimal places for float results (default: 10)"}
            },
            "required": ["expression"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_search",
        "description": "Search/filter data using binary search, linear scan, or regex. O(log n) for sorted data. Use to find items in large datasets precisely.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "array", "description": "Data to search through"},
                "target": {"description": "Value to find"},
                "method": {
                    "type": "string",
                    "enum": ["binary", "linear", "filter", "regex"],
                    "description": "Search method (binary requires sorted data)"
                },
                "condition": {"type": "string", "description": "For filter: Python expression using 'x' (e.g. 'x > 50', 'x % 2 == 0')"}
            },
            "required": ["data"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_matrix",
        "description": "Matrix operations: multiply, transpose, determinant, inverse, eigenvalues. For linear algebra computations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["multiply", "transpose", "determinant", "inverse", "eigenvalues", "solve"],
                    "description": "Matrix operation"
                },
                "matrix_a": {"type": "array", "description": "First matrix (2D array of numbers)"},
                "matrix_b": {"type": "array", "description": "Second matrix (for multiply) or vector (for solve)"}
            },
            "required": ["action", "matrix_a"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_prime",
        "description": "Prime number operations: factorize, primality test, generate primes, find nth prime. Exact integer arithmetic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["factorize", "is_prime", "generate", "nth_prime"],
                    "description": "What to compute"
                },
                "n": {"type": "integer", "description": "The number to test/factorize, or count of primes to generate"},
                "limit": {"type": "integer", "description": "Upper bound for 'generate' action"}
            },
            "required": ["action", "n"],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_hash",
        "description": "Compute cryptographic hashes: SHA-256, SHA-512, MD5, BLAKE2. For data integrity verification and checksums.",
        "input_schema": {
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "String to hash"},
                "algorithm": {
                    "type": "string",
                    "enum": ["sha256", "sha512", "md5", "blake2b", "sha1"],
                    "description": "Hash algorithm (default: sha256)"
                },
                "file_path": {"type": "string", "description": "Hash a file instead of a string"}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "compute_convert",
        "description": "Unit and base conversions: number bases (bin/oct/hex), temperatures, distances, data sizes, timestamps. Precise conversions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"description": "Value to convert"},
                "from_unit": {"type": "string", "description": "Source unit/base (e.g. 'celsius', 'hex', 'bytes', 'unix_timestamp')"},
                "to_unit": {"type": "string", "description": "Target unit/base (e.g. 'fahrenheit', 'decimal', 'gb', 'iso8601')"}
            },
            "required": ["value", "from_unit", "to_unit"],
            "additionalProperties": False
        }
    },
    {
        "name": "tmux_agents",
        "description": "Manage parallel Claude Code agents in tmux panes. Spawn agents with optional git worktree isolation, monitor status, collect output, kill agents. Elvis-pattern multi-agent orchestration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["spawn", "spawn_parallel", "list", "output", "kill", "kill_all", "cleanup"],
                    "description": "Action: spawn a single agent, spawn multiple in parallel, list running agents, get output, kill one/all, or cleanup worktree"
                },
                "job_id": {"type": "string", "description": "Job identifier (for spawn, output, kill, cleanup)"},
                "prompt": {"type": "string", "description": "Agent prompt/instruction (for spawn)"},
                "pane_id": {"type": "string", "description": "Tmux pane ID (for output, kill)"},
                "jobs": {
                    "type": "array",
                    "description": "List of job dicts for spawn_parallel. Each needs: job_id, prompt. Optional: worktree_repo, cwd",
                    "items": {"type": "object"}
                },
                "worktree_repo": {"type": "string", "description": "Git repo path to create worktree from (for spawn)"},
                "use_worktree": {"type": "boolean", "description": "Create isolated git worktree (default: false)"},
                "cwd": {"type": "string", "description": "Working directory override (for spawn)"},
                "timeout_minutes": {"type": "integer", "description": "Kill agent after N minutes (default: 30, 0=no limit)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "security_scan",
        "description": "Run an OXO security scan against a target (IP, domain, or URL). Profiles: quick (Nmap only), full (Nmap+Nuclei), web (Nmap+Nuclei+ZAP). Returns scan results as text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target to scan: IP address, domain, or URL"},
                "scan_type": {
                    "type": "string",
                    "enum": ["quick", "full", "web"],
                    "description": "Scan profile: quick (Nmap), full (Nmap+Nuclei), web (Nmap+Nuclei+ZAP). Default: quick"
                },
                "agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Override: explicit list of OXO agent keys to run (e.g. ['agent/ostorlab/nmap'])"
                }
            },
            "required": ["target"],
            "additionalProperties": False
        }
    },
    {
        "name": "prediction_market",
        "description": "Query Polymarket prediction markets. Search markets, get details, list events. Use for checking probabilities on current events, elections, tech, crypto, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "get_market", "list_markets", "list_events"],
                    "description": "Action: search markets, get specific market, list markets, list events"
                },
                "query": {"type": "string", "description": "Search query (for search action)"},
                "market_id": {"type": "string", "description": "Market ID or slug (for get_market action)"},
                "tag": {"type": "string", "description": "Event tag filter (for list_events, e.g. 'politics', 'crypto')"},
                "limit": {"type": "integer", "description": "Max results to return (default: 10)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "get_reflections",
        "description": "Get past job reflections (learnings from completed/failed jobs). Returns stats, recent reflections, or searches for reflections relevant to a task. Use to learn from past experience before starting work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["stats", "list", "search"],
                    "description": "Action: stats (summary), list (recent reflections), search (find relevant reflections for a task)"
                },
                "task": {"type": "string", "description": "Task description to search for (required for search action)"},
                "project": {"type": "string", "description": "Filter by project name (optional)"},
                "limit": {"type": "integer", "description": "Max reflections to return (default: 5)"}
            },
            "required": ["action"],
            "additionalProperties": False
        }
    },
    {
        "name": "create_event",
        "description": "Create/emit an event to the OpenClaw event engine. Use for logging custom events, milestones, or triggers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "Event type: job.created, job.completed, job.failed, deploy.complete, cost.alert, custom, etc."},
                "data": {"type": "object", "description": "Event payload data (any key-value pairs)"}
            },
            "required": ["event_type"],
            "additionalProperties": False
        }
    },
    {
        "name": "plan_my_day",
        "description": "Plan the user's day: fetches calendar events, pending jobs, agency status, and emails to create a prioritized daily plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "description": "Optional focus area: work, personal, or all (default: all)"}
            },
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # NEWS & SOCIAL MEDIA TOOLS
    # ═══════════════════════════════════════════════════════════════
    # ═══════════════════════════════════════════════════════════════
    # PERPLEXITY RESEARCH
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "perplexity_research",
        "description": "Deep research using Perplexity Sonar — returns AI-synthesized answers with web citations. Better than web_search for complex questions requiring synthesis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Research question"},
                "model": {"type": "string", "enum": ["sonar", "sonar-pro"], "description": "Model: sonar (fast, cheap $1/M) or sonar-pro (deeper, $3/$15 per M). Default: sonar"},
                "focus": {"type": "string", "enum": ["web", "academic", "news"], "description": "Search focus: web (general), academic (papers/research), news (recent events). Default: web"}
            },
            "required": ["query"],
            "additionalProperties": False
        }
    },
    # ═══════════════════════════════════════════════════════════════
    # NEWS & SOCIAL MEDIA TOOLS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "read_ai_news",
        "description": "Fetch RSS feeds from major AI news sources and return article summaries. Great for staying up to date on AI research, product launches, and industry news.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max articles to return (default: 10)"},
                "source": {"type": "string", "description": "Filter to specific source: openai, deepmind, huggingface, arxiv, verge, arstechnica, techcrunch, hackernews, mittech"},
                "hours": {"type": "integer", "description": "Only return articles from last N hours (default: 24)"}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "read_tweets",
        "description": "Read recent AI community posts and social media. Tries Reddit AI subs (primary), then Bluesky, then RSSHub Twitter, then Nitter, then web search. Returns posts with text, links, and platform.",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {"type": "string", "description": "Twitter username to read (without @). Default: reads from a list of top AI accounts"},
                "limit": {"type": "integer", "description": "Max tweets per account (default: 5)"},
            },
            "required": [],
            "additionalProperties": False
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
        # ═ Agency management tools
        elif tool_name == "kill_job":
            return _kill_job(tool_input["job_id"])
        elif tool_name == "agency_status":
            return _agency_status()
        elif tool_name == "manage_reactions":
            return _manage_reactions(tool_input["action"], tool_input.get("rule_id", ""), tool_input.get("rule_data"))
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
        # ═ Code editing tools
        elif tool_name == "file_edit":
            return _file_edit(tool_input["path"], tool_input["old_string"], tool_input["new_string"],
                             tool_input.get("replace_all", False))
        elif tool_name == "glob_files":
            return _glob_files(tool_input["pattern"], tool_input.get("path", "/root"),
                              tool_input.get("max_results", 50))
        elif tool_name == "grep_search":
            return _grep_search(tool_input["pattern"], tool_input.get("path", "/root"),
                               tool_input.get("file_pattern", ""), tool_input.get("context_lines", 2),
                               tool_input.get("max_results", 20))
        elif tool_name == "process_manage":
            return _process_manage(tool_input["action"], tool_input.get("target", ""),
                                  tool_input.get("signal", "TERM"))
        elif tool_name == "env_manage":
            return _env_manage(tool_input["action"], tool_input.get("key", ""),
                              tool_input.get("value", ""), tool_input.get("env_file", "/root/.env"),
                              tool_input.get("filter", ""))
        # ═ Compute tools
        elif tool_name == "compute_sort":
            return _compute_sort(tool_input["data"], tool_input.get("algorithm", "auto"),
                                tool_input.get("reverse", False), tool_input.get("key"))
        elif tool_name == "compute_stats":
            return _compute_stats(tool_input["data"], tool_input.get("percentiles"))
        elif tool_name == "compute_math":
            return _compute_math(tool_input["expression"], tool_input.get("precision", 10))
        elif tool_name == "compute_search":
            return _compute_search(tool_input["data"], tool_input.get("target"),
                                  tool_input.get("method", "linear"), tool_input.get("condition"))
        elif tool_name == "compute_matrix":
            return _compute_matrix(tool_input["action"], tool_input["matrix_a"],
                                  tool_input.get("matrix_b"))
        elif tool_name == "compute_prime":
            return _compute_prime(tool_input["action"], tool_input["n"], tool_input.get("limit"))
        elif tool_name == "compute_hash":
            return _compute_hash(tool_input.get("data", ""), tool_input.get("algorithm", "sha256"),
                                tool_input.get("file_path"))
        elif tool_name == "compute_convert":
            return _compute_convert(tool_input["value"], tool_input["from_unit"], tool_input["to_unit"])
        elif tool_name == "tmux_agents":
            return _tmux_agents(tool_input)
        elif tool_name == "security_scan":
            return _security_scan(tool_input["target"], tool_input.get("scan_type", "quick"),
                                  tool_input.get("agents"))
        elif tool_name == "prediction_market":
            return _prediction_market(tool_input["action"], tool_input.get("query", ""),
                                      tool_input.get("market_id", ""), tool_input.get("tag", ""),
                                      tool_input.get("limit", 10))
        elif tool_name == "get_reflections":
            return _get_reflections(tool_input["action"], tool_input.get("task", ""),
                                    tool_input.get("project"), tool_input.get("limit", 5))
        elif tool_name == "create_event":
            return _create_event(tool_input["event_type"], tool_input.get("data", {}))
        elif tool_name == "plan_my_day":
            return _plan_my_day(tool_input.get("focus", "all"))
        # ═ Perplexity research
        elif tool_name == "perplexity_research":
            return _perplexity_research(tool_input["query"], tool_input.get("model", "sonar"),
                                        tool_input.get("focus", "web"))
        # ═ News & Social Media tools
        elif tool_name == "read_ai_news":
            return _read_ai_news(tool_input.get("limit", 10), tool_input.get("source"), tool_input.get("hours", 24))
        elif tool_name == "read_tweets":
            return _read_tweets(tool_input.get("account"), tool_input.get("limit", 5))
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
    jobs = list_jobs(status=status)

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
    """Save to persistent JSONL memory store."""
    import uuid
    mem_file = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data"), "memories.jsonl")
    os.makedirs(os.path.dirname(mem_file), exist_ok=True)
    mem_id = str(uuid.uuid4())[:8]
    record = {"id": mem_id, "content": content, "tags": tags or [], "importance": importance,
              "timestamp": datetime.now(timezone.utc).isoformat()}
    with open(mem_file, "a") as f:
        f.write(json.dumps(record) + "\n")
    return f"Memory saved (id={mem_id}): {content[:80]}"


def _search_memory(query: str, limit: int = 5) -> str:
    """Search memories by keyword matching."""
    mem_file = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data"), "memories.jsonl")
    if not os.path.exists(mem_file):
        return "No memories found"
    query_lower = query.lower()
    matches = []
    with open(mem_file) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                m = json.loads(line)
                content_str = m.get("content", "").lower()
                tags_str = " ".join(m.get("tags", [])).lower()
                if query_lower in content_str or query_lower in tags_str:
                    matches.append(m)
            except: continue
    matches.sort(key=lambda m: m.get("importance", 5), reverse=True)
    if not matches:
        return f"No memories matching '{query}'"
    lines = [f"[{m['id']}] (imp={m.get('importance',5)}) {m['content'][:100]}" for m in matches[:limit]]
    return f"Found {len(matches)} memories:\n" + "\n".join(lines)


def _kill_job(job_id: str) -> str:
    """Cancel a running or pending job."""
    kill_flags_file = os.path.join(os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data"), "jobs", "kill_flags.json")
    os.makedirs(os.path.dirname(kill_flags_file), exist_ok=True)
    flags = {}
    if os.path.exists(kill_flags_file):
        with open(kill_flags_file) as f:
            flags = json.load(f)
    flags[job_id] = {"killed_at": datetime.now(timezone.utc).isoformat(), "reason": "manual"}
    with open(kill_flags_file, "w") as f:
        json.dump(flags, f)
    # Try to kill tmux pane
    subprocess.run(["tmux", "kill-window", "-t", f"job-{job_id}"], capture_output=True)
    try:
        from job_manager import update_job_status
        update_job_status(job_id, "cancelled")
    except Exception:
        pass
    return f"Kill flag set for job {job_id}"


def _agency_status() -> str:
    """Get combined agency overview."""
    parts = []
    # Active jobs
    try:
        from job_manager import list_jobs as lj
        jobs = lj(status="all")
        active = [j for j in jobs if j.get("status") in ("analyzing", "running", "pending")]
        recent_done = [j for j in jobs if j.get("status") == "done"][-5:]
        parts.append(f"Active jobs: {len(active)}")
        for j in active:
            parts.append(f"  [{j.get('status')}] {j['id'][:8]}: {j.get('task', '')[:60]}")
        parts.append(f"\nRecent completed: {len(recent_done)}")
        for j in recent_done:
            parts.append(f"  {j['id'][:8]}: {j.get('task', '')[:60]}")
    except Exception as e:
        parts.append(f"Jobs: error - {e}")
    # Costs
    try:
        from cost_tracker import get_cost_metrics
        costs = get_cost_metrics()
        parts.append(f"\nCosts today: ${costs.get('today_usd', 0):.4f}")
        parts.append(f"Costs this month: ${costs.get('month_usd', 0):.4f}")
    except Exception:
        pass
    # Tmux agents
    try:
        result = subprocess.run(["tmux", "list-windows", "-t", "openclaw", "-F", "#{window_name}"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            windows = [w for w in result.stdout.strip().split("\n") if w]
            parts.append(f"\nActive tmux agents: {len(windows)}")
            for w in windows[:10]:
                parts.append(f"  {w}")
    except Exception:
        pass
    # 7-day performance (computed from jobs.jsonl — source of truth)
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y%m%d")
        recent_all = [j for j in jobs if j.get("id", "")[4:12] >= cutoff]
        terminal = [j for j in recent_all if j.get("status") in ("done", "failed", "killed_iteration_limit", "killed_cost_limit", "killed_timeout")]
        successes = sum(1 for j in terminal if j.get("status") == "done")
        failures = len(terminal) - successes
        rate = round(successes / len(terminal) * 100, 1) if terminal else 0
        parts.append(f"\n7-day performance: {rate}% success ({successes}/{len(terminal)} jobs)")
        if failures > 0:
            fail_types = {}
            for j in terminal:
                if j.get("status") != "done":
                    s = j.get("status", "unknown")
                    fail_types[s] = fail_types.get(s, 0) + 1
            parts.append(f"  Failures: {fail_types}")
    except Exception as e:
        parts.append(f"\n7-day performance: error - {e}")
    return "\n".join(parts)


def _manage_reactions(action: str, rule_id: str = "", rule_data: dict = None) -> str:
    """Manage auto-reaction rules."""
    try:
        from reactions import get_reactions_engine
        engine = get_reactions_engine()
        if action == "list":
            rules = engine.get_rules()
            return json.dumps(rules, indent=2)
        elif action == "triggers":
            triggers = engine.get_recent_triggers()
            return json.dumps(triggers, indent=2)
        elif action == "add":
            if not rule_data:
                return "Error: rule_data required"
            new_id = engine.add_rule(rule_data)
            return f"Rule added: {new_id}"
        elif action == "update":
            if not rule_id or not rule_data:
                return "Error: rule_id and rule_data required"
            engine.update_rule(rule_id, rule_data)
            return f"Rule {rule_id} updated"
        elif action == "delete":
            if not rule_id:
                return "Error: rule_id required"
            engine.delete_rule(rule_id)
            return f"Rule {rule_id} deleted"
        return f"Unknown action: {action}"
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

    # Check blocked commands (substring match)
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"BLOCKED: '{blocked}' is not allowed"

    # Check for dangerous subshell / backtick injection patterns
    for pattern in _DANGEROUS_SUBSHELL_PATTERNS:
        if pattern.search(command):
            return False, "BLOCKED: dangerous subshell/backtick injection detected"

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


# Paths that must NEVER be written to by agents (even if inside ALLOWED_WRITE_DIRS)
BLOCKED_WRITE_PATHS = [
    "/etc/",                # System configs
    "/root/.ssh/",          # SSH keys
    "/root/.ssh",           # SSH dir itself
    "/root/.env",           # Environment secrets (edit manually only)
    "/root/.bashrc",        # Shell config
    "/root/.profile",       # Shell config
]

# Path components that block writes when found anywhere in the path
BLOCKED_PATH_COMPONENTS = [
    "/.git/",               # Git internals (objects, hooks, config)
    "/.env",                # Dotenv files anywhere
]


def _is_path_writable(path: str) -> bool:
    """Check if path is in allowed write directories and not in blocked paths."""
    abs_path = os.path.abspath(path)

    # Check blocked paths (exact prefix match)
    for blocked in BLOCKED_WRITE_PATHS:
        if abs_path == blocked.rstrip("/") or abs_path.startswith(blocked):
            return False

    # Check blocked path components (substring match)
    for component in BLOCKED_PATH_COMPONENTS:
        if component in abs_path:
            return False

    return any(abs_path.startswith(d) for d in ALLOWED_WRITE_DIRS)


def _shell_execute(command: str, cwd: str = "/root", timeout: int = 60) -> str:
    """Execute a sandboxed shell command."""
    # Sanitize cwd
    if "\x00" in cwd:
        return "⛔ Command rejected: null byte in working directory path"
    cwd = os.path.realpath(os.path.abspath(cwd))
    if not os.path.isdir(cwd):
        return f"⛔ Working directory does not exist: {cwd}"

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
            output = result.stdout.strip() + ("\n" + result.stderr.strip() if result.stderr else "")
            # Emit deploy event for auto-reactions (security scan, notifications)
            if result.returncode == 0:
                try:
                    from event_engine import get_event_engine
                    deploy_url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
                    get_event_engine().emit("deploy.complete", {
                        "project": os.path.basename(project_path),
                        "url": deploy_url,
                        "env": "production" if production else "preview",
                    })
                except Exception:
                    pass  # don't fail deploy over event emission
            return output

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


# Paths agents should never read (secrets, SSH keys, etc.)
BLOCKED_READ_PATHS = [
    "/root/.ssh/",
    "/root/.env",
    "/etc/shadow",
]


def _file_read(path: str, lines: int = None, offset: int = 0) -> str:
    """Read file contents with optional line limits."""
    try:
        abs_path, err = _sanitize_path(path)
        if err:
            return f"⛔ {err}"
        # Block reading sensitive files
        for blocked in BLOCKED_READ_PATHS:
            if abs_path == blocked.rstrip("/") or abs_path.startswith(blocked):
                return f"⛔ Access denied: reading {path} is not permitted"
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


def _sanitize_path(path: str) -> tuple[str, str | None]:
    """Sanitize a file path. Returns (abs_path, error_msg_or_None)."""
    # Block null bytes (can truncate paths in C-based libs)
    if "\x00" in path:
        return "", "BLOCKED: null byte in path"
    # Resolve to absolute, collapsing any ../
    abs_path = os.path.realpath(os.path.abspath(path))
    return abs_path, None


def _file_write(path: str, content: str, mode: str = "write") -> str:
    """Write or append to a file."""
    try:
        abs_path, err = _sanitize_path(path)
        if err:
            return f"⛔ {err}"
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


# ═══════════════════════════════════════════════════════════════════════════
# CODE EDITING TOOLS — Edit, Glob, Grep, Process, Env
# ═══════════════════════════════════════════════════════════════════════════

def _file_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Find and replace a string in a file (surgical edit, not overwrite)."""
    try:
        abs_path, err = _sanitize_path(path)
        if err:
            return f"⛔ {err}"
        if not os.path.exists(abs_path):
            return f"File not found: {path}"
        if not _is_path_writable(abs_path):
            return f"⛔ Path not writable: {path}"

        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()

        if old_string not in content:
            return f"⛔ String not found in {path}. Make sure old_string matches exactly (including whitespace/indentation)."

        if not replace_all:
            count = content.count(old_string)
            if count > 1:
                return f"⛔ Found {count} occurrences of old_string — must be unique. Add more context to make it unique, or set replace_all=true."
            new_content = content.replace(old_string, new_string, 1)
        else:
            count = content.count(old_string)
            new_content = content.replace(old_string, new_string)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        replaced = content.count(old_string) if replace_all else 1
        return f"✅ Edited {path}: replaced {replaced} occurrence(s) ({len(new_content)} bytes written)"
    except Exception as e:
        return f"Edit error: {e}"


def _glob_files(pattern: str, path: str = "/root", max_results: int = 50) -> str:
    """Find files matching a glob pattern."""
    import glob as glob_mod

    try:
        # Skip directories that produce massive results
        skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".cache"}
        search_pattern = os.path.join(path, pattern)

        # Use iglob iterator so we can cap the scan early
        matches = []
        scan_limit = max_results * 20  # Scan at most 20x the requested results
        for i, m in enumerate(glob_mod.iglob(search_pattern, recursive=True)):
            if i >= scan_limit:
                break
            # Skip files inside heavy directories
            parts = set(Path(m).parts)
            if parts & skip_dirs:
                continue
            if os.path.isfile(m):
                matches.append(m)

        if not matches:
            return f"No files matching '{pattern}' in {path}"

        # Sort by modification time (newest first) — only on the capped list
        matches.sort(key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)
        matches = matches[:max_results]

        lines = []
        for m in matches:
            try:
                size = os.path.getsize(m)
                mtime = os.path.getmtime(m)
                from datetime import datetime
                dt = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                size_str = f"{size:>8,}" if size < 1_000_000 else f"{size/1_000_000:.1f}M"
                lines.append(f"{size_str}  {dt}  {m}")
            except Exception:
                lines.append(f"           {m}")

        header = f"Found {len(matches)} files matching '{pattern}':"
        return header + "\n" + "\n".join(lines)
    except Exception as e:
        return f"Glob error: {e}"


def _grep_search(pattern: str, path: str = "/root", file_pattern: str = "",
                 context_lines: int = 2, max_results: int = 20) -> str:
    """Search file contents using grep/ripgrep."""
    try:
        # Prefer ripgrep (rg) if available, else fallback to grep
        rg = shutil.which("rg")

        if rg:
            cmd = [rg, "--no-heading", "-n", f"-C{context_lines}", f"-m{max_results}"]
            if file_pattern:
                cmd.extend(["-g", file_pattern])
            cmd.extend([pattern, path])
        else:
            cmd = ["grep", "-rn", f"-C{context_lines}", f"-m{max_results}"]
            if file_pattern:
                cmd.extend(["--include", file_pattern])
            cmd.extend([pattern, path])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()

        if not output:
            return f"No matches for '{pattern}' in {path}"

        # Truncate if too long
        if len(output) > MAX_SHELL_OUTPUT:
            output = output[:MAX_SHELL_OUTPUT] + f"\n... [truncated, showing first {MAX_SHELL_OUTPUT} chars]"

        match_count = output.count("\n") + 1
        return f"Found matches ({match_count} lines):\n{output}"
    except subprocess.TimeoutExpired:
        return "Search timed out"
    except Exception as e:
        return f"Grep error: {e}"


def _process_manage(action: str, target: str = "", signal: str = "TERM") -> str:
    """Manage running processes."""
    try:
        if action == "list":
            # List running processes (filtered if target provided)
            if target:
                result = subprocess.run(
                    ["pgrep", "-a", "-f", target],
                    capture_output=True, text=True, timeout=5
                )
            else:
                result = subprocess.run(
                    ["ps", "aux", "--sort=-pcpu"],
                    capture_output=True, text=True, timeout=5
                )
            output = result.stdout.strip()
            return output[:3000] if output else "No matching processes"

        elif action == "kill":
            if not target:
                return "Error: target (PID or process name) required"
            sig = {"TERM": "15", "KILL": "9", "HUP": "1"}.get(signal, "15")

            # Try as PID first
            if target.isdigit():
                result = subprocess.run(
                    ["kill", f"-{sig}", target],
                    capture_output=True, text=True, timeout=5
                )
            else:
                # Kill by name
                result = subprocess.run(
                    ["pkill", f"-{sig}", "-f", target],
                    capture_output=True, text=True, timeout=5
                )
            if result.returncode == 0:
                return f"✅ Sent SIG{signal} to {target}"
            else:
                return f"Failed to kill {target}: {result.stderr.strip()}"

        elif action == "check_port":
            if not target:
                return "Error: port number required"
            result = subprocess.run(
                ["fuser", f"{target}/tcp"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                pids = result.stdout.strip()
                # Get process details
                details = subprocess.run(
                    ["ps", "-p", pids.replace(" ", ","), "-o", "pid,comm,args"],
                    capture_output=True, text=True, timeout=5
                )
                return f"Port {target} used by PID(s): {pids}\n{details.stdout.strip()}"
            return f"Port {target} is free"

        elif action == "top":
            result = subprocess.run(
                ["ps", "aux", "--sort=-pcpu"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")
            return "\n".join(lines[:15])  # Top 15 processes

        return f"Unknown action: {action}"
    except Exception as e:
        return f"Process error: {e}"


def _env_manage(action: str, key: str = "", value: str = "",
                env_file: str = "/root/.env", filter_str: str = "") -> str:
    """Manage environment variables and .env files."""
    try:
        if action == "get":
            if not key:
                return "Error: key required"
            val = os.environ.get(key, "")
            if val:
                # Mask secrets
                if any(s in key.upper() for s in ["KEY", "TOKEN", "SECRET", "PASSWORD"]):
                    return f"{key}={val[:8]}...{val[-4:]}" if len(val) > 12 else f"{key}=***"
                return f"{key}={val}"
            return f"{key} not set"

        elif action == "set":
            if not key or not value:
                return "Error: key and value required"
            os.environ[key] = value
            return f"✅ Set {key} in current process"

        elif action == "list":
            env_vars = sorted(os.environ.items())
            if filter_str:
                env_vars = [(k, v) for k, v in env_vars if filter_str.upper() in k.upper()]
            lines = []
            for k, v in env_vars[:50]:
                if any(s in k.upper() for s in ["KEY", "TOKEN", "SECRET", "PASSWORD"]):
                    v_display = f"{v[:8]}..." if len(v) > 8 else "***"
                else:
                    v_display = v[:80]
                lines.append(f"{k}={v_display}")
            return f"Environment variables ({len(lines)}):\n" + "\n".join(lines)

        elif action == "load_dotenv":
            if not os.path.exists(env_file):
                return f"File not found: {env_file}"
            loaded = 0
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip()
                        loaded += 1
            return f"✅ Loaded {loaded} vars from {env_file}"

        elif action == "save_dotenv":
            if not key or not value:
                return "Error: key and value required to save"
            if not _is_path_writable(env_file):
                return f"⛔ Cannot write to {env_file}"

            # Read existing, update or append
            lines = []
            found = False
            if os.path.exists(env_file):
                with open(env_file, "r") as f:
                    for line in f:
                        if line.strip().startswith(f"{key}="):
                            lines.append(f"{key}={value}\n")
                            found = True
                        else:
                            lines.append(line)
            if not found:
                lines.append(f"{key}={value}\n")

            with open(env_file, "w") as f:
                f.writelines(lines)
            return f"✅ Saved {key} to {env_file}"

        return f"Unknown action: {action}"
    except Exception as e:
        return f"Env error: {e}"


# ═══════════════════════════════════════════════════════════════
# COMPUTE TOOL IMPLEMENTATIONS — Precise algorithms
# ═══════════════════════════════════════════════════════════════

def _compute_sort(data: list, algorithm: str = "auto", reverse: bool = False, key: str = None) -> str:
    """Sort data using O(n log n) algorithms with timing."""
    import time
    import heapq
    try:
        n = len(data)
        if n == 0:
            return "[]  (empty input)"

        # If data contains dicts and key specified, extract sort key
        if key and isinstance(data[0], dict):
            keyfunc = lambda x: x.get(key, 0)
        else:
            keyfunc = None

        start = time.perf_counter_ns()

        if algorithm == "mergesort":
            # Pure mergesort implementation
            def mergesort(arr):
                if len(arr) <= 1:
                    return arr
                mid = len(arr) // 2
                left = mergesort(arr[:mid])
                right = mergesort(arr[mid:])
                return merge(left, right)
            def merge(l, r):
                result, i, j = [], 0, 0
                while i < len(l) and j < len(r):
                    lv = l[i].get(key, 0) if key and isinstance(l[i], dict) else l[i]
                    rv = r[j].get(key, 0) if key and isinstance(r[j], dict) else r[j]
                    if lv <= rv:
                        result.append(l[i]); i += 1
                    else:
                        result.append(r[j]); j += 1
                result.extend(l[i:]); result.extend(r[j:])
                return result
            result = mergesort(list(data))
            if reverse:
                result.reverse()

        elif algorithm == "heapsort":
            if keyfunc:
                decorated = [(keyfunc(x), i, x) for i, x in enumerate(data)]
                heapq.heapify(decorated)
                result = [heapq.heappop(decorated)[2] for _ in range(len(decorated))]
            else:
                heap = list(data)
                heapq.heapify(heap)
                result = [heapq.heappop(heap) for _ in range(len(heap))]
            if reverse:
                result.reverse()

        else:  # auto / quicksort / timsort — Python's Timsort is optimal
            result = sorted(data, key=keyfunc, reverse=reverse)

        elapsed_ns = time.perf_counter_ns() - start
        elapsed_ms = elapsed_ns / 1_000_000

        # Format output
        preview = json.dumps(result[:100])
        if n > 100:
            preview = preview[:-1] + f", ... ({n - 100} more)]"

        algo_used = algorithm if algorithm != "auto" else "timsort"
        return f"Sorted {n} items ({algo_used}, O(n·log·n)) in {elapsed_ms:.3f}ms\n{preview}"
    except Exception as e:
        return f"Sort error: {e}"


def _compute_stats(data: list, percentiles: list = None) -> str:
    """Calculate comprehensive statistics."""
    import statistics
    import math
    try:
        n = len(data)
        if n == 0:
            return "Error: empty dataset"

        nums = [float(x) for x in data]
        result = {
            "count": n,
            "sum": sum(nums),
            "min": min(nums),
            "max": max(nums),
            "range": max(nums) - min(nums),
            "mean": statistics.mean(nums),
            "median": statistics.median(nums),
        }

        if n >= 2:
            result["std_dev"] = statistics.stdev(nums)
            result["variance"] = statistics.variance(nums)
            result["pop_std_dev"] = statistics.pstdev(nums)

        try:
            result["mode"] = statistics.mode(nums)
        except statistics.StatisticsError:
            result["mode"] = "no unique mode"

        if n >= 4:
            sorted_nums = sorted(nums)
            q1_idx = n // 4
            q3_idx = (3 * n) // 4
            result["q1"] = sorted_nums[q1_idx]
            result["q3"] = sorted_nums[q3_idx]
            result["iqr"] = sorted_nums[q3_idx] - sorted_nums[q1_idx]

        # Custom percentiles
        if percentiles:
            sorted_nums = sorted(nums)
            pct_results = {}
            for p in percentiles:
                idx = int(p / 100 * (n - 1))
                pct_results[f"p{p}"] = sorted_nums[min(idx, n - 1)]
            result["percentiles"] = pct_results

        lines = [f"Statistics for {n} values:"]
        for k, v in result.items():
            if isinstance(v, float):
                lines.append(f"  {k}: {v:.6f}")
            elif isinstance(v, dict):
                for pk, pv in v.items():
                    lines.append(f"  {pk}: {pv:.6f}" if isinstance(pv, float) else f"  {pk}: {pv}")
            else:
                lines.append(f"  {k}: {v}")
        return "\n".join(lines)
    except Exception as e:
        return f"Stats error: {e}"


def _compute_math(expression: str, precision: int = 10) -> str:
    """Evaluate math expressions safely."""
    import math
    try:
        # Allowed names for eval
        safe_names = {
            "math": math, "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "len": len, "pow": pow, "int": int, "float": float,
            "pi": math.pi, "e": math.e, "inf": math.inf, "tau": math.tau,
            "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
            "ceil": math.ceil, "floor": math.floor,
            "factorial": math.factorial, "gcd": math.gcd, "lcm": math.lcm,
            "comb": math.comb, "perm": math.perm,
            "radians": math.radians, "degrees": math.degrees,
            "isqrt": math.isqrt, "exp": math.exp,
            "True": True, "False": False,
        }

        # Block dangerous builtins
        for blocked in ["import", "__", "exec", "eval", "open", "compile", "globals", "locals", "getattr", "setattr", "delattr"]:
            if blocked in expression:
                return f"Error: '{blocked}' not allowed in expressions"

        result = eval(expression, {"__builtins__": {}}, safe_names)

        if isinstance(result, float):
            if result == int(result) and abs(result) < 10**15:
                return f"{expression} = {int(result)}"
            return f"{expression} = {result:.{precision}f}"
        return f"{expression} = {result}"
    except Exception as e:
        return f"Math error: {e}"


def _compute_search(data: list, target=None, method: str = "linear", condition: str = None) -> str:
    """Search/filter data using various algorithms."""
    import bisect
    import re
    import time
    try:
        n = len(data)
        start = time.perf_counter_ns()

        if method == "binary":
            if target is None:
                return "Error: target required for binary search"
            idx = bisect.bisect_left(data, target)
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            if idx < n and data[idx] == target:
                return f"Found {target} at index {idx} (binary search, O(log n)) in {elapsed:.3f}ms"
            return f"{target} not found (binary search, checked {n} items) in {elapsed:.3f}ms"

        elif method == "filter":
            if not condition:
                return "Error: condition required for filter (e.g. 'x > 50')"
            for blocked in ["import", "__", "exec", "eval", "open"]:
                if blocked in condition:
                    return f"Error: '{blocked}' not allowed"
            results = [x for x in data if eval(condition, {"__builtins__": {}}, {"x": x})]
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            preview = json.dumps(results[:50])
            return f"Filter '{condition}': {len(results)}/{n} items matched in {elapsed:.3f}ms\n{preview}"

        elif method == "regex":
            if target is None:
                return "Error: target (regex pattern) required"
            pattern = re.compile(str(target))
            results = [x for x in data if pattern.search(str(x))]
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            return f"Regex '{target}': {len(results)}/{n} matched in {elapsed:.3f}ms\n{json.dumps(results[:50])}"

        else:  # linear
            if target is None:
                return "Error: target required for linear search"
            indices = [i for i, x in enumerate(data) if x == target]
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            if indices:
                return f"Found {target} at {len(indices)} position(s): {indices[:20]} (linear, O(n)) in {elapsed:.3f}ms"
            return f"{target} not found (linear search, {n} items) in {elapsed:.3f}ms"
    except Exception as e:
        return f"Search error: {e}"


def _compute_matrix(action: str, matrix_a: list, matrix_b: list = None) -> str:
    """Matrix operations — pure Python, no numpy required."""
    try:
        a = [[float(c) for c in row] for row in matrix_a]
        rows_a, cols_a = len(a), len(a[0])

        if action == "transpose":
            result = [[a[j][i] for j in range(rows_a)] for i in range(cols_a)]
            return f"Transpose ({rows_a}x{cols_a} → {cols_a}x{rows_a}):\n{json.dumps(result)}"

        elif action == "multiply":
            if not matrix_b:
                return "Error: matrix_b required for multiply"
            b = [[float(c) for c in row] if isinstance(row, list) else [float(row)] for row in matrix_b]
            rows_b, cols_b = len(b), len(b[0])
            if cols_a != rows_b:
                return f"Error: incompatible dimensions {rows_a}x{cols_a} * {rows_b}x{cols_b}"
            result = [[sum(a[i][k] * b[k][j] for k in range(cols_a)) for j in range(cols_b)] for i in range(rows_a)]
            return f"Product ({rows_a}x{cols_a} * {rows_b}x{cols_b} = {rows_a}x{cols_b}):\n{json.dumps(result)}"

        elif action == "determinant":
            if rows_a != cols_a:
                return "Error: determinant requires square matrix"
            def det(m):
                n = len(m)
                if n == 1: return m[0][0]
                if n == 2: return m[0][0]*m[1][1] - m[0][1]*m[1][0]
                d = 0
                for j in range(n):
                    sub = [[m[i][k] for k in range(n) if k != j] for i in range(1, n)]
                    d += ((-1)**j) * m[0][j] * det(sub)
                return d
            d = det(a)
            return f"Determinant of {rows_a}x{cols_a} matrix = {d}"

        elif action == "inverse":
            if rows_a != cols_a:
                return "Error: inverse requires square matrix"
            n = rows_a
            # Augment with identity
            aug = [row + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
            for col in range(n):
                max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
                aug[col], aug[max_row] = aug[max_row], aug[col]
                if abs(aug[col][col]) < 1e-12:
                    return "Error: matrix is singular (no inverse)"
                pivot = aug[col][col]
                aug[col] = [x / pivot for x in aug[col]]
                for row in range(n):
                    if row != col:
                        factor = aug[row][col]
                        aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(2 * n)]
            inv = [row[n:] for row in aug]
            return f"Inverse of {n}x{n} matrix:\n{json.dumps([[round(c, 8) for c in row] for row in inv])}"

        elif action == "solve":
            if not matrix_b:
                return "Error: matrix_b (vector b) required for solve Ax=b"
            b_vec = [float(x) if not isinstance(x, list) else float(x[0]) for x in matrix_b]
            n = rows_a
            aug = [list(a[i]) + [b_vec[i]] for i in range(n)]
            for col in range(n):
                max_row = max(range(col, n), key=lambda r: abs(aug[r][col]))
                aug[col], aug[max_row] = aug[max_row], aug[col]
                if abs(aug[col][col]) < 1e-12:
                    return "Error: system has no unique solution"
                pivot = aug[col][col]
                aug[col] = [x / pivot for x in aug[col]]
                for row in range(n):
                    if row != col:
                        factor = aug[row][col]
                        aug[row] = [aug[row][k] - factor * aug[col][k] for k in range(n + 1)]
            solution = [round(aug[i][n], 8) for i in range(n)]
            return f"Solution x = {solution}"

        elif action == "eigenvalues":
            if rows_a != cols_a:
                return "Error: eigenvalues require square matrix"
            if rows_a == 2:
                trace = a[0][0] + a[1][1]
                det_val = a[0][0]*a[1][1] - a[0][1]*a[1][0]
                disc = trace**2 - 4*det_val
                if disc >= 0:
                    e1 = (trace + disc**0.5) / 2
                    e2 = (trace - disc**0.5) / 2
                    return f"Eigenvalues: [{round(e1, 8)}, {round(e2, 8)}]"
                else:
                    real = trace / 2
                    imag = (-disc)**0.5 / 2
                    return f"Eigenvalues: [{real:.8f} + {imag:.8f}i, {real:.8f} - {imag:.8f}i]"
            return "Eigenvalues for matrices >2x2 require numpy (not installed). Use 2x2 matrices or install numpy."

        return f"Unknown matrix action: {action}"
    except Exception as e:
        return f"Matrix error: {e}"


def _compute_prime(action: str, n: int, limit: int = None) -> str:
    """Prime number operations."""
    try:
        if action == "is_prime":
            if n < 2:
                return f"{n} is NOT prime"
            if n < 4:
                return f"{n} IS prime"
            if n % 2 == 0:
                return f"{n} is NOT prime (divisible by 2)"
            i = 3
            while i * i <= n:
                if n % i == 0:
                    return f"{n} is NOT prime (divisible by {i})"
                i += 2
            return f"{n} IS prime"

        elif action == "factorize":
            if n < 2:
                return f"{n} has no prime factorization"
            factors = []
            d = 2
            temp = n
            while d * d <= temp:
                while temp % d == 0:
                    factors.append(d)
                    temp //= d
                d += 1
            if temp > 1:
                factors.append(temp)
            # Format as exponents
            from collections import Counter
            counts = Counter(factors)
            factored = " × ".join(f"{p}^{e}" if e > 1 else str(p) for p, e in sorted(counts.items()))
            return f"{n} = {factored}  (factors: {factors})"

        elif action == "generate":
            upper = limit if limit else n
            if upper > 10_000_000:
                return "Error: limit too large (max 10M for sieve)"
            # Sieve of Eratosthenes — O(n log log n)
            sieve = [True] * (upper + 1)
            sieve[0] = sieve[1] = False
            for i in range(2, int(upper**0.5) + 1):
                if sieve[i]:
                    for j in range(i*i, upper + 1, i):
                        sieve[j] = False
            primes = [i for i, is_p in enumerate(sieve) if is_p]
            count = len(primes)
            preview = primes[:100]
            result = f"Found {count} primes up to {upper}\n{preview}"
            if count > 100:
                result += f"\n... and {count - 100} more"
            return result

        elif action == "nth_prime":
            if n > 500_000:
                return "Error: n too large (max 500K)"
            count = 0
            candidate = 2
            while True:
                is_p = True
                if candidate < 2:
                    is_p = False
                elif candidate == 2:
                    is_p = True
                elif candidate % 2 == 0:
                    is_p = False
                else:
                    i = 3
                    while i * i <= candidate:
                        if candidate % i == 0:
                            is_p = False
                            break
                        i += 2
                if is_p:
                    count += 1
                    if count == n:
                        return f"The {n}th prime is {candidate}"
                candidate += 1

        return f"Unknown prime action: {action}"
    except Exception as e:
        return f"Prime error: {e}"


def _compute_hash(data: str = "", algorithm: str = "sha256", file_path: str = None) -> str:
    """Compute cryptographic hashes."""
    import hashlib
    try:
        h = hashlib.new(algorithm)

        if file_path:
            if not os.path.exists(file_path):
                return f"File not found: {file_path}"
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    h.update(chunk)
            size = os.path.getsize(file_path)
            return f"{algorithm}({file_path}) [{size} bytes] = {h.hexdigest()}"

        if not data:
            return "Error: provide data string or file_path"

        h.update(data.encode("utf-8"))
        return f"{algorithm}(\"{data[:50]}{'...' if len(data) > 50 else ''}\") = {h.hexdigest()}"
    except Exception as e:
        return f"Hash error: {e}"


def _compute_convert(value, from_unit: str, to_unit: str) -> str:
    """Unit and base conversions."""
    try:
        from_u = from_unit.lower().strip()
        to_u = to_unit.lower().strip()

        # Number base conversions
        base_map = {"bin": 2, "binary": 2, "oct": 8, "octal": 8, "dec": 10, "decimal": 10, "hex": 16, "hexadecimal": 16}
        if from_u in base_map and to_u in base_map:
            num = int(str(value), base_map[from_u])
            if base_map[to_u] == 2:
                result = bin(num)
            elif base_map[to_u] == 8:
                result = oct(num)
            elif base_map[to_u] == 16:
                result = hex(num)
            else:
                result = str(num)
            return f"{value} (base {base_map[from_u]}) = {result} (base {base_map[to_u]})"

        v = float(value)

        # Temperature
        temp_conversions = {
            ("celsius", "fahrenheit"): lambda c: c * 9/5 + 32,
            ("fahrenheit", "celsius"): lambda f: (f - 32) * 5/9,
            ("celsius", "kelvin"): lambda c: c + 273.15,
            ("kelvin", "celsius"): lambda k: k - 273.15,
            ("fahrenheit", "kelvin"): lambda f: (f - 32) * 5/9 + 273.15,
            ("kelvin", "fahrenheit"): lambda k: (k - 273.15) * 9/5 + 32,
        }
        if (from_u, to_u) in temp_conversions:
            result = temp_conversions[(from_u, to_u)](v)
            return f"{v} {from_u} = {result:.4f} {to_u}"

        # Data sizes
        data_units = {"bits": 1, "bytes": 8, "kb": 8*1024, "mb": 8*1024**2, "gb": 8*1024**3, "tb": 8*1024**4, "kib": 8*1024, "mib": 8*1024**2, "gib": 8*1024**3}
        if from_u in data_units and to_u in data_units:
            bits = v * data_units[from_u]
            result = bits / data_units[to_u]
            return f"{v} {from_unit} = {result:.6f} {to_unit}"

        # Distance
        dist_m = {"m": 1, "meters": 1, "km": 1000, "mi": 1609.344, "miles": 1609.344, "ft": 0.3048, "feet": 0.3048, "in": 0.0254, "inches": 0.0254, "cm": 0.01, "mm": 0.001, "yd": 0.9144, "yards": 0.9144, "nm": 1852, "nautical_miles": 1852}
        if from_u in dist_m and to_u in dist_m:
            meters = v * dist_m[from_u]
            result = meters / dist_m[to_u]
            return f"{v} {from_unit} = {result:.6f} {to_unit}"

        # Weight
        weight_kg = {"kg": 1, "g": 0.001, "mg": 0.000001, "lb": 0.453592, "lbs": 0.453592, "oz": 0.0283495, "ton": 907.185, "tonne": 1000, "st": 6.35029}
        if from_u in weight_kg and to_u in weight_kg:
            kg = v * weight_kg[from_u]
            result = kg / weight_kg[to_u]
            return f"{v} {from_unit} = {result:.6f} {to_unit}"

        # Timestamp conversions
        if from_u == "unix_timestamp" and to_u == "iso8601":
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(v, tz=timezone.utc)
            return f"{value} unix = {dt.isoformat()}"
        if from_u == "iso8601" and to_u == "unix_timestamp":
            from datetime import datetime
            dt = datetime.fromisoformat(str(value))
            return f"{value} = {dt.timestamp()} unix"

        return f"Unknown conversion: {from_unit} → {to_unit}"
    except Exception as e:
        return f"Convert error: {e}"


# ═══════════════════════════════════════════════════════════════
# Tmux Agent Spawning (Elvis pattern)
# ═══════════════════════════════════════════════════════════════

def _tmux_agents(tool_input: dict) -> str:
    """Manage parallel Claude Code agents in tmux panes."""
    try:
        from tmux_spawner import get_spawner
        spawner = get_spawner()
        action = tool_input["action"]

        if action == "spawn":
            job_id = tool_input.get("job_id")
            prompt = tool_input.get("prompt")
            if not job_id or not prompt:
                return "Error: spawn requires job_id and prompt"
            pane_id = spawner.spawn_agent(
                job_id=job_id,
                prompt=prompt,
                worktree_repo=tool_input.get("worktree_repo"),
                use_worktree=tool_input.get("use_worktree", False),
                cwd=tool_input.get("cwd"),
                timeout_minutes=tool_input.get("timeout_minutes", 30),
            )
            return json.dumps({"status": "spawned", "pane_id": pane_id, "job_id": job_id})

        elif action == "spawn_parallel":
            jobs = tool_input.get("jobs", [])
            if not jobs:
                return "Error: spawn_parallel requires jobs list"
            results = spawner.spawn_parallel(jobs)
            spawned = sum(1 for r in results if r["status"] == "spawned")
            return json.dumps({"spawned": spawned, "total": len(jobs), "results": results})

        elif action == "list":
            agents = spawner.list_agents()
            return json.dumps({"count": len(agents), "agents": agents})

        elif action == "output":
            pane_id = tool_input.get("pane_id")
            if not pane_id:
                return "Error: output requires pane_id"
            output = spawner.collect_output(pane_id)
            status = spawner.get_agent_status(pane_id)
            return json.dumps({
                "pane_id": pane_id,
                "output": output[:10000],  # Cap output size
                "status": status,
            })

        elif action == "kill":
            pane_id = tool_input.get("pane_id")
            if not pane_id:
                return "Error: kill requires pane_id"
            killed = spawner.kill_agent(pane_id)
            return json.dumps({"killed": killed, "pane_id": pane_id})

        elif action == "kill_all":
            count = spawner.kill_all()
            return json.dumps({"killed": count})

        elif action == "cleanup":
            job_id = tool_input.get("job_id")
            if not job_id:
                return "Error: cleanup requires job_id"
            spawner.cleanup(job_id)
            return json.dumps({"cleaned": True, "job_id": job_id})

        else:
            return f"Unknown tmux_agents action: {action}"

    except Exception as e:
        return f"Error: {e}"


# ═══════════════════════════════════════════════════════════════
# Security Scan (OXO / Ostorlab)
# ═══════════════════════════════════════════════════════════════

SCAN_PROFILES = {
    "quick": ["agent/ostorlab/nmap"],
    "full": ["agent/ostorlab/nmap", "agent/ostorlab/nuclei"],
    "web": ["agent/ostorlab/nmap", "agent/ostorlab/nuclei", "agent/ostorlab/zap"],
}


def _security_scan(target: str, scan_type: str = "quick", agents: list = None) -> str:
    """Run an OXO security scan against a target."""
    import re

    if not shutil.which("oxo"):
        return "Error: oxo CLI not installed. Install with: pip3 install ostorlab"

    # Validate target
    target = target.strip()
    if not target:
        return "Error: target is required"

    # Determine asset type
    if re.match(r"^https?://", target):
        asset_flag = ["--url", target]
    elif re.match(r"^\d{1,3}(\.\d{1,3}){3}$", target):
        asset_flag = ["--ip", target]
    elif re.match(r"^\d{1,3}(\.\d{1,3}){3}/\d+$", target):
        asset_flag = ["--ip-range", target]
    else:
        asset_flag = ["--domain", target]

    # Pick agents
    agent_list = agents or SCAN_PROFILES.get(scan_type, SCAN_PROFILES["quick"])

    # Build command
    cmd = ["oxo", "scan", "run"]
    for agent_key in agent_list:
        cmd.extend(["--agent", agent_key])
    cmd.extend(asset_flag)

    try:
        logger.info(f"Starting OXO scan: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        output = result.stdout.strip()
        if result.stderr:
            output += f"\n{result.stderr.strip()}"

        # Emit scan event
        try:
            from event_engine import get_event_engine
            event_type = "scan.completed" if result.returncode == 0 else "scan.failed"
            get_event_engine().emit(event_type, {
                "target": target,
                "scan_type": scan_type,
                "agents": agent_list,
            })
        except Exception:
            pass

        return output or "Scan completed (no output)"
    except subprocess.TimeoutExpired:
        return "Scan timed out after 5 minutes. Try a 'quick' scan or specific agents."
    except Exception as e:
        return f"Scan error: {e}"


def _prediction_market(action: str, query: str, market_id: str, tag: str, limit: int) -> str:
    """Query Polymarket prediction markets via CLI."""
    try:
        if action == "search":
            if not query:
                return "Error: 'query' is required for search action"
            cmd = ["polymarket", "markets", "search", query, "-o", "json"]
        elif action == "get_market":
            if not market_id:
                return "Error: 'market_id' is required for get_market action"
            cmd = ["polymarket", "markets", "get", market_id, "-o", "json"]
        elif action == "list_markets":
            cmd = ["polymarket", "markets", "list", "-o", "json"]
        elif action == "list_events":
            cmd = ["polymarket", "events", "list", "-o", "json"]
            if tag:
                cmd.extend(["--tag", tag])
        else:
            return f"Unknown action: {action}. Use: search, get_market, list_markets, list_events"

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output = result.stderr.strip() if not output else f"{output}\n{result.stderr.strip()}"

        if not output:
            return "No results returned"

        # Cap output size
        if len(output) > MAX_SHELL_OUTPUT:
            output = output[:MAX_SHELL_OUTPUT] + "\n... (truncated)"

        return output
    except subprocess.TimeoutExpired:
        return "Polymarket query timed out after 30 seconds"
    except FileNotFoundError:
        return "Error: polymarket CLI not installed. Run: curl -sSL https://raw.githubusercontent.com/Polymarket/polymarket-cli/main/install.sh | sh"
    except Exception as e:
        return f"Prediction market error: {e}"


def _get_reflections(action: str, task: str = "", project: str = None, limit: int = 5) -> str:
    """Get past job reflections — learnings from completed/failed jobs."""
    try:
        from reflexion import get_stats, list_reflections, search_reflections, format_reflections_for_prompt

        if action == "stats":
            stats = get_stats()
            return json.dumps(stats, indent=2)

        elif action == "list":
            refs = list_reflections(project=project, limit=limit)
            if not refs:
                return "No reflections found."
            lines = [f"Reflections ({len(refs)} total):"]
            for r in refs:
                outcome = "SUCCESS" if r.get("outcome") == "success" else "FAILED"
                lines.append(
                    f"  [{outcome}] {r.get('job_id', '?')} — {r.get('task', '?')[:80]} "
                    f"(project={r.get('project', '?')}, {r.get('duration_seconds', 0):.0f}s)"
                )
            return "\n".join(lines)

        elif action == "search":
            if not task:
                return "Error: 'task' parameter required for search action"
            refs = search_reflections(task, project=project, limit=limit)
            if not refs:
                return "No relevant reflections found for this task."
            return format_reflections_for_prompt(refs)

        else:
            return f"Unknown action: {action}. Use: stats, list, search"

    except Exception as e:
        return f"Reflections error: {e}"


def _create_event(event_type: str, data: dict) -> str:
    """Emit an event to the OpenClaw event engine."""
    try:
        import requests as req
        resp = req.post(
            "http://localhost:18789/api/events",
            json={"event_type": event_type, "data": data},
            timeout=10,
        )
        return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return f"Error creating event: {e}"


def _plan_my_day(focus: str = "all") -> str:
    """Gather calendar, jobs, agency status, and emails for a daily plan."""
    try:
        import requests as req
        gw = "http://localhost:18789"
        results = {}

        # Calendar
        try:
            r = req.get(f"{gw}/api/calendar/today", timeout=10)
            results["calendar"] = r.json() if r.ok else {"events": []}
        except Exception:
            results["calendar"] = {"events": []}

        # Jobs
        try:
            r = req.get(f"{gw}/api/jobs?limit=20", timeout=10)
            jobs = r.json().get("jobs", []) if r.ok else []
            results["pending_jobs"] = [j for j in jobs if j.get("status") in ("pending", "analyzing")]
            results["active_jobs"] = [j for j in jobs if j.get("status") in ("running", "in_progress")]
            results["recent_completed"] = [j for j in jobs if j.get("status") == "done"][:5]
        except Exception:
            results["pending_jobs"] = []
            results["active_jobs"] = []
            results["recent_completed"] = []

        # Agency status
        try:
            r = req.get(f"{gw}/api/agency/status", timeout=10)
            results["agency_status"] = r.json() if r.ok else {}
        except Exception:
            results["agency_status"] = {}

        # Emails
        try:
            r = req.get(f"{gw}/api/gmail/inbox?max_results=10", timeout=10)
            results["unread_emails"] = r.json().get("messages", []) if r.ok else []
        except Exception:
            results["unread_emails"] = []

        results["focus"] = focus

        # AI News Highlights
        try:
            news = _read_ai_news(limit=5, source=None, hours=24)
            results["ai_news_highlights"] = news
        except Exception:
            results["ai_news_highlights"] = "Could not fetch AI news"

        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Error planning day: {e}"


# ═══════════════════════════════════════════════════════════════
# NEWS & SOCIAL MEDIA IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "openai": "https://openai.com/blog/rss.xml",
    "deepmind": "https://deepmind.google/blog/rss.xml",
    "huggingface": "https://huggingface.co/blog/feed.xml",
    "arxiv": "https://rss.arxiv.org/rss/cs.AI",
    "verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "techcrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "hackernews": "https://hnrss.org/frontpage?q=AI+OR+LLM+OR+GPT+OR+Claude+OR+machine+learning",
    "mittech": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
}

NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://xcancel.com",
]

AI_TWITTER_ACCOUNTS = [
    "AnthropicAI",
    "OpenAI",
    "GoogleDeepMind",
    "ylecun",
    "sama",
    "kaboragora",
]

# Bluesky AT Protocol — free public API, no auth needed
BLUESKY_API = "https://public.api.bsky.app/xrpc"
BLUESKY_ACCOUNTS = [
    "sama.bsky.social",
    "karpathy.bsky.social",
    "jimfan.bsky.social",
    "huggingface.bsky.social",
    "deepmind.bsky.social",
]

# Map Twitter handles to Bluesky handles where available
TWITTER_TO_BLUESKY = {
    "sama": "sama.bsky.social",
    "karpathy": "karpathy.bsky.social",
    "jimfan": "jimfan.bsky.social",
}

# Reddit AI subreddits (native RSS, no auth needed, very reliable)
REDDIT_AI_FEEDS = [
    "https://www.reddit.com/r/MachineLearning/hot/.rss",
    "https://www.reddit.com/r/artificial/hot/.rss",
    "https://www.reddit.com/r/LocalLLaMA/hot/.rss",
]


def _perplexity_research(query: str, model: str = "sonar", focus: str = "web") -> str:
    """Deep research using Perplexity Sonar API — returns AI-synthesized answers with citations."""
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        return json.dumps({
            "error": "PERPLEXITY_API_KEY not set. Get one at https://perplexity.ai/settings/api",
            "hint": "Add PERPLEXITY_API_KEY to /root/.env and restart the gateway."
        })

    # Validate model
    if model not in ("sonar", "sonar-pro"):
        model = "sonar"

    # Map focus to search_mode (Perplexity API parameter)
    # Perplexity supports: web, academic, sec
    search_mode_map = {"web": "web", "academic": "academic", "news": "web"}
    search_mode = search_mode_map.get(focus, "web")

    # Build recency filter for news focus
    search_recency = None
    if focus == "news":
        search_recency = "week"

    # Build system message
    system_msg = "You are a research assistant. Provide detailed, factual answers with citations. Be thorough and precise."

    # Build request body (OpenAI-compatible format)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": query}
        ],
        "max_tokens": 4096,
        "temperature": 0.2,
        "search_mode": search_mode,
    }

    # Add recency filter for news
    if search_recency:
        body["search_recency_filter"] = search_recency

    try:
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=body
            )

            if resp.status_code != 200:
                error_text = resp.text[:500]
                return json.dumps({
                    "error": f"Perplexity API returned {resp.status_code}",
                    "detail": error_text
                })

            data = resp.json()

            # Extract response
            answer = ""
            if data.get("choices"):
                answer = data["choices"][0].get("message", {}).get("content", "")

            # Extract citations
            citations = data.get("citations", [])

            # Extract usage for cost tracking
            usage = data.get("usage", {})

            result = {
                "answer": answer,
                "citations": citations,
                "model": data.get("model", model),
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                },
                "query": query,
                "focus": focus
            }

            return json.dumps(result)

    except httpx.TimeoutException:
        return json.dumps({"error": "Perplexity API request timed out (60s limit)"})
    except Exception as e:
        return json.dumps({"error": f"Perplexity research failed: {str(e)}"})


def _read_ai_news(limit: int = 10, source: str = None, hours: int = 24) -> str:
    """Fetch AI news from RSS feeds. Returns article titles, summaries, and links."""
    import re
    import html
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    feeds_to_check = {}

    if source and source.lower() in RSS_FEEDS:
        feeds_to_check[source.lower()] = RSS_FEEDS[source.lower()]
    else:
        feeds_to_check = dict(RSS_FEEDS)

    all_articles = []

    for src_name, feed_url in feeds_to_check.items():
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                resp = client.get(feed_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                })
                if resp.status_code != 200:
                    continue

                xml = resp.text

                # Simple XML parsing for RSS/Atom items
                items = re.findall(r'<item[^>]*>(.*?)</item>', xml, re.DOTALL)
                if not items:
                    items = re.findall(r'<entry[^>]*>(.*?)</entry>', xml, re.DOTALL)

                for item_xml in items[:20]:  # Check up to 20 per feed
                    title = ""
                    link = ""
                    description = ""
                    pub_date = ""

                    # Title
                    t = re.search(r'<title[^>]*>(.*?)</title>', item_xml, re.DOTALL)
                    if t:
                        title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', t.group(1)).strip()
                        title = re.sub(r'<[^>]+>', '', title).strip()

                    # Link (RSS uses <link>, Atom uses <link href="..."/>)
                    l = re.search(r'<link[^>]*href="([^"]+)"', item_xml)
                    if l:
                        link = l.group(1)
                    else:
                        l = re.search(r'<link[^>]*>(.*?)</link>', item_xml, re.DOTALL)
                        if l:
                            link = l.group(1).strip()

                    # Description/summary
                    d = re.search(r'<description[^>]*>(.*?)</description>', item_xml, re.DOTALL)
                    if not d:
                        d = re.search(r'<summary[^>]*>(.*?)</summary>', item_xml, re.DOTALL)
                    if d:
                        description = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', d.group(1), flags=re.DOTALL).strip()
                        description = re.sub(r'<[^>]+>', '', description).strip()
                        description = description[:200]

                    # Published date
                    p = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', item_xml, re.DOTALL)
                    if not p:
                        p = re.search(r'<published[^>]*>(.*?)</published>', item_xml, re.DOTALL)
                    if not p:
                        p = re.search(r'<updated[^>]*>(.*?)</updated>', item_xml, re.DOTALL)
                    if p:
                        pub_date = p.group(1).strip()

                    # Try to parse date and filter by cutoff
                    article_time = None
                    if pub_date:
                        try:
                            from email.utils import parsedate_to_datetime
                            article_time = parsedate_to_datetime(pub_date)
                        except Exception:
                            try:
                                # Try ISO format
                                article_time = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                            except Exception:
                                pass

                    if article_time and article_time.tzinfo and article_time < cutoff:
                        continue

                    if title:
                        all_articles.append({
                            "source": src_name,
                            "title": html.unescape(title),
                            "link": link,
                            "summary": html.unescape(description) if description else "",
                            "published": pub_date,
                            "parsed_time": article_time,
                        })

        except Exception as e:
            logger.warning(f"Failed to fetch RSS from {src_name}: {e}")
            continue

    # Sort by date (newest first), articles without dates go last
    def sort_key(a):
        if a.get("parsed_time"):
            return a["parsed_time"].timestamp()
        return 0

    all_articles.sort(key=sort_key, reverse=True)

    # Limit results
    all_articles = all_articles[:limit]

    if not all_articles:
        return json.dumps({"articles": [], "message": f"No AI news found in the last {hours} hours"})

    # Clean up for output (remove parsed_time which isn't serializable)
    output = []
    for a in all_articles:
        output.append({
            "source": a["source"],
            "title": a["title"],
            "link": a["link"],
            "summary": a["summary"],
            "published": a["published"],
        })

    return json.dumps({"articles": output, "count": len(output)}, indent=2)


def _parse_rss_items(xml: str, acct: str, limit: int) -> list:
    """Parse RSS XML and extract tweet items. Shared between RSSHub and Nitter."""
    import re
    tweets = []
    items = re.findall(r'<item[^>]*>(.*?)</item>', xml, re.DOTALL)
    for item_xml in items[:limit]:
        title = ""
        link = ""
        pub_date = ""
        description = ""

        t = re.search(r'<title[^>]*>(.*?)</title>', item_xml, re.DOTALL)
        if t:
            title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', t.group(1)).strip()
            title = re.sub(r'<[^>]+>', '', title).strip()

        l = re.search(r'<link[^>]*>(.*?)</link>', item_xml, re.DOTALL)
        if l:
            link = l.group(1).strip()

        p = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', item_xml, re.DOTALL)
        if p:
            pub_date = p.group(1).strip()

        d = re.search(r'<description[^>]*>(.*?)</description>', item_xml, re.DOTALL)
        if d:
            description = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', d.group(1), flags=re.DOTALL).strip()
            description = re.sub(r'<[^>]+>', '', description).strip()
            description = description[:280]

        if title or description:
            tweets.append({
                "account": acct,
                "text": description or title,
                "link": link,
                "published": pub_date,
            })
    return tweets


RSSHUB_BASE_URL = "http://localhost:1200"


def _read_tweets(account: str = None, limit: int = 5) -> str:
    """Read recent AI community posts. Tries Reddit AI subs, Bluesky, RSSHub Twitter, Nitter, then web search."""
    import html as html_mod
    import re as re_mod

    accounts = [account] if account else AI_TWITTER_ACCOUNTS
    all_tweets = []
    source = None

    # === Strategy 0: Reddit AI subreddits (most reliable, always fresh) ===
    if not account:  # Only use Reddit when not looking for a specific account
        for feed_url in REDDIT_AI_FEEDS:
            try:
                # Use urllib (not httpx) — Reddit blocks HTTP/2 Python clients
                import urllib.request
                req = urllib.request.Request(feed_url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status != 200:
                        continue
                    xml = resp.read().decode("utf-8")
                    # Parse Atom entries
                    entries = re_mod.findall(r'<entry>(.*?)</entry>', xml, re_mod.DOTALL)
                    subreddit = re_mod.search(r'/r/(\w+)/', feed_url)
                    sub_name = subreddit.group(1) if subreddit else "reddit"
                    for entry_xml in entries[:limit]:
                        title = ""
                        link = ""
                        updated = ""

                        t = re_mod.search(r'<title[^>]*>(.*?)</title>', entry_xml, re_mod.DOTALL)
                        if t:
                            title = html_mod.unescape(re_mod.sub(r'<[^>]+>', '', t.group(1))).strip()

                        l = re_mod.search(r'<link href="([^"]+)"', entry_xml)
                        if l:
                            link = l.group(1)

                        u = re_mod.search(r'<updated[^>]*>(.*?)</updated>', entry_xml, re_mod.DOTALL)
                        if u:
                            updated = u.group(1).strip()

                        if title and not title.startswith("[D]") and not title.startswith("[P]"):
                            # Skip pure discussion/project threads, keep research/news
                            pass
                        if title:
                            all_tweets.append({
                                "account": f"r/{sub_name}",
                                "text": html_mod.unescape(title),
                                "link": link,
                                "published": updated,
                                "platform": "reddit",
                            })
                if all_tweets:
                    source = "reddit"
            except Exception as e:
                logger.warning(f"Reddit RSS failed for {feed_url}: {e}")

    # === Strategy 1: Bluesky AT Protocol (free, no auth) ===
    if not all_tweets:
        bsky_accounts_to_check = []
        if account:
            bsky_handle = TWITTER_TO_BLUESKY.get(account.lower())
            if bsky_handle:
                bsky_accounts_to_check = [bsky_handle]
            elif account.endswith(".bsky.social"):
                bsky_accounts_to_check = [account]
        else:
            bsky_accounts_to_check = BLUESKY_ACCOUNTS

        for bsky_acct in bsky_accounts_to_check:
            try:
                url = f"{BLUESKY_API}/app.bsky.feed.getAuthorFeed?actor={bsky_acct}&limit={limit}&filter=posts_no_replies"
                with httpx.Client(timeout=10) as client:
                    resp = client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for item in data.get("feed", [])[:limit]:
                        post = item.get("post", {})
                        record = post.get("record", {})
                        author = post.get("author", {})
                        text = record.get("text", "")
                        if not text:
                            continue
                        all_tweets.append({
                            "account": f"@{author.get('handle', bsky_acct)}",
                            "display_name": author.get("displayName", ""),
                            "text": html_mod.unescape(text),
                            "link": f"https://bsky.app/profile/{author.get('handle', bsky_acct)}/post/{post.get('uri', '').split('/')[-1]}",
                            "published": record.get("createdAt", ""),
                            "likes": post.get("likeCount", 0),
                            "reposts": post.get("repostCount", 0),
                            "platform": "bluesky",
                        })
                    if all_tweets:
                        source = "bluesky"
            except Exception as e:
                logger.warning(f"Bluesky failed for {bsky_acct}: {e}")

    # === Strategy 2: Self-hosted RSSHub Twitter (localhost:1200) ===
    if not all_tweets:
        for acct in accounts:
            try:
                url = f"{RSSHUB_BASE_URL}/twitter/user/{acct}"
                with httpx.Client(timeout=15, follow_redirects=True) as client:
                    resp = client.get(url, headers={
                        "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                    })
                    if resp.status_code == 200 and '<?xml' in resp.text[:100]:
                        tweets = _parse_rss_items(resp.text, acct, limit)
                        if tweets:
                            all_tweets.extend(tweets)
                            source = "rsshub_twitter"
            except Exception as e:
                logger.warning(f"RSSHub failed for @{acct}: {e}")

    # === Strategy 3: Nitter instances (fallback) ===
    if not all_tweets:
        for nitter_url in NITTER_INSTANCES:
            if all_tweets:
                break
            for acct in accounts:
                try:
                    url = f"{nitter_url}/{acct}/rss"
                    with httpx.Client(timeout=10, follow_redirects=True) as client:
                        resp = client.get(url, headers={
                            "User-Agent": "Mozilla/5.0 (compatible; OpenClaw/2.0)"
                        })
                        if resp.status_code != 200:
                            continue
                        tweets = _parse_rss_items(resp.text, acct, limit)
                        if tweets:
                            all_tweets.extend(tweets)
                            source = "nitter"
                except Exception as e:
                    logger.warning(f"Nitter failed for @{acct} from {nitter_url}: {e}")
                    continue

    # === Strategy 4: Web search fallback ===
    if not all_tweets:
        try:
            search_accounts = account or "AnthropicAI OR OpenAI OR GoogleDeepMind"
            search_result = _web_search(f"{search_accounts} AI latest announcement 2026")
            return json.dumps({
                "tweets": [],
                "source": "web_search_fallback",
                "fallback_search": search_result,
                "message": "Reddit, Bluesky, RSSHub, and Nitter unavailable. Used web search fallback.",
            }, indent=2)
        except Exception:
            pass
        return json.dumps({
            "tweets": [],
            "message": "All sources failed (Reddit, Bluesky, RSSHub, Nitter, web search)",
        })

    return json.dumps({
        "tweets": all_tweets,
        "count": len(all_tweets),
        "source": source
    }, indent=2)

