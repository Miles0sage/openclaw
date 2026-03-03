"""
OpenClaw Reflexion Loop — Self-improving agent memory

After each job, stores a reflection. Before new jobs, injects relevant past reflections.
Primary backend: Supabase | Fallback: JSON files on disk
"""
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("reflexion")

REFLECTIONS_DIR = Path("/root/openclaw/data/reflections")


def ensure_dir():
    REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def _sb():
    try:
        from supabase_client import table_insert, table_select, is_connected
        return {"insert": table_insert, "select": table_select, "connected": is_connected}
    except Exception:
        return None


def _use_supabase() -> bool:
    try:
        sb = _sb()
        return sb is not None and sb["connected"]()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def save_reflection(job_id: str, job_data: dict, outcome: str, duration_seconds: float = 0, department: str = ""):
    """Save a post-job reflection. Called after job completes."""
    ensure_dir()

    tags = list(_extract_tags(job_data.get("task", "")))

    if outcome == "success":
        learnings = [
            f"Task '{job_data.get('task', '')[:100]}' completed successfully",
            f"Project: {job_data.get('project', 'unknown')}",
            f"Duration: {duration_seconds:.0f}s",
        ]
    else:
        learnings = [
            f"Task '{job_data.get('task', '')[:100]}' FAILED",
            f"Project: {job_data.get('project', 'unknown')}",
            "Review logs for error details",
        ]

    reflection = {
        "job_id": job_id,
        "project": job_data.get("project", "unknown"),
        "task": job_data.get("task", ""),
        "outcome": outcome,
        "department": department,
        "duration_seconds": duration_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": tags,
        "learnings": learnings,
    }

    # Try Supabase first
    if _use_supabase():
        sb = _sb()
        row = {
            "job_id": job_id,
            "project": reflection["project"],
            "task": reflection["task"],
            "outcome": outcome,
            "department": department,
            "reflection": json.dumps(learnings),
            "lessons": learnings,
            "cost_usd": job_data.get("cost_usd", 0),
            "duration_seconds": int(duration_seconds),
            "created_at": reflection["timestamp"],
        }
        result = sb["insert"]("reflections", row)
        if result:
            logger.info(f"Reflection saved (Supabase): {job_id} [dept={department}]")
            return job_id

    # JSON file fallback
    filepath = REFLECTIONS_DIR / f"{job_id}.json"
    with open(filepath, "w") as f:
        json.dump(reflection, f, indent=2)
    logger.info(f"Reflection saved (file): {filepath} [dept={department}]")
    return filepath


def search_reflections(task_description: str, project: str = None, department: str = None, limit: int = 3) -> list:
    """Find relevant past reflections for a new task.

    When department is specified, prioritizes same-department reflections
    and pads with cross-department results.
    """

    # Try Supabase first — get all reflections and score locally
    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if project:
            query = f"project=eq.{project}&{query}"
        rows = sb["select"]("reflections", query, limit=200)
        if rows:
            return _score_and_rank(rows, task_description, project, limit, department=department)

    # File fallback
    ensure_dir()
    all_reflections = []
    for filepath in REFLECTIONS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                ref = json.load(f)
            all_reflections.append(ref)
        except (json.JSONDecodeError, IOError):
            continue

    return _score_and_rank(all_reflections, task_description, project, limit, department=department)


def _score_and_rank(reflections: list, task_description: str, project: str, limit: int, department: str = None) -> list:
    """Score reflections by relevance to a task and return top matches.

    When department is specified, same-department reflections get a bonus
    and are prioritized in the results.
    """
    tags = _extract_tags(task_description)
    scored = []

    for ref in reflections:
        score = 0
        # Tag overlap (Supabase rows use 'lessons' array, file rows use 'tags')
        ref_tags = set(ref.get("tags", []) or [])
        if not ref_tags:
            ref_tags = _extract_tags(ref.get("task", ""))
        score += len(tags & ref_tags) * 2

        if project and ref.get("project") == project:
            score += 3

        # Department bonus: same-department reflections are more relevant
        if department and ref.get("department") == department:
            score += 4

        task_words = set(task_description.lower().split())
        ref_words = set(ref.get("task", "").lower().split())
        score += len(task_words & ref_words)

        if score > 0:
            ref["_relevance_score"] = score
            # Normalize learnings field
            if "learnings" not in ref and "lessons" in ref:
                ref["learnings"] = ref["lessons"]
            scored.append(ref)

    scored.sort(key=lambda r: (r.get("_relevance_score", 0), r.get("timestamp", r.get("created_at", ""))), reverse=True)

    # When department is set, ensure same-department results come first
    if department:
        dept_results = [r for r in scored if r.get("department") == department]
        other_results = [r for r in scored if r.get("department") != department]
        return (dept_results + other_results)[:limit]

    return scored[:limit]


def format_reflections_for_prompt(reflections: list) -> str:
    """Format reflections as context to inject into agent prompts."""
    if not reflections:
        return ""

    lines = ["## Past Experience (from similar tasks)"]
    for ref in reflections:
        outcome_label = "SUCCESS" if ref.get("outcome") == "success" else "FAILED"
        lines.append(f"\n### [{outcome_label}] {ref.get('task', 'Unknown task')[:120]}")
        dur = ref.get("duration_seconds", 0)
        lines.append(f"Project: {ref.get('project', '?')} | Duration: {dur:.0f}s" if dur else f"Project: {ref.get('project', '?')}")
        for learning in ref.get("learnings", ref.get("lessons", [])):
            lines.append(f"- {learning}")

    lines.append("\nUse these past experiences to inform your approach. Avoid repeating past failures.")
    return "\n".join(lines)


def get_stats() -> dict:
    """Get reflection statistics."""
    if _use_supabase():
        sb = _sb()
        rows = sb["select"]("reflections", "", limit=5000)
        if rows is not None:
            total = len(rows)
            successes = sum(1 for r in rows if r.get("outcome") == "success")
            failures = total - successes
            return {
                "total_reflections": total,
                "successes": successes,
                "failures": failures,
                "success_rate": f"{successes/total*100:.1f}%" if total > 0 else "N/A",
            }

    # File fallback
    ensure_dir()
    total = 0
    successes = 0
    for filepath in REFLECTIONS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                ref = json.load(f)
            total += 1
            if ref.get("outcome") == "success":
                successes += 1
        except Exception:
            continue

    return {
        "total_reflections": total,
        "successes": successes,
        "failures": total - successes,
        "success_rate": f"{successes/total*100:.1f}%" if total > 0 else "N/A",
    }


def list_reflections(project: str = None, limit: int = 50) -> list:
    """List all reflections, optionally filtered by project."""
    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if project:
            query = f"project=eq.{project}&{query}"
        rows = sb["select"]("reflections", query, limit=limit)
        if rows is not None:
            return rows

    # File fallback
    ensure_dir()
    results = []
    for filepath in sorted(REFLECTIONS_DIR.glob("*.json"), reverse=True):
        try:
            with open(filepath) as f:
                ref = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue
        if project and ref.get("project") != project:
            continue
        results.append(ref)
        if len(results) >= limit:
            break
    return results


def _extract_tags(text: str) -> set:
    """Extract relevant tags from task text for matching."""
    tag_keywords = {
        "deploy", "vercel", "supabase", "database", "sql", "api", "endpoint",
        "frontend", "backend", "css", "tailwind", "react", "next", "nextjs",
        "bug", "fix", "refactor", "test", "security", "audit", "pentest",
        "docker", "git", "ci", "cd", "pipeline", "build", "install",
        "auth", "login", "signup", "email", "notification", "slack",
        "performance", "optimize", "cache", "migration", "schema",
        "component", "page", "route", "middleware", "hook",
        "openclaw", "delhi", "barber", "prestress", "canoe",
    }
    words = set(text.lower().split())
    return words & tag_keywords
