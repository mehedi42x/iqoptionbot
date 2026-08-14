"""
core.py - Central Engine and Orchestrator
"""

import importlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.auth import IQOptionAuth
from api.binary import BinaryAPI
from api.bliz import BlizAPI
from api.digital import DigitalAPI
from api.Marginal import MarginalAPI

logger = logging.getLogger("IQ_BOT.Core")


class TradingEngine:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.running = False
        self._stop_requested = threading.Event()

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.case_dir = os.path.join(self.base_dir, "case")
        os.makedirs(self.case_dir, exist_ok=True)
        self.trades_file = os.path.join(self.case_dir, "trades.json")
        self.state_file = os.path.join(self.case_dir, "state.json")
        self.summary_file = os.path.join(self.case_dir, "summary.json")

        self.starting_balance: float = 0.0
        self.current_balance: float = 0.0
        self.active_trades: List[Dict[str, Any]] = []
        self.last_candle_timestamp: Optional[int] = None
        self._trade_lock = threading.Lock()

        self.strategy_module = importlib.import_module(f"Strategies.{config.get('STRATEGY')}")
        self.auth = IQOptionAuth(
            email=config.get("IQ_EMAIL", ""),
            password=config.get("IQ_PASSWORD", ""),
            account_type=config.get("ACCOUNT", "PRACTICE"),
        )
        self.api = self._initialize_trade_api()

    def _initialize_trade_api(self):
        t_type = self.config.get("TRADE_TYPE", "FOREX").upper()
        if t_type == "BINARY":
            return BinaryAPI(self.auth)
        elif t_type == "DIGITAL":
            return DigitalAPI(self.auth)
        elif t_type in ["FOREX", "MARGINAL"]:
            return MarginalAPI(self.auth)
        elif t_type == "BLIZ":
            return BlizAPI(self.auth)
        raise ValueError(f"Unknown TRADE_TYPE: {t_type}")

    def initialize(self) -> bool:
        if not self.auth.connect_ws():
            return False
        self.starting_balance = self.auth.get_balance()
        self.current_balance = self.starting_balance
        self._update_state(connection_state="INITIALIZED")
        self._update_summary()
        return True

    def start(self):
        self.running = True
        timeframe_sec = int(self.config.get("TIMEFRAME", 1)) * 60
        symbol = self.config.get("SYMBOL", "XAUUSD")

        while not self._stop_requested.is_set():
            try:
                if not self.auth.is_connected:
                    self.auth.connect_ws()

                self.current_balance = self.auth.get_balance()
                self._monitor_active_trades()

                max_open = int(self.config.get("MAX_OPEN_TRADES", 1))
                with self._trade_lock:
                    if len(self.active_trades) >= max_open:
                        time.sleep(2)
                        continue

                candles = self.api.get_candles(symbol, timeframe_seconds=timeframe_sec, count=120)
                if not candles or len(candles) < 30:
                    time.sleep(2)
                    continue

                latest_time = candles[-1].get("from", 0)
                if self.last_candle_timestamp == latest_time:
                    time.sleep(1)
                    continue

                signal = self.strategy_module.analyze({
                    "candles": candles,
                    "current_price": candles[-1]["close"],
                    "symbol": symbol,
                })
                self.last_candle_timestamp = latest_time
                self._update_state(last_signal=signal)

                if signal in ["BUY", "SELL"]:
                    logger.info(f"Signal: [{signal}] on {symbol} @ {candles[-1]['close']}")
                    self._execute_signal(signal, candles[-1]["close"])

            except Exception as e:
                logger.error(f"Engine Loop Exception: {e}")
            time.sleep(1)

    def _execute_signal(self, signal: str, current_price: float):
        symbol = self.config.get("SYMBOL", "XAUUSD")
        amount = float(self.config.get("AMOUNT", 10.0))
        trade_type = self.config.get("TRADE_TYPE", "FOREX").upper()

        if trade_type in ["FOREX", "MARGINAL"]:
            lev = int(self.config.get("LEVERAGE", 10))
            sl_dist = float(self.config.get("STOP_LOSS", 2.0))
            tp_dist = float(self.config.get("TAKE_PROFIT", 4.0))

            sl_price = round(current_price - sl_dist, 4) if signal == "BUY" else round(current_price + sl_dist, 4)
            tp_price = round(current_price + tp_dist, 4) if signal == "BUY" else round(current_price - tp_dist, 4)

            res = self.api.place_order(symbol, signal, amount, lev, sl_price, tp_price)
            if res.get("success"):
                trade_record = {
                    "trade_id": str(res.get("position_id")),
                    "symbol": symbol,
                    "trade_type": trade_type,
                    "strategy": self.config.get("STRATEGY"),
                    "direction": signal,
                    "amount": amount,
                    "leverage": lev,
                    "entry_price": res.get("entry_price", current_price),
                    "exit_price": None,
                    "stop_loss": sl_price,
                    "take_profit": tp_price,
                    "open_time": datetime.now(timezone.utc).isoformat(),
                    "close_time": None,
                    "execution_time": None,
                    "result": "PENDING",
                    "pnl": 0.0,
                    "status": "OPEN",
                }
                with self._trade_lock:
                    self.active_trades.append(trade_record)
                self._update_state()

        else:
            exec_time = int(self.config.get("EXECUTION_TIME", 1) or 1)
            res = self.api.place_order(symbol, signal, amount, exec_time)
            if res.get("success"):
                trade_record = {
                    "trade_id": str(res.get("order_id")),
                    "symbol": symbol,
                    "trade_type": trade_type,
                    "strategy": self.config.get("STRATEGY"),
                    "direction": signal,
                    "amount": amount,
                    "entry_price": res.get("entry_price", current_price),
                    "exit_price": None,
                    "stop_loss": None,
                    "take_profit": None,
                    "open_time": datetime.now(timezone.utc).isoformat(),
                    "close_time": None,
                    "execution_time": exec_time,
                    "result": "PENDING",
                    "pnl": 0.0,
                    "status": "OPEN",
                }
                with self._trade_lock:
                    self.active_trades.append(trade_record)
                self._update_state()
                threading.Thread(target=self._wait_and_settle_option, args=(trade_record,), daemon=True).start()

    def _wait_and_settle_option(self, trade_record: Dict[str, Any]):
        trade_id = int(trade_record["trade_id"])
        result = self.api.wait_for_result(trade_id)
        trade_record["status"] = "CLOSED"
        trade_record["result"] = result.get("result", "UNKNOWN")
        trade_record["pnl"] = result.get("pnl", 0.0)
        trade_record["exit_price"] = result.get("exit_price")
        trade_record["close_time"] = datetime.now(timezone.utc).isoformat()

        with self._trade_lock:
            self.active_trades = [t for t in self.active_trades if t["trade_id"] != str(trade_id)]
        self._record_closed_trade(trade_record)
        self._update_state()
        self._update_summary()

    def _monitor_active_trades(self):
        if self.config.get("TRADE_TYPE", "FOREX").upper() not in ["FOREX", "MARGINAL"]:
            return
        with self._trade_lock:
            active_copy = list(self.active_trades)

        for trade in active_copy:
            pos_id = int(trade["trade_id"])
            pos_info = self.api.get_position_status(pos_id)
            if pos_info and pos_info.get("status") == "CLOSED":
                trade["status"] = "CLOSED"
                trade["result"] = pos_info.get("result", "UNKNOWN")
                trade["pnl"] = pos_info.get("pnl", 0.0)
                trade["exit_price"] = pos_info.get("exit_price")
                trade["close_time"] = datetime.now(timezone.utc).isoformat()

                with self._trade_lock:
                    self.active_trades = [t for t in self.active_trades if t["trade_id"] != str(pos_id)]
                self._record_closed_trade(trade)
                self._update_state()
                self._update_summary()

    def _record_closed_trade(self, trade_record: Dict[str, Any]):
        try:
            trades = []
            if os.path.exists(self.trades_file):
                with open(self.trades_file, "r") as f:
                    trades = json.load(f)
            trades.append(trade_record)
            with open(self.trades_file, "w") as f:
                json.dump(trades, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving trade record: {e}")

    def _update_state(self, connection_state: Optional[str] = None, last_signal: Optional[str] = None):
        try:
            state = {
                "active_trades": self.active_trades,
                "open_position_ids": [t["trade_id"] for t in self.active_trades],
                "last_processed_signal": last_signal,
                "last_known_balance": self.current_balance,
                "connection_state": connection_state or ("CONNECTED" if self.auth.is_connected else "DISCONNECTED"),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def _update_summary(self):
        try:
            trades = []
            if os.path.exists(self.trades_file):
                with open(self.trades_file, "r") as f:
                    trades = json.load(f)
            total = len(trades)
            wins = sum(1 for t in trades if t.get("result") == "WIN")
            losses = sum(1 for t in trades if t.get("result") == "LOSS")
            ties = sum(1 for t in trades if t.get("result") == "TIE")
            win_rate = (wins / total * 100) if total > 0 else 0.0
            total_pnl = sum(t.get("pnl", 0.0) for t in trades)

            summary = {
                "total_trades": total,
                "winning_trades": wins,
                "losing_trades": losses,
                "tie_trades": ties,
                "win_rate": round(win_rate, 2),
                "starting_balance": round(self.starting_balance, 2),
                "ending_balance": round(self.current_balance, 2),
                "total_pnl": round(total_pnl, 2),
            }
            with open(self.summary_file, "w") as f:
                json.dump(summary, f, indent=2)
        except Exception:
            pass

    def get_summary(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.summary_file):
                with open(self.summary_file, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def stop(self):
        self.running = False
        self._stop_requested.set()
        self._update_state(connection_state="STOPPED")
        self._update_summary()
        self.auth.close()
