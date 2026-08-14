"""
Strategies/marginal_breakout_pro.py
Forex / Marginal Gold Breakout Pro Strategy.
Employs Donchian Channel High/Low breakouts, ATR volatility expansion filters,
and false breakout rejection detection.

Output:
    'BUY', 'SELL', or 'NO_SIGNAL'
"""

from typing import Any, Dict, List, Union
import numpy as np
import pandas as pd


def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


class MarginalBreakoutPro:
    """
    High-probability Donchian Breakout strategy for Forex and Gold.
    """

    def __init__(self, lookback_period: int = 20):
        self.name = "marginal_breakout_pro"
        self.lookback = lookback_period

    def analyze(self, data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> str:
        """
        Analyzes breakouts and returns 'BUY', 'SELL', or 'NO_SIGNAL'.
        """
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            candles = data.get("candles", [])
            df = pd.DataFrame(candles) if isinstance(candles, list) else candles
        else:
            df = data.copy()

        if df is None or len(df) < (self.lookback + 15):
            return "NO_SIGNAL"

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                return "NO_SIGNAL"

        # Donchian Channels (computed on shifted bars to avoid lookahead bias)
        df["channel_high"] = df["high"].shift(1).rolling(window=self.lookback).max()
        df["channel_low"] = df["low"].shift(1).rolling(window=self.lookback).min()

        # Volatility filters
        df["atr"] = _calculate_atr(df, 14)
        df["atr_ma"] = df["atr"].rolling(window=20).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]

        c_close = float(last["close"])
        c_open = float(last["open"])
        c_high = float(last["high"])
        c_low = float(last["low"])

        body = abs(c_close - c_open)
        c_range = c_high - c_low + 1e-9
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low

        # Volatility condition: current ATR is active and expanding
        volatility_active = last["atr"] >= (last["atr_ma"] * 0.95)

        # Bullish Breakout:
        # 1. Close breaks above the recent lookback High
        # 2. Previous candle was below the channel high (fresh breakout)
        # 3. Candle is strong bullish (body >= 50% of range, upper wick <= 25% of range)
        # 4. Volatility expansion confirmation
        fresh_bull_breakout = c_close > last["channel_high"] and prev["close"] <= prev["channel_high"]
        bullish_candle_quality = (c_close > c_open) and ((body / c_range) >= 0.50) and ((upper_wick / c_range) <= 0.25)

        if fresh_bull_breakout and bullish_candle_quality and volatility_active:
            return "BUY"

        # Bearish Breakdown:
        # 1. Close breaks below the recent lookback Low
        # 2. Previous candle was above the channel low (fresh breakdown)
        # 3. Candle is strong bearish (body >= 50% of range, lower wick <= 25% of range)
        # 4. Volatility expansion confirmation
        fresh_bear_breakdown = c_close < last["channel_low"] and prev["close"] >= prev["channel_low"]
        bearish_candle_quality = (c_close < c_open) and ((body / c_range) >= 0.50) and ((lower_wick / c_range) <= 0.25)

        if fresh_bear_breakdown and bearish_candle_quality and volatility_active:
            return "SELL"

        return "NO_SIGNAL"


def analyze(data: Any) -> str:
    strategy = MarginalBreakoutPro()
    return strategy.analyze(data)
