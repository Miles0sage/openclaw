# Daily Betting System Scan Setup

## Overview

The automated daily scanning system runs three betting scanners every day at 4:30 PM ET and sends results via Slack and SMS.

**Components:**
- `/root/openclaw/daily_scan.py` — Standalone script that runs all scans
- `money_engine.py` — Added `scan_schedule` action to show next scan and history
- Cron job that invokes daily_scan.py

## What It Scans

Each daily run executes:

1. **Dashboard Scan** (`money_engine("dashboard")`)
   - Quick opportunity summary across all strategies
   - Returns top signals only (fastest)

2. **NBA Value Plays** (`betting_brain("find_value", {"sport": "nba"})`)
   - Deep analysis of NBA matchups
   - Identifies mispriced lines vs Pinnacle sharp reference

3. **Crypto Signals** (`money_engine("crypto")`)
   - Bitcoin Fear & Greed Index
   - Top movers and mean reversion plays

## Output Locations

- **Full JSON Report**: `/root/openclaw/data/betting/daily_reports/YYYY-MM-DD.json`
  - Complete results from all three scans
  - Saved after each daily run

- **Scan Log**: `/root/openclaw/data/betting/scan.log`
  - Cron output and execution logs
  - All errors and status messages

## Installation (for Miles)

### Step 1: Set Required Credentials (if using SMS)

Add to `/root/openclaw/.env`:

```env
MILES_PHONE_NUMBER=+1XXXXXXXXXX    # E.164 format (e.g., +15551234567)
```

If `MILES_PHONE_NUMBER` is not set, SMS will be skipped and only Slack will receive results.

### Step 2: Install Cron Entry

Paste this into `crontab -e`:

```cron
30 21 * * * cd /root/openclaw && /usr/bin/python3 daily_scan.py >> data/betting/scan.log 2>&1
```

This runs daily at 4:30 PM ET (21:30 UTC).

### Step 3: Verify Installation

```bash
# Check cron is installed
crontab -l | grep daily_scan

# Check logs
tail -f /root/openclaw/data/betting/scan.log

# View recent reports
ls -lh /root/openclaw/data/betting/daily_reports/
```

## Usage

### View Next Scan Schedule

```python
from money_engine import money_engine
result = money_engine("scan_schedule")
# Shows next scan time and recent scan history
```

### Manual Trigger

Run a scan immediately (e.g., for testing):

```bash
cd /root/openclaw && python3 daily_scan.py
```

### View Recent Reports

```bash
ls -lh /root/openclaw/data/betting/daily_reports/

# View today's report
cat /root/openclaw/data/betting/daily_reports/2026-03-05.json | jq .

# View specific field
cat /root/openclaw/data/betting/daily_reports/2026-03-05.json | jq '.dashboard'
```

## How It Works

1. **At 21:30 UTC (4:30 PM ET)**: Cron invokes `daily_scan.py`

2. **Script execution**:
   - Loads `.env` for credentials
   - Runs dashboard scan (fastest)
   - Runs NBA value scan
   - Runs crypto scan (each handles its own errors)
   - Saves full JSON report to `data/betting/daily_reports/YYYY-MM-DD.json`

3. **Results dispatch**:
   - Formats SMS summary (max 500 chars) from key signals
   - Formats Slack message (full details, <2000 chars)
   - Sends to Slack (always)
   - Sends SMS only if `MILES_PHONE_NUMBER` is configured

4. **Logging**:
   - All output to `data/betting/scan.log`
   - Errors are logged but don't stop the script
   - Partial results still get sent if one scan fails

## Error Handling

The script is designed for resilience:

- If **dashboard scan fails**: still runs NBA and crypto scans
- If **NBA value scan fails**: still sends dashboard + crypto results
- If **crypto scan fails**: still sends dashboard + NBA results
- If **SMS send fails**: Slack still sends (and vice versa)
- If **Slack send fails**: SMS still sends (and vice versa)

Each scan failure is logged to `data/betting/scan.log` for debugging.

## File Locations Summary

| File | Purpose |
|------|---------|
| `/root/openclaw/daily_scan.py` | Main scan script |
| `/root/openclaw/money_engine.py` | Updated with `scan_schedule` action |
| `/root/openclaw/data/betting/daily_reports/` | Daily JSON reports (one per day) |
| `/root/openclaw/data/betting/scan.log` | Execution logs and errors |

## Testing

### Dry Run (import test)

```bash
python3 -c "import daily_scan; print('OK')"
```

### Full Dry Run (without sending)

```bash
# Edit daily_scan.py temporarily:
# Comment out: send_sms_result(sms_summary)
# Comment out: send_slack_result(slack_summary)

python3 daily_scan.py  # Will create report but not send
```

### With Slack Only (no SMS)

```bash
python3 daily_scan.py  # Works if MILES_PHONE_NUMBER not in .env
```

## Customization

### Change Scan Time

Edit the cron entry in `crontab -e`:

```cron
# Daily at 3 PM ET (20:00 UTC)
00 20 * * * cd /root/openclaw && /usr/bin/python3 daily_scan.py >> data/betting/scan.log 2>&1

# Twice daily (8 AM and 4 PM ET)
00 13 * * * cd /root/openclaw && /usr/bin/python3 daily_scan.py >> data/betting/scan.log 2>&1
30 21 * * * cd /root/openclaw && /usr/bin/python3 daily_scan.py >> data/betting/scan.log 2>&1
```

### Change Slack Channel

In `daily_scan.py`, modify:

```python
send_slack_result(slack_summary)  # Uses default SLACK_REPORT_CHANNEL from .env
```

To use a different channel:

```python
from agent_tools import _send_slack_message
_send_slack_message(slack_summary, channel="C12345XXXXX")
```

### Skip SMS or Slack

In `daily_scan.py` `main()`, comment out:

```python
# send_sms_result(sms_summary)  # Skip SMS
# send_slack_result(slack_summary)  # Skip Slack
```

## Next Steps

1. **Miles**: Set `MILES_PHONE_NUMBER` in `.env` if SMS is desired
2. **Miles**: Run `crontab -e` and paste the cron entry above
3. **Verify**: Wait for next scheduled run or run `python3 daily_scan.py` manually
4. **Monitor**: Check `data/betting/scan.log` and Slack reports channel

---

**Status**: Ready for deployment
**Created**: 2026-03-05
**Script Test**: ✓ Imports successfully
**Directories**: ✓ Created
**Cron Entry**: Ready (see above)
