"""FastAPI application for the IQ Option Bot control centre.

The dashboard is intentionally same-origin: the browser only ever talks to this
process, while IQ Option credentials and WebSocket traffic stay on the server.
Set ``DASHBOARD_PASSWORD`` in production to protect this trading console.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import backtester
from .engine import EventBus, IQOptionEngine, StrategyRunner

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(ROOT / "webapp"))).expanduser()
USER_STRATS = DATA_DIR / "user_strategies"
SETTINGS_FILE = DATA_DIR / "settings.json"
USER_STRATS.mkdir(parents=True, exist_ok=True)

SESSION_COOKIE = "iqbot_dashboard_session"
SESSION_TTL_SECONDS = max(300, int(os.getenv("DASHBOARD_SESSION_TTL", "28800")))
_sessions: dict[str, float] = {}
_sessions_lock = threading.Lock()

bus = EventBus()
engine = IQOptionEngine(bus)
app = FastAPI(title="IQ Option Bot Dashboard", docs_url=None, redoc_url=None)


# ----------------------------------------------------------------------
# Deployment security
# ----------------------------------------------------------------------
def _dashboard_password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "").strip()


def _auth_required() -> bool:
    # Render blueprint sets REQUIRE_DASHBOARD_PASSWORD=true, so an omitted
    # secret fails closed instead of accidentally publishing trade controls.
    force_auth = os.getenv("REQUIRE_DASHBOARD_PASSWORD", "").strip().lower()
    return bool(_dashboard_password()) or force_auth in {"1", "true", "yes", "on"}


def _is_valid_session(token: str | None) -> bool:
    if not _auth_required():
        return True
    if not token:
        return False
    now = time.time()
    with _sessions_lock:
        # Prune expired entries while we are already holding the lock.
        for key, expiry in list(_sessions.items()):
            if expiry <= now:
                _sessions.pop(key, None)
        return _sessions.get(token, 0) > now


def _create_session() -> str:
    token = secrets.token_urlsafe(32)
    with _sessions_lock:
        _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token


def _forget_session(token: str | None) -> None:
    if token:
        with _sessions_lock:
            _sessions.pop(token, None)


def _is_https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0] == "https"


@app.middleware("http")
async def dashboard_security(request: Request, call_next):
    """Require a password-backed session for app and API routes when enabled."""
    path = request.url.path
    public_paths = {"/health", "/login", "/api/session", "/api/session/logout"}
    is_public = path in public_paths or path.startswith("/static/")

    if _auth_required() and not is_public and not _is_valid_session(request.cookies.get(SESSION_COOKIE)):
        if path.startswith("/api/"):
            response = JSONResponse({"error": "Dashboard session expired. Please sign in again."}, status_code=401)
        else:
            response = RedirectResponse("/login", status_code=303)
    else:
        response = await call_next(request)

    # These headers are safe for a same-origin dashboard and reduce accidental
    # embedding/cross-origin execution when the Render URL is shared.
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


class SessionIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


@app.get("/login")
def login_page(request: Request):
    if not _auth_required():
        return RedirectResponse("/", status_code=303)
    if _is_valid_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC / "login.html")


@app.post("/api/session")
def create_session(body: SessionIn, request: Request, response: Response):
    password = _dashboard_password()
    if not password:
        raise HTTPException(status_code=503, detail="Dashboard password is required but has not been configured by the service owner.")
    if not hmac.compare_digest(body.password, password):
        raise HTTPException(status_code=401, detail="Incorrect access password.")

    token = _create_session()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_is_https(request),
        samesite="lax",
        path="/",
    )
    return {"ok": True, "expires_in": SESSION_TTL_SECONDS}


@app.post("/api/session/logout")
def destroy_session(request: Request, response: Response):
    _forget_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/health")
def health():
    """Unauthenticated health check for Render."""
    return {"ok": True, "service": "iq-option-bot", "connected": engine.is_connected}


# ----------------------------------------------------------------------
# Settings persistence (opt-in, local filesystem only)
# ----------------------------------------------------------------------
PERSISTED_SETTING_KEYS = {
    "email", "password", "account_type", "active_id", "active_name",
    "amount", "expiration", "max_concurrent_trades",
}


def load_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with SETTINGS_FILE.open(encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        return {key: raw[key] for key in PERSISTED_SETTING_KEYS if key in raw}
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(data: dict[str, Any]) -> None:
    """Atomically persist opted-in settings with owner-only permissions where possible."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = {key: data[key] for key in PERSISTED_SETTING_KEYS if key in data}
    fd, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=DATA_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, SETTINGS_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear_settings() -> None:
    try:
        SETTINGS_FILE.unlink()
    except FileNotFoundError:
        pass


@app.on_event("startup")
async def startup():
    # Broker credentials are intentionally supplied through the Account & Risk
    # screen. We never read IQ Option credentials from .env or Render env vars.
    settings = load_settings()
    if settings:
        try:
            engine.configure(**settings)
        except (TypeError, ValueError):
            engine.log("Saved settings could not be loaded.", "warn")
    if _dashboard_password():
        engine.log("Dashboard access protection is enabled.", "success")
    elif _auth_required():
        engine.log("Dashboard password is required but not configured.", "error")
    else:
        engine.log("Dashboard is public. Set DASHBOARD_PASSWORD before deploying.", "warn")


@app.on_event("shutdown")
async def shutdown():
    engine.disconnect()


# ----------------------------------------------------------------------
# Input models
# ----------------------------------------------------------------------
class AccountIn(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, max_length=512)
    account_type: str | None = None
    active_id: int | None = Field(default=None, gt=0)
    active_name: str | None = Field(default=None, max_length=100)
    amount: float | None = Field(default=None, gt=0, le=1_000_000)
    expiration: int | None = Field(default=None, ge=5, le=86_400)
    max_concurrent_trades: int | None = Field(default=None, ge=1, le=10)
    remember: bool = False


class TradeIn(BaseModel):
    direction: str
    amount: float | None = Field(default=None, gt=0, le=1_000_000)
    expiration: int | None = Field(default=None, ge=5, le=86_400)


class AssetIn(BaseModel):
    active_id: int = Field(gt=0)
    active_name: str | None = Field(default=None, max_length=100)


class TFIn(BaseModel):
    timeframe: int = Field(ge=5, le=86_400)


class AutoIn(BaseModel):
    enabled: bool


class StrategyIn(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    code: str | None = Field(default=None, max_length=250_000)
    filename: str | None = Field(default=None, max_length=100)


class BacktestIn(BaseModel):
    strategy: str = Field(min_length=1, max_length=100)
    dataset: str = Field(min_length=1, max_length=255)
    expiration: int = Field(ge=5, le=86_400)
    payout: float = Field(gt=0, le=1)
    stake: float = Field(gt=0, le=1_000_000)
    start: str | None = None
    end: str | None = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _model_data(model: BaseModel) -> dict[str, Any]:
    """Keep the application usable with either Pydantic v1 or v2."""
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)  # type: ignore[attr-defined]
    return model.dict(exclude_none=True)  # type: ignore[attr-defined]


def _assert_account_values(data: dict[str, Any]) -> None:
    if "account_type" in data:
        data["account_type"] = str(data["account_type"]).upper()
        if data["account_type"] not in {"PRACTICE", "REAL"}:
            raise HTTPException(status_code=422, detail="Account type must be PRACTICE or REAL.")
    if "active_id" in data and int(data["active_id"]) <= 0:
        raise HTTPException(status_code=422, detail="ACTIVE_ID must be a positive integer.")
    if "active_name" in data and data["active_name"] is not None:
        data["active_name"] = str(data["active_name"]).strip()


def _strategy_path(strategy_id: str) -> Path | None:
    """Resolve only Script Lab strategies; the application ships none."""
    if not strategy_id.startswith("user:"):
        return None
    filename = strategy_id[5:]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}\.py", filename):
        return None
    return USER_STRATS / filename


def _require_strategy(strategy_id: str) -> Path:
    path = _strategy_path(strategy_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Strategy not found.")
    return path


# ----------------------------------------------------------------------
# REST API
# ----------------------------------------------------------------------
@app.get("/api/state")
def get_state():
    return {**engine.snapshot(), "auth_enabled": _auth_required(), "storage_path": str(DATA_DIR)}


@app.post("/api/account")
def set_account(body: AccountIn):
    data = _model_data(body)
    remember = data.pop("remember", True)
    _assert_account_values(data)
    engine.configure(**data)
    if data.get("account_type"):
        engine.switch_balance(data["account_type"])

    if remember:
        stored = load_settings()
        stored.update(data)
        save_settings(stored)
    else:
        # Explicitly opt out: never leave a prior password in an ephemeral or
        # persistent Render filesystem after the user unchecks Remember.
        clear_settings()
    return {"ok": True, "state": engine.snapshot(), "remembered": bool(remember)}


@app.post("/api/connect")
def connect():
    ok = engine.connect()
    if not ok:
        raise HTTPException(status_code=400, detail="Could not start the IQ Option connection. Check account settings and logs.")
    return {"ok": True}


@app.post("/api/disconnect")
def disconnect():
    engine.disconnect()
    return {"ok": True}


@app.post("/api/asset")
def set_asset(body: AssetIn):
    engine.switch_asset(body.active_id, body.active_name or "")
    return {"ok": True}


@app.post("/api/chart-timeframe")
def set_tf(body: TFIn):
    engine.set_chart_timeframe(body.timeframe)
    return {"ok": True}


@app.post("/api/trade")
def trade(body: TradeIn):
    if str(body.direction).lower() not in {"call", "put", "buy", "sell", "up", "down"}:
        raise HTTPException(status_code=422, detail="Direction must be CALL or PUT.")
    ok = engine.place_trade(body.direction, body.amount, body.expiration, source="manual")
    if not ok:
        raise HTTPException(status_code=409, detail="Trade was not submitted. Check the connection, balance, and active-trade limit.")
    return {"ok": True}


@app.post("/api/auto")
def auto(body: AutoIn):
    ok = engine.set_auto(body.enabled)
    if not ok:
        raise HTTPException(status_code=409, detail="Load a strategy and connect before enabling auto trading.")
    return {"ok": True}


@app.post("/api/reset-stats")
def reset_stats():
    engine.reset_stats()
    return {"ok": True}


@app.get("/api/strategies")
def list_strategies():
    """Return only strategies created through Script Lab."""
    out = []
    for path in sorted(USER_STRATS.glob("*.py")):
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}\.py", path.name):
            out.append({"id": f"user:{path.name}", "name": path.stem.replace("_", " ").title()})
    return out


@app.get("/api/strategy-source")
def strategy_source(id: str):
    path = _require_strategy(id)
    try:
        return {"id": id, "code": path.read_text(encoding="utf-8")}
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not read strategy: {exc}") from exc


@app.post("/api/strategy/save")
def save_strategy(body: StrategyIn):
    if not body.code or not body.filename:
        raise HTTPException(status_code=400, detail="Filename and code are required.")
    filename = body.filename.strip()
    if not filename.endswith(".py"):
        filename += ".py"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}\.py", filename):
        raise HTTPException(
            status_code=422,
            detail="Use a filename starting with a letter and containing only letters, numbers, and underscores.",
        )

    path = USER_STRATS / filename
    temporary_path: str | None = None
    try:
        # Keep a .py suffix: importlib chooses a loader from the suffix when
        # StrategyRunner validates the temporary source file.
        fd, temporary_path = tempfile.mkstemp(prefix=f".{filename}.", suffix=".py", dir=USER_STRATS)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body.code)
        runner = StrategyRunner(source_path=temporary_path)
        timeframes = runner.required_timeframes()
        os.replace(temporary_path, path)
        temporary_path = None
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Strategy failed to load: {exc}",
            headers={"X-Strategy-Error": "validation-failed"},
        ) from exc
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)

    return {"ok": True, "id": f"user:{filename}", "timeframes": timeframes}


@app.post("/api/strategy/load")
def load_strategy(body: StrategyIn):
    if not body.name:
        raise HTTPException(status_code=400, detail="Strategy name is required.")
    try:
        path = _require_strategy(body.name)
        timeframes = engine.load_strategy(source_path=str(path), label=path.stem)
        return {"ok": True, "timeframes": timeframes}
    except HTTPException:
        raise
    except Exception as exc:
        engine.log(f"Strategy load failed: {exc}", "error")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/datasets")
def datasets():
    return backtester.list_datasets(str(ROOT))


@app.post("/api/backtest")
def run_backtest(body: BacktestIn):
    dataset_name = os.path.basename(body.dataset)
    if dataset_name != body.dataset:
        raise HTTPException(status_code=422, detail="Invalid dataset name.")
    dataset_path = ROOT / dataset_name
    if not dataset_path.is_file() or not dataset_name.startswith("candles_asset_") or not dataset_name.endswith(".csv"):
        raise HTTPException(status_code=404, detail="Dataset not found.")

    strategy_path = _require_strategy(body.strategy)
    timeframe = 60
    for part in dataset_name.removesuffix(".csv").split("_"):
        if part.endswith("s") and part[:-1].isdigit():
            timeframe = int(part[:-1])
    try:
        options = dict(
            dataset_path=str(dataset_path), expiration=body.expiration, payout=body.payout,
            stake=body.stake, start=body.start, end=body.end, timeframe=timeframe,
            label=strategy_path.stem,
        )
        return backtester.run(strategy_path=str(strategy_path), **options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        engine.log(f"Backtest failed: {exc}\n{traceback.format_exc(limit=3)}", "error")
        raise HTTPException(status_code=500, detail="Backtest failed. Check strategy compatibility and server logs.") from exc


# ----------------------------------------------------------------------
# WebSocket stream to browser
# ----------------------------------------------------------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if _auth_required() and not _is_valid_session(ws.cookies.get(SESSION_COOKIE)):
        await ws.close(code=1008, reason="Dashboard authentication required")
        return

    await ws.accept()
    queue = bus.subscribe()
    try:
        await ws.send_json({"type": "state", "ts": int(time.time() * 1000), "data": engine.snapshot()})
        for event in bus.history()[-80:]:
            await ws.send_json(event)
        timeframe = engine.chart_timeframe
        if engine.candles.get(timeframe):
            await ws.send_json({
                "type": "candles_snapshot",
                "ts": int(time.time() * 1000),
                "data": {
                    "timeframe": timeframe,
                    "active_name": engine.active_name,
                    "candles": engine.candles[timeframe][-300:],
                    "markers": engine.markers[-100:],
                },
            })
        while True:
            sent = False
            while queue:
                await ws.send_json(queue.popleft())
                sent = True
            await asyncio.sleep(0.01 if sent else 0.15)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(queue)


# ----------------------------------------------------------------------
# Static application
# ----------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
