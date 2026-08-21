# Backtest Suite — 15s Leveraged CFD Strategy Research

Professional walk-forward backtesting pipeline for the 15-second timeframe,
$10 margin at 800x leverage, with **bot-managed** SL/TP (the broker never sees
the stop, exactly like the production bot).

## Quick start

```bash
# install deps (pandas, numpy, matplotlib)
pip3 install -r ../requirements.txt matplotlib

# DEMO run on synthetic 15s data (EURUSD + XAUUSD)
python3 -m backtest.run_backtest

# REAL run on your candle data
python3 -m backtest.run_backtest --data path/to/candles.csv --spread 0.00015

# Full options
python3 -m backtest.run_backtest --symbols EURUSD XAUUSD \
    --amount 10 --leverage 800 --bars 28800 --seed 42
```

## Your candle data format

Any CSV with OHLC columns works — column names are auto-detected
(`time/timestamp/date/from`, `open/o`, `high/h/max`, `low/l/min`,
`close/c/price`, optional `volume/v`). Example:

```csv
time,open,high,low,close
2026-08-10T00:00:00Z,1.08480,1.08495,1.08472,1.08490
2026-08-10T00:00:15Z,1.08490,1.08505,1.08488,1.08501
...
```

Drop the file anywhere and pass `--data`. The engine resamples nothing — it
assumes the file is already the timeframe you want to trade (15s).

## What gets produced

| File | Contents |
|---|---|
| `report/backtest_report.md` | ranked leaderboard + best-strategy detail |
| `report/results.json` | full machine-readable results |
| `report/equity_*.png` | equity curves of the top strategies |

## How it works (important details)

- **Walk-forward**: each strategy's parameters are grid-searched on the first
  60% of the data (in-sample) and evaluated on the last 40% it never saw
  (out-of-sample). The leaderboard ranks by **out-of-sample expectancy**.
- **Fill model**: signal at bar close → fill at next bar open; conservative
  intra-bar path (SL before TP); gaps honoured.
- **Costs**: half-spread charged at entry, half at exit.
- **800x reality**: `1/800 = 0.125%` adverse move = full margin loss
  (liquidation). The engine models this and takes liquidation before a stop
  that is placed wider than the liquidation distance.

## The 9 strategies tested

1. `ema_trend_adx` — EMA crossover + ADX trend filter
2. `rsi_mean_reversion` — RSI extremes + Bollinger band touch
3. `bollinger_squeeze_breakout` — squeeze → band break
4. `macd_momentum` — MACD histogram flip + ADX filter
5. `supertrend_flip` — SuperTrend direction change
6. `donchian_breakout` — Donchian channel breakout
7. `vwap_reversion` — VWAP z-score mean reversion
8. `price_action_engulfing` — engulfing candles at swing S/R
9. `volatility_contraction` — NR7 squeeze + momentum ignition

## Honesty note

- The **demo** runs on **synthetic** data. Its numbers demonstrate the pipeline
  only — they are **not** evidence of future performance.
- The **real** selection must be run on your actual candle CSV. Ranking can
  change completely on real data.
- High leverage amplifies losses exactly as much as gains. Always validate on
  `ACCOUNT=PRACTICE` first.
