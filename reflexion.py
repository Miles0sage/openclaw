"""
OpenClaw Reflexion Loop — Self-improving agent memory

After each job, stores a reflection. Before new jobs, injects relevant past reflections.
"""
import os
import json
import glob
from datetime import datetime
from pathlib import Path

REFLECTIONS_DIR = Path("/root/openclaw/data/reflections")


def ensure_dir():
    REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)


def save_reflection(job_id: str, job_data: dict, outcome: str, duration_seconds: float = 0):
    """Save a post-job reflection. Called after job completes."""
    ensure_dir()

    reflection = {
        "job_id": job_id,
        "project": job_data.get("project", "unknown"),
        "task": job_data.get("task", ""),
        "outcome": outcome,  # "success" or "failed"
        "duration_seconds": duration_seconds,
        "timestamp": datetime.utcnow().isoformat(),
        "tags": list(_extract_tags(job_data.get("task", ""))),
    }

    # Generate reflection prompt
    if outcome == "success":
        reflection["learnings"] = [
            f"Task '{job_data.get('task', '')[:100]}' completed successfully",
            f"Project: {job_data.get('project', 'unknown')}",
            f"Duration: {duration_seconds:.0f}s",
        ]
    else:
        reflection["learnings"] = [
            f"Task '{job_data.get('task', '')[:100]}' FAILED",
            f"Project: {job_data.get('project', 'unknown')}",
            "Review logs for error details",
        ]

    filepath = REFLECTIONS_DIR / f"{job_id}.json"
    with open(filepath, "w") as f:
        json.dump(reflection, f, indent=2)

    return filepath


def search_reflections(task_description: str, project: str = None, limit: int = 3) -> list:
    """Find relevant past reflections for a new task. Used to inject context before jobs."""
    ensure_dir()

    tags = _extract_tags(task_description)
    all_reflections = []

    for filepath in REFLECTIONS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                ref = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        # Score relevance
        score = 0
        ref_tags = set(ref.get("tags", []))
        score += len(tags & ref_tags) * 2  # tag overlap

        if project and ref.get("project") == project:
            score += 3  # same project bonus

        # Keyword overlap in task description
        task_words = set(task_description.lower().split())
        ref_words = set(ref.get("task", "").lower().split())
        score += len(task_words & ref_words)

        if score > 0:
            ref["_relevance_score"] = score
            all_reflections.append(ref)

    # Sort by relevance, then recency
    all_reflections.sort(key=lambda r: (r["_relevance_score"], r.get("timestamp", "")), reverse=True)

    return all_reflections[:limit]


def format_reflections_for_prompt(reflections: list) -> str:
    """Format reflections as context to inject into agent prompts."""
    if not reflections:
        return ""

    lines = ["## Past Experience (from similar tasks)"]
    for ref in reflections:
        outcome_label = "SUCCESS" if ref.get("outcome") == "success" else "FAILED"
        lines.append(f"\n### [{outcome_label}] {ref.get('task', 'Unknown task')[:120]}")
        lines.append(f"Project: {ref.get('project', '?')} | Duration: {ref.get('duration_seconds', 0):.0f}s")
        for learning in ref.get("learnings", []):
            lines.append(f"- {learning}")

    lines.append("\nUse these past experiences to inform your approach. Avoid repeating past failures.")
    return "\n".join(lines)


def get_stats() -> dict:
    """Get reflection statistics."""
    ensure_dir()
    total = 0
    successes = 0
    failures = 0

    for filepath in REFLECTIONS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                ref = json.load(f)
            total += 1
            if ref.get("outcome") == "success":
                successes += 1
            else:
                failures += 1
        except Exception:
            continue

    return {
        "total_reflections": total,
        "successes": successes,
        "failures": failures,
        "success_rate": f"{successes/total*100:.1f}%" if total > 0 else "N/A",
    }


def list_reflections(project: str = None, limit: int = 50) -> list:
    """List all reflections, optionally filtered by project."""
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
