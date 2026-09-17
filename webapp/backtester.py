"""Backtest runner for the web app.

Same settlement logic as backtest.py: signal fires at the OPEN of candle[i]
based on candle[i-1] (no look-ahead), entry = open[i], expiry price = the
price at entry_ts + expiration (open of that candle when it exists, else the
last close at/before expiry). MAX_CONCURRENT=1 is enforced.
"""
from __future__ import annotations

import csv
import glob
import os
from collections import Counter
from datetime import datetime, timezone

from .engine import StrategyRunner

DATA_GLOB = "candles_asset_*_*s_*d.csv"


def list_datasets(root: str = ".") -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(root, DATA_GLOB))):
        name = os.path.basename(path)
        try:
            with open(path, newline="") as f:
                rows = sum(1 for _ in f) - 1
        except Exception:
            rows = 0
        tf = 60
        for part in name.replace(".csv", "").split("_"):
            if part.endswith("s") and part[:-1].isdigit():
                tf = int(part[:-1])
        out.append({"file": name, "path": path, "rows": rows, "timeframe": tf})
    return out


def load_candles(path: str) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({
                    "timestamp": float(r["timestamp"]),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                })
            except (KeyError, ValueError):
                continue
    rows.sort(key=lambda c: c["timestamp"])
    return rows


def _filter_range(candles, start=None, end=None):
    def to_ts(v):
        if not v:
            return None
        try:
            return datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None
    s, e = to_ts(start), to_ts(end)
    if s:
        candles = [c for c in candles if c["timestamp"] >= s]
    if e:
        candles = [c for c in candles if c["timestamp"] <= e + 86399]
    return candles


def run(strategy_module=None, strategy_path=None, dataset_path=None,
        expiration=60, payout=0.80, stake=1.0, start=None, end=None,
        timeframe=60, label=None):
    runner = StrategyRunner(module_name=strategy_module, source_path=strategy_path)
    Strategy = runner.module.Strategy
    strat = Strategy()

    candles = _filter_range(load_candles(dataset_path), start, end)
    if len(candles) < 30:
        raise ValueError("Not enough candles in the selected range.")

    ts = [c["timestamp"] for c in candles]
    index_of = {t: i for i, t in enumerate(ts)}

    trades, equity = [], []
    balance = 0.0
    peak, max_dd = 0.0, 0.0
    streak, best_win_streak, worst_loss_streak = 0, 0, 0
    reasons = Counter()
    hourly = {}
    busy_until = None
    skipped_overlap = 0

    for i, c in enumerate(candles):
        try:
            signal = strat.update_candle(timeframe, dict(c))
        except Exception:
            signal = None
        st = strat.get_status() if hasattr(strat, "get_status") else {}
        if not signal:
            reasons[(st or {}).get("no_trade_reason") or "NO_SIGNAL"] += 1
            continue

        entry_ts = c["timestamp"]
        entry_price = c["open"]
        if busy_until is not None and entry_ts < busy_until:
            skipped_overlap += 1
            continue

        expiry_time = entry_ts + expiration
        if expiry_time in index_of:
            expiry_price = candles[index_of[expiry_time]]["open"]
        else:
            j = None
            for k in range(len(candles) - 1, -1, -1):
                if ts[k] <= expiry_time:
                    j = k
                    break
            if j is None or j <= i:
                continue
            expiry_price = candles[j]["close"]

        direction = str(signal).upper()
        if direction in ("BUY", "UP"):
            direction = "CALL"
        if direction in ("SELL", "DOWN"):
            direction = "PUT"

        if direction == "CALL":
            result = ("WIN" if expiry_price > entry_price
                      else "DRAW" if expiry_price == entry_price else "LOSS")
        else:
            result = ("WIN" if expiry_price < entry_price
                      else "DRAW" if expiry_price == entry_price else "LOSS")

        profit = stake * payout if result == "WIN" else (-stake if result == "LOSS" else 0.0)
        balance += profit
        peak = max(peak, balance)
        max_dd = max(max_dd, peak - balance)

        if result == "WIN":
            streak = streak + 1 if streak > 0 else 1
            best_win_streak = max(best_win_streak, streak)
        elif result == "LOSS":
            streak = streak - 1 if streak < 0 else -1
            worst_loss_streak = min(worst_loss_streak, streak)

        dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
        h = hourly.setdefault(dt.hour, {"hour": dt.hour, "wins": 0, "losses": 0, "draws": 0})
        h[{"WIN": "wins", "LOSS": "losses", "DRAW": "draws"}[result]] += 1

        trades.append({
            "n": len(trades) + 1,
            "entry_time": entry_ts,
            "entry_dt": dt.strftime("%Y-%m-%d %H:%M"),
            "direction": direction,
            "entry_price": entry_price,
            "expiry_price": expiry_price,
            "result": result,
            "profit": round(profit, 4),
            "balance": round(balance, 4),
            "module": (st or {}).get("last_module"),
        })
        equity.append({"n": len(trades), "balance": round(balance, 4), "t": entry_ts})
        busy_until = expiry_time

    wins = sum(1 for t in trades if t["result"] == "WIN")
    losses = sum(1 for t in trades if t["result"] == "LOSS")
    draws = sum(1 for t in trades if t["result"] == "DRAW")
    decided = wins + losses

    for h in hourly.values():
        d = h["wins"] + h["losses"]
        h["winrate"] = round(h["wins"] / d * 100, 2) if d else 0.0
        h["trades"] = d + h["draws"]

    span = ""
    if candles:
        span = (datetime.fromtimestamp(candles[0]["timestamp"], tz=timezone.utc)
                .strftime("%Y-%m-%d") + " → " +
                datetime.fromtimestamp(candles[-1]["timestamp"], tz=timezone.utc)
                .strftime("%Y-%m-%d"))

    return {
        "label": label or strategy_module or "custom",
        "dataset": os.path.basename(dataset_path),
        "range": span,
        "candles": len(candles),
        "expiration": expiration,
        "payout": payout,
        "stake": stake,
        "trades": len(trades),
        "wins": wins, "losses": losses, "draws": draws,
        "winrate": round(wins / decided * 100, 2) if decided else 0.0,
        "breakeven_winrate": round(100 / (1 + payout), 2),
        "pnl": round(balance, 2),
        "roi": round(balance / (stake * len(trades)) * 100, 2) if trades else 0.0,
        "max_drawdown": round(max_dd, 2),
        "best_win_streak": best_win_streak,
        "worst_loss_streak": abs(worst_loss_streak),
        "skipped_overlap": skipped_overlap,
        "top_reasons": reasons.most_common(8),
        "hourly": sorted(hourly.values(), key=lambda x: x["hour"]),
        "equity": equity,
        "trade_list": trades[-300:],
    }
