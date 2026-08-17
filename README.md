# IQ OPTION AUTO TRADING BOT

A production-grade, modular, pure-Python automated trading bot for **IQ Option**. Built without third-party wrappers, utilizing native HTTP authentication and direct WebSocket protocols. Supports Binary Options, Digital Options, Forex / Marginal CFD, and Blitz trading.

---

## 📑 Project Structure

```text
IqOption/
│
├── .env                              # Active environment configuration
├── bot.py                            # Main CLI controller, validation & display
├── console.py                        # Clean terminal output (status line + event lines)
├── core.py                           # Central trading engine & orchestrator
├── requirements.txt                  # Python dependencies
├── README.md                         # Full documentation
│
├── Strategies/                       # Modular Trading Strategies (auto-discovered)
│   ├── __init__.py
│   ├── short_term_option_scalper.py     # Binary/Digital/Bliz scalping
│   ├── short_term_option_reversal.py    # Binary/Digital/Bliz wick reversal
│   ├── mtf_confluence_sniper.py         # 30s triple-timeframe confluence sniper
│   ├── bliz_ema_crossover.py            # Bliz 1m EMA 9/12 bias + 15s EMA 2/3 entry
│   ├── marginal_gold_scalper.py         # Forex/Marginal XAUUSD 1m scalping
│   ├── marginal_breakout_pro.py         # Forex/Marginal Donchian breakout
│   └── marginal_momentum_reversal.py    # Forex/Marginal MACD + Stochastic reversal
│
├── api/                              # Direct Protocol Layers
│   ├── __init__.py
│   ├── auth.py                          # HTTP login, SSID, WS session, balance manager
│   ├── binary.py                        # Binary/Turbo options protocol
│   ├── digital.py                       # Digital options protocol
│   ├── Marginal.py                      # Forex/Marginal CFD protocol (bot-managed SL/TP)
│   └── bliz.py                          # Bliz/Blitz fast options protocol
│
└── case/                             # Persistent Runtime Data
    ├── trades.json                      # Trade history ledger
    ├── state.json                       # State recovery & active position tracker
    └── summary.json                     # Cumulative trading statistics & win-rate
```

---

## 🚀 Installation & Prerequisites

- **Python Version**: Python `3.10` or newer (Tested on Python `3.12.3`)
- **System**: Linux, macOS, or Windows

### 1. Install Dependencies
Run in your terminal:
```bash
pip3 install -r requirements.txt
```
*(Dependencies: `python-dotenv`, `websocket-client`, `requests`, `pandas`, `numpy`)*

---

## ⚙️ Configuration (`.env`)

```bash
IQ_EMAIL=you@example.com
IQ_PASSWORD=your_password

SYMBOL=XAUUSD
AMOUNT=10

ACCOUNT=PRACTICE

MODE=FOREX

EXECUTION_TIME=60

TIMEFRAME=1

STRATEGY=marginal_gold_scalper

LEVERAGE=10

STOP_LOSS=2.00
TAKE_PROFIT=4.00

MAX_OPEN_TRADES=1
```

### Configuration Parameters

| Variable | Description | Allowed Values / Examples |
| :--- | :--- | :--- |
| `IQ_EMAIL` | IQ Option Account Email | `your_email@domain.com` |
| `IQ_PASSWORD` | IQ Option Account Password | `your_secure_password` |
| `SYMBOL` | Trading Asset Symbol | `XAUUSD`, `EURUSD`, `GBPUSD`, `USDJPY` |
| `AMOUNT` | Base Investment Amount | `10`, `50`, `100` |
| `ACCOUNT` | Account Selection | `PRACTICE` (Demo) or `REAL` (Live) |
| `MODE` | Which trading API the core uses | `BINARY`, `DIGITAL`, `FOREX`, `MARGINAL`, `BLIZ` |
| `EXECUTION_TIME` | Expiration duration (**seconds**) | `60` (1m), `120` (2m), `300` (5m), `900` (15m) |
| `BLIZ_ACTIVE_ID` | (optional) override Bliz active_id | e.g. `2436` — falls back to the built-in map |
| `TIMEFRAME` | Candle timeframe (minutes) | `1`, `5`, `15` |
| `STRATEGY` | Strategy module name (auto-discovered) | `marginal_gold_scalper`, `marginal_breakout_pro`, etc. |
| `LEVERAGE` | Multiplier for Forex/CFD | `10`, `20`, `50`, `100` |
| `STOP_LOSS` | SL distance from entry | `2.00`, `5.00` |
| `TAKE_PROFIT` | TP distance from entry | `4.00`, `10.00` |
| `MAX_OPEN_TRADES`| Max concurrent positions | `1`, `2`, `5` |

### MODE → API Mapping

The `MODE` value in `.env` decides which API module `core.py` uses:

| MODE | API Module | Trading Type |
| :--- | :--- | :--- |
| `BINARY` | `api/binary.py` | Binary / Turbo options |
| `DIGITAL` | `api/digital.py` | Digital options |
| `FOREX` | `api/Marginal.py` | Forex / Marginal CFD (continuous) |
| `MARGINAL` | `api/Marginal.py` | Forex / Marginal CFD (continuous) |
| `BLIZ` | `api/bliz.py` | Bliz / Blitz fast options |

---

## 🛡️ Stop Loss & Take Profit — Bot-Managed (NOT Broker)

This is the most important design decision of this bot:

> **The bot itself handles Stop Loss and Take Profit. SL/TP are NEVER sent to the broker.**
> The broker does **not** auto-close positions at SL/TP — the bot tracks the live market price and closes the trade itself.

### How it works (Forex / Marginal)

1. When a `BUY` / `SELL` signal fires, `core.py` calculates SL/TP prices locally from `.env` distances:
   - **BUY (LONG)**:
     - `SL = Entry Price - STOP_LOSS`
     - `TP = Entry Price + TAKE_PROFIT`
   - **SELL (SHORT)**:
     - `SL = Entry Price + STOP_LOSS`
     - `TP = Entry Price - TAKE_PROFIT`
2. `api/Marginal.py` opens the order **without** any SL/TP in the broker request.
3. Every engine cycle, `core.py` fetches the live market price (`_monitor_active_trades_market_price`):
   - If **price ≤ SL** (long) or **price ≥ SL** (short) → `STOP_LOSS` hit
   - If **price ≥ TP** (long) or **price ≤ TP** (short) → `TAKE_PROFIT` hit
4. On SL/TP hit, the bot calls `MarginalAPI.close_position()` (`marginal-forex.close-by-market`) to close the trade itself.

> For fixed-expiry modes (BINARY / DIGITAL / BLIZ) SL/TP does not apply — the option expires automatically.

---

## 🧩 Strategy System — Auto-Discovery

**Anyone can add a strategy by simply dropping a `.py` file into `Strategies/`.**

No registry, no hardcoded list. `bot.py` scans the `Strategies/` package at startup and imports every module that exports an `analyze(data) -> str` function.

### How to write a custom strategy

```python
# Strategies/my_custom_strategy.py
from typing import Any

def analyze(data: Any) -> str:
    """
    data = {
        "candles": [...],      # list of candle dicts
        "current_price": 1234.5,
        "symbol": "XAUUSD",
    }
    Return: 'BUY', 'SELL', or 'NO_SIGNAL'
    """
    candles = data["candles"]
    # ... your logic ...
    return "BUY"  # or "SELL" / "NO_SIGNAL"
```

Then set `STRATEGY=my_custom_strategy` in `.env`. The bot will detect it automatically.

### Built-in Strategies

1. **`short_term_option_scalper`** — Binary/Digital/Bliz · EMA 9/21, RSI(14), Stochastic(14,3)
2. **`short_term_option_reversal`** — Binary/Digital/Bliz · Bollinger(20,2), RSI(14), wick rejection
3. **`bliz_ema_crossover`** — Bliz · two-timeframe EMA crossover (see below)
4. **`mtf_confluence_sniper`** — Binary/Digital/Bliz · triple-timeframe confluence + hard filters (see below)
5. **`marginal_gold_scalper`** — Forex/Marginal · EMA 20/50/200, MACD, ATR(14)
6. **`marginal_breakout_pro`** — Forex/Marginal · Donchian(20), ATR volatility expansion
7. **`marginal_momentum_reversal`** — Forex/Marginal · MACD, Stochastic, engulfing

### `mtf_confluence_sniper` — Triple-Timeframe High-Accuracy Sniper (30s options)

The most advanced built-in strategy — built for **30-second Binary / Digital / Bliz
trades** with an accuracy-first, *quality-over-quantity* design. It is a heavy
**filter first, signal second** system: most candles produce `NO_SIGNAL`, and a
trade only fires when every layer agrees.

| Timeframe | Source | Role |
| :--- | :--- | :--- |
| **5 minutes** | resampled internally from the 1m candles | Macro trend — EMA 6/12 + close location |
| **1 minute** | `TIMEFRAME=1` | Trend (EMA 9/21 stacked + sloping) & regime filters |
| **15 seconds** | auto-fetched (`SIGNAL_TIMEFRAME = 15`) | Entry trigger — EMA 3/8 cross **or** pullback-reclaim |

**Hard filters — ALL 5 must pass, otherwise `NO_SIGNAL`:**

1. **Triple-timeframe alignment** — 5m, 1m, and 15s trend must all agree.
2. **ADX(14) ≥ 18** on 1m — market must be trending; ranging chop is skipped.
3. **ATR regime** — 1m ATR must sit between 0.65× and 2.20× its own recent
   median: dead markets *and* news-spike chaos are both skipped.
4. **Room to move** — price must not be trading straight into a recent 1m
   swing high/low (needs ≥ 0.5 ATR of room, unless it is breaking through).
5. **Healthy RSI zone** — BUY only at RSI 50–72, SELL only at 28–50 — never
   chases exhausted moves.

**Confirmation score — at least 3 of 5 required:**

- MACD(12,26,9) histogram rising/falling with the trade
- Stochastic(9,3) cross on 15s in trade direction, not exhausted
- Decisive signal candle (body ≥ 50% of range, close in the trend-side 35%)
- Previous 15s candle does not strongly oppose the trade
- Price on the right side of the 1m Bollinger midline without piercing the outer band

Recommended `.env`:

```bash
MODE=BLIZ            # or BINARY / DIGITAL
STRATEGY=mtf_confluence_sniper
TIMEFRAME=1
EXECUTION_TIME=30    # 30-second expiry
```

All thresholds (ADX minimum, ATR band, RSI zones, score requirement, etc.) are
plain constants at the top of `Strategies/mtf_confluence_sniper.py` — tune them
there if you want the strategy stricter or more active.

### `bliz_ema_crossover` — Dual-Timeframe EMA Crossover (Bliz)

Designed specifically for Bliz trading. It combines two candle timeframes:

| Timeframe | Indicator | Role |
| :--- | :--- | :--- |
| **1 minute** (`TIMEFRAME=1`) | EMA 9 vs EMA 12 | Sets the **direction bias** — `EMA 9 > EMA 12` → bullish (BUY side), `EMA 9 < EMA 12` → bearish (SELL side) |
| **15 seconds** (auto-fetched) | EMA 2 vs EMA 3 | Fires the **entry signal** — EMA 2 crossing **above** EMA 3 → BUY, crossing **below** → SELL |

Rules:

- The 15-second EMA 2/3 crossover is only acted on when it agrees with the
  1-minute bias (bull bias + up-cross → `BUY`, bear bias + down-cross → `SELL`).
- The engine automatically fetches the 15-second candles (`SIGNAL_TIMEFRAME = 15`)
  and deduplicates signals per 15-second candle, so each new signal candle is
  evaluated exactly once.
- `EXECUTION_TIME` controls the Bliz option expiry (default `15` seconds to match
  the signal timeframe — adjust to `30`/`60` if you prefer longer expiries).

Set `MODE=BLIZ` and `STRATEGY=bliz_ema_crossover` in `.env` (this is the default
shipping configuration).

---

## ⏱️ Execution Time (in Seconds)

`EXECUTION_TIME` is specified in **seconds**, not minutes:

| Seconds | Duration |
| :--- | :--- |
| `60` | 1 minute |
| `120` | 2 minutes |
| `300` | 5 minutes |
| `900` | 15 minutes |

For Forex / Marginal modes, `EXECUTION_TIME` is ignored (positions run until SL/TP is hit).

---

## 🚀 Bliz Trading Protocol

`api/bliz.py` implements the Bliz trading protocol exactly as specified:

| Step | Request | Response / Stream |
| :--- | :--- | :--- |
| 1. Server time sync | `sendMessage` → `{ name: "get-servertime", version: "1.0" }` | `servertime { msg: <unix_ts> }` |
| 2. Live quote subscribe | `subscribeMessage` → `{ name: "quote-generated", params: { routingFilters: { active_id } } }` | continuous `quote-generated { active_id, value, price, timestamp }` |
| 3. Trade placement | `sendMessage` → `{ name: "binary-options.open-option", version: "2.0", body: { user_balance_id, active_id, option_type_id: 12, direction, expiration_size, expired, price, profit_percent, refund_value, value } }` | `option { id, active_id, amount }` |
| 4. Balance update | — (auto) | `balance-changed { current_balance: { id, amount } }` |
| 5. Trade result | — (auto) | `option-closed { id, win, status, profit_amount, close_price }` |
| 6. Heartbeat | `ping { msg: <unix_ts> }` every 5s | `timeSync { msg: <unix_ts> }` |

Key points:

- **`value`** in the order payload always comes from the **live `quote-generated` subscription** — never calculated locally.
- **`expired`** = broker server time + `expiration_size` (seconds) — synced via `get-servertime` before each order.
- **`option_type_id: 12`** (Bliz), `profit_percent: 92`, `refund_value: 0`.
- Results arrive automatically as `option-closed`; no polling needed.
- If your broker uses a different `active_id` (e.g. `2436`), set `BLIZ_ACTIVE_ID` in `.env`.

---

## 🏃 Execution

To launch the bot:
```bash
python3 bot.py
```

### Terminal Output

`console.py` keeps the terminal clean and readable:

- **One floating status line** (with a spinner) always shows what the bot is doing
  right now — *"Reading .env configuration…"*, *"Connecting to IQ Option…"*,
  *"Fetching candles…"*, *"Analyzing signal…"*, *"Waiting for next candle…"*.
  When a task finishes, the line is replaced in-place by the next task.
- **Only essential events** are printed as permanent, colour-coded lines:
  - `✓` success — connected, trade opened, take-profit hit, win
  - `!` warning — stop-loss hit, loss, connection closed
  - `✗` error — login failed, order rejected, engine-loop error
  - `»` event — new trading signal
- Full debug detail (with tracebacks) is written to `case/bot.log` for
  troubleshooting, so it never clutters the terminal.
- Colours are disabled automatically when output is redirected or when
  `NO_COLOR=1` is set.

### Safety Note
Always test strategies first on `ACCOUNT=PRACTICE` before running with real funds (`ACCOUNT=REAL`).

---

## 💾 Persistent Case Storage

All runtime state and trading activity is logged persistently in the `case/` directory:
- **`case/trades.json`**: Complete trade history including trade ID, symbol, direction, entry/exit prices, SL/TP, close reason (`STOP_LOSS` / `TAKE_PROFIT`), timestamps, win/loss status, and net PnL.
- **`case/state.json`**: Current operational state, active open position IDs, connection status, and last processed signals.
- **`case/summary.json`**: Real-time aggregated statistics (Total Trades, Wins, Losses, Ties, Win Rate %, Starting Balance, Ending Balance, Total PnL).
- **`case/bot.log`**: Full debug log (the clean terminal shows only the essentials).

---

## 🛑 Graceful Shutdown

Press `Ctrl+C` in your terminal at any time. The bot will:
1. Stop taking new signals.
2. Maintain connection to finish monitoring active positions.
3. Save final state to `case/state.json` and `case/summary.json`.
4. Close the WebSocket connection cleanly.
5. Print a comprehensive session summary table.
