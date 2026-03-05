#!/usr/bin/env python3
"""
Daily Digest for Miles — Sends a consolidated Telegram message.

Usage:
  python3 daily_digest.py noon      # 12:00 digest (lightweight: schedule, jobs, costs)
  python3 daily_digest.py preshift   # 4:30pm brief (full: + betting picks, project status, AI news)

Cron:
  0 12 * * * /usr/bin/python3 /root/openclaw/scripts/daily_digest.py noon
  30 16 * * * /usr/bin/python3 /root/openclaw/scripts/daily_digest.py preshift
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone

# Load .env
from pathlib import Path
env_path = Path("/root/openclaw/.env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID", "")
GATEWAY = "http://localhost:18789"
AUTH_TOKEN = os.getenv("GATEWAY_AUTH_TOKEN", "")


def tg_send(text: str):
    """Send message to Miles via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_USER_ID:
        print(f"[SKIP] No Telegram credentials. Message:\n{text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Split into chunks if needed
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            resp = requests.post(url, json={
                "chat_id": TELEGRAM_USER_ID,
                "text": chunk,
                "parse_mode": "HTML",
            }, timeout=10)
            if resp.status_code != 200:
                # Retry without HTML
                requests.post(url, json={
                    "chat_id": TELEGRAM_USER_ID,
                    "text": chunk,
                }, timeout=10)
        except Exception as e:
            print(f"[ERROR] Telegram send: {e}")


def gw_get(path: str, timeout: int = 10) -> dict:
    """GET from gateway with auth."""
    try:
        headers = {"X-Auth-Token": AUTH_TOKEN} if AUTH_TOKEN else {}
        r = requests.get(f"{GATEWAY}{path}", headers=headers, timeout=timeout)
        return r.json() if r.ok else {}
    except Exception:
        return {}


def get_schedule() -> str:
    """Miles' schedule context."""
    now = datetime.now()
    day = now.strftime("%A")
    date = now.strftime("%Y-%m-%d")

    if day == "Monday":
        return f"<b>{day} {date}</b> — Day OFF\nBest for: big tasks, planning, Claude sessions"

    notes = []
    if day == "Thursday":
        notes.append("Soccer at 9:20pm")
    notes_str = f"\n{chr(10).join(notes)}" if notes else ""

    return f"<b>{day} {date}</b> — Work 5pm-10pm{notes_str}"


def get_jobs_summary() -> str:
    """Job queue summary."""
    data = gw_get("/api/jobs?status=all")
    jobs = data.get("jobs", [])
    if not jobs:
        return "No jobs in queue"

    pending = sum(1 for j in jobs if j.get("status") in ("pending", "analyzing"))
    running = sum(1 for j in jobs if j.get("status") in ("running", "in_progress"))
    done = sum(1 for j in jobs if j.get("status") == "done")
    failed = sum(1 for j in jobs if j.get("status") == "failed")

    parts = []
    if pending: parts.append(f"{pending} pending")
    if running: parts.append(f"{running} running")
    if done: parts.append(f"{done} done")
    if failed: parts.append(f"{failed} failed")

    return " | ".join(parts) if parts else "Queue empty"


def get_costs() -> str:
    """Cost summary."""
    data = gw_get("/api/costs/summary")
    if not data:
        return "Cost data unavailable"
    today = data.get("today_usd", 0)
    month = data.get("month_usd", 0)
    return f"${today:.2f} today | ${month:.2f} this month"


def get_betting_picks() -> str:
    """Get today's betting recommendations."""
    try:
        sys.path.insert(0, "/root/openclaw")
        from sports_model import sports_betting
        result = sports_betting(action="recommend", sport="basketball_nba", bankroll=100, min_ev=0.02, limit=5)
        if isinstance(result, str):
            data = json.loads(result)
        else:
            data = result

        bets = data.get("recommendations", [])
        if not bets:
            return "No +EV bets found today"

        lines = []
        for b in bets[:5]:
            team = b.get("team", "?")
            ev = b.get("edge_pct", b.get("ev", 0))
            book = b.get("best_book", b.get("sportsbook", "?"))
            odds = b.get("best_odds", b.get("odds", "?"))
            lines.append(f"  {team} @ {book} ({odds}) +{ev:.1f}% EV")
        return "\n".join(lines)
    except Exception as e:
        return f"Betting picks unavailable: {str(e)[:80]}"


def get_project_status() -> str:
    """Quick project status from known paths."""
    projects = [
        ("/root/openclaw", "OpenClaw"),
        ("/root/Delhi-Palace", "Delhi Palace"),
        ("/root/Barber-CRM", "Barber CRM"),
    ]
    lines = []
    for path, name in projects:
        if os.path.isdir(path):
            try:
                import subprocess
                result = subprocess.run(
                    ["git", "log", "--oneline", "-1", "--format=%h %s (%cr)"],
                    cwd=path, capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    lines.append(f"  {name}: {result.stdout.strip()}")
                else:
                    lines.append(f"  {name}: (no git)")
            except Exception:
                lines.append(f"  {name}: exists")
    return "\n".join(lines) if lines else "No project data"


def get_ai_news_brief() -> str:
    """Quick AI news highlights."""
    try:
        sys.path.insert(0, "/root/openclaw")
        from agent_tools import _read_ai_news
        result = _read_ai_news(limit=3, source=None, hours=24)
        if isinstance(result, str) and len(result) > 20:
            # Truncate to fit
            return result[:500]
        return "No recent AI news"
    except Exception:
        return "AI news unavailable"


def build_noon_digest() -> str:
    """Lightweight noon digest."""
    parts = [
        "<b>Daily Digest</b>",
        "",
        get_schedule(),
        "",
        f"<b>Jobs:</b> {get_jobs_summary()}",
        f"<b>Costs:</b> {get_costs()}",
    ]
    return "\n".join(parts)


def build_preshift_brief() -> str:
    """Full pre-shift brief at 4:30pm."""
    parts = [
        "<b>Pre-Shift Brief</b>",
        "",
        get_schedule(),
        "",
        f"<b>Jobs:</b> {get_jobs_summary()}",
        f"<b>Costs:</b> {get_costs()}",
        "",
        "<b>Betting Picks:</b>",
        get_betting_picks(),
        "",
        "<b>Projects:</b>",
        get_project_status(),
        "",
        "<b>AI News:</b>",
        get_ai_news_brief(),
    ]
    return "\n".join(parts)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "noon"
    no_send = "--no-send" in sys.argv

    if mode == "preshift":
        msg = build_preshift_brief()
    else:
        msg = build_noon_digest()

    print(msg)
    if not no_send:
        tg_send(msg)
        print("\n[OK] Digest sent to Telegram")
    else:
        print("\n[OK] --no-send: printed only")
