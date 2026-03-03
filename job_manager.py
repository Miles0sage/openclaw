"""
Autonomous Job Queue Manager for OpenClaw
==========================================
Manages job lifecycle: pending -> analyzing -> code_generated -> pr_ready -> done
Primary backend: Supabase (real-time, queryable, multi-device)
Fallback: JSONL file (if Supabase is unreachable)
"""

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
import logging

logger = logging.getLogger("job_manager")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data")
JOBS_DIR = Path(os.path.join(DATA_DIR, "jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = JOBS_DIR / "jobs.jsonl"

# ---------------------------------------------------------------------------
# Supabase backend
# ---------------------------------------------------------------------------

def _sb():
    """Lazy import supabase_client to avoid circular imports."""
    try:
        from supabase_client import table_insert, table_select, table_update, table_delete, is_connected
        return {
            "insert": table_insert,
            "select": table_select,
            "update": table_update,
            "delete": table_delete,
            "connected": is_connected,
        }
    except Exception:
        return None


def _use_supabase() -> bool:
    """Check if Supabase is available and connected."""
    try:
        sb = _sb()
        return sb is not None and sb["connected"]()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JSONL fallback (kept for resilience)
# ---------------------------------------------------------------------------

def _locked_read_jobs() -> list:
    """Read all jobs from JSONL with file locking."""
    if not JOBS_FILE.exists():
        return []
    with open(JOBS_FILE, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return [json.loads(line) for line in f if line.strip()]
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _locked_write_jobs(jobs: list):
    """Write all jobs to JSONL with exclusive file locking."""
    with open(JOBS_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            for job in jobs:
                f.write(json.dumps(job) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _locked_append_job(job_dict: dict):
    """Append a single job to JSONL with exclusive file locking."""
    with open(JOBS_FILE, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(json.dumps(job_dict) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_PROJECTS = {
    "barber-crm", "openclaw", "delhi-palace",
    "prestress-calc", "concrete-canoe",
}


class JobValidationError(ValueError):
    """Raised when job input fails validation."""
    pass


def validate_job(project: str, task: str, priority: str = "P1") -> None:
    """Validate job inputs. Raises JobValidationError on bad input."""
    if not task or not task.strip():
        raise JobValidationError("Task description cannot be empty")
    if len(task) > 5000:
        raise JobValidationError(f"Task too long ({len(task)} chars, max 5000)")
    if priority not in VALID_PRIORITIES:
        raise JobValidationError(f"Invalid priority '{priority}', must be one of {VALID_PRIORITIES}")
    if project and project not in VALID_PROJECTS:
        raise JobValidationError(
            f"Unknown project '{project}', must be one of {VALID_PROJECTS}"
        )


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, project: str, task: str, priority: str = "P1"):
        self.id = f"job-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
        self.project = project
        self.task = task
        self.priority = priority
        self.status = "pending"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.pr_url = None
        self.branch_name = None
        self.approved_by = None
        self.completed_at = None
        self.analysis = {}
        self.generated_code = {}

    def to_dict(self):
        return {
            "id": self.id,
            "project": self.project,
            "task": self.task,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at,
            "pr_url": self.pr_url,
            "branch_name": self.branch_name,
            "approved_by": self.approved_by,
            "completed_at": self.completed_at,
        }


# ---------------------------------------------------------------------------
# CRUD operations (Supabase-first, JSONL fallback)
# ---------------------------------------------------------------------------

def create_job(project: str, task: str, priority: str = "P1") -> Job:
    """Create a new job and add to queue."""
    validate_job(project, task, priority)
    job = Job(project, task, priority)
    job_dict = job.to_dict()

    if _use_supabase():
        sb = _sb()
        result = sb["insert"]("jobs", {
            "id": job_dict["id"],
            "project": job_dict["project"],
            "task": job_dict["task"],
            "priority": job_dict["priority"],
            "status": job_dict["status"],
            "created_at": job_dict["created_at"],
        })
        if result:
            logger.info(f"Job created (Supabase): {job.id}")
        else:
            logger.warning(f"Supabase insert failed, falling back to JSONL")
            _locked_append_job(job_dict)
    else:
        _locked_append_job(job_dict)
        logger.info(f"Job created (JSONL): {job.id}")

    return job


def get_job(job_id: str) -> dict:
    """Get job by ID."""
    if _use_supabase():
        sb = _sb()
        rows = sb["select"]("jobs", f"id=eq.{job_id}", limit=1)
        if rows:
            return rows[0]
    # Fallback
    for job in _locked_read_jobs():
        if job["id"] == job_id:
            return job
    return None


def get_pending_jobs(limit: int = 10):
    """Get pending jobs, ordered by priority then creation time.

    Merges results from Supabase AND local JSONL to catch jobs that
    were created in either store (MCP subprocess may not have Supabase).
    """
    seen_ids = set()
    jobs = []

    # Check Supabase first
    if _use_supabase():
        sb = _sb()
        rows = sb["select"](
            "jobs",
            "status=eq.pending&order=priority.asc,created_at.asc",
            limit=limit,
        )
        if rows:
            for r in rows:
                seen_ids.add(r["id"])
                jobs.append(r)

    # Also check JSONL (catches jobs not in Supabase)
    for job in _locked_read_jobs():
        if job["status"] == "pending" and job["id"] not in seen_ids:
            jobs.append(job)
            if len(jobs) >= limit:
                break

    return jobs[:limit]


def update_job_status(job_id: str, status: str, **kwargs):
    """Update job status."""
    now = datetime.now(timezone.utc).isoformat()
    updates = {"status": status, "updated_at": now}
    updates.update(kwargs)

    if status in ("approved", "merged", "done"):
        updates["completed_at"] = now
    if status == "analyzing":
        updates["started_at"] = now

    if _use_supabase():
        sb = _sb()
        result = sb["update"]("jobs", f"id=eq.{job_id}", updates)
        if result:
            logger.info(f"Job {job_id} -> {status} (Supabase)")
            return
        logger.warning(f"Supabase update failed for {job_id}, falling back to JSONL")

    # JSONL fallback
    if not JOBS_FILE.exists():
        return
    with open(JOBS_FILE, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            jobs = [json.loads(line) for line in f if line.strip()]
            for job in jobs:
                if job["id"] == job_id:
                    job.update(updates)
            f.seek(0)
            f.truncate()
            for job in jobs:
                f.write(json.dumps(job) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    logger.info(f"Job {job_id} -> {status} (JSONL)")


def list_jobs(status: str = "all"):
    """List jobs, optionally filtered by status."""
    if _use_supabase():
        sb = _sb()
        query = "order=created_at.desc"
        if status != "all":
            query = f"status=eq.{status}&{query}"
        rows = sb["select"]("jobs", query, limit=200)
        if rows is not None:
            return rows

    # Fallback
    jobs = _locked_read_jobs()
    if status != "all":
        jobs = [j for j in jobs if j.get("status") == status]
    return jobs


def set_kill_flag(job_id: str) -> bool:
    """Set kill flag on a job (used by kill_job MCP tool)."""
    update_job_status(job_id, "killed_manual")
    return True


if __name__ == "__main__":
    job = create_job("openclaw", "Test Supabase job manager", "P3")
    print(f"Created job: {job.id}")
    fetched = get_job(job.id)
    print(f"Fetched: {fetched['id']} status={fetched['status']}")
    update_job_status(job.id, "done")
    fetched = get_job(job.id)
    print(f"After update: status={fetched['status']}")
