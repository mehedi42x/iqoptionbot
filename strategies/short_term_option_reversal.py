"""
Short-Term Option Reversal Strategy
Target: BINARY, DIGITAL, BLIZ
Timeframe: 1 Minute

Pure Market Analysis Engine.
Detects wick rejection, exhaustion, and mean-reversion at local extremes.
"""

from typing import Dict, Any, List
import math


class ShortTermOptionReversal:
    def __init__(self):
        self.name = "short_term_option_reversal"
        self.compatible_trade_types = ["BINARY", "DIGITAL", "BLIZ"]

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "timeframe": 60,
            "candle_count": 35,
            "need_live_price": True,
            "indicators": ["BollingerBands", "RSI5", "WickRejection"]
        }

    def _calculate_rsi(self, closes: List[float], period: int = 5) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))

        if len(gains) < period:
            return 50.0

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calculate_bollinger_bands(self, closes: List[float], period: int = 20, num_std: float = 2.0):
        if len(closes) < period:
            return None, None, None
        subset = closes[-period:]
        sma = sum(subset) / period
        variance = sum((x - sma) ** 2 for x in subset) / period
        std_dev = math.sqrt(variance)
        upper = sma + (std_dev * num_std)
        lower = sma - (std_dev * num_std)
        return upper, sma, lower

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze price action and candlestick geometry for rapid reversal.
        """
        candles = market_data.get("candles", [])
        current_price = market_data.get("current_price")

        if not candles or len(candles) < 25 or current_price is None:
            return {
                "action": "NO_SIGNAL",
                "confidence": 0.0,
                "reason": "Insufficient candle data for reversal analysis"
            }

        closes = [float(c.get("close", c.get("c", 0.0))) for c in candles]
        opens = [float(c.get("open", c.get("o", 0.0))) for c in candles]
        highs = [float(c.get("max", c.get("high", c.get("h", 0.0)))) for c in candles]
        lows = [float(c.get("min", c.get("low", c.get("l", 0.0)))) for c in candles]

        upper_bb, mid_bb, lower_bb = self._calculate_bollinger_bands(closes, period=20, num_std=2.0)
        rsi = self._calculate_rsi(closes, period=5)

        if upper_bb is None or lower_bb is None:
            return {
                "action": "NO_SIGNAL",
                "confidence": 0.0,
                "reason": "Bollinger Bands calculation unavailable"
            }

        last_open = opens[-1]
        last_close = closes[-1]
        last_high = highs[-1]
        last_low = lows[-1]

        candle_range = max(last_high - last_low, 0.00001)
        body = abs(last_close - last_open)
        upper_wick = last_high - max(last_open, last_close)
        lower_wick = min(last_open, last_close) - last_low

        lower_wick_ratio = lower_wick / candle_range
        upper_wick_ratio = upper_wick / candle_range

        # CALL Signal: Lower rejection wick >= 50% of candle range, price near/below Lower BB, RSI oversold (< 25)
        if (last_low <= lower_bb or current_price <= lower_bb * 1.0005) and (lower_wick_ratio >= 0.45 or rsi < 22):
            confidence = min(0.95, 0.72 + (lower_wick_ratio * 0.18) + max(0, (25 - rsi) * 0.01))
            return {
                "action": "CALL",
                "confidence": round(confidence, 2),
                "reason": f"Bullish rejection / oversold reversal (LowerWick={lower_wick_ratio:.2f}, RSI={rsi:.1f})"
            }

        # PUT Signal: Upper rejection wick >= 50% of candle range, price near/above Upper BB, RSI overbought (> 75)
        if (last_high >= upper_bb or current_price >= upper_bb * 0.9995) and (upper_wick_ratio >= 0.45 or rsi > 78):
            confidence = min(0.95, 0.72 + (upper_wick_ratio * 0.18) + max(0, (rsi - 75) * 0.01))
            return {
                "action": "PUT",
                "confidence": round(confidence, 2),
                "reason": f"Bearish rejection / overbought reversal (UpperWick={upper_wick_ratio:.2f}, RSI={rsi:.1f})"
            }

        return {
            "action": "NO_SIGNAL",
            "confidence": 0.0,
            "reason": "No strong wick rejection or extreme boundary conditions detected"
        }
