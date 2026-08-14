"""
Strategies/short_term_option_scalper.py
Short-Term Option Scalper Strategy for Binary, Digital, and Bliz trading.

Output:
    'BUY', 'SELL', or 'NO_SIGNAL'
"""

from typing import Any, Dict, List, Tuple, Union
import numpy as np
import pandas as pd


def _calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _calculate_stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> Tuple[pd.Series, pd.Series]:
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    k_percent = 100 * ((df["close"] - low_min) / (high_max - low_min + 1e-9))
    d_percent = k_percent.rolling(window=d_period).mean()
    return k_percent, d_percent


class ShortTermOptionScalper:
    """
    Short-Term Scalper strategy detecting high-momentum continuation setups.
    """

    def __init__(self):
        self.name = "short_term_option_scalper"

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

        if df is None or len(df) < 30:
            return "NO_SIGNAL"

        # Ensure required numeric columns
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                return "NO_SIGNAL"

        # Technical Indicators
        df["ema_fast"] = _calculate_ema(df["close"], 9)
        df["ema_slow"] = _calculate_ema(df["close"], 21)
        df["rsi"] = _calculate_rsi(df["close"], 14)
        k_percent, d_percent = _calculate_stochastic(df, 14, 3)
        df["stoch_k"] = k_percent
        df["stoch_d"] = d_percent

        last = df.iloc[-1]

        current_close = float(last["close"])
        current_open = float(last["open"])
        current_high = float(last["high"])
        current_low = float(last["low"])

        candle_body = abs(current_close - current_open)
        candle_range = current_high - current_low + 1e-9
        body_ratio = candle_body / candle_range

        # Condition checks
        # Bullish Scalping Setup:
        # 1. EMA 9 > EMA 21 (Short-term uptrend)
        # 2. Close > EMA 9
        # 3. RSI between 52 and 72 (Strong momentum, not overbought)
        # 4. Stochastic K > D and K < 80
        # 5. Bullish candle with solid body ratio (> 0.45)
        is_bullish_trend = last["ema_fast"] > last["ema_slow"]
        is_bullish_price = current_close > last["ema_fast"]
        is_bullish_rsi = 52.0 <= last["rsi"] <= 72.0
        is_bullish_stoch = last["stoch_k"] > last["stoch_d"] and last["stoch_k"] < 80.0
        is_bullish_candle = current_close > current_open and body_ratio >= 0.45

        if (
            is_bullish_trend
            and is_bullish_price
            and is_bullish_rsi
            and is_bullish_stoch
            and is_bullish_candle
        ):
            return "BUY"

        # Bearish Scalping Setup:
        # 1. EMA 9 < EMA 21 (Short-term downtrend)
        # 2. Close < EMA 9
        # 3. RSI between 28 and 48 (Strong downward momentum, not oversold)
        # 4. Stochastic K < D and K > 20
        # 5. Bearish candle with solid body ratio (> 0.45)
        is_bearish_trend = last["ema_fast"] < last["ema_slow"]
        is_bearish_price = current_close < last["ema_fast"]
        is_bearish_rsi = 28.0 <= last["rsi"] <= 48.0
        is_bearish_stoch = last["stoch_k"] < last["stoch_d"] and last["stoch_k"] > 20.0
        is_bearish_candle = current_close < current_open and body_ratio >= 0.45

        if (
            is_bearish_trend
            and is_bearish_price
            and is_bearish_rsi
            and is_bearish_stoch
            and is_bearish_candle
        ):
            return "SELL"

        return "NO_SIGNAL"


def analyze(data: Any) -> str:
    strategy = ShortTermOptionScalper()
    return strategy.analyze(data)
