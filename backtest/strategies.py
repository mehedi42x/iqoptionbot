"""
backtest/strategies.py
Nine distinct trading methodologies, each implemented as a signal generator.

Interface
    Strategy.signals(df, params) -> pd.Series of ints aligned to df.index:
        +1 = BUY entry  (evaluated at bar close, filled next bar open)
        -1 = SELL entry
         0 = no signal

    Strategy.exits -> default exit rules (in ATR multiples), consumed by the
    engine: sl_atr, tp_atr, trail_atr (optional), max_bars (optional).

All signals are lookahead-free: they only use information available at the
close of the current bar (crossover comparisons use .shift(1) where needed).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import (
    adx,
    atr,
    bollinger,
    donchian,
    ema,
    macd,
    rsi,
    supertrend,
    vwap,
)


def _sig(up: pd.Series, dn: pd.Series) -> pd.Series:
    """Combine boolean buy/sell conditions into an int signal series."""
    up = up.fillna(False).astype(bool)
    dn = dn.fillna(False).astype(bool)
    return (up.astype(int) - dn.astype(int))


class Strategy:
    name: str = ""
    label: str = ""
    param_grid: dict = {}
    exits: dict = {}

    def signals(self, df: pd.DataFrame, params: dict) -> pd.Series:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# 1. Trend following — dual EMA crossover filtered by ADX
# --------------------------------------------------------------------------- #
class EmaTrendAdx(Strategy):
    name = "ema_trend_adx"
    label = "Trend following (EMA cross + ADX filter)"
    param_grid = {
        "fast": [6, 10, 15],
        "slow": [20, 30, 45],
        "adx_min": [18, 22, 28],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 3.0, "trail_atr": 2.0, "max_bars": 45}

    def signals(self, df, p):
        f = ema(df["close"], p["fast"])
        s = ema(df["close"], p["slow"])
        adxv, _, _ = adx(df, 14)
        trending = adxv >= p["adx_min"]
        cross_up = (f > s) & (f.shift(1) <= s.shift(1))
        cross_dn = (f < s) & (f.shift(1) >= s.shift(1))
        return _sig(cross_up & trending, cross_dn & trending)


# --------------------------------------------------------------------------- #
# 2. Mean reversion — RSI extremes + Bollinger band touch
# --------------------------------------------------------------------------- #
class RsiMeanReversion(Strategy):
    name = "rsi_mean_reversion"
    label = "Mean reversion (RSI extremes + Bollinger bands)"
    param_grid = {
        "period": [14],
        "ob": [70, 80],
        "os": [30, 20],
        "bb_n": [20],
        "bb_k": [2.0],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 2.0, "max_bars": 40}

    def signals(self, df, p):
        r = rsi(df["close"], p["period"])
        _, up, lo = bollinger(df["close"], p["bb_n"], p["bb_k"])
        buy = (r < p["os"]) & (df["close"] < lo)
        sell = (r > p["ob"]) & (df["close"] > up)
        return _sig(buy, sell)


# --------------------------------------------------------------------------- #
# 3. Volatility breakout — Bollinger squeeze then band break
# --------------------------------------------------------------------------- #
class BollingerSqueezeBreakout(Strategy):
    name = "bollinger_squeeze_breakout"
    label = "Volatility breakout (Bollinger squeeze -> band break)"
    param_grid = {
        "n": [20],
        "k": [2.0],
        "squeeze_n": [100, 120],
        "sq_pct": [15, 20, 30],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 3.5, "trail_atr": 2.0, "max_bars": 60}

    def signals(self, df, p):
        _, up, lo = bollinger(df["close"], p["n"], p["k"])
        width = up - lo
        sq_thr = width.rolling(p["squeeze_n"]).quantile(p["sq_pct"] / 100.0)
        squeeze = width <= sq_thr
        break_up = df["close"] > up.shift(1)
        break_dn = df["close"] < lo.shift(1)
        return _sig(squeeze.shift(1) & break_up, squeeze.shift(1) & break_dn)


# --------------------------------------------------------------------------- #
# 4. Momentum — MACD histogram sign change filtered by ADX
# --------------------------------------------------------------------------- #
class MacdMomentum(Strategy):
    name = "macd_momentum"
    label = "Momentum (MACD histogram flip + ADX filter)"
    param_grid = {
        "fast": [8, 12],
        "slow": [21, 26],
        "signal": [9],
        "adx_min": [16, 20, 24],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 3.0, "trail_atr": 1.5, "max_bars": 45}

    def signals(self, df, p):
        _, _, hist = macd(df["close"], p["fast"], p["slow"], p["signal"])
        adxv, _, _ = adx(df, 14)
        trending = adxv >= p["adx_min"]
        up = (hist > 0) & (hist.shift(1) <= 0)
        dn = (hist < 0) & (hist.shift(1) >= 0)
        return _sig(up & trending, dn & trending)


# --------------------------------------------------------------------------- #
# 5. Trend flip — SuperTrend direction change
# --------------------------------------------------------------------------- #
class SuperTrendFlip(Strategy):
    name = "supertrend_flip"
    label = "SuperTrend direction flip"
    param_grid = {
        "n": [7, 10],
        "mult": [2.5, 3.0],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 3.0, "trail_atr": 2.0, "max_bars": 50}

    def signals(self, df, p):
        trend, _ = supertrend(df, p["n"], p["mult"])
        up = (trend == 1) & (trend.shift(1) == -1)
        dn = (trend == -1) & (trend.shift(1) == 1)
        return _sig(up, dn)


# --------------------------------------------------------------------------- #
# 6. Breakout — Donchian channel
# --------------------------------------------------------------------------- #
class DonchianBreakout(Strategy):
    name = "donchian_breakout"
    label = "Donchian channel breakout"
    param_grid = {
        "n": [15, 20, 30],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 3.0, "trail_atr": 2.0, "max_bars": 40}

    def signals(self, df, p):
        hh, ll = donchian(df, p["n"])
        up = df["close"] > hh.shift(1)
        dn = df["close"] < ll.shift(1)
        return _sig(up, dn)


# --------------------------------------------------------------------------- #
# 7. Institutional — VWAP mean reversion (z-score)
# --------------------------------------------------------------------------- #
class VwapReversion(Strategy):
    name = "vwap_reversion"
    label = "VWAP mean reversion (z-score)"
    param_grid = {
        "n": [100, 200],
        "z": [1.5, 2.0, 2.5],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 2.0, "max_bars": 40}

    def signals(self, df, p):
        v = vwap(df, p["n"])
        sd = df["close"].rolling(p["n"]).std(ddof=0)
        z = (df["close"] - v) / (sd + 1e-12)
        return _sig(z < -p["z"], z > p["z"])


# --------------------------------------------------------------------------- #
# 8. Price action — engulfing candle at swing support/resistance
# --------------------------------------------------------------------------- #
class PriceActionEngulfing(Strategy):
    name = "price_action_engulfing"
    label = "Price action (engulfing candle at swing S/R)"
    param_grid = {
        "swing": [8, 12],
        "body_ratio": [0.5],
        "prox_atr": [0.8, 1.2],
    }
    exits = {"sl_atr": 2.0, "tp_atr": 3.0, "max_bars": 30}

    def signals(self, df, p):
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]
        body = (c - o).abs()
        rng = (h - l).replace(0, np.nan)
        quality = (body / rng) > p["body_ratio"]

        prev_bear = o.shift(1) > c.shift(1)
        bull_eng = (c > o) & (o <= c.shift(1)) & (c >= o.shift(1)) & prev_bear & quality
        prev_bull = o.shift(1) < c.shift(1)
        bear_eng = (c < o) & (o >= c.shift(1)) & (c <= o.shift(1)) & prev_bull & quality

        a = atr(df, 14)
        swing_hi = h.rolling(p["swing"]).max().shift(1)
        swing_lo = l.rolling(p["swing"]).min().shift(1)
        prox = p["prox_atr"] * a.shift(1)
        near_support = (c.shift(1) - swing_lo).abs() <= prox
        near_resist = (swing_hi - c.shift(1)).abs() <= prox

        return _sig(bull_eng & near_support, bear_eng & near_resist)


# --------------------------------------------------------------------------- #
# 9. Range contraction — NR7 squeeze + momentum ignition
# --------------------------------------------------------------------------- #
class VolatilityContraction(Strategy):
    name = "volatility_contraction"
    label = "Range contraction (NR7 squeeze + momentum ignition)"
    param_grid = {
        "nr": [6, 7, 8],
        "mom": [4, 6],
    }
    exits = {"sl_atr": 1.5, "tp_atr": 3.0, "trail_atr": 1.5, "max_bars": 30}

    def signals(self, df, p):
        rng = df["high"] - df["low"]
        nr = rng < rng.rolling(p["nr"]).min().shift(1)
        mom = df["close"].pct_change(p["mom"])
        return _sig(nr & (mom > 0), nr & (mom < 0))


STRATEGIES: dict[str, Strategy] = {
    s.name: s for s in (
        EmaTrendAdx(),
        RsiMeanReversion(),
        BollingerSqueezeBreakout(),
        MacdMomentum(),
        SuperTrendFlip(),
        DonchianBreakout(),
        VwapReversion(),
        PriceActionEngulfing(),
        VolatilityContraction(),
    )
}
