# IQ OPTION AUTO TRADING BOT
Modular, Short-Term, Strategy-Driven Auto Trading Bot in Python.

---

## 📁 Project Structure

```
IqOption/
│
├── .env
├── .env.example
├── bot.py
├── core.py
├── requirements.txt
├── README.md
│
├── Strategies/
│   ├── short_term_option_scalper.py
│   ├── short_term_option_reversal.py
│   ├── marginal_gold_scalper.py
│   ├── marginal_breakout_pro.py
│   └── marginal_momentum_reversal.py
│
├── api/
│   ├── auth.py
│   ├── binary.py
│   ├── digital.py
│   ├── Marginal.py
│   └── bliz.py
│
└── case/
    └── session_trades.json
```

---

## 🚀 Architecture & Data Flow

```
.env  ──>  bot.py  ──>  core.py  ──>  selected strategy
                             │
                             ▼
                         API Layer (auth / binary / digital / Marginal / bliz)
                             │
                             ▼
                   Trade Execution & Real-Time Monitoring
```

- **Strategy Layer**: Pure market analysis engine. No API calls, no login, no `.env` reading.
- **Core Layer (`core.py`)**: The central bridge. Validates configuration, requests market data on demand, validates signals, executes trades, monitors positions, and enforces risk management.
- **Bot Layer (`bot.py`)**: CLI application controller, configuration validator, lifecycle manager, and session summary generator.

---

## ⚙️ Configuration (`.env`)

Edit `.env` before running:

```env
# IQ Option credentials
IQ_EMAIL=your_email@example.com
IQ_PASSWORD=your_password

# Trading symbol (e.g. XAUUSD, EURUSD)
SYMBOL=XAUUSD

# Base trade amount in USD
AMOUNT=10

# Account Type: PRACTICE or REAL
ACCOUNT=PRACTICE

# Trade Type: BINARY | DIGITAL | FOREX | MARGINAL | BLIZ
TRADE_TYPE=FOREX

# Execution / Expiration Time (in minutes)
# BINARY: 1, 2, 3, 4, 5
# DIGITAL: 1, 5, 15
# BLIZ: 1, 2, 3, 4, 5
# FOREX / MARGINAL: leave blank
EXECUTION_TIME=

# Main candle timeframe (in minutes, default: 1)
TIMEFRAME=1

# Selected strategy:
# short_term_option_scalper
# short_term_option_reversal
# marginal_gold_scalper (or alias 'leverage')
# marginal_breakout_pro
# marginal_momentum_reversal
STRATEGY=marginal_gold_scalper

# Leverage (Only for FOREX / MARGINAL)
LEVERAGE=10

# Maximum simultaneously open trades
MAX_OPEN_TRADES=1
```

---

## 📊 Available Strategies

| Strategy | Compatible Trade Types | Target Instrument | Description |
|---|---|---|---|
| `short_term_option_scalper` | BINARY, DIGITAL, BLIZ | Any Currency / Gold | 1-min momentum micro-trend scalper using EMA(5/13) + RSI(7) + candle body geometry |
| `short_term_option_reversal` | BINARY, DIGITAL, BLIZ | Any Currency / Gold | 1-min wick rejection & Bollinger Band extreme mean-reversion |
| `marginal_gold_scalper` | FOREX, MARGINAL | XAUUSD / Forex | Trend alignment scalper with dynamic ATR-based Stop Loss and Take Profit |
| `marginal_breakout_pro` | FOREX, MARGINAL | XAUUSD / Forex | Donchian 20-candle High-Low breakout with dynamic risk/reward management |
| `marginal_momentum_reversal` | FOREX, MARGINAL | XAUUSD / Forex | MACD histogram reversal + Stochastic Oscillator oversold/overbought divergence |

---

## 🔧 Installation & Running

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure `.env`:**
   ```bash
   cp .env.example .env
   # Edit your IQ_EMAIL and IQ_PASSWORD in .env
   ```

3. **Run the Bot:**
   ```bash
   python3 bot.py
   ```

4. **Stop Gracefully:**
   Press `Ctrl+C` at any time to safely close positions, disconnect, and display the final performance summary.
