# IQ Option Bot

IQ Option binary-options research scripts, strategies, historical backtests এবং একটি FastAPI ভিত্তিক **Web Control Centre**।

## Web dashboard চালান

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn webapp.server:app --host 0.0.0.0 --port 8000 --reload
```

তারপর `http://localhost:8000` খুলুন। IQ Option email, password, PRACTICE/REAL mode এবং trade settings dashboard-এর **Account & Risk** page থেকে ইনপুট করুন—`.env` বা `IQOPTION_*` environment variable দরকার নেই।

## Render deploy

এই repo-তে Render Blueprint-এর জন্য `render.yaml`, production `requirements.txt`, `Procfile`, `.python-version`, health endpoint এবং password-protected dashboard login যোগ করা আছে।

1. Render-এ **New → Blueprint** নির্বাচন করুন এবং repository connect করুন।
2. শুধু `DASHBOARD_PASSWORD` secret দিন—এটি public dashboard access lock করে, এটি IQ Option password নয়।
3. Deploy হওয়ার পরে dashboard-এ login করে **Account & Risk** থেকে IQ Option account setup করুন।
4. Account settings restart-এর পরও রাখতে Render Persistent Disk attach করে `APP_DATA_DIR=/var/data` দিন।
5. Deploy-এর পরে `/health` endpoint দিয়ে service health দেখুন।

সম্পূর্ণ Render setup, storage, security notes ও strategy contract: **[webapp/README.md](webapp/README.md)**

> **Risk notice:** REAL IQ Option account ব্যবহার করলে বাস্তব টাকা ঝুঁকিতে পড়ে। PRACTICE mode ও backtest দিয়ে আগে যাচাই করুন।
