# IQ Bot — Web Control Centre

IQ Option binary-options bot-এর জন্য FastAPI ভিত্তিক private web dashboard। IQ Option account email, password, account mode এবং trade settings **শুধু web app-এর Account & Risk screen থেকে** দেওয়া হয়। Broker credentials পড়ার জন্য `.env` বা `IQOPTION_*` environment variable ব্যবহার করা হয় না।

> **ঝুঁকির সতর্কতা:** Binary/digital options উচ্চ-ঝুঁকির। প্রথমে **PRACTICE** account ও backtest দিয়ে যাচাই করুন। REAL mode-এ order দিলে বাস্তব টাকা ব্যবহার হবে।

## Render-এ deploy (প্রস্তাবিত)

Repository root-এ থাকা [`render.yaml`](../render.yaml) এবং [`requirements.txt`](../requirements.txt) deploy-এর জন্য প্রস্তুত।

1. কোডটি GitHub-এ push করুন এবং Render-এ **New → Blueprint** নির্বাচন করুন।
2. এই repository connect করুন। Render স্বয়ংক্রিয়ভাবে `render.yaml` পড়বে।
3. Render service-এর **Environment** পেজে শুধু এই access secret-টি দিন:

   | Variable | প্রয়োজন | কাজ |
   |---|---:|---|
   | `DASHBOARD_PASSWORD` | **অবশ্যই** | Public Render URL খোলার login password। এটি IQ Option password নয়। |

4. Deploy শেষ হলে service URL খুলুন, `DASHBOARD_PASSWORD` দিয়ে login করুন।
5. **Account & Risk → IQ Option Credentials**-এ আপনার IQ Option email, password, account mode, `ACTIVE_ID`, trade amount এবং expiration নিজে ইনপুট করে **Save** করুন। এখানে কোনো account বা market ID আগে থেকে দেওয়া থাকে না। তারপর Sidebar থেকে **Connect** করুন।

Render health check endpoint হলো `/health`। Start command:

```bash
uvicorn webapp.server:app --host 0.0.0.0 --port $PORT --proxy-headers
```

### Account settings কোথায় থাকে?

Account screen-এ **Remember settings on this server** checked থাকলে credentials ও default settings server-side `settings.json`-এ save হয় এবং file permission owner-only করার চেষ্টা করা হয়। Render-এর HTTPS connection-এ browser থেকে data যায়; settings file নিজে encrypted নয়, তাই অবশ্যই private persistent disk ব্যবহার করুন। এগুলো Git-এ যায় না, API response-এ password ফেরত আসে না এবং frontend source-এ লেখা থাকে না।

Render-এর default filesystem restart/redeploy-এ মুছে যেতে পারে। তাই account settings ও custom strategy restart-এর পরেও রাখতে চাইলে একটি Render Persistent Disk mount করুন, যেমন `/var/data`, এবং এই **non-secret** environment variable দিন:

```text
APP_DATA_DIR=/var/data
```

এতে `settings.json` এবং `user_strategies/` ওই disk-এ থাকবে। Persistent disk ব্যবহার না করলে deployment restart হওয়ার পরে Account & Risk screen থেকে password আবার দিতে হবে।

## Local run

Python 3.11 ব্যবহার করার পরামর্শ দেওয়া হচ্ছে।

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn webapp.server:app --host 0.0.0.0 --port 8000 --reload
```

তারপর `http://localhost:8000` খুলুন। Local development-এ `DASHBOARD_PASSWORD` unset থাকলে login screen দেখাবে না; public deployment-এ এটি খালি রাখবেন না।

## নিরাপত্তা

- Render URL public হতে পারে; তাই `DASHBOARD_PASSWORD` ছাড়া deploy করবেন না। এটি dashboard API, live order controls এবং custom Python strategy editor-কে সুরক্ষিত রাখে।
- IQ Option email/password Account & Risk screen ছাড়া অন্য কোথাও সেট করার দরকার নেই। `.env`/Render environment-এ brokerage secret রাখা হয় না।
- “Remember settings” বন্ধ করলে server-side `settings.json` মুছে দেওয়া হয়; current process চলা পর্যন্ত settings কার্যকর থাকে।
- Dashboard session httpOnly cookie দিয়ে চলে এবং 8 ঘণ্টা পরে শেষ হয়। `DASHBOARD_SESSION_TTL` দিয়ে seconds-এ সময় পরিবর্তন করা যায়।
- App একই origin ব্যবহার করে। Browser শুধু নিজের Render URL-তে request করে; IQ Option login ও WebSocket traffic server-side থাকে।

## Dashboard sections

| Section | কাজ |
|---|---|
| **Dashboard** | Balance, session P/L, win rate, open orders, live candle chart, execution log এবং trade journal। |
| **Trading** | Asset, stake, expiry select করে manual CALL/PUT; validated strategy দিয়ে auto-trading চালু করা যায়। |
| **Strategy Lab** | Python strategy edit, validate ও live signal-এর জন্য activate। |
| **Backtest** | Local CSV dataset-এ fixed stake/payout দিয়ে strategy result, equity curve, hourly stats দেখা যায়। |
| **Account & Risk** | IQ Option account, account mode, user-supplied `ACTIVE_ID` এবং risk guardrails configure। |

## Strategy contract

কোনো built-in strategy নেই। Script Lab-এ তৈরি ও validate করা strategy `APP_DATA_DIR/user_strategies/`-এ (default: `webapp/user_strategies/`) save হয় এবং সেখান থেকেই live/backtest-এর জন্য load হয়। প্রতিটি strategy-তে `Strategy` class থাকতে হবে:

```python
class Strategy:
    required_timeframes = [60]

    def update_candle(self, timeframe, candle):
        # candle = {"timestamp", "open", "high", "low", "close", "volume"}
        return "CALL"  # BUY signal
        # return "PUT" # SELL signal
        # return None  # no trade

    def get_status(self):  # optional
        return {"no_trade_reason": "..."}

    def reset(self):       # optional; called after an asset change
        pass
```

## API health check

```bash
curl https://YOUR-SERVICE.onrender.com/health
# {"ok":true,"service":"iq-option-bot","connected":false}
```
