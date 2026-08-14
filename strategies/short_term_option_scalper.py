"""
Short-Term Option Scalper Strategy
Target: BINARY, DIGITAL, BLIZ
Timeframe: 1 Minute

Pure Market Analysis Engine.
Does NOT call APIs, place orders, or read environment variables.
"""

from typing import Dict, Any, List


class ShortTermOptionScalper:
    def __init__(self):
        self.name = "short_term_option_scalper"
        self.compatible_trade_types = ["BINARY", "DIGITAL", "BLIZ"]

    def get_requirements(self) -> Dict[str, Any]:
        """
        Define market data requirements for core.py to fetch.
        """
        return {
            "timeframe": 60,  # 1-minute candles (in seconds)
            "candle_count": 30,  # minimum required candles
            "need_live_price": True,
            "indicators": ["EMA5", "EMA13", "RSI7"]
        }

    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return []
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        return ema

    def _calculate_rsi(self, closes: List[float], period: int = 7) -> float:
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

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze 1-minute market data to detect momentum scalping signals.
        Returns:
            {"action": "CALL" | "PUT" | "NO_SIGNAL", "confidence": float, "reason": str}
        """
        candles = market_data.get("candles", [])
        current_price = market_data.get("current_price")

        if not candles or len(candles) < 20 or current_price is None:
            return {
                "action": "NO_SIGNAL",
                "confidence": 0.0,
                "reason": "Insufficient candle data for analysis"
            }

        closes = [float(c.get("close", c.get("c", 0.0))) for c in candles]
        opens = [float(c.get("open", c.get("o", 0.0))) for c in candles]
        highs = [float(c.get("max", c.get("high", c.get("h", 0.0)))) for c in candles]
        lows = [float(c.get("min", c.get("low", c.get("l", 0.0)))) for c in candles]

        # Indicator Calculations
        ema5 = self._calculate_ema(closes, 5)
        ema13 = self._calculate_ema(closes, 13)
        rsi = self._calculate_rsi(closes, 7)

        if not ema5 or not ema13:
            return {
                "action": "NO_SIGNAL",
                "confidence": 0.0,
                "reason": "Failed to calculate technical indicators"
            }

        curr_ema5 = ema5[-1]
        curr_ema13 = ema13[-1]
        prev_ema5 = ema5[-2]
        prev_ema13 = ema13[-2]

        last_open = opens[-1]
        last_close = closes[-1]
        last_high = highs[-1]
        last_low = lows[-1]

        prev_open = opens[-2]
        prev_close = closes[-2]

        body_size = abs(last_close - last_open)
        candle_range = max(last_high - last_low, 0.00001)
        body_ratio = body_size / candle_range

        # CALL Signal: EMA5 > EMA13, RSI between 45 and 75, Strong Bullish Momentum Candle
        if curr_ema5 > curr_ema13 and (prev_ema5 <= prev_ema13 or curr_ema5 - curr_ema13 > prev_ema5 - prev_ema13):
            if 48 <= rsi <= 72 and last_close > last_open and body_ratio > 0.55:
                confidence = min(0.92, 0.70 + (body_ratio * 0.15) + ((rsi - 50) / 100))
                return {
                    "action": "CALL",
                    "confidence": round(confidence, 2),
                    "reason": f"Bullish momentum scalp (EMA5 > EMA13, RSI={rsi:.1f}, BodyRatio={body_ratio:.2f})"
                }

        # PUT Signal: EMA5 < EMA13, RSI between 28 and 52, Strong Bearish Momentum Candle
        if curr_ema5 < curr_ema13 and (prev_ema5 >= prev_ema13 or curr_ema13 - curr_ema5 > prev_ema13 - prev_ema5):
            if 28 <= rsi <= 52 and last_close < last_open and body_ratio > 0.55:
                confidence = min(0.92, 0.70 + (body_ratio * 0.15) + ((50 - rsi) / 100))
                return {
                    "action": "PUT",
                    "confidence": round(confidence, 2),
                    "reason": f"Bearish momentum scalp (EMA5 < EMA13, RSI={rsi:.1f}, BodyRatio={body_ratio:.2f})"
                }

        return {
            "action": "NO_SIGNAL",
            "confidence": 0.0,
            "reason": "Market conditions do not meet scalper threshold criteria"
        }
