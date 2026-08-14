"""
api/binary.py
Binary Option API and WebSocket Trading Layer for IQ Option.
"""

import logging
import math
import threading
from typing import Any, Dict, List, Optional
from api.auth import IQOptionAuth

logger = logging.getLogger("IQ_BOT.Binary")

COMMON_BINARY_ACTIVES = {
    "EURUSD": 1, "EURGBP": 2, "GBPJPY": 3, "EURJPY": 4, "GBPUSD": 5,
    "USDJPY": 6, "AUDCAD": 7, "NZDUSD": 8, "USDCHF": 72, "AUDUSD": 99,
    "USDCAD": 100, "AUDJPY": 101, "GBPCAD": 102, "XAUUSD": 108,
}

class BinaryAPI:
    def __init__(self, auth: IQOptionAuth):
        self.auth = auth
        self.actives_map = COMMON_BINARY_ACTIVES.copy()
        self._order_results: Dict[int, Dict[str, Any]] = {}
        self._result_events: Dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self.auth.subscribe("option-closed", self._on_option_closed)

    def get_active_id(self, symbol: str) -> int:
        return self.actives_map.get(symbol.replace("/", "").upper(), 1)

    def get_candles(self, symbol: str, timeframe_seconds: int = 60, count: int = 100) -> List[Dict[str, Any]]:
        active_id = self.get_active_id(symbol)
        msg = {
            "active_id": active_id,
            "size": timeframe_seconds,
            "count": count,
            "to": self.auth.get_server_time(),
        }
        res = self.auth.send_request("get-candles", msg, timeout=12.0)
        if res and "msg" in res:
            candles = res["msg"].get("candles", res["msg"]) if isinstance(res["msg"], dict) else res["msg"]
            if isinstance(candles, list):
                parsed = [
                    {
                        "from": c.get("from", c.get("at", 0)),
                        "at": c.get("at", c.get("from", 0)),
                        "open": float(c.get("open", 0)),
                        "high": float(c.get("max", c.get("high", 0))),
                        "low": float(c.get("min", c.get("low", 0))),
                        "close": float(c.get("close", 0)),
                        "volume": float(c.get("volume", 0)),
                    }
                    for c in candles
                ]
                parsed.sort(key=lambda x: x["from"])
                return parsed
        return []

    def calculate_expiration(self, execution_time_minutes: int) -> int:
        server_time = self.auth.get_server_time()
        duration_sec = max(1, int(execution_time_minutes)) * 60
        exp = math.floor(server_time) + duration_sec
        rem = exp % 60
        return exp + (60 - rem) if rem != 0 else exp

    def place_order(self, symbol: str, direction: str, amount: float, execution_time_minutes: int = 1) -> Dict[str, Any]:
        active_id = self.get_active_id(symbol)
        opt_dir = "call" if direction.lower() in ["buy", "call"] else "put"
        exp_time = self.calculate_expiration(execution_time_minutes)
        type_id = 3 if execution_time_minutes <= 5 else 1

        msg = {
            "price": float(amount),
            "act": active_id,
            "exp": exp_time,
            "type_id": type_id,
            "direction": opt_dir,
            "time": self.auth.get_server_time(),
        }

        res = self.auth.send_request("buyV2", msg, timeout=10.0)
        if res and isinstance(res.get("msg"), dict) and res["msg"].get("id"):
            order_id = res["msg"]["id"]
            with self._lock:
                self._result_events[order_id] = threading.Event()
            return {
                "success": True,
                "order_id": order_id,
                "symbol": symbol,
                "direction": opt_dir.upper(),
                "amount": amount,
                "entry_price": float(res["msg"].get("value", 0.0)),
                "open_time": res["msg"].get("created", self.auth.get_server_time()),
                "expiration_time": exp_time,
            }
        return {"success": False, "error": res.get("msg", "Order rejected") if res else "Timeout"}

    def wait_for_result(self, order_id: int, timeout: float = 360.0) -> Dict[str, Any]:
        with self._lock:
            event = self._result_events.setdefault(order_id, threading.Event())
        settled = event.wait(timeout=timeout)
        with self._lock:
            res = self._order_results.pop(order_id, None)
            self._result_events.pop(order_id, None)
        return res or {"order_id": order_id, "status": "UNKNOWN", "result": "TIMEOUT", "pnl": 0.0, "exit_price": 0.0}

    def _on_option_closed(self, msg_data: Dict[str, Any]):
        msg = msg_data.get("msg", {})
        order_id = msg.get("id") or msg.get("option_id")
        if not order_id:
            return
        pnl = float(msg.get("win_amount", 0.0) - msg.get("amount", 0.0))
        result = "WIN" if pnl > 0 else ("TIE" if pnl == 0 else "LOSS")
        res_payload = {
            "order_id": order_id,
            "status": "CLOSED",
            "result": result,
            "pnl": pnl,
            "exit_price": float(msg.get("close_quote", 0.0)),
            "close_time": msg.get("closed", self.auth.get_server_time()),
        }
        with self._lock:
            self._order_results[order_id] = res_payload
            if order_id in self._result_events:
                self._result_events[order_id].set()
