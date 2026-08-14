"""
api/auth.py
Direct IQ Option Authentication, Session Management, and WebSocket Engine.
"""

import json
import logging
import random
import string
import threading
import time
from typing import Any, Callable, Dict, List, Optional
import requests
import websocket

logger = logging.getLogger("IQ_BOT.Auth")


class IQOptionAuth:
    HTTP_LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
    WS_URL = "wss://ws.iqoption.com/echo/websocket"

    def __init__(self, email: str, password: str, account_type: str = "PRACTICE"):
        self.email = email
        self.password = password
        self.target_account_type = account_type.upper()

        self.session = requests.Session()
        self.ssid: Optional[str] = None
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None

        self.is_connected = False
        self.is_authenticated = False
        self._stop_event = threading.Event()

        self.profile: Dict[str, Any] = {}
        self.balances: List[Dict[str, Any]] = []
        self.active_balance_id: Optional[int] = None
        self.current_balance: float = 0.0
        self.currency: str = "USD"
        self.user_id: Optional[int] = None
        self.server_time: int = int(time.time())

        self._pending_requests: Dict[str, Dict[str, Any]] = {}
        self._request_lock = threading.Lock()
        self._subscriptions: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self._sub_lock = threading.Lock()

    def generate_request_id(self) -> str:
        chars = string.ascii_letters + string.digits
        return "".join(random.choice(chars) for _ in range(16))

    def login(self) -> bool:
        logger.info(f"Logging in with account: {self.email}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {"identifier": self.email, "password": self.password}
        try:
            response = self.session.post(self.HTTP_LOGIN_URL, json=payload, headers=headers, timeout=15)
            data = response.json()
            if response.status_code == 200 and data.get("code") == "success":
                ssid = self.session.cookies.get("ssid") or data.get("ssid") or data.get("data", {}).get("ssid")
                if not ssid:
                    ssid = self.session.cookies.get_dict().get("ssid")
                if ssid:
                    self.ssid = ssid
                    logger.info("HTTP Login successful. Session SSID retrieved.")
                    return True
            logger.error(f"Login failed: {data.get('message', 'Auth error')}")
            return False
        except Exception as e:
            logger.error(f"Exception during HTTP login: {e}")
            return False

    def connect_ws(self) -> bool:
        if not self.ssid and not self.login():
            return False

        logger.info("Opening WebSocket connection...")
        self._stop_event.clear()
        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_open=self._on_ws_open,
            on_message=self._on_ws_message,
            on_error=self._on_ws_error,
            on_close=self._on_ws_close,
        )
        self.ws_thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"ping_interval": 20, "ping_timeout": 10},
            daemon=True,
        )
        self.ws_thread.start()

        timeout = 25
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_authenticated and self.active_balance_id is not None:
                self.set_account_type(self.target_account_type)
                logger.info(
                    f"WebSocket Connected & Authenticated. Selected Account: {self.target_account_type} | Balance: {self.current_balance:.2f} {self.currency}"
                )
                self._start_heartbeat()
                return True
            time.sleep(0.3)

        logger.error("WebSocket connection timed out waiting for authentication.")
        return False

    def _on_ws_open(self, ws):
        logger.info("WebSocket connected. Authenticating SSID...")
        self.is_connected = True
        auth_msg = {"name": "ssid", "msg": self.ssid, "request_id": "auth_" + self.generate_request_id()}
        self.send_raw(auth_msg)

    def _on_ws_message(self, ws, message):
        try:
            data = json.loads(message)
            name = data.get("name")
            req_id = data.get("request_id")
            msg = data.get("msg")

            if "server_time" in data:
                self.server_time = data["server_time"]

            if name == "profile":
                self.profile = msg if isinstance(msg, dict) else {}
                self.user_id = self.profile.get("user_id") or self.profile.get("id")
                self.balances = self.profile.get("balances", [])
                self.currency = self.profile.get("currency", "USD")
                self.is_authenticated = True
                self._update_balance_info()

            elif name == "balances" and isinstance(msg, list):
                self.balances = msg
                self._update_balance_info()

            elif name == "balance-changed" and isinstance(msg, dict):
                b_id = msg.get("id")
                new_val = msg.get("amount") or msg.get("current_balance")
                if b_id == self.active_balance_id and new_val is not None:
                    self.current_balance = float(new_val)

            elif name == "heartbeat" and isinstance(msg, int):
                self.server_time = int(msg / 1000)

            if req_id:
                with self._request_lock:
                    if req_id in self._pending_requests:
                        self._pending_requests[req_id]["response"] = data
                        self._pending_requests[req_id]["event"].set()

            if name:
                with self._sub_lock:
                    for cb in self._subscriptions.get(name, []):
                        try:
                            cb(data)
                        except Exception as cb_err:
                            logger.error(f"Subscription callback error on '{name}': {cb_err}")
        except Exception as e:
            logger.error(f"Error parsing WS message: {e}")

    def _on_ws_error(self, ws, error):
        logger.error(f"WebSocket Error: {error}")

    def _on_ws_close(self, ws, close_status_code, close_msg):
        logger.warning(f"WebSocket Connection closed: {close_status_code} - {close_msg}")
        self.is_connected = False
        self.is_authenticated = False

    def _start_heartbeat(self):
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return

        def heartbeat_loop():
            while not self._stop_event.is_set() and self.is_connected:
                try:
                    self.send_raw({"name": "heartbeat", "msg": int(time.time() * 1000)})
                except Exception:
                    pass
                time.sleep(15)

        self.heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

    def _update_balance_info(self):
        for b in self.balances:
            b_type = b.get("type")
            if self.target_account_type == "PRACTICE" and b_type == 4:
                self.active_balance_id = b.get("id")
                self.current_balance = float(b.get("amount", 0.0))
                break
            elif self.target_account_type == "REAL" and b_type == 1:
                self.active_balance_id = b.get("id")
                self.current_balance = float(b.get("amount", 0.0))
                break

    def set_account_type(self, account_type: str) -> bool:
        self.target_account_type = account_type.upper()
        target_type_id = 4 if self.target_account_type == "PRACTICE" else 1

        target_balance = next((b for b in self.balances if b.get("type") == target_type_id), None)
        if not target_balance:
            return False

        b_id = target_balance.get("id")
        self.active_balance_id = b_id
        self.current_balance = float(target_balance.get("amount", 0.0))
        self.send_raw({"name": "change-balance", "msg": {"balance_id": b_id}})
        return True

    def send_raw(self, payload: Dict[str, Any]) -> bool:
        if not self.ws or not self.is_connected:
            return False
        try:
            self.ws.send(json.dumps(payload))
            return True
        except Exception as e:
            logger.error(f"Failed to send raw WS message: {e}")
            return False

    def send_request(self, name: str, msg: Any, timeout: float = 10.0, req_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not req_id:
            req_id = self.generate_request_id()

        event = threading.Event()
        with self._request_lock:
            self._pending_requests[req_id] = {"event": event, "response": None}

        if not self.send_raw({"name": name, "msg": msg, "request_id": req_id}):
            with self._request_lock:
                self._pending_requests.pop(req_id, None)
            return None

        responded = event.wait(timeout=timeout)
        with self._request_lock:
            res_entry = self._pending_requests.pop(req_id, None)

        return res_entry["response"] if responded and res_entry else None

    def subscribe(self, name: str, callback: Callable[[Dict[str, Any]], None]):
        with self._sub_lock:
            self._subscriptions.setdefault(name, []).append(callback)

    def get_balance(self) -> float:
        return self.current_balance

    def get_server_time(self) -> int:
        return self.server_time or int(time.time())

    def close(self):
        self._stop_event.set()
        self.is_connected = False
        self.is_authenticated = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.session.close()
