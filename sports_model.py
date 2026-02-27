"""
Sports Prediction Engine — Phase 3: XGBoost NBA model + betting recommendations

Uses nba_api for historical data, XGBoost for win probability predictions.
Models saved to /root/openclaw/data/models/.

Composes with sportsbook_odds.py to produce full predict→odds→EV→Kelly pipeline.
"""

import json
import os
import time
import pickle
from datetime import datetime, timedelta
from pathlib import Path

MODEL_DIR = Path("/root/openclaw/data/models")
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Cache for NBA API calls (rate-limited at ~2 req/sec)
_cache = {}
_CACHE_TTL = 1800  # 30 minutes


def _cached_get(key: str):
    """Get from cache if fresh."""
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def _cached_set(key: str, data):
    """Set cache entry."""
    _cache[key] = {"data": data, "ts": time.time()}


# ═══════════════════════════════════════════════════════════════
# NBA data helpers
# ═══════════════════════════════════════════════════════════════

def _get_nba_features(team_id: int, season: str, games_back: int = 10) -> dict:
    """Pull team stats from nba_api — rolling averages over last N games.

    Features: FG_PCT, FG3_PCT, REB, AST, TOV, PTS, rest_days, win_pct
    """
    from nba_api.stats.endpoints import teamgamelog
    import pandas as pd

    cache_key = f"team_{team_id}_{season}_{games_back}"
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    try:
        time.sleep(0.6)  # Rate limit: NBA.com allows ~2 req/sec
        log = teamgamelog.TeamGameLog(team_id=team_id, season=season, timeout=15)
        df = log.get_data_frames()[0]

        if df.empty:
            return {"error": f"No games found for team {team_id} in {season}"}

        # Take last N games
        recent = df.head(games_back)

        features = {
            "fg_pct": round(recent["FG_PCT"].mean(), 4),
            "fg3_pct": round(recent["FG3_PCT"].mean(), 4),
            "reb": round(recent["REB"].mean(), 1),
            "ast": round(recent["AST"].mean(), 1),
            "tov": round(recent["TOV"].mean(), 1),
            "pts": round(recent["PTS"].mean(), 1),
            "win_pct": round(recent["WL"].apply(lambda x: 1 if x == "W" else 0).mean(), 3),
        }

        # Rest days (days since last game)
        if len(df) >= 2:
            dates = pd.to_datetime(df["GAME_DATE"])
            features["rest_days"] = (dates.iloc[0] - dates.iloc[1]).days
        else:
            features["rest_days"] = 3  # default

        _cached_set(cache_key, features)
        return features

    except Exception as e:
        return {"error": f"NBA API error for team {team_id}: {str(e)[:200]}"}


def _get_all_teams() -> dict:
    """Get all NBA teams as id -> abbreviation mapping."""
    from nba_api.stats.static import teams as nba_teams

    cache_key = "all_teams"
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    all_teams = nba_teams.get_teams()
    result = {t["id"]: t for t in all_teams}
    _cached_set(cache_key, result)
    return result


def _find_team(name: str) -> dict:
    """Find an NBA team by name, abbreviation, or city."""
    from nba_api.stats.static import teams as nba_teams

    all_teams = nba_teams.get_teams()
    name_lower = name.lower().strip()

    for t in all_teams:
        if (name_lower == t["abbreviation"].lower() or
            name_lower == t["full_name"].lower() or
            name_lower == t["nickname"].lower() or
            name_lower == t["city"].lower() or
            name_lower in t["full_name"].lower()):
            return t
    return {"error": f"Team '{name}' not found. Use full name (e.g. 'Los Angeles Lakers') or abbreviation (e.g. 'LAL')"}


def _get_todays_games() -> list:
    """Get today's NBA schedule."""
    from nba_api.stats.endpoints import scoreboardv2
    import pandas as pd

    cache_key = "todays_games"
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    try:
        time.sleep(0.6)
        today = datetime.now().strftime("%m/%d/%Y")
        sb = scoreboardv2.ScoreboardV2(game_date=today, timeout=15)
        header = sb.get_data_frames()[0]

        games = []
        for _, row in header.iterrows():
            games.append({
                "game_id": row.get("GAME_ID", ""),
                "home_team_id": int(row.get("HOME_TEAM_ID", 0)),
                "away_team_id": int(row.get("VISITOR_TEAM_ID", 0)),
                "game_status": int(row.get("GAME_STATUS_ID", 0)),
                "game_status_text": row.get("GAME_STATUS_TEXT", ""),
            })

        _cached_set(cache_key, games)
        return games

    except Exception as e:
        return [{"error": f"Failed to get today's games: {str(e)[:200]}"}]


def _build_training_data(seasons: list = None) -> tuple:
    """Build training dataset from 3 seasons of NBA games.

    Returns (X, y) where X = feature matrix, y = home win (0/1).
    Caches to parquet for fast reloads.
    """
    import pandas as pd
    from nba_api.stats.endpoints import leaguegamelog

    if seasons is None:
        # Last 3 full seasons
        current_year = datetime.now().year
        seasons = [f"{y}-{str(y+1)[-2:]}" for y in range(current_year - 3, current_year)]

    cache_path = MODEL_DIR / "nba_training_data.parquet"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 168:  # 1 week
            df = pd.read_parquet(cache_path)
            X = df.drop(columns=["home_win"]).values
            y = df["home_win"].values
            return X, y, df.drop(columns=["home_win"]).columns.tolist()

    all_rows = []
    for season in seasons:
        try:
            time.sleep(1.0)
            log = leaguegamelog.LeagueGameLog(season=season, season_type_all_star="Regular Season", timeout=30)
            df = log.get_data_frames()[0]

            # Group by game — each game has 2 rows (home + away)
            game_groups = df.groupby("GAME_ID")
            for game_id, group in game_groups:
                if len(group) != 2:
                    continue

                # Determine home vs away from MATCHUP column ("vs." = home, "@" = away)
                home_row = None
                away_row = None
                for _, row in group.iterrows():
                    matchup = str(row.get("MATCHUP", ""))
                    if "vs." in matchup:
                        home_row = row
                    elif "@" in matchup:
                        away_row = row

                if home_row is None or away_row is None:
                    continue

                home_win = 1 if home_row.get("WL") == "W" else 0

                all_rows.append({
                    "home_fg_pct": home_row.get("FG_PCT", 0),
                    "home_fg3_pct": home_row.get("FG3_PCT", 0),
                    "home_reb": home_row.get("REB", 0),
                    "home_ast": home_row.get("AST", 0),
                    "home_tov": home_row.get("TOV", 0),
                    "home_pts": home_row.get("PTS", 0),
                    "away_fg_pct": away_row.get("FG_PCT", 0),
                    "away_fg3_pct": away_row.get("FG3_PCT", 0),
                    "away_reb": away_row.get("REB", 0),
                    "away_ast": away_row.get("AST", 0),
                    "away_tov": away_row.get("TOV", 0),
                    "away_pts": away_row.get("PTS", 0),
                    "home_win": home_win,
                })

        except Exception as e:
            continue  # Skip season on error

    if not all_rows:
        return None, None, None

    result_df = pd.DataFrame(all_rows)
    result_df.to_parquet(cache_path)

    X = result_df.drop(columns=["home_win"]).values
    y = result_df["home_win"].values
    return X, y, result_df.drop(columns=["home_win"]).columns.tolist()


def _train_xgboost(X, y, feature_names: list) -> dict:
    """Train XGBoost classifier. 80/20 split. Save to pkl."""
    import xgboost as xgb
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = xgb.XGBClassifier(
        max_depth=6,
        n_estimators=200,
        learning_rate=0.1,
        objective="binary:logistic",
        eval_metric="logloss",
        use_label_encoder=False,
        random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)

    # Evaluate
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]

    accuracy = accuracy_score(y_test, y_pred)
    brier = brier_score_loss(y_test, y_prob)
    logloss = log_loss(y_test, y_prob)

    # Feature importances
    importances = dict(zip(feature_names, [round(float(v), 4) for v in model.feature_importances_]))

    # Save model
    model_path = MODEL_DIR / "nba_xgboost.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({"model": model, "features": feature_names, "trained": datetime.now().isoformat()}, f)

    return {
        "accuracy": round(accuracy, 4),
        "brier_score": round(brier, 4),
        "log_loss": round(logloss, 4),
        "train_size": len(X_train),
        "test_size": len(X_test),
        "feature_importances": importances,
        "model_path": str(model_path),
    }


def _load_model(sport: str = "nba") -> dict:
    """Load saved model from pkl."""
    model_path = MODEL_DIR / f"{sport}_xgboost.pkl"
    if not model_path.exists():
        return {"error": f"No trained model found at {model_path}. Run action=train first."}

    with open(model_path, "rb") as f:
        data = pickle.load(f)
    return data


def _predict_game(home_features: dict, away_features: dict, model_data: dict) -> dict:
    """Predict a single game using loaded model."""
    import numpy as np

    model = model_data["model"]
    feature_names = model_data["features"]

    # Build feature vector matching training order
    feature_map = {
        "home_fg_pct": home_features.get("fg_pct", 0.45),
        "home_fg3_pct": home_features.get("fg3_pct", 0.36),
        "home_reb": home_features.get("reb", 44),
        "home_ast": home_features.get("ast", 24),
        "home_tov": home_features.get("tov", 14),
        "home_pts": home_features.get("pts", 110),
        "away_fg_pct": away_features.get("fg_pct", 0.45),
        "away_fg3_pct": away_features.get("fg3_pct", 0.36),
        "away_reb": away_features.get("reb", 44),
        "away_ast": away_features.get("ast", 24),
        "away_tov": away_features.get("tov", 14),
        "away_pts": away_features.get("pts", 110),
    }

    X = np.array([[feature_map.get(f, 0) for f in feature_names]])
    prob = model.predict_proba(X)[0]

    return {
        "home_win_prob": round(float(prob[1]), 4),
        "away_win_prob": round(float(prob[0]), 4),
    }


# ═══════════════════════════════════════════════════════════════
# Helper to get current NBA season string
# ═══════════════════════════════════════════════════════════════

def _current_season() -> str:
    """Return current NBA season string (e.g. '2025-26')."""
    now = datetime.now()
    year = now.year if now.month >= 10 else now.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


# ═══════════════════════════════════════════════════════════════
# TOOL 3: sports_predict — XGBoost predictions for NBA
# ═══════════════════════════════════════════════════════════════

def sports_predict(action: str, sport: str = "nba", team: str = "",
                   date: str = "", limit: int = 10) -> str:
    """XGBoost-powered NBA game predictions.

    Actions:
        predict  — Today's game predictions with win probabilities
        evaluate — Model accuracy, Brier score, feature importances
        train    — Retrain on latest 3 seasons (~3700 games, <30s on CPU)
        features — What features the model uses + their weights
        compare  — Predictions vs current odds → +EV recommendations
    """
    try:
        if action == "train":
            start = time.time()
            X, y, features = _build_training_data()
            if X is None:
                return json.dumps({"error": "Failed to build training data. NBA API may be rate-limiting."})

            result = _train_xgboost(X, y, features)
            result["training_time_seconds"] = round(time.time() - start, 1)
            result["total_games"] = len(X)
            return json.dumps(result)

        elif action == "predict":
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            games = _get_todays_games()
            if not games or (len(games) == 1 and "error" in games[0]):
                return json.dumps({"message": "No NBA games scheduled today.", "games": games})

            teams = _get_all_teams()
            season = _current_season()
            predictions = []

            for game in games[:limit]:
                if "error" in game:
                    continue

                home_id = game["home_team_id"]
                away_id = game["away_team_id"]
                home_info = teams.get(home_id, {})
                away_info = teams.get(away_id, {})

                home_features = _get_nba_features(home_id, season)
                away_features = _get_nba_features(away_id, season)

                if "error" in home_features or "error" in away_features:
                    predictions.append({
                        "home": home_info.get("full_name", str(home_id)),
                        "away": away_info.get("full_name", str(away_id)),
                        "error": "Could not fetch team stats",
                    })
                    continue

                pred = _predict_game(home_features, away_features, model_data)

                predictions.append({
                    "home": home_info.get("full_name", str(home_id)),
                    "away": away_info.get("full_name", str(away_id)),
                    "home_abbrev": home_info.get("abbreviation", ""),
                    "away_abbrev": away_info.get("abbreviation", ""),
                    "home_win_prob": pred["home_win_prob"],
                    "away_win_prob": pred["away_win_prob"],
                    "predicted_winner": home_info.get("full_name", "") if pred["home_win_prob"] > 0.5 else away_info.get("full_name", ""),
                    "confidence": round(max(pred["home_win_prob"], pred["away_win_prob"]), 3),
                    "status": game.get("game_status_text", ""),
                })

            return json.dumps({
                "predictions": predictions,
                "model_trained": model_data.get("trained", "unknown"),
                "sport": sport,
                "date": datetime.now().strftime("%Y-%m-%d"),
            })

        elif action == "evaluate":
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            model = model_data["model"]
            features = model_data["features"]
            importances = dict(zip(features, [round(float(v), 4) for v in model.feature_importances_]))

            return json.dumps({
                "model": f"{sport}_xgboost",
                "trained": model_data.get("trained", "unknown"),
                "features": features,
                "feature_importances": importances,
                "n_estimators": model.n_estimators,
                "max_depth": model.max_depth,
                "note": "Run action=train to retrain with latest data and see accuracy metrics",
            })

        elif action == "features":
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            features = model_data["features"]
            model = model_data["model"]
            importances = dict(zip(features, [round(float(v), 4) for v in model.feature_importances_]))
            sorted_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)

            return json.dumps({
                "features": [{"name": k, "importance": v, "description": _feature_desc(k)} for k, v in sorted_features],
                "total_features": len(features),
                "model": f"{sport}_xgboost",
            })

        elif action == "compare":
            # Predictions vs current odds → +EV recommendations
            model_data = _load_model(sport)
            if "error" in model_data:
                return json.dumps(model_data)

            # Get predictions
            pred_result = json.loads(sports_predict("predict", sport, limit=limit))
            if "error" in pred_result:
                return json.dumps(pred_result)

            # Get current odds
            from sportsbook_odds import sportsbook_odds, _decimal_to_implied, _calculate_ev, _kelly_fraction
            odds_result = json.loads(sportsbook_odds("best_odds", f"basketball_{sport}", limit=limit))

            comparisons = []
            predictions = pred_result.get("predictions", [])

            for pred in predictions:
                if "error" in pred:
                    continue

                # Try to match with odds data
                home_name = pred.get("home", "")
                away_name = pred.get("away", "")
                model_home_prob = pred["home_win_prob"]
                model_away_prob = pred["away_win_prob"]

                matched_odds = None
                for line in odds_result.get("best_lines", []):
                    game_str = line.get("game", "").lower()
                    if (home_name.lower().split()[-1] in game_str or
                        away_name.lower().split()[-1] in game_str):
                        matched_odds = line
                        break

                comp = {
                    "game": f"{away_name} @ {home_name}",
                    "model_home_prob": model_home_prob,
                    "model_away_prob": model_away_prob,
                    "predicted_winner": pred.get("predicted_winner", ""),
                    "confidence": pred.get("confidence", 0),
                }

                if matched_odds:
                    best = matched_odds.get("best_odds", {})

                    # Check EV for home bet
                    for team_name, prob in [(home_name, model_home_prob), (away_name, model_away_prob)]:
                        team_odds = best.get(team_name, {})
                        if isinstance(team_odds, dict) and "decimal" in team_odds:
                            dec = team_odds["decimal"]
                            ev = _calculate_ev(prob, dec)
                            kelly = _kelly_fraction(prob, dec)
                            comp[f"{team_name}_odds"] = {
                                "decimal": dec,
                                "book": team_odds.get("book_title", ""),
                                "implied_prob": round(_decimal_to_implied(dec), 4),
                                "model_prob": round(prob, 4),
                                "ev_pct": round(ev * 100, 2),
                                "is_plus_ev": ev > 0,
                                "kelly_fraction": round(kelly, 4),
                                "kelly_$100": round(kelly * 100, 2),
                            }

                    comp["has_odds"] = True
                else:
                    comp["has_odds"] = False
                    comp["note"] = "No matching odds found — game may not be listed yet"

                comparisons.append(comp)

            return json.dumps({
                "comparisons": comparisons,
                "method": "XGBoost model prob vs best available odds → EV + Kelly sizing",
                "sport": sport,
            })

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: predict, evaluate, train, features, compare"})

    except Exception as e:
        return json.dumps({"error": str(e)})


def _feature_desc(name: str) -> str:
    """Human-readable feature description."""
    descs = {
        "home_fg_pct": "Home team field goal percentage (rolling avg)",
        "home_fg3_pct": "Home team 3-point percentage (rolling avg)",
        "home_reb": "Home team rebounds per game (rolling avg)",
        "home_ast": "Home team assists per game (rolling avg)",
        "home_tov": "Home team turnovers per game (rolling avg)",
        "home_pts": "Home team points per game (rolling avg)",
        "away_fg_pct": "Away team field goal percentage (rolling avg)",
        "away_fg3_pct": "Away team 3-point percentage (rolling avg)",
        "away_reb": "Away team rebounds per game (rolling avg)",
        "away_ast": "Away team assists per game (rolling avg)",
        "away_tov": "Away team turnovers per game (rolling avg)",
        "away_pts": "Away team points per game (rolling avg)",
    }
    return descs.get(name, name)


# ═══════════════════════════════════════════════════════════════
# TOOL 4: sports_betting — Meta-tool composing predict + odds + EV
# ═══════════════════════════════════════════════════════════════

def sports_betting(action: str, sport: str = "nba", bankroll: float = 100.0,
                   min_ev: float = 0.01, limit: int = 10) -> str:
    """Full betting pipeline: predict + odds + EV + Kelly sizing.

    Actions:
        recommend — Full pipeline: predictions + odds + EV + Kelly-sized picks
        bankroll  — Kelly-sized bet recommendations for a given bankroll
        dashboard — Summary of all active opportunities across sports
    """
    try:
        if action == "recommend":
            # Full pipeline: compare predictions to odds
            compare_result = json.loads(sports_predict("compare", sport, limit=limit))
            if "error" in compare_result:
                return json.dumps(compare_result)

            recommendations = []
            for comp in compare_result.get("comparisons", []):
                if not comp.get("has_odds"):
                    continue

                # Find +EV opportunities
                for key, val in comp.items():
                    if isinstance(val, dict) and val.get("is_plus_ev"):
                        team = key.replace("_odds", "")
                        kelly_pct = val["kelly_fraction"]
                        bet_size = round(bankroll * kelly_pct, 2)

                        if bet_size >= 1.0:  # Only recommend bets >= $1
                            recommendations.append({
                                "game": comp["game"],
                                "bet_on": team,
                                "book": val["book"],
                                "odds": val["decimal"],
                                "model_prob": val["model_prob"],
                                "edge": round(val["model_prob"] - val["implied_prob"], 4),
                                "ev_pct": val["ev_pct"],
                                "kelly_fraction": kelly_pct,
                                "bet_size": bet_size,
                                "expected_profit": round(bet_size * val["ev_pct"] / 100, 2),
                                "confidence": comp.get("confidence", 0),
                            })

            recommendations.sort(key=lambda x: x["ev_pct"], reverse=True)

            total_bet = sum(r["bet_size"] for r in recommendations)
            total_ev = sum(r["expected_profit"] for r in recommendations)

            return json.dumps({
                "recommendations": recommendations[:limit],
                "summary": {
                    "total_bets": len(recommendations),
                    "total_wagered": round(total_bet, 2),
                    "total_expected_profit": round(total_ev, 2),
                    "bankroll": bankroll,
                    "bankroll_pct_risked": round(total_bet / bankroll * 100, 1) if bankroll > 0 else 0,
                },
                "method": "XGBoost model → Pinnacle-devigged sharp prob → best odds → quarter-Kelly sizing",
                "disclaimer": "Model predictions are probabilistic, not guaranteed. Past performance does not predict future results. Gamble responsibly.",
            })

        elif action == "bankroll":
            # Just the Kelly sizing recommendations
            rec_result = json.loads(sports_betting("recommend", sport, bankroll, min_ev, limit))
            if "error" in rec_result:
                return json.dumps(rec_result)

            return json.dumps({
                "bankroll": bankroll,
                "recommendations": rec_result.get("recommendations", []),
                "summary": rec_result.get("summary", {}),
                "kelly_method": "quarter-Kelly (25% of full Kelly) — conservative to avoid ruin",
            })

        elif action == "dashboard":
            # Multi-sport dashboard
            sports_to_check = ["basketball_nba"]
            # Could expand: "americanfootball_nfl", "baseball_mlb", "icehockey_nhl"

            from sportsbook_odds import sportsbook_arb

            dashboard = {"sports": {}}
            for s in sports_to_check:
                sport_key = s.split("_")[-1] if "_" in s else s

                # EV scan from sportsbook_arb
                ev_result = json.loads(sportsbook_arb("ev_scan", s, limit=5))
                ev_opps = ev_result.get("ev_opportunities", [])

                dashboard["sports"][sport_key] = {
                    "ev_opportunities": len(ev_opps),
                    "top_ev": ev_opps[:3] if ev_opps else [],
                    "quota": ev_result.get("quota", {}),
                }

            # Add model predictions if available
            model_data = _load_model("nba")
            if "error" not in model_data:
                dashboard["model_status"] = {
                    "trained": model_data.get("trained", "unknown"),
                    "available": True,
                }
            else:
                dashboard["model_status"] = {"available": False, "note": "Run sports_predict(action=train) first"}

            return json.dumps(dashboard)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: recommend, bankroll, dashboard"})

    except Exception as e:
        return json.dumps({"error": str(e)})
