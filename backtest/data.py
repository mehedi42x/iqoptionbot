"""
backtest/data.py
Data ingestion for the backtester.

1. load_candles(path)  -> read a real CSV export and normalise it to a standard
   DataFrame [time, open, high, low, close, volume]. Column names are detected
   automatically (open/O/Open, timestamp/time/date/from/at, max/min, etc.).

2. generate_synthetic(symbol, ...) -> realistic 15-second OHLCV data built from
   a regime-switching random walk with GARCH-style volatility clustering.
   Used only so the full pipeline can be demonstrated before real data is
   provided. Synthetic results are NOT tradable evidence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TIME_ALIASES = ["time", "timestamp", "datetime", "date", "from", "at", "time_utc", "datetime_utc"]
OPEN_ALIASES = ["open", "o"]
HIGH_ALIASES = ["high", "h", "max"]
LOW_ALIASES = ["low", "l", "min"]
CLOSE_ALIASES = ["close", "c", "price"]
VOLUME_ALIASES = ["volume", "vol", "v"]


def _find(cols, aliases):
    lowered = {str(c).strip().lower(): c for c in cols}
    for a in aliases:
        if a in lowered:
            return lowered[a]
    return None


def load_candles(path: str) -> pd.DataFrame:
    """Load and normalise a candle CSV. Accepts many common column spellings."""
    df = pd.read_csv(path)
    cols = list(df.columns)
    rename = {}
    for std, aliases in (
        ("time", TIME_ALIASES),
        ("open", OPEN_ALIASES),
        ("high", HIGH_ALIASES),
        ("low", LOW_ALIASES),
        ("close", CLOSE_ALIASES),
        ("volume", VOLUME_ALIASES),
    ):
        hit = _find(cols, aliases)
        if hit is not None and hit != std:
            rename[hit] = std
    df = df.rename(columns=rename)

    required = ["open", "high", "low", "close"]
    missing = [r for r in required if r not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns {missing}. Found columns: {cols}")

    for c in required:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(1.0)
    else:
        df["volume"] = 1.0

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    else:
        df["time"] = pd.date_range(
            start=pd.Timestamp.utcnow().floor("s") - pd.Timedelta(seconds=15 * len(df)),
            periods=len(df),
            freq="15s",
        )

    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


# --------------------------------------------------------------------------- #
# Synthetic 15s data generator (DEMO ONLY)
# --------------------------------------------------------------------------- #
_REGIME_DRIFT = [1.0, 0.3, 0.0, -0.3, -1.0]  # drift strength in units of sigma
_TRANSITION = np.array(
    [
        [0.9700, 0.0180, 0.0080, 0.0020, 0.0020],
        [0.0200, 0.9400, 0.0300, 0.0060, 0.0040],
        [0.0060, 0.0240, 0.9400, 0.0240, 0.0060],
        [0.0040, 0.0060, 0.0300, 0.9400, 0.0200],
        [0.0020, 0.0020, 0.0080, 0.0180, 0.9700],
    ]
)
_MOMENTUM = 0.06  # weak return autocorrelation (real markets are slightly momentum-driven)


def _instrument_params(symbol: str):
    sym = symbol.upper().replace("/", "").replace("-", "")
    if sym in ("XAUUSD", "GOLD", "XAU"):
        return 2400.0, 0.012
    if sym.endswith("JPY"):
        return 150.0, 0.005
    return 1.0850, 0.0045


def generate_synthetic(symbol: str = "EURUSD", n_bars: int = 28800, seed: int = 42) -> pd.DataFrame:
    """
    Generate realistic 15-second OHLCV candles.

    Model: hidden Markov regime (strong/weak trend up & down + range) drives the
    drift; a GARCH(1,1)-like process drives the volatility clustering. Wicks are
    drawn proportionally to the per-bar volatility. Fully deterministic for a
    given seed.
    """
    rng = np.random.default_rng(seed)
    base, daily_vol = _instrument_params(symbol)
    bars_per_day = 24 * 60 * 4
    sigma_base = daily_vol / np.sqrt(bars_per_day)

    state = 2
    h = np.zeros(n_bars)
    drift = np.zeros(n_bars)
    states = np.zeros(n_bars, dtype=int)
    hh = 0.0
    rho = 0.995
    vol_noise = 0.07
    for i in range(n_bars):
        state = int(rng.choice(5, p=_TRANSITION[state]))
        states[i] = state
        hh = rho * hh + vol_noise * rng.standard_normal()
        h[i] = hh
        sigma_i = sigma_base * np.exp(0.5 * hh)
        drift[i] = _REGIME_DRIFT[state] * sigma_i

    noise = rng.standard_normal(n_bars)
    log_ret = np.zeros(n_bars)
    for i in range(n_bars):
        log_ret[i] = drift[i] + _MOMENTUM * (log_ret[i - 1] if i else 0.0) \
            + sigma_base * np.exp(0.5 * h[i]) * noise[i]
    close = base * np.exp(np.cumsum(log_ret))

    open_ = np.empty(n_bars)
    open_[0] = base
    open_[1:] = close[:-1]

    body_hi = np.maximum(open_, close)
    body_lo = np.minimum(open_, close)
    price = np.maximum(close, 1e-6)
    wick_up = 0.5 * sigma_base * price * np.abs(rng.standard_normal(n_bars))
    wick_dn = 0.5 * sigma_base * price * np.abs(rng.standard_normal(n_bars))
    high = body_hi + wick_up
    low = body_lo - wick_dn

    volume = rng.lognormal(mean=np.log(1000.0), sigma=0.5, size=n_bars)
    time = pd.date_range(
        start=pd.Timestamp("2026-08-10 00:00:00", tz="UTC"),
        periods=n_bars,
        freq="15s",
    )

    df = pd.DataFrame(
        {
            "time": time,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    return df
