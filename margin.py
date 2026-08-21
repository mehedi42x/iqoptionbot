import json
import ssl
import time
import threading
import importlib
import os
import sys
import requests
import websocket
from datetime import datetime
from dotenv import dotenv_values

from rich.console import Console, Group
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich.align import Align
from rich.spinner import Spinner
from rich import box

CONFIG = dotenv_values(".env")
LOGIN_URL = "https://auth.iqoption.com/api/v2/login"
WS_URL = "wss://iqoption.com/echo/websocket"

ASSET_MAP = {
    1: "EUR/USD", 2: "EUR/GBP", 3: "GBP/USD", 4: "USD/JPY", 5: "AUD/USD",
    74: "GOLD (XAU/USD)", 81: "GOLD (XAU/USD)", 82: "SILVER", 83: "CRUDE OIL",
    200: "BTC/USD", 201: "ETH/USD",
}


class Bot:
    def __init__(self, cfg):
        # Use RLock (Reentrant Lock) to prevent threading deadlocks
        self.lock = threading.RLock()

        self.email = cfg.get("EMAIL", "")
        self.password = cfg.get("PASSWORD", "")
        self.acc_type = cfg.get("ACCOUNT_TYPE", "PRACTICE").upper()
        self.active_id = int(cfg.get("FX_ACTIVE_ID", 74))
        self.strategy_name = cfg.get("FX_STRATEGY", "demo_margin")

        raw_amount = float(cfg.get("FX_TRADE_AMOUNT", "1.0"))
        self.amount_str = str(int(raw_amount)) if raw_amount.is_integer() else str(raw_amount)
        self.leverage_str = str(cfg.get("FX_LEVERAGE", "800"))
        self.amount = float(self.amount_str)
        self.leverage = int(self.leverage_str)

        self.asset_name = ASSET_MAP.get(self.active_id, f"ASSET_{self.active_id}")

        # WebSocket & Balance State
        self.ssid = None
        self.ws = None
        self.req_id = 100
        self.user_id = None
        self.balance_id = None
        self.balance = 0.0
        self.initial_balance_loaded = False
        self.ws_connected = False  # UI-only connection indicator

        # Trade Pipeline State
        self.price = 0.0
        self.pos = None
        self.last_order_req_id = None
        self.pos_confirmed = False
        self.is_closing = False
        self.last_known_pnl = 0.0
        self.last_pnl_log_time = 0
        # UI-only: how often the live trade row is allowed to refresh.
        # (Does NOT affect strategy logic — self.pos["pnl"] itself is always
        # updated immediately in every branch; this only throttles redraw.)
        self.PNL_UI_THROTTLE = 0.1

        # close-confirmation retry tracking
        self.close_requested_time = None
        self.close_retry_count = 0

        # Stats
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0

        # ───────────────────── RICH UI STATE ─────────────────────
        self.console = Console()
        self.start_time = time.time()
        self.system_log = []          # permanent success/error/info lines
        self.status_msg = ""          # current transient (grey/spinner) line
        self.status_active = False
        self.trades = []              # one row per trade
        self.current_trade_idx = None

        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="log", size=9),
            Layout(name="trades"),
            Layout(name="footer", size=3),
        )

        self.live = Live(
            get_renderable=self._render,
            console=self.console,
            refresh_per_second=15,
            screen=False,
            transient=False,
        )
        self.live.start()

        self._load_strategy()

    # ───────────────────── CLEAN LOGGING HELPERS ─────────────────────
    def _now(self):
        return datetime.now().strftime("%H:%M:%S")

    def log_info(self, msg):
        self.status_active = False
        with self.lock:
            self.system_log.append(f"[grey50]{self._now()}[/] [bold cyan]ℹ[/]  {msg}")

    def log_running(self, msg):
        self.status_msg = msg
        self.status_active = True

    def log_success(self, msg):
        self.status_active = False
        with self.lock:
            self.system_log.append(f"[grey50]{self._now()}[/] [bold green]✔[/]  [green]{msg}[/]")

    def log_error(self, msg):
        self.status_active = False
        with self.lock:
            self.system_log.append(f"[grey50]{self._now()}[/] [bold red]✘[/]  [bold red]{msg}[/]")

    def _next_id(self):
        self.req_id += 1
        return str(self.req_id)

    # ───────────────────── RICH RENDER ─────────────────────
    def _fmt_uptime(self):
        s = int(time.time() - self.start_time)
        h, r = divmod(s, 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _build_header(self):
        dot = "[bold green]●[/]" if self.ws_connected else "[bold red]●[/]"
        bal_str = f"${self.balance:,.2f}" if self.initial_balance_loaded else "…"

        left = Text.from_markup(f" {dot} [bold white]LIVE[/]" if self.ws_connected else f" {dot} [bold grey58]OFFLINE[/]")
        title = Text("⚡ IQ OPTION AUTO-TRADER ⚡", style="bold magenta", justify="center")
        right = Text(f"⏱ {self._fmt_uptime()} ", style="grey62", justify="right")

        top_grid = Table.grid(expand=True)
        top_grid.add_column(justify="left", ratio=1)
        top_grid.add_column(justify="center", ratio=2)
        top_grid.add_column(justify="right", ratio=1)
        top_grid.add_row(left, title, right)

        info = Table.grid(expand=True, padding=(0, 2))
        info.add_column(justify="center")
        info.add_column(justify="center")
        info.add_column(justify="center")
        info.add_column(justify="center")
        info.add_row(
            f"[grey62]Asset[/] [bold white]{self.asset_name}[/]",
            f"[grey62]Account[/] [bold cyan]{self.acc_type}[/]",
            f"[grey62]Balance[/] [bold green]{bal_str}[/]",
            f"[grey62]Strategy[/] [bold yellow]{self.strategy_name}[/]",
        )

        return Panel(
            Group(top_grid, info),
            border_style="bright_magenta",
            box=box.HEAVY,
            padding=(0, 1),
        )

    def _build_log_panel(self):
        with self.lock:
            lines = list(self.system_log[-6:])

        body = [Text.from_markup(l) for l in lines] if lines else [Text("Waiting for events...", style="grey42 italic")]

        if self.status_active and self.status_msg:
            spinner = Spinner("dots", text=Text(f" {self.status_msg}", style="grey58 italic"), style="bold yellow")
            body.append(spinner)

        return Panel(
            Group(*body),
            title="[bold white]SYSTEM LOG[/]",
            title_align="left",
            border_style="grey37",
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def _build_trade_table(self):
        table = Table(
            box=box.HEAVY_HEAD,
            expand=True,
            border_style="grey37",
            header_style="bold white on grey19",
            title="[bold white]📈 TRADE HISTORY[/]",
            title_style="bold white",
            row_styles=["", "on grey11"],
        )
        table.add_column("#", justify="center", width=4)
        table.add_column("SIDE", justify="center", width=8)
        table.add_column("OPEN", justify="right")
        table.add_column("CLOSE", justify="right")
        table.add_column("PNL", justify="right")
        table.add_column("TOTAL PNL", justify="right")

        with self.lock:
            rows = list(self.trades[-14:])

        if not rows:
            table.add_row("[grey42]-[/]", "[grey42]-[/]", "-", "-", "-", "-")
        else:
            for t in rows:
                is_live = t["live"]
                side_style = "bold green" if t["side"] == "BUY" else "bold red"
                side_icon = "▲ BUY" if t["side"] == "BUY" else "▼ SELL"

                pnl = t["pnl"]
                pnl_style = "bold green" if pnl >= 0 else "bold red"
                pnl_str = f"{'+' if pnl >= 0 else '-'}${abs(pnl):.2f}"

                tot = t["total_pnl"]
                tot_style = "bold green" if tot >= 0 else "bold red"
                tot_str = f"{'+' if tot >= 0 else '-'}${abs(tot):.2f}"

                close_str = "[bold yellow]● LIVE[/]" if is_live else f"{t['close']:.4f}"
                num_str = f"[bold yellow]{t['num']}[/]" if is_live else f"[grey62]{t['num']}[/]"

                table.add_row(
                    num_str,
                    f"[{side_style}]{side_icon}[/]",
                    f"{t['open']:.4f}",
                    close_str,
                    f"[{pnl_style}]{pnl_str}[/]",
                    f"[{tot_style}]{tot_str}[/]",
                )
        return table

    def _build_footer(self):
        total_trades = self.wins + self.losses
        winrate = (self.wins / total_trades * 100) if total_trades > 0 else 0.0
        tot_style = "bold green" if self.total_pnl >= 0 else "bold red"
        tot_str = f"{'+' if self.total_pnl >= 0 else '-'}${abs(self.total_pnl):.2f}"

        grid = Table.grid(expand=True, padding=(0, 2))
        grid.add_column(justify="center")
        grid.add_column(justify="center")
        grid.add_column(justify="center")
        grid.add_column(justify="center")
        grid.add_column(justify="center")
        grid.add_row(
            f"[grey62]Trades[/] [bold white]{total_trades}[/]",
            f"[grey62]Wins[/] [bold green]{self.wins}[/]",
            f"[grey62]Losses[/] [bold red]{self.losses}[/]",
            f"[grey62]Win Rate[/] [bold cyan]{winrate:.1f}%[/]",
            f"[grey62]Session P/L[/] [{tot_style}]{tot_str}[/]",
        )
        return Panel(grid, border_style="bright_blue", box=box.HEAVY, padding=(0, 1))

    def _render(self):
        self.layout["header"].update(self._build_header())
        self.layout["log"].update(self._build_log_panel())
        self.layout["trades"].update(self._build_trade_table())
        self.layout["footer"].update(self._build_footer())
        return self.layout

    def _print_summary(self):
        total_trades = self.wins + self.losses
        winrate = (self.wins / total_trades * 100) if total_trades > 0 else 0.0
        pnl_style = "bold green" if self.total_pnl >= 0 else "bold red"

        grid = Table.grid(padding=(0, 3))
        grid.add_column(style="bold grey70")
        grid.add_column()
        grid.add_row("Total Trades:", str(total_trades))
        grid.add_row("Wins:", f"[bold green]{self.wins}[/]")
        grid.add_row("Losses:", f"[bold red]{self.losses}[/]")
        grid.add_row("Win Rate:", f"{winrate:.1f}%")
        grid.add_row("Total P/L:", f"[{pnl_style}]{'+' if self.total_pnl >= 0 else '-'}${abs(self.total_pnl):.2f}[/]")
        grid.add_row("Session Time:", self._fmt_uptime())

        self.console.print(
            Panel(grid, title="[bold yellow]📊 SESSION SUMMARY[/]", border_style="bright_yellow", box=box.DOUBLE)
        )

    # ───────────────────── TRADE ROW HELPERS ─────────────────────
    def _update_trade_live(self, close_price, pnl):
        with self.lock:
            if self.current_trade_idx is not None and self.current_trade_idx < len(self.trades):
                t = self.trades[self.current_trade_idx]
                t["close"] = close_price
                t["pnl"] = pnl
                t["total_pnl"] = self.total_pnl + pnl
                t["live"] = True

    def _finalize_trade_row(self, pnl, close_price):
        with self.lock:
            if self.current_trade_idx is not None and self.current_trade_idx < len(self.trades):
                t = self.trades[self.current_trade_idx]
                t["close"] = close_price
                t["pnl"] = pnl
                t["total_pnl"] = self.total_pnl
                t["live"] = False
            self.current_trade_idx = None

    # ───────────────────── STRATEGY LOAD ─────────────────────
    def _load_strategy(self):
        self.log_running(f"Loading strategy module: strategies/{self.strategy_name}.py...")
        try:
            m = importlib.import_module(f"strategies.{self.strategy_name}")
            self.strategy = m.Strategy()
            self.log_success(f"Strategy [{self.strategy_name}] loaded successfully.")
        except Exception as e:
            self.log_error(f"Failed to load strategy: {e}")
            self.live.stop()
            sys.exit(1)

    # ───────────────────── AUTHENTICATION & WEBSOCKET ─────────────────────
    def login(self):
        self.log_running("Authenticating user with IQ Option...")
        try:
            r = requests.post(
                LOGIN_URL,
                json={"identifier": self.email, "password": self.password},
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            r.raise_for_status()
            self.ssid = r.cookies.get("ssid") or r.json().get("ssid")
            if not self.ssid:
                raise ValueError("SSID token not found in response")
            self.log_success("Login Successful!")
        except Exception as e:
            self.log_error(f"Login Failed: {e}")
            self.live.stop()
            sys.exit(1)

    # ───────────────────── reconnect loop + ping keepalive ─────────────────────
    def connect(self):
        def _run():
            while True:
                self.log_running(f"Connecting to WebSocket: {WS_URL}...")
                self.ws = websocket.WebSocketApp(
                    WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_msg,
                    on_error=lambda ws, e: (self._set_disconnected(), self.log_error(f"WebSocket Error: {e}")),
                    on_close=lambda ws, c, m: (self._set_disconnected(), self.log_error("WebSocket Connection Closed."))
                )
                self.ws.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_NONE},
                    ping_interval=15,
                    ping_timeout=10
                )
                self._set_disconnected()
                self.log_error("Disconnected — reconnecting in 3s...")
                self.initial_balance_loaded = False
                time.sleep(3)

        threading.Thread(target=_run, daemon=True).start()
        threading.Thread(target=self._watchdog_loop, daemon=True).start()

    def _set_disconnected(self):
        self.ws_connected = False

    def _on_open(self, ws):
        self.ws_connected = True
        self.log_success("WebSocket Connected.")
        self.log_running("Sending SSID handshake...")
        ws.send(json.dumps({"name": "ssid", "msg": self.ssid, "request_id": self._next_id()}))
        time.sleep(0.5)
        self.log_running("Requesting Account Balances & Profile...")
        self._request_balance()
        self._subscribe_market_data()

    def _ws_ok(self):
        return self.ws and self.ws.sock and self.ws.sock.connected

    def _request_balance(self):
        if self._ws_ok():
            self.ws.send(json.dumps({
                "name": "sendMessage",
                "msg": {"name": "get-balances", "version": "1.0"},
                "request_id": self._next_id()
            }))

    def _request_open_positions(self):
        """Active polling to retrieve open marginal positions immediately"""
        if not self._ws_ok() or not self.balance_id:
            return
        # 1. Fetch Marginal Portfolio
        self.ws.send(json.dumps({
            "name": "sendMessage",
            "msg": {
                "name": "marginal-portfolio.get-user-positions",
                "version": "1.0",
                "body": {"user_balance_id": int(self.balance_id)}
            },
            "request_id": self._next_id()
        }))
        # 2. Fetch General Portfolio
        if self.user_id:
            self.ws.send(json.dumps({
                "name": "sendMessage",
                "msg": {
                    "name": "portfolio.get-positions",
                    "version": "2.0",
                    "body": {
                        "user_id": int(self.user_id),
                        "user_balance_id": int(self.balance_id),
                        "instrument_types": ["marginal-cfd"]
                    }
                },
                "request_id": self._next_id()
            }))

    def _subscribe_market_data(self):
        if not self._ws_ok():
            return
        self.ws.send(json.dumps({
            "name": "subscribeMessage",
            "msg": {
                "name": "candle-generated",
                "params": {"routingFilters": {"active_id": int(self.active_id), "size": 1}}
            },
            "request_id": self._next_id()
        }))
        self.log_running(f"Subscribing to real-time price feed for {self.asset_name} (Active ID: {self.active_id})...")

    def _subscribe_portfolio_streams(self):
        if not self._ws_ok() or not self.balance_id:
            return
        self.ws.send(json.dumps({
            "name": "subscribeMessage",
            "msg": {
                "name": "positions-state",
                "params": {"routingFilters": {"user_balance_id": int(self.balance_id)}}
            },
            "request_id": self._next_id()
        }))

    def _subscribe_position_updates(self, str_pos_id):
        if not self._ws_ok() or not str_pos_id:
            return
        self.ws.send(json.dumps({
            "name": "sendMessage",
            "request_id": self._next_id(),
            "local_time": int(time.time() * 1000) % 1000000,
            "msg": {
                "name": "subscribe-positions",
                "version": "1.0",
                "body": {"frequency": "frequent", "ids": [str_pos_id]}
            }
        }))

    # ───────────────────── watchdog: heartbeat status + retry/force-finalize ─────────────────────
    def _watchdog_loop(self):
        last_heartbeat = 0
        while True:
            time.sleep(1.5)

            if time.time() - last_heartbeat >= 5:
                last_heartbeat = time.time()
                if self.pos:
                    if self.is_closing:
                        waited = time.time() - (self.close_requested_time or time.time())
                        state = f"Closing position #{self.pos.get('id')}... ({waited:.1f}s elapsed, retry {self.close_retry_count})"
                    elif not self.pos_confirmed:
                        state = f"Awaiting numeric position ID (order #{self.pos.get('order_id')})..."
                    else:
                        state = f"Position #{self.pos.get('id')} open ({self.pos.get('dir')}) — monitoring live PnL..."
                    self.log_running(state)
                else:
                    self.log_running(f"Idle — scanning for entry signal on {self.asset_name} @ ${self.price:.4f}")

            if self._ws_ok():
                if not self.balance_id:
                    self._request_balance()
                elif self.pos:
                    self._request_open_positions()
                    self._request_balance()

                    if self.is_closing and self.close_requested_time:
                        elapsed = time.time() - self.close_requested_time
                        if elapsed > 8:
                            if self.close_retry_count < 3:
                                self.close_retry_count += 1
                                self.log_running(f"No close confirmation yet, retrying close request (attempt {self.close_retry_count})...")
                                self.is_closing = False
                                self._close()
                            else:
                                self.log_error("Close still not confirmed after retries — forcing finalize with last known PnL.")
                                self._finalize(forced_pnl=self.last_known_pnl)

    # ───────────────────── DEEP EXTRACTION ENGINE ─────────────────────
    def _deep_extract(self, obj):
        res = {
            "num_pos_id": None,
            "str_pos_id": None,
            "order_id": None,
            "entry_price": None,
            "pnl": None,
            "status": None
        }

        def crawl(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    k_lower = str(k).lower()

                    if k_lower == "raw_event":
                        continue

                    if k_lower in ("position_id", "external_id", "pos_id"):
                        if isinstance(v, int):
                            res["num_pos_id"] = v
                        elif isinstance(v, str):
                            if v.isdigit():
                                res["num_pos_id"] = int(v)
                            elif len(v) >= 20:
                                res["str_pos_id"] = v

                    if k_lower == "id":
                        if isinstance(v, int) and v > 10000000000:
                            if str(v).startswith("100"):
                                res["num_pos_id"] = v
                            elif str(v).startswith("101"):
                                res["order_id"] = v
                        elif isinstance(v, str) and len(v) >= 20:
                            res["str_pos_id"] = v

                    if k_lower in ("order_id", "order_ids"):
                        if isinstance(v, int):
                            res["order_id"] = v
                        elif isinstance(v, list) and len(v) > 0:
                            try:
                                res["order_id"] = int(v[0])
                            except:
                                pass

                    if k_lower in ("underlying_price", "open_underlying_price", "open_quote", "open_price"):
                        try:
                            res["entry_price"] = float(v)
                        except:
                            pass

                    if k_lower in ("pnl_net", "sell_profit", "pnl"):
                        try:
                            res["pnl"] = float(v)
                        except:
                            pass

                    if k_lower == "status" and isinstance(v, str):
                        res["status"] = v.lower()

                    crawl(v)
            elif isinstance(node, list):
                for item in node:
                    crawl(item)

        crawl(obj)
        return res

    def _bind_position_success(self, pos_id, entry_p=None, str_id=None):
        with self.lock:
            if not self.pos or self.pos_confirmed:
                return
            self.pos["num_pos_id"] = int(pos_id)
            self.pos["id"] = int(pos_id)
            if str_id:
                self.pos["str_pos_id"] = str_id
            if entry_p:
                self.pos["entry"] = float(entry_p)
            self.pos_confirmed = True
            self.log_success(f"Position Bound! Numeric ID: #{self.pos['id']} | Entry Price: ${self.pos['entry']:.4f}")
        if str_id:
            self._subscribe_position_updates(str_id)

    # ───────────────────── MESSAGE ROUTER ─────────────────────
    def _on_msg(self, ws, raw):
        try:
            d = json.loads(raw)
        except:
            return

        name = d.get("name", "")
        msg = d.get("msg", {})

        # ১. ব্যালেন্স ও ইউজার আইডি লোড
        if name in ("balances", "profile"):
            target_type = 4 if self.acc_type == "PRACTICE" else 1
            bals = msg if isinstance(msg, list) else msg.get("balances", [msg])
            for b in bals:
                if isinstance(b, dict) and b.get("type") == target_type:
                    self.balance_id = int(b.get("id"))
                    self.user_id = b.get("user_id", self.user_id)
                    self.balance = float(b.get("amount", b.get("equity", self.balance)))
                    if not self.initial_balance_loaded:
                        self.log_success(f"Account Balance: ${self.balance:,.2f} [Account: {self.acc_type} | Balance ID: {self.balance_id}]")
                        self.initial_balance_loaded = True
                        self._subscribe_portfolio_streams()
                        self.log_success(f"Bot Started — scanning for trading signals on {self.asset_name}...")
                        if self.pos:
                            self._request_open_positions()
                            if self.pos.get("str_pos_id"):
                                self._subscribe_position_updates(self.pos["str_pos_id"])
                    break
            return

        # ২. ধাপ ২: অর্ডার প্লেস কনফার্মেশন
        if name == "market-order-placed":
            order_id = msg.get("id") if isinstance(msg, dict) else None
            with self.lock:
                if self.pos and order_id:
                    self.pos["order_id"] = int(order_id)
                    self.log_success(f"Broker Accepted Order | Order ID: #{order_id}")
                    self.log_running("Awaiting Numeric Position ID from Broker...")

            threading.Thread(target=lambda: (time.sleep(0.2), self._request_open_positions()), daemon=True).start()
            return

        # ২-ক. real close confirmation push
        if name == "position-closed":
            with self.lock:
                if self.pos:
                    self.log_info("Position closed by broker.")
                    self._finalize(forced_pnl=self.pos.get("pnl", self.last_known_pnl))
            return

        # ৩. ইউনিভার্সাল পজিশন ইন্টারসেপশন (যেকোনো মেসেজ আসলে স্ক্যান হবে)
        if self.pos and not self.pos_confirmed and name != "candle-generated":
            ex = self._deep_extract(d)
            if ex["num_pos_id"]:
                self._bind_position_success(pos_id=ex["num_pos_id"], entry_p=ex["entry_price"], str_id=ex["str_pos_id"])

        # ৪-ক. positions-state: real per-position frequent live feed
        if name == "positions-state":
            positions_list = msg.get("positions", []) if isinstance(msg, dict) else []
            with self.lock:
                if self.pos:
                    target_str_id = self.pos.get("str_pos_id")
                    target_num_id = self.pos.get("num_pos_id")
                    match = None
                    for p in positions_list:
                        if not isinstance(p, dict):
                            continue
                        p_str_id = p.get("id")
                        if target_str_id and p_str_id == target_str_id:
                            match = p
                            break
                        if not target_str_id and target_num_id:
                            p_num_candidate = p.get("external_id") or p.get("position_id")
                            if p_num_candidate and int(p_num_candidate) == int(target_num_id):
                                match = p
                                if p_str_id:
                                    self.pos["str_pos_id"] = p_str_id
                                    self._subscribe_position_updates(p_str_id)
                                break

                    if match:
                        pnl_val = match.get("pnl_net", match.get("pnl", match.get("sell_profit")))
                        if pnl_val is not None:
                            self.pos["pnl"] = float(pnl_val)
                            self.last_known_pnl = float(pnl_val)
                        cp = match.get("current_price")
                        if cp is not None:
                            self.pos["curr"] = float(cp)

                        if self.pos_confirmed and (time.time() - self.last_pnl_log_time >= self.PNL_UI_THROTTLE) and not self.is_closing:
                            self._update_trade_live(self.pos["curr"], self.pos["pnl"])
                            self.last_pnl_log_time = time.time()
                    elif target_str_id and self.pos_confirmed and (time.time() - self.pos.get("open_time", 0) > 1.5):
                        self.log_info("Position no longer present in feed (Closed).")
                        self._finalize()
            return

        # ৪. লাইভ পজিশন ও PnL আপডেট
        if name in ("position-changed", "balance-changed", "positions", "marginal-portfolio.user-positions", "portfolio.positions"):
            ex = self._deep_extract(d)
            with self.lock:
                if self.pos:
                    if not self.pos_confirmed and ex["num_pos_id"]:
                        self._bind_position_success(pos_id=ex["num_pos_id"], entry_p=ex["entry_price"], str_id=ex["str_pos_id"])
                    elif self.pos_confirmed and not self.pos.get("str_pos_id") and ex["str_pos_id"]:
                        self.pos["str_pos_id"] = ex["str_pos_id"]
                        self._subscribe_position_updates(ex["str_pos_id"])

                    if ex["pnl"] is not None:
                        self.pos["pnl"] = ex["pnl"]
                        self.last_known_pnl = ex["pnl"]

                    curr_p = float(msg.get("current_price") or self.price) if isinstance(msg, dict) else self.price
                    self.pos["curr"] = curr_p

                    if self.pos_confirmed and (time.time() - self.last_pnl_log_time >= self.PNL_UI_THROTTLE) and not self.is_closing:
                        self._update_trade_live(curr_p, self.pos["pnl"])
                        self.last_pnl_log_time = time.time()

                    if ex["status"] == "closed":
                        self.log_info("Position closed status received from broker.")
                        self._finalize(forced_pnl=self.pos["pnl"], close_price=curr_p)
            return

        # ৫. ব্যাকআপ ব্যালেন্স চেঞ্জড হ্যান্ডলার
        if name == "balance-changed":
            target_type = 4 if self.acc_type == "PRACTICE" else 1
            if isinstance(msg, dict) and msg.get("type") == target_type:
                self.balance = float(msg.get("equity", msg.get("available", self.balance)))
                pps = msg.get("position_pnls")
                with self.lock:
                    if self.pos:
                        if pps and len(pps) > 0:
                            for p in pps:
                                p_id = int(p.get("id"))
                                pd = p.get("pnl_details", {})
                                entry_p = pd.get("open_underlying_price")
                                if not self.pos_confirmed:
                                    self._bind_position_success(pos_id=p_id, entry_p=entry_p)
                                pnl = float(p.get("pnl_net") or p.get("pnl") or 0.0)
                                self.pos["pnl"] = pnl
                                self.last_known_pnl = pnl
                                break
                        elif pps is not None and len(pps) == 0:
                            if self.pos_confirmed and (time.time() - self.pos.get("open_time", 0) > 1.5):
                                self.log_info("Position removed from portfolio list (Closed).")
                                self._finalize()
            return

        # ৬. প্রাইস টিক্স
        if name in ("candle-generated", "quote-generated"):
            if isinstance(msg, dict):
                aid = msg.get("active_id")
                if aid is None or int(aid) == self.active_id:
                    p = msg.get("close") or msg.get("price") or msg.get("ask") or msg.get("c")
                    if p:
                        self.price = float(p)
                        self._process_tick(d)
            return

    # ───────────────────── TICK & STRATEGY ─────────────────────
    def _process_tick(self, raw_data):
        if hasattr(self.strategy, "update_market_data"):
            try:
                self.strategy.update_market_data(self.price, raw_data)
            except:
                pass

        with self.lock:
            if self.pos:
                self.pos["curr"] = self.price
                self._check_close()
            else:
                self._check_entry()

    def _check_entry(self):
        if not self.balance_id or self.price <= 0 or self.pos:
            return

        sig = None
        if hasattr(self.strategy, "check_signal"):
            try:
                sig = self.strategy.check_signal(self.price)
            except TypeError:
                try:
                    sig = self.strategy.check_signal()
                except:
                    pass
            except:
                sig = None

        if sig and str(sig).upper() in ("BUY", "SELL"):
            self._place(str(sig).upper())

    def _check_close(self):
        if not self.pos or self.is_closing:
            return
        if hasattr(self.strategy, "check_close_signal"):
            try:
                should_close = self.strategy.check_close_signal(
                    position=self.pos,
                    current_price=self.price,
                    live_pnl=self.pos.get("pnl", 0.0)
                )
                if should_close:
                    self.log_info("Strategy triggered close signal.")
                    self._close()
            except:
                pass

    # ───────────────────── EXECUTION ─────────────────────
    def _place(self, direction):
        if self.pos or not self.balance_id or not self._ws_ok():
            return

        self.log_running(f"Strategy generated {direction} signal @ ${self.price:.4f}. Sending Order...")
        rid = self._next_id()
        self.last_order_req_id = str(rid)

        payload = {
            "name": "sendMessage",
            "request_id": rid,
            "local_time": int(time.time() * 1000) % 1000000,
            "msg": {
                "name": "marginal-cfd.place-market-order",
                "version": "1.0",
                "body": {
                    "side": direction.lower(),
                    "user_balance_id": int(self.balance_id),
                    "instrument_id": f"mcfd.{self.active_id}",
                    "instrument_active_id": int(self.active_id),
                    "is_margin_isolated": True,
                    "keep_position_open": False,
                    "leverage": self.leverage_str,
                    "margin": self.amount_str
                }
            }
        }
        self.ws.send(json.dumps(payload))

        now_ts = time.time()
        self.pos = {
            "order_id": None,
            "str_pos_id": None,
            "num_pos_id": None,
            "id": None,
            "time": datetime.now().strftime("%H:%M:%S"),
            "open_time": now_ts,
            "dir": direction,
            "amt": self.amount,
            "lev": self.leverage,
            "entry": self.price,
            "curr": self.price,
            "pnl": 0.0
        }
        self.pos_confirmed = False
        self.is_closing = False
        self.last_known_pnl = 0.0
        self.last_pnl_log_time = 0
        self.close_requested_time = None
        self.close_retry_count = 0

        with self.lock:
            self.trades.append({
                "num": len(self.trades) + 1,
                "side": direction,
                "open": self.price,
                "close": self.price,
                "pnl": 0.0,
                "total_pnl": self.total_pnl,
                "live": True
            })
            self.current_trade_idx = len(self.trades) - 1

        self.log_success(f"Market Order Sent to Server (Request ID: #{rid})")

    def _close(self):
        if not self.pos or self.is_closing:
            return

        pos_id = self.pos.get("num_pos_id") or self.pos.get("id")

        if not pos_id:
            self.log_running("Fetching active position ID from broker for close...")
            self._request_open_positions()
            time.sleep(0.3)
            pos_id = self.pos.get("num_pos_id") or self.pos.get("id")

        if not pos_id:
            self.log_error("Cannot close: Position ID not bound yet!")
            return

        self.is_closing = True
        self.close_requested_time = time.time()
        self.log_running(f"Sending request to close position #{pos_id}...")

        payload = {
            "name": "sendMessage",
            "request_id": self._next_id(),
            "local_time": int(time.time() * 1000) % 1000000,
            "msg": {
                "name": "marginal-cfd.close-position",
                "version": "1.0",
                "body": {"position_id": int(pos_id)}
            }
        }
        self.ws.send(json.dumps(payload))

    def _finalize(self, forced_pnl=None, close_price=None):
        with self.lock:
            if not self.pos:
                return

            pnl = forced_pnl if forced_pnl is not None else self.pos.get("pnl", self.last_known_pnl)
            c_price = close_price if close_price is not None else self.price

            self.total_pnl += pnl
            if pnl > 0:
                self.wins += 1
            elif pnl < 0:
                self.losses += 1

            self._finalize_trade_row(pnl, c_price)

            self.log_success(
                f"Trade Closed | Exit: ${c_price:.4f} | P/L: {'+$' if pnl >= 0 else '-$'}{abs(pnl):.2f} | "
                f"Total: {'+$' if self.total_pnl >= 0 else '-$'}{abs(self.total_pnl):.2f} ({self.wins}W/{self.losses}L)"
            )

            self.pos = None
            self.pos_confirmed = False
            self.is_closing = False
            self.close_requested_time = None
            self.close_retry_count = 0

        self._request_balance()

    def run(self):
        try:
            self.login()
            self.connect()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            self.live.stop()
            self._print_summary()
            if self.ws:
                self.ws.close()
        sys.exit(0)


if __name__ == "__main__":
    bot = Bot(CONFIG)
    bot.run()
