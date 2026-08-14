"""
api/bliz.py
Bliz / Blitz Trading API and WebSocket Layer for IQ Option.
Handles high-frequency short duration options, actives mapping, order placement,
and real-time settlement tracking.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from api.auth import IQOptionAuth

logger = logging.getLogger("IQ_BOT.Bliz")

BLIZ_ACTIVES: Dict[str, int] = {
    "EURUSD": 1,
    "GBPUSD": 5,
    "USDJPY": 6,
    "AUDUSD": 99,
    "USDCAD": 100,
    "XAUUSD": 108,
    "EURUSD-OTC": 76,
    "GBPUSD-OTC": 81,
}


class BlizAPI:
    """
    Manages Bliz / Blitz Options trading on IQ Option.
    """

    def __init__(self, auth: IQOptionAuth):
        self.auth = auth
        self.actives_map = BLIZ_ACTIVES.copy()
        self._order_results: Dict[int, Dict[str, Any]] = {}
        self._result_events: Dict[int, threading.Event] = {}
        self._lock = threading.Lock()

        # Subscriptions
        self.auth.subscribe("option-closed", self._on_option_closed)
        self.auth.subscribe("blitz-option-closed", self._on_option_closed)

    def get_active_id(self, symbol: str) -> int:
        clean = symbol.replace("/", "").replace(" ", "").upper()
        return self.actives_map.get(clean, 1)

    def get_candles(
        self, symbol: str, timeframe_seconds: int = 60, count: int = 60
    ) -> List[Dict[str, Any]]:
        """Fetches candles for Bliz trading."""
        active_id = self.get_active_id(symbol)
        server_time = self.auth.get_server_time()
        req_id = f"bliz_candles_{self.auth.generate_request_id()}"

        msg = {
            "active_id": active_id,
            "size": timeframe_seconds,
            "count": count,
            "to": server_time,
        }

        response = self.auth.send_request("get-candles", msg, timeout=10.0, req_id=req_id)
        if response and "msg" in response:
            raw_candles = response["msg"]
            if isinstance(raw_candles, dict) and "candles" in raw_candles:
                raw_candles = raw_candles["candles"]
            if isinstance(raw_candles, list):
                parsed = []
                for c in raw_candles:
                    parsed.append(
                        {
                            "from": c.get("from", c.get("at", 0)),
                            "at": c.get("at", c.get("from", 0)),
                            "open": float(c.get("open", 0)),
                            "high": float(c.get("max", c.get("high", 0))),
                            "low": float(c.get("min", c.get("low", 0))),
                            "close": float(c.get("close", 0)),
                            "volume": float(c.get("volume", 0)),
                        }
                    )
                parsed.sort(key=lambda x: x["from"])
                return parsed
        return []

    def place_order(
        self,
        symbol: str,
        direction: str,
        amount: float,
        execution_time_minutes: int = 1,
    ) -> Dict[str, Any]:
        """Places a Bliz option order."""
        active_id = self.get_active_id(symbol)
        dir_clean = direction.strip().lower()
        opt_dir = "call" if dir_clean in ["buy", "call"] else "put"
        server_time = self.auth.get_server_time()
        exp_time = server_time + (max(1, int(execution_time_minutes)) * 60)

        req_id = f"bliz_order_{self.auth.generate_request_id()}"
        msg = {
            "price": float(amount),
            "act": active_id,
            "exp": exp_time,
            "type_id": 3,  # Turbo/Bliz type
            "direction": opt_dir,
            "time": server_time,
        }

        logger.info(
            f"Placing Bliz Order: {symbol} | Dir: {opt_dir.upper()} | Amount: ${amount} | Exp: {execution_time_minutes}m"
        )

        response = self.auth.send_request("buyV2", msg, timeout=10.0, req_id=req_id)
        if response and response.get("msg"):
            msg_body = response["msg"]
            order_id = msg_body.get("id")
            if order_id:
                with self._lock:
                    self._result_events[order_id] = threading.Event()
                return {
                    "success": True,
                    "order_id": order_id,
                    "symbol": symbol,
                    "direction": opt_dir.upper(),
                    "amount": amount,
                    "entry_price": float(msg_body.get("value", 0.0)),
                    "open_time": msg_body.get("created", server_time),
                    "expiration_time": exp_time,
                    "execution_time": execution_time_minutes,
                }

        return {"success": False, "error": "Bliz order rejected"}

    def wait_for_result(self, order_id: int, timeout: float = 300.0) -> Dict[str, Any]:
        """Waits for Bliz option settlement."""
        event = None
        with self._lock:
            event = self._result_events.get(order_id)
            if not event:
                event = threading.Event()
                self._result_events[order_id] = event

        settled = event.wait(timeout=timeout)
        with self._lock:
            res = self._order_results.pop(order_id, None)
            self._result_events.pop(order_id, None)

        if settled and res:
            return res

        return {
            "order_id": order_id,
            "status": "UNKNOWN",
            "result": "TIMEOUT",
            "pnl": 0.0,
            "exit_price": 0.0,
        }

    def _on_option_closed(self, msg_data: Dict[str, Any]):
        msg = msg_data.get("msg", {})
        if not isinstance(msg, dict):
            return

        order_id = msg.get("id") or msg.get("option_id")
        if not order_id:
            return

        pnl = float(msg.get("win_amount", 0.0) - msg.get("amount", 0.0))
        res_str = "WIN" if pnl > 0 else ("TIE" if pnl == 0 else "LOSS")

        payload = {
            "order_id": order_id,
            "status": "CLOSED",
            "result": res_str,
            "pnl": pnl,
            "exit_price": float(msg.get("close_quote", 0.0)),
            "close_time": msg.get("closed", self.auth.get_server_time()),
        }

        with self._lock:
            self._order_results[order_id] = payload
            if order_id in self._result_events:
                self._result_events[order_id].set()

        logger.info(f"Bliz Order #{order_id} Settled -> Result: {res_str} | PnL: ${pnl:+.2f}")
