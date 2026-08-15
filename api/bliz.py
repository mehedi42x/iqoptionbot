"""
api/bliz.py
Bliz / Blitz Trading API and WebSocket Layer for IQ Option.
Pure API execution module: communicates ONLY with IQOptionAuth and core.py.
Completely decoupled from .env or os.getenv.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Union

from api.auth import IQOptionAuth

logger = logging.getLogger("IQ_BOT.Bliz")

# Bliz protocol constants
OPTION_TYPE_ID = 12   # Bliz option type
PROFIT_PERCENT = 92   # fixed payout percentage
REFUND_VALUE = 0      # no refund


class BlizAPI:
    """
    Bliz / Blitz options trading executor for IQ Option.
    Receives all parameters directly from core.py.
    """

    def __init__(self, auth: IQOptionAuth, active_id: Optional[int] = None):
        self.auth = auth
        self.default_active_id: Optional[int] = active_id

        self._order_results: Dict[int, Dict[str, Any]] = {}
        self._result_events: Dict[int, threading.Event] = {}
        self._latest_quotes: Dict[int, Dict[str, Any]] = {}
        self._subscribed_actives: set = set()
        self._lock = threading.Lock()

        # Protocol event listeners
        self.auth.subscribe("quote-generated", self._on_quote_generated)
        self.auth.subscribe("option-closed", self._on_option_closed)
        self.auth.subscribe("blitz-option-closed", self._on_option_closed)

    def _resolve_active_id(self, target: Optional[Union[int, str]] = None) -> int:
        """Resolves target into an integer active_id passed by core."""
        if isinstance(target, int):
            return target
        if isinstance(target, str) and target.isdigit():
            return int(target)
        if self.default_active_id is not None:
            return self.default_active_id
        return 1

    # ------------------------------------------------------------------ #
    #  CANDLE FETCHING
    # ------------------------------------------------------------------ #

    def get_candles(
        self,
        symbol_or_active_id: Any = None,
        timeframe_seconds: int = 60,
        count: int = 60,
        active_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Fetches candles for strategy analysis based on parameters from core.py."""
        aid = active_id or self._resolve_active_id(symbol_or_active_id)
        server_time = self.auth.get_server_time()
        req_id = f"bliz_candles_{self.auth.generate_request_id()}"

        msg = {
            "active_id": aid,
            "size": timeframe_seconds,
            "count": count,
            "to": server_time,
        }

        response = self.auth.send_request("get-candles", msg, timeout=10.0, req_id=req_id)

        # Fallback to v2 protocol if needed
        if not response or not response.get("msg"):
            v2_req_id = f"bliz_candles_v2_{self.auth.generate_request_id()}"
            v2_msg = {
                "name": "get-candles",
                "version": "2.0",
                "body": {
                    "active_id": aid,
                    "split": timeframe_seconds,
                    "count": count,
                    "to": server_time,
                }
            }
            response = self.auth.send_request("sendMessage", v2_msg, timeout=10.0, req_id=v2_req_id)

        if response and "msg" in response:
            raw_candles = response["msg"]
            if isinstance(raw_candles, dict):
                if "candles" in raw_candles:
                    raw_candles = raw_candles["candles"]
                elif "data" in raw_candles:
                    raw_candles = raw_candles["data"]
                elif "msg" in raw_candles:
                    raw_candles = raw_candles["msg"]

            if isinstance(raw_candles, list):
                parsed = []
                for c in raw_candles:
                    if not isinstance(c, dict):
                        continue
                    f_time = c.get("from", c.get("at", c.get("time", 0)))
                    o_price = float(c.get("open", 0.0))
                    h_price = float(c.get("max", c.get("high", o_price)))
                    l_price = float(c.get("min", c.get("low", o_price)))
                    c_price = float(c.get("close", o_price))
                    vol = float(c.get("volume", c.get("vol", 0.0)))
                    parsed.append({
                        "from": f_time,
                        "at": f_time,
                        "open": o_price,
                        "high": h_price,
                        "low": l_price,
                        "close": c_price,
                        "volume": vol,
                    })
                parsed.sort(key=lambda x: x["from"])
                return parsed
        return []

    # ------------------------------------------------------------------ #
    #  SERVER TIME & QUOTE STREAM
    # ------------------------------------------------------------------ #

    def sync_server_time(self) -> int:
        """Requests broker server time."""
        req_id = f"time_req_{self.auth.generate_request_id()}"
        msg = {"name": "get-servertime", "version": "1.0"}

        response = self.auth.send_request("sendMessage", msg, timeout=10.0, req_id=req_id)
        if response and isinstance(response.get("msg"), int):
            server_ts = response["msg"]
            self.auth.server_time = server_ts
            return server_ts

        return self.auth.get_server_time()

    def subscribe_quotes(self, target: Optional[Union[int, str]] = None):
        """Subscribes to live quote/tick stream for the active_id."""
        active_id = self._resolve_active_id(target)
        with self._lock:
            if active_id in self._subscribed_actives:
                return
            self._subscribed_actives.add(active_id)

        payload = {
            "name": "subscribeMessage",
            "msg": {
                "name": "quote-generated",
                "params": {
                    "routingFilters": {
                        "active_id": active_id,
                    }
                },
            },
            "request_id": f"sub_{self.auth.generate_request_id()}",
        }
        self.auth.send_raw(payload)
        logger.debug(f"Subscribed to live quotes (active_id={active_id})")

    def get_latest_quote(self, target: Optional[Union[int, str]] = None) -> Optional[Dict[str, Any]]:
        """Returns latest quote for active_id."""
        active_id = self._resolve_active_id(target)
        with self._lock:
            return self._latest_quotes.get(active_id)

    def _on_quote_generated(self, msg_data: Dict[str, Any]):
        """Stores latest live quote (value, price, timestamp)."""
        msg = msg_data.get("msg", {})
        if not isinstance(msg, dict):
            return
        active_id = msg.get("active_id")
        if active_id is None:
            return
        with self._lock:
            self._latest_quotes[active_id] = {
                "value": msg.get("value"),
                "price": msg.get("price"),
                "timestamp": msg.get("timestamp"),
            }
            self._subscribed_actives.add(active_id)

    # ------------------------------------------------------------------ #
    #  TRADE EXECUTION & SETTLEMENT
    # ------------------------------------------------------------------ #

    def place_order(
        self,
        symbol_or_active_id: Any,
        direction: str,
        amount: float,
        execution_time_seconds: int = 30,
    ) -> Dict[str, Any]:
        """Places a Bliz option order based on command from core.py."""
        active_id = self._resolve_active_id(symbol_or_active_id)
        dir_clean = direction.strip().lower()
        opt_dir = "call" if dir_clean in ["buy", "call"] else "put"

        self.subscribe_quotes(active_id)
        value = self._wait_for_quote_value(active_id, timeout=8.0)
        if value is None:
            return {"success": False, "error": f"No live quote value received for active_id={active_id}"}

        server_time = self.sync_server_time()
        expiration_size = max(1, int(execution_time_seconds))
        expired = server_time + expiration_size

        body = {
            "user_balance_id": self.auth.active_balance_id,
            "active_id": active_id,
            "option_type_id": OPTION_TYPE_ID,
            "direction": opt_dir,
            "expiration_size": expiration_size,
            "expired": expired,
            "price": float(amount),
            "profit_percent": PROFIT_PERCENT,
            "refund_value": REFUND_VALUE,
            "value": value,
        }

        req_id = f"trade_{self.auth.generate_request_id()}"
        msg = {"name": "binary-options.open-option", "version": "2.0", "body": body}

        logger.debug(
            f"Placing Bliz Order (active_id={active_id}) | Dir: {opt_dir.upper()} | "
            f"Amount: ${amount} | Exp: {expiration_size}s | Value: {value}"
        )

        response = self.auth.send_request("sendMessage", msg, timeout=12.0, req_id=req_id)

        if response and response.get("msg"):
            msg_body = response["msg"]
            order_id = msg_body.get("id")
            if order_id:
                with self._lock:
                    self._result_events[order_id] = threading.Event()
                quote = self._latest_quotes.get(active_id, {})
                return {
                    "success": True,
                    "order_id": order_id,
                    "active_id": active_id,
                    "direction": opt_dir.upper(),
                    "amount": amount,
                    "entry_price": float(quote.get("price") or 0.0),
                    "entry_value": value,
                    "open_time": server_time,
                    "expiration_time": expired,
                    "expiration_size": expiration_size,
                    "execution_time": execution_time_seconds,
                }

        return {"success": False, "error": f"Bliz order rejected: {response}"}

    def _wait_for_quote_value(self, active_id: int, timeout: float = 8.0) -> Optional[int]:
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                quote = self._latest_quotes.get(active_id)
            if quote and quote.get("value") is not None:
                return quote["value"]
            time.sleep(0.2)
        logger.warning(f"No live quote received for active_id={active_id} within {timeout}s")
        return None

    def wait_for_result(self, order_id: int, timeout: float = 300.0) -> Dict[str, Any]:
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

        win_flag = msg.get("win")
        status = str(msg.get("status", "")).lower()
        profit_amount = float(msg.get("profit_amount", msg.get("win_amount", 0.0)))
        close_price = float(msg.get("close_price", msg.get("close_quote", 0.0)))

        if status == "won":
            res_str, pnl = "WIN", profit_amount
        elif status == "lost":
            res_str = "LOSS"
            pnl = profit_amount if profit_amount < 0 else -profit_amount
        elif status == "equal":
            res_str = "TIE", 0.0
        else:
            if win_flag is True:
                res_str, pnl = "WIN", profit_amount
            elif win_flag is False:
                res_str = "LOSS"
                pnl = profit_amount if profit_amount < 0 else -profit_amount
            else:
                res_str, pnl = "TIE", 0.0

        payload = {
            "order_id": order_id,
            "status": "CLOSED",
            "result": res_str,
            "pnl": pnl,
            "exit_price": close_price,
            "close_time": msg.get("close_time", self.auth.get_server_time()),
        }

        with self._lock:
            self._order_results[order_id] = payload
            if order_id in self._result_events:
                self._result_events[order_id].set()

        logger.debug(f"Bliz Order #{order_id} Settled -> Result: {res_str} | PnL: ${pnl:+.2f}")
