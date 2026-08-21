"""
backtest/indicators.py
Pure pandas/numpy indicator library. Every function is vectorized (except
SuperTrend, which needs a single O(n) pass) and returns Series aligned to the
input DataFrame's index. No lookahead: all rolling windows use only past data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Moving averages
# --------------------------------------------------------------------------- #
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


# --------------------------------------------------------------------------- #
# Volatility
# --------------------------------------------------------------------------- #
def true_range(df: pd.DataFrame) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-smoothed Average True Range."""
    return true_range(df).ewm(alpha=1.0 / period, adjust=False).mean()


# --------------------------------------------------------------------------- #
# Momentum oscillators
# --------------------------------------------------------------------------- #
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    dn = -delta.clip(upper=0.0)
    avg_up = up.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_dn = dn.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_up / (avg_dn + 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    line = fast_ema - slow_ema
    sig = line.ewm(span=signal, adjust=False).mean()
    hist = line - sig
    return line, sig, hist


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    ll = df["low"].rolling(k_period).min()
    hh = df["high"].rolling(k_period).max()
    k = 100.0 * (df["close"] - ll) / (hh - ll + 1e-12)
    d = k.rolling(d_period).mean()
    return k, d


def adx(df: pd.DataFrame, period: int = 14):
    """Returns (ADX, +DI, -DI)."""
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    atr_s = true_range(df).ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / (atr_s + 1e-12)
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / (atr_s + 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    adx_s = dx.ewm(alpha=1.0 / period, adjust=False).mean()
    return adx_s, plus_di, minus_di


# --------------------------------------------------------------------------- #
# Bands / channels
# --------------------------------------------------------------------------- #
def bollinger(series: pd.Series, period: int = 20, k: float = 2.0):
    mid = series.rolling(period).mean()
    sd = series.rolling(period).std(ddof=0)
    return mid, mid + k * sd, mid - k * sd


def donchian(df: pd.DataFrame, period: int = 20):
    return df["high"].rolling(period).max(), df["low"].rolling(period).min()


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    """Returns (trend, supertrend_line). trend: +1 up, -1 down."""
    a = atr(df, period).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2.0).to_numpy()
    close = df["close"].to_numpy()
    ub = hl2 + multiplier * a
    lb = hl2 - multiplier * a
    n = len(df)
    fub = np.empty(n)
    flb = np.empty(n)
    trend = np.ones(n, dtype=int)
    fub[0] = ub[0]
    flb[0] = lb[0]
    for i in range(1, n):
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or close[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or close[i - 1] < flb[i - 1]) else flb[i - 1]
        if trend[i - 1] == 1:
            trend[i] = -1 if close[i] < flb[i] else 1
        else:
            trend[i] = 1 if close[i] > fub[i] else -1
    st = np.where(trend == 1, flb, fub)
    return pd.Series(trend, index=df.index), pd.Series(st, index=df.index)


def vwap(df: pd.DataFrame, period: int = 200) -> pd.Series:
    """Rolling (anchored) VWAP using typical price."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"] if "volume" in df.columns else pd.Series(1.0, index=df.index)
    pv = tp * vol
    return pv.rolling(period).sum() / vol.rolling(period).sum()
