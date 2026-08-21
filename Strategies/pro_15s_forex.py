"""
Strategies/pro_15s_forex.py
PRO 15s FOREX — Donchian Channel Breakout Scalper (800x, bot-managed ATR SL/TP)

Winner of the walk-forward backtest across 9 candidate strategies on 15-second
candle data (see backtest/report/backtest_report.md).

METHOD (trend-following breakout on the 15-second timeframe):
    1. Build a Donchian channel: the highest HIGH and lowest LOW of the last
       DONCHIAN_PERIOD (30) 15-second candles.
    2. BUY  when the close breaks ABOVE the prior 30-bar high.
       SELL when the close breaks BELOW the prior 30-bar low.
    3. Trade direction is never fought — entries fire only in the breakout
       direction, and the bot-managed ATR stop trails behind the move.

RISK MANAGEMENT (bot-managed, never sent to the broker):
    * SL = entry ∓ SL_ATR_MULT (2.0) × ATR(14)
    * TP = entry ± TP_ATR_MULT (3.0) × ATR(14)
    * Trailing stop = TRAIL_ATR_MULT (2.0) × ATR(14) behind price (locks profit)
    * MAX_BARS (40) = hard time-stop so a dead position is never held forever

    ⚠ At 800x leverage a move of only 0.125% liquidates the full margin, so the
      ATR-based stop MUST stay tighter than the liquidation distance. With
      2×ATR(14) on 15s bars the stop sits far inside that threshold, meaning the
      stop (not liquidation) is the binding risk control.

Output:
    'BUY', 'SELL', or 'NO_SIGNAL'

Exports used by core.py (dynamic, ATR-based SL/TP + trailing):
    SIGNAL_TIMEFRAME   -> hint for the engine's 15s candle fetch
    SL_ATR_MULT / TP_ATR_MULT / TRAIL_ATR_MULT / ATR_PERIOD
    compute_sl_tp(candles, direction, price) -> (sl, tp)
    compute_atr(candles) -> atr
"""

from typing import Any, Dict, List, Tuple, Union

import numpy as np
import pandas as pd

SIGNAL_TIMEFRAME = 15          # seconds — this strategy trades 15s candles
PRIMARY_TIMEFRAME = 15         # seconds — primary candles should be 15s too

DONCHIAN_PERIOD = 30
ATR_PERIOD = 14
SL_ATR_MULT = 2.0
TP_ATR_MULT = 3.0
TRAIL_ATR_MULT = 2.0
MAX_BARS = 40


def _atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _to_df(data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> pd.DataFrame:
    if isinstance(data, list):
        df = pd.DataFrame(data)
    elif isinstance(data, dict):
        candles = data.get("signal_candles") or data.get("candles", [])
        df = pd.DataFrame(candles) if isinstance(candles, list) else candles
    else:
        df = data.copy()
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


class Pro15sForex:
    """Donchian(30) breakout scalper for 15-second leveraged CFD trading."""

    def __init__(self):
        self.name = "pro_15s_forex"

    def analyze(self, data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> str:
        df = _to_df(data)
        if df is None or len(df) < DONCHIAN_PERIOD + 3:
            return "NO_SIGNAL"

        hh = df["high"].rolling(DONCHIAN_PERIOD).max()
        ll = df["low"].rolling(DONCHIAN_PERIOD).min()
        close = df["close"]

        # Compare the latest close against the channel built on the PREVIOUS
        # bars (excludes the current bar -> no lookahead).
        if close.iloc[-1] > hh.iloc[-2]:
            return "BUY"
        if close.iloc[-1] < ll.iloc[-2]:
            return "SELL"
        return "NO_SIGNAL"


def compute_atr(candles: Union[List[Dict[str, Any]], pd.DataFrame]) -> float:
    """Return the latest ATR(14) so core.py can size the stop distance."""
    df = _to_df(candles)
    if df is None or len(df) < ATR_PERIOD + 2:
        return 0.0
    a = _atr(df).iloc[-1]
    return float(a) if np.isfinite(a) and a > 0 else 0.0


def compute_sl_tp(
    candles: Union[List[Dict[str, Any]], pd.DataFrame],
    direction: str,
    price: float,
) -> Tuple[float, float]:
    """
    Dynamic, ATR-based SL/TP for a new position (bot-managed, not sent to the
    broker). Returns (stop_loss, take_profit) prices.
    """
    a = compute_atr(candles)
    if a <= 0:
        return None, None  # core.py falls back to fixed .env distances
    if direction == "BUY":
        sl = price - SL_ATR_MULT * a
        tp = price + TP_ATR_MULT * a
    else:
        sl = price + SL_ATR_MULT * a
        tp = price - TP_ATR_MULT * a
    return round(sl, 6), round(tp, 6)


def analyze(data: Any) -> str:
    return Pro15sForex().analyze(data)
