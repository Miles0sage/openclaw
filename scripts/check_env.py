#!/usr/bin/env python3
"""Quick env var validation for daily betting analysis."""
import sys, os
sys.path.insert(0, '/root/openclaw')
from dotenv import load_dotenv
load_dotenv('/root/openclaw/.env')

checks = {
    'ODDS_API_KEY': bool(os.getenv('ODDS_API_KEY')),
    'SLACK_BOT_TOKEN': bool(os.getenv('SLACK_BOT_TOKEN')),
    'SLACK_REPORT_CHANNEL': bool(os.getenv('SLACK_REPORT_CHANNEL')),
}
for k, v in checks.items():
    print(f'  {"✅" if v else "❌"} {k}: {"SET" if v else "MISSING"}')

all_ok = all(checks.values())
print(f'\nAll required env vars: {"✅ OK" if all_ok else "❌ MISSING"}')

# Also verify script exists and is executable
import stat
from pathlib import Path
script = Path('/root/openclaw/scripts/daily_betting_analysis.py')
wrapper = Path('/root/openclaw/scripts/run_daily_betting.sh')
log_dir = Path('/root/openclaw/logs')

print(f'\nFile checks:')
print(f'  {"✅" if script.exists() else "❌"} Pipeline script: {script}')
print(f'  {"✅" if wrapper.exists() else "❌"} Wrapper script: {wrapper}')
print(f'  {"✅" if log_dir.exists() else "❌"} Log directory: {log_dir}')

if wrapper.exists():
    mode = wrapper.stat().st_mode
    is_exec = bool(mode & stat.S_IXUSR)
    print(f'  {"✅" if is_exec else "❌"} Wrapper is executable: {is_exec}')

sys.exit(0 if all_ok else 1)
