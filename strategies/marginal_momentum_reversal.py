"""
Marginal Momentum Reversal Strategy
Target: FOREX, MARGINAL
Primary Symbol: XAUUSD
Timeframe: 1 Minute

Pure Market Analysis Engine.
MACD (12, 26, 9) + Stochastic Oscillator (14, 3, 3) divergence and dynamic SL/TP.
"""

from typing import Dict, Any, List


class MarginalMomentumReversal:
    def __init__(self):
        self.name = "marginal_momentum_reversal"
        self.compatible_trade_types = ["FOREX", "MARGINAL"]

    def get_requirements(self) -> Dict[str, Any]:
        return {
            "timeframe": 60,
            "candle_count": 45,
            "need_live_price": True,
            "indicators": ["MACD(12,26,9)", "Stochastic(14,3,3)", "ATR14"]
        }

    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        if len(prices) < period:
            return []
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        return ema

    def _calculate_macd(self, closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
        if len(closes) < slow + signal:
            return None, None, None
        ema_fast = self._calculate_ema(closes, fast)
        ema_slow = self._calculate_ema(closes, slow)

        # Align length
        offset = slow - fast
        ema_fast_trimmed = ema_fast[offset:]

        macd_line = [f - s for f, s in zip(ema_fast_trimmed, ema_slow)]
        if len(macd_line) < signal:
            return None, None, None
        signal_line = self._calculate_ema(macd_line, signal)
        macd_line_trimmed = macd_line[-len(signal_line):]
        histogram = [m - sig for m, sig in zip(macd_line_trimmed, signal_line)]

        return macd_line_trimmed[-1], signal_line[-1], histogram[-1]

    def _calculate_stochastic(self, highs: List[float], lows: List[float], closes: List[float], k_period: int = 14, d_period: int = 3):
        if len(closes) < k_period + d_period:
            return 50.0, 50.0
        k_values = []
        for i in range(k_period, len(closes) + 1):
            subset_h = highs[i - k_period:i]
            subset_l = lows[i - k_period:i]
            current_c = closes[i - 1]
            highest_h = max(subset_h)
            lowest_l = min(subset_l)
            if highest_h == lowest_l:
                k_values.append(50.0)
            else:
                k = ((current_c - lowest_l) / (highest_h - lowest_l)) * 100.0
                k_values.append(k)

        if len(k_values) < d_period:
            return 50.0, 50.0

        stoch_k = k_values[-1]
        stoch_d = sum(k_values[-d_period:]) / d_period
        return stoch_k, stoch_d

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
        Analyze MACD histogram turning points and Stochastic reversal boundaries.
        """
        candles = market_data.get("candles", [])
        current_price = market_data.get("current_price")

        if not candles or len(candles) < 40 or current_price is None:
            return {
                "action": "NO_SIGNAL",
                "stop_loss": None,
                "take_profit": None,
                "confidence": 0.0,
                "reason": "Insufficient candle data for momentum reversal"
            }

        closes = [float(c.get("close", c.get("c", 0.0))) for c in candles]
        highs = [float(c.get("max", c.get("high", c.get("h", 0.0)))) for c in candles]
        lows = [float(c.get("min", c.get("low", c.get("l", 0.0)))) for c in candles]

        macd_val, macd_sig, macd_hist = self._calculate_macd(closes)
        stoch_k, stoch_d = self._calculate_stochastic(highs, lows, closes)
        atr = self._calculate_atr(highs, lows, closes, 14)

        if macd_val is None or macd_sig is None or macd_hist is None:
            return {
                "action": "NO_SIGNAL",
                "stop_loss": None,
                "take_profit": None,
                "confidence": 0.0,
                "reason": "MACD calculation unavailable"
            }

        recent_low = min(lows[-8:])
        recent_high = max(highs[-8:])

        # BUY: Stochastic oversold (< 25) with %K crossing above %D and MACD showing bullish reversal
        if stoch_k < 28 and stoch_k > stoch_d and macd_hist > -0.5:
            sl_distance = max(atr * 1.5, abs(current_price - recent_low) + 0.3)
            tp_distance = sl_distance * 1.8

            stop_loss = round(current_price - sl_distance, 2)
            take_profit = round(current_price + tp_distance, 2)

            return {
                "action": "BUY",
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence": 0.86,
                "reason": f"Oversold stochastic cross + MACD momentum turn (StochK={stoch_k:.1f}, Hist={macd_hist:.3f})"
            }

        # SELL: Stochastic overbought (> 75) with %K crossing below %D and MACD showing bearish reversal
        if stoch_k > 72 and stoch_k < stoch_d and macd_hist < 0.5:
            sl_distance = max(atr * 1.5, abs(recent_high - current_price) + 0.3)
            tp_distance = sl_distance * 1.8

            stop_loss = round(current_price + sl_distance, 2)
            take_profit = round(current_price - tp_distance, 2)

            return {
                "action": "SELL",
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence": 0.86,
                "reason": f"Overbought stochastic cross + MACD momentum turn (StochK={stoch_k:.1f}, Hist={macd_hist:.3f})"
            }

        return {
            "action": "NO_SIGNAL",
            "stop_loss": None,
            "take_profit": None,
            "confidence": 0.0,
            "reason": "Oscillators within neutral territory"
        }

    def analyze_exit(self, market_data: Dict[str, Any], open_position: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exit when oscillators reach extreme opposing levels.
        """
        direction = open_position.get("direction", "").upper()
        candles = market_data.get("candles", [])

        if not candles:
            return {"action": "HOLD", "reason": "Awaiting candle data"}

        closes = [float(c.get("close", c.get("c", 0.0))) for c in candles]
        highs = [float(c.get("max", c.get("high", c.get("h", 0.0)))) for c in candles]
        lows = [float(c.get("min", c.get("low", c.get("l", 0.0)))) for c in candles]

        stoch_k, _ = self._calculate_stochastic(highs, lows, closes)

        if direction == "BUY" and stoch_k > 85:
            return {"action": "EXIT", "reason": "Stochastic reached extreme overbought level (>85)"}
        if direction == "SELL" and stoch_k < 15:
            return {"action": "EXIT", "reason": "Stochastic reached extreme oversold level (<15)"}

        return {"action": "HOLD", "reason": "Momentum condition active"}
