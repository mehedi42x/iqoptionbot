# IQ Option Bot Web Control Centre

FastAPI ভিত্তিক IQ Option trading dashboard। ব্রাউজার থেকে account setup, live candles, manual/automatic trading, strategy management এবং local candle-data backtest চালানো যায়। Broker credentials server-side engine-এ থাকে; browser সরাসরি IQ Option-এর সঙ্গে যোগাযোগ করে না।

> **Risk notice:** Binary/digital options উচ্চ-ঝুঁকির। প্রথমে **PRACTICE** account ও backtest দিয়ে যাচাই করুন। REAL mode-এ order দিলে বাস্তব টাকা ব্যবহার হবে।

## Local run

Python 3.11 ব্যবহার করার পরামর্শ দেওয়া হচ্ছে:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn webapp.server:app --host 0.0.0.0 --port 8000 --reload
```

তারপর `http://localhost:8000` খুলুন। Local development-এ `DASHBOARD_PASSWORD` unset থাকলে login gateway দেখাবে না; public deployment-এ এটি অবশ্যই সেট করুন।

## Render deploy

Repository-র `render.yaml`, `Procfile`, `.python-version` এবং `requirements.txt` Render web service-এর জন্য প্রস্তুত। Render-এ Blueprint হিসেবে repository connect করুন এবং `DASHBOARD_PASSWORD` secret দিন। Deploy হওয়ার পরে `/health` endpoint দিয়ে service health দেখা যাবে।

Account settings ও custom strategies restart-এর পরেও রাখতে চাইলে Persistent Disk mount করে `APP_DATA_DIR=/var/data` দিন। সম্পূর্ণ deployment, storage, security notes এবং strategy contract-এর জন্য [`webapp/README.md`](webapp/README.md) দেখুন।

## Repository layout

- `webapp/` — FastAPI server, live trading engine, backtest runner এবং browser UI
- `strategies/` — dashboard-এ load করা built-in strategies
- `candles_asset_*_30s_30d.csv` / `candles_asset_*_60s_30d.csv` — Backtest tab-এর local datasets

> `settings.json` এবং user strategies runtime-এ `APP_DATA_DIR`-এর অধীনে তৈরি হয়; এগুলো version control-এ রাখা হয় না।
