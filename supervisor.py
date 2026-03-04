"""
Supervisor Pattern — OODA Multi-Agent Decomposition

When Overseer detects a complex task (multi-file, multi-concern), it:
1. OBSERVE: Analyze the task for decomposable sub-tasks
2. ORIENT: Map sub-tasks to the right specialist agents
3. DECIDE: Choose parallel vs sequential execution
4. ACT: Spawn sub-agents via TmuxSpawner, collect results, synthesize

Max depth: 1 (sub-agents NEVER spawn sub-agents).
Max parallel: 4 (VPS constraint: 4 CPU / 8GB RAM).

Cost: ~$0.001 per decomposition call (Grok grok-3-mini).
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("supervisor")

MAX_PARALLEL_AGENTS = 4
DECOMPOSITION_TIMEOUT = 30  # seconds for Grok to decompose
AGENT_TIMEOUT_MINUTES = 15  # per sub-agent


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SubTask:
    id: str
    description: str
    agent: str = "codegen_pro"  # default to cheapest
    priority: int = 1  # 1=first, higher=later
    depends_on: list = field(default_factory=list)  # sub-task IDs
    result: Optional[str] = None
    status: str = "pending"  # pending, running, done, failed
    pane_id: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class DecompositionResult:
    should_decompose: bool = False
    reason: str = ""
    sub_tasks: list = field(default_factory=list)
    execution_mode: str = "parallel"  # parallel or sequential
    estimated_speedup: float = 1.0


# ---------------------------------------------------------------------------
# Task complexity detection
# ---------------------------------------------------------------------------

COMPLEXITY_SIGNALS = {
    "multi_file": ["multi-file", "multiple files", "across files", "several files"],
    "multi_concern": ["refactor", "redesign", "overhaul", "rewrite", "migration"],
    "parallel_possible": ["and also", "additionally", "as well as", "plus"],
    "distinct_domains": [
        "frontend and backend", "client and server", "api and ui",
        "database and application", "tests and implementation",
    ],
    "testing": ["test", "coverage", "unit test", "integration test"],
}

# Minimum complexity threshold (sum of signal weights)
DECOMPOSE_THRESHOLD = 3


def detect_complexity(task: str) -> dict:
    """Fast heuristic check — should we even try decomposition?

    Returns {"score": int, "signals": list[str], "should_attempt": bool}
    """
    task_lower = task.lower()
    score = 0
    signals = []

    for category, keywords in COMPLEXITY_SIGNALS.items():
        for kw in keywords:
            if kw in task_lower:
                weight = 2 if category in ("multi_concern", "distinct_domains") else 1
                score += weight
                signals.append(f"{category}:{kw}")
                break  # one match per category is enough

    # Length heuristic: longer tasks are more likely to be decomposable
    if len(task) > 300:
        score += 1
        signals.append("long_description")

    return {
        "score": score,
        "signals": signals,
        "should_attempt": score >= DECOMPOSE_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# LLM-powered decomposition
# ---------------------------------------------------------------------------

async def decompose_task(task: str, project: str = "openclaw") -> DecompositionResult:
    """Use Grok to decompose a complex task into parallel sub-tasks.

    Cost: ~$0.001 per call (grok-3-mini).
    """
    from grok_executor import call_grok

    prompt = f"""You are a task decomposition engine for an AI agent system.

TASK: {task}
PROJECT: {project}

Analyze this task and determine if it can be split into 2-4 independent sub-tasks
that different specialist agents can work on IN PARALLEL.

Available agents:
- codegen_pro: Simple code (fixes, features, CSS, single-file edits). Cheapest.
- codegen_elite: Complex code (refactors, multi-file, architecture). More capable.
- pentest_ai: Security audits, vulnerability checks, RLS policies.
- test_generator: Write tests, coverage analysis, edge case detection.
- code_reviewer: Code review, tech debt assessment, pattern checks.
- debugger: Deep debugging, race conditions, memory leaks.

Rules:
- Only decompose if sub-tasks are TRULY independent (can run in parallel)
- Each sub-task must be self-contained (agent won't see other sub-task outputs)
- 2-4 sub-tasks max (more = coordination overhead exceeds benefit)
- If the task is naturally sequential, say so — don't force decomposition

Respond ONLY in this JSON format:
{{"decompose": true/false, "reason": "why", "mode": "parallel"/"sequential", "speedup": 1.5, "tasks": [{{"id": "t1", "description": "...", "agent": "codegen_pro", "depends_on": []}}]}}"""

    try:
        resp = await call_grok(
            prompt=prompt,
            system_prompt="You are a strict task decomposition engine. Output ONLY valid JSON.",
            model="grok-3-mini",
            max_tokens=512,
            temperature=0.0,
        )

        text = resp.get("text", "").strip()
        if "{" in text:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            parsed = json.loads(json_str)

            result = DecompositionResult(
                should_decompose=parsed.get("decompose", False),
                reason=parsed.get("reason", ""),
                execution_mode=parsed.get("mode", "parallel"),
                estimated_speedup=parsed.get("speedup", 1.0),
            )

            for t in parsed.get("tasks", []):
                result.sub_tasks.append(SubTask(
                    id=t.get("id", f"t{len(result.sub_tasks)+1}"),
                    description=t.get("description", ""),
                    agent=t.get("agent", "codegen_pro"),
                    depends_on=t.get("depends_on", []),
                ))

            # Enforce limits
            if len(result.sub_tasks) > MAX_PARALLEL_AGENTS:
                result.sub_tasks = result.sub_tasks[:MAX_PARALLEL_AGENTS]

            return result

    except Exception as e:
        logger.warning(f"Task decomposition failed: {e}")

    return DecompositionResult(
        should_decompose=False,
        reason=f"Decomposition failed: {e}" if 'e' in dir() else "Parse error",
    )


# ---------------------------------------------------------------------------
# Parallel execution via TmuxSpawner
# ---------------------------------------------------------------------------

async def execute_parallel(
    sub_tasks: list[SubTask],
    project: str = "openclaw",
    project_root: str = "/root/openclaw",
) -> list[SubTask]:
    """Spawn sub-agents in parallel, wait for completion, collect results."""
    from tmux_spawner import TmuxSpawner

    spawner = TmuxSpawner()

    # Build job specs for spawn_parallel
    jobs = []
    for st in sub_tasks:
        prompt = (
            f"You are a specialist agent. Complete this sub-task precisely.\n\n"
            f"SUB-TASK: {st.description}\n\n"
            f"RULES:\n"
            f"- Complete ONLY this sub-task, nothing else\n"
            f"- Do NOT spawn sub-agents\n"
            f"- When done, output [AGENT_COMPLETED] on its own line\n"
            f"- Be concise in your output\n"
        )
        jobs.append({
            "job_id": f"sub_{st.id}",
            "prompt": prompt,
            "worktree_repo": project_root,
            "use_worktree": True,
            "timeout_minutes": AGENT_TIMEOUT_MINUTES,
        })

    logger.info(f"Supervisor: spawning {len(jobs)} parallel sub-agents")
    spawn_results = spawner.spawn_parallel(jobs)

    # Track pane IDs
    pane_map = {}
    for sr in spawn_results:
        if sr.get("status") == "spawned":
            pane_map[sr["job_id"]] = sr["pane_id"]

    # Wait for all agents to complete (poll every 10s, max AGENT_TIMEOUT_MINUTES)
    start = time.time()
    timeout = AGENT_TIMEOUT_MINUTES * 60
    completed = set()

    while len(completed) < len(pane_map) and (time.time() - start) < timeout:
        await asyncio.sleep(10)

        agents = spawner.list_agents()
        running_panes = {a["pane_id"] for a in agents if a.get("status") == "running"}

        for job_id, pane_id in pane_map.items():
            if job_id not in completed and pane_id not in running_panes:
                completed.add(job_id)
                logger.info(f"Supervisor: sub-agent {job_id} completed")

    # Collect outputs
    for st in sub_tasks:
        job_id = f"sub_{st.id}"
        pane_id = pane_map.get(job_id)
        if pane_id:
            try:
                output = spawner.collect_output(pane_id, lines=2000, job_id=job_id)
                st.result = output
                st.status = "done" if "[AGENT_COMPLETED]" in (output or "") else "failed"
                st.pane_id = pane_id
            except Exception as e:
                st.result = f"Error collecting output: {e}"
                st.status = "failed"
        else:
            st.status = "failed"
            st.result = "Agent failed to spawn"

        st.duration_seconds = time.time() - start

    return sub_tasks


# ---------------------------------------------------------------------------
# Result synthesis
# ---------------------------------------------------------------------------

async def synthesize_results(
    original_task: str,
    sub_tasks: list[SubTask],
) -> dict:
    """Synthesize sub-agent results into a coherent final output.

    Cost: ~$0.001 (Grok grok-3-mini).
    """
    from grok_executor import call_grok

    sub_results = []
    for st in sub_tasks:
        # Truncate each result to avoid blowing context
        result_preview = (st.result or "No output")[:1000]
        sub_results.append(
            f"## Sub-task: {st.id} ({st.agent})\n"
            f"Status: {st.status}\n"
            f"Description: {st.description}\n"
            f"Output:\n{result_preview}\n"
        )

    synthesis_prompt = f"""You are synthesizing results from {len(sub_tasks)} parallel AI agents.

ORIGINAL TASK: {original_task}

SUB-TASK RESULTS:
{''.join(sub_results)}

Create a unified summary that:
1. Reports what was accomplished (or failed)
2. Lists any files changed
3. Notes any conflicts between sub-agent outputs
4. Gives a clear success/failure verdict

Be concise — 5-10 sentences max."""

    try:
        resp = await call_grok(
            prompt=synthesis_prompt,
            system_prompt="You synthesize multi-agent results concisely.",
            model="grok-3-mini",
            max_tokens=512,
            temperature=0.0,
        )
        summary = resp.get("text", "Synthesis failed")
    except Exception as e:
        summary = f"Synthesis error: {e}"

    succeeded = sum(1 for st in sub_tasks if st.status == "done")
    total = len(sub_tasks)

    return {
        "success": succeeded == total,
        "summary": summary,
        "sub_tasks_completed": succeeded,
        "sub_tasks_total": total,
        "sub_tasks": [
            {
                "id": st.id,
                "description": st.description,
                "agent": st.agent,
                "status": st.status,
                "duration_seconds": round(st.duration_seconds, 1),
            }
            for st in sub_tasks
        ],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def maybe_decompose_and_execute(
    job: dict,
    project_root: str = "/root/openclaw",
) -> Optional[dict]:
    """Check if a job should be decomposed and executed via supervisor pattern.

    Returns None if task shouldn't be decomposed (caller should use normal pipeline).
    Returns result dict if supervisor handled it.
    """
    task = job.get("task", "")
    project = job.get("project", "openclaw")
    job_id = job.get("id", "unknown")

    # Step 1: Fast complexity check
    complexity = detect_complexity(task)
    if not complexity["should_attempt"]:
        logger.debug(
            f"Job {job_id}: Supervisor skip — complexity {complexity['score']} "
            f"< threshold {DECOMPOSE_THRESHOLD}"
        )
        return None

    logger.info(
        f"Job {job_id}: Supervisor considering decomposition — "
        f"score={complexity['score']}, signals={complexity['signals']}"
    )

    # Step 2: LLM decomposition
    decomposition = await decompose_task(task, project)
    if not decomposition.should_decompose or len(decomposition.sub_tasks) < 2:
        logger.info(
            f"Job {job_id}: Supervisor decided NOT to decompose — {decomposition.reason}"
        )
        return None

    logger.info(
        f"Job {job_id}: Supervisor decomposing into {len(decomposition.sub_tasks)} "
        f"sub-tasks ({decomposition.execution_mode}), "
        f"estimated speedup: {decomposition.estimated_speedup}x"
    )

    # Step 3: Execute sub-tasks in parallel
    completed_tasks = await execute_parallel(
        decomposition.sub_tasks,
        project=project,
        project_root=project_root,
    )

    # Step 4: Synthesize results
    result = await synthesize_results(task, completed_tasks)
    result["supervisor"] = True
    result["decomposition"] = {
        "reason": decomposition.reason,
        "mode": decomposition.execution_mode,
        "estimated_speedup": decomposition.estimated_speedup,
        "complexity_score": complexity["score"],
        "complexity_signals": complexity["signals"],
    }

    return result
