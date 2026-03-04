"""
Autonomous Job Runner for OpenClaw
===================================
The CORE engine that turns OpenClaw from a chatbot into an AI agency.
Picks up pending jobs, runs them through a 5-phase execution pipeline
(RESEARCH -> PLAN -> EXECUTE -> VERIFY -> DELIVER), with tool use,
cost tracking, error recovery, and parallel execution.

Usage:
    runner = AutonomousRunner(max_concurrent=2)
    await runner.start()       # Starts background polling loop
    await runner.stop()        # Graceful shutdown
    await runner.execute_job(job_id)  # Run a single job on demand

Architecture:
    - Background asyncio loop polls for pending jobs every 10s
    - Each job runs in its own asyncio Task with isolated context
    - Agents are called via call_model_for_agent() with tool_use
    - Tools are executed via execute_tool() from agent_tools.py
    - Progress logged to data/jobs/runs/{job_id}/
    - Costs tracked per phase via cost_tracker.py
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from agent_tools import execute_tool as _raw_execute_tool, AGENT_TOOLS
from tool_router import get_registry as _get_tool_registry, PhaseViolationError

from ide_session import create_session, save_session, load_session, delete_session

try:
    from repo_map import generate_compact_map
    HAS_REPO_MAP = True
except ImportError:
    HAS_REPO_MAP = False


def _execute_tool_routed(tool_name: str, tool_input: dict, phase: str = "", job_id: str = "", agent_key: str = "") -> str:
    """Execute tool through ToolRegistry (phase-gated + audited) with capability whitelist enforcement."""
    # --- Capability-based tool whitelist enforcement ---
    if agent_key:
        from agent_tool_profiles import get_tools_for_agent
        allowlist = get_tools_for_agent(agent_key)
        if allowlist is not None and tool_name not in allowlist:
            logger.warning(
                f"BLOCKED tool '{tool_name}' for agent '{agent_key}' (not in allowlist) "
                f"[job={job_id}, phase={phase}]"
            )
            return f"[BLOCKED] Tool '{tool_name}' is not authorized for agent '{agent_key}'. Available tools: {', '.join(sorted(allowlist))}"

    if _get_tool_registry is not None:
        registry = _get_tool_registry()
        return registry.execute_tool(tool_name, tool_input, phase=phase, job_id=job_id)
    return _raw_execute_tool(tool_name, tool_input)
from alerts import send_telegram
from blackboard import write as blackboard_write, get_context_for_prompt as blackboard_context, cleanup_expired as blackboard_cleanup
from checkpoint import save_checkpoint, get_latest_checkpoint, clear_checkpoints
from job_manager import get_job, update_job_status, list_jobs, get_pending_jobs, validate_job, JobValidationError
from reflexion import save_reflection, search_reflections, format_reflections_for_prompt
from departments import DEPARTMENTS, AGENT_TO_DEPARTMENT, load_department_knowledge
from memory_policies import inject_context, auto_extract_learnings, save_learnings
from agent_templates import get_template, get_failure_recovery, get_model_preference
from agent_sessions import get_session, record_job, build_agent_context
from phase_scoring import score_all_phases, validate_phase_output
try:
    from supervisor import maybe_decompose_and_execute
except ImportError:
    async def maybe_decompose_and_execute(*args, **kwargs):
        return None  # supervisor not available — skip decomposition
# Cost tracking — import from cost_tracker (single source of truth)
from cost_tracker import (
    calculate_cost,
    log_cost_event,
    get_cost_metrics,
)
# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data")
JOB_RUNS_DIR = Path(os.path.join(DATA_DIR, "jobs", "runs"))
DEFAULT_POLL_INTERVAL = 10        # seconds between job queue checks
DEFAULT_MAX_CONCURRENT = 3        # max parallel job executions (VPS: 4 CPU / 8GB RAM)
DEFAULT_MAX_RETRIES = 3           # retries per phase on failure
DEFAULT_BUDGET_LIMIT_USD = 5.0    # per-job cost cap (legacy fallback — guardrails enforce priority-based caps)
MAX_TOOL_ITERATIONS = 15          # safety cap on agent tool loops per step
TOOL_NUDGE_THRESHOLD = 10         # after this many iterations, nudge agent to finish up
LOOP_DETECT_THRESHOLD = 3         # same tool+args called this many times → force break
MAX_PLAN_STEPS = 10               # safety cap on plan step count (fewer = less iteration burn)

# ---------------------------------------------------------------------------
# Error Classification — transient errors get retried, permanent ones don't
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6-Category Error Classification (inspired by Devin MCP HTTP matrix)
# Each category has: max_retries, backoff_strategy, recovery_action
# ---------------------------------------------------------------------------

ERROR_CATEGORIES = {
    "network": {
        "max_retries": 3, "backoff": "exponential", "action": "retry_same",
        "patterns": [
            "rate limit", "rate_limit", "429", "too many requests",
            "timeout", "timed out", "deadline exceeded",
            "connection reset", "connection refused", "connection error",
            "temporary failure", "service unavailable", "503",
            "internal server error", "500",
            "network error", "dns resolution",
            "overloaded", "capacity", "try again",
            "econnrefused", "econnreset", "etimedout",
            "ssl error", "handshake", "502", "504",
        ],
    },
    "auth": {
        "max_retries": 0, "backoff": "none", "action": "escalate",
        "patterns": [
            "authentication", "unauthorized", "401", "403",
            "forbidden", "invalid api key", "invalid token",
            "expired token", "access denied",
        ],
    },
    "not_found": {
        "max_retries": 1, "backoff": "none", "action": "diagnose_and_rewrite",
        "patterns": [
            "file not found", "no such file", "filenotfounderror",
            "not found", "404", "does not exist",
            "no such directory", "path not found",
        ],
    },
    "code_error": {
        "max_retries": 2, "backoff": "fixed", "action": "diagnose_and_rewrite",
        "patterns": [
            "syntax error", "syntaxerror", "invalid syntax",
            "import error", "importerror", "modulenotfounderror",
            "name error", "nameerror", "is not defined",
            "type error", "typeerror", "not callable",
            "attribute error", "attributeerror", "has no attribute",
            "value error", "valueerror",
            "key error", "keyerror",
            "index error", "indexerror",
        ],
    },
    "permission": {
        "max_retries": 0, "backoff": "none", "action": "skip",
        "patterns": [
            "permission denied", "permissionerror",
            "read-only file system", "operation not permitted",
        ],
    },
    "resource": {
        "max_retries": 1, "backoff": "exponential", "action": "retry_same",
        "patterns": [
            "out of memory", "oom", "memory error",
            "disk full", "no space left", "quota exceeded",
        ],
    },
}

# Flatten for backward compat
TRANSIENT_ERROR_PATTERNS = ERROR_CATEGORIES["network"]["patterns"]
PERMANENT_ERROR_PATTERNS = (
    ERROR_CATEGORIES["auth"]["patterns"]
    + ERROR_CATEGORIES["permission"]["patterns"]
)


def _classify_error(error_str: str) -> str:
    """Classify an error into one of 6 categories with specific recovery actions.

    Returns a category key from ERROR_CATEGORIES, or 'unknown'.
    For backward compat, also maps to 'transient'/'permanent' where needed.
    """
    err_lower = error_str.lower()
    # Check categories in priority order (most specific first)
    for category in ["auth", "permission", "resource", "network", "not_found", "code_error"]:
        cat = ERROR_CATEGORIES[category]
        for pattern in cat["patterns"]:
            if pattern in err_lower:
                return category
    return "unknown"


def _get_error_config(error_class: str) -> dict:
    """Get retry/recovery config for an error category."""
    return ERROR_CATEGORIES.get(error_class, {
        "max_retries": 2, "backoff": "fixed", "action": "diagnose_and_rewrite",
    })


async def _diagnose_failure(
    error_text: str,
    original_prompt: str,
    phase: str,
    error_history: list[dict] | None = None,
    error_class: str = "unknown",
    job_task: str = "",
) -> dict:
    """Diagnose a failure and suggest a modified prompt for retry.

    Enhanced with patterns from Devin, Manus, Cursor leaked prompts:
    1. Root cause vs symptom distinction (Cursor pattern)
    2. Past reflexion injection — learn from similar past failures
    3. Error-category-specific diagnosis prompts (Manus modular pattern)
    4. Partial result preservation context

    Calls Grok grok-3-mini (~$0.0004) to analyze the error and rewrite the prompt.

    Returns:
        {"diagnosis": str, "modified_prompt": str, "strategy": "retry|skip|escalate",
         "root_cause": str, "lesson": str}
    """
    try:
        from grok_executor import call_grok

        # --- Past reflexion injection (learn from similar past failures) ---
        reflexion_context = ""
        try:
            past = search_reflections(job_task or error_text[:100], limit=2)
            if past:
                lessons = []
                for r in past[:2]:
                    lesson = r.get("lesson", r.get("summary", ""))
                    if lesson:
                        lessons.append(f"  - {lesson[:150]}")
                if lessons:
                    reflexion_context = "\nLessons from similar past failures:\n" + "\n".join(lessons)
        except Exception:
            pass  # Non-fatal — reflexion search failure shouldn't block diagnosis

        history_context = ""
        if error_history:
            history_lines = []
            for entry in error_history[-3:]:
                history_lines.append(
                    f"  Attempt {entry.get('attempt')}: {entry.get('error', '')[:200]}"
                )
            history_context = f"\nPrevious failures:\n" + "\n".join(history_lines)

        # --- Error-category-specific diagnosis guidance (Manus modular pattern) ---
        category_guidance = {
            "network": "This is a network/API error. Keep the prompt nearly identical. Suggest 'retry' with minimal changes.",
            "auth": "This is an authentication/authorization error. The prompt cannot fix this — suggest 'escalate' unless the prompt can use a different API or approach.",
            "not_found": "A file or resource was not found. The prompt likely references a wrong path. Rewrite to use correct paths or add a file-discovery step first.",
            "code_error": "The generated code has a bug (syntax/type/name error). Identify the ROOT CAUSE of the bug and rewrite the prompt to produce correct code. Do NOT just suppress the error.",
            "permission": "Permission denied. Suggest 'skip' unless the prompt can use a different file or approach.",
            "resource": "System resource issue (memory/disk). Suggest 'retry' — may be transient.",
            "unknown": "Unknown error type. Analyze carefully and determine the best strategy.",
        }
        guidance = category_guidance.get(error_class, category_guidance["unknown"])

        diag_prompt = (
            f"An AI agent step failed during the '{phase}' phase.\n\n"
            f"Error category: {error_class}\n"
            f"Error: {error_text[:500]}\n"
            f"{history_context}\n"
            f"{reflexion_context}\n\n"
            f"Original prompt (first 800 chars):\n{original_prompt[:800]}\n\n"
            f"Category guidance: {guidance}\n\n"
            f"IMPORTANT: Distinguish the ROOT CAUSE from the SYMPTOM. "
            f"The error message is a symptom — what is the underlying cause? "
            f"Address the root cause in your modified prompt, not just the symptom.\n\n"
            f"Respond with EXACTLY this JSON format (no markdown, no extra text):\n"
            f'{{"diagnosis": "brief explanation of what went wrong",'
            f' "root_cause": "the underlying cause (not the symptom)",'
            f' "modified_prompt": "the rewritten prompt that avoids the error",'
            f' "strategy": "retry",'
            f' "lesson": "one-sentence lesson for future jobs with similar errors"}}\n\n'
            f'strategy must be one of: "retry" (try again with modified prompt), '
            f'"skip" (this step cannot succeed, move on), '
            f'"escalate" (needs human/PM review).\n'
        )

        result = await call_grok(
            prompt=diag_prompt,
            system_prompt="You are a failure diagnosis agent. Analyze errors and suggest fixes. Respond only with valid JSON.",
            model="grok-3-mini",
            max_tokens=1024,
            temperature=0.1,
            timeout=30,
        )

        text = result.get("text", "").strip()
        # Try to parse JSON from the response
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            diag_result = {
                "diagnosis": parsed.get("diagnosis", ""),
                "root_cause": parsed.get("root_cause", ""),
                "modified_prompt": parsed.get("modified_prompt", ""),
                "strategy": parsed.get("strategy", "retry"),
                "lesson": parsed.get("lesson", ""),
                "cost_usd": result.get("cost_usd", 0),
            }
            # Auto-save lesson for future jobs if present
            lesson = diag_result.get("lesson", "")
            if lesson and len(lesson) > 10:
                try:
                    save_reflection(
                        job_id=f"diag-{phase}",
                        job_data={"task": job_task[:200], "project": "openclaw"},
                        outcome="failure_diagnosed",
                        lesson=lesson,
                        phase_scores={},
                    )
                except Exception:
                    pass  # Non-fatal
            return diag_result
        else:
            return {"diagnosis": text[:200], "root_cause": "", "modified_prompt": "", "strategy": "retry", "lesson": "", "cost_usd": result.get("cost_usd", 0)}

    except Exception as e:
        logger.debug(f"Failure diagnosis failed (non-fatal): {e}")
        return {"diagnosis": f"Diagnosis unavailable: {e}", "root_cause": "", "modified_prompt": "", "strategy": "retry", "lesson": "", "cost_usd": 0}


def _make_call_signature(tool_name: str, tool_input) -> str:
    """Create a deterministic signature for loop detection.

    Uses hashlib.md5 instead of hash() to avoid Python's hash randomization
    which can produce different values across runs and collisions.
    """
    if isinstance(tool_input, dict):
        input_str = str(sorted(tool_input.items()))
    else:
        input_str = str(tool_input)
    input_hash = hashlib.md5(input_str.encode()).hexdigest()[:12]
    return f"{tool_name}:{input_hash}"


def _check_loop(call_sig: str, counts: dict, job_id: str, phase: str) -> bool:
    """Check if a tool call has been repeated too many times.

    Returns True if loop detected (caller should break).
    """
    counts[call_sig] = counts.get(call_sig, 0) + 1
    if counts[call_sig] >= LOOP_DETECT_THRESHOLD:
        tool_name = call_sig.split(":")[0]
        logger.warning(
            f"Loop detected for {job_id}/{phase}: {tool_name} called {counts[call_sig]}x with same args"
        )
        return True
    return False

# Agent SDK integration — uses Claude Code's native tool execution engine instead of
# our manual tool-use loop. Benefits: native context compaction, better tool handling,
# hooks support, 80.9% SWE-bench accuracy. Toggle off with OPENCLAW_USE_SDK=0.
USE_SDK = os.environ.get("OPENCLAW_USE_SDK", "1") == "1"

# Oz executor — uses Warp Oz CLI for multi-model orchestration (GPT-5.2, Claude 4.6, Gemini 3 Pro).
# Auto-selects best model per task. Falls back to OpenCode/SDK on failure.
# Toggle off with OPENCLAW_USE_OZ=0.
USE_OZ = os.environ.get("OPENCLAW_USE_OZ", "1") == "1"  # Warp cloud agents (run-cloud)

# OpenCode executor — uses Go-based OpenCode CLI for ~90% cost savings.
# Falls back to Agent SDK on failure. Toggle off with OPENCLAW_USE_OPENCODE=0.
USE_OPENCODE = os.environ.get("OPENCLAW_USE_OPENCODE", "1") == "1"

logger = logging.getLogger("autonomous_runner")

# Agent keys from config.json — mapped by capability
AGENT_MAP = {
    "project_manager": "project_manager",   # Claude Opus  — planning, coordination
    "coder_agent":     "coder_agent",        # Kimi 2.5    — routine code
    "elite_coder":     "elite_coder",        # MiniMax M2.5 — complex code
    "hacker_agent":    "hacker_agent",       # Kimi Reasoner — security
    "database_agent":  "database_agent",     # Claude Opus  — data / SQL
    "code_reviewer":   "code_reviewer",      # Kimi 2.5    — PR/code review
}

# Tools available during each phase (restrict for safety)
RESEARCH_TOOLS = [
    "research_task", "web_search", "web_fetch", "web_scrape",
    "file_read", "glob_files", "grep_search",
    "github_repo_info",
]

PLAN_TOOLS = [
    "file_read", "glob_files", "grep_search",
    "github_repo_info",
]

EXECUTE_TOOLS = [
    "shell_execute", "git_operations", "file_read", "file_write", "file_edit",
    "glob_files", "grep_search", "install_package",
    "vercel_deploy", "process_manage", "env_manage",
]

CODE_REVIEW_TOOLS = [
    "file_read", "glob_files", "grep_search",
]

VERIFY_TOOLS = [
    "shell_execute", "file_read", "glob_files", "grep_search",
    "github_repo_info",
]

DELIVER_TOOLS = [
    "git_operations", "vercel_deploy", "shell_execute",
    "send_slack_message",
]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class Phase(str, Enum):
    RESEARCH    = "research"
    PLAN        = "plan"
    EXECUTE     = "execute"
    CODE_REVIEW = "code_review"
    VERIFY      = "verify"
    DELIVER     = "deliver"


@dataclass
class PlanStep:
    index: int
    description: str
    tool_hints: list = field(default_factory=list)
    status: str = "pending"         # pending | running | done | failed | skipped
    result: str = ""
    attempts: int = 0
    error: str = ""
    delegate_to: str = ""           # agent key for delegation (empty = use default agent)


@dataclass
class ExecutionPlan:
    job_id: str
    agent: str
    steps: list = field(default_factory=list)   # list[PlanStep]
    created_at: str = ""

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "agent": self.agent,
            "steps": [asdict(s) for s in self.steps],
            "created_at": self.created_at,
        }


@dataclass
class JobProgress:
    job_id: str
    phase: Phase = Phase.RESEARCH
    phase_status: str = "pending"       # pending | running | done | failed
    step_index: int = 0
    total_steps: int = 0
    cost_usd: float = 0.0
    started_at: str = ""
    updated_at: str = ""
    error: str = ""
    retries: int = 0
    cancelled: bool = False
    workspace: str = ""                 # isolated per-job workspace directory

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "phase": self.phase.value,
            "phase_status": self.phase_status,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "cost_usd": round(self.cost_usd, 6),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "retries": self.retries,
            "cancelled": self.cancelled,
            "workspace": self.workspace,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_run_dir(job_id: str) -> Path:
    d = JOB_RUNS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_phase(job_id: str, phase: str, data: dict):
    """Append a phase log entry to the job run directory."""
    run_dir = _job_run_dir(job_id)
    log_file = run_dir / f"{phase}.jsonl"
    entry = {"timestamp": _now_iso(), **data}
    with open(log_file, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _save_progress(progress: JobProgress):
    """Persist current progress to disk."""
    run_dir = _job_run_dir(progress.job_id)
    progress.updated_at = _now_iso()
    with open(run_dir / "progress.json", "w") as f:
        json.dump(progress.to_dict(), f, indent=2)


def _trim_context(text: str, max_tokens: int = 2000) -> str:
    """Trim context data to prevent token bloat between phases.

    Uses ~4 chars per token estimate. max_tokens is the target token budget.
    Keeps the first (max_tokens * 4) characters. If truncated, appends a note
    so the agent knows context was trimmed.
    """
    if not text:
        return text
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars]
    return trimmed + f"\n\n[... truncated from {len(text)} to {max_chars} chars (~{max_tokens} tokens) to save tokens ...]"


PROJECT_ROOTS = {
    "barber-crm": "/root/Barber-CRM/nextjs-app",
    "delhi-palace": "/root/Delhi-Palace",
    "openclaw": "/root/openclaw",
    "prestress-calc": "/root/Mathcad-Scripts",
    "concrete-canoe": "/root/concrete-canoe-project2026",
}


def _load_project_context(project: str) -> str:
    """Load CLAUDE.md and component manifest for a project.

    This gives the agent accurate knowledge of what files/components exist,
    preventing it from importing non-existent modules.
    """
    root = PROJECT_ROOTS.get(project, "")
    if not root:
        return ""

    parts = []

    # Load CLAUDE.md if it exists (truncated to save tokens)
    claude_md_path = os.path.join(root, "CLAUDE.md")
    if os.path.isfile(claude_md_path):
        try:
            with open(claude_md_path, "r") as f:
                md = f.read()
            # Take first 3000 chars — enough for key patterns and structure
            parts.append(f"PROJECT GUIDE (from CLAUDE.md):\n{md[:3000]}")
        except Exception:
            pass

    # Auto-discover UI components for Next.js projects
    ui_dir = os.path.join(root, "src", "components", "ui")
    if os.path.isdir(ui_dir):
        try:
            components = [f.replace(".tsx", "").replace(".ts", "")
                          for f in os.listdir(ui_dir)
                          if f.endswith((".tsx", ".ts")) and not f.startswith("_")]
            if components:
                parts.append(
                    f"AVAILABLE UI COMPONENTS in @/components/ui/: {', '.join(sorted(components))}\n"
                    f"IMPORTANT: Only import from components that exist in this list. "
                    f"Do NOT import components that are not listed here."
                )
        except Exception:
            pass

    # Auto-discover existing API routes
    api_dir = os.path.join(root, "src", "app", "api")
    if os.path.isdir(api_dir):
        try:
            routes = []
            for dirpath, dirnames, filenames in os.walk(api_dir):
                if "route.ts" in filenames or "route.tsx" in filenames:
                    rel = os.path.relpath(dirpath, os.path.join(root, "src", "app"))
                    routes.append(f"/{rel}")
            if routes:
                parts.append(f"EXISTING API ROUTES: {', '.join(sorted(routes))}")
        except Exception:
            pass

    return "\n\n".join(parts)


def _extract_and_save_discoveries(agent_output: str, job_id: str, project: str):
    """Extract DISCOVERY: lines from agent output and save to blackboard.

    Inspired by Cursor's update_memory pattern — agents save patterns they
    find during execution so future agents benefit.
    """
    discoveries = []
    for line in agent_output.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("DISCOVERY:"):
            discovery = stripped[len("DISCOVERY:"):].strip()
            if discovery:
                discoveries.append(discovery)

    for discovery in discoveries[:5]:  # Cap at 5 per step
        try:
            blackboard_write(
                key=f"discovery_{job_id}_{uuid.uuid4().hex[:6]}",
                value=discovery,
                project=project,
                job_id=job_id,
                agent="executor",
                ttl_seconds=604800,  # 7 days
            )
            logger.info(f"Saved discovery for {job_id}: {discovery[:80]}")
        except Exception as e:
            logger.debug(f"Failed to save discovery: {e}")


def _build_context_bundle(step: PlanStep, research: str, previous_results: list) -> str:
    """Build a focused context bundle for the execute phase.

    Instead of dumping the full research text, this:
    1. Extracts file paths mentioned in the step description
    2. Scores research lines by keyword relevance to the current step
    3. Includes only the last 2 step summaries (not all)

    Expected gain: 20-30% reduction in execute phase input tokens.
    """
    lines = []

    # 1. Extract file paths from step description for focused context
    step_desc_lower = step.description.lower()
    step_keywords = set(step_desc_lower.split())
    # Remove common words
    stop_words = {"the", "a", "an", "to", "in", "of", "for", "and", "or", "is", "it", "at", "on", "by", "with", "from"}
    step_keywords -= stop_words

    # 2. Score research lines by relevance
    if research:
        research_lines = research.split("\n")
        scored_lines = []
        for line in research_lines:
            if not line.strip():
                continue
            line_lower = line.lower()
            # Score: count keyword matches + bonus for file paths
            score = sum(1 for kw in step_keywords if kw in line_lower)
            if "/" in line or "." in line.split()[-1] if line.split() else False:
                score += 2  # Bonus for file paths
            if any(marker in line_lower for marker in ["relevant", "important", "key", "pattern", "depend"]):
                score += 1
            scored_lines.append((score, line))

        # Sort by relevance, take top lines that fit in ~4000 chars (~1000 tokens)
        scored_lines.sort(key=lambda x: x[0], reverse=True)
        budget = 4000
        for score, line in scored_lines:
            if score <= 0:
                break
            if budget <= 0:
                break
            lines.append(line)
            budget -= len(line)

    context = "\n".join(lines) if lines else research[:4000] if research else ""

    # 3. Include only last 2 step summaries
    if previous_results:
        recent = previous_results[-2:]
        step_summaries = "\n".join(
            f"- Step {r['step']+1}: {r.get('summary', r.get('status', '?'))[:150]}"
            for r in recent
        )
        context = f"RECENT STEPS:\n{step_summaries}\n\nRESEARCH CONTEXT:\n{context}"
    else:
        context = f"RESEARCH CONTEXT:\n{context}"

    return context


# ---------------------------------------------------------------------------
# Git Worktree Isolation — for concurrent same-project jobs
# ---------------------------------------------------------------------------

WORKTREES_DIR = Path(os.path.join(DATA_DIR, "jobs", "worktrees"))


def _create_job_worktree(job_id: str, project_root: str) -> str:
    """Create a git worktree for isolated job execution. Returns worktree path."""
    wt_path = str(WORKTREES_DIR / job_id)
    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)

    if os.path.exists(wt_path):
        logger.info(f"Reusing existing worktree: {wt_path}")
        return wt_path

    branch_name = f"agent/{job_id}"
    result = subprocess.run(
        ["git", "-C", project_root, "worktree", "add", "-b", branch_name, wt_path, "HEAD"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        # Branch might already exist, try detached HEAD
        result = subprocess.run(
            ["git", "-C", project_root, "worktree", "add", wt_path, "HEAD", "--detach"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree for {job_id}: {result.stderr.strip()}")

    logger.info(f"Created worktree: {wt_path} (from {project_root})")
    return wt_path


def _cleanup_job_worktree(job_id: str, project_root: str):
    """Remove worktree and branch after job completion."""
    wt_path = str(WORKTREES_DIR / job_id)
    if os.path.exists(wt_path):
        subprocess.run(
            ["git", "-C", project_root, "worktree", "remove", "--force", wt_path],
            capture_output=True, text=True, timeout=15,
        )
        logger.info(f"Removed worktree: {wt_path}")
    # Clean up branch
    branch_name = f"agent/{job_id}"
    subprocess.run(
        ["git", "-C", project_root, "branch", "-D", branch_name],
        capture_output=True, text=True, timeout=10,
    )


def _merge_worktree_changes(job_id: str, project_root: str) -> bool:
    """Merge worktree branch changes back into main branch. Returns True on success."""
    branch_name = f"agent/{job_id}"
    result = subprocess.run(
        ["git", "-C", project_root, "merge", branch_name, "--no-edit"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        logger.warning(f"Failed to merge worktree branch {branch_name}: {result.stderr.strip()}")
        return False
    logger.info(f"Merged worktree branch {branch_name} into main")
    return True


def _compact_description(desc: str, max_len: int = 100) -> str:
    """Shorten a tool description to ≤max_len chars.

    Strips fluff like 'Use when...' and 'Use this to...' keeping only the
    core action.  Saves ~3000 tokens per agent call across 72 tools.
    """
    if len(desc) <= max_len:
        return desc
    # Drop trailing 'Use ...' sentences
    sentences = desc.split(". ")
    core = sentences[0]
    if len(core) <= max_len:
        return core + "." if not core.endswith(".") else core
    return core[:max_len - 1] + "…"


def _compact_tools(tools: list) -> list:
    """Return tool defs with shortened descriptions (saves tokens)."""
    compacted = []
    for t in tools:
        ct = dict(t)
        ct["description"] = _compact_description(ct.get("description", ""))
        compacted.append(ct)
    return compacted


def _filter_tools_for_phase(phase: Phase, agent_key: str = None, compact: bool = True) -> list:
    """Return the AGENT_TOOLS definitions filtered for a given phase.

    Uses ToolRegistry for phase gating (canonical source of truth).
    If agent_key is provided, further restricts to the agent's tool profile
    (intersection of phase tools and agent allowlist).
    If compact=True, shortens descriptions to save tokens.
    """
    from tool_router import get_registry
    registry = get_registry()
    phase_tools = registry.get_tools_for_phase(phase.value)

    # Apply agent-specific tool profile if available
    if agent_key:
        try:
            from agent_tool_profiles import get_tools_for_agent
            agent_allowlist = get_tools_for_agent(agent_key)
            if agent_allowlist is not None:
                phase_tools = [t for t in phase_tools if t["name"] in agent_allowlist]
        except ImportError:
            pass

    return _compact_tools(phase_tools) if compact else phase_tools


def _classify_department(job: dict) -> str:
    """Route job to a department based on task + project keywords.

    Two-step process:
    1. Explicit agent_pref overrides keyword routing
    2. Score each department by keyword hits, highest wins
    """
    task_lower = (job.get("task", "") + " " + job.get("project", "")).lower()

    # Explicit agent_pref overrides keyword routing
    if job.get("agent_pref"):
        return AGENT_TO_DEPARTMENT.get(job["agent_pref"], "backend")

    # Score each department by keyword hits
    scores = {name: 0 for name in DEPARTMENTS}
    for dept_name, dept in DEPARTMENTS.items():
        scores[dept_name] = sum(1 for kw in dept.keywords if kw in task_lower)

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "backend"  # safe default


def _select_agent_for_job(job: dict) -> tuple[str, str]:
    """Pick the best agent for a job using department-based routing + agent templates.

    Returns (agent_key, department_name).

    Uses agent_templates.get_template_for_task() for task-type routing when
    a clear task signal is detected. Falls back to department-based routing
    with complexity heuristics.
    """
    dept_name = _classify_department(job)
    dept = DEPARTMENTS[dept_name]
    task_lower = job.get("task", "").lower()

    # Try template-based routing first (more granular than department routing)
    try:
        from agent_templates import get_template_for_task, _AGENT_KEY_TO_TEMPLATE

        # Map task keywords to template task types
        task_type_signals = {
            "security_audit": ["security audit", "pentest", "vulnerability scan"],
            "pentest": ["penetration test", "pen test"],
            "debug": ["debug", "race condition", "memory leak", "heisenbug"],
            "code_review": ["code review", "pr review", "review pr", "audit code"],
            "testing": ["write test", "add test", "test coverage", "unit test", "e2e test"],
            "complex_refactor": ["refactor", "overhaul", "redesign", "rewrite"],
            "architecture": ["architecture", "system design", "api design"],
            "database": ["database", "sql", "migration", "schema", "supabase query"],
            "bug_fix": ["fix bug", "bug fix", "broken", "not working"],
            "feature": ["add feature", "implement", "build", "create"],
        }

        matched_type = None
        for task_type, keywords in task_type_signals.items():
            if any(kw in task_lower for kw in keywords):
                matched_type = task_type
                break

        if matched_type:
            template = get_template_for_task(matched_type)
            # Reverse-map: template_name -> agent_key
            template_to_agent = {v: k for k, v in _AGENT_KEY_TO_TEMPLATE.items()}
            from agent_templates import TEMPLATES
            for tmpl_name, tmpl_obj in TEMPLATES.items():
                if tmpl_obj is template and tmpl_name in template_to_agent:
                    agent_key = template_to_agent[tmpl_name]
                    logger.info(f"Template routing: task_type={matched_type} -> agent={agent_key}")
                    return agent_key, template.department or dept_name
    except Exception as tmpl_err:
        logger.debug(f"Template routing failed, using department routing: {tmpl_err}")

    # Fallback: department-based routing with complexity heuristics
    complex_kw = ["refactor", "architecture", "multi-file", "rewrite", "overhaul", "redesign"]
    is_complex = any(kw in task_lower for kw in complex_kw)

    # Special routing for test generation tasks
    test_kw = ["test", "tests", "testing", "coverage", "spec", "e2e", "unit test"]
    if any(kw in task_lower for kw in test_kw) and dept_name in ("frontend", "backend"):
        return "test_generator", dept_name

    if is_complex and dept.fallback_agent:
        return dept.fallback_agent, dept_name
    return dept.primary_agent, dept_name


# ---------------------------------------------------------------------------
# Agent SDK execution path — replaces manual tool-use loop with Claude Code's
# native agentic execution engine. Falls back to legacy path on import error.
# ---------------------------------------------------------------------------

async def _call_agent_sdk(
    prompt: str,
    system_prompt: str = "",
    job_id: str = "",
    phase: str = "",
    priority: str = "P2",
    guardrails: "JobGuardrails | None" = None,
    workspace: str = "",
    max_turns: int = 0,
) -> dict:
    """
    Execute an agent task using the Claude Agent SDK.

    The SDK spawns a Claude Code subprocess with full tool access (Bash, Read,
    Write, Edit, Glob, Grep) and native context compaction. This replaces our
    manual Anthropic API tool-use loop with Claude Code's battle-tested agentic
    engine, which achieves 80.9% on SWE-bench.

    Returns: {"text": str, "tokens": int, "tool_calls": list[dict], "cost_usd": float}
    """
    try:
        from claude_agent_sdk import query as sdk_query
        from claude_agent_sdk import ClaudeAgentOptions
    except ImportError:
        logger.error("claude_agent_sdk not installed — falling back to legacy path")
        raise  # Let caller handle fallback

    # Select model based on priority — default to Haiku (cheap) for SDK fallbacks.
    # Only P0 critical jobs get Sonnet. This prevents expensive fallbacks when
    # OpenCode fails (was causing $17+/day in Sonnet SDK costs).
    if priority == "P0":
        model = "sonnet"
    else:
        model = "haiku"

    # Determine max turns from phase if not specified
    if max_turns <= 0:
        phase_turns = {
            "research": 15,
            "plan": 10,
            "execute": 30,
            "verify": 10,
            "deliver": 10,
        }
        max_turns = phase_turns.get(phase, 20)

    # Determine working directory
    cwd = workspace if workspace else "/root/openclaw"

    # Build the full prompt with system context
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

    # Remove CLAUDECODE env var to prevent "nested session" detection.
    # The SDK subprocess inherits os.environ, and CLAUDECODE triggers
    # "Claude Code cannot be launched inside another Claude Code session".
    saved_claudecode = os.environ.pop("CLAUDECODE", None)

    try:
        logger.info(
            f"SDK call: job={job_id} phase={phase} model={model} "
            f"max_turns={max_turns} cwd={cwd}"
        )

        options = ClaudeAgentOptions(
            model=model,
            permission_mode="acceptEdits",
            max_turns=max_turns,
            cwd=cwd,
        )

        # Collect results from async iterator
        all_tool_calls = []
        final_text = ""
        total_cost = 0.0
        total_tokens = 0
        turn_count = 0

        async for message in sdk_query(
            prompt=full_prompt,
            options=options,
        ):
            msg_type = type(message).__name__

            if msg_type == "AssistantMessage":
                # Track tool calls from assistant messages.
                # SDK returns content as list of SDK objects (ToolUseBlock,
                # TextBlock, ThinkingBlock) — NOT dicts.
                content = getattr(message, "content", None)
                if content and isinstance(content, list):
                    for block in content:
                        # SDK blocks are typed objects (ToolUseBlock, TextBlock,
                        # ThinkingBlock) without a .type string attr. Check class name.
                        block_cls = type(block).__name__
                        if block_cls == "ToolUseBlock" or (hasattr(block, "name") and hasattr(block, "input") and hasattr(block, "id")):
                            tool_name = getattr(block, "name", "unknown")
                            tool_input = getattr(block, "input", {})
                            all_tool_calls.append({
                                "tool": tool_name,
                                "input": tool_input,
                                "result": "(sdk-managed)",
                            })
                            _log_phase(job_id, phase, {
                                "event": "sdk_tool_call",
                                "tool": tool_name,
                                "input": {k: str(v)[:200] for k, v in tool_input.items()} if isinstance(tool_input, dict) else {},
                            })
                turn_count += 1

            elif msg_type == "ResultMessage":
                # Final result — extract all metrics
                final_text = getattr(message, "result", "") or ""
                total_cost = getattr(message, "total_cost_usd", 0.0) or 0.0
                num_turns = getattr(message, "num_turns", 0) or 0
                is_error = getattr(message, "is_error", False)

                # Extract token usage
                usage = getattr(message, "usage", {}) or {}
                if isinstance(usage, dict):
                    total_tokens = usage.get("output_tokens", 0) + usage.get("input_tokens", 0)

                logger.info(
                    f"SDK result: job={job_id} phase={phase} turns={num_turns} "
                    f"cost=${total_cost:.4f} tools={len(all_tool_calls)} "
                    f"error={is_error}"
                )

                if is_error:
                    logger.warning(f"SDK returned error for {job_id}/{phase}: {final_text[:500]}")

        # Update guardrails with SDK cost
        if guardrails and total_cost > 0:
            guardrails.cost_usd += total_cost

        # Log cost event
        if total_cost > 0:
            log_cost_event(
                project=job_id.split("-")[0] if job_id else "openclaw",
                agent=f"sdk_{model}",
                model=f"claude-{model}-sdk",
                tokens_input=total_tokens // 2,  # Approximate split
                tokens_output=total_tokens // 2,
                cost=total_cost,
            )

        return {
            "text": final_text,
            "tokens": total_tokens,
            "tool_calls": all_tool_calls,
            "cost_usd": total_cost,
        }

    finally:
        # Restore CLAUDECODE env var
        if saved_claudecode is not None:
            os.environ["CLAUDECODE"] = saved_claudecode


async def _call_agent(agent_key: str, prompt: str, conversation: list = None,
                      tools: list = None, job_id: str = "", phase: str = "",
                      guardrails: "JobGuardrails | None" = None,
                      department: str = "", priority: str = "P2") -> dict:
    """
    Call an agent model. Wraps the synchronous call_model_for_agent in an
    executor so it doesn't block the event loop. If tools are provided,
    they are passed to the Claude API for tool_use; the agent iterates
    until it stops requesting tool calls.

    CRITICAL: When tools are required (execute, verify, deliver phases),
    we use Anthropic provider since only Anthropic supports native tool_use.
    P3 jobs use Claude Haiku (cheap), all other priorities use Claude Sonnet
    (better quality). Non-Anthropic agents (Kimi, MiniMax, Deepseek) are
    used for text-only phases (research, plan).

    Returns: {"text": str, "tokens": int, "tool_calls": list[dict], "cost_usd": float}
    """
    # Import here to avoid circular imports at module level
    from gateway import call_model_for_agent, anthropic_client, get_agent_config

    agent_config = get_agent_config(agent_key)
    config_provider = agent_config.get("apiProvider", "anthropic") if agent_config else "anthropic"
    config_model = agent_config.get("model", "claude-opus-4-6") if agent_config else "claude-opus-4-6"

    # Track effective model/provider separately from agent_config so cost logging
    # uses the actual model that made the API call, not the originally-assigned one.
    effective_model = config_model
    effective_provider = config_provider

    total_tokens = 0
    total_cost = 0.0
    all_tool_calls = []
    final_text = ""

    # When tools are required, use Anthropic for actual execution.
    # Only Anthropic natively supports tool_use content blocks that we can dispatch
    # to execute_tool(). Non-Anthropic providers (Kimi/deepseek, MiniMax/minimax)
    # write tool calls as prose/code in their text response, which never executes.
    # Model selection: P3 -> Haiku (cheap), P0/P1/P2 -> Sonnet (better quality).
    if tools:
        # --- Oz path: multi-model orchestration via Warp Oz CLI ---
        if USE_OZ:
            try:
                from oz_executor import execute_with_oz_fallback

                # Build system prompt with department context
                oz_system = ""
                if department and department in DEPARTMENTS:
                    dept = DEPARTMENTS[department]
                    oz_system = dept.system_prompt
                else:
                    oz_system = (
                        "You are an autonomous AI agent executing a task step-by-step. "
                        "Read/write files, run shell commands, and complete the task."
                    )

                # Determine workspace
                oz_workspace = ""
                ws_match = re.search(r"WORKSPACE DIRECTORY[^:]*:\s*(\S+)", prompt)
                if ws_match and os.path.isdir(ws_match.group(1)):
                    oz_workspace = ws_match.group(1)
                elif job_id:
                    job_run_dir = JOB_RUNS_DIR / job_id / "workspace"
                    if job_run_dir.exists():
                        oz_workspace = str(job_run_dir)

                result = await execute_with_oz_fallback(
                    prompt=prompt,
                    workspace=oz_workspace or "/root/openclaw",
                    job_id=job_id,
                    phase=phase,
                    priority=priority,
                    guardrails=guardrails,
                    system_prompt=oz_system,
                )
                return result

            except ImportError:
                logger.warning("oz_executor not available — falling back to OpenCode/SDK")
            except Exception as oz_err:
                logger.warning(f"Oz path failed for {job_id}/{phase}: {oz_err} — trying OpenCode/SDK")

        # --- OpenCode path: cheap execution via OpenCode CLI (~90% savings) ---
        if USE_OPENCODE:
            try:
                from opencode_executor import execute_with_fallback

                # Build system prompt with department context
                oc_system = ""
                if department and department in DEPARTMENTS:
                    dept = DEPARTMENTS[department]
                    oc_system = dept.system_prompt
                else:
                    oc_system = (
                        "You are an autonomous AI agent executing a task step-by-step. "
                        "Read/write files, run shell commands, and complete the task."
                    )

                # Determine workspace
                oc_workspace = ""
                ws_match = re.search(r"WORKSPACE DIRECTORY[^:]*:\s*(\S+)", prompt)
                if ws_match and os.path.isdir(ws_match.group(1)):
                    oc_workspace = ws_match.group(1)
                elif job_id:
                    job_run_dir = JOB_RUNS_DIR / job_id / "workspace"
                    if job_run_dir.exists():
                        oc_workspace = str(job_run_dir)

                result = await execute_with_fallback(
                    prompt=prompt,
                    workspace=oc_workspace or "/root/openclaw",
                    job_id=job_id,
                    phase=phase,
                    priority=priority,
                    guardrails=guardrails,
                    system_prompt=oc_system,
                )
                return result

            except ImportError:
                logger.warning("opencode_executor not available — falling back to SDK/legacy")
            except Exception as oc_err:
                logger.warning(f"OpenCode path failed for {job_id}/{phase}: {oc_err} — trying SDK")

        # --- Grok path: xAI Grok as cheap fallback (~$0.001 for grok-3-mini) ---
        if USE_SDK:
            try:
                from grok_executor import execute_with_grok

                result = await execute_with_grok(
                    prompt=prompt,
                    job_id=job_id,
                    phase=phase,
                    priority=priority,
                    conversation=conversation,
                    system_prompt=oc_system if oc_system else "",
                )
                if result and result.get("text"):
                    logger.info(f"Grok completed {job_id}/{phase} for ${result.get('cost_usd', 0):.4f}")
                    return result
                logger.warning(f"Grok returned empty response for {job_id}/{phase} — trying GitHub Actions")
            except ImportError:
                logger.warning("grok_executor not available — trying GitHub Actions")
            except Exception as grok_err:
                logger.warning(f"Grok path failed for {job_id}/{phase}: {grok_err} — trying GitHub Actions")

        # --- GitHub Actions path: use Max Plan via claude-code-action ($0 cost) ---
        # Instead of calling Anthropic API directly (sdk_haiku/sdk_sonnet), route
        # through GitHub Issues → claude-code-action workflow → Max Plan OAuth token.
        if USE_SDK:
            try:
                from github_job_bridge import execute_via_github

                # Prepend conversation context into the prompt if available
                gh_prompt = prompt
                if conversation:
                    context_parts = []
                    for msg in conversation[-6:]:  # Last 3 exchanges max
                        role = msg.get("role", "user")
                        content = msg.get("content", "")
                        if isinstance(content, str) and content.strip():
                            context_parts.append(f"[Previous {role}]: {content[:1000]}")
                    if context_parts:
                        gh_prompt = "CONTEXT FROM PREVIOUS STEPS:\n" + "\n".join(context_parts) + "\n\n---\n\n" + prompt

                result = await execute_via_github(
                    prompt=gh_prompt,
                    job_id=job_id,
                    phase=phase,
                    priority=priority,
                )
                return result

            except ImportError:
                logger.warning("github_job_bridge not available — falling back to legacy")
            except Exception as gh_err:
                logger.error(f"GitHub Actions path failed for {job_id}/{phase}: {gh_err} — falling back to legacy")

        # --- Legacy path: manual tool-use loop ---
        # API fallback is disabled — route to GitHub Actions instead of paying Anthropic API.
        # If the GitHub Actions path above already ran and failed, we defer the job rather
        # than spending API money on the legacy Anthropic/Gemini tool-use loop.
        if effective_provider not in ("anthropic", "gemini"):
            logger.warning(
                f"Would have used Anthropic API for {job_id}/{phase} but API fallback is disabled. "
                f"Job will be retried on next cycle via OpenCode/GitHub."
            )
            return {
                "text": f"Execution deferred — OpenCode and GitHub Actions paths both unavailable for {phase}",
                "tokens": 0,
                "cost_usd": 0.0,
            }

        # Minimal system prompt for job execution context.
        # Department system prompt is prepended when available for domain expertise.
        base_system = (
            "You are an autonomous AI agent executing a task step-by-step using tools. "
            "When you need to perform an action (read/write files, run shell commands, "
            "git operations, etc.), you MUST use the provided tools — do NOT describe "
            "actions in text. Call tools directly. After all actions are complete, "
            "summarize what was done and the outcome."
        )
        # Inject department-specific system prompt if available
        if department and department in DEPARTMENTS:
            dept = DEPARTMENTS[department]
            system_prompt = f"{dept.system_prompt}\n\n{base_system}"
        else:
            system_prompt = base_system

        # Build messages
        messages = list(conversation or [])
        messages.append({"role": "user", "content": prompt})

        # Get the event loop once before the iteration loop (Python 3.10+ compatible)
        loop = asyncio.get_running_loop()

        # Cache system prompt (doesn't change between iterations)
        cached_system = [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}] if isinstance(system_prompt, str) else system_prompt

        # Cache tool definitions (they don't change between calls)
        cached_tools = list(tools) if tools else []
        if cached_tools:
            cached_tools[-1] = {**cached_tools[-1], "cache_control": {"type": "ephemeral"}}

        # Tool-use loop: agent may request tools multiple times.
        # Loop continues until the model returns no tool_use blocks.
        # Supports both Anthropic SDK objects and Gemini dict-based responses.
        iterations = 0
        use_gemini = effective_provider == "gemini"

        # Loop detection: track (tool_name, input_hash) → count.
        # If same call repeated LOOP_DETECT_THRESHOLD times, force-break.
        _tool_call_counts: dict[str, int] = {}
        _loop_detected = False

        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1

            # --- Guardrail check at every tool-loop iteration ---
            if guardrails:
                guardrails.record_iteration(cost_increment=0)  # cost added after API call
                try:
                    guardrails.check()
                except GuardrailViolation:
                    raise  # Propagate to pipeline handler

            if use_gemini:
                # Gemini tool-use path — use GeminiClient directly
                from gemini_client import GeminiClient as _GeminiClient

                # Flatten messages to a single prompt for Gemini
                prompt_parts = []
                for m in messages:
                    role_label = "User" if m["role"] == "user" else "Assistant"
                    c = m["content"]
                    if isinstance(c, str):
                        prompt_parts.append(f"{role_label}: {c}")
                    elif isinstance(c, list):
                        for block in c:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    prompt_parts.append(f"{role_label}: {block['text']}")
                                elif block.get("type") == "tool_result":
                                    prompt_parts.append(f"Tool result ({block.get('tool_use_id','')}): {block.get('content','')}")

                flat_prompt = "\n".join(prompt_parts)
                _gemini_client = _GeminiClient()

                _current_model = effective_model
                _current_tools = tools
                gemini_response = await loop.run_in_executor(
                    None,
                    lambda: _gemini_client.call(
                        model=_current_model,
                        prompt=flat_prompt,
                        system_prompt=system_prompt,
                        max_tokens=8192,
                        tools=_current_tools,
                    )
                )

                tokens_in = gemini_response.tokens_input
                tokens_out = gemini_response.tokens_output
                total_tokens += tokens_out
                step_cost = calculate_cost(effective_model, tokens_in, tokens_out)
                total_cost += step_cost

                # Update guardrails with actual cost from this API call
                if guardrails:
                    guardrails.cost_usd += step_cost

                log_cost_event(
                    project=job_id.split("-")[0] if job_id else "openclaw",
                    agent=agent_key,
                    model=effective_model,
                    tokens_input=tokens_in,
                    tokens_output=tokens_out,
                    cost=step_cost,
                )

                final_text = gemini_response.content or ""
                tool_use_blocks = gemini_response.tool_calls or []

                if not tool_use_blocks:
                    break

                # Execute each Gemini tool call (already normalized to dicts)
                tool_results = []
                serialized_content = []
                if final_text:
                    serialized_content.append({"type": "text", "text": final_text})

                for tc in tool_use_blocks:
                    tool_name = tc["name"]
                    tool_input = tc.get("input", {})
                    tc_id = tc.get("id", f"gemini_tc_{iterations}")

                    serialized_content.append({
                        "type": "tool_use", "id": tc_id,
                        "name": tool_name, "input": tool_input,
                    })

                    _log_phase(job_id, phase, {"event": "tool_call", "tool": tool_name, "input": tool_input})

                    result_str = await loop.run_in_executor(
                        None, _execute_tool_routed, tool_name, tool_input, phase, job_id, agent_key
                    )

                    all_tool_calls.append({"tool": tool_name, "input": tool_input, "result": result_str[:2000]})
                    _log_phase(job_id, phase, {"event": "tool_result", "tool": tool_name, "result": result_str[:500]})

                    tool_results.append({"type": "tool_result", "tool_use_id": tc_id, "content": result_str})

                    # --- Loop detection: track repeated tool calls ---
                    call_sig = _make_call_signature(tool_name, tool_input)
                    if _check_loop(call_sig, _tool_call_counts, job_id, phase):
                        _loop_detected = True

                messages.append({"role": "assistant", "content": serialized_content})
                messages.append({"role": "user", "content": tool_results})

                # Force-break on loop detection
                if _loop_detected:
                    logger.warning(f"Force-breaking tool loop for {job_id}/{phase} after {iterations} iterations (repeated calls detected)")
                    final_text += "\n\n[STOPPED: Repeated tool call detected — moving to next step]"
                    break

                # Save checkpoint after successful tool execution
                if job_id:
                    save_checkpoint(
                        job_id=job_id, phase=phase, step_index=0,
                        tool_iteration=iterations,
                        state={"text_so_far": final_text[:1000], "tool_calls_count": len(all_tool_calls)},
                        messages=messages[-10:],
                    )

                # Rolling window: keep original prompt + last N turns.
                # Must preserve assistant/user alternation — start tail from
                # an assistant message so tool_use precedes tool_result.
                if len(messages) > 20:
                    tail = messages[-18:]  # even count = complete pairs
                    if tail and tail[0].get("role") == "user":
                        tail = tail[1:]  # drop orphaned tool_result
                    messages = [messages[0]] + tail

            else:
                # Anthropic tool-use path (original)
                # NOTE: We do NOT add cache_control to user messages.
                # System prompt + tools already use 2 cache blocks. Adding
                # user-message blocks risks exceeding Anthropic's max of 4
                # cache_control blocks, which causes API errors and job failures.
                # System + tools caching alone provides most of the benefit.

                # Snapshot current messages list length to avoid lambda closure mutation issues
                _current_messages = list(messages)
                _current_model = effective_model
                _current_tools = cached_tools or tools
                _current_system = cached_system

                response = await loop.run_in_executor(
                    None,
                    lambda: anthropic_client.messages.create(
                        model=_current_model,
                        max_tokens=8192,
                        system=_current_system,
                        messages=_current_messages,
                        tools=_current_tools,
                    )
                )

                tokens_in = response.usage.input_tokens
                tokens_out = response.usage.output_tokens
                total_tokens += tokens_out
                step_cost = calculate_cost(effective_model, tokens_in, tokens_out)
                total_cost += step_cost

                # Update guardrails with actual cost from this API call
                if guardrails:
                    guardrails.cost_usd += step_cost

                # Log cost
                log_cost_event(
                    project=job_id.split("-")[0] if job_id else "openclaw",
                    agent=agent_key,
                    model=effective_model,
                    tokens_input=tokens_in,
                    tokens_output=tokens_out,
                    cost=step_cost,
                )

                # Process response content blocks
                tool_use_blocks = []
                text_parts = []

                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                    elif block.type == "tool_use":
                        tool_use_blocks.append(block)

                final_text = "\n".join(text_parts)

                # If no tool calls, we are done
                if not tool_use_blocks:
                    break

                # Execute each tool call
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name = tool_block.name
                    tool_input = tool_block.input

                    _log_phase(job_id, phase, {
                        "event": "tool_call",
                        "tool": tool_name,
                        "input": tool_input,
                    })

                    # Run tool in executor (some tools do subprocess/IO)
                    result_str = await loop.run_in_executor(
                        None, _execute_tool_routed, tool_name, tool_input, phase, job_id, agent_key
                    )

                    all_tool_calls.append({
                        "tool": tool_name,
                        "input": tool_input,
                        "result": result_str[:2000],
                    })

                    _log_phase(job_id, phase, {
                        "event": "tool_result",
                        "tool": tool_name,
                        "result": result_str[:500],
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": result_str,
                    })

                    # --- Loop detection: track repeated tool calls ---
                    call_sig = _make_call_signature(tool_name, tool_input)
                    if _check_loop(call_sig, _tool_call_counts, job_id, phase):
                        _loop_detected = True

                # Nudge agent to wrap up if approaching iteration limit
                if iterations == TOOL_NUDGE_THRESHOLD and tool_results:
                    nudge = (
                        f"\n\n[SYSTEM: You have used {iterations} tool calls for this step. "
                        f"Wrap up now — summarize what you've done and move on. "
                        f"Remaining budget: {MAX_TOOL_ITERATIONS - iterations} calls.]"
                    )
                    tool_results[-1]["content"] += nudge

                # Append assistant response + tool results to messages for next iteration
                # IMPORTANT: Serialize response.content to dicts (not SDK objects)
                serialized_content = []
                for block in response.content:
                    if block.type == "text":
                        serialized_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        serialized_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input
                        })

                messages.append({"role": "assistant", "content": serialized_content})
                messages.append({"role": "user", "content": tool_results})

                # Force-break on loop detection
                if _loop_detected:
                    logger.warning(f"Force-breaking tool loop for {job_id}/{phase} after {iterations} iterations (repeated calls detected)")
                    final_text += "\n\n[STOPPED: Repeated tool call detected — moving to next step]"
                    break

                # Save checkpoint after successful tool execution
                if job_id:
                    save_checkpoint(
                        job_id=job_id, phase=phase, step_index=0,
                        tool_iteration=iterations,
                        state={"text_so_far": final_text[:1000], "tool_calls_count": len(all_tool_calls)},
                        messages=messages[-10:],
                    )

                # Rolling window: keep original prompt + last N turns.
                # Must preserve assistant/user alternation — start tail from
                # an assistant message so tool_use precedes tool_result.
                if len(messages) > 20:
                    tail = messages[-18:]  # even count = complete pairs
                    if tail and tail[0].get("role") == "user":
                        tail = tail[1:]  # drop orphaned tool_result
                    messages = [messages[0]] + tail

        return {
            "text": final_text,
            "tokens": total_tokens,
            "tool_calls": all_tool_calls,
            "cost_usd": total_cost,
        }

    else:
        # Non-tool call path (text-only, non-Anthropic provider)
        # Add 90-second timeout to prevent Deepseek/Kimi API hangs from blocking forever
        loop = asyncio.get_running_loop()
        try:
            response_text, tokens = await asyncio.wait_for(
                loop.run_in_executor(
                    None, call_model_for_agent, agent_key, prompt, conversation
                ),
                timeout=90,
            )
        except asyncio.TimeoutError:
            logger.warning(f"API call timed out after 90s for agent={agent_key} job={job_id} phase={phase}")
            return {
                "text": f"[API timeout after 90s — {agent_key}/{config_provider}/{config_model}]",
                "tokens": 0,
                "tool_calls": [],
                "cost_usd": 0.0,
            }
        # Estimate cost for non-Anthropic models based on tokens
        est_cost = calculate_cost(config_model, tokens // 2, tokens // 2) if tokens else 0.0
        return {
            "text": response_text,
            "tokens": tokens,
            "tool_calls": [],
            "cost_usd": est_cost,
        }


# ---------------------------------------------------------------------------
# Execution Pipeline — 5 Phases
# ---------------------------------------------------------------------------

async def _research_phase(job: dict, agent_key: str, progress: JobProgress,
                          guardrails: "JobGuardrails | None" = None,
                          department: str = "") -> str:
    """
    Phase 1: RESEARCH
    Gather context about the task — read relevant files, search the web,
    understand the codebase. Returns a research summary string.
    """
    progress.phase = Phase.RESEARCH
    progress.phase_status = "running"
    _save_progress(progress)
    if guardrails:
        guardrails.set_phase("research")

    task = job["task"]
    project = job.get("project", "unknown")
    workspace = progress.workspace

    # Inject past experience from reflexion loop (department-aware)
    past_reflections = search_reflections(task, project=project, department=department, limit=3)
    reflexion_context = format_reflections_for_prompt(past_reflections)
    if reflexion_context:
        logger.info(f"Job {job['id']}: Injecting {len(past_reflections)} past reflections into research prompt")

    # Load department-specific knowledge instead of generic project context
    if department:
        dept_knowledge = load_department_knowledge(department, project)
    else:
        dept_knowledge = _load_project_context(project)

    prompt = (
        f"You are researching a task before planning and executing it.\n\n"
        f"PROJECT: {project}\n"
        f"DEPARTMENT: {department or 'general'}\n"
        f"TASK: {task}\n\n"
        f"WORKSPACE DIRECTORY: {workspace}\n"
        f"This is your isolated working directory for this job. Any files you need to\n"
        f"clone, download, or create during research should go inside {workspace}/\n\n"
    )

    if dept_knowledge:
        prompt += f"{dept_knowledge}\n\n"

    if reflexion_context:
        prompt += f"{reflexion_context}\n\n"

    # Inject shared blackboard context from previous jobs
    bb_context = blackboard_context(project)
    if bb_context:
        prompt += f"{bb_context}\n\n"

    # Inject repo-map so agent skips exploratory file listing
    repo_map = job.get("_repo_map")
    if repo_map:
        prompt += f"PROJECT STRUCTURE:\n{repo_map}\n\n"

    prompt += (
        f"Gather all the context you need:\n"
        f"1. Use research_task to understand the domain/technology involved\n"
        f"2. Use glob_files and grep_search to find relevant existing code\n"
        f"3. Use file_read to examine key files\n"
        f"4. Use github_repo_info to check open issues/PRs if relevant\n\n"
        f"STOP CONDITIONS: Stop researching when you have enough context to plan. "
        f"Do NOT exhaustively read every file — 3-5 key files is usually enough. "
        f"If a search returns no results, move on — don't retry with slight variations.\n\n"
        f"After researching, provide a structured summary:\n"
        f"- RELEVANT FILES: List the files that need to change or are related\n"
        f"- EXISTING PATTERNS: Key patterns/conventions in the codebase\n"
        f"- DEPENDENCIES: What this task depends on\n"
        f"- RISKS: Potential issues or gotchas\n"
        f"- CONTEXT: Any other important context for planning"
    )

    tools = _filter_tools_for_phase(Phase.RESEARCH)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="research",
                               guardrails=guardrails, department=department,
                               priority=job.get("priority", "P2"))

    progress.cost_usd += result["cost_usd"]
    progress.phase_status = "done"
    _save_progress(progress)

    _log_phase(job["id"], "research", {
        "event": "phase_complete",
        "summary_length": len(result["text"]),
        "tool_calls": len(result["tool_calls"]),
        "cost_usd": result["cost_usd"],
    })

    return result["text"]


async def _plan_phase(job: dict, agent_key: str, research: str,
                      progress: JobProgress,
                      guardrails: "JobGuardrails | None" = None) -> ExecutionPlan:
    """
    Phase 2: PLAN
    Create a step-by-step execution plan based on research findings.
    Returns an ExecutionPlan with concrete steps.
    """
    progress.phase = Phase.PLAN
    progress.phase_status = "running"
    _save_progress(progress)
    if guardrails:
        guardrails.set_phase("plan")

    task = job["task"]
    project = job.get("project", "unknown")

    # Inject repo-map so planner knows project structure
    repo_map = job.get("_repo_map", "")
    repo_map_section = f"PROJECT STRUCTURE:\n{repo_map}\n\n" if repo_map else ""

    prompt = (
        f"Based on the research below, create a concrete step-by-step plan to complete this task.\n\n"
        f"PROJECT: {project}\n"
        f"TASK: {task}\n\n"
        f"{repo_map_section}"
        f"RESEARCH FINDINGS:\n{research}\n\n"
        f"Create a plan with numbered steps. For each step specify:\n"
        f"- A clear description of what to do\n"
        f"- Which tools to use (file_write, file_edit, shell_execute, git_operations, etc.)\n"
        f"- Optionally, a 'delegate_to' agent key if the step should be handled by a specialist:\n"
        f"  Available agents: coder_agent, elite_coder, hacker_agent, database_agent, research_agent\n\n"
        f"IMPORTANT: Respond ONLY with valid JSON in this exact format:\n"
        f'{{"steps": [\n'
        f'  {{"description": "Step 1: ...", "tools": ["file_write", "shell_execute"]}},\n'
        f'  {{"description": "Step 2: ...", "tools": ["file_edit"], "delegate_to": "elite_coder"}}\n'
        f"]}}\n\n"
        f"Keep the plan LEAN — minimum steps needed. Aim for 3-6 steps.\n"
        f"Each step should do ONE concrete action (write code, run test, etc).\n"
        f"Do NOT add separate 'documentation' or 'reporting' steps — just build and test.\n"
        f"Maximum {MAX_PLAN_STEPS} steps. Fewer is better.\n"
        f"Do NOT include markdown fences or any text outside the JSON."
    )

    tools = _filter_tools_for_phase(Phase.PLAN)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="plan",
                               guardrails=guardrails,
                               priority=job.get("priority", "P2"))

    progress.cost_usd += result["cost_usd"]

    # Parse the plan from the agent response
    plan_text = result["text"].strip()

    # Try to extract JSON from the response (agent may wrap it in markdown)
    plan_data = None
    for attempt_str in [plan_text, _extract_json_block(plan_text)]:
        try:
            plan_data = json.loads(attempt_str)
            break
        except (json.JSONDecodeError, TypeError):
            continue

    if not plan_data or "steps" not in plan_data:
        # Retry once with stricter prompt before falling back
        logger.warning(f"Could not parse plan JSON for {job['id']}, retrying with stricter prompt")
        retry_prompt = (
            f"Your previous response was not valid JSON. Respond with ONLY a JSON object, "
            f"no markdown, no explanation.\n\n"
            f"TASK: {task}\n\n"
            f'Return exactly: {{"steps": [{{"description": "...", "tools": ["..."]}}]}}\n'
        )
        retry_result = await _call_agent(agent_key, retry_prompt, tools=tools,
                                          job_id=job["id"], phase="plan",
                                          guardrails=guardrails,
                                          priority=job.get("priority", "P2"))
        progress.cost_usd += retry_result["cost_usd"]
        retry_text = retry_result["text"].strip()
        for attempt_str in [retry_text, _extract_json_block(retry_text)]:
            try:
                plan_data = json.loads(attempt_str)
                if "steps" in plan_data:
                    break
                plan_data = None
            except (json.JSONDecodeError, TypeError):
                continue

    if not plan_data or "steps" not in plan_data:
        # Final fallback: 3 generic steps (read → implement → test)
        logger.warning(f"Plan retry also failed for {job['id']}, using 3-step fallback plan")
        plan_data = {"steps": [
            {"description": f"Read relevant files and understand the codebase for: {task}", "tools": ["file_read", "glob_files", "grep_search"]},
            {"description": f"Implement the changes: {task}", "tools": ["file_write", "file_edit", "shell_execute"]},
            {"description": f"Test and verify the changes work correctly", "tools": ["shell_execute", "file_read"]},
        ]}

    plan = ExecutionPlan(
        job_id=job["id"],
        agent=agent_key,
        created_at=_now_iso(),
    )

    for i, step_data in enumerate(plan_data["steps"][:MAX_PLAN_STEPS]):
        plan.steps.append(PlanStep(
            index=i,
            description=step_data.get("description", f"Step {i+1}"),
            tool_hints=step_data.get("tools", []),
            delegate_to=step_data.get("delegate_to", ""),
        ))

    progress.total_steps = len(plan.steps)
    progress.phase_status = "done"
    _save_progress(progress)

    # Persist plan to disk
    run_dir = _job_run_dir(job["id"])
    with open(run_dir / "plan.json", "w") as f:
        json.dump(plan.to_dict(), f, indent=2)

    _log_phase(job["id"], "plan", {
        "event": "phase_complete",
        "steps_count": len(plan.steps),
        "cost_usd": result["cost_usd"],
    })

    return plan


async def _execute_phase(job: dict, agent_key: str, plan: ExecutionPlan,
                         research: str, progress: JobProgress,
                         guardrails: "JobGuardrails | None" = None,
                         department: str = "") -> list:
    """
    Phase 3: EXECUTE
    Run each step in the plan. The agent gets the step description plus
    tool access and decides which tools to call.

    Returns a list of step results.
    """
    progress.phase = Phase.EXECUTE
    progress.phase_status = "running"
    _save_progress(progress)
    if guardrails:
        guardrails.set_phase("execute")

    results = []
    conversation_context = []
    workspace = progress.workspace

    for step in plan.steps:
        if progress.cancelled:
            step.status = "skipped"
            results.append({"step": step.index, "status": "skipped", "reason": "job cancelled"})
            continue

        step.status = "running"
        progress.step_index = step.index
        _save_progress(progress)

        # Determine which agent runs this step (delegation support)
        step_agent = step.delegate_to if step.delegate_to else agent_key
        tools = _filter_tools_for_phase(Phase.EXECUTE, agent_key=step_agent)

        if step.delegate_to:
            logger.info(
                f"Step {step.index} delegated to {step.delegate_to} "
                f"(tools: {len(tools)}) for job {job['id']}"
            )

        # Build focused context bundle (token-optimized)
        context_bundle = _build_context_bundle(step, research, results)

        # Load department-specific knowledge (more focused than generic project context)
        if department:
            project_context = load_department_knowledge(department, job.get("project", ""))
        else:
            project_context = _load_project_context(job.get("project", ""))

        prompt = (
            f"You are executing step {step.index + 1} of {len(plan.steps)} for a job.\n\n"
            f"PROJECT: {job.get('project', 'unknown')}\n"
            f"DEPARTMENT: {department or 'general'}\n"
            f"OVERALL TASK: {job['task']}\n\n"
            f"WORKSPACE DIRECTORY (for temp/scratch files): {workspace}\n"
            f"IMPORTANT: Edit the ACTUAL PROJECT FILES at their real paths on disk.\n"
            f"If the task says to edit /root/Delhi-Palace/src/app/kds/page.tsx, write to THAT path.\n"
            f"Only use the workspace for scratch files, clones, or new standalone projects.\n"
            f"DO NOT write analysis documents — write actual code.\n\n"
        )

        # File ownership header for conflict prevention
        if department and department in DEPARTMENTS:
            dept = DEPARTMENTS[department]
            prompt += f"FILES YOU OWN: {', '.join(dept.file_patterns)}. Do NOT modify files outside your ownership.\n\n"

        if project_context:
            prompt += f"{project_context}\n\n"

        prompt += (
            f"{context_bundle}\n\n"
            f"CURRENT STEP: {step.description}\n"
            f"SUGGESTED TOOLS: {', '.join(step.tool_hints)}\n\n"
        )

        # --- Stolen patterns from Devin, Cursor, Windsurf ---

        # Pattern 1 (Devin): Think before critical decisions
        prompt += (
            "## THINK BEFORE ACTING\n"
            "Before making any of these moves, STOP and reason through it explicitly:\n"
            "- Deleting or overwriting existing code\n"
            "- Multi-file changes that could break imports\n"
            "- Choosing between two valid approaches\n"
            "- When you're stuck or an approach isn't working after 2 attempts\n"
            "Write your reasoning as: THINK: [your analysis]. Then proceed.\n\n"
        )

        # Pattern 2 (Windsurf): Live plan adaptation
        prompt += (
            "## PLAN ADAPTATION\n"
            f"You are on step {step.index + 1} of {len(plan.steps)}. "
            "If this step doesn't match reality (file doesn't exist, approach won't work, "
            "prerequisite is missing), DO NOT blindly follow it. Instead:\n"
            "1. State what's different from expected\n"
            "2. Adapt the approach to what actually works\n"
            "3. Complete the step's intent, not its exact wording\n\n"
        )

        # Pattern 3 (Cursor): Surface discoveries for memory
        prompt += (
            "## CAPTURE DISCOVERIES\n"
            "If you discover something important while working (a pattern in the codebase, "
            "a gotcha, a useful file path, an API quirk), note it at the end of your response as:\n"
            "DISCOVERY: [what you found]\n"
            "These get saved for future agent runs.\n\n"
        )

        # Pattern 4: Stop conditions to prevent iteration loops
        prompt += (
            "## STOP CONDITIONS\n"
            "STOP and move on if ANY of these are true:\n"
            "- You've tried the same approach twice without progress\n"
            "- A file or resource doesn't exist after checking twice\n"
            "- A command fails with the same error on retry\n"
            "- You're reading the same files repeatedly without making changes\n"
            "- The step is complete (don't keep polishing — move on)\n"
            "Do NOT loop. If stuck, state what went wrong and stop.\n\n"
        )

        prompt += (
            f"Execute this step now using the available tools. "
            f"When done, summarize what you did and the outcome."
        )

        # Retry logic per step (Adaptive Retry — diagnose failures before retrying)
        error_history: list[dict] = []  # track each attempt's error + diagnosis
        step_result = None
        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                result = await _call_agent(step_agent, prompt, tools=tools,
                                           job_id=job["id"], phase="execute",
                                           guardrails=guardrails,
                                           department=department,
                                           priority=job.get("priority", "P2"))
                progress.cost_usd += result["cost_usd"]

                # Budget check (legacy fallback — guardrails are the primary check)
                budget_limit = guardrails.max_cost_usd * 1.10 if guardrails else DEFAULT_BUDGET_LIMIT_USD
                if progress.cost_usd > budget_limit:
                    raise BudgetExceededError(
                        f"Job budget exceeded: ${progress.cost_usd:.4f} > ${budget_limit:.2f}"
                    )

                # Clear error streak on success (for circuit breaker)
                if guardrails:
                    guardrails.clear_errors()

                step.status = "done"
                step.result = result["text"][:5000]
                step.attempts = attempt + 1

                # Pattern 3 (Cursor): Extract and save discoveries from agent output
                _extract_and_save_discoveries(
                    result["text"], job["id"], job.get("project", "unknown")
                )

                step_result = {
                    "step": step.index,
                    "status": "done",
                    "summary": result["text"][:500],
                    "tool_calls": len(result["tool_calls"]),
                    "cost_usd": result["cost_usd"],
                    "attempts": attempt + 1,
                }
                break

            except (BudgetExceededError, GuardrailViolation, CreditExhaustedError):
                raise  # Don't retry budget/guardrail/credit failures

            except Exception as e:
                # Circuit breaker: credit balance / billing errors are non-retryable
                err_lower = str(e).lower()
                if "credit balance" in err_lower or "billing" in err_lower or "insufficient_quota" in err_lower:
                    logger.error(f"Credit/billing error for {job['id']}: {e} — stopping immediately")
                    raise CreditExhaustedError(
                        f"API credit/billing error (non-retryable): {e}"
                    ) from e

                # 6-category error classification (Devin MCP matrix pattern)
                error_class = _classify_error(str(e))
                error_config = _get_error_config(error_class)

                # Immediate-stop categories: auth, permission
                if error_config["action"] in ("escalate", "skip") and error_config["max_retries"] == 0:
                    logger.warning(
                        f"Step {step.index} {error_class.upper()} error for {job['id']}: {e}. "
                        f"Action: {error_config['action']} (no retry)."
                    )
                    _log_phase(job["id"], "execute", {
                        "event": f"step_{error_config['action']}",
                        "step": step.index,
                        "error": str(e),
                        "error_class": error_class,
                    })
                    break

                # Record error for circuit breaker
                if guardrails:
                    guardrails.record_error(str(e))
                step.attempts = attempt + 1

                # Category-aware backoff
                if error_config["backoff"] == "exponential":
                    backoff = (2 ** attempt) * 2  # 2s, 4s, 8s
                elif error_config["backoff"] == "fixed":
                    backoff = 3  # Fixed 3s for code errors
                else:
                    backoff = 1

                # Max retries per error category
                max_retries_for_error = error_config["max_retries"]

                # --- Adaptive Retry: diagnose failure and modify prompt ---
                error_entry = {"attempt": attempt + 1, "error": str(e)[:500], "error_class": error_class}
                diagnosis = await _diagnose_failure(
                    error_text=str(e),
                    original_prompt=prompt,
                    phase="execute",
                    error_history=error_history,
                    error_class=error_class,
                    job_task=job.get("task", ""),
                )
                error_entry["diagnosis"] = diagnosis.get("diagnosis", "")[:300]
                error_entry["root_cause"] = diagnosis.get("root_cause", "")[:200]
                error_entry["strategy"] = diagnosis.get("strategy", "retry")
                error_history.append(error_entry)

                # Use diagnosis strategy (overrides category default if diagnosis is smarter)
                diag_strategy = diagnosis.get("strategy", "retry")
                if diag_strategy == "skip":
                    logger.info(f"Step {step.index}: diagnosis recommends SKIP — moving on")
                    break
                elif diag_strategy == "escalate":
                    logger.info(f"Step {step.index}: diagnosis recommends ESCALATE")

                # Use modified prompt from diagnosis (for diagnose_and_rewrite categories)
                modified_prompt = diagnosis.get("modified_prompt", "")
                if modified_prompt and len(modified_prompt) > 50:
                    prompt = modified_prompt
                    logger.info(
                        f"Step {step.index}: using diagnosed modified prompt ({len(prompt)} chars). "
                        f"Root cause: {diagnosis.get('root_cause', 'n/a')[:60]}"
                    )

                # Check agent template failure recovery strategy
                agent_recovery = get_failure_recovery(step_agent)
                if agent_recovery == "skip" and attempt >= 1:
                    logger.info(f"Step {step.index}: agent template says SKIP after {attempt+1} attempts")
                    break
                elif agent_recovery == "escalate" and attempt >= 1:
                    logger.warning(f"Step {step.index}: agent template says ESCALATE — flagging for PM review")
                    _log_phase(job["id"], "execute", {
                        "event": "step_escalated",
                        "step": step.index,
                        "error_history": error_history,
                    })
                    break

                logger.warning(
                    f"Step {step.index} attempt {attempt+1} failed for {job['id']} "
                    f"[{error_class}]: {e}. Root cause: {diagnosis.get('root_cause', 'n/a')[:60]}. "
                    f"Retrying in {backoff}s (max {max_retries_for_error})..."
                )
                _log_phase(job["id"], "execute", {
                    "event": "step_retry",
                    "step": step.index,
                    "attempt": attempt + 1,
                    "error": str(e),
                    "error_class": error_class,
                    "root_cause": diagnosis.get("root_cause", "")[:200],
                    "diagnosis": diagnosis.get("diagnosis", "")[:200],
                    "backoff_seconds": backoff,
                })
                if attempt < max_retries_for_error - 1:
                    await asyncio.sleep(backoff)
                else:
                    break  # Exhausted retries for this error category

        if step_result is None:
            step.status = "failed"
            step.error = f"Failed after {DEFAULT_MAX_RETRIES} attempts"
            step_result = {
                "step": step.index,
                "status": "failed",
                "error": step.error,
                "attempts": DEFAULT_MAX_RETRIES,
            }

        results.append(step_result)
        _save_progress(progress)

        # Save checkpoint after each step completion for resume support
        save_checkpoint(
            job_id=job["id"], phase="execute", step_index=step.index,
            tool_iteration=0,
            state={
                "completed_steps": [r["step"] for r in results if r.get("status") == "done"],
                "current_step": step.index,
                "total_steps": len(plan.steps),
            },
            messages=[],
        )

        _log_phase(job["id"], "execute", {
            "event": "step_complete",
            **step_result,
        })

    progress.phase_status = "done"
    _save_progress(progress)

    return results


# ---------------------------------------------------------------------------
# Phase 3.5: TRIPLE AI CODE REVIEW
# ---------------------------------------------------------------------------
async def _code_review_phase(
    job: dict,
    execution_results: list,
    progress: JobProgress,
    guardrails: "JobGuardrails | None" = None,
) -> dict:
    """
    Phase 3.5: CODE REVIEW (between EXECUTE and VERIFY)

    Triple-review inspired by Elvis's agent swarm pattern:
      1. Code Reviewer (Kimi 2.5 — $0.14/M) — logic errors, patterns, edge cases
      2. Static analysis (free) — syntax checks on changed Python/JS files
      3. Security review (Kimi Reasoner — $0.27/M) — only for security-relevant changes

    Returns:
        dict with reviews, issues_found, has_critical, passed, cost_usd
    """
    project = job.get("project", "unknown")
    job_id = job["id"]

    # Map projects to repo paths
    project_paths = {
        "barber-crm":     "/root/Barber-CRM",
        "delhi-palace":   "/root/Delhi-Palace",
        "openclaw":       "/root/openclaw",
        "prestress-calc": "/root/Mathcad-Scripts",
        "concrete-canoe": "/root/concrete-canoe-project2026",
    }
    repo_path = project_paths.get(project, f"/root/{project}")

    # --- Collect the git diff of changes made during EXECUTE ---
    git_diff = ""
    try:
        # Try uncommitted changes first
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--stat", "--patch",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        git_diff = stdout.decode(errors="replace")

        # If nothing uncommitted, check staged
        if not git_diff.strip():
            proc2 = await asyncio.create_subprocess_exec(
                "git", "diff", "--cached", "--stat", "--patch",
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=15)
            git_diff = stdout2.decode(errors="replace")

        # If still nothing, try last commit
        if not git_diff.strip():
            proc3 = await asyncio.create_subprocess_exec(
                "git", "diff", "HEAD~1", "--stat", "--patch",
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout3, _ = await asyncio.wait_for(proc3.communicate(), timeout=15)
            git_diff = stdout3.decode(errors="replace")
    except Exception as e:
        logger.warning(f"Job {job_id}: code review — git diff failed: {e}")

    # Cap diff to avoid token explosion
    git_diff = git_diff[:8000]

    if not git_diff.strip():
        logger.info(f"Job {job_id}: code review — no diff found, skipping")
        return {
            "reviews": [],
            "review_count": 0,
            "issues_found": 0,
            "has_critical": False,
            "passed": True,
            "cost_usd": 0.0,
            "summary": "No changes detected — review skipped",
        }

    # Build execution summary
    steps_summary = "\n".join(
        f"- Step {r.get('step', '?')}: {r.get('summary', r.get('status', '?'))}"
        for r in execution_results
    )

    # --- Extract list of changed files from diff ---
    changed_files = []
    for line in git_diff.splitlines():
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            if len(parts) > 1:
                changed_files.append(parts[-1])

    logger.info(f"Job {job_id}: code review — {len(changed_files)} files changed, diff {len(git_diff)} chars")

    reviews = []
    total_cost = 0.0

    # ---- REVIEW 1: Code Reviewer (Kimi 2.5 — $0.14/M, pattern-focused) ----
    review_prompt = (
        f"You are reviewing code changes for quality, correctness, and maintainability.\n\n"
        f"TASK: {job['task']}\n"
        f"PROJECT: {project}\n\n"
        f"EXECUTION SUMMARY:\n{steps_summary}\n\n"
        f"GIT DIFF:\n```\n{git_diff}\n```\n\n"
        f"Review for:\n"
        f"1. Logic errors or bugs\n"
        f"2. Missing error handling for edge cases\n"
        f"3. Code that doesn't match the task intent\n"
        f"4. Regressions (breaking existing functionality)\n"
        f"5. Naming and readability issues (critical only)\n\n"
        f"Respond with ONLY a JSON object (no markdown fences):\n"
        f'{{"severity": "pass|minor|major|critical", '
        f'"issues": [{{"type": "bug|logic|edge_case|regression|style", '
        f'"file": "filename", "description": "...", "suggestion": "..."}}], '
        f'"summary": "one-line verdict"}}'
    )

    try:
        r1 = await _call_agent(
            "code_reviewer", review_prompt, tools=None,
            job_id=job_id, phase="code_review",
            guardrails=guardrails, priority=job.get("priority", "P2"),
        )
        total_cost += r1.get("cost_usd", 0)
        reviews.append({
            "reviewer": "code_reviewer",
            "model": "kimi-2.5",
            "cost_usd": r1.get("cost_usd", 0),
            "response": r1.get("text", ""),
        })
        logger.info(f"Job {job_id}: code review #1 (Code Reviewer) done — ${r1.get('cost_usd', 0):.4f}")
    except Exception as e:
        logger.warning(f"Job {job_id}: code review #1 failed: {e}")
        reviews.append({"reviewer": "code_reviewer", "error": str(e)})

    # ---- REVIEW 2: Static Analysis (FREE — no LLM cost) ----
    static_issues = []
    py_files = [f for f in changed_files if f.endswith(".py")]
    js_ts_files = [f for f in changed_files if f.endswith((".js", ".ts", ".tsx", ".jsx"))]

    # Python syntax check
    for pf in py_files[:10]:  # Cap at 10 files
        full_path = os.path.join(repo_path, pf)
        if os.path.isfile(full_path):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-m", "py_compile", full_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if stderr:
                    static_issues.append(f"Python syntax error in {pf}: {stderr.decode()[:200]}")
            except Exception:
                pass

    # JS/TS syntax check via node --check
    for jf in js_ts_files[:10]:
        full_path = os.path.join(repo_path, jf)
        if os.path.isfile(full_path) and jf.endswith(".js"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "node", "--check", full_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if stderr:
                    static_issues.append(f"JS syntax error in {jf}: {stderr.decode()[:200]}")
            except Exception:
                pass

    reviews.append({
        "reviewer": "static_analysis",
        "model": "none",
        "cost_usd": 0.0,
        "response": json.dumps({
            "severity": "critical" if static_issues else "pass",
            "issues": [{"type": "syntax", "description": i} for i in static_issues],
            "summary": f"{len(static_issues)} syntax errors" if static_issues else "All files pass syntax check",
        }),
    })
    logger.info(f"Job {job_id}: code review #2 (static analysis) — {len(static_issues)} issues")

    # ---- REVIEW 3: Security Review (Kimi Reasoner — $0.27/M) ----
    # Only for changes touching auth, API, database, or secrets
    security_keywords = [
        "auth", "token", "password", "session", "rls", "policy", "api_key",
        "secret", "credential", "permission", "sql", "query", "inject",
        "cookie", "cors", "csrf", "xss", "sanitiz", "encrypt", "hash",
    ]
    security_relevant = any(kw in git_diff.lower() for kw in security_keywords)

    if security_relevant:
        security_prompt = (
            f"SECURITY CODE REVIEW — analyze these code changes for vulnerabilities.\n\n"
            f"PROJECT: {project}\n"
            f"TASK: {job['task']}\n\n"
            f"GIT DIFF:\n```\n{git_diff}\n```\n\n"
            f"Check for:\n"
            f"1. Injection attacks (SQL, command, XSS)\n"
            f"2. Authentication/authorization bypass\n"
            f"3. Data leaks (secrets in code, PII exposure)\n"
            f"4. Broken access control\n"
            f"5. Insecure cryptography or session handling\n\n"
            f"Respond with ONLY a JSON object (no markdown fences):\n"
            f'{{"severity": "pass|minor|major|critical", '
            f'"issues": [{{"type": "security", "description": "...", '
            f'"file": "filename", "suggestion": "..."}}], '
            f'"summary": "one-line security verdict"}}'
        )

        try:
            r3 = await _call_agent(
                "hacker_agent", security_prompt, tools=None,
                job_id=job_id, phase="code_review",
                guardrails=guardrails, priority=job.get("priority", "P2"),
            )
            total_cost += r3.get("cost_usd", 0)
            reviews.append({
                "reviewer": "pentest_ai",
                "model": "kimi-reasoner",
                "cost_usd": r3.get("cost_usd", 0),
                "response": r3.get("text", ""),
            })
            logger.info(f"Job {job_id}: code review #3 (Pentest AI) done — ${r3.get('cost_usd', 0):.4f}")
        except Exception as e:
            logger.warning(f"Job {job_id}: code review #3 (security) failed: {e}")
            reviews.append({"reviewer": "pentest_ai", "error": str(e)})
    else:
        logger.info(f"Job {job_id}: code review #3 skipped (no security-relevant changes)")

    # ---- Aggregate Results ----
    progress.cost_usd += total_cost
    has_critical = False
    has_major = False
    all_issues = []

    for review in reviews:
        text = review.get("response", "")
        parsed = None
        # Try to extract JSON even if agent appends signature text after it
        try:
            parsed = json.loads(text) if text else {}
        except (json.JSONDecodeError, TypeError):
            # Agent may append signature (e.g. "— Pentest AI") after JSON
            # Try extracting JSON substring between first { and last }
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                parsed = json.loads(text[start:end])
            except (ValueError, json.JSONDecodeError, TypeError):
                parsed = None

        if parsed and isinstance(parsed, dict):
            sev = parsed.get("severity", "").lower()
            if sev == "critical":
                has_critical = True
            elif sev == "major":
                has_major = True
            all_issues.extend(parsed.get("issues", []))
        elif text:
            # Truly free-text response — only flag if explicit "CRITICAL" (uppercase) appears
            if "CRITICAL" in text and "severity" not in text.lower():
                has_critical = True

    # Block on critical or major — both indicate real problems
    passed = not has_critical and not has_major
    if has_critical:
        verdict = "CRITICAL — BLOCKED"
    elif has_major:
        verdict = "MAJOR ISSUES — BLOCKED"
    else:
        verdict = "PASSED"

    summary = f"{len(reviews)} reviews, {len(all_issues)} issues, {verdict}"
    logger.info(f"Job {job_id}: code review complete — {summary}, cost ${total_cost:.4f}")

    return {
        "reviews": reviews,
        "review_count": len(reviews),
        "issues_found": len(all_issues),
        "has_critical": has_critical,
        "has_major": has_major,
        "passed": passed,
        "cost_usd": total_cost,
        "summary": summary,
        "changed_files": changed_files,
    }


async def _verify_phase(job: dict, agent_key: str, execution_results: list,
                        progress: JobProgress,
                        guardrails: "JobGuardrails | None" = None,
                        department: str = "") -> dict:
    """
    Phase 4: VERIFY
    Run tests, lint checks, and quality verification.
    Returns a verification result dict.
    """
    progress.phase = Phase.VERIFY
    progress.phase_status = "running"
    _save_progress(progress)
    if guardrails:
        guardrails.set_phase("verify")

    project = job.get("project", "unknown")
    workspace = progress.workspace

    # Map projects to repo paths (same as deliver phase)
    project_paths = {
        "barber-crm":    "/root/Barber-CRM",
        "delhi-palace":  "/root/Delhi-Palace",
        "openclaw":      "/root/openclaw",
        "prestress-calc":"/root/Mathcad-Scripts",
        "concrete-canoe":"/root/concrete-canoe-project2026",
    }
    repo_path = project_paths.get(project, f"/root/{project}")

    # Build summary of what was done
    steps_summary = "\n".join(
        f"- Step {r['step']+1}: {r.get('summary', r.get('status', '?'))}"
        for r in execution_results
    )

    # Department-specific verification instruction
    dept_verify = ""
    if department and department in DEPARTMENTS:
        dept_verify = f"\nDEPARTMENT-SPECIFIC CHECKS:\n{DEPARTMENTS[department].verify_instruction}\n"

    # Code review findings from Phase 3.5
    code_review_section = ""
    cr_issues = job.get("_code_review_issues", "")
    if cr_issues:
        code_review_section = (
            f"\nCODE REVIEW FINDINGS (from triple AI review):\n{cr_issues}\n"
            f"Pay special attention to these flagged issues during verification.\n"
        )

    prompt = (
        f"You just completed execution of a task. Now verify the results.\n\n"
        f"PROJECT: {project}\n"
        f"DEPARTMENT: {department or 'general'}\n"
        f"TASK: {job['task']}\n\n"
        f"WORKSPACE DIRECTORY: {workspace}\n"
        f"PROJECT PATH: {repo_path}\n"
        f"IMPORTANT: The actual project files are at {repo_path}, NOT in the workspace sandbox.\n"
        f"Use file_read and grep_search against {repo_path}/ paths to verify changes.\n\n"
        f"EXECUTION RESULTS:\n{steps_summary}\n\n"
        f"{code_review_section}"
        f"Verification checklist:\n"
        f"1. Use shell_execute to run any relevant tests (pytest, jest, vitest, etc.) from {repo_path}\n"
        f"2. If files were modified, lint ONLY the changed files — do NOT lint the entire project\n"
        f"3. Use file_read to spot-check created/modified files at {repo_path}/ for correctness\n"
        f"4. Use grep_search to check for common issues (TODO, FIXME, console.log, etc.) ONLY in changed files\n"
        f"5. If the task was read-only (no files modified), verify the output content is accurate\n"
        f"\nIMPORTANT: Only fail verification for issues in THIS task's changes. Pre-existing issues are NOT blockers.\n"
        f"{dept_verify}\n"
        f"STOP CONDITIONS: Run each check ONCE. Do NOT re-run tests or re-read files "
        f"you already checked. If a test fails, note it and move on — don't try to fix it here.\n"
        f"CRITICAL: Do NOT run full-project linting (eslint ., flake8 ., etc.) — only lint specific changed files.\n"
        f"Pre-existing warnings/errors unrelated to this task are NOT failures.\n"
        f"If the task was simple (add comment, read file, create small utility), a quick file_read check is sufficient.\n\n"
        f"Respond with a JSON object:\n"
        f'{{"passed": true/false, "summary": "...", "issues": ["issue1", "issue2"]}}\n'
        f"Do NOT include markdown fences or any text outside the JSON."
    )

    tools = _filter_tools_for_phase(Phase.VERIFY)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="verify",
                               guardrails=guardrails, department=department,
                               priority=job.get("priority", "P2"))

    progress.cost_usd += result["cost_usd"]

    # Parse verification result
    verify_text = result["text"].strip()
    verify_data = None
    for attempt_str in [verify_text, _extract_json_block(verify_text)]:
        try:
            verify_data = json.loads(attempt_str)
            break
        except (json.JSONDecodeError, TypeError):
            continue

    if not verify_data:
        # If we can't parse, assume passed (agent gave free-text summary)
        verify_data = {
            "passed": True,
            "summary": verify_text[:500],
            "issues": [],
        }

    # ------------------------------------------------------------------
    # Cross-check verify_data against actual tool results.
    # If shell_execute ran tests and returned a non-zero exit code, mark
    # verification as failed even if the LLM claimed it passed.
    # ------------------------------------------------------------------
    test_failures_detected = False
    shell_outputs = []

    for tc in result.get("tool_calls", []):
        if tc.get("tool") == "shell_execute":
            tool_result = tc.get("result", "")
            shell_outputs.append(tool_result)
            # Detect test runner failures from exit code or error patterns
            if "[EXIT CODE]: " in tool_result:
                exit_match = re.search(r'\[EXIT CODE\]: (\d+)', tool_result)
                if exit_match and exit_match.group(1) != "0":
                    test_failures_detected = True
            # Detect common test failure patterns (strict — avoid false positives)
            # Skip known false-positive outputs
            false_positive = any(fp in tool_result for fp in [
                "deprecated", "warning:", "Warning:", "is deprecated",
                "Compiled successfully", "Build complete",
                "problems", "warnings found", "linting",
                "no-unused-vars", "no-explicit-any", "@typescript-eslint",
            ])
            if not false_positive:
                if any(pat in tool_result for pat in [
                    "FAILED", "AssertionError", "AssertionError",
                    "Test Suites: ", "FAIL ", "npm ERR!", "ModuleNotFoundError",
                    "Failed to compile",
                ]):
                    # Check if it's actually a failure (not a pass with "failed" in test name)
                    if "failed" in tool_result.lower() and (
                        "passed" not in tool_result.lower() or
                        tool_result.lower().index("failed") < tool_result.lower().index("passed")
                    ):
                        test_failures_detected = True
                # Parse pytest/jest numeric failure output (e.g. "3 failed", "2 errors")
                if re.search(r'\d+\s+failed', tool_result, re.IGNORECASE):
                    test_failures_detected = True
                if re.search(r'FAILURES|ERRORS\s*$', tool_result, re.MULTILINE):
                    test_failures_detected = True

    if test_failures_detected and verify_data.get("passed", True):
        logger.warning(
            f"Verify phase: LLM claimed passed=True but shell tool outputs indicate failures. "
            f"Overriding to passed=False."
        )
        verify_data["passed"] = False
        verify_data["issues"] = verify_data.get("issues", []) + [
            "Test runner exit code was non-zero (actual failure detected from shell output)"
        ]

    # Record that actual tool calls were made (not just LLM narration)
    verify_data["tool_calls_made"] = len(result.get("tool_calls", []))

    progress.phase_status = "done"
    _save_progress(progress)

    _log_phase(job["id"], "verify", {
        "event": "phase_complete",
        "passed": verify_data.get("passed", True),
        "issues_count": len(verify_data.get("issues", [])),
        "tool_calls_made": verify_data["tool_calls_made"],
        "cost_usd": result["cost_usd"],
    })

    return verify_data


async def _deliver_phase(job: dict, agent_key: str, verify_result: dict,
                         progress: JobProgress,
                         guardrails: "JobGuardrails | None" = None) -> dict:
    """
    Phase 5: DELIVER
    Git commit, push, deploy if needed, send notifications.
    Returns a delivery result dict.
    """
    progress.phase = Phase.DELIVER
    progress.phase_status = "running"
    _save_progress(progress)
    if guardrails:
        guardrails.set_phase("deliver")

    project = job.get("project", "unknown")
    workspace = progress.workspace

    # Map projects to repo paths
    project_paths = {
        "barber-crm":    "/root/Barber-CRM",
        "delhi-palace":  "/root/Delhi-Palace",
        "openclaw":      "/root/openclaw",
        "prestress-calc":"/root/Mathcad-Scripts",
        "concrete-canoe":"/root/concrete-canoe-project2026",
    }

    repo_path = project_paths.get(project, f"/root/{project}")
    passed = verify_result.get("passed", True)

    if not passed:
        # Verification failed — do not deliver
        delivery = {
            "delivered": False,
            "reason": "Verification failed",
            "issues": verify_result.get("issues", []),
        }
        progress.phase_status = "done"
        _save_progress(progress)
        return delivery

    # Pre-deploy Slack notification
    try:
        from gateway import send_slack_message
        staging_projects = {"barber-crm", "delhi-palace"}
        deploy_mode = "preview" if project in staging_projects else "production"
        await send_slack_message("", (
            f"🚀 *Deploying {project}* ({deploy_mode})\n"
            f"*Task:* {job['task'][:100]}\n"
            f"*Cost so far:* ${progress.cost_usd:.4f}"
        ))
    except Exception:
        pass

    # Staging-first: client projects deploy to preview first
    staging_projects = {"barber-crm", "delhi-palace"}
    deploy_instruction = (
        f"5. Deploy to Vercel PREVIEW (not production) using vercel_deploy with production=false\n"
        if project in staging_projects else
        f"5. If the project uses Vercel, use vercel_deploy to trigger a deployment\n"
    )

    prompt = (
        f"The task is complete and verified. Now deliver the results.\n\n"
        f"PROJECT: {project}\n"
        f"TASK: {job['task']}\n"
        f"REPO PATH: {repo_path}\n"
        f"WORKSPACE DIRECTORY: {workspace}\n"
        f"All output files from execution are located inside {workspace}/\n"
        f"Copy or move files from {workspace}/ to {repo_path}/ as needed before committing.\n\n"
        f"Delivery steps:\n"
        f"1. Use git_operations with action='status' to see what changed (repo_path='{repo_path}')\n"
        f"2. Use git_operations with action='add' to stage the changes (repo_path='{repo_path}')\n"
        f"3. Use git_operations with action='commit' with a clear commit message (repo_path='{repo_path}')\n"
        f"4. Use git_operations with action='push' to push to remote (repo_path='{repo_path}')\n"
        f"{deploy_instruction}"
        f"6. Send a slack message summarizing what was done\n\n"
        f"Respond with a JSON object when done:\n"
        f'{{"delivered": true, "commit_hash": "...", "pushed": true, "deployed": true/false, "summary": "..."}}\n'
        f"Do NOT include markdown fences or any text outside the JSON.\n\n"
        f"STOP CONDITIONS: Run each delivery step ONCE. If git push fails, note it and stop — "
        f"don't retry endlessly. If there are no changes to commit, skip to sending the Slack message."
    )

    tools = _filter_tools_for_phase(Phase.DELIVER)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="deliver",
                               guardrails=guardrails,
                               priority=job.get("priority", "P2"))

    progress.cost_usd += result["cost_usd"]

    # Parse delivery result from LLM text (used as fallback/summary only)
    deliver_text = result["text"].strip()
    delivery = None
    for attempt_str in [deliver_text, _extract_json_block(deliver_text)]:
        try:
            delivery = json.loads(attempt_str)
            break
        except (json.JSONDecodeError, TypeError):
            continue

    if not delivery:
        delivery = {
            "delivered": True,
            "summary": deliver_text[:500],
        }

    # ------------------------------------------------------------------
    # Override delivery data with ground truth from actual tool results.
    # The LLM text response may contain fabricated commit hashes or false
    # status claims. We parse real tool outputs to get authoritative values.
    # ------------------------------------------------------------------
    real_commit_hash = ""
    git_pushed = False
    git_status_output = ""

    for tc in result.get("tool_calls", []):
        tool_name = tc.get("tool", "")
        tool_result = tc.get("result", "")
        tool_input = tc.get("input", {})

        if tool_name == "git_operations":
            action = tool_input.get("action", "")

            if action == "commit":
                # Real commit output looks like: "[main abc1234] message"
                # Extract the short hash from the commit output
                commit_match = re.search(r'\[[\w/\-]+ ([0-9a-f]{5,40})\]', tool_result)
                if commit_match:
                    real_commit_hash = commit_match.group(1)
                    logger.info(f"Deliver phase: real commit hash extracted: {real_commit_hash}")

            elif action == "push":
                # Push succeeded if exit code line is 0 or output contains success indicators
                if "[EXIT CODE]: 0" in tool_result or "master" in tool_result or "main" in tool_result:
                    if "error" not in tool_result.lower() and "fatal" not in tool_result.lower():
                        git_pushed = True

            elif action == "status":
                git_status_output = tool_result[:500]

    # Apply real values to delivery dict, overriding LLM fabrications
    if real_commit_hash:
        delivery["commit_hash"] = real_commit_hash
        delivery["delivered"] = True
    if git_pushed:
        delivery["pushed"] = True
    if git_status_output:
        delivery["git_status"] = git_status_output

    # If any tool calls were made, mark as actually delivered (not just narrated)
    delivery["tool_calls_made"] = len(result.get("tool_calls", []))
    delivery["actual_execution"] = delivery["tool_calls_made"] > 0

    # ------------------------------------------------------------------
    # Auto-delivery: GitHub PR creation
    # After the agent has done its git work (commit/push via tools),
    # we also imperatively call deliver_job_to_github() if the job has
    # a delivery_config.repo set so a PR is always created.
    # ------------------------------------------------------------------
    pr_url = ""
    deploy_url = ""

    job_data = get_job(progress.job_id) or job
    delivery_config = job_data.get("delivery_config", {}) if isinstance(job_data, dict) else {}
    repo = delivery_config.get("repo", "")

    if repo:
        try:
            from github_integration import deliver_job_to_github as _deliver_to_github

            # Collect workspace files so the PR body lists what changed.
            ws_path = JOB_RUNS_DIR / progress.job_id / "workspace"
            files_changed: dict = {}
            if ws_path.exists():
                for f in ws_path.rglob("*"):
                    if f.is_file() and not f.name.startswith("."):
                        rel = str(f.relative_to(ws_path))
                        files_changed[rel] = "Modified by OpenClaw autonomous job"

            if files_changed:
                logger.info(
                    f"Auto-delivering job {progress.job_id} to GitHub repo={repo} "
                    f"({len(files_changed)} files)"
                )
                pr_result = await _deliver_to_github(
                    job_id=progress.job_id,
                    repo=repo,
                    files_changed=files_changed,
                    auto_merge=delivery_config.get("auto_merge", False),
                )
                pr_url = pr_result.get("pr_url", "")
                delivery["pr_url"] = pr_url
                delivery["pr_number"] = pr_result.get("pr_number", 0)
                delivery["branch"] = pr_result.get("branch", "")
                _log_phase(progress.job_id, "deliver", {
                    "event": "github_pr_created",
                    "pr_url": pr_url,
                    "branch": pr_result.get("branch", ""),
                    "files_count": len(files_changed),
                })
                logger.info(f"GitHub PR created for job {progress.job_id}: {pr_url}")
            else:
                logger.info(
                    f"Job {progress.job_id}: delivery_config.repo set but no workspace "
                    f"files found — skipping GitHub PR creation"
                )
        except Exception as e:
            logger.warning(f"Auto-delivery to GitHub failed for {progress.job_id}: {e}")
            _log_phase(progress.job_id, "deliver", {
                "event": "github_pr_failed",
                "error": str(e),
            })

    # ------------------------------------------------------------------
    # Auto-deploy: Vercel deployment
    # Triggered when workspace contains vercel.json, or package.json AND
    # delivery_config has deploy_vercel=True.
    # ------------------------------------------------------------------
    ws_path = JOB_RUNS_DIR / progress.job_id / "workspace"
    vercel_json = ws_path / "vercel.json"
    package_json = ws_path / "package.json"

    if vercel_json.exists() or (
        package_json.exists() and delivery_config.get("deploy_vercel", False)
    ):
        try:
            logger.info(
                f"Auto-deploying job {progress.job_id} to Vercel from {ws_path}"
            )
            raw_deploy = await asyncio.get_running_loop().run_in_executor(
                None, _execute_tool_routed, "vercel_deploy", {
                    "action": "deploy",
                    "project_path": str(ws_path),
                }, "deliver", progress.job_id, agent_key
            )
            deploy_url = str(raw_deploy)[:500]
            delivery["vercel_deploy"] = deploy_url
            _log_phase(progress.job_id, "deliver", {
                "event": "vercel_deployed",
                "result": deploy_url,
            })
            logger.info(
                f"Vercel deploy complete for job {progress.job_id}: {deploy_url}"
            )
        except Exception as e:
            logger.warning(f"Vercel auto-deploy failed for {progress.job_id}: {e}")
            _log_phase(progress.job_id, "deliver", {
                "event": "vercel_deploy_failed",
                "error": str(e),
            })

    # ------------------------------------------------------------------
    # Update intake job record with final delivery URLs
    # ------------------------------------------------------------------
    try:
        from intake_routes import update_job_status as intake_update_status
        parts = []
        if pr_url:
            parts.append(f"PR={pr_url}")
        if deploy_url:
            parts.append(f"Deploy={deploy_url[:120]}")
        log_msg = f"Delivered: {', '.join(parts)}" if parts else "Delivered (no URLs)"
        intake_update_status(
            progress.job_id,
            "done",
            log_message=log_msg,
        )
    except Exception as e:
        logger.warning(f"Failed to update intake status for {progress.job_id}: {e}")

    # Persist delivery URLs into the delivery dict so result.json is complete
    delivery["delivery_urls"] = {
        "pr_url": pr_url,
        "deploy_url": deploy_url,
    }

    progress.phase_status = "done"
    _save_progress(progress)

    _log_phase(job["id"], "deliver", {
        "event": "phase_complete",
        "delivered": delivery.get("delivered", True),
        "pr_url": pr_url,
        "deploy_url": deploy_url,
        "cost_usd": result["cost_usd"],
    })

    return delivery


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _extract_json_block(text: str) -> Optional[str]:
    """Extract JSON from a response that may contain markdown fences."""
    # Try ```json ... ```
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Try finding first { ... } block
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        return text[brace_start:brace_end + 1]
    return None


class BudgetExceededError(Exception):
    """Raised when a job exceeds its cost budget."""
    pass


class CreditExhaustedError(Exception):
    """Raised when the API provider reports insufficient credits or billing issues.
    This is a non-retryable, queue-stopping error — no point retrying if the
    account has no funds."""
    pass


class GuardrailViolation(Exception):
    """Raised when any guardrail limit is breached."""
    def __init__(self, job_id: str, reason: str, kill_status: str):
        self.job_id = job_id
        self.reason = reason
        self.kill_status = kill_status
        super().__init__(f"Job {job_id} killed ({kill_status}): {reason}")


# ---------------------------------------------------------------------------
# Kill Flags — file-based kill switch
# ---------------------------------------------------------------------------

KILL_FLAGS_PATH = Path(os.path.join(DATA_DIR, "jobs", "kill_flags.json"))


def _load_kill_flags() -> dict:
    """Load kill flags from disk. Returns {job_id: {"reason": ..., "timestamp": ...}}."""
    try:
        if KILL_FLAGS_PATH.exists():
            with open(KILL_FLAGS_PATH) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _set_kill_flag(job_id: str, reason: str = "manual"):
    """Set a kill flag for a job (called from the API)."""
    flags = _load_kill_flags()
    flags[job_id] = {"reason": reason, "timestamp": _now_iso()}
    KILL_FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(KILL_FLAGS_PATH, "w") as f:
        json.dump(flags, f, indent=2)


def _clear_kill_flag(job_id: str):
    """Remove a kill flag after a job finishes."""
    flags = _load_kill_flags()
    if job_id in flags:
        del flags[job_id]
        with open(KILL_FLAGS_PATH, "w") as f:
            json.dump(flags, f, indent=2)


# ---------------------------------------------------------------------------
# JobGuardrails — per-job safety limits
# ---------------------------------------------------------------------------

class JobGuardrails:
    """
    Tracks cost, iterations, wall-clock time, error patterns, and kill flags
    for a single job. Call check() at every iteration boundary — it raises
    GuardrailViolation if any limit is breached.

    Defaults:
        max_cost_usd      = priority-based (P0=$5, P1=$3, P2=$3, P3=$1) + 10% grace
        max_iterations     = 350     (total agent calls across all phases)
        max_duration_secs  = 3600    (60 minutes wall-clock)
        circuit_breaker_n  = 3       (same error 3x in a row → kill)

    Phase iteration limits (prevents any single phase from hogging all iterations):
        research=15, plan=10, execute=40, verify=10, deliver=5

    Progressive warnings are logged at 50%, 75%, 90% of cost and iteration
    limits so operators see problems before the hard kill fires.
    """

    WARNING_THRESHOLDS = (0.50, 0.75, 0.90)

    # Phase-specific iteration budgets — prevents any single phase from
    # eating the entire iteration allowance (e.g. execute hogging 48/50).
    PHASE_ITERATION_LIMITS = {
        "research": 60,
        "plan":     30,
        "execute":  250,
        "verify":   30,
        "deliver":  30,
    }

    def __init__(
        self,
        job_id: str,
        max_cost_usd: float = 2.0,
        max_iterations: int = 400,
        max_duration_secs: int = 3600,
        circuit_breaker_n: int = 3,
    ):
        self.job_id = job_id
        self.max_cost_usd = max_cost_usd
        self.max_iterations = max_iterations
        self.max_duration_secs = max_duration_secs
        self.circuit_breaker_n = circuit_breaker_n

        self.iterations = 0
        self.cost_usd = 0.0
        self.start_time = time.monotonic()

        # Phase-level iteration tracking
        self.current_phase: str = "research"
        self.phase_iterations: dict[str, int] = {
            "research": 0, "plan": 0, "execute": 0, "verify": 0, "deliver": 0,
        }

        # Circuit breaker state
        self._recent_errors: list[str] = []

        # Track which warning thresholds have already fired (to avoid spam)
        self._cost_warnings_fired: set[float] = set()
        self._iter_warnings_fired: set[float] = set()

        logger.info(
            f"[Guardrails] Job {job_id}: max_cost=${max_cost_usd}, "
            f"max_iter={max_iterations}, max_duration={max_duration_secs}s, "
            f"circuit_breaker={circuit_breaker_n}"
        )

    # ------------------------------------------------------------------
    # Public: call after every agent iteration / tool loop turn
    # ------------------------------------------------------------------

    def set_phase(self, phase: str):
        """Set the current phase for per-phase iteration tracking."""
        self.current_phase = phase

    def record_iteration(self, cost_increment: float = 0.0):
        """Record one agent iteration and its cost. Call this BEFORE check()."""
        self.iterations += 1
        self.cost_usd += cost_increment
        # Track per-phase iterations
        if self.current_phase in self.phase_iterations:
            self.phase_iterations[self.current_phase] += 1

    def record_error(self, error_msg: str):
        """Record an error message for circuit breaker detection."""
        # Normalize: strip whitespace and truncate
        normalized = error_msg.strip()[:200]
        self._recent_errors.append(normalized)
        # Only keep last N errors for comparison
        if len(self._recent_errors) > self.circuit_breaker_n + 2:
            self._recent_errors = self._recent_errors[-(self.circuit_breaker_n + 2):]

    def clear_errors(self):
        """Reset the error streak (call after a successful iteration)."""
        self._recent_errors.clear()

    def check(self):
        """
        Check all guardrails. Raises GuardrailViolation if any limit breached.
        Also logs progressive warnings. Call this at every iteration boundary.
        """
        # 1. Kill switch (file-based, checked from disk)
        flags = _load_kill_flags()
        if self.job_id in flags:
            reason = flags[self.job_id].get("reason", "manual kill")
            raise GuardrailViolation(
                self.job_id, f"Kill switch activated: {reason}", "killed_manual"
            )

        # 2. Cost cap (with 10% grace period to avoid killing jobs that are
        #    about to finish — the last API call often pushes just over the limit)
        self._check_progressive_warnings(
            "cost", self.cost_usd, self.max_cost_usd, self._cost_warnings_fired
        )
        hard_limit = self.max_cost_usd * 1.10  # 10% grace
        if self.cost_usd > hard_limit:
            raise GuardrailViolation(
                self.job_id,
                f"Cost ${self.cost_usd:.4f} exceeds cap ${self.max_cost_usd:.2f} "
                f"(+10% grace = ${hard_limit:.2f})",
                "killed_cost_limit",
            )

        # 3. Iteration cap (global)
        self._check_progressive_warnings(
            "iterations", self.iterations, self.max_iterations, self._iter_warnings_fired
        )
        if self.iterations > self.max_iterations:
            raise GuardrailViolation(
                self.job_id,
                f"Iterations {self.iterations} exceeds cap {self.max_iterations}",
                "killed_iteration_limit",
            )

        # 3b. Per-phase iteration cap
        if self.current_phase in self.PHASE_ITERATION_LIMITS:
            phase_count = self.phase_iterations.get(self.current_phase, 0)
            phase_limit = self.PHASE_ITERATION_LIMITS[self.current_phase]
            if phase_count > phase_limit:
                raise GuardrailViolation(
                    self.job_id,
                    f"Phase '{self.current_phase}' iterations {phase_count} exceeds "
                    f"phase cap {phase_limit} (global: {self.iterations}/{self.max_iterations})",
                    "killed_phase_iteration_limit",
                )

        # 4. Wall-clock timeout
        elapsed = time.monotonic() - self.start_time
        if elapsed > self.max_duration_secs:
            raise GuardrailViolation(
                self.job_id,
                f"Wall-clock {elapsed:.0f}s exceeds cap {self.max_duration_secs}s",
                "killed_timeout",
            )

        # 5. Circuit breaker — same error N times in a row
        if len(self._recent_errors) >= self.circuit_breaker_n:
            tail = self._recent_errors[-self.circuit_breaker_n:]
            if len(set(tail)) == 1:
                raise GuardrailViolation(
                    self.job_id,
                    f"Same error repeated {self.circuit_breaker_n}x: {tail[0][:100]}",
                    "killed_circuit_breaker",
                )

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    def summary(self) -> dict:
        """Return current guardrail metrics for logging/progress."""
        return {
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "cost_usd": round(self.cost_usd, 6),
            "max_cost_usd": self.max_cost_usd,
            "elapsed_seconds": round(self.elapsed_seconds(), 1),
            "max_duration_seconds": self.max_duration_secs,
            "recent_errors": len(self._recent_errors),
            "current_phase": self.current_phase,
            "phase_iterations": dict(self.phase_iterations),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_progressive_warnings(
        self, metric_name: str, current: float, limit: float, fired: set
    ):
        """Log warnings at 50%, 75%, 90% of a limit."""
        if limit <= 0:
            return
        ratio = current / limit
        for threshold in self.WARNING_THRESHOLDS:
            if ratio >= threshold and threshold not in fired:
                fired.add(threshold)
                pct = int(threshold * 100)
                logger.warning(
                    f"[Guardrails] Job {self.job_id}: {metric_name} at {pct}% "
                    f"({current:.4f} / {limit:.4f})"
                )
                _log_phase(self.job_id, "guardrails", {
                    "event": "warning",
                    "metric": metric_name,
                    "threshold_pct": pct,
                    "current": current,
                    "limit": limit,
                })


# ---------------------------------------------------------------------------
# AutonomousRunner
# ---------------------------------------------------------------------------

class AutonomousRunner:
    """
    Background job runner that polls for pending jobs and executes them
    through the 5-phase pipeline.
    """

    def __init__(
        self,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        budget_limit_usd: float = DEFAULT_BUDGET_LIMIT_USD,
    ):
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self.budget_limit_usd = budget_limit_usd

        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._active_jobs: dict[str, asyncio.Task] = {}     # job_id -> Task
        self._active_jobs_meta: dict[str, dict] = {}         # job_id -> {project, department, ...}
        self._progress: dict[str, JobProgress] = {}          # job_id -> JobProgress
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._cancelled_jobs: set = set()
        self._job_available: asyncio.Event = asyncio.Event()

        # Ensure directories exist
        JOB_RUNS_DIR.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"AutonomousRunner initialized: poll={poll_interval}s, "
            f"concurrency={max_concurrent}, budget=${budget_limit_usd}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self):
        """Start the background job polling loop."""
        if self._running:
            logger.warning("AutonomousRunner is already running")
            return

        # Recover orphaned jobs from previous gateway process
        await self._recover_orphaned_jobs()

        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("AutonomousRunner STARTED — polling for jobs")

    async def _recover_orphaned_jobs(self):
        """Reset jobs stuck in intermediate statuses back to pending.

        When the gateway restarts, in-flight jobs are orphaned in statuses
        like 'analyzing', 'code_generated', or 'running'. Reset them so
        the poll loop can pick them up again.

        IMPORTANT: Skip jobs whose progress.json shows they already completed
        their pipeline (phase=deliver, phase_status=done) — re-running these
        wastes money and can create duplicate commits.
        """
        orphan_statuses = ["running", "analyzing", "code_generated"]
        try:
            from supabase_client import table_select, table_update
            recovered = 0
            skipped = 0
            for status in orphan_statuses:
                rows = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda s=status: table_select("jobs", f"status=eq.{s}", limit=50),
                )
                for row in rows:
                    job_id = row["id"]

                    # Check progress.json — if the job already completed the
                    # deliver phase, mark it done instead of resetting to pending
                    progress_file = JOB_RUNS_DIR / job_id / "progress.json"
                    already_done = False
                    if progress_file.exists():
                        try:
                            import json as _json
                            pdata = _json.loads(progress_file.read_text())
                            if (pdata.get("phase") == "deliver"
                                    and pdata.get("phase_status") == "done"):
                                already_done = True
                        except Exception:
                            pass

                    if already_done:
                        logger.info(
                            f"Orphan job {job_id} already completed pipeline "
                            f"(was '{status}') — marking done, not re-queuing"
                        )
                        await asyncio.get_running_loop().run_in_executor(
                            None,
                            lambda jid=job_id: table_update(
                                "jobs", f"id=eq.{jid}",
                                {"status": "done"},
                            ),
                        )
                        skipped += 1
                        continue

                    logger.warning(
                        f"Recovering orphaned job {job_id} "
                        f"(was '{status}' → resetting to 'pending')"
                    )
                    await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda jid=job_id: table_update(
                            "jobs", f"id=eq.{jid}",
                            {"status": "pending", "started_at": None, "error": None},
                        ),
                    )
                    recovered += 1
            logger.info(f"Orphan recovery complete: {recovered} recovered, {skipped} already-done skipped")
        except Exception as e:
            logger.error(f"Orphan recovery failed (non-fatal): {e}")

    def notify_new_job(self):
        """Signal the poll loop that a new job is available, waking it immediately."""
        self._job_available.set()

    async def stop(self):
        """Gracefully stop the runner. Waits for active jobs to finish."""
        if not self._running:
            return

        logger.info("AutonomousRunner shutting down...")
        self._running = False

        # Cancel the polling loop
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        # Wait for active jobs to complete (with timeout)
        if self._active_jobs:
            logger.info(f"Waiting for {len(self._active_jobs)} active jobs to complete...")
            tasks = list(self._active_jobs.values())
            done, pending = await asyncio.wait(tasks, timeout=120)
            for t in pending:
                t.cancel()

        logger.info("AutonomousRunner STOPPED")

    async def execute_job(self, job_id: str) -> dict:
        """
        Execute a single job through the full pipeline (on-demand).
        Returns the final result dict.
        """
        job = get_job(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        return await self._run_job_pipeline(job)

    def get_job_progress(self, job_id: str) -> Optional[dict]:
        """Get current progress for a running or completed job."""
        if job_id in self._progress:
            return self._progress[job_id].to_dict()

        # Try loading from disk
        progress_file = JOB_RUNS_DIR / job_id / "progress.json"
        if progress_file.exists():
            with open(progress_file) as f:
                return json.load(f)

        return None

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job. It will stop after the current step."""
        if job_id in self._progress:
            self._progress[job_id].cancelled = True
            self._cancelled_jobs.add(job_id)
            logger.info(f"Job {job_id} marked for cancellation")

            # Cancel the asyncio task if it exists
            if job_id in self._active_jobs:
                self._active_jobs[job_id].cancel()

            update_job_status(job_id, "cancelled")
            return True

        return False

    def get_active_jobs(self) -> list:
        """Return list of currently running job IDs."""
        return list(self._active_jobs.keys())

    def get_stats(self) -> dict:
        """Return runner statistics."""
        return {
            "running": self._running,
            "active_jobs": len(self._active_jobs),
            "max_concurrent": self.max_concurrent,
            "poll_interval": self.poll_interval,
            "budget_limit_usd": self.budget_limit_usd,
            "active_job_ids": list(self._active_jobs.keys()),
            "total_cost_usd": sum(
                p.cost_usd for p in self._progress.values()
            ),
        }

    # ------------------------------------------------------------------
    # Internal — Polling Loop
    # ------------------------------------------------------------------

    async def _poll_loop(self):
        """Background loop that checks for pending jobs."""
        logger.info("Poll loop started")
        while self._running:
            try:
                pending = await asyncio.get_running_loop().run_in_executor(
                    None, get_pending_jobs
                )

                for job in pending:
                    job_id = job["id"]

                    # Skip if already running or cancelled
                    if job_id in self._active_jobs or job_id in self._cancelled_jobs:
                        continue

                    # Acquire semaphore slot (limits concurrency)
                    if self._semaphore.locked():
                        logger.debug(
                            f"Concurrency limit reached ({self.max_concurrent}), "
                            f"deferring job {job_id}"
                        )
                        break

                    # Launch job execution as a background task
                    logger.info(f"Picking up job: {job_id} — {job['task'][:80]}")
                    task = asyncio.create_task(self._execute_with_semaphore(job))
                    self._active_jobs[job_id] = task

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poll loop error: {e}")

            self._job_available.clear()
            try:
                await asyncio.wait_for(self._job_available.wait(), timeout=self.poll_interval)
                logger.debug("Job queue signaled — checking for new jobs")
            except asyncio.TimeoutError:
                pass  # Normal periodic poll

    async def _execute_with_semaphore(self, job: dict):
        """Wraps job execution with the concurrency semaphore."""
        job_id = job["id"]
        async with self._semaphore:
            try:
                await self._run_job_pipeline(job)
            except Exception as e:
                logger.error(f"Job {job_id} failed (uncaught): {e}\n{traceback.format_exc()}")
                # Ensure the job is marked as failed with an error message
                try:
                    update_job_status(job_id, "failed", error=f"Uncaught error: {str(e)[:500]}")
                except Exception:
                    pass
            finally:
                self._active_jobs.pop(job_id, None)
                self._active_jobs_meta.pop(job_id, None)

    # ------------------------------------------------------------------
    # Internal — Pipeline Execution
    # ------------------------------------------------------------------

    async def _run_job_pipeline(self, job: dict) -> dict:
        """
        Run a job through the full 5-phase pipeline:
        RESEARCH -> PLAN -> EXECUTE -> VERIFY -> DELIVER
        """
        job_id = job["id"]
        started_at = _now_iso()

        # Input validation at system boundary: ensure job is well-formed before execution
        try:
            validate_job(job["project"], job["task"], job.get("priority", "P1"))
        except JobValidationError as e:
            logger.error(f"Job {job_id} failed validation: {e}")
            update_job_status(job_id, "failed", error=f"Validation failed: {str(e)[:500]}")
            return {"error": f"Validation failed: {str(e)}"}

        # Validate job before any phase runs
        try:
            validate_job(job.get("project", ""), job.get("task", ""), job.get("priority", "P1"))
        except JobValidationError as ve:
            logger.error(f"Job {job_id} failed validation: {ve}")
            update_job_status(job_id, "failed", error=str(ve))
            return {"job_id": job_id, "success": False, "error": str(ve)}

        # Select agent via department routing
        agent_key, department = _select_agent_for_job(job)
        logger.info(f"Job {job_id}: dept={department}, agent={agent_key}, project={job.get('project','?')}")

        # Track active job metadata for worktree conflict detection
        project = job.get("project", "")
        project_root = PROJECT_ROOTS.get(project)
        self._active_jobs_meta[job_id] = {
            "project": project,
            "department": department,
            "agent": agent_key,
        }

        # Create an isolated workspace directory for this job so concurrent jobs
        # cannot interfere with each other's files on the shared VPS filesystem.
        workspace = JOB_RUNS_DIR / job_id / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)

        # Git worktree isolation: if another active job targets the same project,
        # create a worktree so agents don't step on each other's files.
        use_worktree = False
        if project_root:
            same_project_active = any(
                self._active_jobs_meta.get(jid, {}).get("project") == project
                for jid in self._active_jobs if jid != job_id
            )
            if same_project_active:
                try:
                    wt_path = _create_job_worktree(job_id, project_root)
                    workspace = Path(wt_path)
                    use_worktree = True
                    logger.info(f"Job {job_id}: worktree at {workspace} (concurrent {project} job)")
                except Exception as wt_err:
                    logger.warning(f"Job {job_id}: worktree creation failed ({wt_err}), using project root")
                    workspace = Path(project_root)
            else:
                workspace = Path(project_root)
        logger.info(f"Job {job_id}: workspace={workspace}, worktree={use_worktree}")

        # Initialize progress tracking
        progress = JobProgress(
            job_id=job_id,
            started_at=started_at,
            workspace=str(workspace),
        )
        self._progress[job_id] = progress
        _save_progress(progress)

        # Update job status to running
        update_job_status(job_id, "running")

        # Initialize IDE session for context tracking across phases
        ide_session = None
        try:
            ide_session = load_session(job_id) or create_session(job_id, project, str(workspace))
            logger.info(f"Job {job_id}: IDE session {'resumed' if ide_session.updated_at != ide_session.created_at else 'created'}")
        except Exception as sess_err:
            logger.warning(f"Job {job_id}: IDE session init failed: {sess_err}")

        # Generate repo-map for project context (saves agents 10-15 min exploration)
        if HAS_REPO_MAP:
            try:
                repo_map_text = generate_compact_map(str(workspace))
                if repo_map_text:
                    job["_repo_map"] = repo_map_text[:2000]
                    if ide_session:
                        ide_session.add_context("repo_map", repo_map_text[:2000], source="repo_map", relevance=0.7, phase="research")
                    logger.info(f"Job {job_id}: repo-map generated ({len(repo_map_text)} chars)")
            except Exception as rm_err:
                logger.warning(f"Job {job_id}: repo-map failed: {rm_err}")

        # --- Initialize guardrails for this job ---
        # Priority-based cost caps: P0 gets most headroom, P3 is cheapest
        job_priority = job.get("priority", "P2")
        budget_map = {"P0": 5.0, "P1": 3.0, "P2": 3.0, "P3": 2.0}
        job_max_cost = float(job.get("max_cost_usd", budget_map.get(job_priority, 2.0)))
        job_max_iter = job.get("max_iterations", 400)
        job_max_dur  = job.get("max_duration_seconds", 3600)
        guardrails = JobGuardrails(
            job_id=job_id,
            max_cost_usd=float(job_max_cost),
            max_iterations=int(job_max_iter),
            max_duration_secs=int(job_max_dur),
        )

        result = {
            "job_id": job_id,
            "agent": agent_key,
            "department": department,
            "started_at": started_at,
            "phases": {},
            "success": False,
            "error": None,
            "cost_usd": 0.0,
        }

        # Check for existing checkpoint to resume from
        existing_checkpoint = get_latest_checkpoint(job_id)
        resume_from_phase = None
        phase_order = ["research", "plan", "execute", "verify", "deliver"]
        if existing_checkpoint:
            resume_from_phase = existing_checkpoint["phase"]
            logger.info(
                f"Job {job_id}: Found checkpoint at phase={resume_from_phase}, "
                f"step={existing_checkpoint['step_index']} — will resume"
            )

        def _should_skip(phase_name: str) -> bool:
            """Skip phases that completed before the checkpoint phase."""
            if not resume_from_phase:
                return False
            try:
                resume_idx = phase_order.index(resume_from_phase)
                current_idx = phase_order.index(phase_name)
                return current_idx < resume_idx
            except ValueError:
                return False

        try:
            # ---- Supervisor: check if task should be decomposed ----
            if not existing_checkpoint:  # don't decompose resumed jobs
                try:
                    supervisor_result = await maybe_decompose_and_execute(
                        job, project_root=project_root or "/root/openclaw"
                    )
                    if supervisor_result:
                        logger.info(
                            f"Job {job_id}: Supervisor handled — "
                            f"{supervisor_result.get('sub_tasks_completed', 0)}/"
                            f"{supervisor_result.get('sub_tasks_total', 0)} sub-tasks done"
                        )
                        result["success"] = supervisor_result.get("success", False)
                        result["supervisor"] = supervisor_result
                        result["phases"]["supervisor"] = {
                            "status": "completed",
                            "decomposition": supervisor_result.get("decomposition", {}),
                            "sub_tasks": supervisor_result.get("sub_tasks", []),
                            "summary": supervisor_result.get("summary", ""),
                        }
                        result["cost_usd"] = progress.cost_usd
                        return result
                except Exception as sup_err:
                    logger.warning(f"Job {job_id}: Supervisor check failed (falling through): {sup_err}")

            # ---- Phase 1: RESEARCH ----
            if _should_skip("research"):
                logger.info(f"Job {job_id}: Skipping research (resuming from {resume_from_phase})")
                research = "(resumed — research phase skipped)"
                result["phases"]["research"] = {"status": "skipped"}
            else:
                research = await self._run_phase_with_retry(
                    "research",
                    lambda: _research_phase(job, agent_key, progress, guardrails=guardrails, department=department),
                    progress,
                )
                result["phases"]["research"] = {"status": "done", "length": len(research)}
                # Schema validation
                _rv = validate_phase_output("research", research)
                if _rv["errors"]:
                    logger.warning(f"Job {job_id}: Research schema errors: {_rv['errors']}")
                if isinstance(result["phases"].get("research"), dict):
                    result["phases"]["research"]["validation"] = _rv
                if ide_session:
                    ide_session.set_phase("research")
                    ide_session.add_context("research", research[:3000], source="research_phase", relevance=0.8, phase="research")
                    save_session(ide_session)

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 2: PLAN ----
            if ide_session:
                ide_session.compact(target_tokens=6000)

            if _should_skip("plan"):
                logger.info(f"Job {job_id}: Skipping plan (resuming from {resume_from_phase})")
                # Create a minimal plan so execute phase has something to work with
                plan = ExecutionPlan(
                    job_id=job_id,
                    agent=agent_key,
                    steps=[
                        PlanStep(index=0, description=job["task"], tool_hints=["file_read", "file_edit", "shell_execute"])
                    ],
                    created_at=_now_iso(),
                )
                result["phases"]["plan"] = {"status": "skipped"}
            else:
                research_for_plan = _trim_context(research, max_tokens=3000)
                plan = await self._run_phase_with_retry(
                    "plan",
                    lambda: _plan_phase(job, agent_key, research_for_plan, progress, guardrails=guardrails),
                    progress,
                )
                result["phases"]["plan"] = {
                    "status": "done",
                    "steps": len(plan.steps),
                }
                # Schema validation
                _pv = validate_phase_output("plan", plan)
                if _pv["errors"]:
                    logger.warning(f"Job {job_id}: Plan schema errors: {_pv['errors']}")
                if isinstance(result["phases"].get("plan"), dict):
                    result["phases"]["plan"]["validation"] = _pv
                if ide_session:
                    ide_session.set_phase("plan")
                    plan_text = "\n".join(f"Step {s.index}: {s.description}" for s in plan.steps)
                    ide_session.add_context("plan", plan_text[:3000], source="plan_phase", relevance=0.9, phase="plan")
                    save_session(ide_session)

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Pre-flight validation before EXECUTE ----
            if not _should_skip("execute"):
                preflight_issues = []
                ws_path = Path(workspace)
                if not ws_path.exists():
                    preflight_issues.append(f"Workspace does not exist: {workspace}")
                elif not ws_path.is_dir():
                    preflight_issues.append(f"Workspace is not a directory: {workspace}")
                # Check git status if this is a git repo
                if ws_path.exists() and (ws_path / ".git").exists():
                    try:
                        git_status = subprocess.run(
                            ["git", "status", "--porcelain"], capture_output=True,
                            text=True, cwd=str(ws_path), timeout=10,
                        )
                        if git_status.returncode != 0:
                            preflight_issues.append(f"Git status check failed: {git_status.stderr[:100]}")
                    except Exception as git_err:
                        preflight_issues.append(f"Git check error: {git_err}")
                # Check plan has steps
                if not plan.steps:
                    preflight_issues.append("Plan has no steps — nothing to execute")
                if preflight_issues:
                    logger.warning(f"Job {job_id} pre-flight issues: {preflight_issues}")
                    _log_phase(job_id, "execute", {"event": "preflight_warning", "issues": preflight_issues})

            # ---- Phase 3: EXECUTE ----
            if ide_session:
                ide_session.set_phase("execute")
                ide_session.compact(target_tokens=4000)
                save_session(ide_session)

            # Inject relevant memories + past reflections into execute context
            try:
                job_metadata = {
                    "task": job.get("task", ""),
                    "project": job.get("project", ""),
                    "department": department,
                }
                # Enhance the task prompt with memory context
                original_task = job.get("task", "")
                enriched_task = inject_context(original_task, job_metadata)
                # Inject persistent agent context (cross-job memory)
                try:
                    agent_ctx = build_agent_context(agent_key, original_task, job.get("project", ""))
                    if agent_ctx:
                        enriched_task = f"{agent_ctx}\n\n---\n\n{enriched_task}"
                        logger.info(f"Job {job_id}: Agent session context injected ({len(agent_ctx)} chars)")
                except Exception as agent_ctx_err:
                    logger.debug(f"Job {job_id}: Agent context injection skipped: {agent_ctx_err}")
                if enriched_task != original_task:
                    job["_enriched_task"] = enriched_task
                    logger.info(f"Job {job_id}: Memory context injected ({len(enriched_task) - len(original_task)} chars added)")
            except Exception as mem_err:
                logger.debug(f"Job {job_id}: Memory injection skipped: {mem_err}")

            research_for_execute = _trim_context(research, max_tokens=1500)
            if not _should_skip("execute"):
                exec_results = await self._run_phase_with_retry(
                    "execute",
                    lambda: _execute_phase(job, agent_key, plan, research_for_execute, progress, guardrails=guardrails, department=department),
                    progress,
                )
            else:
                logger.info(f"Job {job_id}: Skipping execute (resuming from {resume_from_phase})")
                exec_results = [{"status": "skipped"}]

            failed_steps = [r for r in exec_results if r.get("status") == "failed"]
            result["phases"]["execute"] = {
                "status": "done" if not failed_steps else "partial",
                "steps_done": len(exec_results) - len(failed_steps),
                "steps_failed": len(failed_steps),
            }
            # Schema validation
            _ev = validate_phase_output("execute", exec_results)
            if _ev["errors"]:
                logger.warning(f"Job {job_id}: Execute schema errors: {_ev['errors']}")
            if isinstance(result["phases"].get("execute"), dict):
                result["phases"]["execute"]["validation"] = _ev

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 3.5: TRIPLE AI CODE REVIEW ----
            code_review_result = {"passed": True, "reviews": [], "summary": "skipped"}
            try:
                code_review_result = await _code_review_phase(
                    job, exec_results, progress, guardrails=guardrails,
                )
                result["phases"]["code_review"] = code_review_result
                if ide_session:
                    review_summary = code_review_result.get("summary", "")
                    ide_session.add_context(
                        "code_review", review_summary[:1500],
                        source="code_review_phase", relevance=0.85, phase="code_review",
                    )
                    save_session(ide_session)

                if not code_review_result.get("passed", True):
                    severity = "CRITICAL" if code_review_result.get("has_critical") else "MAJOR"
                    logger.warning(
                        f"Job {job_id}: code review BLOCKED ({severity}) — "
                        f"{code_review_result.get('issues_found', 0)} issues found. "
                        f"Passing findings to verify phase for confirmation."
                    )
            except Exception as cr_err:
                logger.warning(f"Job {job_id}: code review phase error (non-fatal): {cr_err}")
                result["phases"]["code_review"] = {"error": str(cr_err), "passed": True}

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 4: VERIFY ----
            if ide_session:
                ide_session.compact(target_tokens=4000)

            if not _should_skip("verify"):
                # Pass code review findings to verify phase so it knows what to double-check
                if code_review_result.get("issues_found", 0) > 0:
                    job["_code_review_issues"] = code_review_result.get("summary", "")
                verify_result = await self._run_phase_with_retry(
                    "verify",
                    lambda: _verify_phase(job, agent_key, exec_results, progress, guardrails=guardrails, department=department),
                    progress,
                )
            else:
                logger.info(f"Job {job_id}: Skipping verify (resuming from {resume_from_phase})")
                verify_result = {"status": "skipped"}
            result["phases"]["verify"] = verify_result
            # Schema validation
            _vv = validate_phase_output("verify", verify_result)
            if _vv["errors"]:
                logger.warning(f"Job {job_id}: Verify schema errors: {_vv['errors']}")
            if isinstance(result["phases"].get("verify"), dict):
                result["phases"]["verify"]["validation"] = _vv
            if ide_session:
                ide_session.set_phase("verify")
                save_session(ide_session)

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 5: DELIVER ----
            if ide_session:
                ide_session.compact(target_tokens=3000)

            delivery = await self._run_phase_with_retry(
                "deliver",
                lambda: _deliver_phase(job, agent_key, verify_result, progress, guardrails=guardrails),
                progress,
            )
            result["phases"]["deliver"] = delivery
            # Schema validation
            _dv = validate_phase_output("deliver", delivery)
            if _dv["errors"]:
                logger.warning(f"Job {job_id}: Deliver schema errors: {_dv['errors']}")
            if isinstance(result["phases"].get("deliver"), dict):
                result["phases"]["deliver"]["validation"] = _dv

            # Merge worktree changes back and clean up
            if use_worktree and project_root:
                try:
                    _merge_worktree_changes(job_id, project_root)
                    _cleanup_job_worktree(job_id, project_root)
                    logger.info(f"Job {job_id}: worktree merged and cleaned up")
                except Exception as wt_err:
                    logger.warning(f"Job {job_id}: worktree cleanup failed: {wt_err}")

            # Phase-level quality scoring (Process Reward Model lite)
            try:
                phase_scores = score_all_phases(
                    result,
                    plan=plan,
                    research_text=research,
                    exec_results=exec_results,
                )
                result["phase_scores"] = phase_scores
                phase_summary = ", ".join(
                    f"{k}={v['score']:.2f}" for k, v in phase_scores["phases"].items()
                )
                logger.info(
                    f"Job {job_id}: Phase scores — aggregate={phase_scores['aggregate']:.2f}, {phase_summary}"
                )
            except Exception as ps_err:
                logger.warning(f"Job {job_id}: Phase scoring failed (non-fatal): {ps_err}")

            # Mark success
            result["success"] = delivery.get("delivered", True)
            result["cost_usd"] = progress.cost_usd

            # Clean up IDE session on success
            if ide_session:
                ide_session.set_phase("deliver")
                save_session(ide_session)

            # Clear checkpoints on successful completion (no resume needed)
            clear_checkpoints(job_id)

            # Write key findings to shared blackboard for future jobs
            try:
                commit_hash = delivery.get("commit_hash", "")
                summary = delivery.get("summary", "")[:200]
                if commit_hash or summary:
                    blackboard_write(
                        key=f"last_delivery_{job_id[:20]}",
                        value=json.dumps({
                            "task": job.get("task", "")[:100],
                            "commit": commit_hash,
                            "summary": summary,
                        }),
                        job_id=job_id,
                        agent=agent_key,
                        project=job.get("project", ""),
                        ttl_seconds=604800,  # 7 days
                    )
            except Exception:
                pass

            # Update job to done
            final_status = "done" if result["success"] else "failed"
            final_kwargs = {
                "completed_at": _now_iso(),
                "cost_usd": round(progress.cost_usd, 6),
            }
            if not result["success"]:
                # Build error message from failed steps so it's always recorded
                failed_phases = [
                    f"{p}: {d.get('error', d.get('status', 'unknown'))}"
                    for p, d in result.get("phases", {}).items()
                    if isinstance(d, dict) and d.get("status") in ("failed", "partial")
                ]
                final_kwargs["error"] = "; ".join(failed_phases) if failed_phases else "Pipeline completed but delivery failed"
            update_job_status(job_id, final_status, **final_kwargs)

            logger.info(
                f"Job {job_id} COMPLETED: success={result['success']}, "
                f"cost=${progress.cost_usd:.4f}"
            )

            # Cross-channel notification: post to Slack + broadcast SSE event
            try:
                from gateway import send_slack_message, broadcast_event
                task_desc = job.get("task", "")[:100]
                pr_url = result.get("phases", {}).get("deliver", {}).get("pr_url", "")
                deploy_url = result.get("phases", {}).get("deliver", {}).get("vercel_deploy", "")

                slack_msg = (
                    f"✅ *Job Completed*\n"
                    f"*Task:* {task_desc}\n"
                    f"*Agent:* {result.get('agent', 'unknown')}\n"
                    f"*Cost:* ${progress.cost_usd:.4f}\n"
                    f"*Status:* {'Success' if result['success'] else 'Failed'}"
                )
                if pr_url:
                    slack_msg += f"\n*PR:* {pr_url}"
                if deploy_url:
                    slack_msg += f"\n*Deploy:* {deploy_url}"

                await send_slack_message("", slack_msg)

                status_emoji = "✅" if result["success"] else "❌"
                tg_msg = (
                    f"{status_emoji} *Job {'Done' if result['success'] else 'Failed'}*\n"
                    f"{job_id}\n{task_desc[:80]}\n"
                    f"Cost: ${progress.cost_usd:.4f}"
                )
                await send_telegram(tg_msg)

                broadcast_event({
                    "type": "job_completed",
                    "job_id": job_id,
                    "success": result["success"],
                    "cost": progress.cost_usd,
                    "task": task_desc,
                    "agent": result.get("agent", ""),
                    "timestamp": _now_iso(),
                })
            except Exception as notify_err:
                logger.warning(f"Job completion notification failed: {notify_err}")

        except BudgetExceededError as e:
            result["error"] = str(e)
            result["cost_usd"] = progress.cost_usd
            progress.error = str(e)
            progress.phase_status = "failed"
            _save_progress(progress)
            update_job_status(job_id, "failed", error=str(e))
            logger.error(f"Job {job_id} BUDGET EXCEEDED: {e}")
            try:
                await send_telegram(f"💸 *Budget Exceeded*\n{job_id}\n{e}")
            except Exception:
                pass

        except CreditExhaustedError as e:
            result["error"] = str(e)
            result["cost_usd"] = progress.cost_usd
            result["kill_status"] = "credit_exhausted"
            progress.error = str(e)
            progress.phase_status = "failed"
            _save_progress(progress)
            update_job_status(job_id, "credit_exhausted", error=str(e))
            logger.critical(f"Job {job_id} CREDIT EXHAUSTED: {e} — stopping queue")
            try:
                await send_telegram(
                    f"🚨 *Credit Exhausted — Queue Stopped*\n{job_id}\n{e}\n"
                    f"All pending jobs paused. Top up credits and restart."
                )
            except Exception:
                pass
            # Stop the runner — no point processing more jobs with no credits
            if hasattr(self, '_running'):
                self._running = False
                logger.critical("Runner stopped due to credit exhaustion")

        except GuardrailViolation as e:
            result["error"] = str(e)
            result["cost_usd"] = progress.cost_usd
            result["kill_status"] = e.kill_status
            result["guardrails"] = guardrails.summary()
            progress.error = str(e)
            progress.phase_status = "failed"
            _save_progress(progress)
            update_job_status(job_id, e.kill_status, error=str(e))
            _clear_kill_flag(job_id)  # Clean up kill flag if it was a manual kill
            logger.error(
                f"Job {job_id} GUARDRAIL VIOLATION ({e.kill_status}): {e.reason} "
                f"| guardrails={guardrails.summary()}"
            )
            # Notify about guardrail kills
            try:
                from gateway import send_slack_message
                await send_slack_message("", (
                    f"🛑 *Job Killed — {e.kill_status}*\n"
                    f"*Job:* {job_id}\n"
                    f"*Reason:* {e.reason}\n"
                    f"*Cost:* ${guardrails.cost_usd:.4f} / ${guardrails.max_cost_usd:.2f}\n"
                    f"*Iterations:* {guardrails.iterations} / {guardrails.max_iterations}\n"
                    f"*Elapsed:* {guardrails.elapsed_seconds():.0f}s / {guardrails.max_duration_secs}s"
                ))
                await send_telegram(
                    f"🛑 *Job Killed (Guardrail)*\n{job_id}\n{e.reason}"
                )
            except Exception:
                pass

        except CancelledError as e:
            result["error"] = "Job cancelled"
            result["cost_usd"] = progress.cost_usd
            update_job_status(job_id, "cancelled")
            logger.info(f"Job {job_id} CANCELLED")

        except Exception as e:
            result["error"] = str(e)
            result["cost_usd"] = progress.cost_usd
            progress.error = str(e)
            progress.phase_status = "failed"
            _save_progress(progress)
            update_job_status(job_id, "failed", error=str(e))
            logger.error(f"Job {job_id} FAILED: {e}\n{traceback.format_exc()}")
            try:
                await send_telegram(
                    f"❌ *Job Failed*\n{job_id}\n{job.get('task', '')[:80]}\n"
                    f"Error: {str(e)[:100]}"
                )
            except Exception:
                pass

        # Clean up worktree on failure (success path handles it above)
        if use_worktree and project_root and result.get("error"):
            try:
                _cleanup_job_worktree(job_id, project_root)
            except Exception:
                pass

        # Include final guardrail metrics in result
        result["guardrails"] = guardrails.summary()

        # Save final result
        run_dir = _job_run_dir(job_id)
        result["completed_at"] = _now_iso()
        with open(run_dir / "result.json", "w") as f:
            json.dump(result, f, indent=2, default=str)

        # Log metrics to self-improvement engine
        try:
            from self_improve import get_self_improve_engine
            si = get_self_improve_engine()
            elapsed = time.time() - (getattr(progress, '_start_time', None) or time.time())
            error_str = result.get("error", "")
            error_type = ""
            if error_str:
                error_lower = str(error_str).lower()
                if "budget" in error_lower:
                    error_type = "budget"
                elif "guardrail" in error_lower:
                    error_type = "guardrail"
                elif "timeout" in error_lower or "timed out" in error_lower:
                    error_type = "timeout"
                else:
                    error_type = "code_error"
            si.log_job_outcome(
                job_id=job_id,
                project=job.get("project", "unknown"),
                task=job.get("task", ""),
                agent=result.get("agent", "unknown"),
                success=result.get("success", False),
                iterations=guardrails.iterations if guardrails else 0,
                cost_usd=progress.cost_usd,
                time_seconds=abs(elapsed),
                phases_completed=sum(1 for p in result.get("phases", {}).values() if p),
                error_type=error_type,
            )
        except Exception as si_err:
            logger.warning(f"Failed to log self-improve metric: {si_err}")

        # Save reflexion for future jobs (structured v2)
        try:
            elapsed_secs = time.time() - (getattr(progress, '_start_time', None) or time.time())
            outcome = "success" if result.get("success") else "failed"
            save_reflection(
                job_id=job_id,
                job_data=job,
                outcome=outcome,
                duration_seconds=abs(elapsed_secs),
                department=department,
                run_result=result,
            )
            logger.info(f"Job {job_id}: Reflexion saved (outcome={outcome}, dept={department}, structured=yes)")
        except Exception as ref_err:
            logger.warning(f"Failed to save reflexion: {ref_err}")

        # Auto-extract learnings from completed jobs and save to memory
        try:
            job_metadata = {
                "task": job.get("task", ""),
                "project": job.get("project", "openclaw"),
                "department": department,
            }
            learnings = auto_extract_learnings(result, job_metadata)
            if learnings:
                save_learnings(learnings, project=job.get("project", "openclaw"))
                logger.info(f"Job {job_id}: {len(learnings)} learnings auto-extracted")
        except Exception as learn_err:
            logger.debug(f"Job {job_id}: Learning extraction failed: {learn_err}")

        # Auto-skill extraction from successful jobs
        try:
            if result.get("success"):
                from auto_skills import try_extract_and_save
                skill_name = try_extract_and_save(job_id, job, result)
                if skill_name:
                    logger.info(f"Job {job_id}: Auto-skill extracted: {skill_name}")
        except Exception as skill_err:
            logger.warning(f"Failed to extract auto-skill: {skill_err}")

        # Record job in agent's persistent session (cross-job memory)
        try:
            agent_session = get_session(agent_key)
            record_job(agent_session, result, {
                "job_id": job_id,
                "task": job.get("task", ""),
                "project": job.get("project", "openclaw"),
                "department": department,
            })
            logger.info(f"Job {job_id}: Recorded in agent session '{agent_key}'")
        except Exception as sess_err:
            logger.debug(f"Job {job_id}: Agent session recording failed: {sess_err}")

        return result

    async def _run_phase_with_retry(self, phase_name: str, phase_fn, progress: JobProgress):
        """Run a phase function with retry logic and exponential backoff."""
        last_error = None
        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                return await phase_fn()
            except (BudgetExceededError, GuardrailViolation, CreditExhaustedError):
                raise  # Never retry budget/guardrail/credit failures
            except Exception as e:
                # Circuit breaker: credit/billing errors are non-retryable
                err_lower = str(e).lower()
                if "credit balance" in err_lower or "billing" in err_lower or "insufficient_quota" in err_lower:
                    raise CreditExhaustedError(
                        f"API credit/billing error (non-retryable): {e}"
                    ) from e
                last_error = e
                progress.retries += 1
                backoff = (2 ** attempt) * 3  # 3s, 6s, 12s
                logger.warning(
                    f"Phase {phase_name} attempt {attempt+1}/{DEFAULT_MAX_RETRIES} "
                    f"failed for {progress.job_id}: {e}. Retrying in {backoff}s..."
                )
                _log_phase(progress.job_id, phase_name, {
                    "event": "phase_retry",
                    "attempt": attempt + 1,
                    "error": str(e),
                    "backoff_seconds": backoff,
                })
                if attempt < DEFAULT_MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)

        # All retries exhausted
        raise RuntimeError(
            f"Phase {phase_name} failed after {DEFAULT_MAX_RETRIES} attempts: {last_error}"
        ) from last_error


class CancelledError(Exception):
    """Raised when a job is cancelled."""
    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job {job_id} cancelled")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_runner_instance: Optional[AutonomousRunner] = None


def get_runner() -> Optional[AutonomousRunner]:
    """Get the global runner instance."""
    return _runner_instance


def init_runner(**kwargs) -> AutonomousRunner:
    """Initialize and return the global runner instance."""
    global _runner_instance
    _runner_instance = AutonomousRunner(**kwargs)
    return _runner_instance


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

    print("=" * 60)
    print("OpenClaw Autonomous Job Runner")
    print("=" * 60)
    print()

    # Quick self-test: verify imports and data structures work
    runner = AutonomousRunner(poll_interval=10, max_concurrent=2, budget_limit_usd=5.0)
    print(f"[OK] Runner initialized: {runner.get_stats()}")

    # Test data models
    progress = JobProgress(job_id="test-001", started_at=_now_iso())
    print(f"[OK] JobProgress: {progress.to_dict()}")

    plan = ExecutionPlan(
        job_id="test-001",
        agent="coder_agent",
        steps=[
            PlanStep(index=0, description="Write the code", tool_hints=["file_write"]),
            PlanStep(index=1, description="Run tests", tool_hints=["shell_execute"]),
        ],
        created_at=_now_iso(),
    )
    print(f"[OK] ExecutionPlan: {len(plan.steps)} steps")

    # Test agent selection
    test_jobs = [
        {"task": "Fix CSS button on landing page", "project": "barber-crm"},
        {"task": "Refactor authentication system architecture", "project": "openclaw"},
        {"task": "Security audit of RLS policies", "project": "barber-crm"},
        {"task": "Query monthly revenue from Supabase", "project": "delhi-palace"},
        {"task": "Plan the sprint roadmap", "project": "openclaw"},
    ]
    for tj in test_jobs:
        agent, dept = _select_agent_for_job(tj)
        print(f"[OK] Route: '{tj['task'][:50]}' -> dept={dept}, agent={agent}")

    # Test tool filtering
    for phase in Phase:
        tools = _filter_tools_for_phase(phase)
        print(f"[OK] Phase {phase.value}: {len(tools)} tools available")

    # Test JSON extraction
    test_json = '```json\n{"steps": [{"description": "test", "tools": ["file_write"]}]}\n```'
    extracted = _extract_json_block(test_json)
    parsed = json.loads(extracted)
    print(f"[OK] JSON extraction: {parsed}")

    # Test directory creation
    test_dir = _job_run_dir("test-selfcheck")
    assert test_dir.exists()
    print(f"[OK] Job run directory: {test_dir}")

    print()
    print("All self-checks passed. Runner is ready.")
    print()
    print("To start in production:")
    print("  from autonomous_runner import init_runner")
    print("  runner = init_runner(max_concurrent=2, budget_limit_usd=5.0)")
    print("  await runner.start()")
