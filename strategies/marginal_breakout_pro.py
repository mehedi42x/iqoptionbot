"""
Marginal Breakout Pro Strategy
Target: FOREX, MARGINAL
Primary Symbol: XAUUSD
Timeframe: 1 Minute

Pure Market Analysis Engine.
High-Low / Donchian channel breakout strategy with dynamic volatility SL/TP calculation.
"""

from typing import Dict, Any, List


class MarginalBreakoutPro:
    def __init__(self):
        self.name = "marginal_breakout_pro"
        self.compatible_trade_types = ["FOREX", "MARGINAL"]

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "timeframe": 60,
            "candle_count": 40,
            "need_live_price": True,
            "indicators": ["Donchian20", "ATR14", "VolumeExpansion"]
        }

    def _calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 1.5
        tr_list = []
        for i in range(1, len(closes)):
            h = highs[i]
            l = lows[i]
            prev_c = closes[i - 1]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_list.append(tr)

        if len(tr_list) < period:
            return 1.5
        return sum(tr_list[-period:]) / period

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze high/low channels and price expansion for breakout trading.
        """
        candles = market_data.get("candles", [])
        current_price = market_data.get("current_price")

        if not candles or len(candles) < 25 or current_price is None:
            return {
                "action": "NO_SIGNAL",
                "stop_loss": None,
                "take_profit": None,
                "confidence": 0.0,
                "reason": "Insufficient candle data for breakout analysis"
            }

        closes = [float(c.get("close", c.get("c", 0.0))) for c in candles]
        opens = [float(c.get("open", c.get("o", 0.0))) for c in candles]
        highs = [float(c.get("max", c.get("high", c.get("h", 0.0)))) for c in candles]
        lows = [float(c.get("min", c.get("low", c.get("l", 0.0)))) for c in candles]

        # Prior 20 candles channel (excluding the active candle)
        channel_high = max(highs[-21:-1])
        channel_low = min(lows[-21:-1])
        channel_mid = (channel_high + channel_low) / 2.0

        atr = self._calculate_atr(highs, lows, closes, 14)
        last_close = closes[-1]
        last_open = opens[-1]

        # Bullish Breakout: Current price breaks strictly above the 20-period high with a bullish close
        if current_price > channel_high and last_close >= last_open:
            sl_distance = max(atr * 1.5, current_price - channel_mid)
            tp_distance = sl_distance * 2.0  # 1:2 R:R

            stop_loss = round(current_price - sl_distance, 2)
            take_profit = round(current_price + tp_distance, 2)

            return {
                "action": "BUY",
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence": 0.88,
                "reason": f"Donchian 20-candle High breakout ({current_price:.2f} > {channel_high:.2f}, ATR={atr:.2f})"
            }

        # Bearish Breakout: Current price breaks strictly below the 20-period low with a bearish close
        if current_price < channel_low and last_close <= last_open:
            sl_distance = max(atr * 1.5, channel_mid - current_price)
            tp_distance = sl_distance * 2.0  # 1:2 R:R

            stop_loss = round(current_price + sl_distance, 2)
            take_profit = round(current_price - tp_distance, 2)

            return {
                "action": "SELL",
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence": 0.88,
                "reason": f"Donchian 20-candle Low breakout ({current_price:.2f} < {channel_low:.2f}, ATR={atr:.2f})"
            }

        return {
            "action": "NO_SIGNAL",
            "stop_loss": None,
            "take_profit": None,
            "confidence": 0.0,
            "reason": "Price consolidating inside Donchian channel"
        }

    def analyze_exit(self, market_data: Dict[str, Any], open_position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exit when price violates the midline of the channel.
        """
        current_price = market_data.get("current_price")
        direction = open_position.get("direction", "").upper()
        candles = market_data.get("candles", [])

        if not candles or current_price is None:
            return {"action": "HOLD", "reason": "Awaiting market data"}

        highs = [float(c.get("max", c.get("high", c.get("h", 0.0)))) for c in candles]
        lows = [float(c.get("min", c.get("low", c.get("l", 0.0)))) for c in candles]

        channel_high = max(highs[-20:])
        channel_low = min(lows[-20:])
        channel_mid = (channel_high + channel_low) / 2.0

        if direction == "BUY" and current_price < channel_mid:
            return {"action": "EXIT", "reason": "Breakout invalidated: price dropped below channel midline"}
        if direction == "SELL" and current_price > channel_mid:
            return {"action": "EXIT", "reason": "Breakout invalidated: price climbed above channel midline"}

        return {"action": "HOLD", "reason": "Breakout structure maintained"}
