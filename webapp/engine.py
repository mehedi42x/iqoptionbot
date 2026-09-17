"""
IQ Option live trading engine for the web dashboard.

The WebSocket protocol, login flow, candle subscription, order payload and
result handling follow the supplied IQ Option reference bot. Instead of
printing to a console, every event is pushed onto an in-memory event bus which
the FastAPI layer streams to the browser over WebSocket.
"""
from __future__ import annotations

import json
import ssl
import time
import threading
import importlib.util
import traceback
from collections import deque

import requests
import websocket

LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
WS_URL = "wss://iqoption.com/echo/websocket"

# The web app does not ship an account, asset, or strategy configuration.
# Everything is supplied by the user through Account & Risk and Script Lab.
ACCOUNT_TYPE_IDS = {
    "PRACTICE": 4,
    "REAL": 1,
}

# Keep the broker payload aligned with the supplied WebSocket reference.
OPTION_TYPE_ID = 12


def now_ms() -> int:
    return int(time.time() * 1000)


class EventBus:
    """Thread-safe fan-out of engine events to any number of subscribers."""

    def __init__(self, history: int = 400):
        self._lock = threading.Lock()
        self._subs: list[deque] = []
        self._history: deque = deque(maxlen=history)

    def subscribe(self) -> deque:
        q: deque = deque(maxlen=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: deque) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event_type: str, payload=None) -> None:
        evt = {"type": event_type, "ts": now_ms(), "data": payload or {}}
        with self._lock:
            if event_type == "log":
                self._history.append(evt)
            for q in self._subs:
                q.append(evt)

    def history(self) -> list:
        with self._lock:
            return list(self._history)


class StrategyRunner:
    """Load one user-authored Script Lab strategy from a Python source file."""

    def __init__(self, source_path: str):
        if not source_path:
            raise RuntimeError("Create and save a strategy in Script Lab first.")
        self.name = source_path
        spec = importlib.util.spec_from_file_location(
            f"user_strategy_{int(time.time() * 1000000)}", source_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load the strategy source file")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "Strategy"):
            raise RuntimeError("Strategy file must define a class named `Strategy`")
        self.module = module
        self.strategy = module.Strategy()

    def required_timeframes(self) -> list[int]:
        """Discover timeframes exactly as the supplied bot contract does."""
        s = self.strategy
        if hasattr(s, "get_required_timeframes"):
            timeframes = s.get_required_timeframes()
        elif hasattr(s, "required_timeframes"):
            timeframes = s.required_timeframes
        else:
            timeframes = [60]

        out = set()
        for timeframe in timeframes or []:
            try:
                timeframe = int(timeframe)
                if timeframe > 0:
                    out.add(timeframe)
            except (TypeError, ValueError):
                continue
        return sorted(out) or [60]

    def feed(self, timeframe: int, candle: dict):
        """Use the universal contract, then the reference bot's legacy fallbacks."""
        s = self.strategy
        if hasattr(s, "update_candle"):
            return s.update_candle(timeframe, candle)
        name = f"update_{timeframe}s" if timeframe < 60 else f"update_{timeframe // 60}m"
        if hasattr(s, name):
            return getattr(s, name)(candle)
        if hasattr(s, "check_signal"):
            return s.check_signal()
        return None

    def status(self) -> dict:
        if hasattr(self.strategy, "get_status"):
            try:
                value = self.strategy.get_status()
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
        return {}


class IQOptionEngine:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.lock = threading.RLock()

        # ---- account config -------------------------------------------
        self.email = ""
        self.password = ""
        self.account_type = None
        self.active_id = None
        self.active_name = ""
        self.amount = None
        self.expiration = None
        self.max_concurrent_trades = None

        # ---- connection state -----------------------------------------
        self.ssid = None
        self.ws: websocket.WebSocketApp | None = None
        self.balances: dict = {}
        self.balance_id = None
        self.balance_amount = 0.0
        self.currency = "USD"
        self.profile: dict = {}
        self.request_id = 0
        self.is_connected = False
        self._stop = False

        # ---- trading state --------------------------------------------
        self.auto_trading = False
        self.runner: StrategyRunner | None = None
        self.strategy_label = None
        self.required_timeframes: list[int] = []
        self.chart_timeframe: int | None = None
        self.candles: dict[int, list] = {}
        self.subscribed: set[int] = set()

        self.active_trades_count = 0
        self.pending_trades: dict[str, dict] = {}
        self.open_trades: dict[str, dict] = {}
        self.trade_history: list[dict] = []
        self.markers: list[dict] = []
        self.wins = 0
        self.losses = 0
        self.draws = 0
        self.pnl = 0.0

    # ==================================================================
    # helpers
    # ==================================================================
    def log(self, message: str, level: str = "info"):
        self.bus.publish("log", {"level": level, "message": message})

    def _next_id(self) -> str:
        with self.lock:
            self.request_id += 1
            return str(self.request_id)

    def _send(self, payload: dict) -> bool:
        if not self.ws:
            return False
        try:
            self.ws.send(json.dumps(payload))
            return True
        except Exception as e:
            self.log(f"WS send error: {e}", "error")
            return False

    def snapshot(self) -> dict:
        with self.lock:
            total = self.wins + self.losses
            return {
                "connected": self.is_connected,
                "email": self.email,
                "account_type": self.account_type,
                "balance": round(self.balance_amount, 2),
                "currency": self.currency,
                "user_id": self.profile.get("user_id"),
                "name": self.profile.get("name"),
                "active_id": self.active_id,
                "active_name": self.active_name,
                "amount": self.amount,
                "expiration": self.expiration,
                "max_concurrent_trades": self.max_concurrent_trades,
                "auto_trading": self.auto_trading,
                "strategy": self.strategy_label,
                "timeframes": self.required_timeframes,
                "chart_timeframe": self.chart_timeframe,
                "active_trades": self.active_trades_count,
                "wins": self.wins,
                "losses": self.losses,
                "draws": self.draws,
                "pnl": round(self.pnl, 2),
                "winrate": round(self.wins / total * 100, 2) if total else 0.0,
                "open_trades": list(self.open_trades.values()),
                "history": self.trade_history[-50:],
                "strategy_status": self.runner.status() if self.runner else {},
            }

    def push_state(self):
        self.bus.publish("state", self.snapshot())

    # ==================================================================
    # login / connect
    # ==================================================================
    def configure(self, **kw):
        with self.lock:
            for key in (
                "email", "password", "account_type", "active_id", "active_name",
                "amount", "expiration", "max_concurrent_trades",
            ):
                if key in kw and kw[key] is not None:
                    value = kw[key]
                    if key in ("active_id", "expiration", "max_concurrent_trades"):
                        value = int(value)
                    elif key == "amount":
                        value = float(value)
                    elif key == "account_type":
                        value = str(value).upper()
                    setattr(self, key, value)
        self.push_state()

    def login(self) -> bool:
        if not self.email or not self.password:
            self.log("Email / password missing. Fill in Account Setup first.", "error")
            return False
        self.log("Authenticating with IQ Option...")
        try:
            resp = requests.post(
                LOGIN_URL,
                json={"identifier": self.email, "password": self.password},
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            self.ssid = resp.cookies.get("ssid") or resp.json().get("ssid")
            if not self.ssid:
                raise RuntimeError("SSID not found in response")
            self.log("Login success, SSID acquired", "success")
            return True
        except Exception as e:
            self.log(f"Login failed: {e}", "error")
            return False

    def connect(self) -> bool:
        if self.is_connected:
            self.log("Already connected.", "warn")
            return True

        missing = []
        for key, value in (
            ("email", self.email),
            ("password", self.password),
            ("account type", self.account_type),
            ("ACTIVE_ID", self.active_id),
            ("trade amount", self.amount),
            ("expiration", self.expiration),
            ("max concurrent trades", self.max_concurrent_trades),
            ("Script Lab strategy", self.runner),
        ):
            if value in (None, ""):
                missing.append(key)
        if missing:
            self.log("Complete Account & Risk first: " + ", ".join(missing), "error")
            return False

        if not self.login():
            return False
        self._stop = False
        self.log("Connecting to WebSocket...")
        self.ws = websocket.WebSocketApp(
            WS_URL,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        threading.Thread(
            target=self.ws.run_forever,
            kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}},
            daemon=True,
        ).start()
        return True

    def disconnect(self):
        self._stop = True
        self.auto_trading = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.is_connected = False
        self.log("Disconnected by user.", "warn")
        self.push_state()

    # ==================================================================
    # websocket callbacks
    # ==================================================================
    def on_open(self, ws):
        self.is_connected = True
        self.log("WebSocket connected", "success")

        # This handshake and subscription order intentionally mirrors the
        # supplied reference bot: SSID, balances, then only the strategy's
        # requested candle timeframes.
        self._send({"name": "ssid", "msg": self.ssid, "request_id": self._next_id()})
        time.sleep(1)
        self._send({
            "name": "sendMessage",
            "msg": {"name": "get-balances", "version": "1.0"},
            "request_id": self._next_id(),
        })
        time.sleep(1)
        self.subscribed.clear()
        for timeframe in self.required_timeframes:
            self.subscribe_candles(timeframe)
            time.sleep(0.2)
        self.push_state()

    def on_error(self, ws, error):
        self.is_connected = False
        self.log(f"WebSocket error: {error}", "error")
        self.push_state()

    def on_close(self, ws, code, msg):
        self.is_connected = False
        self.log("WebSocket disconnected", "warn")
        self.push_state()

    # ==================================================================
    # subscriptions
    # ==================================================================
    def subscribe_candles(self, size: int):
        size = int(size)
        if size in self.subscribed:
            return
        ok = self._send({
            "name": "subscribeMessage",
            "msg": {
                "name": "candle-generated",
                "params": {"routingFilters": {"active_id": self.active_id, "size": size}},
            },
            "request_id": self._next_id(),
        })
        if ok:
            self.subscribed.add(size)
            self.candles.setdefault(size, [])
            self.log(f"Subscribed candles {size}s on active {self.active_id}")

    def unsubscribe_candles(self, size: int):
        size = int(size)
        self._send({
            "name": "unsubscribeMessage",
            "msg": {
                "name": "candle-generated",
                "params": {"routingFilters": {"active_id": self.active_id, "size": size}},
            },
            "request_id": self._next_id(),
        })
        self.subscribed.discard(size)

    def switch_asset(self, active_id: int, active_name: str):
        old = self.active_id
        with self.lock:
            self.active_id = int(active_id)
            self.active_name = active_name
            self.candles = {tf: [] for tf in self.candles}
            self.markers = []
        if self.is_connected:
            for tf in list(self.subscribed):
                self._send({
                    "name": "unsubscribeMessage",
                    "msg": {
                        "name": "candle-generated",
                        "params": {"routingFilters": {"active_id": old, "size": tf}},
                    },
                    "request_id": self._next_id(),
                })
            self.subscribed.clear()
            for tf in self.required_timeframes:
                self.subscribe_candles(tf)
        if self.runner and hasattr(self.runner.strategy, "reset"):
            try:
                self.runner.strategy.reset()
            except Exception:
                pass
        self.log(f"Asset switched to {active_name} (id {active_id})", "success")
        self.bus.publish("chart_reset", {"active_name": active_name})
        self.push_state()

    def set_chart_timeframe(self, size: int):
        size = int(size)
        self.chart_timeframe = size
        self.candles.setdefault(size, [])
        if self.required_timeframes and size not in self.required_timeframes:
            self.log(
                f"Chart timeframe {size}s is not subscribed; load a strategy that requests it.",
                "warn",
            )
        self.bus.publish("chart_reset", {"active_name": self.active_name})
        self.push_state()

    # ==================================================================
    # message routing
    # ==================================================================
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return
        name = data.get("name")
        try:
            if name == "balances":
                self._handle_balances(data)
            elif name == "balance-changed":
                self._handle_balance_changed(data)
            elif name == "candle-generated":
                self._handle_candle(data)
            elif name in ("option", "option-open"):
                self._handle_open(data)
            elif name in ("option-closed", "portfolio.position-changed", "position-changed"):
                self._handle_close(data)
        except Exception:
            self.log(f"Handler error on '{name}': {traceback.format_exc(limit=2)}", "error")

    def _handle_balances(self, data):
        target = ACCOUNT_TYPE_IDS.get(self.account_type, 4)
        for b in data.get("msg", []) or []:
            self.balances[b.get("type")] = b
            if b.get("type") == target:
                self.balance_id = b.get("id")
                self.balance_amount = float(b.get("amount") or 0)
                self.currency = b.get("currency", "USD")
        self.log(
            f"Balance selected: {self.account_type} "
            f"{self.balance_amount} {self.currency}",
            "success",
        )
        self.push_state()

    def _handle_balance_changed(self, data):
        msg = (data.get("msg") or {}).get("current_balance") or data.get("msg") or {}
        if msg.get("id") == self.balance_id and msg.get("amount") is not None:
            self.balance_amount = float(msg["amount"])
            self.push_state()

    def switch_balance(self, account_type: str):
        self.account_type = str(account_type).upper()
        target = ACCOUNT_TYPE_IDS.get(self.account_type, 4)
        b = self.balances.get(target)
        if b:
            self.balance_id = b.get("id")
            self.balance_amount = float(b.get("amount") or 0)
            self.currency = b.get("currency", "USD")
        elif self.is_connected:
            self._send({
                "name": "sendMessage",
                "msg": {"name": "get-balances", "version": "1.0"},
                "request_id": self._next_id(),
            })
        self.log(f"Account type -> {self.account_type}", "success")
        self.push_state()

    # ---------------- candles ----------------
    @staticmethod
    def _norm(c: dict) -> dict | None:
        low = c.get("low")
        if low is None:
            low = c.get("min")
        high = c.get("high")
        if high is None:
            high = c.get("max")
        o, cl = c.get("open"), c.get("close")
        ts = c.get("from") or c.get("timestamp") or c.get("at")
        if None in (low, high, o, cl, ts):
            return None
        try:
            ts = float(ts)
            if ts > 1e11:
                ts = ts / 1e9 if ts > 1e15 else ts / 1000.0
            return {
                "timestamp": int(ts), "from": int(ts),
                "open": float(o), "high": float(high),
                "low": float(low), "close": float(cl),
                "volume": c.get("volume", 0),
                "size": c.get("size"),
            }
        except (TypeError, ValueError):
            return None

    def _handle_candle(self, data):
        # The reference bot ignores every timeframe that the loaded strategy
        # did not request. This prevents the chart or another subscriber from
        # accidentally feeding a second timeframe into the strategy.
        raw = data.get("msg") or {}
        size = raw.get("size")
        try:
            size = int(size)
        except (TypeError, ValueError):
            return
        if size not in self.required_timeframes:
            return

        candle = self._norm(raw)
        if candle is None:
            return
        candle["size"] = size

        # Keep the same bounded append behavior as the supplied bot.
        store = self.candles.setdefault(size, [])
        store.append(candle)
        if len(store) > 500:
            self.candles[size] = store[-500:]
            store = self.candles[size]

        if size == self.chart_timeframe:
            self.bus.publish("candle", {"timeframe": size, "candle": candle})
            self._check_open_trades(candle["close"])

        if not self.runner:
            return

        signal = None
        try:
            signal = self.runner.feed(size, dict(candle))
        except Exception as e:
            self.log(f"Strategy error: {e}", "error")

        if signal:
            sig = str(signal).lower()
            self.log(f"SIGNAL {sig.upper()} on {size}s from {self.strategy_label}", "signal")
            self.bus.publish("signal", {
                "direction": sig, "timeframe": size,
                "price": candle["close"], "time": candle["timestamp"],
                "strategy": self.strategy_label,
            })
            if self.auto_trading:
                self.place_trade(sig, source="auto")
            else:
                self.log("Auto-trading OFF -> signal not executed.", "warn")
        else:
            self.bus.publish("strategy_status", self.runner.status())

    # ---------------- trading ----------------
    def place_trade(self, direction: str, amount: float | None = None,
                    expiration: int | None = None, source: str = "manual"):
        direction = str(direction).lower()
        if direction in ("buy", "up"):
            direction = "call"
        if direction in ("sell", "down"):
            direction = "put"
        if direction not in ("call", "put"):
            self.log(f"Invalid direction: {direction}", "error")
            return False
        if not self.is_connected:
            self.log("Not connected -- cannot place trade.", "error")
            return False

        amount = amount if amount is not None else self.amount
        expiration = expiration if expiration is not None else self.expiration
        if amount is None or expiration is None or self.max_concurrent_trades is None:
            self.log("Set trade amount, expiration, and concurrency in Account & Risk first.", "error")
            return False
        amount = float(amount)
        expiration = int(expiration)

        with self.lock:
            if self.active_trades_count >= self.max_concurrent_trades:
                self.log("Max concurrent trades reached -- skipping.", "warn")
                return False
            if not self.balance_id:
                self.log("Balance ID unavailable.", "error")
                return False
            self.active_trades_count += 1

        req_id = self._next_id()
        expired = int(time.time()) + expiration

        payload = {
            "name": "sendMessage",
            "request_id": req_id,
            "msg": {
                "name": "binary-options.open-option",
                "version": "2.0",
                "body": {
                    "user_balance_id": self.balance_id,
                    "active_id": self.active_id,
                    "option_type_id": OPTION_TYPE_ID,
                    "direction": direction,
                    "expiration_size": expiration,
                    "expired": expired,
                    "price": amount,
                    "profit_percent": 0,
                    "refund_value": 0,
                },
            },
        }

        if not self._send(payload):
            with self.lock:
                self.active_trades_count = max(0, self.active_trades_count - 1)
            return False

        entry_price = None
        store = self.candles.get(self.chart_timeframe) or []
        if store:
            entry_price = store[-1]["close"]

        trade = {
            "id": req_id,
            "direction": direction,
            "amount": amount,
            "expiration": expiration,
            "asset": self.active_name,
            "source": source,
            "strategy": self.strategy_label if source == "auto" else None,
            "open_time": int(time.time()),
            "expire_time": expired,
            "entry_price": entry_price,
            "current_price": entry_price,
            "status": "open",
            "result": None,
            "profit": 0.0,
        }
        self.pending_trades[req_id] = trade
        self.open_trades[req_id] = trade

        marker = {
            "time": trade["open_time"], "price": entry_price,
            "direction": direction, "id": req_id, "status": "open",
        }
        self.markers.append(marker)
        self.bus.publish("trade_open", trade)
        self.log(
            f"TRADE PLACED {direction.upper()} ${amount} {expiration}s "
            f"on {self.active_name or self.active_id} [{source}]",
            "trade",
        )
        self.push_state()
        return True

    def _check_open_trades(self, price: float):
        changed = False
        for t in list(self.open_trades.values()):
            if t.get("entry_price") is None:
                t["entry_price"] = price
            t["current_price"] = price
            delta = price - t["entry_price"]
            t["floating"] = (
                "winning" if (delta > 0) == (t["direction"] == "call") and delta != 0
                else ("losing" if delta != 0 else "flat")
            )
            t["seconds_left"] = max(0, t["expire_time"] - int(time.time()))
            changed = True
        if changed:
            self.bus.publish("trades_tick", {"open": list(self.open_trades.values())})

    def _reject_trade(self, request_id: str, message: str):
        """Remove a rejected pending order so the UI/concurrency count cannot stick."""
        trade = self.pending_trades.pop(request_id, None)
        if not trade:
            return
        self.open_trades.pop(request_id, None)
        if trade.get("option_id") is not None:
            self.open_trades.pop(str(trade["option_id"]), None)
        with self.lock:
            self.active_trades_count = max(0, self.active_trades_count - 1)
        self.log(f"Trade rejected: {message or 'Unknown error'}", "error")
        self.push_state()

    def _handle_open(self, data):
        msg = data.get("msg") or {}
        rid = str(data.get("request_id") or "")
        trade = self.pending_trades.get(rid)
        if not trade:
            return
        if msg.get("is_successful") is False:
            self._reject_trade(rid, str(msg.get("message") or "Unknown error"))
            return

        opt_id = msg.get("id") or (msg.get("option") or {}).get("id")
        if opt_id:
            trade["option_id"] = opt_id
            # A broker option id replaces the temporary request id. Keeping
            # both keys rendered the same live position twice in the browser.
            self.open_trades.pop(rid, None)
            self.open_trades[str(opt_id)] = trade
        if msg.get("value") is not None:
            try:
                trade["entry_price"] = float(msg["value"])
            except (TypeError, ValueError):
                pass
        self.bus.publish("trade_open", trade)

    def _handle_close(self, data):
        msg = data.get("msg") or {}
        if isinstance(msg, dict) and msg.get("status") == "open":
            return

        if msg.get("is_successful") is False:
            rid = str(data.get("request_id") or "")
            if not rid:
                rid = str(msg.get("request_id") or "")
            self._reject_trade(rid, str(msg.get("message") or "Unknown error"))
            return

        opt_id = str(msg.get("id") or msg.get("option_id") or "")
        trade = self.open_trades.pop(opt_id, None)
        if trade is None and self.open_trades:
            # fall back to the oldest open trade
            oldest = sorted(self.open_trades.values(), key=lambda t: t["open_time"])[0]
            trade = self.open_trades.pop(oldest["id"], None) or oldest
            self.open_trades.pop(str(oldest.get("option_id", "")), None)
        if trade is None:
            return
        self.pending_trades.pop(trade["id"], None)
        self.open_trades.pop(trade["id"], None)

        amount = float(msg.get("amount", trade["amount"]) or trade["amount"])
        win_status = msg.get("win")
        win_amount = msg.get("win_amount")
        profit_amount = msg.get("profit_amount")

        result, profit = None, 0.0
        payout = win_amount if win_amount is not None else profit_amount
        if win_status == "win":
            result = "WIN"
        elif win_status in ("loose", "loss"):
            result = "LOSS"
        elif win_status in ("equal", "draw"):
            result = "DRAW"
        elif payout is not None:
            try:
                p = float(payout)
                result = "WIN" if p > amount else ("DRAW" if p == amount else "LOSS")
            except (TypeError, ValueError):
                return

        # Match the reference bot's win_amount/profit_amount handling: a
        # broker value larger than the stake is a total return, otherwise it
        # is already treated as the profit value.
        if result == "WIN":
            try:
                p = float(payout) if payout is not None else 0.0
            except (TypeError, ValueError):
                p = 0.0
            profit = p - amount if p > amount else p
        elif result == "LOSS":
            profit = -amount
        elif result == "DRAW":
            profit = 0.0

        trade.update({
            "status": "closed", "result": result or "UNKNOWN",
            "profit": round(profit, 2),
            "close_time": int(time.time()),
            "close_price": msg.get("close_quote") or trade.get("current_price"),
        })

        with self.lock:
            self.active_trades_count = max(0, self.active_trades_count - 1)
            if result == "WIN":
                self.wins += 1
            elif result == "LOSS":
                self.losses += 1
            elif result == "DRAW":
                self.draws += 1
            self.pnl += profit
            self.trade_history.append(trade)
            self.balance_amount += profit

        for m in self.markers:
            if m["id"] == trade["id"]:
                m["status"] = (result or "").lower()
                m["profit"] = trade["profit"]

        self.bus.publish("trade_close", trade)
        self.log(
            f"RESULT {result} {trade['direction'].upper()} "
            f"{trade['asset']} profit {trade['profit']:+.2f}",
            "success" if result == "WIN" else ("error" if result == "LOSS" else "warn"),
        )
        self.push_state()

    # ---------------- strategy ----------------
    def load_strategy(self, source_path: str | None = None,
                      label: str | None = None):
        runner = StrategyRunner(source_path=source_path or "")
        old_timeframes = set(self.required_timeframes)
        self.runner = runner
        self.strategy_label = label or "custom"
        self.required_timeframes = runner.required_timeframes()
        if self.chart_timeframe not in self.required_timeframes:
            self.chart_timeframe = self.required_timeframes[0]
        for timeframe in self.required_timeframes:
            self.candles.setdefault(timeframe, [])
        if self.is_connected:
            for timeframe in old_timeframes - set(self.required_timeframes):
                self.unsubscribe_candles(timeframe)
            for timeframe in self.required_timeframes:
                self.subscribe_candles(timeframe)
        self.log(
            f"Strategy loaded: {self.strategy_label} "
            f"(timeframes {self.required_timeframes})",
            "success",
        )
        self.push_state()
        return self.required_timeframes

    def set_auto(self, enabled: bool):
        if enabled and not self.runner:
            self.log("Load a strategy before enabling auto-trading.", "error")
            return False
        if enabled and not self.is_connected:
            self.log("Connect to IQ Option before enabling auto-trading.", "error")
            return False
        self.auto_trading = bool(enabled)
        self.log(f"Auto-trading {'ENABLED' if enabled else 'DISABLED'}",
                 "success" if enabled else "warn")
        self.push_state()
        return True

    def reset_stats(self):
        with self.lock:
            self.wins = self.losses = self.draws = 0
            self.pnl = 0.0
            self.trade_history.clear()
            self.markers.clear()
        self.push_state()
