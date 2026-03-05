#!/usr/bin/env python3
"""Install the daily betting analysis cron job at 8:00 AM UTC."""
import subprocess
import sys

WRAPPER_SCRIPT = "/root/openclaw/scripts/run_daily_betting.sh"
PYTHON_SCRIPT  = "/root/openclaw/scripts/daily_betting_analysis.py"
LOG_FILE       = "/root/openclaw/logs/daily_betting_analysis.log"
CRON_MARKER    = "daily_betting_analysis"

# Preferred cron line uses the wrapper (loads .env, validates vars, logs timestamps)
CRON_LINE_WRAPPER = f"0 8 * * * {WRAPPER_SCRIPT} >> {LOG_FILE} 2>&1"
# Legacy direct python3 line (already installed — also works since script loads .env itself)
CRON_LINE_LEGACY  = f"0 8 * * * /usr/bin/python3 {PYTHON_SCRIPT} >> {LOG_FILE} 2>&1"

def get_current_crontab():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    # No crontab yet
    return ""

def install_cron():
    current = get_current_crontab()
    
    # If wrapper is already installed, nothing to do
    if WRAPPER_SCRIPT in current:
        print("✅ Wrapper-based cron job already installed.")
        return True

    # If legacy direct python3 entry exists, upgrade it to the wrapper
    if PYTHON_SCRIPT in current:
        print("Found legacy cron entry — upgrading to wrapper script...")
        lines = current.splitlines(keepends=True)
        new_lines = []
        replaced = False
        for line in lines:
            if PYTHON_SCRIPT in line and not line.strip().startswith("#"):
                new_lines.append(f"# Daily ML Betting Analysis — runs at 8:00 AM UTC\n")
                new_lines.append(f"{CRON_LINE_WRAPPER}\n")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append(f"# Daily ML Betting Analysis — runs at 8:00 AM UTC\n")
            new_lines.append(f"{CRON_LINE_WRAPPER}\n")
        new_crontab = "".join(new_lines)
    else:
        # Fresh install
        new_crontab = current.rstrip("\n")
        if new_crontab:
            new_crontab += "\n"
        new_crontab += f"# Daily ML Betting Analysis — runs at 8:00 AM UTC\n"
        new_crontab += f"{CRON_LINE_WRAPPER}\n"
    
    # Install via crontab -
    result = subprocess.run(
        ["crontab", "-"],
        input=new_crontab,
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("✅ Cron job installed successfully!")
        print(f"   Schedule: 0 8 * * * (daily at 8:00 AM UTC)")
        print(f"   Script:   {WRAPPER_SCRIPT}")
        print(f"   Log:      {LOG_FILE}")
        return True
    else:
        print(f"❌ Failed to install cron job: {result.stderr}")
        return False

def verify_cron():
    current = get_current_crontab()
    if CRON_MARKER in current or WRAPPER_SCRIPT in current:
        print("\n✅ Verification: Cron job confirmed in crontab:")
        for line in current.splitlines():
            if line.strip() and (CRON_MARKER in line or "betting" in line.lower()):
                print(f"   {line}")
        return True
    else:
        print("❌ Verification failed: cron job not found in crontab")
        return False

if __name__ == "__main__":
    print("Installing daily betting analysis cron job...")
    success = install_cron()
    if success:
        verify_cron()
    sys.exit(0 if success else 1)
