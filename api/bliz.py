"""
IQ Option Blitz / Bliz Trading & Market Data API Module
Responsible for Bliz ultra short-term candles and trade execution.
Contains NO strategy logic.
"""

import time
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("IQBlizAPI")


class BlizAPI:
    def __init__(self, auth):
        self.auth = auth

    def get_candles(self, symbol: str, timeframe: int, count: int) -> List[Dict[str, Any]]:
        """
        Fetch ultra short-term candles for Bliz.
        """
        if self.auth._is_mock or not self.auth.api:
            now = int(time.time())
            base_price = 1.0850 if "EUR" in symbol else 2390.00
            candles = []
            for i in range(count):
                ts = now - (count - i) * timeframe
                open_p = base_price + (i * 0.02) - (0.01 * (i % 2))
                close_p = open_p + 0.015 if i % 2 == 0 else open_p - 0.015
                high_p = max(open_p, close_p) + 0.01
                low_p = min(open_p, close_p) - 0.01
                candles.append({
                    "id": i,
                    "from": ts,
                    "at": ts + timeframe,
                    "to": ts + timeframe,
                    "open": round(open_p, 4),
                    "close": round(close_p, 4),
                    "min": round(low_p, 4),
                    "max": round(high_p, 4),
                    "volume": 80 + i * 3
                })
            return candles

        try:
            end_time = int(time.time())
            candles = self.auth.api.get_candles(symbol, timeframe, count, end_time)
            if candles and isinstance(candles, list):
                return candles
            return []
        except Exception as e:
            logger.error(f"Error fetching Bliz candles: {e}")
            return []

    def get_realtime_price(self, symbol: str) -> Optional[float]:
        if self.auth._is_mock or not self.auth.api:
            return 2395.20 if "XAU" in symbol else 1.0855

        try:
            candles = self.get_candles(symbol, 60, 1)
            if candles:
                return float(candles[-1].get("close", 0.0))
            return None
        except Exception as e:
            logger.error(f"Error getting Bliz price: {e}")
            return None

    def execute_trade(self, symbol: str, amount: float, action: str, duration: int) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Execute Blitz option trade.
        """
        action_clean = action.lower()
        if action_clean not in ["call", "put"]:
            return False, f"Invalid direction: {action}", None

        if self.auth._is_mock or not self.auth.api:
            trade_id = f"mock_bliz_{int(time.time())}"
            info = {
                "id": trade_id,
                "symbol": symbol,
                "amount": amount,
                "action": action_clean,
                "duration": duration,
                "open_time": time.time(),
                "status": "open"
            }
            return True, trade_id, info

        try:
            # Bliz options route through high-frequency binary engine
            check, order_id = self.auth.api.buy(amount, symbol, action_clean, duration)
            if check:
                info = {
                    "id": str(order_id),
                    "symbol": symbol,
                    "amount": amount,
                    "action": action_clean,
                    "duration": duration,
                    "open_time": time.time(),
                    "status": "open"
                }
                return True, str(order_id), info
            else:
                return False, f"Bliz order rejected: {order_id}", None
        except Exception as e:
            return False, f"Bliz execution error: {str(e)}", None

    def check_trade_result(self, trade_id: str) -> Tuple[str, float]:
        """
        Check Bliz trade resolution.
        """
        if self.auth._is_mock or not self.auth.api:
            return "WIN", 8.0

        try:
            result, pnl = self.auth.api.check_win_v3(trade_id)
            if result:
                pnl_val = float(pnl) if pnl is not None else 0.0
                if pnl_val > 0:
                    return "WIN", pnl_val
                elif pnl_val < 0:
                    return "LOSE", pnl_val
                else:
                    return "TIE", 0.0
            return "PENDING", 0.0
        except Exception as e:
            logger.error(f"Error checking Bliz trade result: {e}")
            return "PENDING", 0.0
