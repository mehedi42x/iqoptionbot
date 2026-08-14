"""
api/digital.py
Digital Option API and WebSocket Trading Layer for IQ Option.
Handles Digital Option instrument selection, strike determination, order placement (CALL/PUT),
and expiration result tracking.
"""

import datetime
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

from api.auth import IQOptionAuth

logger = logging.getLogger("IQ_BOT.Digital")

COMMON_DIGITAL_ACTIVES: Dict[str, int] = {
    "EURUSD": 1,
    "EURGBP": 2,
    "GBPJPY": 3,
    "EURJPY": 4,
    "GBPUSD": 5,
    "USDJPY": 6,
    "AUDUSD": 99,
    "USDCAD": 100,
    "AUDJPY": 101,
    "GBPCAD": 102,
    "EURCAD": 105,
    "XAUUSD": 108,
}


class DigitalAPI:
    """
    Manages Digital Option operations on IQ Option.
    """

    def __init__(self, auth: IQOptionAuth):
        self.auth = auth
        self.actives_map = COMMON_DIGITAL_ACTIVES.copy()
        self._order_results: Dict[int, Dict[str, Any]] = {}
        self._result_events: Dict[int, threading.Event] = {}
        self._lock = threading.Lock()

        # Subscribe to digital option events
        self.auth.subscribe("digital-option-closed", self._on_digital_closed)
        self.auth.subscribe("position-changed", self._on_position_changed)

    def get_active_id(self, symbol: str) -> int:
        """Resolves symbol to active ID for underlying asset."""
        clean = symbol.replace("/", "").replace(" ", "").upper()
        return self.actives_map.get(clean, 1)

    def get_candles(
        self, symbol: str, timeframe_seconds: int = 60, count: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetches candle data for the symbol."""
        active_id = self.get_active_id(symbol)
        server_time = self.auth.get_server_time()
        req_id = f"candles_{self.auth.generate_request_id()}"

        msg = {
            "active_id": active_id,
            "size": timeframe_seconds,
            "count": count,
            "to": server_time,
        }

        response = self.auth.send_request("get-candles", msg, timeout=12.0, req_id=req_id)
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

    def calculate_expiration_timestamp(self, execution_time_minutes: int) -> int:
        """
        Calculates expiration timestamp formatted for Digital Options (1m, 5m, 15m).
        """
        server_time = self.auth.get_server_time()
        duration_sec = execution_time_minutes * 60
        exp = int(server_time + duration_sec)
        rem = exp % (execution_time_minutes * 60)
        if rem != 0:
            exp += (execution_time_minutes * 60) - rem
        return exp

    def place_order(
        self,
        symbol: str,
        direction: str,
        amount: float,
        execution_time_minutes: int = 1,
    ) -> Dict[str, Any]:
        """
        Places a Digital Option order (CALL/PUT) with the specified duration.
        """
        dir_clean = direction.strip().lower()
        call_put = "call" if dir_clean in ["buy", "call"] else "put"
        active_id = self.get_active_id(symbol)
        exp_time = self.calculate_expiration_timestamp(execution_time_minutes)

        # IQ Option digital option instrument ID format: do{symbol_upper}{YYYYMMDD}{HHMM}{duration}PT{call_put_letter}
        clean_symbol = symbol.replace("/", "").replace(" ", "").upper()
        req_id = f"digital_order_{self.auth.generate_request_id()}"

        msg = {
            "user_balance_id": self.auth.active_balance_id,
            "instrument_active_id": active_id,
            "amount": str(amount),
            "direction": call_put,
            "expiration_time": exp_time,
            "underlying": clean_symbol,
        }

        logger.info(
            f"Placing Digital Option Order: {clean_symbol} | Dir: {call_put.upper()} | Amount: ${amount} | Exp: {execution_time_minutes}m"
        )

        response = self.auth.send_request(
            "digital-options.open-option", msg, timeout=10.0, req_id=req_id
        )

        if response and response.get("msg"):
            msg_body = response.get("msg")
            order_id = msg_body.get("id") or msg_body.get("position_id")
            if order_id:
                with self._lock:
                    self._result_events[order_id] = threading.Event()

                return {
                    "success": True,
                    "order_id": order_id,
                    "symbol": symbol,
                    "direction": call_put.upper(),
                    "amount": amount,
                    "entry_price": float(msg_body.get("open_price", 0.0)),
                    "open_time": msg_body.get("open_time", self.auth.get_server_time()),
                    "expiration_time": exp_time,
                    "execution_time": execution_time_minutes,
                }

        # Alternative protocol fallback for digital open-position
        fallback_msg = {
            "name": "digital-options.open-option",
            "version": "1.0",
            "body": {
                "user_balance_id": self.auth.active_balance_id,
                "instrument_id": f"do{clean_symbol}",
                "amount": float(amount),
                "direction": call_put,
            },
        }
        res_fb = self.auth.send_request("digital-options.open-option", fallback_msg, timeout=10.0)
        if res_fb and res_fb.get("msg", {}).get("id"):
            oid = res_fb["msg"]["id"]
            with self._lock:
                self._result_events[oid] = threading.Event()
            return {
                "success": True,
                "order_id": oid,
                "symbol": symbol,
                "direction": call_put.upper(),
                "amount": amount,
                "entry_price": 0.0,
                "open_time": self.auth.get_server_time(),
                "expiration_time": exp_time,
                "execution_time": execution_time_minutes,
            }

        return {"success": False, "error": "Digital option order rejected or timed out"}

    def wait_for_result(self, order_id: int, timeout: float = 360.0) -> Dict[str, Any]:
        """
        Waits for digital option settlement.
        """
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

    def _on_digital_closed(self, msg_data: Dict[str, Any]):
        """Handler for digital-option-closed message."""
        msg = msg_data.get("msg", {})
        if not isinstance(msg, dict):
            return

        order_id = msg.get("id") or msg.get("position_id")
        if not order_id:
            return

        pnl = float(msg.get("pnl", msg.get("profit", 0.0)))
        res_str = "WIN" if pnl > 0 else ("TIE" if pnl == 0 else "LOSS")
        exit_price = float(msg.get("close_price", msg.get("exit_price", 0.0)))

        result = {
            "order_id": order_id,
            "status": "CLOSED",
            "result": res_str,
            "pnl": pnl,
            "exit_price": exit_price,
            "close_time": msg.get("close_time", self.auth.get_server_time()),
        }

        with self._lock:
            self._order_results[order_id] = result
            if order_id in self._result_events:
                self._result_events[order_id].set()

        logger.info(f"Digital Option #{order_id} Closed -> Result: {res_str} | PnL: ${pnl:+.2f}")

    def _on_position_changed(self, msg_data: Dict[str, Any]):
        """Handles position update status for digital options."""
        msg = msg_data.get("msg", {})
        if isinstance(msg, dict) and msg.get("status") == "closed":
            order_id = msg.get("id")
            if order_id:
                pnl = float(msg.get("pnl", msg.get("close_profit", 0.0)))
                res_str = "WIN" if pnl > 0 else ("TIE" if pnl == 0 else "LOSS")
                result = {
                    "order_id": order_id,
                    "status": "CLOSED",
                    "result": res_str,
                    "pnl": pnl,
                    "exit_price": float(msg.get("close_price", 0.0)),
                    "close_time": self.auth.get_server_time(),
                }
                with self._lock:
                    self._order_results[order_id] = result
                    if order_id in self._result_events:
                        self._result_events[order_id].set()
