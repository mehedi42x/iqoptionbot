"""
backtest/run_backtest.py
CLI entry point. Runs every strategy through walk-forward optimization on the
provided (or synthetic) 15s data and produces:

    report/backtest_report.md   ranked leaderboard + best-strategy detail
    report/equity_curves.png    equity curves of the top strategies
    report/results.json         full machine-readable results

Usage (from the repo root):
    python3 -m backtest.run_backtest                       # synthetic demo
    python3 -m backtest.run_backtest --data candles.csv    # real data
    python3 -m backtest.run_backtest --symbols EURUSD XAUUSD --amount 10 --leverage 800
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backtest.data import generate_synthetic, load_candles
from backtest.engine import BacktestConfig
from backtest.optimizer import rank, walk_forward
from backtest.strategies import STRATEGIES

DEFAULT_SPREADS = {
    "EURUSD": 0.00015,
    "XAUUSD": 0.30,
    "GOLD": 0.30,
    "USDJPY": 0.012,
    "GBPUSD": 0.00020,
}
DEFAULT_SPREAD = 0.00015


def _fmt_pf(v) -> str:
    if isinstance(v, float) and not np.isfinite(v):
        return "inf"
    return f"{v:.2f}"


def _stats_table_row(s: dict) -> str:
    return (
        f"| {s['trades']} | {s['win_rate']:.1f}% | {_fmt_pf(s['profit_factor'])} "
        f"| ${s['expectancy']:.3f} | ${s['net_pnl']:.2f} | ${s['max_drawdown']:.2f} "
        f"({s['max_dd_pct']:.1f}%) | {s['sharpe']:.2f} |"
    )


def build_report(symbol: str, cfg: BacktestConfig, meta: dict, results: list, data_df: pd.DataFrame) -> str:
    ranked = rank(results)
    lines = []
    lines.append(f"# Backtest Report — {symbol} (15-second candles)\n")
    lines.append(
        "> **Risk warning:** 800x leverage means a move of only **0.125%** against a "
        "position liquidates the full $10 margin. Backtests — especially on synthetic "
        "data — do **not** guarantee future results. Trade PRACTICE first.\n"
    )
    lines.append("## Configuration\n")
    lines.append(f"| Setting | Value |\n|---|---|")
    lines.append(f"| Candle timeframe | 15 seconds |")
    lines.append(f"| Bars tested | {meta['bars']:,} |")
    lines.append(f"| Data window | {meta['start']} → {meta['end']} |")
    lines.append(f"| Data source | {meta['source']} |")
    lines.append(f"| Margin per trade | ${cfg.amount:.2f} |")
    lines.append(f"| Leverage | {cfg.leverage}x |")
    lines.append(f"| Notional exposure | ${cfg.amount * cfg.leverage:,.0f} |")
    lines.append(f"| Liquidation distance | {1.0 / cfg.leverage * 100:.3f}% |")
    lines.append(f"| Spread | {cfg.spread} |")
    lines.append(f"| Starting balance | ${cfg.start_balance:.2f} |")
    lines.append("")
    lines.append(
        "## Methodology\n\n"
        "Every strategy is optimised on the **first 60%** of the data (in-sample) and "
        "evaluated on the **last 40%** it never saw (out-of-sample). Ranking uses "
        "out-of-sample **expectancy** ($ per trade). SL/TP are ATR-based and managed "
        "by the bot; liquidation and spread are modelled.\n"
    )

    lines.append("## Leaderboard (ranked by out-of-sample expectancy)\n")
    lines.append(
        "| # | Strategy | Params | OOS trades | OOS win% | OOS PF | OOS expect. | "
        "OOS net PnL | OOS max DD | OOS Sharpe |\n|---|---|---|---|---|---|---|---|---|---|"
    )
    for i, r in enumerate(ranked, 1):
        o = r["out_of_sample"]
        flag = "" if r["qualified"] else "  ⚠ low trades"
        lines.append(
            f"| {i} | {r['label']}{flag} | {r['params']} | {o['trades']} | {o['win_rate']:.1f}% "
            f"| {_fmt_pf(o['profit_factor'])} | ${o['expectancy']:.3f} | ${o['net_pnl']:.2f} "
            f"| ${o['max_drawdown']:.2f} | {o['sharpe']:.2f} |"
        )

    if ranked:
        best = ranked[0]
        o = best["out_of_sample"]
        f = best["full"]
        lines.append("\n## Best strategy (on this data)\n")
        lines.append(f"**{best['label']}** (`{best['strategy']}`)\n")
        lines.append(f"- Parameters: `{best['params']}`")
        lines.append(f"- Exit rules: `{best['exits']}`")
        lines.append("\n| Metric | In-sample | Out-of-sample | Full series |\n|---|---|---|---|")
        for key, name in (
            ("trades", "Trades"),
            ("win_rate", "Win rate"),
            ("profit_factor", "Profit factor"),
            ("expectancy", "Expectancy ($/trade)"),
            ("net_pnl", "Net PnL ($)"),
            ("max_drawdown", "Max drawdown ($)"),
            ("sharpe", "Sharpe"),
        ):
            lines.append(
                f"| {name} | {best['in_sample'][key]} | {best['out_of_sample'][key]} | {best['full'][key]} |"
            )
        lines.append(f"\nClose reasons (full series): {best['full']['reasons']}")

        # example trades
        sig = STRATEGIES[best["strategy"]].signals(data_df, best["params"])
        from backtest.engine import run_backtest
        trades, _, _ = run_backtest(data_df, sig, best["exits"], cfg)
        lines.append("\n### Last 5 trades (full series)\n")
        lines.append("| Exit time | Side | Entry | Exit | SL | TP | Reason | PnL |\n|---|---|---|---|---|---|---|---|")
        for t in trades[-5:]:
            lines.append(
                f"| {t['exit_time']} | {t['side']} | {t['entry']} | {t['exit']} | "
                f"{t['stop_loss']} | {t['take_profit']} | {t['reason']} | ${t['pnl']:.2f} |"
            )

    lines.append(
        "\n---\n"
        "*Generated by `backtest/run_backtest.py`. For real data, run "
        "`python3 -m backtest.run_backtest --data your_candles.csv` and the leaderboard "
        "will re-rank on your actual market data.*\n"
    )
    return "\n".join(lines)


def plot_equity(symbol: str, ranked: list, out_path: str):
    if not ranked:
        return
    top = [r for r in ranked[:3] if r["full_curve"]]
    fig, ax = plt.subplots(figsize=(11, 5))
    for r in top:
        curve = pd.DataFrame(r["full_curve"], columns=["time", "equity", "reason"])
        curve["time"] = pd.to_datetime(curve["time"], errors="coerce")
        curve = curve.dropna(subset=["time"])
        ax.step(curve["time"], curve["equity"], where="post", label=r["strategy"], lw=1.2)
    ax.set_title(f"{symbol} — top strategies equity curve (full series)")
    ax.set_xlabel("time")
    ax.set_ylabel("equity ($)")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def run_symbol(symbol: str, data_path: str | None, cfg: BacktestConfig, bars: int, seed: int):
    if data_path:
        df = load_candles(data_path)
        source = f"real data: {data_path}"
    else:
        df = generate_synthetic(symbol, n_bars=bars, seed=seed)
        source = "synthetic (demo)"
    meta = {
        "bars": len(df),
        "start": str(df["time"].iloc[0])[:19],
        "end": str(df["time"].iloc[-1])[:19],
        "source": source,
    }
    results = []
    for name, strat in STRATEGIES.items():
        r = walk_forward(df, strat, cfg)
        if r is not None:
            results.append(r)
    return df, meta, results


def main():
    p = argparse.ArgumentParser(description="15s leveraged CFD strategy backtester")
    p.add_argument("--data", default=None, help="path to a candle CSV (real data)")
    p.add_argument("--symbols", nargs="+", default=["EURUSD", "XAUUSD"], help="symbols for synthetic demo")
    p.add_argument("--amount", type=float, default=10.0)
    p.add_argument("--leverage", type=int, default=800)
    p.add_argument("--spread", type=float, default=None)
    p.add_argument("--balance", type=float, default=1000.0)
    p.add_argument("--bars", type=int, default=28800, help="synthetic bars (28800 = 5 days of 15s)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report")
    os.makedirs(out_dir, exist_ok=True)

    all_results = {}
    report_parts = []
    eq_pngs = []
    for symbol in args.symbols:
        spread = args.spread if args.spread is not None else DEFAULT_SPREADS.get(symbol.upper(), DEFAULT_SPREAD)
        cfg = BacktestConfig(amount=args.amount, leverage=args.leverage, spread=spread,
                             start_balance=args.balance)
        df, meta, results = run_symbol(symbol, args.data, cfg, args.bars, args.seed)
        ranked = rank(results)
        report_parts.append(build_report(symbol, cfg, meta, results, df))
        all_results[symbol] = {
            "config": {"amount": args.amount, "leverage": args.leverage, "spread": spread,
                       "start_balance": args.balance},
            "meta": meta,
            "results": [
                {
                    "strategy": r["strategy"],
                    "label": r["label"],
                    "params": r["params"],
                    "exits": r["exits"],
                    "in_sample": r["in_sample"],
                    "out_of_sample": r["out_of_sample"],
                    "full": r["full"],
                }
                for r in results
            ],
        }
        # re-rank stored results with the same key as optimizer.rank
        for r in all_results[symbol]["results"]:
            r["qualified"] = r["out_of_sample"]["trades"] >= 8
        all_results[symbol]["results"] = sorted(
            all_results[symbol]["results"],
            key=lambda r: (r["qualified"], r["out_of_sample"]["expectancy"]),
            reverse=True,
        )
        png = os.path.join(out_dir, f"equity_{symbol.replace('/', '').lower()}.png")
        plot_equity(symbol, ranked, png)
        eq_pngs.append(png)

    # console summary
    for symbol in args.symbols:
        ranked = all_results[symbol]["results"]
        print(f"\n=== {symbol} leaderboard (OOS expectancy) ===")
        for i, r in enumerate(ranked, 1):
            o = r["out_of_sample"]
            print(f"{i:2d}. {r['strategy']:<26} trades={o['trades']:>4} win%={o['win_rate']:>5.1f} "
                  f"PF={_fmt_pf(o['profit_factor']):>6} expect=${o['expectancy']:>7.3f} "
                  f"net=${o['net_pnl']:>8.2f} maxDD=${o['max_drawdown']:>7.2f}")
        if ranked:
            b = ranked[0]
            print(f"   -> BEST: {b['strategy']}  params={b['params']}")

    report_path = os.path.join(out_dir, "backtest_report.md")
    with open(report_path, "w") as f:
        f.write("\n\n---\n\n".join(report_parts))
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\nReport written: {report_path}")
    print(f"Equity charts : {', '.join(eq_pngs)}")


if __name__ == "__main__":
    main()
