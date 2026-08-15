"""
api/bliz.py
Bliz / Blitz Trading API and WebSocket Layer for IQ Option.

Implements the Bliz trading protocol end-to-end:

  1. Server time sync      -> sendMessage { name: "get-servertime", version: "1.0" }
                              => servertime { msg: <unix_ts> }
  2. Live quote subscribe  -> subscribeMessage { name: "quote-generated",
                              params: { routingFilters: { active_id } } }
                              => continuous quote-generated { active_id, value, price, timestamp }
  3. Trade placement       -> sendMessage { name: "binary-options.open-option", version: "2.0",
                              body: { user_balance_id, active_id, option_type_id: 12, direction,
                                      expiration_size, expired, price, profit_percent,
                                      refund_value, value } }
                              => option { id, active_id, amount }
  4. Balance changed       -> balance-changed (handled by auth.py)
  5. Trade closed          -> option-closed { id, win, status, profit_amount, close_price }
  6. Heartbeat (ping)      -> ping / timeSync (handled by auth.py)
"""

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from api.auth import IQOptionAuth

logger = logging.getLogger("IQ_BOT.Bliz")

# Standard IQ Option active IDs.
# Override per-symbol via BLIZ_ACTIVE_ID in .env if your broker uses different IDs.
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

# --- Bliz protocol constants (per the trading protocol spec) ---
OPTION_TYPE_ID = 12   # Bliz option type
PROFIT_PERCENT = 92   # fixed payout percentage
REFUND_VALUE = 0      # no refund


class BlizAPI:
    """
    Bliz / Blitz options trading on IQ Option, following the
    sendMessage / subscribeMessage / binary-options.open-option protocol.
    """

    def __init__(self, auth: IQOptionAuth):
        self.auth = auth
        self.actives_map = BLIZ_ACTIVES.copy()
        self._apply_env_active_override()

        self._order_results: Dict[int, Dict[str, Any]] = {}
        self._result_events: Dict[int, threading.Event] = {}
        self._latest_quotes: Dict[int, Dict[str, Any]] = {}
        self._subscribed_actives: set = set()
        self._lock = threading.Lock()

        # Protocol event listeners
        self.auth.subscribe("quote-generated", self._on_quote_generated)
        self.auth.subscribe("option-closed", self._on_option_closed)
        self.auth.subscribe("blitz-option-closed", self._on_option_closed)

    # ------------------------------------------------------------------ #
    #  HELPERS
    # ------------------------------------------------------------------ #

    def _apply_env_active_override(self):
        """Allows overriding the active_id for the configured symbol via .env."""
        override = os.getenv("BLIZ_ACTIVE_ID", "").strip()
        if override:
            try:
                overridden = int(override)
                symbol = os.getenv("SYMBOL", "XAUUSD").strip().upper().replace("/", "").replace(" ", "")
                self.actives_map[symbol] = overridden
                logger.debug(f"Bliz active_id override: {symbol} -> {overridden}")
            except (ValueError, TypeError):
                logger.warning(f"Invalid BLIZ_ACTIVE_ID in .env: {override!r}")

    def get_active_id(self, symbol: str) -> int:
        clean = symbol.replace("/", "").replace(" ", "").upper()
        return self.actives_map.get(clean, 1)

    def get_candles(
        self, symbol: str, timeframe_seconds: int = 60, count: int = 60
    ) -> List[Dict[str, Any]]:
        """Fetches candles for strategy signal generation (analysis only)."""
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

    # ------------------------------------------------------------------ #
    #  1. SERVER TIME SYNC  (get-servertime)
    # ------------------------------------------------------------------ #

    def sync_server_time(self) -> int:
        """
        Explicitly requests the broker server time via the protocol:
        sendMessage { name: "get-servertime", version: "1.0" }
        """
        req_id = f"time_req_{self.auth.generate_request_id()}"
        msg = {"name": "get-servertime", "version": "1.0"}

        response = self.auth.send_request("sendMessage", msg, timeout=10.0, req_id=req_id)
        if response and isinstance(response.get("msg"), int):
            server_ts = response["msg"]
            self.auth.server_time = server_ts  # keep auth's cache in sync
            logger.debug(f"Server time synced: {server_ts}")
            return server_ts

        # fall back to the time already synced via ping/timeSync
        return self.auth.get_server_time()

    # ------------------------------------------------------------------ #
    #  2. LIVE QUOTE SUBSCRIPTION  (quote-generated)
    # ------------------------------------------------------------------ #

    def subscribe_quotes(self, symbol: str):
        """
        Subscribes to live tick/quote data for the asset:
        subscribeMessage { name: "quote-generated", params: { routingFilters: { active_id } } }
        After subscribing, the server streams continuous quote-generated messages.
        """
        active_id = self.get_active_id(symbol)
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
        logger.debug(f"Subscribed to live quotes for {symbol} (active_id={active_id})")

    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns the latest saved quote for the asset, if any."""
        active_id = self.get_active_id(symbol)
        with self._lock:
            return self._latest_quotes.get(active_id)

    def _on_quote_generated(self, msg_data: Dict[str, Any]):
        """Stores the latest live quote (value, price, timestamp) per active_id."""
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
    #  3. TRADE PLACEMENT  (binary-options.open-option v2.0)
    # ------------------------------------------------------------------ #

    def place_order(
        self,
        symbol: str,
        direction: str,
        amount: float,
        execution_time_seconds: int = 30,
    ) -> Dict[str, Any]:
        """
        Places a Bliz option order following the protocol:

        sendMessage {
          name: "binary-options.open-option",
          version: "2.0",
          body: {
            user_balance_id, active_id, option_type_id: 12, direction,
            expiration_size, expired, price, profit_percent, refund_value, value
          }
        }

        The `value` is the LATEST LIVE QUOTE value from the quote-generated subscription
        (never a local calculation).
        """
        active_id = self.get_active_id(symbol)
        dir_clean = direction.strip().lower()
        opt_dir = "call" if dir_clean in ["buy", "call"] else "put"

        # --- Ensure we are subscribed and have a live value ---
        self.subscribe_quotes(symbol)
        value = self._wait_for_quote_value(active_id, symbol, timeout=8.0)
        if value is None:
            return {"success": False, "error": "No live quote value received from subscription"}

        # --- Server time for accurate expiration ---
        server_time = self.sync_server_time()
        expiration_size = max(1, int(execution_time_seconds))
        expired = server_time + expiration_size

        body = {
            "user_balance_id": self.auth.active_balance_id,
            "active_id": active_id,
            "option_type_id": OPTION_TYPE_ID,      # 12 = Bliz
            "direction": opt_dir,
            "expiration_size": expiration_size,    # seconds
            "expired": expired,
            "price": float(amount),
            "profit_percent": PROFIT_PERCENT,
            "refund_value": REFUND_VALUE,
            "value": value,                        # live quote value
        }

        req_id = f"trade_{self.auth.generate_request_id()}"
        msg = {"name": "binary-options.open-option", "version": "2.0", "body": body}

        logger.debug(
            f"Placing Bliz Order: {symbol} | Dir: {opt_dir.upper()} | Amount: ${amount} | "
            f"Exp: {expiration_size}s | Value: {value}"
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
                    "symbol": symbol,
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

    def _wait_for_quote_value(self, active_id: int, symbol: str, timeout: float = 8.0) -> Optional[int]:
        """Waits briefly for the first live quote value after subscribing."""
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                quote = self._latest_quotes.get(active_id)
            if quote and quote.get("value") is not None:
                return quote["value"]
            time.sleep(0.2)
        logger.warning(f"No live quote received for {symbol} (active_id={active_id}) within {timeout}s")
        return None

    # ------------------------------------------------------------------ #
    #  5. TRADE RESULT  (option-closed)
    # ------------------------------------------------------------------ #

    def wait_for_result(self, order_id: int, timeout: float = 300.0) -> Dict[str, Any]:
        """Waits for the Bliz option settlement (server auto-sends option-closed)."""
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
        """
        Handles the auto-sent settlement message:

        option-closed {
          id: <trade_id>,
          win: true/false,
          status: "won"/"lost"/"equal",
          profit_amount: 9.20,
          close_price: 1.09880
        }
        """
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

        # status field has highest priority ("won" / "lost" / "equal")
        if status == "won":
            res_str, pnl = "WIN", profit_amount
        elif status == "lost":
            res_str = "LOSS"
            pnl = profit_amount if profit_amount < 0 else -profit_amount
        elif status == "equal":
            res_str, pnl = "TIE", 0.0
        else:
            # fall back to the win boolean flag
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
