"""
Strategies/marginal_momentum_reversal.py
Forex / Marginal Gold Momentum + Reversal Strategy.
Combines MACD histogram divergence/inflection, Stochastic oscillator extremes,
and structural candlestick price action.

Output:
    'BUY', 'SELL', or 'NO_SIGNAL'
"""

from typing import Any, Dict, List, Union
import numpy as np
import pandas as pd


def _calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = series.ewm(span=fast, adjust=False).mean()
    slow_ema = series.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _calculate_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    k_percent = 100 * ((df["close"] - low_min) / (high_max - low_min + 1e-9))
    d_percent = k_percent.rolling(window=d_period).mean()
    return k_percent, d_percent


class MarginalMomentumReversal:
    """
    Momentum Reversal strategy capturing inflection points on Gold / Forex pairs.
    """

    def __init__(self):
        self.name = "marginal_momentum_reversal"

    def analyze(self, data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> str:
        """
        Analyzes momentum oscillator confluence and returns 'BUY', 'SELL', or 'NO_SIGNAL'.
        """
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            candles = data.get("candles", [])
            df = pd.DataFrame(candles) if isinstance(candles, list) else candles
        else:
            df = data.copy()

        if df is None or len(df) < 35:
            return "NO_SIGNAL"

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                return "NO_SIGNAL"

        # Calculate Oscillators
        df["macd"], df["macd_sig"], df["macd_hist"] = _calculate_macd(df["close"], 12, 26, 9)
        df["stoch_k"], df["stoch_d"] = _calculate_stochastic(df, 14, 3)

        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        c_close = float(last["close"])
        c_open = float(last["open"])
        c_high = float(last["high"])
        c_low = float(last["low"])

        p_close = float(prev["close"])
        p_open = float(prev["open"])

        # Bullish Momentum Reversal Setup:
        # 1. Stochastic K was in oversold territory (< 25) and crossed above D
        # 2. MACD histogram is improving (last > prev or crossing zero upward)
        # 3. Candlestick shows bullish rejection or engulfing
        stoch_oversold_cross = (prev["stoch_k"] <= 30.0 or last["stoch_k"] <= 30.0) and (last["stoch_k"] > last["stoch_d"])
        macd_improving = last["macd_hist"] > prev["macd_hist"]
        bullish_candle = c_close > c_open and (c_close > p_close or (c_close - c_open) >= ((c_high - c_low) * 0.45))

        if stoch_oversold_cross and macd_improving and bullish_candle:
            return "BUY"

        # Bearish Momentum Reversal Setup:
        # 1. Stochastic K was in overbought territory (> 75) and crossed below D
        # 2. MACD histogram is worsening (last < prev or crossing zero downward)
        # 3. Candlestick shows bearish rejection or engulfing
        stoch_overbought_cross = (prev["stoch_k"] >= 70.0 or last["stoch_k"] >= 70.0) and (last["stoch_k"] < last["stoch_d"])
        macd_worsening = last["macd_hist"] < prev["macd_hist"]
        bearish_candle = c_close < c_open and (c_close < p_close or (p_open - c_close) >= ((c_high - c_low) * 0.45))

        if stoch_overbought_cross and macd_worsening and bearish_candle:
            return "SELL"

        return "NO_SIGNAL"


def analyze(data: Any) -> str:
    strategy = MarginalMomentumReversal()
    return strategy.analyze(data)
