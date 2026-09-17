"""
IQ Option live trading engine for the web dashboard.

This is a refactor of bot.py -- the WebSocket protocol, login flow,
candle subscription, order payload and result handling are byte-for-byte
the same as the working CLI bot. The only difference is that instead of
printing to a rich Console, every event is pushed onto an in-memory event
bus which the FastAPI layer streams to the browser over WebSocket.
"""
from __future__ import annotations

import json
import ssl
import time
import threading
import importlib
import importlib.util
import traceback
from collections import deque
from datetime import datetime, timezone

import requests
import websocket

LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
WS_URL = "wss://iqoption.com/echo/websocket"

# option_type_id used by binary-options.open-option
OPTION_TYPE_IDS = {
    "binary": 1,
    "turbo": 3,
}

ACCOUNT_TYPE_IDS = {
    "PRACTICE": 4,
    "REAL": 1,
}


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
    """Loads a python strategy module/source and feeds candles to it."""

    def __init__(self, module_name: str | None = None, source_path: str | None = None):
        self.name = module_name or (source_path or "unknown")
        if source_path:
            spec = importlib.util.spec_from_file_location(
                f"user_strategy_{int(time.time())}", source_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore
        else:
            module = importlib.import_module(f"strategies.{module_name}")
            module = importlib.reload(module)
        if not hasattr(module, "Strategy"):
            raise RuntimeError("Strategy file must define a class named `Strategy`")
        self.module = module
        self.strategy = module.Strategy()

    def required_timeframes(self) -> list[int]:
        s = self.strategy
        tfs = None
        if hasattr(s, "get_required_timeframes"):
            tfs = s.get_required_timeframes()
        elif hasattr(s, "required_timeframes"):
            tfs = s.required_timeframes
        out = set()
        for tf in tfs or [60]:
            try:
                tf = int(tf)
                if tf > 0:
                    out.add(tf)
            except (TypeError, ValueError):
                continue
        return sorted(out) or [60]

    def feed(self, timeframe: int, candle: dict):
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
                return self.strategy.get_status()
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
        self.account_type = "PRACTICE"
        self.trade_type = "turbo"          # turbo | binary | digital
        self.active_id = 1
        self.active_name = "EURUSD"
        self.amount = 1.0
        self.expiration = 60
        self.max_concurrent_trades = 1

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
        self._watchdog = None

        # ---- trading state --------------------------------------------
        self.auto_trading = False
        self.runner: StrategyRunner | None = None
        self.strategy_label = None
        self.required_timeframes = [60]
        self.chart_timeframe = 60
        self.candles: dict[int, list] = {60: []}
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
                "trade_type": self.trade_type,
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
                "email", "password", "account_type", "trade_type", "active_id",
                "active_name", "amount", "expiration", "max_concurrent_trades",
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
            kwargs={
                "sslopt": {"cert_reqs": ssl.CERT_NONE},
                "ping_interval": 30,
                "ping_timeout": 10,
            },
            daemon=True,
        ).start()
        if self._watchdog is None or not self._watchdog.is_alive():
            self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog.start()
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

    def _watchdog_loop(self):
        while not self._stop:
            time.sleep(5)
            if self._stop:
                break
            if not self.is_connected:
                self.log("Connection lost. Reconnecting in 15s...", "warn")
                time.sleep(15)
                if self._stop:
                    break
                if self.login():
                    self.ws = websocket.WebSocketApp(
                        WS_URL,
                        on_open=self.on_open,
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close,
                    )
                    threading.Thread(
                        target=self.ws.run_forever,
                        kwargs={
                            "sslopt": {"cert_reqs": ssl.CERT_NONE},
                            "ping_interval": 30,
                            "ping_timeout": 10,
                        },
                        daemon=True,
                    ).start()

    # ==================================================================
    # websocket callbacks
    # ==================================================================
    def on_open(self, ws):
        self.is_connected = True
        self.log("WebSocket connected", "success")

        self._send({"name": "ssid", "msg": self.ssid, "request_id": self._next_id()})
        time.sleep(1)
        self._send({
            "name": "sendMessage",
            "msg": {"name": "get-balances", "version": "1.0"},
            "request_id": self._next_id(),
        })
        self._send({
            "name": "sendMessage",
            "msg": {"name": "get-profile", "version": "1.0"},
            "request_id": self._next_id(),
        })
        time.sleep(0.5)
        self.subscribed.clear()
        for tf in set(self.required_timeframes) | {self.chart_timeframe}:
            self.subscribe_candles(tf)
        self.request_history(self.chart_timeframe, 200)
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

    def request_history(self, size: int, count: int = 200):
        self._send({
            "name": "sendMessage",
            "request_id": self._next_id(),
            "msg": {
                "name": "get-candles",
                "version": "2.0",
                "body": {
                    "active_id": self.active_id,
                    "size": int(size),
                    "to": int(time.time()),
                    "count": int(count),
                },
            },
        })

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
            for tf in set(self.required_timeframes) | {self.chart_timeframe}:
                self.subscribe_candles(tf)
            self.request_history(self.chart_timeframe, 200)
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
        if self.is_connected:
            self.subscribe_candles(size)
            self.request_history(size, 200)
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
            elif name == "profile":
                self._handle_profile(data)
            elif name == "candle-generated":
                self._handle_candle(data)
            elif name == "candles":
                self._handle_history(data)
            elif name in ("option", "option-open"):
                self._handle_open(data)
            elif name in ("option-closed", "portfolio.position-changed", "position-changed"):
                self._handle_close(data)
        except Exception:
            self.log(f"Handler error on '{name}': {traceback.format_exc(limit=2)}", "error")

    def _handle_profile(self, data):
        msg = data.get("msg") or {}
        if isinstance(msg, dict):
            self.profile = {
                "user_id": msg.get("user_id") or msg.get("id"),
                "name": (msg.get("first_name", "") + " " + msg.get("last_name", "")).strip()
                or msg.get("nickname"),
                "country": msg.get("country_id"),
            }
            self.push_state()

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
        low = c.get("low", c.get("min"))
        high = c.get("high", c.get("max"))
        o, cl = c.get("open"), c.get("close")
        ts = c.get("from") or c.get("timestamp") or c.get("at")
        if None in (low, high, o, cl, ts):
            return None
        if ts > 1e11:
            ts = ts / 1e9 if ts > 1e15 else ts / 1000.0
        return {
            "timestamp": int(ts), "from": int(ts),
            "open": float(o), "high": float(high),
            "low": float(low), "close": float(cl),
            "volume": c.get("volume", 0),
            "size": c.get("size"),
        }

    def _handle_history(self, data):
        msg = data.get("msg") or {}
        candles = msg.get("candles") or msg.get("data") or []
        size = self.chart_timeframe
        out = []
        for c in candles:
            n = self._norm(c)
            if n:
                n["size"] = size
                out.append(n)
        out.sort(key=lambda x: x["timestamp"])
        if out:
            self.candles[size] = out[-500:]
            self.bus.publish("candles_snapshot", {
                "timeframe": size,
                "active_name": self.active_name,
                "candles": self.candles[size],
                "markers": self.markers[-100:],
            })
            self.log(f"Loaded {len(out)} historical {size}s candles")

    def _handle_candle(self, data):
        raw = data.get("msg") or {}
        size = raw.get("size")
        try:
            size = int(size)
        except (TypeError, ValueError):
            return
        candle = self._norm(raw)
        if candle is None:
            return
        candle["size"] = size

        store = self.candles.setdefault(size, [])
        if store and store[-1]["timestamp"] == candle["timestamp"]:
            store[-1] = candle
            new_candle = False
        else:
            store.append(candle)
            new_candle = True
            if len(store) > 500:
                del store[0:len(store) - 500]

        if size == self.chart_timeframe:
            self.bus.publish("candle", {"timeframe": size, "candle": candle})
            self._check_open_trades(candle["close"])

        if size not in self.required_timeframes or not self.runner:
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
        elif new_candle:
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

        amount = float(amount or self.amount)
        expiration = int(expiration or self.expiration)

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

        if self.trade_type == "digital":
            payload = self._digital_payload(direction, amount, expiration, req_id)
        else:
            payload = {
                "name": "sendMessage",
                "request_id": req_id,
                "msg": {
                    "name": "binary-options.open-option",
                    "version": "2.0",
                    "body": {
                        "user_balance_id": self.balance_id,
                        "active_id": self.active_id,
                        "option_type_id": OPTION_TYPE_IDS.get(self.trade_type, 3),
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
            "trade_type": self.trade_type,
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
            f"on {self.active_name} ({self.trade_type}) [{source}]",
            "trade",
        )
        self.push_state()
        return True

    def _digital_payload(self, direction, amount, expiration, req_id):
        exp_dt = datetime.now(timezone.utc)
        minutes = max(1, expiration // 60)
        exp_ts = int(time.time()) + minutes * 60
        exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        instrument = (
            f"do{self.active_id}A"
            f"{exp_dt.strftime('%Y%m%d%H%M')}"
            f"{'C' if direction == 'call' else 'P'}SPT"
        )
        return {
            "name": "sendMessage",
            "request_id": req_id,
            "msg": {
                "name": "digital-options.place-digital-option",
                "version": "2.0",
                "body": {
                    "user_balance_id": self.balance_id,
                    "instrument_id": instrument,
                    "amount": str(amount),
                    "asset_id": self.active_id,
                    "instrument_index": 0,
                },
            },
        }

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
        if win_status == "win":
            result = "WIN"
        elif win_status in ("loose", "loss"):
            result = "LOSS"
        elif win_status in ("equal", "draw"):
            result = "DRAW"

        payout = win_amount if win_amount is not None else profit_amount
        if payout is not None:
            try:
                p = float(payout)
                profit = p - amount if result != "LOSS" else -amount
                if result is None:
                    result = "WIN" if p > amount else ("DRAW" if p == amount else "LOSS")
            except Exception:
                pass
        if result == "LOSS":
            profit = -amount
        elif result == "DRAW":
            profit = 0.0
        elif result == "WIN" and profit <= 0:
            profit = amount * 0.8

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
    def load_strategy(self, module_name: str | None = None, source_path: str | None = None,
                      label: str | None = None):
        runner = StrategyRunner(module_name=module_name, source_path=source_path)
        self.runner = runner
        self.strategy_label = label or module_name or "custom"
        self.required_timeframes = runner.required_timeframes()
        for tf in self.required_timeframes:
            self.candles.setdefault(tf, [])
        if self.is_connected:
            for tf in self.required_timeframes:
                self.subscribe_candles(tf)
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
