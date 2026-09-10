#!/usr/bin/env python3
"""
Backtest for strategies/* on candles_asset_1861_60s_365d.csv

Replicates the LIVE bot behaviour exactly:
  - Candles are fed one-by-one, in chronological order, into
    Strategy.update_candle(60, candle) -- the same method bot.py calls.
  - A signal (if any) is generated at the OPEN of candle[i], based on the
    just-closed candle[i-1]. The trade entry price = open[i].
  - For a 60s expiration, the expiry price is the price at ts[i]+60, i.e.
    open[i+1] when data is contiguous, else close[i] (gap fallback).
  - CALL wins if expiry_price > entry_price, PUT wins if <, else DRAW.
  - MAX_CONCURRENT_TRADES=1 is enforced (only matters for expiry > 60s).

No look-ahead: the strategy only ever sees completed[:-1] internally.

Stdlib only (no pandas/numpy needed).

Usage:
  python3 backtest.py                                  # v1 (emacombo)
  python3 backtest.py --strategy emacombo_v2 --prefix backtest_v2
"""
import argparse
import csv
import importlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

CSV_FILE = "candles_asset_1861_60s_365d.csv"
EXPIRATIONS = [60, 120, 300]   # primary = 60s
PAYOUTS = [0.70, 0.75, 0.80, 0.85, 0.90]
BASE_PAYOUT = 0.80             # IQ Option typical ~70-90%

MAX_CONCURRENT = 1


def load_candles(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "timestamp": float(r["timestamp"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
            })
    rows.sort(key=lambda c: c["timestamp"])
    return rows


def run_backtest(candles, expiration, Strategy):
    strat = Strategy()
    ts = [c["timestamp"] for c in candles]
    index_of = {t: i for i, t in enumerate(ts)}

    trades = []
    skipped_overlap = 0
    incomplete_at_end = 0
    no_trade_reasons = Counter()
    busy_until = None  # timestamp until which a trade is running

    for i, c in enumerate(candles):
        signal = strat.update_candle(60, dict(c))
        st = strat.get_status()
        if signal is None:
            no_trade_reasons[st.get("no_trade_reason") or "UNKNOWN"] += 1
            continue

        entry_ts = c["timestamp"]
        entry_price = c["open"]

        # MAX_CONCURRENT_TRADES = 1  (same as bot.place_trade guard)
        if busy_until is not None and entry_ts < busy_until:
            skipped_overlap += 1
            continue

        expiry_time = entry_ts + expiration
        # expiry price = price at exact expiry instant:
        # if expiry aligns on a candle boundary, use that candle's open
        if expiry_time in index_of:
            j = index_of[expiry_time]
            expiry_price = candles[j]["open"]
            contiguous = (j == i + expiration // 60)
        else:
            # gap (weekend) or past end of data -> fallback
            # find last candle at/before expiry_time
            j = None
            for k in range(len(candles) - 1, -1, -1):
                if ts[k] <= expiry_time:
                    j = k
                    break
            if j is None or j <= i:
                incomplete_at_end += 1
                continue
            expiry_price = candles[j]["close"]
            contiguous = False

        if signal == "CALL":
            result = "WIN" if expiry_price > entry_price else ("DRAW" if expiry_price == entry_price else "LOSS")
        else:
            result = "WIN" if expiry_price < entry_price else ("DRAW" if expiry_price == entry_price else "LOSS")

        closed = candles[i - 1]  # signal candle (just closed)
        gap_entry = (entry_ts - ts[i - 1]) != 60 if i > 0 else False

        trades.append({
            "n": len(trades) + 1,
            "entry_time": entry_ts,
            "entry_dt": datetime.fromtimestamp(entry_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "expiry_dt": datetime.fromtimestamp(expiry_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "direction": signal,
            "module": st.get("last_module"),
            "market_direction": st.get("direction"),
            "entry_price": entry_price,
            "expiry_price": expiry_price,
            "result": result,
            "pips": (expiry_price - entry_price) * (1 if signal == "CALL" else -1),
            "gap_entry": gap_entry,
            "contiguous_expiry": contiguous,
            "sig_hour": datetime.fromtimestamp(closed["timestamp"], tz=timezone.utc).hour,
            "sig_weekday": datetime.fromtimestamp(closed["timestamp"], tz=timezone.utc).strftime("%a"),
            "sig_month": datetime.fromtimestamp(closed["timestamp"], tz=timezone.utc).strftime("%Y-%m"),
            "ema9": st.get("ema9_1m"),
            "ema12": st.get("ema12_1m"),
            "atr": st.get("atr_1m"),
        })
        busy_until = expiry_time

    return trades, skipped_overlap, incomplete_at_end, no_trade_reasons


def wilson_ci(wins, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / den), min(1.0, (c + m) / den))


def summarize(trades, payout, label):
    wins = sum(1 for t in trades if t["result"] == "WIN")
    losses = sum(1 for t in trades if t["result"] == "LOSS")
    draws = sum(1 for t in trades if t["result"] == "DRAW")
    decided = wins + losses
    wr = wins / decided if decided else 0.0
    be = 1 / (1 + payout)
    gross_profit = wins * payout
    gross_loss = losses * 1.0
    net = gross_profit - gross_loss
    pf = gross_profit / gross_loss if gross_loss else float("inf")
    exp = net / decided if decided else 0.0
    lo, hi = wilson_ci(wins, decided)
    # z-test vs breakeven
    if decided:
        se = math.sqrt(be * (1 - be) / decided)
        z = (wr - be) / se if se else 0.0
        # two-sided p-value from normal approx
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    else:
        z, p = 0.0, 1.0

    # streaks & drawdown (in R, draws = 0)
    eq, peak, maxdd = 0.0, 0.0, 0.0
    curve = [0.0]
    cw = cl_ = 0
    maxw = maxl = 0
    for t in trades:
        r = payout if t["result"] == "WIN" else (-1.0 if t["result"] == "LOSS" else 0.0)
        eq += r
        curve.append(eq)
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
        if t["result"] == "WIN":
            cw += 1
            cl_ = 0
            maxw = max(maxw, cw)
        elif t["result"] == "LOSS":
            cl_ += 1
            cw = 0
            maxl = max(maxl, cl_)

    return {
        "label": label,
        "trades": len(trades), "wins": wins, "losses": losses, "draws": draws,
        "winrate": round(wr * 100, 2),
        "winrate_ci95": [round(lo * 100, 2), round(hi * 100, 2)],
        "breakeven_wr": round(be * 100, 2),
        "z_vs_breakeven": round(z, 3),
        "p_value": round(p, 4),
        "net_R": round(net, 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else None,
        "expectancy_R": round(exp, 4),
        "max_drawdown_R": round(maxdd, 2),
        "max_win_streak": maxw,
        "max_loss_streak": maxl,
        "_curve": curve,
    }


def breakdown(trades, key, payout):
    groups = defaultdict(list)
    for t in trades:
        groups[t[key]].append(t)
    out = {}
    for k in sorted(groups, key=str):
        out[str(k)] = summarize(groups[k], payout, f"{key}={k}")
        out[str(k)].pop("_curve", None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="emacombo")
    ap.add_argument("--prefix", default="backtest")
    ap.add_argument("--payout", type=float, default=BASE_PAYOUT)
    args = ap.parse_args()

    Strategy = importlib.import_module(f"strategies.{args.strategy}").Strategy
    print(f"Strategy: strategies.{args.strategy} -> prefix '{args.prefix}'")

    candles = load_candles(CSV_FILE)
    first = datetime.fromtimestamp(candles[0]["timestamp"], tz=timezone.utc)
    last = datetime.fromtimestamp(candles[-1]["timestamp"], tz=timezone.utc)
    print(f"Candles: {len(candles)} | {first} -> {last} "
          f"({(candles[-1]['timestamp'] - candles[0]['timestamp']) / 86400:.1f} days)")

    all_results = {"strategy": args.strategy,
                   "data": {"candles": len(candles),
                            "first": first.strftime("%Y-%m-%d %H:%M UTC"),
                            "last": last.strftime("%Y-%m-%d %H:%M UTC"),
                            "days": round((candles[-1]["timestamp"] - candles[0]["timestamp"]) / 86400, 1)}}

    for exp in EXPIRATIONS:
        trades, skipped, incomplete, reasons = run_backtest(candles, exp, Strategy)
        s = summarize(trades, args.payout, f"expiry={exp}s")
        s["skipped_overlap"] = skipped
        s["incomplete_at_end"] = incomplete
        print(f"\n=== Expiry {exp}s === "
              f"trades={s['trades']} W={s['wins']} L={s['losses']} D={s['draws']} "
              f"WR={s['winrate']}% net={s['net_R']}R PF={s['profit_factor']} "
              f"(skipped_overlap={skipped}, incomplete={incomplete})")
        all_results[f"expiry_{exp}s"] = {k: v for k, v in s.items() if k != "_curve"}
        if exp == 60:
            all_results["no_trade_reasons"] = dict(reasons.most_common())

            # payout sensitivity
            sens = {}
            for p in PAYOUTS:
                    ps = summarize(trades, p, f"payout={p}")
                    sens[f"{int(p * 100)}%"] = {"net_R": ps["net_R"],
                                                "expectancy_R": ps["expectancy_R"],
                                                "profit_factor": ps["profit_factor"],
                                                "breakeven_wr": ps["breakeven_wr"]}
            all_results["payout_sensitivity_60s"] = sens

            # breakdowns @80%
            for key in ("module", "direction", "market_direction", "sig_hour",
                        "sig_weekday", "sig_month", "gap_entry",
                        "contiguous_expiry"):
                all_results[f"by_{key}"] = breakdown(trades, key, args.payout)

            # per-trade CSV
            tpath = f"{args.prefix}_trades_60s.csv"
            with open(tpath, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
                w.writeheader()
                w.writerows(trades)
            print(f"wrote {tpath} ({len(trades)} trades)")
            all_results["expiry_60s"]["equity_curve_R"] = s["_curve"]

    spath = f"{args.prefix}_summary.json"
    with open(spath, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"wrote {spath}")


if __name__ == "__main__":
    main()
