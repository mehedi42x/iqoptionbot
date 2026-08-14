"""
api/Marginal.py
Forex / Marginal / CFD API and WebSocket Trading Layer for IQ Option.
"""

import logging
import threading
from typing import Any, Dict, List, Optional
from api.auth import IQOptionAuth

logger = logging.getLogger("IQ_BOT.Marginal")

MARGINAL_ACTIVE_IDS = {
    "XAUUSD": 108, "GOLD": 108, "EURUSD": 1, "GBPUSD": 5, "USDJPY": 6,
    "AUDUSD": 99, "USDCAD": 100, "USDCHF": 72, "EURJPY": 4,
}

class MarginalAPI:
    def __init__(self, auth: IQOptionAuth):
        self.auth = auth
        self.actives_map = MARGINAL_ACTIVE_IDS.copy()
        self.open_positions: Dict[int, Dict[str, Any]] = {}
        self.closed_positions: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.auth.subscribe("position-changed", self._on_position_changed)

    def get_active_id(self, symbol: str) -> int:
        return self.actives_map.get(symbol.replace("/", "").upper(), 108)

    def get_instrument_id(self, symbol: str) -> str:
        return f"forex_{symbol.replace('/', '').upper()}"

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
            raw = res["msg"].get("candles", res["msg"]) if isinstance(res["msg"], dict) else res["msg"]
            if isinstance(raw, list):
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
                    for c in raw
                ]
                parsed.sort(key=lambda x: x["from"])
                return parsed
        return []

    def place_order(
        self,
        symbol: str,
        direction: str,
        amount: float,
        leverage: int = 10,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        side = "buy" if direction.lower() in ["buy", "call", "long"] else "sell"
        active_id = self.get_active_id(symbol)
        instrument_id = self.get_instrument_id(symbol)

        msg = {
            "user_balance_id": self.auth.active_balance_id,
            "instrument_id": instrument_id,
            "instrument_active_id": active_id,
            "side": side,
            "amount": float(amount),
            "leverage": int(leverage),
            "type": "market",
        }
        if stop_loss_price:
            msg["stop_loss"] = {"type": "price", "value": round(float(stop_loss_price), 4)}
        if take_profit_price:
            msg["take_profit"] = {"type": "price", "value": round(float(take_profit_price), 4)}

        res = self.auth.send_request("marginal-forex.place-order", msg, timeout=12.0)
        if res and res.get("msg"):
            msg_body = res.get("msg", {})
            pos_id = msg_body.get("id") or msg_body.get("position_id")
            if pos_id:
                info = {
                    "position_id": pos_id,
                    "symbol": symbol,
                    "direction": side.upper(),
                    "amount": amount,
                    "leverage": leverage,
                    "entry_price": float(msg_body.get("open_price", 0.0)),
                    "stop_loss": stop_loss_price,
                    "take_profit": take_profit_price,
                    "status": "OPEN",
                    "pnl": 0.0,
                }
                with self._lock:
                    self.open_positions[pos_id] = info
                return {"success": True, **info}

        return {"success": False, "error": "Marginal order execution failed"}

    def get_position_status(self, position_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.open_positions.get(position_id) or self.closed_positions.get(position_id)

    def _on_position_changed(self, msg_data: Dict[str, Any]):
        msg = msg_data.get("msg", {})
        pos_id = msg.get("id") or msg.get("position_id")
        if not pos_id:
            return
        status = msg.get("status")
        current_pnl = float(msg.get("pnl", msg.get("profit", 0.0)))
        with self._lock:
            if status == "closed":
                res = "WIN" if current_pnl > 0 else ("TIE" if current_pnl == 0 else "LOSS")
                info = {
                    "position_id": pos_id,
                    "status": "CLOSED",
                    "result": res,
                    "pnl": current_pnl,
                    "exit_price": float(msg.get("close_price", 0.0)),
                    "close_time": msg.get("close_time", self.auth.get_server_time()),
                }
                if pos_id in self.open_positions:
                    info = {**self.open_positions.pop(pos_id), **info}
                self.closed_positions[pos_id] = info
            elif pos_id in self.open_positions:
                self.open_positions[pos_id]["pnl"] = current_pnl
