"""
Polymarket Trading Module — Phase 2: Full Trading Engine

Wraps the `polymarket` CLI (Rust binary) for real-time prices,
arbitrage detection, portfolio watching, AND order placement.

Trading can be routed through a Cloudflare Worker proxy (POLYMARKET_PROXY_URL)
to bypass US geoblock, or falls back to direct CLI.
"""

import json
import os
import subprocess
import urllib.request
import urllib.parse
from typing import Optional


def _run_cli(args: list[str], timeout: int = 15, max_chars: int = 50000) -> dict:
    """Run a polymarket CLI command and return parsed JSON output."""
    cmd = ["polymarket", "-o", "json"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            err = result.stderr.strip() or output
            return {"error": f"CLI error (exit {result.returncode}): {err[:2000]}"}
        if not output:
            return {"error": "Empty response from CLI"}
        # Truncate before parsing if huge
        if len(output) > max_chars:
            output = output[:max_chars]
        return json.loads(output)
    except subprocess.TimeoutExpired:
        return {"error": f"CLI timed out after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from CLI: {str(e)[:200]}"}
    except Exception as e:
        return {"error": f"CLI failed: {str(e)[:500]}"}


def _resolve_token_ids(market_id: str) -> dict:
    """Resolve a market slug/ID to YES and NO CLOB token IDs.

    Returns: {"yes_token": "0x...", "no_token": "0x...", "question": "...", "condition_id": "0x..."}
    or {"error": "..."} on failure.
    """
    data = _run_cli(["markets", "get", market_id])
    if "error" in data:
        return data

    # clobTokenIds is a JSON string within JSON: "[\"0xabc\",\"0xdef\"]"
    raw_tokens = data.get("clobTokenIds", "")
    if isinstance(raw_tokens, str):
        try:
            tokens = json.loads(raw_tokens)
        except json.JSONDecodeError:
            tokens = []
    else:
        tokens = raw_tokens or []

    if len(tokens) < 2:
        return {"error": f"Market '{market_id}' has no CLOB token IDs — may not have an order book"}

    return {
        "yes_token": tokens[0],
        "no_token": tokens[1],
        "question": data.get("question", ""),
        "condition_id": data.get("conditionId", ""),
        "slug": data.get("slug", market_id),
        "market_id": data.get("id", ""),
        "outcomes": data.get("outcomes", ""),
        "active": data.get("active", False),
        "closed": data.get("closed", False),
    }


# ═══════════════════════════════════════════════════════════════════
# TOOL 1: polymarket_prices — Real-time price data
# ═══════════════════════════════════════════════════════════════════

def polymarket_prices(action: str, market_id: str = "",
                      token_id: str = "", interval: str = "1d",
                      fidelity: int = 0) -> str:
    """Get real-time price data for Polymarket markets.

    Actions:
        snapshot  — Full price snapshot (midpoint, spread, last trade, mispricing flag)
        spread    — Bid-ask spread for a token
        midpoint  — Midpoint price for a token
        book      — Full order book for a token
        last_trade — Last trade price for a token
        history   — Price history for a token (requires interval)
    """
    try:
        if action == "snapshot":
            return _snapshot(market_id)

        # For granular actions, resolve token_id if only market_id given
        tid = token_id
        if not tid and market_id:
            resolved = _resolve_token_ids(market_id)
            if "error" in resolved:
                return json.dumps(resolved)
            tid = resolved["yes_token"]  # Default to YES token

        if not tid:
            return json.dumps({"error": "Provide market_id (slug/ID) or token_id"})

        if action == "spread":
            return json.dumps(_run_cli(["clob", "spread", tid]))
        elif action == "midpoint":
            return json.dumps(_run_cli(["clob", "midpoint", tid]))
        elif action == "book":
            return json.dumps(_run_cli(["clob", "book", tid]))
        elif action == "last_trade":
            return json.dumps(_run_cli(["clob", "last-trade", tid]))
        elif action == "history":
            args = ["clob", "price-history", "--interval", interval, tid]
            if fidelity > 0:
                args.extend(["--fidelity", str(fidelity)])
            return json.dumps(_run_cli(args, timeout=20))
        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: snapshot, spread, midpoint, book, last_trade, history"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _snapshot(market_id: str) -> str:
    """Full price snapshot for a market — resolves tokens, gets midpoint+spread+last for both YES and NO."""
    if not market_id:
        return json.dumps({"error": "market_id required for snapshot"})

    resolved = _resolve_token_ids(market_id)
    if "error" in resolved:
        return json.dumps(resolved)

    yes_token = resolved["yes_token"]
    no_token = resolved["no_token"]

    # Fetch midpoint for both sides
    yes_mid = _run_cli(["clob", "midpoint", yes_token])
    no_mid = _run_cli(["clob", "midpoint", no_token])

    # Fetch spread for YES
    yes_spread = _run_cli(["clob", "spread", yes_token])

    # Fetch last trade for YES
    yes_last = _run_cli(["clob", "last-trade", yes_token])

    # Extract midpoint values
    yes_price = _extract_price(yes_mid)
    no_price = _extract_price(no_mid)

    # Mispricing detection: YES + NO should sum to ~1.00
    mispricing = None
    if yes_price is not None and no_price is not None:
        total = yes_price + no_price
        deviation = abs(total - 1.0)
        mispricing = {
            "yes_plus_no": round(total, 6),
            "deviation_from_1": round(deviation, 6),
            "is_mispriced": deviation > 0.02,  # >2 cents = notable
            "arb_opportunity": deviation > 0.05,  # >5 cents = actionable arb
        }

    return json.dumps({
        "market": {
            "question": resolved["question"],
            "slug": resolved["slug"],
            "market_id": resolved["market_id"],
            "active": resolved["active"],
            "closed": resolved["closed"],
        },
        "yes": {
            "token_id": yes_token,
            "midpoint": yes_mid,
            "spread": yes_spread,
            "last_trade": yes_last,
        },
        "no": {
            "token_id": no_token,
            "midpoint": no_mid,
        },
        "mispricing": mispricing,
    })


def _extract_price(data: dict) -> Optional[float]:
    """Extract a numeric price from CLI output. Handles various response formats."""
    if "error" in data:
        return None
    # midpoint response is usually {"mid": "0.55"} or {"midpoint": 0.55} or just a number
    for key in ("mid", "midpoint", "price", "value"):
        if key in data:
            try:
                return float(data[key])
            except (ValueError, TypeError):
                pass
    # If the response is a flat number
    if isinstance(data, (int, float)):
        return float(data)
    return None


# ═══════════════════════════════════════════════════════════════════
# TOOL 2: polymarket_monitor — Market monitoring & arb detection
# ═══════════════════════════════════════════════════════════════════

def polymarket_monitor(action: str, market_id: str = "",
                       condition_id: str = "", event_id: str = "",
                       period: str = "week", order_by: str = "pnl",
                       limit: int = 10) -> str:
    """Monitor markets, detect mispricings, view on-chain data.

    Actions:
        mispricing    — Check if YES+NO prices deviate from $1.00 (arb detector)
        open_interest — Open interest for a market (needs condition_id or market_id)
        volume        — Live volume for an event (needs event_id)
        holders       — Top token holders for a market
        leaderboard   — Top traders by PnL or volume
        health        — CLOB API health status
    """
    try:
        if action == "mispricing":
            return _check_mispricing(market_id)

        elif action == "open_interest":
            cid = condition_id
            if not cid and market_id:
                resolved = _resolve_token_ids(market_id)
                if "error" in resolved:
                    return json.dumps(resolved)
                cid = resolved["condition_id"]
            if not cid:
                return json.dumps({"error": "Provide condition_id or market_id"})
            return json.dumps(_run_cli(["data", "open-interest", cid]))

        elif action == "volume":
            if not event_id:
                return json.dumps({"error": "event_id required for volume"})
            return json.dumps(_run_cli(["data", "volume", event_id]))

        elif action == "holders":
            cid = condition_id
            if not cid and market_id:
                resolved = _resolve_token_ids(market_id)
                if "error" in resolved:
                    return json.dumps(resolved)
                cid = resolved["condition_id"]
            if not cid:
                return json.dumps({"error": "Provide condition_id or market_id"})
            return json.dumps(_run_cli(["data", "holders", cid, "--limit", str(limit)]))

        elif action == "leaderboard":
            args = ["data", "leaderboard", "--period", period,
                    "--order-by", order_by, "--limit", str(limit)]
            return json.dumps(_run_cli(args))

        elif action == "health":
            return json.dumps(_run_cli(["clob", "ok"]))

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: mispricing, open_interest, volume, holders, leaderboard, health"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _check_mispricing(market_id: str) -> str:
    """Check a market for YES+NO price deviation from $1.00."""
    if not market_id:
        return json.dumps({"error": "market_id required for mispricing check"})

    resolved = _resolve_token_ids(market_id)
    if "error" in resolved:
        return json.dumps(resolved)

    yes_mid = _run_cli(["clob", "midpoint", resolved["yes_token"]])
    no_mid = _run_cli(["clob", "midpoint", resolved["no_token"]])

    yes_price = _extract_price(yes_mid)
    no_price = _extract_price(no_mid)

    if yes_price is None or no_price is None:
        return json.dumps({
            "market": resolved["question"],
            "slug": resolved["slug"],
            "error": "Could not get midpoint prices",
            "yes_raw": yes_mid,
            "no_raw": no_mid,
        })

    total = yes_price + no_price
    deviation = abs(total - 1.0)

    return json.dumps({
        "market": resolved["question"],
        "slug": resolved["slug"],
        "yes_midpoint": yes_price,
        "no_midpoint": no_price,
        "sum": round(total, 6),
        "deviation": round(deviation, 6),
        "is_mispriced": deviation > 0.02,
        "arb_opportunity": deviation > 0.05,
        "analysis": (
            f"YES={yes_price:.4f} + NO={no_price:.4f} = {total:.4f}. "
            f"Deviation: {deviation:.4f} from $1.00. "
            + ("ARBITRAGE OPPORTUNITY!" if deviation > 0.05
               else "Notable mispricing." if deviation > 0.02
               else "Prices are fair.")
        ),
    })


# ═══════════════════════════════════════════════════════════════════
# TOOL 3: polymarket_portfolio — Wallet/portfolio viewing
# ═══════════════════════════════════════════════════════════════════

def polymarket_portfolio(action: str, address: str = "",
                         limit: int = 25) -> str:
    """View any wallet's positions, trades, and on-chain activity (read-only).

    Actions:
        positions  — Open positions for a wallet
        closed     — Closed/resolved positions
        trades     — Trade history for a wallet
        value      — Total portfolio value
        activity   — On-chain activity log
        profile    — Public profile info
    """
    try:
        if not address:
            return json.dumps({"error": "address (0x...) required for portfolio queries"})

        if action == "positions":
            return json.dumps(_run_cli(["data", "positions", address, "--limit", str(limit)]))
        elif action == "closed":
            return json.dumps(_run_cli(["data", "closed-positions", address, "--limit", str(limit)]))
        elif action == "trades":
            return json.dumps(_run_cli(["data", "trades", address, "--limit", str(limit)]))
        elif action == "value":
            return json.dumps(_run_cli(["data", "value", address]))
        elif action == "activity":
            return json.dumps(_run_cli(["data", "activity", address, "--limit", str(limit)]))
        elif action == "profile":
            return json.dumps(_run_cli(["profiles", "get", address]))
        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: positions, closed, trades, value, activity, profile"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ═══════════════════════════════════════════════════════════════════
# TOOL 4: polymarket_trade — Order placement (safety-checked)
# ═══════════════════════════════════════════════════════════════════

def polymarket_trade(action: str, market_id: str = "", side: str = "yes",
                     price: float = 0.0, size: float = 0.0,
                     order_id: str = "", dry_run: Optional[bool] = None) -> str:
    """Place, cancel, and manage Polymarket orders.

    Actions:
        buy         — Limit order to buy YES or NO tokens
        sell        — Limit order to sell
        market_buy  — Market order (takes best available)
        market_sell — Market sell
        cancel      — Cancel a specific order
        cancel_all  — Cancel all open orders
        list_orders — List current open orders

    Routes through Cloudflare proxy if POLYMARKET_PROXY_URL is set (bypasses geoblock).
    All orders pass through safety checks. dry_run=True (default) simulates.
    """
    try:
        from trading_safety import check_order_safety, log_trade, _load_config
        cfg = _load_config()
        is_dry = dry_run if dry_run is not None else cfg.dry_run

        if action in ("buy", "sell", "market_buy", "market_sell"):
            if not market_id:
                return json.dumps({"error": "market_id required for trading"})

            # Convert to cents for safety check
            price_cents = int(price * 100) if price else 50
            count = max(int(size), 1)

            safety = check_order_safety("polymarket", market_id, side, price_cents, count)
            if not safety["ok"]:
                log_trade("polymarket", action, {
                    "market_id": market_id, "side": side, "price": price, "size": size,
                    "blocked": True, "reason": safety["reason"], "dry_run": is_dry,
                })
                return json.dumps({"blocked": True, "reason": safety["reason"]})

            if is_dry:
                # Resolve token to show what would happen
                resolved = _resolve_token_ids(market_id)
                token_info = {}
                if "error" not in resolved:
                    token_info = {
                        "token_id": resolved["yes_token"] if side.lower() == "yes" else resolved["no_token"],
                        "question": resolved["question"],
                    }

                result = {
                    "simulated": True,
                    "action": action,
                    "market_id": market_id,
                    "side": side,
                    "price": price,
                    "size": size,
                    "order_value_usd": f"${price * size:.2f}" if price and size else "market price",
                    **token_info,
                    "message": "DRY RUN — no real order placed. Set dry_run=false to go live.",
                }
                log_trade("polymarket", action, {**result, "dry_run": True})
                return json.dumps(result)

            # Real order
            return _execute_polymarket_order(action, market_id, side, price, size)

        elif action == "cancel":
            if not order_id:
                return json.dumps({"error": "order_id required for cancel"})
            if is_dry:
                result = {"simulated": True, "action": "cancel", "order_id": order_id}
                log_trade("polymarket", "cancel", {**result, "dry_run": True})
                return json.dumps(result)
            return json.dumps(_run_cli(["clob", "cancel", order_id]))

        elif action == "cancel_all":
            if is_dry:
                result = {"simulated": True, "action": "cancel_all"}
                log_trade("polymarket", "cancel_all", {**result, "dry_run": True})
                return json.dumps(result)
            return json.dumps(_run_cli(["clob", "cancel-all"]))

        elif action == "list_orders":
            return json.dumps(_run_cli(["clob", "orders"]))

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: buy, sell, market_buy, market_sell, cancel, cancel_all, list_orders"})

    except Exception as e:
        return json.dumps({"error": str(e)})


def _execute_polymarket_order(action: str, market_id: str, side: str,
                              price: float, size: float) -> str:
    """Execute a real Polymarket order — tries proxy first, then direct CLI."""
    from trading_safety import log_trade

    proxy_url = os.environ.get("POLYMARKET_PROXY_URL", "")

    # Try Cloudflare Worker proxy first (bypasses US geoblock)
    if proxy_url:
        try:
            payload = json.dumps({
                "action": action,
                "market_id": market_id,
                "side": side,
                "price": price,
                "size": size,
            }).encode()
            req = urllib.request.Request(
                f"{proxy_url}/trade",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                log_trade("polymarket", action, {
                    "market_id": market_id, "side": side, "price": price, "size": size,
                    "via": "proxy", "dry_run": False, "response": str(result)[:500],
                })
                return json.dumps(result)
        except Exception as e:
            logger_msg = f"Proxy failed, trying direct CLI: {e}"

    # Fallback: direct CLI
    resolved = _resolve_token_ids(market_id)
    if "error" in resolved:
        return json.dumps(resolved)

    token_id = resolved["yes_token"] if side.lower() == "yes" else resolved["no_token"]

    if action in ("market_buy", "market_sell"):
        cli_args = ["clob", "market-order", "--token", token_id, "--amount", str(size)]
        if action == "market_sell":
            cli_args.append("--sell")
    else:
        cli_args = ["clob", "create-order", "--token", token_id,
                     "--price", str(price), "--size", str(size)]
        if action == "sell":
            cli_args.append("--sell")

    result = _run_cli(cli_args, timeout=30)

    # Check for geoblock
    err = result.get("error", "")
    if "403" in err or "geoblock" in err.lower() or "forbidden" in err.lower():
        result["geoblock_note"] = "US VPS is geoblocked. Set POLYMARKET_PROXY_URL to route through Cloudflare Worker."

    log_trade("polymarket", action, {
        "market_id": market_id, "side": side, "price": price, "size": size,
        "via": "cli", "dry_run": False, "response": str(result)[:500],
    })

    return json.dumps(result)


# ═══════════════════════════════════════════════════════════════════
# TOOL 5: polymarket_balance — Wallet balance and approval status
# ═══════════════════════════════════════════════════════════════════

def polymarket_balance(action: str = "balance") -> str:
    """Check Polymarket wallet balance and approval status.

    Actions:
        balance  — USDC balance on Polygon
        approval — Check if CLOB contract is approved for trading
    """
    try:
        if action == "balance":
            result = _run_cli(["clob", "balance"])
            return json.dumps(result)

        elif action == "approval":
            result = _run_cli(["clob", "check-approval"])
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown action '{action}'. Use: balance, approval"})

    except Exception as e:
        return json.dumps({"error": str(e)})
