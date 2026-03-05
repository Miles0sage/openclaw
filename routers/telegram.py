"""
Telegram webhook router for OpenClaw gateway.

Provides two Telegram bots:
1. Main Telegram bot — Personal Assistant for Miles (schedule, projects, betting, tools)
2. CoderClaw bot — Dedicated Claude Code controller with persistent sessions

Features:
- PA mode: concise, knows Miles's schedule/projects, proactive
- Daily digest (noon) + pre-shift brief (4:30pm) via cron
- Quick commands: /plan, /picks, /brief, /costs, /projects
- Webhook deduplication (persistent, survives restarts)
- Session management for conversation continuity
- Direct Claude Code execution with --resume
- Tmux agent spawning for long-running tasks
- Job queue routing for complex tasks
"""

import os
import json
import asyncio
import uuid
import time
import pathlib
import logging
import re as _re_tg
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Request

# ── Shared dependencies ──────────────────────────────────────────────────────
from .shared import (
    CONFIG, session_store, save_session_history, broadcast_event,
    get_agent_config, call_model_with_escalation, call_model_for_agent,
    build_channel_system_prompt, trim_history_if_needed,
    anthropic_client, agent_router, metrics, BASE_DIR, logger
)

# ── Other module imports ─────────────────────────────────────────────────────
from job_manager import create_job, list_jobs
from tmux_spawner import get_spawner

# ── Router setup ─────────────────────────────────────────────────────────────
router = APIRouter(prefix="/telegram", tags=["telegram"])

# ── Constants ────────────────────────────────────────────────────────────────
TELEGRAM_OWNER_ID = os.getenv("TELEGRAM_USER_ID", "8475962905")
CODERCLAW_BOT_TOKEN = os.getenv("CODERCLAW_BOT_TOKEN", "")
CODERCLAW_SESSIONS_DIR = pathlib.Path("/root/openclaw/data/coderclaw_sessions")
CODERCLAW_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# ── Persistent dedup for Telegram webhooks (survives gateway restarts) ──
_TG_DEDUP_FILE = pathlib.Path("/root/openclaw/data/tg_dedup.json")
_TG_DEDUP_TTL = 600  # 10 minutes

# Task patterns
TASKS_FILE = pathlib.Path(BASE_DIR) / "data" / "tasks.json"

# Claude Code patterns
_CLAUDE_CODE_PATTERNS = [
    # "build X", "fix X", "create X", "deploy X", "refactor X"
    (r'^\s*(?:build|fix|create|deploy|refactor|implement|add|update|upgrade|wire|connect|ship)\s+(.+)', 'single'),
    # "run all in parallel", "run these in parallel: X, Y, Z"
    (r'^\s*run\s+(?:all|these|everything)\s+in\s+parallel(?:[:\s]+(.+))?', 'parallel'),
    # "run: X" or "agent: X" — direct agent command
    (r'^\s*(?:run|agent|execute|do)[:\s]+(.+)', 'single'),
    # "PR for X", "create PR", "make a PR"
    (r'^\s*(?:create|make|open|submit)\s+(?:a\s+)?(?:pr|pull request)(?:\s+(?:for\s+)?(.+))?', 'pr'),
    # "spawn agent: X"
    (r'^\s*spawn\s+(?:agent[:\s]+)?(.+)', 'single'),
]

# Call patterns — trigger outbound sales calls
_CALL_PATTERNS = [
    r'^\s*call\s+(?:the\s+)?leads?(?:\s+for\s+(.+))?',  # "call leads", "call the leads for restaurants"
    r'^\s*call\s+(.+)',  # "call Mountain Grill", "call 928-555-1234"
]

# Lead finder patterns — handled separately from agents
_LEAD_FINDER_PATTERNS = [
    r'^\s*find\s+(?:leads?\s+(?:for\s+)?)?(\w[\w\s]+?)(?:\s+in\s+(.+))?$',
    r'^\s*search\s+(?:for\s+)?(\w[\w\s]+?)(?:\s+in\s+(.+))?$',
    r'^\s*(?:get|show|list)\s+(?:me\s+)?(\w[\w\s]+?)(?:\s+(?:in|near|around)\s+(.+))?$',
]

_TASK_PATTERNS = [
    r'^create task[:\s]+(.+)', r'^todo[:\s]+(.+)', r'^add task[:\s]+(.+)',
    r'^remind me to[:\s]+(.+)', r'^new task[:\s]+(.+)',
]

# PA system prompt — replaces generic agent prompt for Telegram
PA_SYSTEM_PROMPT = """You are Miles's personal assistant, running on the OpenClaw platform.

PERSONALITY: Concise, direct, action-oriented. No emojis unless asked. No fluff.
RESPONSE STYLE: 1-3 sentences for simple questions. Bullet points for lists. Never verbose.

MILES'S CONTEXT:
- Schedule: Work 5pm-10pm Tue-Sun, Monday OFF. Soccer Thursdays ~9:20pm.
- Projects: OpenClaw (this platform), Delhi Palace (restaurant site), Barber CRM, PrestressCalc, Concrete Canoe 2026
- Runs Cybershield Agency from VPS 152.53.55.207
- Betting: NBA XGBoost model, +EV identification, Quarter-Kelly sizing
- Prefers: ship fast, iterate, cost-aware, parallel execution

WHAT YOU CAN DO (use tools proactively):
- Plan days, create events, check calendar
- Check/create jobs, monitor agents
- Search memory for past decisions
- Run betting analysis, check odds
- Send Slack messages, search the web
- Check project status via GitHub
- Run cost reports

RULES:
- If Miles asks something you can answer from context, answer immediately
- If you need live data, use tools — never guess
- Keep responses under 500 chars for Telegram readability
- When asked to "plan my day" or similar, gather schedule + jobs + picks and summarize
- Don't identify yourself as an "AI" or "assistant" — just help
- Sign off with -- PA (not Cybershield PM)
"""


# ═══════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS — Telegram send, token resolution, dedup
# ═══════════════════════════════════════════════════════════════════════════

def _get_telegram_token() -> str:
    """Resolve Telegram bot token from config or env."""
    token = CONFIG.get("channels", {}).get("telegram", {}).get("botToken", "")
    if token.startswith("${") and token.endswith("}"):
        token = os.getenv(token[2:-1], "")
    if not token:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return token


async def _tg_send(chat_id, text: str, reply_to: int = None):
    """Send a message to Telegram. Splits long messages. HTML parse mode with plain-text fallback."""
    token = _get_telegram_token()
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Split into 4096-char chunks (Telegram limit)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=15) as client:
        for i, chunk in enumerate(chunks):
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            if reply_to and i == 0:
                payload["reply_to_message_id"] = reply_to
                payload["allow_sending_without_reply"] = True
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    # Retry without HTML parse mode and without reply
                    payload.pop("parse_mode", None)
                    payload.pop("reply_to_message_id", None)
                    await client.post(url, json=payload)
            except Exception as e:
                logger.error(f"Telegram send error: {e}")


async def _tg_typing(chat_id):
    """Send typing indicator."""
    token = _get_telegram_token()
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            )
    except Exception:
        pass


def _tg_dedup_check(update_id: int, bot: str = "cc") -> bool:
    """Return True if this update_id was already seen (duplicate). Thread-safe via file."""
    now = time.time()
    key = f"{bot}:{update_id}"
    try:
        if _TG_DEDUP_FILE.exists():
            seen = json.loads(_TG_DEDUP_FILE.read_text())
        else:
            seen = {}
    except (json.JSONDecodeError, OSError):
        seen = {}
    # Prune expired entries
    seen = {k: v for k, v in seen.items() if now - v < _TG_DEDUP_TTL}
    if key in seen:
        return True  # Duplicate
    seen[key] = now
    try:
        _TG_DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TG_DEDUP_FILE.write_text(json.dumps(seen))
    except OSError:
        pass
    return False  # New update


# ═══════════════════════════════════════════════════════════════════════════
# CODERCLAW BOT — Dedicated Claude Code controller via Telegram
# Persistent sessions: survives Cursor disconnects, resume from phone
# ═══════════════════════════════════════════════════════════════════════════

def _load_workspace_bootstrap() -> str:
    """
    Load workspace .md files for agent bootstrap context.
    Returns concatenated content of IDENTITY.md, USER.md, HEARTBEAT.md, TOOLS.md
    plus today's daily log. All files sized for token efficiency (~2KB each).
    """
    workspace = pathlib.Path("/root/openclaw/workspace")
    if not workspace.exists():
        return ""

    bootstrap_files = ["IDENTITY.md", "USER.md", "HEARTBEAT.md", "TOOLS.md"]
    parts = []

    # Load fixed bootstrap files
    for fname in bootstrap_files:
        fpath = workspace / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8")
                # Limit each file to 2000 chars to keep bootstrap token-efficient
                parts.append(f"## {fname}\n{content[:2000]}")
            except Exception as e:
                logger.warning(f"Failed to load {fname}: {e}")

    # Load today's daily log
    today = datetime.now().strftime("%Y-%m-%d")
    daily = workspace / f"{today}.md"
    if daily.exists():
        try:
            content = daily.read_text(encoding="utf-8")
            # Limit daily log to 1500 chars
            parts.append(f"## Daily Log ({today})\n{content[:1500]}")
        except Exception as e:
            logger.warning(f"Failed to load daily log: {e}")

    # Join with separators, max 8000 chars total
    bootstrap = "\n\n---\n\n".join(parts)
    return bootstrap[:8000]


async def _cc_send(chat_id, text: str, reply_to: int = None):
    """Send a message via CoderClaw bot."""
    if not CODERCLAW_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{CODERCLAW_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    async with httpx.AsyncClient(timeout=15) as client:
        for i, chunk in enumerate(chunks):
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            if reply_to and i == 0:
                payload["reply_to_message_id"] = reply_to
                payload["allow_sending_without_reply"] = True
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    payload.pop("parse_mode", None)
                    payload.pop("reply_to_message_id", None)
                    await client.post(url, json=payload)
            except Exception as e:
                logger.error(f"CoderClaw send error: {e}")


async def _cc_typing(chat_id):
    """Send typing indicator via CoderClaw bot."""
    if not CODERCLAW_BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{CODERCLAW_BOT_TOKEN}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            )
    except Exception:
        pass


def _cc_get_session(chat_id) -> dict:
    """Load or create a CoderClaw session."""
    session_file = CODERCLAW_SESSIONS_DIR / f"{chat_id}.json"
    if session_file.exists():
        try:
            return json.loads(session_file.read_text())
        except Exception:
            pass
    return {
        "chat_id": chat_id,
        "claude_session_id": None,
        "project": "/root/openclaw",
        "history": [],
        "created_at": datetime.now(timezone.utc).isoformat()
    }


def _cc_save_session(chat_id, session: dict):
    """Save a CoderClaw session."""
    session_file = CODERCLAW_SESSIONS_DIR / f"{chat_id}.json"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(session, indent=2))


async def _cc_run_claude(prompt: str, session: dict, cwd: str = "/root") -> tuple:
    """
    Run Claude Code with --resume for session continuity.
    Returns (result_text, new_session_id).
    """
    try:
        import subprocess
        cmd = ["claude", "code", "--resume"]
        if session.get("claude_session_id"):
            cmd.extend(["--session", session["claude_session_id"]])

        # Combine prompt with workspace bootstrap for context
        bootstrap = _load_workspace_bootstrap()
        full_prompt = f"{bootstrap}\n\n---\n\nTask: {prompt}"

        # Run with timeout (5 min)
        result = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: subprocess.run(
                    cmd,
                    input=full_prompt,
                    text=True,
                    capture_output=True,
                    cwd=cwd,
                    timeout=300
                )
            ),
            timeout=320
        )

        # Parse session_id from Claude Code output if available
        session_id = None
        if "Session ID:" in result.stdout:
            for line in result.stdout.split("\n"):
                if "Session ID:" in line:
                    session_id = line.split("Session ID:")[1].strip()
                    break

        # Return combined stdout/stderr (last 3800 chars to fit Telegram)
        result_text = result.stdout or result.stderr or "Claude Code ran but produced no output."

        # Try to parse JSON output if present
        try:
            lines = result_text.split("\n")
            for line in lines:
                if line.startswith("{"):
                    data = json.loads(line)
                    if "result" in data:
                        result_text = data["result"]
                        break
        except json.JSONDecodeError:
            pass

        return result_text[:3800], session_id

    except asyncio.TimeoutError:
        return "Claude Code timed out after 5 minutes. The task may still be running in the background.", session.get("claude_session_id")
    except Exception as e:
        return f"Error running Claude Code: {e}", session.get("claude_session_id")


@router.post("/coderclaw/webhook")
async def coderclaw_webhook(request: Request):
    """
    CoderClaw bot — Dedicated Claude Code controller via Telegram.

    Every message runs through Claude Code with --resume for session continuity.
    Returns 200 immediately and processes in background to prevent Telegram retries.
    Commands:
      /start — Welcome message
      /new — Start a fresh session (reset session_id)
      /status — Show running agents and session info
      /project <path> — Set working directory
      /output <job_id> — Get tmux agent output
      /spawn <task> — Spawn a long-running tmux agent (for big tasks)
      /kill <id|all> — Kill tmux agents
      Everything else — Runs through Claude Code with session resume
    """
    try:
        update = await request.json()
        if "message" not in update:
            return {"ok": True}

        # ── Dedup: reject retried updates (persistent, survives restarts) ──
        update_id = update.get("update_id")
        if _tg_dedup_check(update_id, bot="cc"):
            logger.info(f"CoderClaw dedup: skipping update_id {update_id}")
            return {"ok": True}

        message = update["message"]
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        text = message.get("text", "")
        msg_id = message.get("message_id")

        if not text:
            return {"ok": True}

        # Owner-only
        if TELEGRAM_OWNER_ID and user_id != TELEGRAM_OWNER_ID:
            return {"ok": True}

        logger.info(f"CoderClaw from {user_id}: {text[:80]}")

        # ── Quick commands: handle inline, return fast ──
        quick_commands = ["/start", "/new", "/status", "/project", "/output", "/kill", "/remote"]
        is_quick = any(text.strip().lower().startswith(cmd) for cmd in quick_commands)

        if is_quick:
            # Handle quick commands inline (fast, no bg needed)
            await _cc_typing(chat_id)

        # Load session
        session = _cc_get_session(chat_id)

        # ── /start ──
        if text.strip().lower() == "/start":
            await _cc_send(chat_id, (
                "<b>CoderClaw — Claude Code via Telegram</b>\n\n"
                "Send any message and I'll run it through Claude Code on your VPS.\n\n"
                "<b>Commands:</b>\n"
                "/new — Fresh session\n"
                "/status — Running agents\n"
                "/remote — Start a web session (get URL to open in browser)\n"
                "/remote stop — Stop the remote session\n"
                "/project &lt;path&gt; — Set working directory\n"
                "/spawn &lt;task&gt; — Long-running tmux agent\n"
                "/output &lt;job_id&gt; — Get agent output\n"
                "/kill &lt;id|all&gt; — Kill agents\n\n"
                "Everything else goes straight to Claude Code with session persistence. "
                "Your conversation carries over even if Cursor disconnects."
            ), reply_to=msg_id)
            return {"ok": True}

        # ── /new ──
        if text.strip().lower() == "/new":
            session["claude_session_id"] = None
            session["history"] = []
            _cc_save_session(chat_id, session)
            await _cc_send(chat_id, "Session reset. Next message starts a fresh Claude Code conversation.", reply_to=msg_id)
            return {"ok": True}

        # ── /project <path> ──
        proj_match = _re_tg.match(r'^/project\s+(.+)', text.strip())
        if proj_match:
            new_path = proj_match.group(1).strip()
            if os.path.isdir(new_path):
                session["project"] = new_path
                _cc_save_session(chat_id, session)
                await _cc_send(chat_id, f"Working directory set to: <code>{new_path}</code>", reply_to=msg_id)
            else:
                await _cc_send(chat_id, f"Directory not found: {new_path}", reply_to=msg_id)
            return {"ok": True}

        # ── /status ──
        if text.strip().lower() == "/status":
            lines = [f"<b>CoderClaw Status</b>\n"]
            lines.append(f"Session ID: <code>{session.get('claude_session_id', 'none')}</code>")
            lines.append(f"Project: <code>{session.get('project', '/root')}</code>")
            lines.append(f"History: {len(session.get('history', []))} messages\n")

            try:
                spawner = get_spawner()
                agents = spawner.list_agents()
                if agents:
                    lines.append(f"<b>{len(agents)} tmux agents running:</b>")
                    for a in agents:
                        lines.append(f"  {a['job_id'] or a['window_name']} — {a['status']} ({a['runtime_human']})")
                else:
                    lines.append("No tmux agents running.")
            except Exception:
                lines.append("Could not check tmux agents.")

            await _cc_send(chat_id, "\n".join(lines), reply_to=msg_id)
            return {"ok": True}

        # ── /remote — Start Claude Code remote-control session (web URL) ──
        if text.strip().lower().startswith("/remote"):
            remote_arg = text.strip()[7:].strip().lower()

            # /remote stop — kill any running remote-control session
            if remote_arg in ("stop", "kill", "off"):
                try:
                    import subprocess as _sp
                    # Find and kill remote-control tmux pane
                    result = _sp.run(
                        ["tmux", "list-panes", "-a", "-F", "#{pane_id} #{pane_current_command}"],
                        capture_output=True, text=True, timeout=5
                    )
                    killed = False
                    for line in result.stdout.strip().split("\n"):
                        if "claude" in line.lower():
                            parts = line.split()
                            if parts:
                                pane_id = parts[0]
                                # Check if it's the remote-control window
                                check = _sp.run(
                                    ["tmux", "capture-pane", "-t", pane_id, "-p"],
                                    capture_output=True, text=True, timeout=5
                                )
                                if "remote-control" in check.stdout.lower() or "Remote Control" in check.stdout:
                                    _sp.run(["tmux", "send-keys", "-t", pane_id, "C-c", ""], timeout=5)
                                    _sp.run(["tmux", "send-keys", "-t", pane_id, "exit", "Enter"], timeout=5)
                                    killed = True
                    # Also check for named window
                    _sp.run(["tmux", "kill-window", "-t", "remote-control"], capture_output=True, timeout=5)
                    await _cc_send(chat_id, "Remote session stopped." if killed else "No active remote session found.", reply_to=msg_id)
                except Exception as e:
                    await _cc_send(chat_id, f"Stop failed: {e}", reply_to=msg_id)
                return {"ok": True}

            # /remote — Start a new remote-control session
            try:
                import subprocess as _sp
                cwd = session.get("project", "/root/openclaw")

                # Kill any existing remote-control window first
                _sp.run(["tmux", "kill-window", "-t", "remote-control"], capture_output=True, timeout=5)

                # Ensure tmux server exists
                _sp.run(["tmux", "has-session", "-t", "openclaw"], capture_output=True, timeout=5)
                has_session = _sp.run(["tmux", "has-session", "-t", "openclaw"], capture_output=True, timeout=5).returncode == 0
                if not has_session:
                    _sp.run(["tmux", "new-session", "-d", "-s", "openclaw"], timeout=5)

                # Start remote-control in a new tmux window
                # Unset CLAUDECODE to avoid nested session error
                cmd = f"cd {cwd} && unset CLAUDECODE && claude remote-control --verbose --permission-mode bypassPermissions 2>&1 | tee /tmp/claude-remote-output.log"
                _sp.run(
                    ["tmux", "new-window", "-t", "openclaw", "-n", "remote-control", "-d", cmd],
                    timeout=10
                )

                # Wait for URL to appear in output
                await _cc_send(chat_id, "Starting remote session... waiting for URL (5s)", reply_to=msg_id)
                await asyncio.sleep(6)

                # Read the output to extract URL
                url = None
                try:
                    # Try the log file first
                    if os.path.exists("/tmp/claude-remote-output.log"):
                        with open("/tmp/claude-remote-output.log") as f:
                            log_content = f.read()
                        import re as _re_mod
                        url_match = _re_mod.search(r'(https://claude\.ai/code/session_[^\s]+)', log_content)
                        if url_match:
                            url = url_match.group(1)

                    # Fallback: capture from tmux pane
                    if not url:
                        capture = _sp.run(
                            ["tmux", "capture-pane", "-t", "openclaw:remote-control", "-p", "-S", "-50"],
                            capture_output=True, text=True, timeout=5
                        )
                        import re as _re_mod
                        url_match = _re_mod.search(r'(https://claude\.ai/code/session_[^\s]+)', capture.stdout)
                        if url_match:
                            url = url_match.group(1)
                except Exception as e:
                    logger.warning(f"Remote URL extraction failed: {e}")

                if url:
                    await _cc_send(chat_id, (
                        f"<b>Remote Session Ready</b>\n\n"
                        f"Open this URL in your browser or Claude app:\n"
                        f"<code>{url}</code>\n\n"
                        f"Working directory: <code>{cwd}</code>\n"
                        f"Full VPS access — files, git, MCP tools, everything.\n\n"
                        f"Stop with: /remote stop"
                    ), reply_to=msg_id)
                else:
                    # URL not found yet — might need more time
                    await _cc_send(chat_id, (
                        "<b>Remote session starting...</b>\n\n"
                        "Couldn't extract URL yet. Check in a few seconds:\n"
                        "/output remote-control\n\n"
                        "Or try: /remote stop and retry."
                    ), reply_to=msg_id)

            except Exception as e:
                await _cc_send(chat_id, f"Remote start failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ── /spawn <task> — long-running tmux agent ──
        spawn_match = _re_tg.match(r'^/spawn\s+(.+)', text.strip(), _re_tg.IGNORECASE)
        if spawn_match:
            task = spawn_match.group(1).strip()
            try:
                spawner = get_spawner()
                job_id = f"cc-{int(time.time())}"
                cwd = session.get("project", "/root")
                prompt = (
                    f"You are CoderClaw, a Claude Code agent running on the VPS.\n"
                    f"Working directory: {cwd}\n"
                    f"Task from Miles via Telegram: {task}\n\n"
                    f"Do the work thoroughly. Commit and push when done. Write a summary."
                )
                pane_id = spawner.spawn_agent(job_id=job_id, prompt=prompt, cwd=cwd, timeout_minutes=30)
                await _cc_send(chat_id, (
                    f"<b>Agent spawned in tmux</b>\n"
                    f"Job: <code>{job_id}</code>\n"
                    f"Task: {task[:300]}\n"
                    f"CWD: {cwd}\n\n"
                    f"Check output: /output {job_id}"
                ), reply_to=msg_id)
            except Exception as e:
                await _cc_send(chat_id, f"Spawn failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ── /output <job_id> ──
        out_match = _re_tg.match(r'^/output\s+(\S+)', text.strip(), _re_tg.IGNORECASE)
        if out_match:
            job_id = out_match.group(1)
            output_file = f"/root/openclaw/data/agent_outputs/openclaw-output-{job_id}.txt"
            if os.path.exists(output_file):
                with open(output_file) as f:
                    content = f.read()
                tail = content[-3000:] if len(content) > 3000 else content
                await _cc_send(chat_id, f"<b>Output {job_id}:</b>\n<pre>{tail}</pre>", reply_to=msg_id)
            else:
                # Try tmux pane capture
                try:
                    spawner = get_spawner()
                    output = spawner.collect_output("", job_id=job_id)
                    await _cc_send(chat_id, f"<b>Output {job_id}:</b>\n<pre>{output[-3000:]}</pre>", reply_to=msg_id)
                except Exception:
                    await _cc_send(chat_id, f"No output found for {job_id}", reply_to=msg_id)
            return {"ok": True}

        # ── /kill <id|all> ──
        kill_match = _re_tg.match(r'^/kill\s+(.+)', text.strip(), _re_tg.IGNORECASE)
        if kill_match:
            target = kill_match.group(1).strip()
            try:
                spawner = get_spawner()
                if target.lower() == "all":
                    count = spawner.kill_all()
                    await _cc_send(chat_id, f"Killed {count} agents.", reply_to=msg_id)
                else:
                    killed = False
                    for a in spawner.list_agents():
                        if a["job_id"] == target or target in (a.get("pane_id", ""), a.get("window_name", "")):
                            spawner.kill_agent(a["pane_id"])
                            killed = True
                            break
                    await _cc_send(chat_id, f"{'Killed' if killed else 'Not found'}: {target}", reply_to=msg_id)
            except Exception as e:
                await _cc_send(chat_id, f"Kill failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ── Slow path: return 200 immediately, process in background ──
        # This prevents Telegram from retrying after 60s timeout
        async def _cc_process_slow(chat_id, text, session, msg_id):
            """Background task for Claude Code execution (can take minutes)."""
            try:
                # ── Route big tasks to the OpenClaw job system ──
                job_keywords = ["build", "deploy", "refactor", "create", "implement", "fix all", "redesign", "migrate"]
                if any(kw in text.lower() for kw in job_keywords) and len(text) > 50:
                    _cc_job_created = None
                    try:
                        project_path = session.get("project", "/root")
                        project_name = os.path.basename(project_path.rstrip("/")) or "openclaw"
                        _cc_job_created = create_job(project=project_name, task=text, priority="P1")
                        await _cc_send(chat_id, (
                            f"<b>Task queued as job</b>\n"
                            f"Job ID: <code>{_cc_job_created.id}</code>\n"
                            f"Project: <code>{project_name}</code>\n"
                            f"Priority: P1\n\n"
                            f"This task is too large for inline execution. "
                            f"An agent will pick it up shortly.\n"
                            f"Check status: /status"
                        ), reply_to=msg_id)
                        return
                    except Exception as e:
                        if _cc_job_created:
                            # Job exists in queue — don't also run inline (prevents double-reply)
                            logger.warning(f"CoderClaw job {_cc_job_created.id} created but send failed: {e}")
                            await _cc_send(chat_id, f"Task queued (job {_cc_job_created.id})", reply_to=msg_id)
                            return
                        logger.warning(f"CoderClaw job routing failed, falling back to inline: {e}")

                # ── DEFAULT: Run through Claude Code with --resume ──
                cwd = session.get("project", "/root")
                await _cc_typing(chat_id)

                result, new_session_id = await _cc_run_claude(text, session, cwd=cwd)

                # Update session
                if new_session_id:
                    session["claude_session_id"] = new_session_id
                session["history"].append({"role": "user", "content": text, "ts": time.time()})
                session["history"].append({"role": "assistant", "content": result[:500], "ts": time.time()})
                if len(session["history"]) > 100:
                    session["history"] = session["history"][-60:]
                _cc_save_session(chat_id, session)

                await _cc_send(chat_id, result, reply_to=msg_id)
            except Exception as e:
                logger.error(f"CoderClaw background processing error: {e}")
                await _cc_send(chat_id, f"Error: {e}", reply_to=msg_id)

        asyncio.create_task(_cc_process_slow(chat_id, text, session, msg_id))
        return {"ok": True}  # Return immediately so Telegram doesn't retry

    except Exception as e:
        logger.error(f"CoderClaw webhook error: {e}")
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# PA HELPER FUNCTIONS — Quick commands that bypass LLM calls
# ═══════════════════════════════════════════════════════════════════════════

async def _pa_plan_day(chat_id, msg_id):
    """Send today's plan: schedule + pending jobs + priorities."""
    try:
        await _tg_typing(chat_id)
        from datetime import datetime
        now = datetime.now()
        day = now.strftime("%A")
        date = now.strftime("%Y-%m-%d")

        lines = [f"<b>{day} {date}</b>"]

        if day == "Monday":
            lines.append("Day OFF — planning, Claude sessions, big tasks")
        else:
            lines.append("Work: 5pm-10pm")
            if day == "Thursday":
                lines.append("Soccer: 9:20pm")

        # Jobs
        try:
            import requests as req
            r = req.get("http://localhost:18789/api/jobs?limit=10", timeout=5)
            if r.ok:
                jobs = r.json().get("jobs", [])
                pending = [j for j in jobs if j.get("status") in ("pending", "analyzing")]
                running = [j for j in jobs if j.get("status") in ("running", "in_progress")]
                if pending:
                    lines.append(f"\n<b>{len(pending)} pending jobs</b>")
                    for j in pending[:3]:
                        lines.append(f"  {j.get('title', j.get('task', '?'))[:60]}")
                if running:
                    lines.append(f"\n<b>{len(running)} running</b>")
        except Exception:
            pass

        # Costs
        try:
            import requests as req
            r = req.get("http://localhost:18789/api/costs/summary",
                        headers={"X-Auth-Token": os.getenv("GATEWAY_AUTH_TOKEN", "")}, timeout=5)
            if r.ok:
                c = r.json()
                lines.append(f"\nCosts: ${c.get('today_usd', 0):.2f} today | ${c.get('month_usd', 0):.2f} month")
        except Exception:
            pass

        await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
    except Exception as e:
        await _tg_send(chat_id, f"Plan failed: {e}", reply_to=msg_id)


async def _pa_betting_picks(chat_id, msg_id):
    """Send today's +EV betting picks."""
    try:
        await _tg_typing(chat_id)
        import sys
        sys.path.insert(0, "/root/openclaw") if "/root/openclaw" not in sys.path else None
        from sports_model import sports_betting
        import json

        result = sports_betting(action="recommend", sport="basketball_nba", bankroll=100, min_ev=0.02, limit=5)
        if isinstance(result, str):
            data = json.loads(result)
        else:
            data = result

        bets = data.get("recommendations", [])
        if not bets:
            await _tg_send(chat_id, "No +EV bets found right now.", reply_to=msg_id)
            return

        lines = [f"<b>{len(bets)} +EV Picks</b>"]
        for b in bets[:5]:
            team = b.get("team", "?")
            ev = b.get("edge_pct", b.get("ev", 0))
            book = b.get("best_book", b.get("sportsbook", "?"))
            odds = b.get("best_odds", b.get("odds", "?"))
            stake = b.get("kelly_stake", b.get("stake", "?"))
            lines.append(f"{team} @ {book} ({odds})")
            lines.append(f"  +{ev:.1f}% EV | Stake: ${stake}")

        await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
    except Exception as e:
        await _tg_send(chat_id, f"Picks unavailable: {str(e)[:200]}", reply_to=msg_id)


async def _pa_daily_brief(chat_id, msg_id):
    """Full daily brief — schedule + jobs + costs + picks + projects."""
    try:
        await _tg_typing(chat_id)
        # Run the digest script inline
        import subprocess
        result = subprocess.run(
            ["/usr/bin/python3", "/root/openclaw/scripts/daily_digest.py", "preshift"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ}
        )
        output = result.stdout.strip()
        if output:
            # Don't re-send to Telegram (script does that), just show inline
            # Actually, let's send it directly here
            await _tg_send(chat_id, output[:4000], reply_to=msg_id)
        else:
            await _tg_send(chat_id, f"Brief generation failed: {result.stderr[:200]}", reply_to=msg_id)
    except Exception as e:
        await _tg_send(chat_id, f"Brief failed: {e}", reply_to=msg_id)


async def _pa_costs(chat_id, msg_id):
    """Quick cost summary."""
    try:
        await _tg_typing(chat_id)
        import requests as req
        r = req.get("http://localhost:18789/api/costs/summary",
                    headers={"X-Auth-Token": os.getenv("GATEWAY_AUTH_TOKEN", "")}, timeout=5)
        if r.ok:
            c = r.json()
            lines = [
                "<b>Cost Report</b>",
                f"Today: ${c.get('today_usd', 0):.4f}",
                f"This month: ${c.get('month_usd', 0):.4f}",
            ]
            if c.get("by_model"):
                lines.append("\nBy model:")
                for model, cost in sorted(c["by_model"].items(), key=lambda x: x[1], reverse=True)[:5]:
                    lines.append(f"  {model}: ${cost:.4f}")
            await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
        else:
            await _tg_send(chat_id, "Cost data unavailable", reply_to=msg_id)
    except Exception as e:
        await _tg_send(chat_id, f"Cost check failed: {e}", reply_to=msg_id)


async def _pa_projects(chat_id, msg_id):
    """Quick project status from git."""
    try:
        await _tg_typing(chat_id)
        import subprocess
        projects = [
            ("/root/openclaw", "OpenClaw"),
            ("/root/Delhi-Palace", "Delhi Palace"),
            ("/root/Barber-CRM", "Barber CRM"),
            ("/root/Mathcad-Scripts", "PrestressCalc"),
        ]
        lines = ["<b>Projects</b>"]
        for path, name in projects:
            if os.path.isdir(path):
                try:
                    result = subprocess.run(
                        ["git", "log", "--oneline", "-1", "--format=%h %s (%cr)"],
                        cwd=path, capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        lines.append(f"<b>{name}:</b> {result.stdout.strip()}")
                except Exception:
                    lines.append(f"<b>{name}:</b> exists")
        await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
    except Exception as e:
        await _tg_send(chat_id, f"Project check failed: {e}", reply_to=msg_id)


async def _pa_jobs(chat_id, msg_id):
    """Job queue summary."""
    try:
        await _tg_typing(chat_id)
        import requests as req
        r = req.get("http://localhost:18789/api/jobs?status=all&limit=20", timeout=5)
        if not r.ok:
            await _tg_send(chat_id, "Job queue unavailable", reply_to=msg_id)
            return

        jobs = r.json().get("jobs", [])
        if not jobs:
            await _tg_send(chat_id, "Job queue is empty.", reply_to=msg_id)
            return

        pending = [j for j in jobs if j.get("status") in ("pending", "analyzing")]
        running = [j for j in jobs if j.get("status") in ("running", "in_progress")]
        done = [j for j in jobs if j.get("status") == "done"]
        failed = [j for j in jobs if j.get("status") == "failed"]

        lines = ["<b>Job Queue</b>"]
        if running:
            lines.append(f"\n<b>Running ({len(running)}):</b>")
            for j in running[:3]:
                lines.append(f"  {j.get('id', '?')[:20]} — {j.get('title', j.get('task', '?'))[:50]}")
        if pending:
            lines.append(f"\n<b>Pending ({len(pending)}):</b>")
            for j in pending[:3]:
                lines.append(f"  {j.get('id', '?')[:20]} — {j.get('title', j.get('task', '?'))[:50]}")
        if failed:
            lines.append(f"\n<b>Failed ({len(failed)}):</b>")
            for j in failed[:3]:
                lines.append(f"  {j.get('id', '?')[:20]} — {j.get('title', j.get('task', '?'))[:50]}")
        if done:
            lines.append(f"\nDone: {len(done)}")

        await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
    except Exception as e:
        await _tg_send(chat_id, f"Job check failed: {e}", reply_to=msg_id)


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Personal Assistant for Miles — routes commands, quick responses, agent spawning."""
    try:
        update = await request.json()

        if "message" not in update:
            return {"ok": True}

        # ── Dedup: reject retried updates (persistent, survives restarts) ──
        update_id = update.get("update_id")
        if _tg_dedup_check(update_id, bot="tg"):
            logger.info(f"Telegram dedup: skipping update_id {update_id}")
            return {"ok": True}

        message = update["message"]
        chat_id = message["chat"]["id"]
        user_id = str(message["from"]["id"])
        text = message.get("text", "")
        msg_id = message.get("message_id")

        if not text:
            return {"ok": True}

        # Owner-only check
        if TELEGRAM_OWNER_ID and user_id != TELEGRAM_OWNER_ID:
            logger.info(f"Ignoring non-owner Telegram message from {user_id}")
            return {"ok": True}

        session_key = f"telegram:{user_id}:{chat_id}"
        logger.info(f"📱 Telegram from {user_id}: {text[:80]}")

        # Send typing indicator
        await _tg_typing(chat_id)

        text_lower = text.strip().lower()

        # ═══════════════════════════════════════════════
        # 0. PA QUICK COMMANDS — Fast responses, no LLM needed
        # ═══════════════════════════════════════════════
        if text_lower in ("/plan", "plan my day", "plan", "what's today"):
            asyncio.create_task(_pa_plan_day(chat_id, msg_id))
            return {"ok": True}

        if text_lower in ("/picks", "picks", "betting picks", "bets", "bets today"):
            asyncio.create_task(_pa_betting_picks(chat_id, msg_id))
            return {"ok": True}

        if text_lower in ("/brief", "brief", "daily brief", "digest"):
            asyncio.create_task(_pa_daily_brief(chat_id, msg_id))
            return {"ok": True}

        if text_lower in ("/costs", "costs", "spending", "budget"):
            asyncio.create_task(_pa_costs(chat_id, msg_id))
            return {"ok": True}

        if text_lower in ("/projects", "projects", "project status"):
            asyncio.create_task(_pa_projects(chat_id, msg_id))
            return {"ok": True}

        if text_lower in ("/jobs", "jobs", "job queue", "queue"):
            asyncio.create_task(_pa_jobs(chat_id, msg_id))
            return {"ok": True}

        if text_lower == "/start":
            await _tg_send(chat_id, (
                "<b>PA Ready</b>\n\n"
                "Quick commands:\n"
                "/plan — Today's schedule + priorities\n"
                "/picks — Betting picks\n"
                "/brief — Full daily brief\n"
                "/costs — Spending report\n"
                "/projects — Project status\n"
                "/jobs — Job queue\n"
                "status — Running agents\n\n"
                "Or just tell me what you need."
            ), reply_to=msg_id)
            return {"ok": True}

        # ═══════════════════════════════════════════════
        # 1. AGENT SPAWN — Build/fix/deploy/refactor commands
        # ═══════════════════════════════════════════════
        tg_agent_match = None
        for pattern, pattern_type in _CLAUDE_CODE_PATTERNS:
            match = _re_tg.match(pattern, text.strip(), _re_tg.IGNORECASE)
            if match:
                agent_match = match.group(1).strip() if match.groups() else text.strip()
                tg_agent_match = agent_match
                pattern_type_used = pattern_type
                break

        if tg_agent_match:
            try:
                spawner = get_spawner()

                # Parallel: multiple agents
                if pattern_type_used == "parallel":
                    tasks_str = tg_agent_match if tg_agent_match else text
                    tasks = [t.strip() for t in tasks_str.split(",") if t.strip()]
                    if not tasks:
                        await _tg_send(chat_id, "❌ No tasks found to run in parallel", reply_to=msg_id)
                        return {"ok": True}

                    pane_ids = []
                    for i, task in enumerate(tasks[:4]):  # Max 4 parallel
                        job_id = f"tg-parallel-{int(time.time())}-{i}"
                        prompt = (
                            f"You are an OpenClaw agent working on the VPS. Working directory: /root/openclaw/\n"
                            f"Task from Miles via Telegram: {task}\n\n"
                            f"Do the work. Be thorough. When done, write a summary."
                        )
                        try:
                            pane_id = spawner.spawn_agent(job_id=job_id, prompt=prompt, timeout_minutes=30)
                            pane_ids.append(pane_id)
                        except Exception as e:
                            logger.error(f"Failed to spawn parallel task {i}: {e}")

                    if pane_ids:
                        await _tg_send(
                            chat_id,
                            f"<b>⚡ {len(pane_ids)} agents spawned in parallel</b>\n"
                            f"Tasks: {', '.join(str(t[:50]) for t in tasks)}\n\n"
                            f"Check output: <code>./autonomous.sh output &lt;job_id&gt;</code>",
                            reply_to=msg_id
                        )
                        return {"ok": True}
                    else:
                        await _tg_send(chat_id, "❌ Failed to spawn any agents", reply_to=msg_id)
                        return {"ok": True}

                else:
                    # Single agent task
                    job_id = f"tg-{int(time.time())}"
                    prompt = (
                        f"You are an OpenClaw agent working on the VPS. Working directory: /root/openclaw/\n"
                        f"Task from Miles via Telegram: {tg_agent_match}\n\n"
                        f"Do the work. Be thorough. When done, write a summary of what you did."
                    )
                    pane_id = spawner.spawn_agent(job_id=job_id, prompt=prompt, timeout_minutes=30)

                    await _tg_send(
                        chat_id,
                        f"<b>⚡ Agent spawned</b>\n"
                        f"Job: <code>{job_id}</code>\n"
                        f"Task: {tg_agent_match[:300]}\n"
                        f"Pane: {pane_id}\n\n"
                        f"Check output: <code>./autonomous.sh output {job_id}</code>",
                        reply_to=msg_id
                    )
                    return {"ok": True}

            except Exception as e:
                logger.error(f"Agent spawn from Telegram failed: {e}")
                await _tg_send(chat_id, f"❌ Agent spawn failed: {e}", reply_to=msg_id)
                return {"ok": True}  # Don't fall through — already replied

        # ═══════════════════════════════════════════════
        # 2. TASK CREATION — "create task:", "todo:", "remind me to:"
        # ═══════════════════════════════════════════════
        tg_task_match = None
        for _p in _TASK_PATTERNS:
            _m = _re_tg.match(_p, text.strip(), _re_tg.IGNORECASE)
            if _m:
                tg_task_match = _m.group(1).strip()
                break

        if tg_task_match:
            try:
                if TASKS_FILE.exists():
                    with open(TASKS_FILE, 'r') as f:
                        tasks = json.load(f)
                else:
                    tasks = []
                routing = agent_router.select_agent(tg_task_match)
                new_task = {
                    "id": str(uuid.uuid4())[:8],
                    "title": tg_task_match[:200],
                    "description": text,
                    "status": "todo",
                    "agent": routing.get("agentId", "project_manager"),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "source": "telegram",
                    "session_key": session_key
                }
                tasks.append(new_task)
                with open(TASKS_FILE, 'w') as f:
                    json.dump(tasks, f, indent=2)

                tg_jm_job_id = None
                try:
                    tg_jm_job = create_job(project=new_task.get("title", "telegram-task"), task=text, priority="P1")
                    tg_jm_job_id = tg_jm_job.id
                except Exception:
                    pass

                task_response = (
                    f"✅ Task created: {tg_task_match[:200]}\n"
                    f"ID: {new_task['id']}"
                    + (f" | Job: {tg_jm_job_id}" if tg_jm_job_id else "")
                )
                broadcast_event({"type": "task_created", "agent": "project_manager",
                                 "message": f"Task from Telegram: {tg_task_match[:80]}"})
                await _tg_send(chat_id, task_response, reply_to=msg_id)
                return {"ok": True}
            except Exception as e:
                logger.error(f"Telegram task creation failed: {e}")
                await _tg_send(chat_id, f"❌ Task creation failed: {e}", reply_to=msg_id)
                return {"ok": True}  # Don't fall through

        # ═══════════════════════════════════════════════
        # 3. STATUS CHECK — "status", "agents", "what's running"
        # ═══════════════════════════════════════════════
        if text_lower in ("status", "/status", "what's running", "agents", "check agents"):
            try:
                spawner = get_spawner()
                agents = spawner.list_agents()
                if agents:
                    lines = [f"<b>🤖 {len(agents)} agents running</b>\n"]
                    for a in agents:
                        lines.append(f"• {a['job_id'] or a['window_name']} — {a['status']} ({a['runtime_human']})")
                    await _tg_send(chat_id, "\n".join(lines), reply_to=msg_id)
                else:
                    await _tg_send(chat_id, "No agents running. Send a command to spawn one!", reply_to=msg_id)
                return {"ok": True}
            except Exception as e:
                await _tg_send(chat_id, f"Status check failed: {e}", reply_to=msg_id)
                return {"ok": True}

        # ═══════════════════════════════════════════════
        # 4. AGENT OUTPUT — "output JOB_ID"
        # ═══════════════════════════════════════════════
        output_match = _re_tg.match(r'^\s*output\s+(\S+)', text.strip(), _re_tg.IGNORECASE)
        if output_match:
            job_id = output_match.group(1)
            output_file = f"/tmp/openclaw-output-{job_id}.txt"
            if os.path.exists(output_file):
                with open(output_file, "r") as f:
                    content = f.read()
                # Last 2000 chars
                tail = content[-2000:] if len(content) > 2000 else content
                await _tg_send(chat_id, f"<b>Output for {job_id}:</b>\n<pre>{tail}</pre>", reply_to=msg_id)
            else:
                await _tg_send(chat_id, f"No output file for job {job_id}", reply_to=msg_id)
            return {"ok": True}

        # ═══════════════════════════════════════════════
        # 5. KILL AGENT — "kill JOB_ID" or "kill all"
        # ═══════════════════════════════════════════════
        kill_match = _re_tg.match(r'^\s*kill\s+(.+)', text.strip(), _re_tg.IGNORECASE)
        if kill_match:
            target = kill_match.group(1).strip()
            try:
                spawner = get_spawner()
                if target.lower() == "all":
                    count = spawner.kill_all()
                    await _tg_send(chat_id, f"Killed {count} agents.", reply_to=msg_id)
                else:
                    # Find agent by job_id
                    killed = False
                    for a in spawner.list_agents():
                        if a["job_id"] == target or target in (a.get("pane_id", ""), a.get("window_name", "")):
                            spawner.kill_agent(a["pane_id"])
                            killed = True
                            break
                    await _tg_send(chat_id, f"{'Killed' if killed else 'Not found'}: {target}", reply_to=msg_id)
            except Exception as e:
                await _tg_send(chat_id, f"Kill failed: {e}", reply_to=msg_id)
            return {"ok": True}

        # ═══════════════════════════════════════════════
        # 6. NORMAL CHAT — Route through Claude for conversation
        # Runs in background to prevent Telegram retry duplicates
        # ═══════════════════════════════════════════════
        async def _tg_process_chat(chat_id, text, session_key, msg_id):
            try:
                session_history = save_session_history(session_key)
                messages_for_api = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in session_history
                ]
                messages_for_api.append({"role": "user", "content": text})

                # Use PA system prompt for Telegram (not generic agent routing)
                system_prompt = PA_SYSTEM_PROMPT
                model = "gemini-2.5-flash"  # Fast + cheap for PA responses

                assistant_message = await call_model_with_escalation(
                    anthropic_client, model, system_prompt, messages_for_api
                )

                session_history.append({"role": "user", "content": text})
                session_history.append({"role": "assistant", "content": assistant_message})
                save_session_history(session_key, session_history)

                await _tg_send(chat_id, assistant_message, reply_to=msg_id)

            except Exception as e:
                logger.error(f"Telegram chat error: {e}")
                await _tg_send(chat_id, f"Error: {str(e)[:500]}", reply_to=msg_id)

        asyncio.create_task(_tg_process_chat(chat_id, text, session_key, msg_id))
        return {"ok": True}  # Return immediately so Telegram doesn't retry

    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return {"ok": False, "error": str(e)}
