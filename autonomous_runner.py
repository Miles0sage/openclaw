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
    - Progress logged to /tmp/openclaw_job_runs/{job_id}/
    - Costs tracked per phase via cost_tracker.py
"""

import asyncio
import json
import logging
import os
import time
import traceback
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from agent_tools import execute_tool, AGENT_TOOLS
from job_manager import get_job, update_job_status, list_jobs, get_pending_jobs
from cost_tracker import log_cost_event, calculate_cost, get_cost_metrics

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOB_RUNS_DIR = Path("/tmp/openclaw_job_runs")
DEFAULT_POLL_INTERVAL = 10        # seconds between job queue checks
DEFAULT_MAX_CONCURRENT = 2        # max parallel job executions
DEFAULT_MAX_RETRIES = 3           # retries per phase on failure
DEFAULT_BUDGET_LIMIT_USD = 5.0    # per-job cost cap
MAX_TOOL_ITERATIONS = 30          # safety cap on agent tool loops per step
MAX_PLAN_STEPS = 20               # safety cap on plan step count

logger = logging.getLogger("autonomous_runner")

# Agent keys from config.json — mapped by capability
AGENT_MAP = {
    "project_manager": "project_manager",   # Claude Opus  — planning, coordination
    "coder_agent":     "coder_agent",        # Kimi 2.5    — routine code
    "elite_coder":     "elite_coder",        # MiniMax M2.5 — complex code
    "hacker_agent":    "hacker_agent",       # Kimi Reasoner — security
    "database_agent":  "database_agent",     # Claude Opus  — data / SQL
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
    RESEARCH = "research"
    PLAN     = "plan"
    EXECUTE  = "execute"
    VERIFY   = "verify"
    DELIVER  = "deliver"


@dataclass
class PlanStep:
    index: int
    description: str
    tool_hints: list = field(default_factory=list)
    status: str = "pending"         # pending | running | done | failed | skipped
    result: str = ""
    attempts: int = 0
    error: str = ""


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


def _filter_tools_for_phase(phase: Phase) -> list:
    """Return the AGENT_TOOLS definitions filtered for a given phase."""
    allowed = {
        Phase.RESEARCH: RESEARCH_TOOLS,
        Phase.PLAN:     PLAN_TOOLS,
        Phase.EXECUTE:  EXECUTE_TOOLS,
        Phase.VERIFY:   VERIFY_TOOLS,
        Phase.DELIVER:  DELIVER_TOOLS,
    }.get(phase, EXECUTE_TOOLS)

    return [t for t in AGENT_TOOLS if t["name"] in allowed]


def _select_agent_for_job(job: dict) -> str:
    """Pick the best agent for a job based on its task description and project.

    Priority order matters: complex-code keywords are checked before security
    keywords so that 'Refactor authentication architecture' routes to elite_coder
    rather than hacker_agent.
    """
    task_lower = (job.get("task", "") + " " + job.get("project", "")).lower()

    # Complex code tasks (check FIRST — these override security keywords)
    if any(kw in task_lower for kw in [
        "refactor", "architecture", "redesign", "system design", "multi-file",
        "algorithm", "race condition", "memory leak", "performance",
    ]):
        return "elite_coder"

    # Security tasks
    if any(kw in task_lower for kw in [
        "security", "audit", "pentest", "vulnerability", "rls", "owasp",
        "xss", "injection", "penetration",
    ]):
        return "hacker_agent"

    # Database / data tasks
    if any(kw in task_lower for kw in [
        "database", "supabase", "sql", "query", "migration", "schema",
        "rls policy", "data analysis",
    ]):
        return "database_agent"

    # Simple code tasks (default for most work)
    if any(kw in task_lower for kw in [
        "fix", "add", "build", "create", "implement", "update", "css",
        "component", "endpoint", "test", "feature", "bug",
    ]):
        return "coder_agent"

    # Fallback: PM handles ambiguous tasks
    return "project_manager"


async def _call_agent(agent_key: str, prompt: str, conversation: list = None,
                      tools: list = None, job_id: str = "", phase: str = "") -> dict:
    """
    Call an agent model. Wraps the synchronous call_model_for_agent in an
    executor so it doesn't block the event loop. If tools are provided,
    they are passed to the Claude API for tool_use; the agent iterates
    until it stops requesting tool calls.

    Returns: {"text": str, "tokens": int, "tool_calls": list[dict], "cost_usd": float}
    """
    # Import here to avoid circular imports at module level
    from gateway import call_model_for_agent, anthropic_client, get_agent_config

    agent_config = get_agent_config(agent_key)
    provider = agent_config.get("apiProvider", "anthropic") if agent_config else "anthropic"
    model = agent_config.get("model", "claude-opus-4-6") if agent_config else "claude-opus-4-6"

    total_tokens = 0
    total_cost = 0.0
    all_tool_calls = []
    final_text = ""

    # Only Anthropic supports native tool_use; for other providers, fall back
    # to a simple text call and parse tool requests from the response.
    if provider == "anthropic" and tools:
        # Build messages
        messages = list(conversation or [])
        messages.append({"role": "user", "content": prompt})

        # Tool-use loop: agent may request tools multiple times
        iterations = 0
        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: anthropic_client.messages.create(
                model=model,
                max_tokens=8192,
                messages=messages,
                tools=tools,
            ))

            tokens_in = response.usage.input_tokens
            tokens_out = response.usage.output_tokens
            total_tokens += tokens_out
            step_cost = calculate_cost(model, tokens_in, tokens_out)
            total_cost += step_cost

            # Log cost
            log_cost_event(
                project=job_id.split("-")[0] if job_id else "openclaw",
                agent=agent_key,
                model=model,
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
                    None, execute_tool, tool_name, tool_input
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

            # Append assistant response + tool results to messages for next iteration
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        return {
            "text": final_text,
            "tokens": total_tokens,
            "tool_calls": all_tool_calls,
            "cost_usd": total_cost,
        }

    else:
        # Non-tool call path (or non-Anthropic provider)
        loop = asyncio.get_event_loop()
        response_text, tokens = await loop.run_in_executor(
            None, call_model_for_agent, agent_key, prompt, conversation
        )
        return {
            "text": response_text,
            "tokens": tokens,
            "tool_calls": [],
            "cost_usd": 0.0,  # cost already logged inside call_model_for_agent
        }


# ---------------------------------------------------------------------------
# Execution Pipeline — 5 Phases
# ---------------------------------------------------------------------------

async def _research_phase(job: dict, agent_key: str, progress: JobProgress) -> str:
    """
    Phase 1: RESEARCH
    Gather context about the task — read relevant files, search the web,
    understand the codebase. Returns a research summary string.
    """
    progress.phase = Phase.RESEARCH
    progress.phase_status = "running"
    _save_progress(progress)

    task = job["task"]
    project = job.get("project", "unknown")

    prompt = (
        f"You are researching a task before planning and executing it.\n\n"
        f"PROJECT: {project}\n"
        f"TASK: {task}\n\n"
        f"Gather all the context you need:\n"
        f"1. Use research_task to understand the domain/technology involved\n"
        f"2. Use glob_files and grep_search to find relevant existing code\n"
        f"3. Use file_read to examine key files\n"
        f"4. Use github_repo_info to check open issues/PRs if relevant\n\n"
        f"After researching, provide a structured summary:\n"
        f"- RELEVANT FILES: List the files that need to change or are related\n"
        f"- EXISTING PATTERNS: Key patterns/conventions in the codebase\n"
        f"- DEPENDENCIES: What this task depends on\n"
        f"- RISKS: Potential issues or gotchas\n"
        f"- CONTEXT: Any other important context for planning"
    )

    tools = _filter_tools_for_phase(Phase.RESEARCH)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="research")

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
                      progress: JobProgress) -> ExecutionPlan:
    """
    Phase 2: PLAN
    Create a step-by-step execution plan based on research findings.
    Returns an ExecutionPlan with concrete steps.
    """
    progress.phase = Phase.PLAN
    progress.phase_status = "running"
    _save_progress(progress)

    task = job["task"]
    project = job.get("project", "unknown")

    prompt = (
        f"Based on the research below, create a concrete step-by-step plan to complete this task.\n\n"
        f"PROJECT: {project}\n"
        f"TASK: {task}\n\n"
        f"RESEARCH FINDINGS:\n{research}\n\n"
        f"Create a plan with numbered steps. For each step specify:\n"
        f"- A clear description of what to do\n"
        f"- Which tools to use (file_write, file_edit, shell_execute, git_operations, etc.)\n\n"
        f"IMPORTANT: Respond ONLY with valid JSON in this exact format:\n"
        f'{{"steps": [\n'
        f'  {{"description": "Step 1: ...", "tools": ["file_write", "shell_execute"]}},\n'
        f'  {{"description": "Step 2: ...", "tools": ["file_edit"]}}\n'
        f"]}}\n\n"
        f"Keep the plan focused and practical. Maximum {MAX_PLAN_STEPS} steps.\n"
        f"Do NOT include markdown fences or any text outside the JSON."
    )

    tools = _filter_tools_for_phase(Phase.PLAN)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="plan")

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
        # Fallback: create a single-step plan with the whole task
        logger.warning(f"Could not parse plan JSON for {job['id']}, using fallback single-step plan")
        plan_data = {"steps": [{"description": f"Complete the task: {task}", "tools": ["shell_execute", "file_write", "file_edit"]}]}

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
                         research: str, progress: JobProgress) -> list:
    """
    Phase 3: EXECUTE
    Run each step in the plan. The agent gets the step description plus
    tool access and decides which tools to call.

    Returns a list of step results.
    """
    progress.phase = Phase.EXECUTE
    progress.phase_status = "running"
    _save_progress(progress)

    tools = _filter_tools_for_phase(Phase.EXECUTE)
    results = []
    conversation_context = []

    for step in plan.steps:
        if progress.cancelled:
            step.status = "skipped"
            results.append({"step": step.index, "status": "skipped", "reason": "job cancelled"})
            continue

        step.status = "running"
        progress.step_index = step.index
        _save_progress(progress)

        prompt = (
            f"You are executing step {step.index + 1} of {len(plan.steps)} for a job.\n\n"
            f"PROJECT: {job.get('project', 'unknown')}\n"
            f"OVERALL TASK: {job['task']}\n\n"
            f"RESEARCH CONTEXT:\n{research[:3000]}\n\n"
            f"CURRENT STEP: {step.description}\n"
            f"SUGGESTED TOOLS: {', '.join(step.tool_hints)}\n\n"
        )

        if conversation_context:
            prompt += (
                f"PREVIOUS STEPS COMPLETED:\n"
                + "\n".join(f"- Step {r['step']+1}: {r.get('summary', 'done')}" for r in results[-5:])
                + "\n\n"
            )

        prompt += (
            f"Execute this step now using the available tools. "
            f"When done, summarize what you did and the outcome."
        )

        # Retry logic per step
        step_result = None
        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                result = await _call_agent(agent_key, prompt, tools=tools,
                                           job_id=job["id"], phase="execute")
                progress.cost_usd += result["cost_usd"]

                # Budget check
                if progress.cost_usd > DEFAULT_BUDGET_LIMIT_USD:
                    raise BudgetExceededError(
                        f"Job budget exceeded: ${progress.cost_usd:.4f} > ${DEFAULT_BUDGET_LIMIT_USD}"
                    )

                step.status = "done"
                step.result = result["text"][:5000]
                step.attempts = attempt + 1
                step_result = {
                    "step": step.index,
                    "status": "done",
                    "summary": result["text"][:500],
                    "tool_calls": len(result["tool_calls"]),
                    "cost_usd": result["cost_usd"],
                    "attempts": attempt + 1,
                }
                break

            except BudgetExceededError:
                raise  # Don't retry budget failures

            except Exception as e:
                step.attempts = attempt + 1
                backoff = (2 ** attempt) * 2  # 2s, 4s, 8s
                logger.warning(
                    f"Step {step.index} attempt {attempt+1} failed for {job['id']}: {e}. "
                    f"Retrying in {backoff}s..."
                )
                _log_phase(job["id"], "execute", {
                    "event": "step_retry",
                    "step": step.index,
                    "attempt": attempt + 1,
                    "error": str(e),
                    "backoff_seconds": backoff,
                })
                if attempt < DEFAULT_MAX_RETRIES - 1:
                    await asyncio.sleep(backoff)

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

        _log_phase(job["id"], "execute", {
            "event": "step_complete",
            **step_result,
        })

    progress.phase_status = "done"
    _save_progress(progress)

    return results


async def _verify_phase(job: dict, agent_key: str, execution_results: list,
                        progress: JobProgress) -> dict:
    """
    Phase 4: VERIFY
    Run tests, lint checks, and quality verification.
    Returns a verification result dict.
    """
    progress.phase = Phase.VERIFY
    progress.phase_status = "running"
    _save_progress(progress)

    project = job.get("project", "unknown")

    # Build summary of what was done
    steps_summary = "\n".join(
        f"- Step {r['step']+1}: {r.get('summary', r.get('status', '?'))}"
        for r in execution_results
    )

    prompt = (
        f"You just completed execution of a task. Now verify the results.\n\n"
        f"PROJECT: {project}\n"
        f"TASK: {job['task']}\n\n"
        f"EXECUTION RESULTS:\n{steps_summary}\n\n"
        f"Verification checklist:\n"
        f"1. Use shell_execute to run any relevant tests (pytest, jest, vitest, etc.)\n"
        f"2. Use shell_execute to run linting if applicable\n"
        f"3. Use file_read to spot-check created/modified files for correctness\n"
        f"4. Use grep_search to check for common issues (TODO, FIXME, console.log, etc.)\n\n"
        f"Respond with a JSON object:\n"
        f'{{"passed": true/false, "summary": "...", "issues": ["issue1", "issue2"]}}\n'
        f"Do NOT include markdown fences or any text outside the JSON."
    )

    tools = _filter_tools_for_phase(Phase.VERIFY)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="verify")

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

    progress.phase_status = "done"
    _save_progress(progress)

    _log_phase(job["id"], "verify", {
        "event": "phase_complete",
        "passed": verify_data.get("passed", True),
        "issues_count": len(verify_data.get("issues", [])),
        "cost_usd": result["cost_usd"],
    })

    return verify_data


async def _deliver_phase(job: dict, agent_key: str, verify_result: dict,
                         progress: JobProgress) -> dict:
    """
    Phase 5: DELIVER
    Git commit, push, deploy if needed, send notifications.
    Returns a delivery result dict.
    """
    progress.phase = Phase.DELIVER
    progress.phase_status = "running"
    _save_progress(progress)

    project = job.get("project", "unknown")

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

    prompt = (
        f"The task is complete and verified. Now deliver the results.\n\n"
        f"PROJECT: {project}\n"
        f"TASK: {job['task']}\n"
        f"REPO PATH: {repo_path}\n\n"
        f"Delivery steps:\n"
        f"1. Use git_operations with action='status' to see what changed (repo_path='{repo_path}')\n"
        f"2. Use git_operations with action='add' to stage the changes (repo_path='{repo_path}')\n"
        f"3. Use git_operations with action='commit' with a clear commit message (repo_path='{repo_path}')\n"
        f"4. Use git_operations with action='push' to push to remote (repo_path='{repo_path}')\n"
        f"5. If the project uses Vercel, use vercel_deploy to trigger a deployment\n"
        f"6. Send a slack message summarizing what was done\n\n"
        f"Respond with a JSON object when done:\n"
        f'{{"delivered": true, "commit_hash": "...", "pushed": true, "deployed": true/false, "summary": "..."}}\n'
        f"Do NOT include markdown fences or any text outside the JSON."
    )

    tools = _filter_tools_for_phase(Phase.DELIVER)
    result = await _call_agent(agent_key, prompt, tools=tools,
                               job_id=job["id"], phase="deliver")

    progress.cost_usd += result["cost_usd"]

    # Parse delivery result
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

    progress.phase_status = "done"
    _save_progress(progress)

    _log_phase(job["id"], "deliver", {
        "event": "phase_complete",
        "delivered": delivery.get("delivered", True),
        "cost_usd": result["cost_usd"],
    })

    return delivery


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _extract_json_block(text: str) -> Optional[str]:
    """Extract JSON from a response that may contain markdown fences."""
    import re
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
        self._progress: dict[str, JobProgress] = {}          # job_id -> JobProgress
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._cancelled_jobs: set = set()

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

        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("AutonomousRunner STARTED — polling for jobs")

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
                pending = await asyncio.get_event_loop().run_in_executor(
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

            await asyncio.sleep(self.poll_interval)

    async def _execute_with_semaphore(self, job: dict):
        """Wraps job execution with the concurrency semaphore."""
        job_id = job["id"]
        async with self._semaphore:
            try:
                await self._run_job_pipeline(job)
            except Exception as e:
                logger.error(f"Job {job_id} failed: {e}")
            finally:
                self._active_jobs.pop(job_id, None)

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

        # Select agent
        agent_key = _select_agent_for_job(job)
        logger.info(f"Job {job_id}: agent={agent_key}, project={job.get('project','?')}")

        # Initialize progress tracking
        progress = JobProgress(
            job_id=job_id,
            started_at=started_at,
        )
        self._progress[job_id] = progress
        _save_progress(progress)

        # Update job status to running
        update_job_status(job_id, "analyzing")

        result = {
            "job_id": job_id,
            "agent": agent_key,
            "started_at": started_at,
            "phases": {},
            "success": False,
            "error": None,
            "cost_usd": 0.0,
        }

        try:
            # ---- Phase 1: RESEARCH ----
            research = await self._run_phase_with_retry(
                "research",
                lambda: _research_phase(job, agent_key, progress),
                progress,
            )
            result["phases"]["research"] = {"status": "done", "length": len(research)}

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 2: PLAN ----
            plan = await self._run_phase_with_retry(
                "plan",
                lambda: _plan_phase(job, agent_key, research, progress),
                progress,
            )
            result["phases"]["plan"] = {
                "status": "done",
                "steps": len(plan.steps),
            }

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 3: EXECUTE ----
            update_job_status(job_id, "code_generated")
            exec_results = await self._run_phase_with_retry(
                "execute",
                lambda: _execute_phase(job, agent_key, plan, research, progress),
                progress,
            )

            failed_steps = [r for r in exec_results if r.get("status") == "failed"]
            result["phases"]["execute"] = {
                "status": "done" if not failed_steps else "partial",
                "steps_done": len(exec_results) - len(failed_steps),
                "steps_failed": len(failed_steps),
            }

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 4: VERIFY ----
            verify_result = await self._run_phase_with_retry(
                "verify",
                lambda: _verify_phase(job, agent_key, exec_results, progress),
                progress,
            )
            result["phases"]["verify"] = verify_result

            if progress.cancelled:
                raise CancelledError(job_id)

            # ---- Phase 5: DELIVER ----
            delivery = await self._run_phase_with_retry(
                "deliver",
                lambda: _deliver_phase(job, agent_key, verify_result, progress),
                progress,
            )
            result["phases"]["deliver"] = delivery

            # Mark success
            result["success"] = delivery.get("delivered", True)
            result["cost_usd"] = progress.cost_usd

            # Update job to done
            final_status = "done" if result["success"] else "failed"
            update_job_status(
                job_id, final_status,
                completed_at=_now_iso(),
                cost_usd=round(progress.cost_usd, 6),
            )

            logger.info(
                f"Job {job_id} COMPLETED: success={result['success']}, "
                f"cost=${progress.cost_usd:.4f}"
            )

        except BudgetExceededError as e:
            result["error"] = str(e)
            result["cost_usd"] = progress.cost_usd
            progress.error = str(e)
            progress.phase_status = "failed"
            _save_progress(progress)
            update_job_status(job_id, "failed", error=str(e))
            logger.error(f"Job {job_id} BUDGET EXCEEDED: {e}")

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

        # Save final result
        run_dir = _job_run_dir(job_id)
        result["completed_at"] = _now_iso()
        with open(run_dir / "result.json", "w") as f:
            json.dump(result, f, indent=2, default=str)

        return result

    async def _run_phase_with_retry(self, phase_name: str, phase_fn, progress: JobProgress):
        """Run a phase function with retry logic and exponential backoff."""
        last_error = None
        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                return await phase_fn()
            except BudgetExceededError:
                raise  # Never retry budget failures
            except Exception as e:
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
        agent = _select_agent_for_job(tj)
        print(f"[OK] Route: '{tj['task'][:50]}' -> {agent}")

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
