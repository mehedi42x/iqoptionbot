"""
bot.py - Main Command Line Controller
Auto-discovers strategies, reads ACTIVE_ID and MODE from .env.
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

from console import console, ConsoleLogHandler
from core import TradingEngine


def _setup_logging() -> None:
    """
    Terminal gets ONLY clean, colour-coded lines via the console handler.
    Full debug detail (with tracebacks) is written to case/bot.log.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console_handler = ConsoleLogHandler()
    console_handler.setLevel(logging.INFO)
    root.addHandler(console_handler)

    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, "case")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(os.path.join(log_dir, "bot.log"), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
        )
        root.addHandler(file_handler)
    except Exception:
        pass

    for noisy in ("websocket", "urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("IQ_BOT")

VALID_MODES = ["BINARY", "DIGITAL", "FOREX", "MARGINAL", "BLIZ"]
VALID_ACCOUNTS = ["PRACTICE", "REAL"]


def discover_strategies() -> Dict[str, str]:
    """
    Auto-discovers strategy modules in the Strategies/ directory.
    Scans for Python files that export an `analyze` function.
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
    console.status("Reading .env configuration...")
    load_dotenv(override=True)
    email = os.getenv("IQ_EMAIL", "").strip()
    password = os.getenv("IQ_PASSWORD", "").strip()
    
    active_id_str = os.getenv("ACTIVE_ID", os.getenv("BLIZ_ACTIVE_ID", "")).strip()
    symbol = os.getenv("SYMBOL", "").strip().upper()

    active_id: Optional[int] = None
    if active_id_str:
        try:
            active_id = int(active_id_str)
        except ValueError:
            console.error(f"Invalid ACTIVE_ID '{active_id_str}' in .env. Must be a valid integer.")
            sys.exit(1)
        if not symbol:
            symbol = f"ACTIVE_{active_id}"
    else:
        if not symbol:
            symbol = "XAUUSD"

    amount = float(os.getenv("AMOUNT", "10"))
    account = os.getenv("ACCOUNT", "PRACTICE").strip().upper()
    mode = os.getenv("MODE", "").strip().upper()
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
        console.error("IQ_EMAIL is missing in .env")
        sys.exit(1)
    if not password:
        console.error("IQ_PASSWORD is missing in .env")
        sys.exit(1)
    if account not in VALID_ACCOUNTS:
        console.error(f"Invalid ACCOUNT '{account}'. Must be one of {VALID_ACCOUNTS}")
        sys.exit(1)
    if mode not in VALID_MODES:
        console.error(f"Invalid MODE '{mode}'. Must be one of {VALID_MODES}")
        sys.exit(1)

    console.status("Discovering strategies...")
    available_strategies = discover_strategies()
    if not available_strategies:
        console.warning("No strategies discovered in Strategies/ directory.")
    elif strategy not in available_strategies:
        console.warning(
            f"Strategy '{strategy}' not found in {list(available_strategies.keys())}. "
            "The engine will try to load it anyway."
        )

    return {
        "IQ_EMAIL": email, "IQ_PASSWORD": password, "SYMBOL": symbol,
        "ACTIVE_ID": active_id,
        "AMOUNT": amount, "ACCOUNT": account, "MODE": mode,
        "EXECUTION_TIME": exec_time, "TIMEFRAME": timeframe, "STRATEGY": strategy,
        "LEVERAGE": leverage, "STOP_LOSS": stop_loss, "TAKE_PROFIT": take_profit,
        "MAX_OPEN_TRADES": max_open,
    }


def display_final_summary(summary: Dict[str, Any]):
    console.stop()
    total = summary.get("total_trades", 0)
    wins = summary.get("winning_trades", 0)
    losses = summary.get("losing_trades", 0)
    ties = summary.get("tie_trades", 0)
    win_rate = summary.get("win_rate", 0.0)
    start = summary.get("starting_balance", 0.0)
    end = summary.get("ending_balance", 0.0)
    pnl = summary.get("total_pnl", 0.0)

    console.banner(
        "FINAL TRADING SUMMARY",
        [
            ("Total trades", f"{total}"),
            ("Winning", f"{wins}  (green)"),
            ("Losing", f"{losses}  (red)"),
            ("Tie / equal", f"{ties}"),
            ("Win rate", f"{win_rate:.2f}%"),
            ("-", ""),
            ("Start balance", f"${start:.2f}"),
            ("End balance", f"${end:.2f}"),
            ("Net PnL", f"{'+' if pnl >= 0 else ''}${pnl:.2f}"),
        ],
    )
    if pnl > 0:
        console.success(f"Session finished in profit: +${pnl:.2f}")
    elif pnl < 0:
        console.warning(f"Session finished in loss: ${pnl:.2f}")
    else:
        console.info("Session finished break-even.")


def main():
    config = validate_config()

    banner_items = [
        ("MODE", config.get("MODE")),
        ("SYMBOL", config.get("SYMBOL")),
    ]
    if config.get("ACTIVE_ID"):
        banner_items.append(("ACTIVE_ID", str(config.get("ACTIVE_ID"))))

    banner_items.extend([
        ("STRATEGY", config.get("STRATEGY")),
        ("ACCOUNT", config.get("ACCOUNT")),
        ("TIMEFRAME", f"{config.get('TIMEFRAME')} min"),
        ("AMOUNT", f"${float(config.get('AMOUNT', 10)):.2f}"),
        ("LEVERAGE", f"{config.get('LEVERAGE')}x"),
    ])

    console.banner("IQ OPTION TRADING BOT", banner_items)

    console.status("Loading strategy module...")
    try:
        engine = TradingEngine(config)
    except Exception as e:
        console.error(f"Failed to initialize the trading engine: {e}")
        sys.exit(1)

    def signal_handler(sig, frame):
        console.stop()
        console.warning("Stopping bot gracefully...")
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
