"""
backtest/engine.py
Event-driven backtest engine for leveraged CFD scalping.

Models the exact mechanics of a bot-managed leveraged position:

  * Margin    : $AMOUNT (default $10) at LEVERAGE x (default 800).
                Notional exposure = AMOUNT * LEVERAGE.
  * PnL       : notional * (price move %), capped at -AMOUNT (margin).
  * Liquidation: a move of 1/LEVERAGE (0.125% @ 800x) against the position wipes
                the entire margin. Any stop placed wider than that is irrelevant
                because the position is force-closed first.
  * SL/TP     : computed from ATR at entry (sl_atr / tp_atr multipliers) and
                managed by the bot (never sent to the broker), exactly like the
                production bot's design.
  * Trailing  : optional, re-priced from the prior bar's close (no lookahead).
  * Spread    : half charged at entry, half at exit (buy at ask, sell at bid).

Fill model (realistic, no lookahead):
  * A signal at the CLOSE of bar i is filled at the OPEN of bar i+1.
  * Within a bar, the conservative path is assumed: for a long, if both SL and
    TP are inside the bar's range, SL is taken first. Liquidation is taken when
    it occurs before the stop (i.e. the stop is wider than the liquidation
    distance). Gaps are honoured via open() vs stop/limit comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.indicators import atr


@dataclass
class BacktestConfig:
    amount: float = 10.0
    leverage: int = 800
    spread: float = 0.00015          # price units (e.g. 0.00015 ~ 1.5 pips EURUSD)
    start_balance: float = 1000.0
    atr_period: int = 14
    commission_per_trade: float = 0.0


def _make_trade(meta: dict) -> dict:
    return meta


def run_backtest(df: pd.DataFrame, signals: pd.Series, exits: dict, cfg: BacktestConfig):
    """
    Run the backtest.

    Returns (trades, equity_curve, stats):
        trades       list[dict]  full trade ledger
        equity_curve list[(time, equity)]  realized equity at each close event
        stats        dict        aggregate performance metrics
    """
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    t = df["time"].to_numpy() if "time" in df.columns else np.arange(len(df))
    a = atr(df, cfg.atr_period).to_numpy()
    sig = signals.reindex(df.index).fillna(0).to_numpy().astype(int)

    n = len(df)
    sl_atr = float(exits.get("sl_atr", 2.0))
    tp_atr = float(exits.get("tp_atr", 3.0))
    trail_atr = exits.get("trail_atr", None)
    max_bars = exits.get("max_bars", None)
    half_spread = cfg.spread / 2.0
    liq_frac = 1.0 / cfg.leverage

    equity = cfg.start_balance
    trades: list[dict] = []
    equity_curve: list[tuple] = []
    pos = None  # open position state dict

    for i in range(n):
        # ---- 1. manage the open position against this bar's OHLC ---------- #
        if pos is not None:
            side = pos["side"]
            stop = pos["sl"]
            if trail_atr and i > pos["idx"] and i >= 1 and np.isfinite(a[i - 1]):
                if side == 1:
                    tstop = c[i - 1] - trail_atr * a[i - 1]
                    stop = max(stop, tstop)
                else:
                    tstop = c[i - 1] + trail_atr * a[i - 1]
                    stop = min(stop, tstop)

            exit_raw = None
            reason = None
            if side == 1:
                if l[i] <= pos["liq"] and pos["sl"] < pos["liq"]:
                    exit_raw, reason = min(o[i], pos["liq"]), "LIQUIDATION"
                elif l[i] <= stop:
                    exit_raw, reason = min(o[i], stop), "STOP_LOSS"
                elif h[i] >= pos["tp"]:
                    exit_raw, reason = max(o[i], pos["tp"]), "TAKE_PROFIT"
            else:
                if h[i] >= pos["liq"] and pos["sl"] > pos["liq"]:
                    exit_raw, reason = max(o[i], pos["liq"]), "LIQUIDATION"
                elif h[i] >= stop:
                    exit_raw, reason = max(o[i], stop), "STOP_LOSS"
                elif l[i] <= pos["tp"]:
                    exit_raw, reason = min(o[i], pos["tp"]), "TAKE_PROFIT"

            if exit_raw is None and max_bars and (i - pos["idx"]) >= max_bars:
                exit_raw, reason = c[i], "TIMEOUT"

            if exit_raw is not None:
                exit_adj = exit_raw - half_spread if side == 1 else exit_raw + half_spread
                notional = cfg.amount * cfg.leverage
                pct = (exit_adj - pos["entry"]) / pos["entry"] if side == 1 \
                    else (pos["entry"] - exit_adj) / pos["entry"]
                pnl = notional * pct
                pnl = max(pnl, -cfg.amount)  # margin is the max loss
                pnl -= cfg.commission_per_trade

                trades.append({
                    "entry_time": str(t[pos["idx"]]),
                    "exit_time": str(t[i]),
                    "side": "BUY" if side == 1 else "SELL",
                    "entry": round(float(pos["entry"]), 6),
                    "exit": round(float(exit_raw), 6),
                    "stop_loss": round(float(pos["sl"]), 6),
                    "take_profit": round(float(pos["tp"]), 6),
                    "atr_entry": round(float(pos["atr_e"]), 6),
                    "reason": reason,
                    "pnl": round(float(pnl), 4),
                    "bars_held": i - pos["idx"],
                })
                equity += pnl
                equity_curve.append((t[i], equity, reason))
                pos = None

        # ---- 2. entry on the previous bar's signal (filled at this open) --- #
        # ATR used for SL/TP must be known at entry, i.e. computed on bar i-1.
        if pos is None and i >= 1 and sig[i - 1] != 0 and np.isfinite(a[i - 1]) and a[i - 1] > 0:
            side = sig[i - 1]
            entry_raw = o[i]
            entry = entry_raw + half_spread if side == 1 else entry_raw - half_spread
            atr_e = a[i - 1]
            if side == 1:
                sl = entry_raw - sl_atr * atr_e
                tp = entry_raw + tp_atr * atr_e
                liq = entry_raw * (1.0 - liq_frac)
            else:
                sl = entry_raw + sl_atr * atr_e
                tp = entry_raw - tp_atr * atr_e
                liq = entry_raw * (1.0 + liq_frac)
            pos = {
                "side": side, "entry": entry, "entry_raw": entry_raw,
                "sl": sl, "tp": tp, "liq": liq,
                "atr_e": atr_e, "idx": i,
            }

    # ---- 3. force-close any open position at the final close --------------- #
    if pos is not None:
        side = pos["side"]
        exit_adj = c[-1] - half_spread if side == 1 else c[-1] + half_spread
        notional = cfg.amount * cfg.leverage
        pct = (exit_adj - pos["entry"]) / pos["entry"] if side == 1 \
            else (pos["entry"] - exit_adj) / pos["entry"]
        pnl = max(notional * pct, -cfg.amount) - cfg.commission_per_trade
        trades.append({
            "entry_time": str(t[pos["idx"]]),
            "exit_time": str(t[-1]),
            "side": "BUY" if side == 1 else "SELL",
            "entry": round(float(pos["entry"]), 6),
            "exit": round(float(c[-1]), 6),
            "stop_loss": round(float(pos["sl"]), 6),
            "take_profit": round(float(pos["tp"]), 6),
            "atr_entry": round(float(pos["atr_e"]), 6),
            "reason": "END_OF_DATA",
            "pnl": round(float(pnl), 4),
            "bars_held": n - 1 - pos["idx"],
        })
        equity += pnl
        equity_curve.append((t[-1], equity, "END_OF_DATA"))

    stats = compute_stats(trades, equity_curve, cfg)
    return trades, equity_curve, stats


def compute_stats(trades: list, equity_curve: list, cfg: BacktestConfig) -> dict:
    n = len(trades)
    start = cfg.start_balance
    if n == 0:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "net_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
            "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "payoff": 0.0, "expectancy": 0.0, "sharpe": 0.0,
            "max_drawdown": 0.0, "max_dd_pct": 0.0, "max_consec_losses": 0,
            "avg_bars": 0.0, "end_balance": start, "reasons": {},
        }

    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    net = float(pnls.sum())

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    payoff = avg_win / abs(avg_loss) if avg_loss else (float("inf") if avg_win else 0.0)

    # realized equity curve for drawdown
    eq = [start] + [e for _, e, _ in equity_curve]
    eq = np.asarray(eq)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    max_dd = float(dd.max()) if len(dd) else 0.0
    dd_idx = int(np.argmax(dd))
    peak_at_dd = float(peak[dd_idx]) if max_dd > 0 else start
    max_dd_pct = (max_dd / peak_at_dd * 100.0) if max_dd > 0 and peak_at_dd > 0 else 0.0

    std = float(pnls.std()) if n > 1 else 0.0
    sharpe = float(pnls.mean() / std * np.sqrt(n)) if std > 0 else 0.0

    # longest losing streak
    max_consec = 0
    cur = 0
    for p in pnls:
        if p <= 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1

    return {
        "trades": n,
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(len(wins) / n * 100.0, 2),
        "net_pnl": round(net, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 2) if np.isfinite(profit_factor) else profit_factor,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "payoff": round(payoff, 2) if np.isfinite(payoff) else payoff,
        "expectancy": round(float(pnls.mean()), 3),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "max_consec_losses": int(max_consec),
        "avg_bars": round(float(np.mean([t["bars_held"] for t in trades])), 1) if n else 0.0,
        "end_balance": round(start + net, 2),
        "reasons": reasons,
    }
