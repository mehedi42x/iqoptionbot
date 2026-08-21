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
        self.email = config["EMAIL"]
        self.password = config["PASSWORD"]
        self.account_type = config.get("ACCOUNT_TYPE", "PRACTICE").upper()
        self.active_id = int(config["ACTIVE_ID"])  
        self.amount = float(config["TRADE_AMOUNT"])
        self.expiration = int(config.get("EXPIRATION_SECONDS", 30))
        self.strategy_name = config.get("STRATEGY", "turbo_scalping")
        
        self.max_concurrent_trades = int(config.get("MAX_CONCURRENT_TRADES", 1))
        self.active_trades_count = 0

        self.ssid = None
        self.ws = None
        self.balance_id = None
        self.request_id = 0
        self.pending_trades = {}
        self.lock = threading.Lock()

        self.wins = 0
        self.losses = 0
        self.pnl = 0.0

        self.console = Console()
        self.status = self.console.status("[gray70]Initializing Bot...[/gray70]", spinner="dots")
        
        try:
            module = importlib.import_module(f"strategies.{self.strategy_name}")
            self.strategy = module.Strategy()
            self.console.print(f"[bold green]✔ Strategy '{self.strategy_name}' loaded successfully![/bold green]")
        except ModuleNotFoundError:
            self.console.print(f"[bold red]✖ Strategy module 'strategies.{self.strategy_name}' not found![/bold red]")
            exit(1)

    def login(self):
        self.status.start()
        self.status.update("[gray70]Authenticating with IQ Option...[/gray70]")
        
        headers = {"Content-Type": "application/json"}
        payload = {"identifier": self.email, "password": self.password}
        
        try:
            resp = requests.post(LOGIN_URL, json=payload, headers=headers)
            resp.raise_for_status()

            self.ssid = resp.cookies.get("ssid")
            if not self.ssid:
                self.ssid = resp.json().get("ssid")

            if not self.ssid:
                raise RuntimeError("SSID not found in response")

            self.console.print("[bold green]✔ Login success, SSID acquired[/bold green]")
        except Exception as e:
            self.status.stop()
            self.console.print(f"[bold red]✖ Login Failed: {e}[/bold red]")
            exit(1)

    def connect(self):
        self.status.update("[gray70]Connecting to WebSockets...[/gray70]")
        self.ws = websocket.WebSocketApp(
            WS_URL,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        t = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}},
        )
        t.daemon = True
        t.start()

    def _next_id(self):
        self.request_id += 1
        return str(self.request_id)

    def on_open(self, ws):
        self.console.print("[bold cyan]✔ WebSocket connected[/bold cyan]")
        
        self.ws.send(json.dumps({
            "name": "ssid",
            "msg": self.ssid,
            "request_id": self._next_id()
        }))
        time.sleep(1)
        
        self.ws.send(json.dumps({
            "name": "sendMessage",
            "msg": {"name": "get-balances", "version": "1.0"},
            "request_id": self._next_id()
        }))
        time.sleep(1)
        
        self._subscribe_candles(60)
        self._subscribe_candles(15)
        
        self.status.update(f"[gray70]Waiting for signals... (Active Trades: 0/{self.max_concurrent_trades})[/gray70]")

    def _subscribe_candles(self, size):
        payload = {
            "name": "subscribeMessage",
            "msg": {
                "name": "candle-generated",
                "params": {
                    "routingFilters": {"active_id": self.active_id, "size": size}
                },
            },
            "request_id": self._next_id()
        }
        self.ws.send(json.dumps(payload))

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

    def _handle_balances(self, data):
        target_type = 4 if self.account_type == "PRACTICE" else 1
        for bal in data.get("msg", []):
            if bal.get("type") == target_type:
                self.balance_id = bal.get("id")
                balance_amount = bal.get("amount")
                
                panel = Panel(
                    f"[bold blue]Account:[/bold blue] {self.account_type}\n"
                    f"[bold blue]Balance:[/bold blue] ${balance_amount}",
                    title="[bold yellow]Balance Selected[/bold yellow]",
                    expand=False
                )
                self.console.print(panel)
                break

    def _handle_candle(self, data):
        candle = data.get("msg", {})
        size = candle.get("size")
        
        candle["low"] = candle.get("min")
        candle["high"] = candle.get("max")

        if size == 60:
            self.strategy.update_1m(candle)
        elif size == 15:
            self.strategy.update_15s(candle)
            
            self.status.update(f"[gray70]Analyzing Market... Active Trades: {self.active_trades_count}/{self.max_concurrent_trades}[/gray70]")

            signal = self.strategy.check_signal()
            if signal:
                self.place_trade(signal)

    def place_trade(self, direction):
        with self.lock:
            if self.active_trades_count >= self.max_concurrent_trades:
                return
            if not self.balance_id:
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
            self.ws.send(json.dumps(payload))

            self.pending_trades[req_id] = {
                "direction": direction,
                "amount": self.amount,
                "time": time.time(),
            }
            
            self.console.print(f"[bold yellow]⚡ TRADE PLACED:[/bold yellow] [bold white]{direction.upper()}[/bold white] | Amount: ${self.amount} | Exp: {self.expiration}s")
            self.status.update(f"[gray70]Trade Running... Active Trades: {self.active_trades_count}/{self.max_concurrent_trades}[/gray70]")

    def _handle_open(self, data):
        pass 

    def _handle_close(self, data):
        msg = data.get("msg", {})
        
        # ১. যদি স্ট্যাটাস "open" থাকে, তবে এটি ক্লোজ ইভেন্ট নয়, তাই ইগনোর করব
        if msg.get("status") == "open":
            return
            
        # ২. ট্রেড যদি সার্ভার থেকে রিজেক্ট হয়
        if msg.get("is_successful") is False:
            with self.lock:
                if self.active_trades_count > 0:
                    self.active_trades_count -= 1
            self.console.print(f"[bold red]✖ Trade Rejected: {msg.get('message', 'Unknown Error')}[/bold red]")
            self.status.update(f"[gray70]Waiting for next signal... Active Trades: {self.active_trades_count}/{self.max_concurrent_trades}[/gray70]")
            return

        # ৩. ডেটা এক্সট্রাক্ট করা (কখনো win থাকে, কখনো win_amount থাকে)
        win_status = msg.get("win")          
        win_amount = msg.get("win_amount")
        profit_amount = msg.get("profit_amount")
        amount = msg.get("amount", self.amount)

        result = None
        
        # প্রথমে 'win' টেক্সট চেক করা
        if win_status == "win":
            result = "WIN"
        elif win_status in ("loose", "loss"):
            result = "LOSS"
        elif win_status in ("equal", "draw"):
            result = "DRAW"
        # যদি 'win' টেক্সট না থাকে, তবে এমাউন্ট দিয়ে চেক করা
        elif win_amount is not None or profit_amount is not None:
            p_val = float(win_amount if win_amount is not None else profit_amount)
            if p_val > float(amount):
                result = "WIN"
            elif p_val == float(amount):
                result = "DRAW"
            else:
                result = "LOSS"
                
        # যদি কোনো ডেটাই ম্যাচ না করে (ফলস অ্যালার্ম), তবে ইগনোর করবে
        if result is None:
            return

        # ৪. প্রফিট/লস ক্যালকুলেশন
        if result == "WIN":
            result_text = "[bold green]WIN[/bold green]"
            p_val = float(profit_amount if profit_amount is not None else win_amount)
            # যদি রিটার্ন ভ্যালু ইনভেস্টের চেয়ে বেশি হয় (যেমন: 18.5), তবে ইনভেস্ট বাদ দিয়ে পিওর প্রফিট বের করব
            if p_val > float(amount):
                change = p_val - float(amount)
            else:
                change = p_val
            self.wins += 1
            
        elif result == "LOSS":
            result_text = "[bold red]LOSS[/bold red]"
            change = -float(amount)
            self.losses += 1
            
        else: # DRAW
            result_text = "[bold yellow]DRAW[/bold yellow]"
            change = 0.0

        self.pnl += change

        with self.lock:
            if self.active_trades_count > 0:
                self.active_trades_count -= 1

        # ৫. সুন্দর করে টেবিল আউটপুট দেওয়া
        table = Table(title="[bold]Trade Result[/bold]", show_header=True, header_style="bold magenta")
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
        self.status.update(f"[gray70]Waiting for next signal... Active Trades: {self.active_trades_count}/{self.max_concurrent_trades}[/gray70]")

    def on_error(self, ws, error):
        self.console.print(f"[bold red]✖ WebSocket Error: {error}[/bold red]")

    def on_close(self, ws, code, msg):
        self.status.stop()
        self.console.print("[bold red][-] WebSocket disconnected[/bold red]")

    def run(self):
        self.login()
        self.connect()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.status.stop()
            self.console.print("\n[bold yellow]Stopping bot...[/bold yellow]")
            if self.ws:
                self.ws.close()


if __name__ == "__main__":
    bot = IQOptionBot(CONFIG)
    bot.run()
