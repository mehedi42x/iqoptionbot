"""
IQ Option Auto-Trading Bot
Application Controller & CLI Interface

Validates environment configuration, initializes core orchestrator,
runs the trading loop, and presents real-time status and final performance summary.
"""

import os
import sys
import time
import signal
from typing import Dict, Any

# Safe dotenv loader (works with or without python-dotenv library)
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=".env"):
        if os.path.exists(dotenv_path):
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v

from core import CoreController


class BotRunner:
    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.core: CoreController = None
        self.start_time: float = 0.0
        self.is_running: bool = False

    def load_and_validate_env(self) -> bool:
        """
        Load environment variables and validate all required parameters.
        """
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if not os.path.exists(env_path):
            example_path = os.path.join(os.path.dirname(__file__), ".env.example")
            if os.path.exists(example_path):
                print(f"[BOT] Warning: .env not found. Copying .env.example to .env")
                with open(example_path, "r") as f_in, open(env_path, "w") as f_out:
                    f_out.write(f_in.read())

        load_dotenv(dotenv_path=env_path)

        email = os.getenv("IQ_EMAIL", "").strip()
        password = os.getenv("IQ_PASSWORD", "").strip()
        symbol = os.getenv("SYMBOL", "XAUUSD").strip()
        amount_raw = os.getenv("AMOUNT", "10").strip()
        account = os.getenv("ACCOUNT", "PRACTICE").strip().upper()
        trade_type = os.getenv("TRADE_TYPE", "FOREX").strip().upper()
        exec_time_raw = os.getenv("EXECUTION_TIME", "").strip()
        timeframe_raw = os.getenv("TIMEFRAME", "1").strip()
        strategy = os.getenv("STRATEGY", "marginal_gold_scalper").strip().lower()
        leverage_raw = os.getenv("LEVERAGE", "10").strip()
        max_open_raw = os.getenv("MAX_OPEN_TRADES", "1").strip()

        # Alias resolution
        if strategy == "leverage":
            strategy = "marginal_gold_scalper"

        # Validations
        if not email or not password:
            print("[BOT ERROR] Missing IQ_EMAIL or IQ_PASSWORD in .env file.")
            return False

        if account not in ["PRACTICE", "REAL"]:
            print(f"[BOT ERROR] Invalid ACCOUNT: '{account}'. Allowed: PRACTICE, REAL")
            return False

        if trade_type not in ["BINARY", "DIGITAL", "FOREX", "MARGINAL", "BLIZ"]:
            print(f"[BOT ERROR] Invalid TRADE_TYPE: '{trade_type}'. Allowed: BINARY, DIGITAL, FOREX, MARGINAL, BLIZ")
            return False

        try:
            amount = float(amount_raw)
            if amount <= 0:
                print(f"[BOT ERROR] AMOUNT must be greater than 0.")
                return False
        except ValueError:
            print(f"[BOT ERROR] Invalid numeric value for AMOUNT: '{amount_raw}'")
            return False

        try:
            timeframe = int(timeframe_raw)
            if timeframe <= 0:
                print(f"[BOT ERROR] TIMEFRAME must be a positive integer.")
                return False
        except ValueError:
            print(f"[BOT ERROR] Invalid numeric value for TIMEFRAME: '{timeframe_raw}'")
            return False

        try:
            max_open = int(max_open_raw)
            if max_open <= 0:
                print(f"[BOT ERROR] MAX_OPEN_TRADES must be >= 1.")
                return False
        except ValueError:
            print(f"[BOT ERROR] Invalid numeric value for MAX_OPEN_TRADES: '{max_open_raw}'")
            return False

        leverage = None
        if trade_type in ["FOREX", "MARGINAL"]:
            if exec_time_raw != "":
                print(f"[BOT ERROR] EXECUTION_TIME must be blank for FOREX/MARGINAL trade types.")
                return False
            try:
                leverage = int(leverage_raw)
                if leverage <= 0:
                    print(f"[BOT ERROR] LEVERAGE must be greater than 0.")
                    return False
            except ValueError:
                print(f"[BOT ERROR] Invalid LEVERAGE: '{leverage_raw}'")
                return False
            exec_time = None
        else:
            try:
                exec_time = int(exec_time_raw)
                if trade_type == "BINARY" and exec_time not in [1, 2, 3, 4, 5]:
                    print(f"[BOT ERROR] Invalid EXECUTION_TIME '{exec_time}' for BINARY. Allowed: 1, 2, 3, 4, 5")
                    return False
                if trade_type == "DIGITAL" and exec_time not in [1, 5, 15]:
                    print(f"[BOT ERROR] Invalid EXECUTION_TIME '{exec_time}' for DIGITAL. Allowed: 1, 5, 15")
                    return False
                if trade_type == "BLIZ" and exec_time not in [1, 2, 3, 4, 5]:
                    print(f"[BOT ERROR] Invalid EXECUTION_TIME '{exec_time}' for BLIZ. Allowed: 1, 2, 3, 4, 5")
                    return False
            except ValueError:
                print(f"[BOT ERROR] EXECUTION_TIME is required for {trade_type} (e.g. 1, 5).")
                return False

        valid_strategies = [
            "short_term_option_scalper",
            "short_term_option_reversal",
            "marginal_gold_scalper",
            "marginal_breakout_pro",
            "marginal_momentum_reversal"
        ]
        if strategy not in valid_strategies:
            print(f"[BOT ERROR] Unknown STRATEGY: '{strategy}'. Allowed: {', '.join(valid_strategies)}")
            return False

        self.config = {
            "IQ_EMAIL": email,
            "IQ_PASSWORD": password,
            "SYMBOL": symbol,
            "AMOUNT": amount,
            "ACCOUNT": account,
            "TRADE_TYPE": trade_type,
            "EXECUTION_TIME": exec_time,
            "TIMEFRAME": timeframe,
            "STRATEGY": strategy,
            "LEVERAGE": leverage,
            "MAX_OPEN_TRADES": max_open
        }
        return True

    def print_banner(self):
        print("=" * 65)
        print("          IQ OPTION MODULAR AUTO-TRADING BOT")
        print("=" * 65)
        print(f" Account Mode   : {self.config['ACCOUNT']}")
        print(f" Trading Symbol : {self.config['SYMBOL']}")
        print(f" Trade Type     : {self.config['TRADE_TYPE']}")
        print(f" Strategy       : {self.config['STRATEGY']}")
        print(f" Base Amount    : ${self.config['AMOUNT']}")
        if self.config["TRADE_TYPE"] in ["FOREX", "MARGINAL"]:
            print(f" Leverage       : {self.config['LEVERAGE']}x")
        else:
            print(f" Expiration     : {self.config['EXECUTION_TIME']} min")
        print(f" Max Open Trades: {self.config['MAX_OPEN_TRADES']}")
        print("=" * 65)

    def print_summary(self):
        duration = time.time() - self.start_time if self.start_time > 0 else 0
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        total_trades = len(self.core.closed_trades) if self.core else 0
        wins = self.core.wins if self.core else 0
        losses = self.core.losses if self.core else 0
        ties = self.core.ties if self.core else 0
        pnl = self.core.total_pnl if self.core else 0.0

        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

        print("\n" + "=" * 65)
        print("                   FINAL SESSION SUMMARY")
        print("=" * 65)
        print(f" Session Duration : {minutes}m {seconds}s")
        print(f" Total Trades     : {total_trades}")
        print(f" Wins             : {wins}")
        print(f" Losses           : {losses}")
        print(f" Ties             : {ties}")
        print(f" Win Rate         : {win_rate:.1f}%")
        print(f" Total PnL        : ${pnl:+.2f}")
        if self.core and self.core.auth:
            bal = self.core.auth.get_balance()
            print(f" Final Balance    : ${bal:.2f} ({self.config.get('ACCOUNT', 'PRACTICE')})")
        print("=" * 65 + "\n")

    def run(self):
        if not self.load_and_validate_env():
            sys.exit(1)

        self.print_banner()

        try:
            self.core = CoreController(self.config)
        except Exception as e:
            print(f"[BOT ERROR] Core initialization failed: {e}")
            sys.exit(1)

        # Validate strategy compatibility inside core
        valid, msg = self.core.validate_setup()
        if not valid:
            print(f"[BOT ERROR] Strategy compatibility check failed:\n  -> {msg}")
            sys.exit(1)

        print("[BOT] Authenticating with IQ Option broker...")
        connected, reason = self.core.connect()
        if not connected:
            print(f"[BOT ERROR] Broker connection failed: {reason}")
            sys.exit(1)

        print(f"[BOT] Connected successfully. ({reason})")
        balance = self.core.auth.get_balance()
        print(f"[BOT] Initial {self.config['ACCOUNT']} Balance: ${balance:.2f}")
        print("[BOT] Auto-trading engine is active. Press Ctrl+C to stop.\n")

        # Setup signal handler for graceful shutdown
        def signal_handler(sig, frame):
            self.is_running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        self.is_running = True
        self.start_time = time.time()

        try:
            while self.is_running:
                # 1. Execute strategy analysis and potential order
                self.core.evaluate_and_trade()

                # 2. Monitor open positions / trades
                self.core.monitor_open_trades()

                # Polling interval (1-2 seconds)
                time.sleep(2)
        except KeyboardInterrupt:
            pass
        finally:
            if self.core:
                self.core.shutdown()
            self.print_summary()


if __name__ == "__main__":
    bot = BotRunner()
    bot.run()
