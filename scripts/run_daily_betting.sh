#!/bin/bash
# Daily Betting Analysis — Cron Wrapper
# Runs daily at 8:00 AM UTC via cron:
#   0 8 * * * /root/openclaw/scripts/run_daily_betting.sh
#
# Loads environment variables from /root/openclaw/.env and executes
# the daily_betting_analysis.py pipeline.

set -euo pipefail

SCRIPT_DIR="/root/openclaw/scripts"
LOG_FILE="/root/openclaw/logs/daily_betting_analysis.log"
ENV_FILE="/root/openclaw/.env"
PYTHON_SCRIPT="${SCRIPT_DIR}/daily_betting_analysis.py"

# ── Load environment variables ────────────────────────────────────────────────
if [ -f "${ENV_FILE}" ]; then
    # Export all non-comment, non-empty lines from .env
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

# ── Ensure required env vars are set ─────────────────────────────────────────
MISSING_VARS=()
[ -z "${ODDS_API_KEY:-}" ]         && MISSING_VARS+=("ODDS_API_KEY")
[ -z "${SLACK_BOT_TOKEN:-}" ]      && MISSING_VARS+=("SLACK_BOT_TOKEN")
[ -z "${SLACK_REPORT_CHANNEL:-}" ] && MISSING_VARS+=("SLACK_REPORT_CHANNEL")

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] ERROR: Missing required env vars: ${MISSING_VARS[*]}" | tee -a "${LOG_FILE}"
    exit 1
fi

# ── Run the pipeline ──────────────────────────────────────────────────────────
echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Starting daily betting analysis pipeline..." | tee -a "${LOG_FILE}"

/usr/bin/python3 "${PYTHON_SCRIPT}" 2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE=${PIPESTATUS[0]}

if [ "${EXIT_CODE}" -eq 0 ]; then
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Pipeline completed successfully (exit 0)" | tee -a "${LOG_FILE}"
else
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] Pipeline FAILED with exit code ${EXIT_CODE}" | tee -a "${LOG_FILE}"
fi

exit "${EXIT_CODE}"
