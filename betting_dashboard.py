"""
OpenClaw Betting Dashboard — Streamlit UI for ML-powered sports betting analysis.

Exposes the full betting pipeline:
- XGBoost NBA predictions with live odds comparison
- +EV identification with Kelly sizing
- Arbitrage scanning across 200+ sportsbooks
- Player props value analysis
- Research agent (news, injuries, line movement)
- CLV tracking and model performance
- Prediction market research

Run: streamlit run betting_dashboard.py --server.port 8502 --server.address 0.0.0.0
"""

import streamlit as st
import json
import time
from datetime import datetime

# Page config
st.set_page_config(
    page_title="OpenClaw Betting Brain",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Import betting tools
try:
    from sports_model import sports_predict, sports_betting, _load_model
    HAS_MODEL = True
except ImportError:
    HAS_MODEL = False

try:
    from betting_brain import betting_brain
    HAS_BRAIN = True
except ImportError:
    HAS_BRAIN = False

try:
    from sportsbook_odds import sportsbook_odds, sportsbook_arb
    HAS_ODDS = True
except ImportError:
    HAS_ODDS = False


def safe_json(func, *args, **kwargs):
    """Call a tool function and parse JSON result safely."""
    try:
        result = func(*args, **kwargs)
        return json.loads(result) if isinstance(result, str) else result
    except Exception as e:
        return {"error": str(e)}


# --- Sidebar ---
st.sidebar.title("OpenClaw Betting Brain")
st.sidebar.caption("ML-powered sports betting analysis")

page = st.sidebar.radio(
    "Navigate",
    [
        "Dashboard",
        "Predictions",
        "Value Finder",
        "Arbitrage",
        "Player Props",
        "Research",
        "Model Info",
        "Prediction Markets",
    ],
)

bankroll = st.sidebar.number_input("Bankroll ($)", min_value=10.0, value=100.0, step=10.0)
min_ev = st.sidebar.slider("Min EV %", 0.0, 20.0, 1.0, 0.5)
st.sidebar.divider()
st.sidebar.caption(f"Session: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# Check model status
model_status = "Not loaded"
if HAS_MODEL:
    try:
        md = _load_model("nba")
        if "error" not in md:
            model_status = f"Trained: {md.get('trained', 'unknown')[:10]}"
        else:
            model_status = "Not trained"
    except Exception:
        model_status = "Error"

st.sidebar.info(f"Model: {model_status}")


# ═══════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════
if page == "Dashboard":
    st.title("Betting Dashboard")
    st.caption("Overview of all active opportunities")

    col1, col2, col3 = st.columns(3)

    # Predictions
    with col1:
        st.subheader("Today's Predictions")
        if HAS_MODEL:
            with st.spinner("Loading predictions..."):
                preds = safe_json(sports_predict, "predict", "nba")
            if "error" in preds:
                st.error(preds["error"])
            else:
                predictions = preds.get("predictions", [])
                if not predictions:
                    st.info("No NBA games today")
                for p in predictions:
                    if "error" in p:
                        continue
                    winner = p.get("predicted_winner", "?")
                    conf = p.get("confidence", 0)
                    color = "green" if conf > 0.65 else "orange" if conf > 0.55 else "gray"
                    st.markdown(
                        f"**{p.get('away', '?')}** @ **{p.get('home', '?')}**  \n"
                        f"Pick: :{color}[{winner}] ({conf:.1%})"
                    )
        else:
            st.warning("sports_model not available")

    # +EV Opportunities
    with col2:
        st.subheader("+EV Opportunities")
        if HAS_MODEL:
            with st.spinner("Scanning for value..."):
                recs = safe_json(sports_betting, "recommend", "nba", bankroll, min_ev / 100)
            if "error" in recs:
                st.error(recs["error"])
            else:
                recommendations = recs.get("recommendations", [])
                if not recommendations:
                    st.info("No +EV plays found right now")
                for r in recommendations:
                    ev = r.get("ev_pct", 0)
                    edge = r.get("edge", 0)
                    st.markdown(
                        f"**{r.get('bet_on', '?')}** — {r.get('game', '')}  \n"
                        f"EV: **+{ev:.1f}%** | Edge: {edge:.1%} | "
                        f"Bet: **${r.get('bet_size', 0):.2f}** @ {r.get('odds', 0):.2f}  \n"
                        f"Book: {r.get('book', '?')}"
                    )
                    st.divider()
                summary = recs.get("summary", {})
                if summary:
                    st.metric("Total Wagered", f"${summary.get('total_wagered', 0):.2f}")
                    st.metric("Expected Profit", f"${summary.get('total_expected_profit', 0):.2f}")
        else:
            st.warning("sports_model not available")

    # Arbitrage
    with col3:
        st.subheader("Arbitrage Scan")
        if HAS_ODDS:
            with st.spinner("Scanning arbs..."):
                arbs = safe_json(sportsbook_arb, "scan", "basketball_nba", limit=5)
            if "error" in arbs:
                st.error(arbs["error"])
            else:
                opps = arbs.get("arbitrage_opportunities", [])
                if not opps:
                    st.info("No arb opportunities found")
                for a in opps:
                    st.markdown(
                        f"**{a.get('game', '?')}**  \n"
                        f"Profit: **{a.get('profit_pct', 0):.1f}%** guaranteed  \n"
                        f"Legs: {len(a.get('legs', []))}"
                    )
        else:
            st.warning("sportsbook_odds not available")


# ═══════════════════════════════════════════════════════════════
# PREDICTIONS
# ═══════════════════════════════════════════════════════════════
elif page == "Predictions":
    st.title("XGBoost NBA Predictions")
    st.caption("23-feature model trained on 3 seasons (~3,700 games)")

    if not HAS_MODEL:
        st.error("sports_model.py not available")
    else:
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("Retrain Model"):
                with st.spinner("Training XGBoost on 3 seasons... (~30s)"):
                    result = safe_json(sports_predict, "train", "nba")
                if "error" in result:
                    st.error(result["error"])
                else:
                    st.success(
                        f"Trained! Accuracy: {result.get('accuracy', 0):.1%}, "
                        f"Brier: {result.get('brier_score', 0):.4f}, "
                        f"Games: {result.get('total_games', 0)}"
                    )

        with st.spinner("Loading predictions..."):
            compare = safe_json(sports_predict, "compare", "nba")

        if "error" in compare:
            st.error(compare["error"])
        else:
            comparisons = compare.get("comparisons", [])
            if not comparisons:
                st.info("No NBA games today")
            else:
                for comp in comparisons:
                    game = comp.get("game", "?")
                    st.subheader(game)

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("Home Win Prob", f"{comp.get('model_home_prob', 0):.1%}")
                    with c2:
                        st.metric("Away Win Prob", f"{comp.get('model_away_prob', 0):.1%}")
                    with c3:
                        st.metric("Confidence", f"{comp.get('confidence', 0):.1%}")

                    # Show odds comparison if available
                    if comp.get("has_odds"):
                        for key, val in comp.items():
                            if isinstance(val, dict) and "ev_pct" in val:
                                team = key.replace("_odds", "")
                                ev = val["ev_pct"]
                                marker = "+" if ev > 0 else ""
                                st.markdown(
                                    f"  {team}: **{val.get('decimal', 0):.2f}** ({val.get('book', '?')}) | "
                                    f"Implied: {val.get('implied_prob', 0):.1%} | "
                                    f"Model: {val.get('model_prob', 0):.1%} | "
                                    f"EV: **{marker}{ev:.1f}%** | "
                                    f"Kelly: ${val.get('kelly_$100', 0):.2f}/$100"
                                )
                    else:
                        st.caption("No odds data available for this game")
                    st.divider()


# ═══════════════════════════════════════════════════════════════
# VALUE FINDER
# ═══════════════════════════════════════════════════════════════
elif page == "Value Finder":
    st.title("Value Finder")
    st.caption("XGBoost model vs sportsbook odds — find where books are wrong")

    if not HAS_BRAIN:
        st.error("betting_brain.py not available")
    else:
        with st.spinner("Running value analysis..."):
            result = safe_json(betting_brain, "find_value", {"sport": "nba"})

        if "error" in result:
            st.error(result["error"])
        else:
            # Value bets
            value_bets = result.get("value_bets", [])
            if value_bets:
                st.subheader(f"Found {len(value_bets)} Value Bet(s)")
                for vb in value_bets:
                    edge = vb.get("edge_pct", 0)
                    color = "green" if edge > 5 else "orange"
                    st.markdown(
                        f"**{vb.get('game', '?')}** — {vb.get('team', '?')}  \n"
                        f"Edge: :{color}[{edge:.1f}%] | "
                        f"Model: {vb.get('model_prob', 0):.1%} vs Implied: {vb.get('implied_prob', 0):.1%}  \n"
                        f"Odds: {vb.get('best_odds', 0):.2f} @ {vb.get('best_book', '?')}  \n"
                        f"Kelly bet: **${vb.get('kelly_bet', 0):.2f}** on ${bankroll:.0f} bankroll"
                    )
                    st.divider()
            else:
                st.info("No value bets found — model agrees with the market")

            # Context signals
            signals = result.get("context_signals", {})
            if signals:
                st.subheader("Context Signals")
                for key, val in signals.items():
                    if isinstance(val, list):
                        for item in val[:3]:
                            st.markdown(f"- {item}" if isinstance(item, str) else f"- {json.dumps(item)[:200]}")
                    else:
                        st.markdown(f"**{key}**: {val}")


# ═══════════════════════════════════════════════════════════════
# ARBITRAGE
# ═══════════════════════════════════════════════════════════════
elif page == "Arbitrage":
    st.title("Arbitrage Scanner")
    st.caption("Risk-free profit opportunities across 200+ sportsbooks")

    sport_key = st.selectbox("Sport", [
        "basketball_nba", "americanfootball_nfl", "baseball_mlb",
        "icehockey_nhl", "soccer_epl",
    ])

    if not HAS_ODDS:
        st.error("sportsbook_odds not available")
    else:
        tab1, tab2 = st.tabs(["Arbitrage", "+EV Scan"])

        with tab1:
            with st.spinner("Scanning for arbitrage..."):
                arbs = safe_json(sportsbook_arb, "scan", sport_key, limit=10)
            if "error" in arbs:
                st.error(arbs["error"])
            else:
                opps = arbs.get("arbitrage_opportunities", [])
                quota = arbs.get("quota", {})
                st.caption(f"API Quota: {quota.get('requests_remaining', '?')}/{quota.get('requests_used', '?')} used")

                if not opps:
                    st.info("No arbitrage opportunities found")
                for a in opps:
                    st.markdown(
                        f"### {a.get('game', '?')}\n"
                        f"**Guaranteed profit: {a.get('profit_pct', 0):.2f}%**"
                    )
                    for leg in a.get("legs", []):
                        st.markdown(
                            f"- {leg.get('team', '?')}: **{leg.get('odds', 0):.2f}** @ {leg.get('book', '?')} "
                            f"— stake ${leg.get('stake', 0):.2f}"
                        )
                    st.divider()

        with tab2:
            with st.spinner("Scanning for +EV..."):
                ev_scan = safe_json(sportsbook_arb, "ev_scan", sport_key, limit=10)
            if "error" in ev_scan:
                st.error(ev_scan["error"])
            else:
                ev_opps = ev_scan.get("ev_opportunities", [])
                if not ev_opps:
                    st.info("No +EV opportunities found")
                for e in ev_opps:
                    st.markdown(
                        f"**{e.get('game', '?')}** — {e.get('team', '?')}  \n"
                        f"EV: **+{e.get('ev_pct', 0):.1f}%** | "
                        f"Odds: {e.get('odds', 0):.2f} @ {e.get('book', '?')}  \n"
                        f"Sharp prob: {e.get('sharp_prob', 0):.1%}"
                    )
                    st.divider()


# ═══════════════════════════════════════════════════════════════
# PLAYER PROPS
# ═══════════════════════════════════════════════════════════════
elif page == "Player Props":
    st.title("Player Props Value")
    st.caption("2-3x less efficient than moneyline — higher edge potential")

    if not HAS_BRAIN:
        st.error("betting_brain.py not available")
    else:
        with st.spinner("Analyzing player props..."):
            result = safe_json(betting_brain, "props_value", {"sport": "nba"})

        if "error" in result:
            st.error(result["error"])
        else:
            summary = result.get("summary", {})
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Props Analyzed", summary.get("total_analyzed", 0))
            with c2:
                st.metric("Value Found", summary.get("value_opportunities", 0))
            with c3:
                st.metric("High Confidence", summary.get("high_confidence", 0))

            props = result.get("value_props", [])
            if not props:
                st.info("No value props found today")
            for p in props:
                signal = p.get("value_signal", "?")
                color = "green" if signal == "High" else "orange"
                st.markdown(
                    f"**{p.get('player', '?')}** — {p.get('prop_type', '?')} {p.get('side', '?')} {p.get('line', 0)}  \n"
                    f"Signal: :{color}[{signal}] | "
                    f"Season avg: {p.get('season_avg', 'N/A')} | "
                    f"Deviation: {p.get('deviation_pct', 0):.1f}%  \n"
                    f"Odds: {p.get('odds', 0):.2f} @ {p.get('best_book', '?')}  \n"
                    f"_{p.get('reasoning', '')}_"
                )
                st.divider()


# ═══════════════════════════════════════════════════════════════
# RESEARCH
# ═══════════════════════════════════════════════════════════════
elif page == "Research":
    st.title("Betting Research Agent")
    st.caption("News, injuries, line movement, model context")

    if not HAS_BRAIN:
        st.error("betting_brain.py not available")
    else:
        tab1, tab2, tab3 = st.tabs(["Full Research", "Line Movement", "CLV Report"])

        with tab1:
            if st.button("Run Full Research", key="research"):
                with st.spinner("Researching... (fetching news, injuries, odds, model predictions)"):
                    result = safe_json(betting_brain, "research", {"sport": "nba"})
                if "error" in result:
                    st.error(result["error"])
                else:
                    # News
                    st.subheader("Sports News")
                    for item in result.get("news", [])[:5]:
                        if isinstance(item, dict):
                            st.markdown(f"- [{item.get('headline', '?')}]({item.get('link', '#')})")
                        else:
                            st.markdown(f"- {item}")

                    # Injuries
                    st.subheader("Injury Report")
                    injuries = result.get("injuries", [])
                    if injuries:
                        for inj in injuries[:10]:
                            st.markdown(f"- {inj}" if isinstance(inj, str) else f"- {json.dumps(inj)[:200]}")
                    else:
                        st.info("No injury data available")

                    # Value summary
                    st.subheader("Value Analysis")
                    st.json(result.get("value_analysis", result.get("value_bets", {})))

                    st.caption(f"Scan time: {result.get('scan_time_seconds', '?')}s")

        with tab2:
            if st.button("Analyze Line Movement", key="lines"):
                with st.spinner("Analyzing lines..."):
                    result = safe_json(betting_brain, "line_analysis", {"sport_key": "basketball_nba"})
                if "error" in result:
                    st.error(result["error"])
                else:
                    st.json(result)

        with tab3:
            if st.button("Generate CLV Report", key="clv"):
                with st.spinner("Generating CLV report..."):
                    result = safe_json(betting_brain, "clv_report")
                if "error" in result:
                    st.error(result["error"])
                else:
                    stats = result.get("clv_stats", {})
                    if stats:
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.metric("Avg CLV", f"{stats.get('avg_clv', 0):.4f}")
                        with c2:
                            st.metric("Positive CLV Bets", stats.get("positive_clv_count", 0))
                        with c3:
                            st.metric("Negative CLV Bets", stats.get("negative_clv_count", 0))

                    st.markdown(f"**Edge Consistency**: {result.get('edge_consistency', 'N/A')}")
                    st.markdown(f"**Recommendation**: {result.get('recommendation', 'N/A')}")

                    recent = result.get("recent_bets", [])
                    if recent:
                        st.subheader("Recent Bets")
                        st.dataframe(recent)
                    else:
                        st.info(result.get("message", "No CLV data yet"))


# ═══════════════════════════════════════════════════════════════
# MODEL INFO
# ═══════════════════════════════════════════════════════════════
elif page == "Model Info":
    st.title("XGBoost Model Details")

    if not HAS_MODEL:
        st.error("sports_model.py not available")
    else:
        tab1, tab2 = st.tabs(["Evaluate", "Features"])

        with tab1:
            with st.spinner("Loading model evaluation..."):
                result = safe_json(sports_predict, "evaluate", "nba")
            if "error" in result:
                st.error(result["error"])
            else:
                st.markdown(f"**Model**: {result.get('model', '?')}")
                st.markdown(f"**Trained**: {result.get('trained', '?')}")
                st.markdown(f"**Estimators**: {result.get('n_estimators', '?')}")
                st.markdown(f"**Max Depth**: {result.get('max_depth', '?')}")

                cal = result.get("calibration", {})
                if cal:
                    st.subheader("Calibration")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("Brier Before", f"{cal.get('brier_before', 0):.4f}")
                    with c2:
                        st.metric("Brier After", f"{cal.get('brier_after', 0):.4f}")
                    with c3:
                        st.metric("Improvement", f"{cal.get('improvement', 0):.4f}")

                curve = result.get("calibration_curve", {})
                if curve:
                    st.subheader("Calibration Curve")
                    import pandas as pd
                    df = pd.DataFrame({
                        "Predicted Probability": curve.get("bin_centers", []),
                        "Actual Win Rate": curve.get("actual_win_rates", []),
                        "Sample Size": curve.get("samples_per_bin", []),
                    })
                    st.line_chart(df.set_index("Predicted Probability")["Actual Win Rate"])
                    st.dataframe(df)

                if st.button("Calibrate Model"):
                    with st.spinner("Calibrating with isotonic regression..."):
                        cal_result = safe_json(sports_predict, "calibrate", "nba")
                    if "error" in cal_result:
                        st.error(cal_result["error"])
                    else:
                        st.success(
                            f"Calibrated! Brier improved from {cal_result.get('brier_score_before', 0):.4f} "
                            f"to {cal_result.get('brier_score_after', 0):.4f}"
                        )

        with tab2:
            with st.spinner("Loading features..."):
                result = safe_json(sports_predict, "features", "nba")
            if "error" in result:
                st.error(result["error"])
            else:
                features = result.get("features", [])
                if features:
                    import pandas as pd
                    df = pd.DataFrame(features)
                    st.bar_chart(df.set_index("name")["importance"])
                    st.dataframe(df)


# ═══════════════════════════════════════════════════════════════
# PREDICTION MARKETS
# ═══════════════════════════════════════════════════════════════
elif page == "Prediction Markets":
    st.title("Prediction Market Research")
    st.caption("Polymarket, Kalshi — bonds, arbs, convergence plays")

    if not HAS_BRAIN:
        st.error("betting_brain.py not available")
    else:
        if st.button("Research Markets"):
            with st.spinner("Scanning prediction markets..."):
                result = safe_json(betting_brain, "prediction_research")
            if "error" in result:
                st.error(result["error"])
            else:
                summary = result.get("summary", {})
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("Total Picks", summary.get("total_picks", 0))
                with c2:
                    st.metric("Bonds", summary.get("bonds", 0))
                with c3:
                    st.metric("Arbs", summary.get("arbs", 0))
                with c4:
                    st.metric("Convergence", summary.get("convergence", 0))

                picks = result.get("actionable_picks", [])
                if picks:
                    st.subheader("Actionable Picks")
                    for p in picks:
                        risk_color = {"near-zero": "green", "low": "blue", "low-medium": "orange"}.get(p.get("risk", ""), "gray")
                        st.markdown(
                            f"**[{p.get('type', '?')}]** {p.get('title', '?')}  \n"
                            f"Risk: :{risk_color}[{p.get('risk', '?')}] | "
                            f"Platform: {p.get('platform', '?')}  \n"
                            f"_{p.get('reasoning', '')}_"
                        )
                        st.divider()
                else:
                    st.info("No actionable picks found")

                # Raw sections
                with st.expander("Raw Data"):
                    st.json(result.get("sections", {}))


# Footer
st.divider()
st.caption("OpenClaw Betting Brain v1.0 | XGBoost + 200+ sportsbooks + Quarter-Kelly sizing | Not financial advice")
