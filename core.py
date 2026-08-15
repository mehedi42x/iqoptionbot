"""
core.py - Central Engine and Orchestrator
- Uses MODE from .env to select the trading API (bliz / binary / digital / marginal)
- Handles Stop Loss and Take Profit by tracking the market price directly
  (broker does NOT auto-close — the bot closes the trade when SL or TP is hit)
- Auto-discovers strategies via import
"""

import importlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from console import console
from api.auth import IQOptionAuth
from api.binary import BinaryAPI
from api.bliz import BlizAPI
from api.digital import DigitalAPI
from api.Marginal import MarginalAPI

logger = logging.getLogger("IQ_BOT.Core")

# Which modes are "continuous" (forex/marginal) vs "fixed-expiry" (binary/digital/bliz)
CONTINUOUS_MODES = {"FOREX", "MARGINAL"}
FIXED_EXPIRY_MODES = {"BINARY", "DIGITAL", "BLIZ"}

# Modes that use marginal (position-based) API
MARGINAL_MODES = {"FOREX", "MARGINAL"}


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
        self._mode = self.config.get("MODE", "FOREX").upper()

    def _initialize_trade_api(self):
        """Selects the trading API based on MODE from .env."""
        mode = self.config.get("MODE", "FOREX").upper()
        logger.debug(f"Initializing trading API for MODE={mode}")

        if mode == "BINARY":
            return BinaryAPI(self.auth)
        elif mode == "DIGITAL":
            return DigitalAPI(self.auth)
        elif mode in ["FOREX", "MARGINAL"]:
            return MarginalAPI(self.auth)
        elif mode == "BLIZ":
            return BlizAPI(self.auth)
        raise ValueError(f"Unknown MODE: {mode}")

    def initialize(self) -> bool:
        if not self.auth.connect_ws():
            console.error("Could not connect to IQ Option. Exiting.")
            return False
        self.starting_balance = self.auth.get_balance()
        self.current_balance = self.starting_balance
        self._update_state(connection_state="INITIALIZED")
        self._update_summary()
        return True

    def _waiting_status(self, symbol: str, timeframe_min: int) -> str:
        with self._trade_lock:
            open_count = len(self.active_trades)
        return (
            f"Waiting for next candle · {symbol} · {timeframe_min}m · "
            f"Balance ${self.current_balance:.2f} · Open trades {open_count}"
        )

    def start(self):
        self.running = True
        timeframe_sec = int(self.config.get("TIMEFRAME", 1)) * 60
        timeframe_min = int(self.config.get("TIMEFRAME", 1))
        symbol = self.config.get("SYMBOL", "XAUUSD")

        console.success(f"Engine started · {self._mode} · {symbol}")
        console.status(self._waiting_status(symbol, timeframe_min))

        while not self._stop_requested.is_set():
            try:
                if not self.auth.is_connected:
                    console.status("Reconnecting to IQ Option...")
                    if not self.auth.connect_ws():
                        console.error("Reconnection failed. Will retry shortly.")
                        time.sleep(3)
                        continue

                self.current_balance = self.auth.get_balance()

                # --- SL/TP monitoring: check every cycle for continuous modes ---
                if self._mode in MARGINAL_MODES:
                    console.status("Monitoring open trades (SL/TP)...")
                    self._monitor_active_trades_market_price()
                    self._monitor_active_trades()  # fallback: pick up broker-closed positions

                # --- Check max open trades ---
                max_open = int(self.config.get("MAX_OPEN_TRADES", 1))
                with self._trade_lock:
                    if len(self.active_trades) >= max_open:
                        console.status(
                            f"Max open trades reached ({len(self.active_trades)}/{max_open}) — waiting..."
                        )
                        time.sleep(2)
                        continue

                # --- Fetch candles & generate signal ---
                console.status("Fetching candles...")
                candles = self.api.get_candles(symbol, timeframe_seconds=timeframe_sec, count=120)
                if not candles or len(candles) < 30:
                    console.status("Loading candle history...")
                    time.sleep(2)
                    continue

                # Optional secondary (signal) timeframe for multi-timeframe
                # strategies such as the Bliz EMA crossover scalper.
                signal_timeframe = getattr(self.strategy_module, "SIGNAL_TIMEFRAME", None)
                signal_candles = None
                if signal_timeframe:
                    signal_candles = self.api.get_candles(
                        symbol, timeframe_seconds=int(signal_timeframe), count=120
                    )
                    if not signal_candles or len(signal_candles) < 5:
                        console.status(f"Loading {int(signal_timeframe)}s candle history...")
                        time.sleep(1)
                        continue
                    latest_time = signal_candles[-1].get("from", 0)
                else:
                    latest_time = candles[-1].get("from", 0)

                if self.last_candle_timestamp == latest_time:
                    console.status(self._waiting_status(symbol, timeframe_min))
                    time.sleep(1)
                    continue

                console.status("Analyzing signal...")
                signal = self.strategy_module.analyze({
                    "candles": candles,
                    "signal_candles": signal_candles,
                    "current_price": (
                        signal_candles[-1]["close"] if signal_candles else candles[-1]["close"]
                    ),
                    "symbol": symbol,
                })
                self.last_candle_timestamp = latest_time
                self._update_state(last_signal=signal)

                if signal in ["BUY", "SELL"]:
                    console.event(f"Signal {signal} · {symbol} @ {candles[-1]['close']}")
                    console.status("Placing order...")
                    self._execute_signal(signal, candles[-1]["close"])

                console.status(self._waiting_status(symbol, timeframe_min))

            except Exception as e:
                console.error(f"Engine loop error: {e}")
                logger.debug("Engine loop traceback:", exc_info=True)
            time.sleep(1)

    # ------------------------------------------------------------------ #
    #  SIGNAL EXECUTION
    # ------------------------------------------------------------------ #

    def _execute_signal(self, signal: str, current_price: float):
        """
        Executes a trading signal.
        For marginal/forex modes, SL/TP are stored locally (NOT sent to broker).
        """
        symbol = self.config.get("SYMBOL", "XAUUSD")
        amount = float(self.config.get("AMOUNT", 10.0))

        if self._mode in MARGINAL_MODES:
            lev = int(self.config.get("LEVERAGE", 10))
            sl_dist = float(self.config.get("STOP_LOSS", 2.0))
            tp_dist = float(self.config.get("TAKE_PROFIT", 4.0))

            # Calculate SL/TP prices (stored locally, NOT sent to broker)
            sl_price = round(current_price - sl_dist, 4) if signal == "BUY" else round(current_price + sl_dist, 4)
            tp_price = round(current_price + tp_dist, 4) if signal == "BUY" else round(current_price - tp_dist, 4)

            logger.debug(
                f"Executing {signal} — Entry: {current_price}, "
                f"SL: {sl_price}, TP: {tp_price} (bot-managed)"
            )

            # place_order no longer sends SL/TP to the broker
            res = self.api.place_order(
                symbol, signal, amount, lev,
                stop_loss_price=sl_price,   # for local record only
                take_profit_price=tp_price,  # for local record only
            )
            if res.get("success"):
                trade_record = {
                    "trade_id": str(res.get("position_id")),
                    "symbol": symbol,
                    "trade_type": self._mode,
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
                console.success(
                    f"Trade #{trade_record['trade_id']} opened · {signal} {symbol} "
                    f"@ {current_price} · SL {sl_price} · TP {tp_price}"
                )
            else:
                console.error(f"Order rejected: {res.get('error', 'unknown error')}")

        else:
            # Fixed-expiry modes (binary, digital, bliz) — no SL/TP
            # EXECUTION_TIME is in SECONDS (e.g. 60 = 1 minute)
            exec_time = int(self.config.get("EXECUTION_TIME", 60) or 60)
            res = self.api.place_order(symbol, signal, amount, exec_time)
            if res.get("success"):
                trade_record = {
                    "trade_id": str(res.get("order_id")),
                    "symbol": symbol,
                    "trade_type": self._mode,
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
                console.success(
                    f"Option #{trade_record['trade_id']} opened · {signal} {symbol} "
                    f"@ {trade_record['entry_price']} · {exec_time}s expiry"
                )
                threading.Thread(
                    target=self._wait_and_settle_option,
                    args=(trade_record,),
                    daemon=True,
                ).start()
            else:
                console.error(f"Order rejected: {res.get('error', 'unknown error')}")

    # ------------------------------------------------------------------ #
    #  SL/TP MARKET-PRICE TRACKING  (the core of the change)
    # ------------------------------------------------------------------ #

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Fetches the latest market price for the given symbol.
        Uses the current candle close as the real-time price estimate.
        """
        try:
            tf = int(self.config.get("TIMEFRAME", 1)) * 60
            candles = self.api.get_candles(symbol, timeframe_seconds=tf, count=5)
            if candles and len(candles) > 0:
                return float(candles[-1]["close"])
        except Exception as e:
            logger.debug(f"Failed to fetch current price for {symbol}: {e}")
        return None

    def _monitor_active_trades_market_price(self):
        """
        Monitors all active marginal/forex trades and closes them when
        Stop Loss or Take Profit is hit.  The broker does NOT auto-close —
        the bot does it itself by tracking the market price.
        """
        with self._trade_lock:
            active_copy = list(self.active_trades)

        for trade in active_copy:
            symbol = trade["symbol"]
            direction = trade["direction"]
            sl = trade.get("stop_loss")
            tp = trade.get("take_profit")
            trade_id = trade.get("trade_id")

            if sl is None and tp is None:
                continue  # no SL/TP set for this trade

            current_price = self._get_current_price(symbol)
            if current_price is None:
                continue

            hit_reason = None

            if direction == "BUY":
                # Long position: SL is below entry, TP is above entry
                if sl is not None and current_price <= sl:
                    hit_reason = "STOP_LOSS"
                elif tp is not None and current_price >= tp:
                    hit_reason = "TAKE_PROFIT"

            elif direction == "SELL":
                # Short position: SL is above entry, TP is below entry
                if sl is not None and current_price >= sl:
                    hit_reason = "STOP_LOSS"
                elif tp is not None and current_price <= tp:
                    hit_reason = "TAKE_PROFIT"

            if hit_reason:
                self._close_trade_by_core(trade, hit_reason, current_price)

    def _close_trade_by_core(self, trade: Dict[str, Any], reason: str, exit_price: float):
        """
        Closes a trade because SL or TP was hit.
        The bot calls the API to close the position (broker does NOT auto-close).
        """
        pos_id = int(trade["trade_id"])
        logger.debug(f"Closing trade #{pos_id} — Reason: {reason} @ {exit_price}")

        # Call the API to close the position
        result = self.api.close_position(pos_id)

        if result.get("success"):
            # Calculate PnL (rough estimate based on entry/exit)
            entry = trade["entry_price"]
            direction = trade["direction"]
            amount = trade["amount"]
            leverage = trade.get("leverage", 1)

            if direction == "BUY":
                pnl_pct = (exit_price - entry) / entry
            else:
                pnl_pct = (entry - exit_price) / entry

            pnl = round(pnl_pct * amount * leverage, 2)
            res_str = "WIN" if pnl > 0 else ("TIE" if pnl == 0 else "LOSS")

            # Update trade record
            trade["status"] = "CLOSED"
            trade["result"] = res_str
            trade["pnl"] = pnl
            trade["exit_price"] = exit_price
            trade["close_time"] = datetime.now(timezone.utc).isoformat()
            trade["close_reason"] = reason

            with self._trade_lock:
                self.active_trades = [t for t in self.active_trades if t["trade_id"] != str(pos_id)]

            self._record_closed_trade(trade)
            self._update_state()
            self._update_summary()

            msg = (
                f"{reason.replace('_', ' ').title()} hit → Trade #{pos_id} closed · "
                f"Entry {entry} · Exit {exit_price} · PnL ${pnl:+.2f} ({res_str})"
            )
            if reason == "TAKE_PROFIT" or pnl > 0:
                console.success(msg)
            elif reason == "STOP_LOSS":
                console.warning(msg)
            else:
                console.info(msg)
        else:
            console.error(
                f"Failed to close trade #{pos_id} via API. "
                "The position may already be closed by the broker — will re-check."
            )
            # Fall through: the position-changed subscription will pick it up eventually

    # ------------------------------------------------------------------ #
    #  OPTION SETTLEMENT  (for fixed-expiry modes: binary, digital, bliz)
    # ------------------------------------------------------------------ #

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

        res = trade_record["result"]
        pnl = trade_record["pnl"]
        symbol = trade_record["symbol"]
        msg = f"Option #{trade_id} settled · {symbol} · {res} · PnL ${pnl:+.2f}"
        if res == "WIN":
            console.success(msg)
        elif res == "LOSS":
            console.warning(msg)
        elif res == "TIE":
            console.info(msg)
        else:
            console.error(f"Option #{trade_id} settled · {symbol} · {res}")

    # ------------------------------------------------------------------ #
    #  LEGACY BROKER-CLOSED MONITORING  (fallback for broker-closed positions)
    # ------------------------------------------------------------------ #

    def _monitor_active_trades(self):
        """
        Legacy monitor that checks if the broker has closed any positions.
        Only used as a fallback for marginal modes.
        The primary closing mechanism is now _monitor_active_trades_market_price().
        """
        if self._mode not in MARGINAL_MODES:
            return
        with self._trade_lock:
            active_copy = list(self.active_trades)

        for trade in active_copy:
            if trade.get("status") == "CLOSED":
                continue
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

                res = trade["result"]
                pnl = trade.get("pnl", 0.0)
                msg = f"Trade #{pos_id} closed by broker · {trade['symbol']} · {res} · PnL ${pnl:+.2f}"
                if res == "WIN":
                    console.success(msg)
                elif res == "LOSS":
                    console.warning(msg)
                else:
                    console.info(msg)

    # ------------------------------------------------------------------ #
    #  PERSISTENCE HELPERS
    # ------------------------------------------------------------------ #

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
                "open_position_ids": [t["trade_id"] for t in self.active_trades if t.get("status") == "OPEN"],
                "last_processed_signal": last_signal,
                "last_known_balance": self.current_balance,
                "connection_state": connection_state or (("CONNECTED" if self.auth.is_connected else "DISCONNECTED")),
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