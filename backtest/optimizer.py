"""
backtest/optimizer.py
Walk-forward parameter optimization to avoid curve-fitting.

For each strategy:
  1. Split the series into IN-SAMPLE (first `split` fraction) and
     OUT-OF-SAMPLE (the rest).
  2. Grid-search the strategy's parameter space on the IN-SAMPLE data,
     selecting the parameter set with the best profit factor (with a minimum
     trade-count guard).
  3. Evaluate those chosen parameters on the UNSEEN out-of-sample data.
  4. Also evaluate on the full series for reference.

Ranking is done by out-of-sample expectancy (average $ per trade) with a
minimum out-of-sample trade count, so the winner is the strategy that actually
made money per trade on data it never saw.
"""

from __future__ import annotations

import itertools

from backtest.engine import BacktestConfig, run_backtest


def _grid(param_grid: dict):
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo))


def walk_forward(df, strategy, cfg: BacktestConfig, split: float = 0.6,
                 min_is_trades: int = 12, min_oos_trades: int = 8):
    cut = int(len(df) * split)
    df_is = df.iloc[:cut]
    df_oos = df.iloc[cut:]

    # --- in-sample grid search ---
    best = None
    for params in _grid(strategy.param_grid):
        sig = strategy.signals(df_is, params)
        _, _, stats = run_backtest(df_is, sig, strategy.exits, cfg)
        if stats["trades"] < min_is_trades:
            continue
        pf = stats["profit_factor"]
        obj = pf if pf != float("inf") else 1e6
        # tie-break by net pnl
        key = (obj, stats["net_pnl"])
        if best is None or key > best[0]:
            best = (key, params, stats)

    if best is None:
        return None

    _, params, is_stats = best

    # --- out-of-sample evaluation with chosen params ---
    sig_oos = strategy.signals(df_oos, params)
    _, oos_curve, oos_stats = run_backtest(df_oos, sig_oos, strategy.exits, cfg)

    # --- full-series reference ---
    sig_full = strategy.signals(df, params)
    _, full_curve, full_stats = run_backtest(df, sig_full, strategy.exits, cfg)

    return {
        "strategy": strategy.name,
        "label": strategy.label,
        "params": params,
        "exits": dict(strategy.exits),
        "in_sample": is_stats,
        "out_of_sample": oos_stats,
        "full": full_stats,
        "oos_curve": [(str(t), float(e), r) for t, e, r in oos_curve],
        "full_curve": [(str(t), float(e), r) for t, e, r in full_curve],
        "qualified": oos_stats["trades"] >= min_oos_trades,
    }


def rank(results: list) -> list:
    """Sort results by out-of-sample expectancy, qualified strategies first."""
    def key(r):
        return (r["qualified"], r["out_of_sample"]["expectancy"])
    return sorted(results, key=key, reverse=True)
