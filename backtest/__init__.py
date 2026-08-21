"""
backtest - Professional 15s CFD strategy research & backtesting suite.

Pipeline:
    data.py        -> load real candles (CSV) or generate realistic synthetic 15s data
    indicators.py  -> pure pandas/numpy indicator library (EMA, RSI, ATR, MACD,
                      Bollinger, Stochastic, ADX, SuperTrend, Donchian, VWAP)
    strategies.py  -> 9 distinct strategy methodologies (signal generators)
    engine.py      -> event-driven backtest engine with $10 margin / 800x leverage,
                      bot-managed SL/TP, trailing stops, spread & liquidation model
    optimizer.py   -> walk-forward (train/test) parameter optimization + ranking
    run_backtest.py-> CLI entry point that produces a ranked leaderboard report
"""

__version__ = "1.0.0"
