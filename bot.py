import json
import ssl
import time
import threading
import importlib
import requests
import websocket

from dotenv import dotenv_values
from rich.console import Console
from rich.status import Status
from rich.panel import Panel
from rich.table import Table


CONFIG = dotenv_values(".env")

LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
WS_URL = "wss://iqoption.com/echo/websocket"


class IQOptionBot:

    def __init__(self, config):

        # ======================================================
        # CONFIG
        # ======================================================

        self.email = config["EMAIL"]
        self.password = config["PASSWORD"]

        self.account_type = (
            config.get("ACCOUNT_TYPE", "PRACTICE")
            .upper()
        )

        self.active_id = int(
            config["ACTIVE_ID"]
        )

        self.amount = float(
            config["TRADE_AMOUNT"]
        )

        self.expiration = int(
            config.get(
                "EXPIRATION_SECONDS",
                30
            )
        )

        self.strategy_name = config.get(
            "STRATEGY",
            "turbo_scalping"
        )

        self.max_concurrent_trades = int(
            config.get(
                "MAX_CONCURRENT_TRADES",
                1
            )
        )

        # ======================================================
        # CONNECTION STATE
        # ======================================================

        self.ssid = None
        self.ws = None
        self.balance_id = None

        self.request_id = 0

        self.pending_trades = {}

        self.lock = threading.Lock()
        
        # New State Variable for Auto-Reconnect
        self.is_connected = False 

        # ======================================================
        # TRADING STATISTICS
        # ======================================================

        self.active_trades_count = 0

        self.wins = 0
        self.losses = 0
        self.pnl = 0.0

        # ======================================================
        # CANDLE STORAGE
        # ======================================================

        self.candles = {}

        # ======================================================
        # CONSOLE
        # ======================================================

        self.console = Console()

        self.status = self.console.status(
            "[gray70]Initializing Bot...[/gray70]",
            spinner="dots"
        )

        # ======================================================
        # LOAD STRATEGY
        # ======================================================

        try:

            module = importlib.import_module(
                f"strategies.{self.strategy_name}"
            )

            self.strategy = module.Strategy()

            self.console.print(
                f"[bold green]"
                f"✔ Strategy '{self.strategy_name}' "
                f"loaded successfully!"
                f"[/bold green]"
            )

        except ModuleNotFoundError:

            self.console.print(
                f"[bold red]"
                f"✖ Strategy module "
                f"'strategies.{self.strategy_name}' "
                f"not found!"
                f"[/bold red]"
            )

            raise SystemExit(1)

        # ======================================================
        # GET TIMEFRAMES REQUIRED BY STRATEGY
        # ======================================================

        self.required_timeframes = (
            self._get_strategy_timeframes()
        )

        self.console.print(
            "[bold cyan]"
            f"Strategy Timeframes: "
            f"{self.required_timeframes}"
            "[/bold cyan]"
        )

        # Create storage
        for timeframe in self.required_timeframes:
            self.candles[timeframe] = []

    # ==========================================================
    # STRATEGY TIMEFRAME DISCOVERY
    # ==========================================================

    def _get_strategy_timeframes(self):
        
        if hasattr(
            self.strategy,
            "get_required_timeframes"
        ):

            timeframes = (
                self.strategy
                .get_required_timeframes()
            )

        elif hasattr(
            self.strategy,
            "required_timeframes"
        ):

            timeframes = (
                self.strategy
                .required_timeframes
            )

        else:

            self.console.print(
                "[bold yellow]"
                "⚠ Strategy did not specify "
                "required_timeframes. "
                "Using 60s as fallback."
                "[/bold yellow]"
            )

            timeframes = [60]


        result = set()

        for tf in timeframes:
            try:
                tf = int(tf)
                if tf <= 0:
                    continue
                result.add(tf)
            except (ValueError, TypeError):
                continue

        if not result:
            result.add(60)

        return sorted(result)

    # ==========================================================
    # LOGIN (UPDATED: Returns True/False for auto-reconnect)
    # ==========================================================

    def login(self):

        self.status.start()

        self.status.update(
            "[gray70]"
            "Authenticating with IQ Option..."
            "[/gray70]"
        )

        headers = {
            "Content-Type": "application/json"
        }

        payload = {
            "identifier": self.email,
            "password": self.password
        }

        try:

            resp = requests.post(
                LOGIN_URL,
                json=payload,
                headers=headers,
                timeout=20
            )

            resp.raise_for_status()

            self.ssid = (
                resp.cookies.get("ssid")
            )

            if not self.ssid:

                self.ssid = (
                    resp.json()
                    .get("ssid")
                )

            if not self.ssid:

                raise RuntimeError(
                    "SSID not found in response"
                )

            self.console.print(
                "[bold green]"
                "✔ Login success, SSID acquired"
                "[/bold green]"
            )
            return True

        except Exception as e:

            self.status.stop()

            self.console.print(
                f"[bold red]"
                f"✖ Login Failed: {e}"
                f"[/bold red]"
            )
            return False

    # ==========================================================
    # CONNECT (UPDATED: Added ping intervals to detect drop)
    # ==========================================================

    def connect(self):

        self.status.update(
            "[gray70]"
            "Connecting to WebSockets..."
            "[/gray70]"
        )

        self.ws = websocket.WebSocketApp(

            WS_URL,

            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )

        # Added ping_interval and ping_timeout to detect internet drop instantly
        thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={
                "sslopt": {
                    "cert_reqs": ssl.CERT_NONE
                },
                "ping_interval": 30,
                "ping_timeout": 10
            },
            daemon=True
        )

        thread.start()

    # ==========================================================
    # REQUEST ID
    # ==========================================================

    def _next_id(self):

        self.request_id += 1

        return str(
            self.request_id
        )

    # ==========================================================
    # WEBSOCKET OPEN (UPDATED: is_connected = True)
    # ==========================================================

    def on_open(self, ws):
        
        self.is_connected = True

        self.console.print(
            "[bold cyan]"
            "✔ WebSocket connected"
            "[/bold cyan]"
        )

        self.ws.send(
            json.dumps({
                "name": "ssid",
                "msg": self.ssid,
                "request_id": self._next_id()
            })
        )

        time.sleep(1)

        self.ws.send(
            json.dumps({
                "name": "sendMessage",
                "msg": {
                    "name": "get-balances",
                    "version": "1.0"
                },
                "request_id": self._next_id()
            })
        )

        time.sleep(1)

        self._subscribe_strategy_timeframes()

        self.status.update(
            "[gray70]"
            "Waiting for signals..."
            f" (Active Trades: "
            f"{self.active_trades_count}/"
            f"{self.max_concurrent_trades})"
            "[/gray70]"
        )

    # ==========================================================
    # SUBSCRIBE STRATEGY TIMEFRAMES
    # ==========================================================

    def _subscribe_strategy_timeframes(self):

        for timeframe in self.required_timeframes:
            self._subscribe_candles(timeframe)
            self.console.print(
                "[green]"
                f"✔ Subscribed: "
                f"{self._format_timeframe(timeframe)}"
                "[/green]"
            )
            time.sleep(0.2)

    # ==========================================================
    # SUBSCRIBE CANDLE
    # ==========================================================

    def _subscribe_candles(self, size):

        payload = {
            "name": "subscribeMessage",
            "msg": {
                "name": "candle-generated",
                "params": {
                    "routingFilters": {
                        "active_id": self.active_id,
                        "size": int(size)
                    }
                }
            },
            "request_id": self._next_id()
        }

        try:
            self.ws.send(json.dumps(payload))
        except Exception as e:
            self.console.print(
                "[bold red]"
                f"✖ Candle subscription error "
                f"({size}s): {e}"
                "[/bold red]"
            )

    # ==========================================================
    # FORMAT TIMEFRAME
    # ==========================================================

    @staticmethod
    def _format_timeframe(seconds):

        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds}S"
        if seconds % 60 == 0:
            minutes = seconds // 60
            if minutes < 60:
                return f"{minutes}M"
            if minutes % 60 == 0:
                hours = minutes // 60
                return f"{hours}H"
        return f"{seconds}s"

    # ==========================================================
    # MESSAGE HANDLER
    # ==========================================================

    def on_message(self, ws, message):

        try:
            data = json.loads(message)
        except Exception:
            return

        name = data.get("name")

        if name == "balances":
            self._handle_balances(data)
        elif name == "candle-generated":
            self._handle_candle(data)
        elif name in ("option", "option-open"):
            self._handle_open(data)
        elif name in ("option-closed", "portfolio.position-changed"):
            self._handle_close(data)

    # ==========================================================
    # BALANCE HANDLER
    # ==========================================================

    def _handle_balances(self, data):

        target_type = 4 if self.account_type == "PRACTICE" else 1

        for balance in data.get("msg", []):
            if balance.get("type") == target_type:
                self.balance_id = balance.get("id")
                balance_amount = balance.get("amount")

                panel = Panel(
                    f"[bold blue]Account:[/bold blue] {self.account_type}\n"
                    f"[bold blue]Balance:[/bold blue] ${balance_amount}",
                    title="[bold yellow]Balance Selected[/bold yellow]",
                    expand=False
                )

                self.console.print(panel)
                break

    # ==========================================================
    # CANDLE HANDLER
    # ==========================================================

    def _handle_candle(self, data):

        candle = data.get("msg", {})
        size = candle.get("size")

        if size is None:
            return

        try:
            size = int(size)
        except (ValueError, TypeError):
            return

        if size not in self.required_timeframes:
            return

        candle["low"] = candle.get("min") if candle.get("low") is None else candle.get("low")
        candle["high"] = candle.get("max") if candle.get("high") is None else candle.get("high")

        required = ("open", "close", "high", "low")
        for key in required:
            if candle.get(key) is None:
                return

        self.candles[size].append(candle)

        if len(self.candles[size]) > 500:
            self.candles[size] = self.candles[size][-500:]

        signal = self._send_candle_to_strategy(size, candle)

        if signal:
            self.console.print(
                "[bold yellow]"
                f"⚡ SIGNAL: {str(signal).upper()} "
                f"| TF: {self._format_timeframe(size)}"
                "[/bold yellow]"
            )
            self.place_trade(signal)

        self.status.update(
            "[gray70]"
            "Analyzing Market... "
            f"| Last TF: {self._format_timeframe(size)} "
            f"| Active Trades: {self.active_trades_count}/"
            f"{self.max_concurrent_trades}"
            "[/gray70]"
        )

    # ==========================================================
    # SEND CANDLE TO STRATEGY
    # ==========================================================

    def _send_candle_to_strategy(self, timeframe, candle):

        if hasattr(self.strategy, "update_candle"):
            return self.strategy.update_candle(timeframe, candle)

        method_name = f"update_{self._timeframe_method_name(timeframe)}"

        if hasattr(self.strategy, method_name):
            method = getattr(self.strategy, method_name)
            return method(candle)

        if hasattr(self.strategy, "check_signal"):
            return self.strategy.check_signal()

        return None

    # ==========================================================
    # TIMEFRAME METHOD NAME
    # ==========================================================

    @staticmethod
    def _timeframe_method_name(timeframe):

        timeframe = int(timeframe)
        if timeframe < 60:
            return f"{timeframe}s"
        if timeframe % 60 == 0:
            minutes = timeframe // 60
            if minutes < 60:
                return f"{minutes}m"
            if minutes % 60 == 0:
                hours = minutes // 60
                return f"{hours}h"
        return f"{timeframe}s"

    # ==========================================================
    # PLACE TRADE
    # ==========================================================

    def place_trade(self, direction):

        direction = str(direction).lower()
        if direction not in ("call", "put"):
            return

        with self.lock:
            if self.active_trades_count >= self.max_concurrent_trades:
                return
            if not self.balance_id:
                self.console.print("[bold red]✖ Balance ID unavailable[/bold red]")
                return
            self.active_trades_count += 1

        expired = int(time.time()) + self.expiration
        req_id = self._next_id()

        payload = {
            "name": "sendMessage",
            "request_id": req_id,
            "msg": {
                "name": "binary-options.open-option",
                "version": "2.0",
                "body": {
                    "user_balance_id": self.balance_id,
                    "active_id": self.active_id,
                    "option_type_id": 12,
                    "direction": direction,
                    "expiration_size": self.expiration,
                    "expired": expired,
                    "price": self.amount,
                    "profit_percent": 0,
                    "refund_value": 0,
                }
            }
        }

        try:
            self.ws.send(json.dumps(payload))
        except Exception as e:
            with self.lock:
                if self.active_trades_count > 0:
                    self.active_trades_count -= 1
            self.console.print(f"[bold red]✖ Trade send error: {e}[/bold red]")
            return

        self.pending_trades[req_id] = {
            "direction": direction,
            "amount": self.amount,
            "time": time.time(),
        }

        self.console.print(
            "[bold yellow]⚡ TRADE PLACED:[/bold yellow] "
            f"[bold white]{direction.upper()}[/bold white] "
            f"| Amount: ${self.amount} | Exp: {self.expiration}s"
        )

        self.status.update(
            "[gray70]"
            "Trade Running... "
            f"Active Trades: {self.active_trades_count}/{self.max_concurrent_trades}"
            "[/gray70]"
        )

    # ==========================================================
    # OPEN HANDLER
    # ==========================================================

    def _handle_open(self, data):
        pass

    # ==========================================================
    # CLOSE HANDLER
    # ==========================================================

    def _handle_close(self, data):

        msg = data.get("msg", {})

        if msg.get("status") == "open":
            return

        if msg.get("is_successful") is False:
            with self.lock:
                if self.active_trades_count > 0:
                    self.active_trades_count -= 1
            self.console.print(
                "[bold red]✖ Trade Rejected: "
                f"{msg.get('message', 'Unknown Error')}[/bold red]"
            )
            return

        win_status = msg.get("win")
        win_amount = msg.get("win_amount")
        profit_amount = msg.get("profit_amount")
        amount = msg.get("amount", self.amount)
        result = None

        if win_status == "win":
            result = "WIN"
        elif win_status in ("loose", "loss"):
            result = "LOSS"
        elif win_status in ("equal", "draw"):
            result = "DRAW"
        elif win_amount is not None or profit_amount is not None:
            try:
                p_val = float(win_amount if win_amount is not None else profit_amount)
                if p_val > float(amount):
                    result = "WIN"
                elif p_val == float(amount):
                    result = "DRAW"
                else:
                    result = "LOSS"
            except Exception:
                return

        if result is None:
            return

        if result == "WIN":
            result_text = "[bold green]WIN[/bold green]"
            try:
                p_val = float(profit_amount if profit_amount is not None else win_amount)
            except Exception:
                p_val = 0.0
            
            if p_val > float(amount):
                change = p_val - float(amount)
            else:
                change = p_val
            self.wins += 1

        elif result == "LOSS":
            result_text = "[bold red]LOSS[/bold red]"
            change = -float(amount)
            self.losses += 1
        else:
            result_text = "[bold yellow]DRAW[/bold yellow]"
            change = 0.0

        self.pnl += change

        with self.lock:
            if self.active_trades_count > 0:
                self.active_trades_count -= 1

        table = Table(
            title="[bold]Trade Result[/bold]",
            show_header=True,
            header_style="bold magenta"
        )
        table.add_column("Result", justify="center")
        table.add_column("Profit/Loss", justify="right")
        table.add_column("Total PnL", justify="right")
        table.add_column("Score (W-L)", justify="center")

        pnl_color = "green" if self.pnl >= 0 else "red"
        change_color = "green" if change > 0 else "red" if change < 0 else "yellow"

        table.add_row(
            result_text,
            f"[{change_color}]${change:.2f}[/{change_color}]",
            f"[{pnl_color}]${self.pnl:.2f}[/{pnl_color}]",
            f"[bold white]{self.wins} - {self.losses}[/bold white]"
        )

        self.console.print(table)
        self.status.update(
            "[gray70]"
            "Waiting for next signal... "
            f"Active Trades: {self.active_trades_count}/{self.max_concurrent_trades}"
            "[/gray70]"
        )

    # ==========================================================
    # ERROR (UPDATED: is_connected = False)
    # ==========================================================

    def on_error(self, ws, error):
        
        self.is_connected = False
        self.console.print(
            f"[bold red]✖ WebSocket Error: {error}[/bold red]"
        )

    # ==========================================================
    # CLOSE (UPDATED: is_connected = False)
    # ==========================================================

    def on_close(self, ws, code, msg):
        
        self.is_connected = False
        self.status.stop()
        self.console.print(
            "[bold red][-] WebSocket disconnected[/bold red]"
        )

    # ==========================================================
    # RUN (UPDATED: Added Watchdog Auto-Reconnect Loop)
    # ==========================================================

    def run(self):

        # Initial connect process
        while not self.login():
            self.console.print("[yellow]Retrying login in 60 seconds...[/yellow]")
            time.sleep(60)
            
        self.connect()

        try:
            # Watchdog Loop
            while True:
                time.sleep(5)
                
                # Check if disconnected (Mobile data off or socket closed)
                if not self.is_connected:
                    self.status.stop()
                    self.console.print(
                        "[bold yellow]⚠ Connection lost. Entering sleep mode for 60 seconds...[/bold yellow]"
                    )
                    time.sleep(60) # Sleep Mode
                    
                    # Try to Re-Login (Gets fresh SSID) and Re-Connect
                    self.console.print("[gray70]Attempting to reconnect...[/gray70]")
                    if self.login():
                        self.connect()

        except KeyboardInterrupt:
            self.status.stop()
            self.console.print(
                "\n[bold yellow]Stopping bot...[/bold yellow]"
            )
            if self.ws:
                self.ws.close()


# ==============================================================
# MAIN
# ==============================================================

if __name__ == "__main__":

    bot = IQOptionBot(CONFIG)
    bot.run()
