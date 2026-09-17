from __future__ import annotations

import asyncio
import json
import os
import time
import traceback

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import assets as assets_mod
from . import backtester
from .engine import EventBus, IQOptionEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
USER_STRATS = os.path.join(ROOT, "webapp", "user_strategies")
SETTINGS_FILE = os.path.join(ROOT, "webapp", "settings.json")
os.makedirs(USER_STRATS, exist_ok=True)

bus = EventBus()
engine = IQOptionEngine(bus)
app = FastAPI(title="IQ Option Bot Dashboard")


# ----------------------------------------------------------------------
# settings persistence (password is stored locally only, opt-in)
# ----------------------------------------------------------------------
def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_settings(data: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


@app.on_event("startup")
async def startup():
    s = load_settings()
    if s:
        engine.configure(**{k: v for k, v in s.items() if k != "remember"})
    # env fallback
    envf = os.path.join(ROOT, ".env")
    if not s and os.path.exists(envf):
        try:
            from dotenv import dotenv_values
            c = dotenv_values(envf)
            engine.configure(
                email=c.get("EMAIL"), password=c.get("PASSWORD"),
                account_type=(c.get("ACCOUNT_TYPE") or "PRACTICE"),
                active_id=int(c.get("ACTIVE_ID") or 1),
                amount=float(c.get("TRADE_AMOUNT") or 1),
                expiration=int(c.get("EXPIRATION_SECONDS") or 60),
                max_concurrent_trades=int(c.get("MAX_CONCURRENT_TRADES") or 1),
                active_name=assets_mod.name_for(int(c.get("ACTIVE_ID") or 1)),
            )
        except Exception:
            pass


# ----------------------------------------------------------------------
# models
# ----------------------------------------------------------------------
class AccountIn(BaseModel):
    email: str | None = None
    password: str | None = None
    account_type: str | None = None
    trade_type: str | None = None
    active_id: int | None = None
    amount: float | None = None
    expiration: int | None = None
    max_concurrent_trades: int | None = None
    remember: bool = True


class TradeIn(BaseModel):
    direction: str
    amount: float | None = None
    expiration: int | None = None


class AssetIn(BaseModel):
    active_id: int


class TFIn(BaseModel):
    timeframe: int


class AutoIn(BaseModel):
    enabled: bool


class StrategyIn(BaseModel):
    name: str | None = None
    code: str | None = None
    filename: str | None = None


class BacktestIn(BaseModel):
    strategy: str
    dataset: str
    expiration: int = 60
    payout: float = 0.80
    stake: float = 1.0
    start: str | None = None
    end: str | None = None


# ----------------------------------------------------------------------
# REST
# ----------------------------------------------------------------------
@app.get("/api/state")
def get_state():
    return engine.snapshot()


@app.get("/api/assets")
def get_assets():
    return assets_mod.ASSETS


@app.post("/api/account")
def set_account(body: AccountIn):
    data = body.model_dump(exclude_none=True)
    remember = data.pop("remember", True)
    if "active_id" in data:
        data["active_name"] = assets_mod.name_for(data["active_id"])
    engine.configure(**data)
    if data.get("account_type"):
        engine.switch_balance(data["account_type"])
    if remember:
        stored = load_settings()
        stored.update(data)
        save_settings(stored)
    return {"ok": True, "state": engine.snapshot()}


@app.post("/api/connect")
def connect():
    ok = engine.connect()
    return {"ok": ok}


@app.post("/api/disconnect")
def disconnect():
    engine.disconnect()
    return {"ok": True}


@app.post("/api/asset")
def set_asset(body: AssetIn):
    engine.switch_asset(body.active_id, assets_mod.name_for(body.active_id))
    return {"ok": True}


@app.post("/api/chart-timeframe")
def set_tf(body: TFIn):
    engine.set_chart_timeframe(body.timeframe)
    return {"ok": True}


@app.post("/api/trade")
def trade(body: TradeIn):
    ok = engine.place_trade(body.direction, body.amount, body.expiration, source="manual")
    return {"ok": ok}


@app.post("/api/auto")
def auto(body: AutoIn):
    return {"ok": engine.set_auto(body.enabled)}


@app.post("/api/reset-stats")
def reset_stats():
    engine.reset_stats()
    return {"ok": True}


@app.get("/api/strategies")
def list_strategies():
    out = []
    for f in sorted(os.listdir(os.path.join(ROOT, "strategies"))):
        if f.endswith(".py") and not f.startswith("__"):
            out.append({"id": f[:-3], "name": f[:-3], "builtin": True})
    for f in sorted(os.listdir(USER_STRATS)):
        if f.endswith(".py"):
            out.append({"id": f"user:{f}", "name": f[:-3], "builtin": False})
    return out


@app.get("/api/strategy-source")
def strategy_source(id: str):
    path = _strategy_path(id)
    if not path or not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    with open(path) as f:
        return {"id": id, "code": f.read()}


def _strategy_path(sid: str) -> str | None:
    if sid.startswith("user:"):
        return os.path.join(USER_STRATS, os.path.basename(sid[5:]))
    return os.path.join(ROOT, "strategies", os.path.basename(sid) + ".py")


@app.post("/api/strategy/save")
def save_strategy(body: StrategyIn):
    if not body.code or not body.filename:
        return JSONResponse({"error": "filename and code required"}, status_code=400)
    fname = os.path.basename(body.filename)
    if not fname.endswith(".py"):
        fname += ".py"
    path = os.path.join(USER_STRATS, fname)
    with open(path, "w") as f:
        f.write(body.code)
    # validate
    try:
        from .engine import StrategyRunner
        r = StrategyRunner(source_path=path)
        tfs = r.required_timeframes()
    except Exception as e:
        return JSONResponse(
            {"error": f"Strategy failed to load: {e}", "trace": traceback.format_exc(limit=3)},
            status_code=400,
        )
    return {"ok": True, "id": f"user:{fname}", "timeframes": tfs}


@app.post("/api/strategy/load")
def load_strategy(body: StrategyIn):
    if not body.name:
        return JSONResponse({"error": "name required"}, status_code=400)
    try:
        if body.name.startswith("user:"):
            path = _strategy_path(body.name)
            tfs = engine.load_strategy(source_path=path, label=os.path.basename(path)[:-3])
        else:
            tfs = engine.load_strategy(module_name=body.name, label=body.name)
        return {"ok": True, "timeframes": tfs}
    except Exception as e:
        engine.log(f"Strategy load failed: {e}", "error")
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/datasets")
def datasets():
    return backtester.list_datasets(ROOT)


@app.post("/api/backtest")
def run_backtest(body: BacktestIn):
    ds = os.path.join(ROOT, os.path.basename(body.dataset))
    if not os.path.exists(ds):
        return JSONResponse({"error": "dataset not found"}, status_code=404)
    tf = 60
    for part in os.path.basename(ds).replace(".csv", "").split("_"):
        if part.endswith("s") and part[:-1].isdigit():
            tf = int(part[:-1])
    try:
        kw = dict(dataset_path=ds, expiration=body.expiration, payout=body.payout,
                  stake=body.stake, start=body.start, end=body.end, timeframe=tf,
                  label=body.strategy.replace("user:", ""))
        if body.strategy.startswith("user:"):
            res = backtester.run(strategy_path=_strategy_path(body.strategy), **kw)
        else:
            res = backtester.run(strategy_module=body.strategy, **kw)
        return res
    except Exception as e:
        return JSONResponse(
            {"error": str(e), "trace": traceback.format_exc(limit=3)}, status_code=400
        )


# ----------------------------------------------------------------------
# WebSocket stream to browser
# ----------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q = bus.subscribe()
    try:
        await ws.send_json({"type": "state", "ts": int(time.time() * 1000),
                            "data": engine.snapshot()})
        for evt in bus.history()[-80:]:
            await ws.send_json(evt)
        tf = engine.chart_timeframe
        if engine.candles.get(tf):
            await ws.send_json({"type": "candles_snapshot", "ts": int(time.time() * 1000),
                                "data": {"timeframe": tf, "active_name": engine.active_name,
                                         "candles": engine.candles[tf][-300:],
                                         "markers": engine.markers[-100:]}})
        while True:
            sent = False
            while q:
                await ws.send_json(q.popleft())
                sent = True
            if not sent:
                await asyncio.sleep(0.15)
            else:
                await asyncio.sleep(0.01)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)


# ----------------------------------------------------------------------
# static
# ----------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
