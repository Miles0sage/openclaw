"""
Workflow Checkpoint System for OpenClaw
========================================
Saves execution state after each successful tool call so jobs can resume
from where they left off instead of restarting from scratch.

SQLite with WAL mode for concurrent access. Checkpoints are keyed by
(job_id, phase, step_index) and store the full state + last N messages.

Usage:
    save_checkpoint(job_id, phase, step_index, tool_iteration, state, messages)
    cp = get_latest_checkpoint(job_id)
    clear_checkpoints(job_id)

Expected gain: 30-40% cost reduction on failed jobs (resume instead of restart).
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("checkpoint")

DATA_DIR = os.environ.get("OPENCLAW_DATA_DIR", "/root/openclaw/data")
DB_PATH = os.path.join(DATA_DIR, "checkpoints.db")


def _get_conn() -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode enabled."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection):
    """Create the checkpoints table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            phase TEXT NOT NULL,
            step_index INTEGER NOT NULL DEFAULT 0,
            tool_iteration INTEGER NOT NULL DEFAULT 0,
            state_json TEXT NOT NULL,
            messages_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_checkpoints_job
        ON checkpoints(job_id, created_at DESC)
    """)
    conn.commit()


def save_checkpoint(
    job_id: str,
    phase: str,
    step_index: int,
    tool_iteration: int,
    state: dict,
    messages: list = None,
):
    """
    Save a checkpoint after a successful tool execution.

    Args:
        job_id: The job being executed
        phase: Current phase (research, plan, execute, verify, deliver)
        step_index: Current step index within the phase
        tool_iteration: Tool loop iteration count
        state: Full execution state dict (progress, plan steps, research, etc.)
        messages: Last N conversation messages (for context resumption)
    """
    conn = _get_conn()
    try:
        _ensure_table(conn)

        # Keep only last 10 messages to limit checkpoint size
        trimmed_messages = messages[-10:] if messages else []

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO checkpoints
               (job_id, phase, step_index, tool_iteration, state_json, messages_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                phase,
                step_index,
                tool_iteration,
                json.dumps(state, default=str),
                json.dumps(trimmed_messages, default=str),
                now,
            ),
        )
        conn.commit()
        logger.debug(
            f"Checkpoint saved: job={job_id} phase={phase} "
            f"step={step_index} iter={tool_iteration}"
        )
    except Exception as e:
        logger.warning(f"Failed to save checkpoint for {job_id}: {e}")
    finally:
        conn.close()


def get_latest_checkpoint(job_id: str) -> dict | None:
    """
    Get the most recent checkpoint for a job.

    Returns:
        dict with keys: job_id, phase, step_index, tool_iteration,
        state (dict), messages (list), created_at
        or None if no checkpoint exists.
    """
    conn = _get_conn()
    try:
        _ensure_table(conn)
        row = conn.execute(
            """SELECT * FROM checkpoints
               WHERE job_id = ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (job_id,),
        ).fetchone()

        if not row:
            return None

        return {
            "job_id": row["job_id"],
            "phase": row["phase"],
            "step_index": row["step_index"],
            "tool_iteration": row["tool_iteration"],
            "state": json.loads(row["state_json"]),
            "messages": json.loads(row["messages_json"]) if row["messages_json"] else [],
            "created_at": row["created_at"],
        }
    except Exception as e:
        logger.warning(f"Failed to get checkpoint for {job_id}: {e}")
        return None
    finally:
        conn.close()


def clear_checkpoints(job_id: str):
    """Remove all checkpoints for a completed/cancelled job."""
    conn = _get_conn()
    try:
        _ensure_table(conn)
        conn.execute("DELETE FROM checkpoints WHERE job_id = ?", (job_id,))
        conn.commit()
        logger.debug(f"Checkpoints cleared for job {job_id}")
    except Exception as e:
        logger.warning(f"Failed to clear checkpoints for {job_id}: {e}")
    finally:
        conn.close()


def list_checkpoints(job_id: str = None) -> list:
    """List checkpoints, optionally filtered by job_id. Returns summary dicts."""
    conn = _get_conn()
    try:
        _ensure_table(conn)
        if job_id:
            rows = conn.execute(
                """SELECT job_id, phase, step_index, tool_iteration, created_at
                   FROM checkpoints WHERE job_id = ? ORDER BY created_at DESC""",
                (job_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT job_id, phase, step_index, tool_iteration, created_at
                   FROM checkpoints ORDER BY created_at DESC LIMIT 50"""
            ).fetchall()

        return [dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"Failed to list checkpoints: {e}")
        return []
    finally:
        conn.close()


def count_checkpoints(job_id: str) -> int:
    """Count checkpoints for a job."""
    conn = _get_conn()
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM checkpoints WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0
    finally:
        conn.close()
