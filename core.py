"""
Core Trading Controller & Orchestrator
Acts as the central bridge between bot.py, Strategies, and the API layer.
Handles data fetching based on strategy requirements, validation, execution, and trade monitoring.
Contains NO hardcoded market analysis or strategy indicator formulas.
"""

import sys
import os
import json
import time
import logging
from typing import Dict, Any, Optional, List, Tuple

# API modules
from api.auth import IQAuth
from api.binary import BinaryAPI
from api.digital import DigitalAPI
from api.Marginal import MarginalAPI
from api.bliz import BlizAPI

# Strategy modules
from Strategies.short_term_option_scalper import ShortTermOptionScalper
from Strategies.short_term_option_reversal import ShortTermOptionReversal
from Strategies.marginal_gold_scalper import MarginalGoldScalper
from Strategies.marginal_breakout_pro import MarginalBreakoutPro
from Strategies.marginal_momentum_reversal import MarginalMomentumReversal

logger = logging.getLogger("CoreTradingBridge")


class CoreController:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.running = False

        # Resolve Strategy & Aliases
        self.strategy_name = self.config.get("STRATEGY", "").lower().strip()
        if self.strategy_name == "leverage":
            self.strategy_name = "marginal_gold_scalper"

        self.strategy = self._initialize_strategy(self.strategy_name)

        # Initialize Auth & API layer
        self.auth = IQAuth(
            email=self.config.get("IQ_EMAIL", ""),
            password=self.config.get("IQ_PASSWORD", ""),
            account_type=self.config.get("ACCOUNT", "PRACTICE")
        )

        self.api_binary = BinaryAPI(self.auth)
        self.api_digital = DigitalAPI(self.auth)
        self.api_marginal = MarginalAPI(self.auth)
        self.api_bliz = BlizAPI(self.auth)

        # State tracking
        self.open_trades: List[Dict[str, Any]] = []
        self.closed_trades: List[Dict[str, Any]] = []
        self.total_pnl: float = 0.0
        self.wins: int = 0
        self.losses: int = 0
        self.ties: int = 0
        self.session_file = os.path.join(os.path.dirname(__file__), "case", "session_trades.json")

        self._ensure_case_dir()

    def _ensure_case_dir(self):
        case_dir = os.path.join(os.path.dirname(__file__), "case")
        os.makedirs(case_dir, exist_ok=True)

    def _initialize_strategy(self, strategy_name: str):
        strategies_map = {
            "short_term_option_scalper": ShortTermOptionScalper,
            "short_term_option_reversal": ShortTermOptionReversal,
            "marginal_gold_scalper": MarginalGoldScalper,
            "marginal_breakout_pro": MarginalBreakoutPro,
            "marginal_momentum_reversal": MarginalMomentumReversal
        }

        strategy_cls = strategies_map.get(strategy_name)
        if not strategy_cls:
            raise ValueError(f"Unknown or unsupported strategy: {strategy_name}")

        return strategy_cls()

    def validate_setup(self) -> Tuple[bool, str]:
        """
        Validate strategy compatibility with trade type and configuration parameters.
        """
        trade_type = self.config.get("TRADE_TYPE", "").upper()
        if trade_type not in self.strategy.compatible_trade_types:
            return False, f"Strategy '{self.strategy_name}' is not compatible with TRADE_TYPE '{trade_type}'. Compatible types: {self.strategy.compatible_trade_types}"

        if trade_type in ["FOREX", "MARGINAL"]:
            exec_time = self.config.get("EXECUTION_TIME")
            if exec_time and str(exec_time).strip() != "":
                return False, "EXECUTION_TIME must be blank for FOREX/MARGINAL trading."
            leverage = self.config.get("LEVERAGE")
            if not leverage or int(leverage) <= 0:
                return False, "LEVERAGE must be a positive integer for FOREX/MARGINAL."
        else:
            exec_time = self.config.get("EXECUTION_TIME")
            if not exec_time:
                return False, f"EXECUTION_TIME is required for {trade_type}."

        return True, "Setup validated successfully"

    def connect(self) -> Tuple[bool, str]:
        """
        Connect to IQ Option via auth module.
        """
        return self.auth.connect()

    def fetch_market_data(self) -> Optional[Dict[str, Any]]:
        """
        Fetch market data required by the active strategy using the correct API module.
        Enforces strict 'NO DATA = NO TRADE' rule.
        """
        reqs = self.strategy.get_requirements()
        timeframe = reqs.get("timeframe", 60)
        candle_count = reqs.get("candle_count", 30)
        symbol = self.config.get("SYMBOL", "XAUUSD")
        trade_type = self.config.get("TRADE_TYPE", "FOREX").upper()

        if not self.auth.check_connection():
            if not self.auth.reconnect():
                print("[CORE] Trade skipped: API connection unavailable.")
                return None

        # Fetch candles via corresponding API module
        candles = []
        current_price = None

        if trade_type == "BINARY":
            candles = self.api_binary.get_candles(symbol, timeframe, candle_count)
            current_price = self.api_binary.get_realtime_price(symbol)
        elif trade_type == "DIGITAL":
            candles = self.api_digital.get_candles(symbol, timeframe, candle_count)
            current_price = self.api_digital.get_realtime_price(symbol)
        elif trade_type in ["FOREX", "MARGINAL"]:
            candles = self.api_marginal.get_candles(symbol, timeframe, candle_count)
            current_price = self.api_marginal.get_realtime_price(symbol)
        elif trade_type == "BLIZ":
            candles = self.api_bliz.get_candles(symbol, timeframe, candle_count)
            current_price = self.api_bliz.get_realtime_price(symbol)

        # Validation Rule: NO DATA = NO TRADE
        if not candles:
            print("[CORE] Trade skipped: Required candle data unavailable.")
            return None

        if len(candles) < (candle_count * 0.7):
            print(f"[CORE] Trade skipped: Insufficient historical candles ({len(candles)}/{candle_count}).")
            return None

        if current_price is None or current_price <= 0:
            print("[CORE] Trade skipped: Current price unavailable.")
            return None

        # Validate freshness (candle timestamp must not be excessively stale)
        last_candle_time = candles[-1].get("to", candles[-1].get("at", 0))
        now = time.time()
        if last_candle_time > 0 and (now - last_candle_time) > 300:
            print(f"[CORE] Trade skipped: Market data is stale (age: {int(now - last_candle_time)}s).")
            return None

        return {
            "symbol": symbol,
            "current_price": current_price,
            "candles": candles,
            "timestamp": now
        }

    def evaluate_and_trade(self):
        """
        Main execution cycle: Market Data -> Strategy Analysis -> Validation -> API Order -> Monitoring.
        """
        max_open = int(self.config.get("MAX_OPEN_TRADES", 1))
        if len(self.open_trades) >= max_open:
            # Skip placing new trades while max limit is reached
            return

        # 1. Gather Market Data
        market_data = self.fetch_market_data()
        if not market_data:
            return

        # 2. Query Strategy for Signal
        signal = self.strategy.analyze(market_data)

        # 3. Validate Strategy Output
        action = signal.get("action", "NO_SIGNAL").upper()
        if action in ["NO_SIGNAL", "NONE", ""]:
            return

        trade_type = self.config.get("TRADE_TYPE", "FOREX").upper()
        symbol = self.config.get("SYMBOL", "XAUUSD")
        amount = float(self.config.get("AMOUNT", 10))

        balance = self.auth.get_balance()
        if balance < amount:
            print(f"[CORE] Trade skipped: Insufficient account balance (${balance:.2f} < ${amount:.2f}).")
            return

        # Option Trade Validation & Execution
        if trade_type in ["BINARY", "DIGITAL", "BLIZ"]:
            if action not in ["CALL", "PUT"]:
                print(f"[CORE] Trade skipped: Strategy signal validation failed ({action}).")
                return

            exec_time = int(self.config.get("EXECUTION_TIME", 1))
            print(f"\n[SIGNAL DETECTED] Action: {action} | Asset: {symbol} | Confidence: {signal.get('confidence', 0):.2f}")
            print(f"[STRATEGY REASON] {signal.get('reason', 'N/A')}")

            success = False
            trade_id = None
            info = None

            if trade_type == "BINARY":
                success, trade_id, info = self.api_binary.execute_trade(symbol, amount, action, exec_time)
            elif trade_type == "DIGITAL":
                success, trade_id, info = self.api_digital.execute_trade(symbol, amount, action, exec_time)
            elif trade_type == "BLIZ":
                success, trade_id, info = self.api_bliz.execute_trade(symbol, amount, action, exec_time)

            if success and info:
                info["trade_type"] = trade_type
                info["reason"] = signal.get("reason")
                self.open_trades.append(info)
                print(f"[CORE] Order successfully executed | ID: {trade_id} | Amount: ${amount} | Expiration: {exec_time}m")
                self._save_session_state()
            else:
                print(f"[CORE] Trade skipped: Broker rejected order -> {trade_id}")

        # Forex / Marginal Trade Validation & Execution
        elif trade_type in ["FOREX", "MARGINAL"]:
            if action not in ["BUY", "SELL"]:
                print(f"[CORE] Trade skipped: Strategy signal validation failed ({action}).")
                return

            stop_loss = signal.get("stop_loss")
            take_profit = signal.get("take_profit")
            current_price = market_data["current_price"]

            # SL / TP Validation
            if action == "BUY":
                if stop_loss is not None and stop_loss >= current_price:
                    print(f"[CORE] Trade skipped: Invalid SL/TP (BUY SL {stop_loss} >= Price {current_price}).")
                    return
                if take_profit is not None and take_profit <= current_price:
                    print(f"[CORE] Trade skipped: Invalid SL/TP (BUY TP {take_profit} <= Price {current_price}).")
                    return
            elif action == "SELL":
                if stop_loss is not None and stop_loss <= current_price:
                    print(f"[CORE] Trade skipped: Invalid SL/TP (SELL SL {stop_loss} <= Price {current_price}).")
                    return
                if take_profit is not None and take_profit >= current_price:
                    print(f"[CORE] Trade skipped: Invalid SL/TP (SELL TP {take_profit} >= Price {current_price}).")
                    return

            leverage = int(self.config.get("LEVERAGE", 10))
            print(f"\n[SIGNAL DETECTED] Action: {action} | Asset: {symbol} | Price: {current_price} | SL: {stop_loss} | TP: {take_profit}")
            print(f"[STRATEGY REASON] {signal.get('reason', 'N/A')}")

            success, pos_id, info = self.api_marginal.open_position(
                symbol=symbol,
                action=action,
                amount=amount,
                leverage=leverage,
                stop_loss=stop_loss,
                take_profit=take_profit
            )

            if success and info:
                info["trade_type"] = trade_type
                info["reason"] = signal.get("reason")
                self.open_trades.append(info)
                print(f"[CORE] Position opened | ID: {pos_id} | Amount: ${amount} | Leverage: {leverage}x")
                self._save_session_state()
            else:
                print(f"[CORE] Trade skipped: Failed to open position -> {pos_id}")

    def monitor_open_trades(self):
        """
        Monitor active positions, check expirations / SL / TP / Strategy early-exit rules.
        """
        if not self.open_trades:
            return

        remaining_trades = []
        for trade in self.open_trades:
            trade_type = trade.get("trade_type", "")
            trade_id = trade.get("id") or trade.get("position_id")

            # Monitoring Binary / Digital / Bliz Options
            if trade_type in ["BINARY", "DIGITAL", "BLIZ"]:
                open_time = trade.get("open_time", 0)
                duration_secs = trade.get("duration", 1) * 60
                elapsed = time.time() - open_time

                if elapsed >= duration_secs:
                    # Expiration reached, determine outcome
                    status = "PENDING"
                    pnl = 0.0

                    if trade_type == "BINARY":
                        status, pnl = self.api_binary.check_trade_result(trade_id)
                    elif trade_type == "DIGITAL":
                        status, pnl = self.api_digital.check_trade_result(trade_id)
                    elif trade_type == "BLIZ":
                        status, pnl = self.api_bliz.check_trade_result(trade_id)

                    if status in ["WIN", "LOSE", "TIE"]:
                        trade["status"] = status
                        trade["pnl"] = pnl
                        trade["close_time"] = time.time()
                        self._record_trade_closure(trade)
                        continue

                remaining_trades.append(trade)

            # Monitoring Forex / Marginal Positions
            elif trade_type in ["FOREX", "MARGINAL"]:
                pnl, current_price = self.api_marginal.get_position_pnl(trade_id, trade)
                action = trade.get("action", "").lower()
                sl = trade.get("stop_loss")
                tp = trade.get("take_profit")

                should_close = False
                close_reason = ""

                # Check Stop Loss / Take Profit triggers
                if action == "buy":
                    if sl and current_price <= sl:
                        should_close = True
                        close_reason = f"Stop Loss hit at {current_price:.2f}"
                    elif tp and current_price >= tp:
                        should_close = True
                        close_reason = f"Take Profit hit at {current_price:.2f}"
                elif action == "sell":
                    if sl and current_price >= sl:
                        should_close = True
                        close_reason = f"Stop Loss hit at {current_price:.2f}"
                    elif tp and current_price <= tp:
                        should_close = True
                        close_reason = f"Take Profit hit at {current_price:.2f}"

                # Query Strategy for Early Exit condition
                if not should_close and hasattr(self.strategy, "analyze_exit"):
                    market_data = self.fetch_market_data()
                    if market_data:
                        exit_signal = self.strategy.analyze_exit(market_data, trade)
                        if exit_signal.get("action") == "EXIT":
                            should_close = True
                            close_reason = exit_signal.get("reason", "Strategy early-exit condition triggered")

                if should_close:
                    success, res = self.api_marginal.close_position(trade_id)
                    if success:
                        trade["status"] = "CLOSED"
                        trade["pnl"] = pnl
                        trade["close_price"] = current_price
                        trade["close_reason"] = close_reason
                        trade["close_time"] = time.time()
                        self._record_trade_closure(trade)
                        continue

                remaining_trades.append(trade)

        self.open_trades = remaining_trades

    def _record_trade_closure(self, trade: Dict[str, Any]):
        pnl = trade.get("pnl", 0.0)
        self.total_pnl += pnl
        if pnl > 0:
            self.wins += 1
            outcome_str = f"WIN (+${pnl:.2f})"
        elif pnl < 0:
            self.losses += 1
            outcome_str = f"LOSS (-${abs(pnl):.2f})"
        else:
            self.ties += 1
            outcome_str = "TIE ($0.00)"

        trade_id = trade.get("id") or trade.get("position_id")
        print(f"\n[TRADE RESOLVED] ID: {trade_id} | Outcome: {outcome_str} | Total Session PnL: ${self.total_pnl:+.2f}")
        self.closed_trades.append(trade)
        self._save_session_state()

    def _save_session_state(self):
        """
        Persist session trade log in case/ directory without passwords.
        """
        try:
            state = {
                "strategy": self.strategy_name,
                "symbol": self.config.get("SYMBOL"),
                "account": self.config.get("ACCOUNT"),
                "trade_type": self.config.get("TRADE_TYPE"),
                "total_trades": len(self.closed_trades),
                "wins": self.wins,
                "losses": self.losses,
                "ties": self.ties,
                "total_pnl": round(self.total_pnl, 2),
                "closed_trades": self.closed_trades
            }
            with open(self.session_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving session state: {e}")

    def shutdown(self):
        """
        Graceful shutdown routine upon SIGINT / Ctrl+C.
        """
        print("\n[CORE] Initiating graceful shutdown...")
        self.running = False
        if self.open_trades:
            print(f"[CORE] Handling {len(self.open_trades)} active positions...")
            for t in self.open_trades:
                tid = t.get("position_id")
                if tid and t.get("trade_type") in ["FOREX", "MARGINAL"]:
                    print(f"[CORE] Auto-closing open position {tid} for safe shutdown...")
                    self.api_marginal.close_position(tid)

        self.auth.disconnect()
        self._save_session_state()
        print("[CORE] Disconnected safely. Session saved.")
