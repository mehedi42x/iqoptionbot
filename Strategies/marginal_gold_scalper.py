"""
Strategies/marginal_gold_scalper.py
Forex / Marginal Gold (XAUUSD) 1-Minute Scalping Strategy.
Uses multi-EMA trend filtration (200, 50, 20), dynamic pullback detection,
MACD momentum confirmation, and candlestick action.

Output:
    'BUY', 'SELL', or 'NO_SIGNAL'
"""

from typing import Any, Dict, List, Union
import numpy as np
import pandas as pd


def _calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = series.ewm(span=fast, adjust=False).mean()
    slow_ema = series.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


class MarginalGoldScalper:
    """
    Precision 1-minute Gold (XAUUSD) Scalper.
    """

    def __init__(self):
        self.name = "marginal_gold_scalper"

    def analyze(self, data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> str:
        """
        Analyzes Gold market structure and returns 'BUY', 'SELL', or 'NO_SIGNAL'.
        """
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            candles = data.get("candles", [])
            df = pd.DataFrame(candles) if isinstance(candles, list) else candles
        else:
            df = data.copy()

        if df is None or len(df) < 50:
            return "NO_SIGNAL"

        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                return "NO_SIGNAL"

        # Moving Averages & Trend Filters
        df["ema20"] = _calculate_ema(df["close"], 20)
        df["ema50"] = _calculate_ema(df["close"], 50)
        # Use available depth for baseline trend (e.g. EMA 100/200)
        baseline_period = 200 if len(df) >= 200 else (100 if len(df) >= 100 else 50)
        df["ema_trend"] = _calculate_ema(df["close"], baseline_period)

        # MACD & ATR
        df["macd"], df["macd_sig"], df["macd_hist"] = _calculate_macd(df["close"])
        df["atr"] = _calculate_atr(df, 14)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        c_close = float(last["close"])
        c_open = float(last["open"])
        c_high = float(last["high"])
        c_low = float(last["low"])

        # Bullish Gold Setup:
        # 1. Macro trend bullish (Close > EMA Trend and EMA 20 > EMA 50)
        # 2. Pullback bounce: Low touched or penetrated near EMA 20/50 zone, but Close bounced back above EMA 20
        # 3. MACD Histogram is positive or ticked higher than previous candle
        # 4. Bullish confirmation candle
        macro_bull = c_close > last["ema_trend"] and last["ema20"] >= last["ema50"]
        pullback_support = prev["low"] <= (prev["ema20"] * 1.0005) or last["low"] <= (last["ema20"] * 1.0005)
        price_above_ema20 = c_close > last["ema20"]
        macd_momentum_up = last["macd_hist"] > prev["macd_hist"] or last["macd_hist"] > 0
        bull_candle = c_close > c_open and (c_close - c_open) >= ((c_high - c_low) * 0.4)

        if macro_bull and pullback_support and price_above_ema20 and macd_momentum_up and bull_candle:
            return "BUY"

        # Bearish Gold Setup:
        # 1. Macro trend bearish (Close < EMA Trend and EMA 20 < EMA 50)
        # 2. Pullback resistance: High touched or penetrated near EMA 20/50 zone, but Close rejected below EMA 20
        # 3. MACD Histogram is negative or ticked lower than previous candle
        # 4. Bearish confirmation candle
        macro_bear = c_close < last["ema_trend"] and last["ema20"] <= last["ema50"]
        pullback_resistance = prev["high"] >= (prev["ema20"] * 0.9995) or last["high"] >= (last["ema20"] * 0.9995)
        price_below_ema20 = c_close < last["ema20"]
        macd_momentum_down = last["macd_hist"] < prev["macd_hist"] or last["macd_hist"] < 0
        bear_candle = c_close < c_open and (c_open - c_close) >= ((c_high - c_low) * 0.4)

        if macro_bear and pullback_resistance and price_below_ema20 and macd_momentum_down and bear_candle:
            return "SELL"

        return "NO_SIGNAL"


def analyze(data: Any) -> str:
    strategy = MarginalGoldScalper()
    return strategy.analyze(data)
