"""
bot.py - Main Command Line Controller
Auto-discovers strategies and uses MODE from .env to select the trading API.
"""

import os
import signal
import sys
import logging
import importlib
import pkgutil
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path: Optional[str] = None, override: bool = True):
        env_file = dotenv_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if not os.path.exists(env_file):
            return
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if override or k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip("'\"'")

from core import TradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("IQ_BOT")

VALID_MODES = ["BINARY", "DIGITAL", "FOREX", "MARGINAL", "BLIZ"]
VALID_ACCOUNTS = ["PRACTICE", "REAL"]


def discover_strategies() -> Dict[str, str]:
    """
    Auto-discovers strategy modules in the Strategies/ directory.
    Scans for Python files that export an `analyze` function.
    Returns a dict mapping strategy_name -> module_path.
    """
    strategies = {}
    strategies_pkg = "Strategies"
    try:
        import Strategies as pkg
        for importer, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
            if modname.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"{strategies_pkg}.{modname}")
                if hasattr(module, "analyze") and callable(module.analyze):
                    strategies[modname] = f"{strategies_pkg}.{modname}"
                    logger.debug(f"Discovered strategy: {modname}")
            except Exception as e:
                logger.warning(f"Could not load strategy '{modname}': {e}")
    except Exception as e:
        logger.error(f"Failed to discover strategies: {e}")
    return strategies


def validate_config() -> Dict[str, Any]:
    load_dotenv(override=True)
    email = os.getenv("IQ_EMAIL", "").strip()
    password = os.getenv("IQ_PASSWORD", "").strip()
    symbol = os.getenv("SYMBOL", "XAUUSD").strip().upper()
    amount = float(os.getenv("AMOUNT", "10"))
    account = os.getenv("ACCOUNT", "PRACTICE").strip().upper()
    mode = os.getenv("MODE", "").strip().upper()
    # Fallback to TRADE_TYPE if MODE is not set (backward compatibility)
    if not mode:
        mode = os.getenv("TRADE_TYPE", "FOREX").strip().upper()
    exec_time = os.getenv("EXECUTION_TIME", "").strip()
    timeframe = int(os.getenv("TIMEFRAME", "1"))
    strategy = os.getenv("STRATEGY", "marginal_gold_scalper").strip()
    leverage = int(os.getenv("LEVERAGE", "10"))
    stop_loss = float(os.getenv("STOP_LOSS", "2.00"))
    take_profit = float(os.getenv("TAKE_PROFIT", "4.00"))
    max_open = int(os.getenv("MAX_OPEN_TRADES", "1"))

    if not email:
        sys.exit("Error: IQ_EMAIL is missing in .env")
    if not password:
        sys.exit("Error: IQ_PASSWORD is missing in .env")
    if account not in VALID_ACCOUNTS:
        sys.exit(f"Error: Invalid ACCOUNT '{account}'. Must be one of {VALID_ACCOUNTS}")
    if mode not in VALID_MODES:
        sys.exit(f"Error: Invalid MODE '{mode}'. Must be one of {VALID_MODES}")

    # Auto-discover strategies and validate the selected one exists
    available_strategies = discover_strategies()
    if not available_strategies:
        logger.warning("No strategies discovered in Strategies/ directory!")
    elif strategy not in available_strategies:
        logger.warning(
            f"Strategy '{strategy}' not found in discovered strategies: {list(available_strategies.keys())}"
        )
        # Don't exit — allow runtime fallback; core will handle import error

    logger.info(f"Configuration loaded — MODE={mode} STRATEGY={strategy} SYMBOL={symbol} ACCOUNT={account}")

    return {
        "IQ_EMAIL": email, "IQ_PASSWORD": password, "SYMBOL": symbol,
        "AMOUNT": amount, "ACCOUNT": account, "MODE": mode,
        "EXECUTION_TIME": exec_time, "TIMEFRAME": timeframe, "STRATEGY": strategy,
        "LEVERAGE": leverage, "STOP_LOSS": stop_loss, "TAKE_PROFIT": take_profit,
        "MAX_OPEN_TRADES": max_open,
    }


def display_final_summary(summary: Dict[str, Any]):
    print("\n" + "=" * 65)
    print("                    FINAL TRADING SUMMARY")
    print("=" * 65)
    print(f" Total Trades Executed:   {summary.get('total_trades', 0)}")
    print(f" Winning Trades:          {summary.get('winning_trades', 0)} (Green)")
    print(f" Losing Trades:           {summary.get('losing_trades', 0)} (Red)")
    print(f" Tie / Equal Trades:      {summary.get('tie_trades', 0)}")
    print(f" Overall Win Rate:        {summary.get('win_rate', 0.0):.2f}%")
    print("-" * 65)
    print(f" Starting Balance:        ${summary.get('starting_balance', 0.0):.2f}")
    print(f" Ending Balance:          ${summary.get('ending_balance', 0.0):.2f}")
    pnl = summary.get("total_pnl", 0.0)
    print(f" Net Session PnL:         {'+' if pnl >= 0 else ''}${pnl:.2f}")
    print("=" * 65 + "\n")


def main():
    config = validate_config()
    engine = TradingEngine(config)

    def signal_handler(sig, frame):
        print("\n[INFO] Stopping bot gracefully...")
        engine.stop()
        display_final_summary(engine.get_summary())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not engine.initialize():
        sys.exit(1)

    try:
        engine.start()
    except KeyboardInterrupt:
        signal_handler(None, None)


if __name__ == "__main__":
    main()