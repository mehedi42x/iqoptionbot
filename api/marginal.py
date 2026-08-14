"""
IQ Option Marginal & Forex Trading API Module
Responsible for Forex/Marginal instrument candles, live streaming, position opening with leverage,
position monitoring, and manual/automated position closing.
Contains NO strategy logic.
"""

import time
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("IQMarginalAPI")


class MarginalAPI:
    def __init__(self, auth):
        self.auth = auth

    def get_candles(self, symbol: str, timeframe: int, count: int) -> List[Dict[str, Any]]:
        """
        Fetch candles for Forex / Marginal instruments (e.g., XAUUSD).
        """
        if self.auth._is_mock or not self.auth.api:
            now = int(time.time())
            base_price = 2395.00 if "XAU" in symbol else 1.0850
            candles = []
            for i in range(count):
                ts = now - (count - i) * timeframe
                open_p = base_price + (i * 0.35) - (0.15 * (i % 3))
                close_p = open_p + 0.25 if i % 2 == 0 else open_p - 0.18
                high_p = max(open_p, close_p) + 0.40
                low_p = min(open_p, close_p) - 0.40
                candles.append({
                    "id": i,
                    "from": ts,
                    "at": ts + timeframe,
                    "to": ts + timeframe,
                    "open": round(open_p, 2),
                    "close": round(close_p, 2),
                    "min": round(low_p, 2),
                    "max": round(high_p, 2),
                    "volume": 250 + i * 10
                })
            return candles

        try:
            end_time = int(time.time())
            candles = self.auth.api.get_candles(symbol, timeframe, count, end_time)
            if candles and isinstance(candles, list):
                return candles
            return []
        except Exception as e:
            logger.error(f"Error fetching marginal candles for {symbol}: {e}")
            return []

    def get_realtime_price(self, symbol: str) -> Optional[float]:
        """
        Get live spot price for gold / forex asset.
        """
        if self.auth._is_mock or not self.auth.api:
            return 2402.50 if "XAU" in symbol else 1.0860

        try:
            candles = self.get_candles(symbol, 60, 1)
            if candles:
                return float(candles[-1].get("close", 0.0))
            return None
        except Exception as e:
            logger.error(f"Error getting marginal live price: {e}")
            return None

    def open_position(
        self,
        symbol: str,
        action: str,
        amount: float,
        leverage: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Open a Forex / Marginal position.
        action: 'buy' or 'sell'
        """
        action_clean = action.lower()
        if action_clean not in ["buy", "sell"]:
            return False, f"Invalid direction: {action}", None

        instrument_type = "forex" if "XAU" in symbol or "USD" in symbol else "crypto"

        if self.auth._is_mock or not self.auth.api:
            pos_id = f"mock_pos_{int(time.time())}"
            info = {
                "position_id": pos_id,
                "symbol": symbol,
                "action": action_clean,
                "amount": amount,
                "leverage": leverage,
                "open_price": self.get_realtime_price(symbol) or 2400.0,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "open_time": time.time(),
                "status": "open"
            }
            return True, pos_id, info

        try:
            # IQ Option marginal order execution
            # buy_order(instrument_type, active, side, amount, leverage, type="market", limit_price=None, stop_price=None, stop_loss_price=None, take_profit_price=None)
            check, order_id = self.auth.api.buy_order(
                instrument_type=instrument_type,
                instrument_id=symbol,
                side=action_clean,
                amount=amount,
                leverage=leverage,
                type="market",
                stop_loss_price=stop_loss,
                take_profit_price=take_profit
            )
            if check:
                info = {
                    "position_id": str(order_id),
                    "symbol": symbol,
                    "action": action_clean,
                    "amount": amount,
                    "leverage": leverage,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "open_time": time.time(),
                    "status": "open"
                }
                return True, str(order_id), info
            else:
                return False, f"Broker rejected position order: {order_id}", None
        except Exception as e:
            return False, f"Marginal position error: {str(e)}", None

    def close_position(self, position_id: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Close an open Forex / Marginal position.
        """
        if self.auth._is_mock or not self.auth.api:
            return True, {"position_id": position_id, "status": "closed", "pnl": 12.50}

        try:
            check = self.auth.api.close_position(position_id)
            if check:
                return True, {"position_id": position_id, "status": "closed"}
            return False, None
        except Exception as e:
            logger.error(f"Error closing position {position_id}: {e}")
            return False, None

    def get_position_pnl(self, position_id: str, open_position: Dict[str, Any]) -> Tuple[float, float]:
        """
        Calculate current unrealized PnL and current price for the position.
        Returns: (pnl, current_price)
        """
        current_price = self.get_realtime_price(open_position.get("symbol", "XAUUSD"))
        if current_price is None:
            return 0.0, 0.0

        open_price = float(open_position.get("open_price", current_price))
        amount = float(open_position.get("amount", 10))
        leverage = int(open_position.get("leverage", 1))
        direction = open_position.get("action", "buy").lower()

        if open_price > 0:
            if direction == "buy":
                pct_change = (current_price - open_price) / open_price
            else:
                pct_change = (open_price - current_price) / open_price
            pnl = round(amount * leverage * pct_change, 2)
        else:
            pnl = 0.0

        return pnl, current_price
