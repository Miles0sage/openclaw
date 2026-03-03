"""
Agent Watchdog for OpenClaw
============================
Monitors running tmux agents for stalls, collects results from completed agents,
and reports status. Designed to run as a systemd service alongside the gateway.

Usage:
    python3 agent_watchdog.py              # Run once (check + report)
    python3 agent_watchdog.py --daemon     # Continuous polling loop
    python3 agent_watchdog.py --status     # Print agent status table

Architecture:
    - Polls tmux session "openclaw-agents" for active panes
    - Checks output file modification times to detect stalls
    - Kills stalled agents after STALL_TIMEOUT_SECS
    - Collects output from completed agents and updates job status
    - Sends Telegram alerts for completions and failures
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TMUX_SESSION = "openclaw-agents"
OUTPUT_DIR = "/tmp"
LOG_FILE = "/tmp/openclaw_watchdog.log"
STALL_TIMEOUT_SECS = 600  # 10 minutes without output = stalled
POLL_INTERVAL_SECS = 30   # check every 30 seconds in daemon mode
MAX_OUTPUT_TAIL = 50       # lines to include in completion reports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
logger = logging.getLogger("watchdog")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmux(*args) -> str:
    """Run a tmux command and return stdout."""
    try:
        result = subprocess.run(
            ["tmux"] + list(args),
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _session_exists() -> bool:
    """Check if the openclaw-agents tmux session exists."""
    out = _tmux("has-session", "-t", TMUX_SESSION)
    return subprocess.run(
        ["tmux", "has-session", "-t", TMUX_SESSION],
        capture_output=True,
    ).returncode == 0


def _list_windows() -> list[dict]:
    """List all windows in the tmux session with their pane IDs."""
    if not _session_exists():
        return []

    out = _tmux(
        "list-windows", "-t", TMUX_SESSION,
        "-F", "#{window_index}|#{window_name}|#{pane_id}|#{pane_pid}|#{pane_dead}",
    )
    windows = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 5:
            windows.append({
                "index": parts[0],
                "name": parts[1],
                "pane_id": parts[2],
                "pid": parts[3],
                "dead": parts[4] == "1",
            })
    return windows


def _get_job_id_from_window(name: str) -> str:
    """Extract job_id from window name like 'agent-abc123'."""
    if name.startswith("agent-"):
        return name[6:]
    return name


def _get_output_file(job_id: str) -> Path:
    """Get the output file path for a job."""
    return Path(f"{OUTPUT_DIR}/openclaw-output-{job_id}.txt")


def _get_output_mtime(job_id: str) -> float:
    """Get the last modification time of a job's output file."""
    path = _get_output_file(job_id)
    if path.exists():
        return path.stat().st_mtime
    return 0.0


def _get_output_tail(job_id: str, lines: int = MAX_OUTPUT_TAIL) -> str:
    """Get the last N lines of a job's output."""
    path = _get_output_file(job_id)
    if not path.exists():
        return "(no output file)"
    try:
        with open(path, "r", errors="replace") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except Exception as e:
        return f"(error reading output: {e})"


def _check_agent_completed(output: str) -> dict:
    """Check if agent output indicates completion/failure."""
    output_lower = output.lower()

    if "[agent_completed]" in output_lower:
        return {"status": "completed", "success": True}
    if "[agent_failed]" in output_lower:
        return {"status": "failed", "success": False}
    if "[agent_exit code=0" in output_lower:
        return {"status": "completed", "success": True}
    if "[agent_exit code=" in output_lower:
        return {"status": "failed", "success": False}

    return {"status": "running", "success": None}


def _send_telegram(message: str):
    """Send a Telegram notification."""
    try:
        from alerts import send_telegram
        send_telegram(message)
    except Exception:
        # Fallback: try direct API call
        try:
            from dotenv import load_dotenv
            load_dotenv("/root/openclaw/.env")
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if token and chat_id:
                import requests
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                    timeout=10,
                )
        except Exception:
            pass


def _update_job_status(job_id: str, status: str, result_summary: str = ""):
    """Update the job status in the job manager."""
    try:
        sys.path.insert(0, "/root/openclaw")
        from job_manager import update_job_status
        update_job_status(job_id, status)
        logger.info(f"Updated job {job_id} status to {status}")
    except Exception as e:
        logger.warning(f"Could not update job status for {job_id}: {e}")


# ---------------------------------------------------------------------------
# Core: check all agents
# ---------------------------------------------------------------------------

def check_agents() -> list[dict]:
    """
    Check all running agents. Returns a list of agent status dicts.
    Detects stalls, completions, and failures.
    """
    windows = _list_windows()
    agents = []
    now = time.time()

    for w in windows:
        job_id = _get_job_id_from_window(w["name"])
        output_file = _get_output_file(job_id)
        output_mtime = _get_output_mtime(job_id)
        stale_secs = now - output_mtime if output_mtime > 0 else 0

        output_tail = _get_output_tail(job_id, lines=30)
        completion = _check_agent_completed(output_tail)

        agent_info = {
            "job_id": job_id,
            "window": w["name"],
            "pane_id": w["pane_id"],
            "pid": w["pid"],
            "dead": w["dead"],
            "output_file": str(output_file),
            "output_exists": output_file.exists(),
            "output_size": output_file.stat().st_size if output_file.exists() else 0,
            "stale_secs": int(stale_secs),
            "status": completion["status"],
            "success": completion["success"],
        }

        # Detect stalls
        if (
            completion["status"] == "running"
            and not w["dead"]
            and stale_secs > STALL_TIMEOUT_SECS
        ):
            agent_info["status"] = "stalled"
            logger.warning(
                f"Agent {job_id} STALLED — no output for {int(stale_secs)}s "
                f"(threshold: {STALL_TIMEOUT_SECS}s)"
            )

        agents.append(agent_info)

    return agents


def handle_results(agents: list[dict], kill_stalled: bool = True):
    """
    Act on agent check results:
    - Kill stalled agents
    - Report completions/failures
    - Update job statuses
    """
    for agent in agents:
        job_id = agent["job_id"]

        if agent["status"] == "completed":
            logger.info(f"Agent {job_id} COMPLETED successfully")
            _update_job_status(job_id, "done")
            tail = _get_output_tail(job_id, lines=10)
            _send_telegram(f"*Agent Completed* `{job_id}`\n\nLast output:\n```\n{tail[:500]}\n```")

        elif agent["status"] == "failed":
            logger.warning(f"Agent {job_id} FAILED")
            _update_job_status(job_id, "failed")
            tail = _get_output_tail(job_id, lines=20)
            _send_telegram(f"*Agent Failed* `{job_id}`\n\nLast output:\n```\n{tail[:500]}\n```")

        elif agent["status"] == "stalled" and kill_stalled:
            logger.warning(f"KILLING stalled agent {job_id}")
            _tmux("kill-window", "-t", f"{TMUX_SESSION}:{agent['window']}")
            _update_job_status(job_id, "failed")
            _send_telegram(
                f"*Agent Stalled & Killed* `{job_id}`\n"
                f"No output for {agent['stale_secs']}s"
            )

        elif agent["dead"]:
            logger.info(f"Agent {job_id} pane is dead (already exited)")


def print_status():
    """Print a formatted status table of all agents."""
    agents = check_agents()
    if not agents:
        print("No agents running in tmux session.")
        return

    print(f"\n{'JOB ID':<25} {'STATUS':<12} {'OUTPUT SIZE':<12} {'STALE (s)':<10} {'PANE':<10}")
    print("─" * 70)
    for a in agents:
        status = a["status"].upper()
        if status == "STALLED":
            status = f"\033[91m{status}\033[0m"  # red
        elif status == "COMPLETED":
            status = f"\033[92m{status}\033[0m"  # green
        elif status == "FAILED":
            status = f"\033[93m{status}\033[0m"  # yellow

        size = f"{a['output_size'] / 1024:.1f}KB" if a['output_size'] else "0"
        print(f"{a['job_id']:<25} {status:<22} {size:<12} {a['stale_secs']:<10} {a['pane_id']:<10}")
    print()


def daemon_loop():
    """Continuous monitoring loop."""
    logger.info(f"Watchdog daemon started (poll={POLL_INTERVAL_SECS}s, stall={STALL_TIMEOUT_SECS}s)")
    while True:
        try:
            agents = check_agents()
            active = [a for a in agents if a["status"] == "running"]
            done = [a for a in agents if a["status"] in ("completed", "failed")]
            stalled = [a for a in agents if a["status"] == "stalled"]

            if agents:
                logger.info(
                    f"Agents: {len(active)} running, {len(done)} done, {len(stalled)} stalled "
                    f"(total: {len(agents)})"
                )

            handle_results(agents, kill_stalled=True)

        except Exception as e:
            logger.error(f"Watchdog error: {e}")

        time.sleep(POLL_INTERVAL_SECS)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="OpenClaw Agent Watchdog")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    parser.add_argument("--status", action="store_true", help="Print agent status table")
    parser.add_argument("--once", action="store_true", help="Check once and exit (default)")
    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.daemon:
        daemon_loop()
    else:
        agents = check_agents()
        handle_results(agents)
        if agents:
            print_status()
        else:
            print("No agents running.")


if __name__ == "__main__":
    main()
