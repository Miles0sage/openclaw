"""
Autonomous Job Queue Manager for OpenClaw
Manages job lifecycle: pending → analyzing → pr_created → approved → merged
"""

import fcntl
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import logging

logger = logging.getLogger("job_manager")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data")
JOBS_DIR = Path(os.path.join(DATA_DIR, "jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_FILE = JOBS_DIR / "jobs.jsonl"

class Job:
    def __init__(self, project: str, task: str, priority: str = "P1"):
        self.id = f"job-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
        self.project = project
        self.task = task
        self.priority = priority
        self.status = "pending"  # pending → analyzing → code_generated → pr_created → approved → merged → done
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


VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_PROJECTS = {
    "barber-crm", "openclaw", "delhi-palace",
    "prestress-calc", "concrete-canoe",
}


class JobValidationError(ValueError):
    """Raised when job input fails validation."""
    pass


def validate_job(project: str, task: str, priority: str = "P1") -> None:
    """Validate job inputs. Raises JobValidationError on bad input.

    Checks:
        - task is non-empty and <= 5000 chars
        - priority is one of P0-P3
        - project is a known project name
    """
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


def create_job(project: str, task: str, priority: str = "P1") -> Job:
    """Create a new job and add to queue. Validates inputs first."""
    validate_job(project, task, priority)
    job = Job(project, task, priority)
    _locked_append_job(job.to_dict())
    logger.info(f"Job created: {job.id} - {task}")
    return job

def get_job(job_id: str) -> dict:
    """Get job by ID"""
    for job in _locked_read_jobs():
        if job["id"] == job_id:
            return job
    return None


def get_pending_jobs(limit: int = 10):
    """Get pending jobs up to the given limit (default 10)."""
    jobs = []
    for job in _locked_read_jobs():
        if job["status"] == "pending":
            jobs.append(job)
            if len(jobs) >= limit:
                break
    return jobs


def update_job_status(job_id: str, status: str, **kwargs):
    """Update job status with file locking to prevent corruption."""
    if not JOBS_FILE.exists():
        return

    # Exclusive lock for read-modify-write
    with open(JOBS_FILE, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            jobs = [json.loads(line) for line in f if line.strip()]
            for job in jobs:
                if job["id"] == job_id:
                    job["status"] = status
                    for key, value in kwargs.items():
                        job[key] = value
                    if status in ["approved", "merged", "done"]:
                        job["completed_at"] = datetime.now(timezone.utc).isoformat()
            f.seek(0)
            f.truncate()
            for job in jobs:
                f.write(json.dumps(job) + "\n")
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

    logger.info(f"Job {job_id} -> {status}")


def list_jobs(status: str = "all"):
    """List jobs, optionally filtered by status.

    Args:
        status: Filter by job status (e.g. 'pending', 'done', 'analyzing').
                Use 'all' to return everything (default).
    """
    jobs = _locked_read_jobs()
    if status != "all":
        jobs = [j for j in jobs if j.get("status") == status]
    return jobs

if __name__ == "__main__":
    # Test
    job = create_job("barber-crm", "Fix RLS vulnerabilities", "P0")
    print(f"Created job: {job.id}")
