#!/usr/bin/env python3
"""
Daily ML Betting Analysis Pipeline
====================================
Orchestrates the full daily betting analysis workflow:

  1. Check if XGBoost model is stale (>7 days) → retrain if needed
  2. Run sports_predict(action='predict') → today's NBA predictions
  3. Run betting_brain(action='find_value') → value bet identification
  4. Run sportsbook_arb(action='ev_scan') → +EV / arbitrage opportunities
  5. Compile comprehensive summary
  6. Send summary to Slack

Usage:
    python3 /root/openclaw/scripts/daily_betting_analysis.py

Cron (daily at 8:00 AM UTC):
    0 8 * * * /usr/bin/python3 /root/openclaw/scripts/daily_betting_analysis.py >> /root/openclaw/logs/daily_betting_analysis.log 2>&1

Dashboard: http://152.53.55.207:8502
"""

import json
import logging
import os
import pickle
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Bootstrap: ensure openclaw root is on sys.path ──────────────────────────
OPENCLAW_ROOT = Path(__file__).resolve().parent.parent
if str(OPENCLAW_ROOT) not in sys.path:
    sys.path.insert(0, str(OPENCLAW_ROOT))

# ── Load .env ────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(OPENCLAW_ROOT / ".env")
except Exception:
    pass

# ── Directories ──────────────────────────────────────────────────────────────
DATA_DIR = OPENCLAW_ROOT / "data"
MODEL_DIR = DATA_DIR / "models"
REPORTS_DIR = DATA_DIR / "betting" / "daily_reports"
LOG_DIR = OPENCLAW_ROOT / "logs"

for d in [MODEL_DIR, REPORTS_DIR, LOG_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "daily_betting_analysis.log"), mode="a"),
    ],
)
logger = logging.getLogger("daily_betting_pipeline")

# ── Constants ─────────────────────────────────────────────────────────────────
MODEL_STALE_DAYS = 7
NBA_SPORT_KEY = "basketball_nba"
SLACK_CHANNEL = os.getenv("SLACK_REPORT_CHANNEL", "C0AFE4QHKH7")
DASHBOARD_URL = "http://152.53.55.207:8502"


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 — Model staleness check + conditional retrain
# ═══════════════════════════════════════════════════════════════════════════════

def check_model_staleness(sport: str = "nba") -> dict:
    """
    Check if the XGBoost model pickle is older than MODEL_STALE_DAYS.

    Returns a dict with:
        stale (bool)       — whether the model needs retraining
        model_age_days     — age in days (None if model doesn't exist)
        model_path         — path checked
        trained_at         — ISO timestamp from model metadata (or None)
    """
    model_path = MODEL_DIR / f"{sport}_xgboost.pkl"

    if not model_path.exists():
        logger.info(f"Model not found at {model_path} — will train fresh.")
        return {
            "stale": True,
            "model_age_days": None,
            "model_path": str(model_path),
            "trained_at": None,
            "reason": "model_missing",
        }

    try:
        with open(model_path, "rb") as f:
            model_data = pickle.load(f)

        trained_str = model_data.get("trained")
        if trained_str:
            trained_at = datetime.fromisoformat(trained_str)
            # Make timezone-aware if naive
            if trained_at.tzinfo is None:
                trained_at = trained_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - trained_at
            age_days = age.total_seconds() / 86400
        else:
            # Fall back to file mtime
            mtime = model_path.stat().st_mtime
            age_days = (time.time() - mtime) / 86400
            trained_str = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        stale = age_days > MODEL_STALE_DAYS
        logger.info(
            f"Model age: {age_days:.1f} days (stale threshold: {MODEL_STALE_DAYS}d) → {'STALE' if stale else 'FRESH'}"
        )
        return {
            "stale": stale,
            "model_age_days": round(age_days, 2),
            "model_path": str(model_path),
            "trained_at": trained_str,
            "reason": "stale" if stale else "fresh",
        }

    except Exception as e:
        logger.warning(f"Could not read model metadata: {e} — treating as stale.")
        return {
            "stale": True,
            "model_age_days": None,
            "model_path": str(model_path),
            "trained_at": None,
            "reason": f"read_error: {e}",
        }


def retrain_model(sport: str = "nba") -> dict:
    """Retrain the XGBoost model via sports_predict(action='train')."""
    logger.info(f"Retraining {sport} XGBoost model...")
    try:
        from sports_model import sports_predict
        result_json = sports_predict(action="train", sport=sport)
        result = json.loads(result_json)
        if "error" in result:
            logger.error(f"Retrain failed: {result['error']}")
        else:
            logger.info(f"Retrain complete: {result.get('message', 'OK')}")
        return result
    except Exception as e:
        logger.error(f"Retrain exception: {e}")
        return {"error": str(e), "step": "retrain"}


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 — Daily NBA predictions
# ═══════════════════════════════════════════════════════════════════════════════

def run_predictions(sport: str = "nba", limit: int = 15) -> dict:
    """Run sports_predict(action='predict') for today's games."""
    logger.info("Running daily NBA predictions...")
    try:
        from sports_model import sports_predict
        result_json = sports_predict(action="predict", sport=sport, limit=limit)
        result = json.loads(result_json)
        n = len(result.get("predictions", []))
        logger.info(f"Predictions: {n} game(s) found")
        return result
    except Exception as e:
        logger.error(f"Prediction exception: {e}")
        return {"error": str(e), "step": "predict"}


# ═══════════════════════════════════════════════════════════════════════════════
# Step 3 — Value bet identification
# ═══════════════════════════════════════════════════════════════════════════════

def run_value_finder(sport: str = "nba") -> dict:
    """Run betting_brain(action='find_value') to surface value bets."""
    logger.info("Running betting brain value finder...")
    try:
        from betting_brain import betting_brain
        result_json = betting_brain(action="find_value", params={"sport": sport})
        result = json.loads(result_json)
        n = len(result.get("top_picks", []))
        logger.info(f"Value finder: {n} pick(s) identified")
        return result
    except Exception as e:
        logger.error(f"Value finder exception: {e}")
        return {"error": str(e), "step": "find_value"}


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4 — EV / Arbitrage scan
# ═══════════════════════════════════════════════════════════════════════════════

def run_ev_scan(sport: str = NBA_SPORT_KEY, limit: int = 10) -> dict:
    """Run sportsbook_arb(action='ev_scan') for +EV opportunities."""
    logger.info("Running sportsbook EV scan...")
    try:
        from sportsbook_odds import sportsbook_arb
        result_json = sportsbook_arb(action="ev_scan", sport=sport, limit=limit)
        result = json.loads(result_json)
        n = len(result.get("ev_opportunities", []))
        logger.info(f"EV scan: {n} opportunity(ies) found")
        return result
    except Exception as e:
        logger.error(f"EV scan exception: {e}")
        return {"error": str(e), "step": "ev_scan"}


# ═══════════════════════════════════════════════════════════════════════════════
# Step 5 — Compile summary
# ═══════════════════════════════════════════════════════════════════════════════

def compile_summary(
    staleness: dict,
    retrain_result: dict | None,
    predictions: dict,
    value_bets: dict,
    ev_scan: dict,
    pipeline_duration_s: float,
) -> str:
    """Compile all results into a comprehensive Slack-ready summary."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")

    lines = [
        f"🏀 *Daily ML Betting Analysis — {date_str} @ {time_str}*",
        f"Dashboard: {DASHBOARD_URL}",
        "",
    ]

    # ── Model status ──────────────────────────────────────────────────────────
    lines.append("*📦 XGBoost Model Status*")
    if staleness["stale"]:
        if retrain_result and "error" not in retrain_result:
            lines.append(f"  ✅ Model retrained (was {staleness.get('model_age_days', '?')} days old)")
            trained_at = retrain_result.get("trained_at") or retrain_result.get("model_path", "")
            if trained_at:
                lines.append(f"  Trained at: {trained_at}")
        elif retrain_result and "error" in retrain_result:
            lines.append(f"  ❌ Retrain failed: {retrain_result['error'][:120]}")
        else:
            lines.append("  ⚠️ Model stale but retrain was skipped")
    else:
        age = staleness.get("model_age_days", "?")
        trained = staleness.get("trained_at", "unknown")
        lines.append(f"  ✅ Model fresh ({age} days old, trained {trained[:10] if trained else 'unknown'})")
    lines.append("")

    # ── Predictions ───────────────────────────────────────────────────────────
    lines.append("*🔮 Today's NBA Predictions*")
    if "error" in predictions:
        lines.append(f"  ❌ Error: {predictions['error'][:150]}")
    else:
        preds = predictions.get("predictions", [])
        model_trained = predictions.get("model_trained", "unknown")
        if preds:
            lines.append(f"  {len(preds)} game(s) predicted | Model: {str(model_trained)[:10]}")
            for p in preds[:5]:  # Top 5 to keep message concise
                home = p.get("home_team") or p.get("home", "?")
                away = p.get("away_team") or p.get("away", "?")
                home_prob = p.get("home_win_prob", 0)
                away_prob = p.get("away_win_prob", 0)
                confidence = p.get("confidence", 0)
                fav = home if home_prob >= away_prob else away
                fav_prob = max(home_prob, away_prob)
                # confidence may be a float (0.0-1.0) or string label
                if isinstance(confidence, float):
                    conf_label = "high" if confidence >= 0.75 else ("medium" if confidence >= 0.60 else "low")
                else:
                    conf_label = str(confidence)
                conf_icon = "🔥" if conf_label == "high" else ("⚡" if conf_label == "medium" else "•")
                lines.append(
                    f"  {conf_icon} {away} @ {home}: *{fav}* wins ({fav_prob:.0%}) [{conf_label}]"
                )
            if len(preds) > 5:
                lines.append(f"  _...and {len(preds) - 5} more — see dashboard_")
        else:
            lines.append("  ℹ️ No games scheduled today")
    lines.append("")

    # ── Value bets ────────────────────────────────────────────────────────────
    lines.append("*💰 Value Bets (Betting Brain)*")
    if "error" in value_bets:
        lines.append(f"  ❌ Error: {value_bets['error'][:150]}")
    else:
        picks = value_bets.get("top_picks", [])
        scan_time = value_bets.get("scan_time_seconds", "?")
        if picks:
            lines.append(f"  {len(picks)} value play(s) found (scan: {scan_time}s)")
            for pick in picks[:4]:
                game = pick.get("game", "?")
                pick_type = pick.get("pick_type", "?")
                ev = pick.get("expected_value", 0)
                model_prob = pick.get("model_prob", 0)
                book_prob = pick.get("book_prob", 0)
                edge = pick.get("edge", 0)
                ev_str = f"+{ev:.1f}%" if isinstance(ev, (int, float)) else str(ev)
                edge_str = f"{edge:.1f}%" if isinstance(edge, (int, float)) else str(edge)
                lines.append(
                    f"  🎯 {game} | {pick_type} | EV: {ev_str} | Edge: {edge_str}"
                )
                if model_prob and book_prob:
                    lines.append(
                        f"     Model: {model_prob:.1%} vs Book: {book_prob:.1%}"
                    )
        else:
            lines.append("  ℹ️ No value plays identified today")

        # Market context summary if available
        market_ctx = value_bets.get("market_context", {})
        if market_ctx and not isinstance(market_ctx, str):
            public_lean = market_ctx.get("public_lean", "")
            if public_lean:
                lines.append(f"  📊 Market lean: {public_lean}")
    lines.append("")

    # ── EV / Arb scan ─────────────────────────────────────────────────────────
    lines.append("*⚡ +EV / Arbitrage Scan*")
    if "error" in ev_scan:
        lines.append(f"  ❌ Error: {ev_scan['error'][:150]}")
    else:
        ev_opps = ev_scan.get("ev_opportunities", [])
        arb_opps = ev_scan.get("arb_opportunities", [])
        quota = ev_scan.get("quota_remaining")

        if ev_opps:
            lines.append(f"  {len(ev_opps)} +EV opportunity(ies) found")
            for opp in ev_opps[:4]:
                game = opp.get("game", "?")
                book = opp.get("book", "?")
                outcome = opp.get("outcome", "?")
                ev_pct = opp.get("ev_pct", 0)
                odds = opp.get("odds", "?")
                ev_str = f"+{ev_pct:.1f}%" if isinstance(ev_pct, (int, float)) else str(ev_pct)
                lines.append(f"  📈 {game} | {outcome} @ {book} | {odds} | EV: {ev_str}")
        else:
            lines.append("  ℹ️ No +EV opportunities found")

        if arb_opps:
            lines.append(f"  🔄 {len(arb_opps)} arbitrage opportunity(ies)")
            for arb in arb_opps[:2]:
                game = arb.get("game", "?")
                profit = arb.get("profit_pct", 0)
                lines.append(f"  🔄 {game} | Profit: {profit:.2f}%")

        if quota is not None:
            lines.append(f"  _API quota remaining: {quota}_")
    lines.append("")

    # ── Pipeline stats ────────────────────────────────────────────────────────
    lines.append(
        f"_Pipeline completed in {pipeline_duration_s:.1f}s | "
        f"Generated {date_str} @ {time_str}_"
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Step 6 — Send to Slack
# ═══════════════════════════════════════════════════════════════════════════════

def send_to_slack(message: str, channel: str = SLACK_CHANNEL) -> bool:
    """Send the compiled summary to Slack via agent_tools._send_slack_message."""
    logger.info(f"Sending summary to Slack channel {channel}...")
    try:
        from agent_tools import _send_slack_message
        result = _send_slack_message(message, channel=channel)
        logger.info(f"Slack response: {result}")
        return True
    except Exception as e:
        logger.error(f"Slack send failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Report persistence
# ═══════════════════════════════════════════════════════════════════════════════

def save_report(
    staleness: dict,
    retrain_result: dict | None,
    predictions: dict,
    value_bets: dict,
    ev_scan: dict,
    summary: str,
) -> Path:
    """Persist the full pipeline output to data/betting/daily_reports/YYYY-MM-DD.json."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"{date_str}.json"

    report = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_staleness": staleness,
        "retrain_result": retrain_result,
        "predictions": predictions,
        "value_bets": value_bets,
        "ev_scan": ev_scan,
        "slack_summary": summary,
    }

    try:
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Report saved to {report_path}")
    except Exception as e:
        logger.error(f"Failed to save report: {e}")

    return report_path


# ═══════════════════════════════════════════════════════════════════════════════
# Main pipeline orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

def run_pipeline(sport: str = "nba") -> dict:
    """
    Execute the full daily betting analysis pipeline.

    Returns a summary dict with all results and the Slack message sent.
    """
    pipeline_start = time.time()
    logger.info("=" * 60)
    logger.info("Daily Betting Analysis Pipeline — START")
    logger.info(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # ── Step 1: Model staleness check ─────────────────────────────────────────
    logger.info("[1/4] Checking model staleness...")
    staleness = check_model_staleness(sport=sport)

    retrain_result = None
    if staleness["stale"]:
        logger.info(f"[1/4] Model is stale ({staleness.get('reason')}) — retraining...")
        retrain_result = retrain_model(sport=sport)
    else:
        logger.info(f"[1/4] Model is fresh — skipping retrain")

    # ── Step 2: Daily predictions ─────────────────────────────────────────────
    logger.info("[2/4] Running daily predictions...")
    predictions = run_predictions(sport=sport)

    # ── Step 3: Value bet finder ──────────────────────────────────────────────
    logger.info("[3/4] Running value bet finder...")
    value_bets = run_value_finder(sport=sport)

    # ── Step 4: EV / Arb scan ─────────────────────────────────────────────────
    logger.info("[4/4] Running EV/arb scan...")
    # sportsbook_arb uses the full sport key (e.g. "basketball_nba")
    sport_key = NBA_SPORT_KEY if sport == "nba" else sport
    ev_scan = run_ev_scan(sport=sport_key)

    # ── Step 5: Compile summary ───────────────────────────────────────────────
    pipeline_duration = time.time() - pipeline_start
    logger.info("Compiling summary...")
    summary = compile_summary(
        staleness=staleness,
        retrain_result=retrain_result,
        predictions=predictions,
        value_bets=value_bets,
        ev_scan=ev_scan,
        pipeline_duration_s=pipeline_duration,
    )

    # ── Step 6: Send to Slack ─────────────────────────────────────────────────
    logger.info("Sending to Slack...")
    slack_ok = send_to_slack(summary)

    # ── Persist report ────────────────────────────────────────────────────────
    report_path = save_report(
        staleness=staleness,
        retrain_result=retrain_result,
        predictions=predictions,
        value_bets=value_bets,
        ev_scan=ev_scan,
        summary=summary,
    )

    logger.info("=" * 60)
    logger.info(f"Pipeline COMPLETE in {pipeline_duration:.1f}s")
    logger.info(f"Slack: {'✅ sent' if slack_ok else '❌ failed'}")
    logger.info(f"Report: {report_path}")
    logger.info("=" * 60)

    return {
        "status": "complete",
        "duration_s": round(pipeline_duration, 2),
        "model_stale": staleness["stale"],
        "retrained": retrain_result is not None and "error" not in (retrain_result or {}),
        "predictions_count": len(predictions.get("predictions", [])),
        "value_bets_count": len(value_bets.get("top_picks", [])),
        "ev_opportunities_count": len(ev_scan.get("ev_opportunities", [])),
        "slack_sent": slack_ok,
        "report_path": str(report_path),
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Daily ML Betting Analysis Pipeline")
    parser.add_argument(
        "--sport",
        default="nba",
        help="Sport to analyze (default: nba)",
    )
    parser.add_argument(
        "--force-retrain",
        action="store_true",
        help="Force model retrain regardless of staleness",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but skip Slack send (print summary instead)",
    )
    args = parser.parse_args()

    if args.force_retrain:
        logger.info("--force-retrain flag set: overriding staleness check")
        # Monkey-patch staleness to force retrain
        _orig_check = check_model_staleness
        def check_model_staleness(sport="nba"):  # noqa: F811
            result = _orig_check(sport)
            result["stale"] = True
            result["reason"] = "force_retrain"
            return result

    if args.dry_run:
        logger.info("--dry-run flag set: Slack send will be skipped")
        _orig_send = send_to_slack
        def send_to_slack(message, channel=SLACK_CHANNEL):  # noqa: F811
            print("\n" + "=" * 60)
            print("DRY RUN — Slack message would be:")
            print("=" * 60)
            print(message)
            print("=" * 60 + "\n")
            return True

    result = run_pipeline(sport=args.sport)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["status"] == "complete" else 1)
