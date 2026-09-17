# IQ Option Bot — Web Control Center

আপনার `bot.py` এর ঠিক একই WebSocket প্রোটোকল ব্যবহার করে বানানো একটি ওয়েব ড্যাশবোর্ড।

## চালানোর নিয়ম

```bash
python3 -m venv .venv
.venv/bin/pip install fastapi "uvicorn[standard]" websocket-client requests python-dotenv
.venv/bin/python -m uvicorn webapp.server:app --host 0.0.0.0 --port 8000
```

ব্রাউজারে খুলুন: http://localhost:8000

## ট্যাব গুলো

| ট্যাব | কাজ |
|---|---|
| **Dashboard** | ব্যালেন্স, সেশন P/L, উইন রেট, ওপেন পজিশন, লাইভ ক্যান্ডেল চার্ট (ট্রেড মার্কার সহ), লাইভ লগ, ট্রেড হিস্ট্রি |
| **Trading** | কারেন্সি পেয়ার সিলেক্ট, ম্যানুয়াল CALL/PUT, অটো-ট্রেডিং টগল, ম্যাক্স কনকারেন্ট ট্রেড, ট্রেড টাইপ |
| **Strategy** | পাইথন স্ট্রাটেজি এডিটর — লিখুন, সেভ + ভ্যালিডেট, লাইভে Activate |
| **Backtest** | স্ট্রাটেজি + ডেটাসেট + ডেট রেঞ্জ + পে-আউট দিয়ে ব্যাকটেস্ট, ইকুইটি কার্ভ + আওয়ারলি রিপোর্ট |
| **Account Setup** | ইমেইল, পাসওয়ার্ড, PRACTICE/REAL, ট্রেড আইডি (Turbo / Binary / Digital), ডিফল্ট স্টেক ও এক্সপায়ারি |

## বট যে WebSocket মেসেজ গুলো ব্যবহার করে (bot.py এর মতই হুবহু)

- `POST https://auth.iqoption.com/api/v2/login` → SSID
- `wss://iqoption.com/echo/websocket` (ping_interval=30, ping_timeout=10, auto-reconnect watchdog)
- `{"name":"ssid"}` → সেশন অথেন্টিকেশন
- `{"name":"sendMessage","msg":{"name":"get-balances"}}` → ব্যালেন্স (type 4 = practice, 1 = real)
- `{"name":"subscribeMessage","msg":{"name":"candle-generated","params":{"routingFilters":{"active_id":X,"size":T}}}}` → লাইভ ক্যান্ডেল
- `{"name":"sendMessage","msg":{"name":"get-candles","version":"2.0"}}` → হিস্টোরিকাল ক্যান্ডেল (চার্ট ওয়ার্ম-আপ)
- `{"name":"sendMessage","msg":{"name":"binary-options.open-option","version":"2.0"}}` → ট্রেড ওপেন
- `option-closed` / `portfolio.position-changed` → রেজাল্ট (WIN / LOSS / DRAW)

## স্ট্রাটেজি কন্ট্রাক্ট

```python
class Strategy:
    required_timeframes = [60]        # বট এই টাইমফ্রেম গুলো subscribe করবে

    def update_candle(self, timeframe, candle):
        # candle = {"timestamp","open","high","low","close","volume"}
        return "CALL"   # BUY সিগন্যাল
        # return "PUT"  # SELL সিগন্যাল
        # return None   # কোনো ট্রেড না

    def get_status(self):   # optional — UI তে দেখাবে
        return {"no_trade_reason": "..."}

    def reset(self):        # optional — asset বদলালে কল হয়
        pass
```

`strategies/` ফোল্ডারের সব বিল্ট-ইন স্ট্রাটেজি (emacombo, maxfade_v*, mtf_*, multisignal_*, sniper_v1) এখানেই লোড হয়।
আপনার নিজের লেখা স্ট্রাটেজি `webapp/user_strategies/` এ সেভ হয়।

## নোট

- `webapp/settings.json` এ ইমেইল/পাসওয়ার্ড লোকালি সেভ হয় (gitignore করা আছে)। না চাইলে "Remember" আনচেক করুন।
- REAL অ্যাকাউন্টে আসল টাকা যায় — আগে PRACTICE এ টেস্ট করুন।
- Digital options এর instrument-id ফরম্যাট IQ Option এর সাইডে বদলাতে পারে; Turbo/Binary পাথটি `bot.py` থেকে সরাসরি নেওয়া ও যাচাই করা।
