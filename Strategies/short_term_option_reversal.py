"""
Strategies/short_term_option_reversal.py
Short-Term Option Reversal Strategy for Binary, Digital, and Bliz trading.
Detects wick rejections, Bollinger Band extreme bounces, and oversold/overbought pivots.

Output:
    'BUY', 'SELL', or 'NO_SIGNAL'
"""

from typing import Any, Dict, List, Union
import numpy as np
import pandas as pd


def _calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _calculate_bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + (std * num_std)
    lower = sma - (std * num_std)
    return upper, sma, lower


class ShortTermOptionReversal:
    """
    Short-Term Reversal strategy based on candlestick wick exhaustion & price envelope extremes.
    """

    def __init__(self):
        self.name = "short_term_option_reversal"

    def analyze(self, data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> str:
        """
        Analyzes market data and returns 'BUY', 'SELL', or 'NO_SIGNAL'.
        """
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            candles = data.get("candles", [])
            df = pd.DataFrame(candles) if isinstance(candles, list) else candles
        else:
            df = data.copy()

        if df is None or len(df) < 25:
            return "NO_SIGNAL"

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                return "NO_SIGNAL"

        # Indicators
        df["rsi"] = _calculate_rsi(df["close"], 14)
        df["bb_upper"], df["bb_mid"], df["bb_lower"] = _calculate_bollinger_bands(df["close"], 20, 2.0)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        c_open = float(last["open"])
        c_close = float(last["close"])
        c_high = float(last["high"])
        c_low = float(last["low"])

        body = abs(c_close - c_open)
        upper_wick = c_high - max(c_open, c_close)
        lower_wick = min(c_open, c_close) - c_low
        candle_range = c_high - c_low + 1e-9

        # Rejection metrics
        lower_rejection = lower_wick >= (1.8 * max(body, 0.0001)) and (lower_wick / candle_range) >= 0.45
        upper_rejection = upper_wick >= (1.8 * max(body, 0.0001)) and (upper_wick / candle_range) >= 0.45

        # Bullish Reversal Setup:
        # 1. Price penetrated or touched lower Bollinger Band
        # 2. RSI <= 32 (Oversold condition)
        # 3. Strong lower wick rejection OR Bullish Pin Bar
        lower_band_test = c_low <= last["bb_lower"] or prev["low"] <= prev["bb_lower"]
        is_oversold = last["rsi"] <= 32.0 or prev["rsi"] <= 30.0

        if lower_band_test and is_oversold and lower_rejection:
            return "BUY"

        # Bearish Reversal Setup:
        # 1. Price penetrated or touched upper Bollinger Band
        # 2. RSI >= 68 (Overbought condition)
        # 3. Strong upper wick rejection OR Bearish Shooting Star
        upper_band_test = c_high >= last["bb_upper"] or prev["high"] >= prev["bb_upper"]
        is_overbought = last["rsi"] >= 68.0 or prev["rsi"] >= 70.0

        if upper_band_test and is_overbought and upper_rejection:
            return "SELL"

        return "NO_SIGNAL"


def analyze(data: Any) -> str:
    strategy = ShortTermOptionReversal()
    return strategy.analyze(data)
