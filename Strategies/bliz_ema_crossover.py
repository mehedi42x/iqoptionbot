"""
Strategies/bliz_ema_crossover.py
Bliz (Blitz) EMA Crossover Scalping Strategy.

Two-timeframe confluence:

  1. DIRECTION (1-minute candles): EMA 9 vs EMA 12 sets the market bias —
     which side to trade.
       * EMA 9 > EMA 12  ->  bullish bias (look for BUY entries)
       * EMA 9 < EMA 12  ->  bearish bias (look for SELL entries)

  2. ENTRY SIGNAL (15-second candles): EMA 2 vs EMA 3 crossover fires the
     actual signal, but ONLY in the direction of the 1-minute bias.
       * EMA 2 crosses ABOVE EMA 3  ->  BUY (if bullish bias)
       * EMA 2 crosses BELOW EMA 3  ->  SELL (if bearish bias)

Output:
    'BUY', 'SELL', or 'NO_SIGNAL'
"""

from typing import Any, Dict, List, Union

import pandas as pd

# Engine hint: also fetch 15-second candles for the entry signal.
# The primary candles (1 minute) come from TIMEFRAME=1 in .env.
SIGNAL_TIMEFRAME = 15   # seconds — entry signal timeframe
PRIMARY_TIMEFRAME = 60  # seconds — direction bias timeframe (must match .env TIMEFRAME=1)

EMA_BIAS_FAST = 9
EMA_BIAS_SLOW = 12
EMA_SIGNAL_FAST = 2
EMA_SIGNAL_SLOW = 3


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


class BlizEmaCrossover:
    """Bliz scalper: 1m EMA 9/12 bias + 15s EMA 2/3 entry crossover."""

    def __init__(self):
        self.name = "bliz_ema_crossover"

    def analyze(self, data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> str:
        """
        Analyzes the two timeframes and returns 'BUY', 'SELL', or 'NO_SIGNAL'.

        Expected `data` keys (provided by core.py):
            candles        -> list of 1-minute candles (direction bias)
            signal_candles -> list of 15-second candles (entry signal)
            current_price  -> latest price
            symbol         -> trading symbol
        """
        candles = None
        signal_candles = None
        if isinstance(data, dict):
            candles = data.get("candles")
            signal_candles = data.get("signal_candles")
        elif isinstance(data, list):
            candles = data

        if candles is None:
            return "NO_SIGNAL"

        df = pd.DataFrame(candles)
        if len(df) < EMA_BIAS_SLOW + 5:
            return "NO_SIGNAL"

        for col in ["close"]:
            if col not in df.columns:
                return "NO_SIGNAL"
        df["close"] = pd.to_numeric(df["close"], errors="coerce")

        # --- 1) Direction bias from 1-minute EMA 9 / 12 ---
        df["ema9"] = _ema(df["close"], EMA_BIAS_FAST)
        df["ema12"] = _ema(df["close"], EMA_BIAS_SLOW)
        ema9 = float(df["ema9"].iloc[-1])
        ema12 = float(df["ema12"].iloc[-1])

        if ema9 > ema12:
            bias = "BULL"
        elif ema9 < ema12:
            bias = "BEAR"
        else:
            bias = "FLAT"

        if bias == "FLAT":
            return "NO_SIGNAL"

        # --- 2) Entry signal from 15-second EMA 2 / 3 crossover ---
        if signal_candles is None or len(signal_candles) < EMA_SIGNAL_SLOW + 2:
            return "NO_SIGNAL"

        sdf = pd.DataFrame(signal_candles)
        if "close" not in sdf.columns:
            return "NO_SIGNAL"
        sdf["close"] = pd.to_numeric(sdf["close"], errors="coerce")

        sdf["ema2"] = _ema(sdf["close"], EMA_SIGNAL_FAST)
        sdf["ema3"] = _ema(sdf["close"], EMA_SIGNAL_SLOW)

        prev2 = float(sdf["ema2"].iloc[-2])
        prev3 = float(sdf["ema3"].iloc[-2])
        last2 = float(sdf["ema2"].iloc[-1])
        last3 = float(sdf["ema3"].iloc[-1])

        cross_up = prev2 <= prev3 and last2 > last3
        cross_down = prev2 >= prev3 and last2 < last3

        # Entry must agree with the 1-minute bias.
        if bias == "BULL" and cross_up:
            return "BUY"
        if bias == "BEAR" and cross_down:
            return "SELL"
        return "NO_SIGNAL"


def analyze(data: Any) -> str:
    strategy = BlizEmaCrossover()
    return strategy.analyze(data)
