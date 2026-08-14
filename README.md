# IQ OPTION AUTO TRADING BOT

A production-grade, modular, pure-Python automated trading bot for **IQ Option**. Built without third-party wrappers, utilizing native HTTP authentication and direct WebSocket protocols. Supports Binary Options, Digital Options, Forex / Marginal CFD, and Blitz trading.

---

## 📑 Project Structure

```text
IqOption/
│
├── .env                              # Active environment configuration
├── .env.example                      # Safe template configuration
├── bot.py                            # Main CLI controller, validation & display
├── core.py                           # Central trading engine & orchestrator
├── requirements.txt                  # Python dependencies
├── README.md                         # Full documentation
│
├── Strategies/                       # Modular Trading Strategies
│   ├── short_term_option_scalper.py     # Binary/Digital/Bliz scalping
│   ├── short_term_option_reversal.py    # Binary/Digital/Bliz wick reversal
│   ├── marginal_gold_scalper.py         # Forex/Marginal XAUUSD 1m scalping
│   ├── marginal_breakout_pro.py         # Forex/Marginal Donchian breakout
│   └── marginal_momentum_reversal.py    # Forex/Marginal MACD + Stochastic reversal
│
├── api/                              # Direct Protocol Layers
│   ├── auth.py                          # HTTP login, SSID, WS session, balance manager
│   ├── binary.py                        # Binary/Turbo options protocol
│   ├── digital.py                       # Digital options protocol
│   ├── Marginal.py                      # Forex/Marginal CFD protocol with SL/TP
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

Copy `.env.example` to `.env` and configure your settings:
```bash
cp .env.example .env
```

### Configuration Parameters

| Variable | Description | Allowed Values / Examples |
| :--- | :--- | :--- |
| `IQ_EMAIL` | IQ Option Account Email | `your_email@domain.com` |
| `IQ_PASSWORD` | IQ Option Account Password | `your_secure_password` |
| `SYMBOL` | Trading Asset Symbol | `XAUUSD`, `EURUSD`, `GBPUSD`, `USDJPY` |
| `AMOUNT` | Base Investment Amount | `10`, `50`, `100` |
| `ACCOUNT` | Account Selection | `PRACTICE` (Demo) or `REAL` (Live) |
| `TRADE_TYPE` | Trading Instrument Type | `BINARY`, `DIGITAL`, `FOREX`, `MARGINAL`, `BLIZ` |
| `EXECUTION_TIME`| Expiration duration (min) | Binary/Bliz: `1,2,3,4,5` \| Digital: `1,5,15` \| Forex: `[blank]` |
| `TIMEFRAME` | Candle timeframe (min) | `1`, `5`, `15` |
| `STRATEGY` | Strategy module name | `marginal_gold_scalper`, `marginal_breakout_pro`, etc. |
| `LEVERAGE` | Multiplier for Forex/CFD | `10`, `20`, `50`, `100` |
| `STOP_LOSS` | SL distance from entry | `2.00`, `5.00` |
| `TAKE_PROFIT` | TP distance from entry | `4.00`, `10.00` |
| `MAX_OPEN_TRADES`| Max concurrent positions | `1`, `2`, `5` |

---

## 📈 Stop Loss & Take Profit Logic (Forex / Marginal)

For Forex and Marginal trading, strategies only output directional signals (`BUY` or `SELL`). `core.py` calculates the exact SL and TP prices using the distances configured in `.env`:

- **BUY (LONG)**:
  - $\text{SL} = \text{Entry Price} - \text{STOP\_LOSS}$
  - $\text{TP} = \text{Entry Price} + \text{TAKE\_PROFIT}$
- **SELL (SHORT)**:
  - $\text{SL} = \text{Entry Price} + \text{STOP\_LOSS}$
  - $\text{TP} = \text{Entry Price} - \text{TAKE\_PROFIT}$

---

## 🧠 Available Strategies

### 1. `short_term_option_scalper`
- **Instruments**: Binary, Digital, Bliz
- **Indicators**: EMA 9, EMA 21, RSI (14), Stochastic (14, 3)
- **Logic**: Identifies trend momentum alignments when EMA 9 crosses EMA 21, RSI is in the strong 52-70 zone, and Stochastic confirms continuation.

### 2. `short_term_option_reversal`
- **Instruments**: Binary, Digital, Bliz
- **Indicators**: Bollinger Bands (20, 2), RSI (14), Candlestick Wick Rejection
- **Logic**: Captures exhaustion pin bars and hammer/shooting star wicks rejecting outer Bollinger Bands in overbought/oversold territories.

### 3. `marginal_gold_scalper`
- **Instruments**: Forex / Marginal (XAUUSD / Gold)
- **Indicators**: EMA 20, EMA 50, EMA 200, MACD (12, 26, 9), ATR (14)
- **Logic**: Trend-following pullback strategy. Uses EMA 200 as master trend filter, waits for dynamic pullback to EMA 20/50 support/resistance, and triggers on MACD histogram inflection.

### 4. `marginal_breakout_pro`
- **Instruments**: Forex / Marginal (Gold / Currency pairs)
- **Indicators**: Donchian Channels (20-period High/Low), ATR Volatility Expansion
- **Logic**: Enters when price cleanly breaks 20-period highs or lows with strong candle body volume and ATR volatility expansion.

### 5. `marginal_momentum_reversal`
- **Instruments**: Forex / Marginal (Gold / Currency pairs)
- **Indicators**: MACD, Stochastic Oscillator, Price Action Engulfing
- **Logic**: Catches reversal turning points with Stochastic oversold/overbought crosses combined with MACD histogram divergence and structural reversal candles.

---

## 🏃 Execution

To launch the bot:
```bash
python3 bot.py
```

### Safety Note
Always test strategies first on `ACCOUNT=PRACTICE` before running with real funds (`ACCOUNT=REAL`).

---

## 💾 Persistent Case Storage

All runtime state and trading activity is logged persistently in the `case/` directory:
- **`case/trades.json`**: Complete trade history including trade ID, symbol, direction, entry/exit prices, SL/TP, timestamps, win/loss status, and net PnL.
- **`case/state.json`**: Current operational state, active open position IDs, connection status, and last processed signals.
- **`case/summary.json`**: Real-time aggregated statistics (Total Trades, Wins, Losses, Ties, Win Rate %, Starting Balance, Ending Balance, Total PnL).

---

## 🛑 Graceful Shutdown

Press `Ctrl+C` in your terminal at any time. The bot will:
1. Stop taking new signals.
2. Maintain connection to finish monitoring active positions.
3. Save final state to `case/state.json` and `case/summary.json`.
4. Close the WebSocket connection cleanly.
5. Print a comprehensive session summary table.
