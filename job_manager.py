"""
Autonomous Job Queue Manager for OpenClaw
Manages job lifecycle: pending → analyzing → pr_created → approved → merged
"""

import json
import os
import uuid
from datetime import datetime
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
        self.id = f"job-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"
        self.project = project
        self.task = task
        self.priority = priority
        self.status = "pending"  # pending → analyzing → code_generated → pr_created → approved → merged → done
        self.created_at = datetime.utcnow().isoformat()
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

def create_job(project: str, task: str, priority: str = "P1") -> Job:
    """Create a new job and add to queue"""
    job = Job(project, task, priority)
    
    # Append to jobs file
    with open(JOBS_FILE, "a") as f:
        f.write(json.dumps(job.to_dict()) + "\n")
    
    logger.info(f"✅ Job created: {job.id} - {task}")
    return job

def get_job(job_id: str) -> dict:
    """Get job by ID"""
    if not JOBS_FILE.exists():
        return None
    
    with open(JOBS_FILE, "r") as f:
        for line in f:
            job = json.loads(line)
            if job["id"] == job_id:
                return job
    return None

def get_pending_jobs(limit: int = 10):
    """Get pending jobs up to the given limit (default 10)."""
    if not JOBS_FILE.exists():
        return []

    jobs = []
    with open(JOBS_FILE, "r") as f:
        for line in f:
            job = json.loads(line)
            if job["status"] == "pending":
                jobs.append(job)
                if len(jobs) >= limit:
                    break

    return jobs

def update_job_status(job_id: str, status: str, **kwargs):
    """Update job status"""
    if not JOBS_FILE.exists():
        return
    
    jobs = []
    with open(JOBS_FILE, "r") as f:
        for line in f:
            job = json.loads(line)
            if job["id"] == job_id:
                job["status"] = status
                for key, value in kwargs.items():
                    job[key] = value
                if status in ["approved", "merged", "done"]:
                    job["completed_at"] = datetime.utcnow().isoformat()
            jobs.append(job)
    
    # Rewrite file
    with open(JOBS_FILE, "w") as f:
        for job in jobs:
            f.write(json.dumps(job) + "\n")
    
    logger.info(f"✅ Job {job_id} → {status}")

def list_jobs(status: str = "all"):
    """List jobs, optionally filtered by status.

    Args:
        status: Filter by job status (e.g. 'pending', 'done', 'analyzing').
                Use 'all' to return everything (default).
    """
    if not JOBS_FILE.exists():
        return []

    jobs = []
    with open(JOBS_FILE, "r") as f:
        for line in f:
            jobs.append(json.loads(line))

    if status != "all":
        jobs = [j for j in jobs if j.get("status") == status]

    return jobs

if __name__ == "__main__":
    # Test
    job = create_job("barber-crm", "Fix RLS vulnerabilities", "P0")
    print(f"Created job: {job.id}")
