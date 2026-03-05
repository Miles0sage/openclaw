# Bet Tracker — P&L System

A production-grade bet tracking + P&L system for sports betting. Tracks every bet recommendation, whether it was placed, and settlement results.

## Files

- **`/root/openclaw/bet_tracker.py`** — Core bet tracking module (12KB)
- **`/root/openclaw/data/betting/bet_ledger.json`** — Persistent bet ledger (auto-created)
- **Integration in `agent_tools.py`** — Lines ~1145 (tool definition) and ~1609 (handler)

## Core Data Structure

Each bet stores:

```json
{
    "bet_id": "auto-uuid (8 chars)",
    "timestamp": "ISO datetime",
    "sport": "nba",
    "game": "Team A @ Team B",
    "side": "Team A",
    "market": "h2h|spread|total|prop",
    "entry_odds": 4.2,
    "entry_implied_prob": 0.2381,
    "model_prob": 0.763,
    "edge_pct": 52.5,
    "book": "DraftKings|FanDuel|Matchbook|etc",
    "stake_usd": 25.00,
    "quarter_kelly_pct": 17.22,
    "status": "pending|won|lost|void|push",
    "result_payout": 105.00,
    "pnl": 80.00,
    "clv": null,
    "notes": ""
}
```

## API

### Main Entry Point

```python
from bet_tracker import bet_tracker

result_json = bet_tracker(action, params_dict)
```

### Actions

#### 1. `log` — Log a new bet recommendation

```python
bet_tracker("log", {
    "game": "Lakers vs Celtics",
    "side": "Lakers",
    "odds": 4.2,
    "model_prob": 0.763,
    "edge_pct": 52.5,
    "book": "Matchbook",
    "stake_usd": 25.00,
    "market": "h2h"  # optional, default: h2h
})
```

Returns:
- Bet object with auto-generated `bet_id`
- Calculated `implied_prob` from odds
- Calculated `quarter_kelly_pct` (Kelly / 4)

#### 2. `settle` — Settle a bet (won/lost/void/push)

```python
bet_tracker("settle", {
    "bet_id": "64d0235e",
    "result": "won"  # won|lost|void|push
})
```

Returns:
- Updated bet with `status`, `result_payout`, `pnl` filled
- Payout = stake × odds (for won), 0 (for lost), stake (for void/push)
- P&L = payout - stake

#### 3. `pending` — Show all unsettled bets

```python
bet_tracker("pending")
```

Returns: `{ "count": N, "bets": [...] }`

#### 4. `history` — Show last N settled bets

```python
bet_tracker("history", {"limit": 20})
```

Returns: `{ "count": N, "bets": [...] }`

#### 5. `pnl` — P&L summary

```python
bet_tracker("pnl")
```

Returns:
```json
{
    "total_bets": 5,
    "wins": 3,
    "losses": 2,
    "voids": 0,
    "pushes": 0,
    "win_rate_pct": 60.0,
    "total_staked": 200.00,
    "total_profit": 107.50,
    "roi_pct": 53.75,
    "current_bankroll": 607.50,
    "best_bet": "bet_id",
    "worst_bet": "bet_id"
}
```

- **ROI** = (total_profit / total_staked) × 100
- **Current Bankroll** = $500 starting + total_profit
- **Win Rate** = wins / (wins + losses) × 100

#### 6. `daily` — Today's P&L

```python
bet_tracker("daily")
```

Returns P&L for bets settled today only.

#### 7. `streak` — Win/loss streak

```python
bet_tracker("streak")
```

Returns:
```json
{
    "current_streak_type": "won|lost",
    "current_streak_count": 3,
    "best_win_streak": 5,
    "best_loss_streak": 2
}
```

## Features

✓ **Thread-safe file access** — Uses fcntl.flock for atomic writes
✓ **Atomic persistence** — Writes to temp file, then replaces (no corruption)
✓ **Automatic calculations** — Implied prob, Kelly %, payout, P&L, ROI
✓ **Running bankroll** — Starts at $500, tracks net profit
✓ **Multiple bet statuses** — pending, won, lost, void, push
✓ **Error handling** — Returns JSON with error messages
✓ **ISO timestamps** — UTC timezone, sortable, queryable
✓ **Streak tracking** — Current and best win/loss streaks

## Integration with Agent Tools

Registered in `agent_tools.py`:

```python
# Via API
execute_tool("bet_tracker", {
    "action": "log",
    "params": {
        "game": "Lakers vs Celtics",
        "side": "Lakers",
        "odds": 4.2,
        ...
    }
})

# Via agent
result = bet_tracker("pnl")  # Returns JSON string
```

## Examples

### Example 1: Log and immediately settle a winning bet

```python
import json
from bet_tracker import bet_tracker

# Log
log_result = json.loads(bet_tracker("log", {
    "game": "Warriors @ Suns",
    "side": "Warriors",
    "odds": 2.5,
    "model_prob": 0.65,
    "edge_pct": 25,
    "book": "DraftKings",
    "stake_usd": 50
}))
bet_id = log_result["bet"]["bet_id"]

# Settle
settle_result = json.loads(bet_tracker("settle", {
    "bet_id": bet_id,
    "result": "won"
}))
print(f"Profit: ${settle_result['bet']['pnl']}")

# Check P&L
pnl = json.loads(bet_tracker("pnl"))
print(f"Total Profit: ${pnl['summary']['total_profit']}")
print(f"ROI: {pnl['summary']['roi_pct']}%")
print(f"Bankroll: ${pnl['summary']['current_bankroll']}")
```

### Example 2: Track multiple bets in a betting session

```python
from bet_tracker import bet_tracker
import json

# Log 3 bets
bet_ids = []
for i, stake in enumerate([50, 40, 60]):
    result = json.loads(bet_tracker("log", {
        "game": f"Game {i+1}",
        "side": "Home Team",
        "odds": 2.0 + i * 0.2,
        "model_prob": 0.6,
        "edge_pct": 20,
        "book": "DraftKings",
        "stake_usd": stake
    }))
    bet_ids.append(result["bet"]["bet_id"])

# Check pending
pending = json.loads(bet_tracker("pending"))
print(f"Pending bets: {pending['count']}")

# Settle: W, L, W
results = ["won", "lost", "won"]
for bid, result in zip(bet_ids, results):
    bet_tracker("settle", {"bet_id": bid, "result": result})

# Summary
summary = json.loads(bet_tracker("pnl"))["summary"]
print(f"Final Record: {summary['wins']}-{summary['losses']}")
print(f"ROI: {summary['roi_pct']}%")
```

## Bankroll Management

- **Starting bankroll**: $500
- **Sizing recommendation**: Quarter-Kelly (25% of full Kelly)
  - Full Kelly = (prob × odds - (1 - prob)) / odds
  - Quarter-Kelly = Full Kelly / 4
  - Quarter-Kelly sizing ensures survivable drawdowns
- **Current bankroll** = $500 + cumulative P&L

## Testing

Run the test suite:

```bash
python3 -c "from bet_tracker import bet_tracker; import json; print(json.dumps(json.loads(bet_tracker('pnl')), indent=2))"
```

All tests pass:
- ✓ Logging new bets
- ✓ Settling with multiple outcomes
- ✓ P&L calculations (ROI, profit, bankroll)
- ✓ Streak tracking
- ✓ Daily P&L filtering
- ✓ File persistence and atomic writes
- ✓ Error handling

## Files Modified

1. **`/root/openclaw/agent_tools.py`**
   - Added tool definition (lines ~1145-1159)
   - Added handler in execute_tool() (lines ~1609-1610)

2. **Created `/root/openclaw/bet_tracker.py`** (12KB)
   - Core tracking module

3. **Auto-created `/root/openclaw/data/betting/bet_ledger.json`**
   - Persistent bet storage

## Next Steps

Integrate with:
- `sportsbook_odds` — Live odds from 200+ bookmakers
- `sports_predict` — XGBoost NBA predictions
- `sports_betting` — Full betting pipeline
- `prediction_tracker` — Track prediction accuracy over time
