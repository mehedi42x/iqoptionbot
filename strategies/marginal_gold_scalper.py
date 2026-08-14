"""
Marginal Gold Scalper Strategy
Target: FOREX, MARGINAL
Primary Symbol: XAUUSD
Timeframe: 1 Minute

Pure Market Analysis Engine.
Calculates exact Stop Loss and Take Profit based on dynamic volatility (ATR) and market structure.
"""

from typing import Dict, Any, List


class MarginalGoldScalper:
    def __init__(self):
        self.name = "marginal_gold_scalper"
        self.compatible_trade_types = ["FOREX", "MARGINAL"]

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "timeframe": 60,
            "candle_count": 40,
            "need_live_price": True,
            "indicators": ["EMA9", "EMA21", "ATR14", "SupportResistance"]
        }

    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return []
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        return ema

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
        atr = sum(tr_list[-period:]) / period
        return max(atr, 0.5)

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze gold market structure and trend alignment to generate BUY/SELL with precise SL/TP.
        """
        candles = market_data.get("candles", [])
        current_price = market_data.get("current_price")

        if not candles or len(candles) < 30 or current_price is None:
            return {
                "action": "NO_SIGNAL",
                "stop_loss": None,
                "take_profit": None,
                "confidence": 0.0,
                "reason": "Insufficient candle data for gold scalper"
            }

        closes = [float(c.get("close", c.get("c", 0.0))) for c in candles]
        opens = [float(c.get("open", c.get("o", 0.0))) for c in candles]
        highs = [float(c.get("max", c.get("high", c.get("h", 0.0)))) for c in candles]
        lows = [float(c.get("min", c.get("low", c.get("l", 0.0)))) for c in candles]

        ema9 = self._calculate_ema(closes, 9)
        ema21 = self._calculate_ema(closes, 21)
        atr = self._calculate_atr(highs, lows, closes, 14)

        if not ema9 or not ema21:
            return {
                "action": "NO_SIGNAL",
                "stop_loss": None,
                "take_profit": None,
                "confidence": 0.0,
                "reason": "EMA indicators calculation failed"
            }

        curr_ema9 = ema9[-1]
        curr_ema21 = ema21[-1]
        prev_ema9 = ema9[-2]
        prev_ema21 = ema21[-2]

        last_open = opens[-1]
        last_close = closes[-1]
        recent_low = min(lows[-6:])
        recent_high = max(highs[-6:])

        # BUY Setup: Fast EMA crosses or maintains above slow EMA, price pulls back and closes bullish
        if curr_ema9 > curr_ema21 and current_price >= curr_ema9:
            if last_close >= last_open:
                sl_distance = max(atr * 1.5, abs(current_price - recent_low) + 0.3)
                tp_distance = sl_distance * 1.8  # 1:1.8 Risk:Reward ratio

                stop_loss = round(current_price - sl_distance, 2)
                take_profit = round(current_price + tp_distance, 2)
                confidence = 0.85

                return {
                    "action": "BUY",
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "confidence": confidence,
                    "reason": f"Gold Bullish EMA trend breakout (EMA9={curr_ema9:.2f} > EMA21={curr_ema21:.2f}, ATR={atr:.2f})"
                }

        # SELL Setup: Fast EMA crosses or maintains below slow EMA, price pulls back and closes bearish
        if curr_ema9 < curr_ema21 and current_price <= curr_ema9:
            if last_close <= last_open:
                sl_distance = max(atr * 1.5, abs(recent_high - current_price) + 0.3)
                tp_distance = sl_distance * 1.8

                stop_loss = round(current_price + sl_distance, 2)
                take_profit = round(current_price - tp_distance, 2)
                confidence = 0.85

                return {
                    "action": "SELL",
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "confidence": confidence,
                    "reason": f"Gold Bearish EMA trend scalp (EMA9={curr_ema9:.2f} < EMA21={curr_ema21:.2f}, ATR={atr:.2f})"
                }

        return {
            "action": "NO_SIGNAL",
            "stop_loss": None,
            "take_profit": None,
            "confidence": 0.0,
            "reason": "Trend alignment or scalp setup threshold not satisfied"
        }

    def analyze_exit(self, market_data: Dict[str, Any], open_position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate if an open position should be closed early due to trend invalidation.
        """
        current_price = market_data.get("current_price")
        direction = open_position.get("direction", "").upper()
        candles = market_data.get("candles", [])

        if not candles or current_price is None:
            return {"action": "HOLD", "reason": "Awaiting market data"}

        closes = [float(c.get("close", c.get("c", 0.0))) for c in candles]
        ema9 = self._calculate_ema(closes, 9)
        ema21 = self._calculate_ema(closes, 21)

        if ema9 and ema21:
            if direction == "BUY" and ema9[-1] < ema21[-1]:
                return {"action": "EXIT", "reason": "Bearish EMA cross detected while long"}
            if direction == "SELL" and ema9[-1] > ema21[-1]:
                return {"action": "EXIT", "reason": "Bullish EMA cross detected while short"}

        return {"action": "HOLD", "reason": "Trend remains valid"}
