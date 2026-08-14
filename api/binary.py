"""
IQ Option Binary Trading & Market Data API Module
Responsible for binary candle retrieval, trade execution, and trade resolution.
Contains NO strategy logic.
"""

import time
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("IQBinaryAPI")


class BinaryAPI:
    def __init__(self, auth):
        self.auth = auth

    def get_candles(self, symbol: str, timeframe: int, count: int) -> List[Dict[str, Any]]:
        """
        Fetch historical/recent candles for binary options.
        timeframe: duration in seconds (e.g. 60 for 1m)
        count: number of candles
        """
        if self.auth._is_mock or not self.auth.api:
            # Generate mock candle series for test/offline execution
            now = int(time.time())
            base_price = 1.0850 if "EUR" in symbol else 2390.00
            candles = []
            for i in range(count):
                ts = now - (count - i) * timeframe
                open_p = base_price + (i * 0.05) - (0.02 * (i % 3))
                close_p = open_p + 0.03 if i % 2 == 0 else open_p - 0.02
                high_p = max(open_p, close_p) + 0.02
                low_p = min(open_p, close_p) - 0.02
                candles.append({
                    "id": i,
                    "from": ts,
                    "at": ts + timeframe,
                    "to": ts + timeframe,
                    "open": round(open_p, 4),
                    "close": round(close_p, 4),
                    "min": round(low_p, 4),
                    "max": round(high_p, 4),
                    "volume": 100 + i * 5
                })
            return candles

        try:
            # iqoptionapi get_candles
            end_time = int(time.time())
            candles = self.auth.api.get_candles(symbol, timeframe, count, end_time)
            if candles and isinstance(candles, list):
                return candles
            return []
        except Exception as e:
            logger.error(f"Error fetching binary candles: {e}")
            return []

    def get_realtime_price(self, symbol: str) -> Optional[float]:
        """
        Get live spot price for binary asset.
        """
        if self.auth._is_mock or not self.auth.api:
            return 2395.20 if "XAU" in symbol else 1.0855

        try:
            candles = self.get_candles(symbol, 60, 1)
            if candles:
                return float(candles[-1].get("close", 0.0))
            return None
        except Exception as e:
            logger.error(f"Error getting real-time price: {e}")
            return None

    def execute_trade(self, symbol: str, amount: float, action: str, duration: int) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Execute binary option trade.
        action: 'call' or 'put'
        duration: expiration in minutes (1-5)
        """
        action_clean = action.lower()
        if action_clean not in ["call", "put"]:
            return False, f"Invalid binary direction: {action}", None

        if self.auth._is_mock or not self.auth.api:
            trade_id = f"mock_bin_{int(time.time())}"
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
                return False, f"Order rejected by broker: {order_id}", None
        except Exception as e:
            return False, f"Binary execution error: {str(e)}", None

    def check_trade_result(self, trade_id: str) -> Tuple[str, float]:
        """
        Check result of binary option trade.
        Returns: (status: 'WIN' | 'LOSE' | 'TIE' | 'PENDING', pnl: float)
        """
        if self.auth._is_mock or not self.auth.api:
            # Mock win result
            return "WIN", 8.5

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
            logger.error(f"Error checking binary trade result: {e}")
            return "PENDING", 0.0
