"""
Strategies/mtf_confluence_sniper.py
MTF CONFLUENCE SNIPER — Advanced Triple-Timeframe, High-Accuracy Strategy
for 30-second Binary / Digital / Bliz options.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger("IQ_BOT.Strategy.MTFSniper")

# --- Engine hints -----------------------------------------------------------
SIGNAL_TIMEFRAME = 15    # seconds — entry trigger timeframe (engine auto-fetches)
PRIMARY_TIMEFRAME = 60   # seconds — must match TIMEFRAME=1 in .env

# --- Tunable parameters -----------------------------------------------------
# Trend
EMA_MACRO_FAST = 6       # on resampled 5m
EMA_MACRO_SLOW = 12      # on resampled 5m
EMA_TREND_FAST = 9       # on 1m
EMA_TREND_SLOW = 21      # on 1m
EMA_ENTRY_FAST = 3       # on 15s
EMA_ENTRY_SLOW = 8       # on 15s

# Regime filters (1m)
ADX_PERIOD = 14
ADX_MIN = 18.0           # below this = ranging chop -> stand aside
ATR_PERIOD = 14
ATR_MEDIAN_LOOKBACK = 50
ATR_RATIO_MIN = 0.65     # ATR too far below its median = dead market
ATR_RATIO_MAX = 2.20     # ATR too far above its median = news spike / chaos
RSI_PERIOD = 14
RSI_BUY_MIN, RSI_BUY_MAX = 50.0, 72.0
RSI_SELL_MIN, RSI_SELL_MAX = 28.0, 50.0

# Support / resistance room (1m)
SR_LOOKBACK = 20         # candles used to find recent swing high / low
SR_EXCLUDE_LAST = 3      # exclude the most recent candles from the swing scan
SR_MIN_ROOM_ATR = 0.5    # minimum room (in ATR units) toward the trade side
SR_BREAK_TOL_ATR = 0.1   # within this of the swing = breakout/continuation (OK)

# Entry (15s)
STOCH_K, STOCH_D = 9, 3
STOCH_OB, STOCH_OS = 85.0, 15.0
BODY_MIN_RATIO = 0.50    # signal candle body must be >= 50% of its range
CLOSE_ZONE = 0.35        # close must sit in the top/bottom 35% of the candle
PULLBACK_ATR_TOL = 0.25  # how close (in 15s ATR) a pullback must tag EMA 8

# Confirmation score
MIN_SCORE = 3            # of 5 confirmations


# =============================  INDICATORS  =================================

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1.0 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1.0 / period, adjust=False).mean()
    rs = gain / (loss + 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False).mean() / (atr + 1e-12)
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False).mean() / (atr + 1e-12)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)
    return dx.ewm(alpha=1.0 / period, adjust=False).mean()


def _macd_hist(series: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.Series:
    macd_line = _ema(series, fast) - _ema(series, slow)
    signal_line = _ema(macd_line, sig)
    return macd_line - signal_line


def _stochastic(df: pd.DataFrame, k_period: int = 9, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    k = 100.0 * (df["close"] - low_min) / (high_max - low_min + 1e-12)
    d = k.rolling(window=d_period).mean()
    return k, d


def _bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    mid = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    return mid + num_std * std, mid, mid - num_std * std


def _to_dataframe(candles: Any) -> Optional[pd.DataFrame]:
    if candles is None:
        return None
    df = pd.DataFrame(candles) if isinstance(candles, list) else candles.copy()
    if df is None or len(df) == 0:
        return None
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            return None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df if len(df) > 0 else None


def _resample_to_5m(df_1m: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Build 5-minute candles from 1-minute candles (third timeframe)."""
    if "from" not in df_1m.columns:
        # Fallback: positional grouping in blocks of 5
        n = len(df_1m) // 5 * 5
        if n < 5:
            return None
        d = df_1m.iloc[len(df_1m) - n:].reset_index(drop=True)
        groups = d.index // 5
    else:
        d = df_1m.copy()
        groups = (pd.to_numeric(d["from"], errors="coerce") // 300).astype("Int64")

    agg = d.groupby(groups).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).reset_index(drop=True)
    return agg if len(agg) >= EMA_MACRO_SLOW + 2 else None


# ==============================  STRATEGY  ==================================

class Strategy:
    """Triple-timeframe confluence sniper: adapted for Live & Backtest Engine."""

    def __init__(self):
        self.name = "mtf_confluence_sniper"
        
        # Engine will automatically detect these timeframes (60s and 15s)
        self.timeframes = [PRIMARY_TIMEFRAME, SIGNAL_TIMEFRAME]
        
        # Data buffers
        self.candles_1m = []
        self.candles_15s = []
        
        # Keeping enough historical data for 5m resample and 1m/15s indicators
        self.max_1m_length = 150  # 150 mins is enough for 5m EMA and 1m ATR
        self.max_15s_length = 50  # Enough for 15s Stochastic & EMA

    def update_1m(self, candle: dict):
        """Receives 1-minute candles from Backtester/Live Engine"""
        self.candles_1m.append(candle)
        if len(self.candles_1m) > self.max_1m_length:
            self.candles_1m.pop(0)

    def update_15s(self, candle: dict):
        """Receives 15-second candles from Backtester/Live Engine"""
        self.candles_15s.append(candle)
        if len(self.candles_15s) > self.max_15s_length:
            self.candles_15s.pop(0)

    def check_signal(self) -> str:
        """Called by the engine after updates. Translates BUY/SELL to call/put."""
        # Ensure we have enough data to calculate all indicators
        if len(self.candles_1m) < 60 or len(self.candles_15s) < 20:
            return None

        # Format data as expected by the original analyze function
        data = {
            "candles": self.candles_1m,
            "signal_candles": self.candles_15s
        }
        
        # Run original analysis logic
        signal = self.analyze(data)
        
        # Translate to engine's expected format
        if signal == "BUY":
            return "call"
        elif signal == "SELL":
            return "put"
        
        return None

    # ---- bias helpers ------------------------------------------------------

    def _macro_bias(self, df5: pd.DataFrame) -> str:
        """5m macro trend from EMA 6/12 + close location."""
        ema_f = _ema(df5["close"], EMA_MACRO_FAST)
        ema_s = _ema(df5["close"], EMA_MACRO_SLOW)
        close = float(df5["close"].iloc[-1])
        f, s = float(ema_f.iloc[-1]), float(ema_s.iloc[-1])
        if f > s and close > s:
            return "BULL"
        if f < s and close < s:
            return "BEAR"
        return "FLAT"

    def _trend_bias(self, df1: pd.DataFrame) -> str:
        """1m trend: EMA 9/21 stacked AND both sloping the same way."""
        ema_f = _ema(df1["close"], EMA_TREND_FAST)
        ema_s = _ema(df1["close"], EMA_TREND_SLOW)
        f_now, f_prev = float(ema_f.iloc[-1]), float(ema_f.iloc[-3])
        s_now, s_prev = float(ema_s.iloc[-1]), float(ema_s.iloc[-3])
        if f_now > s_now and f_now > f_prev and s_now >= s_prev:
            return "BULL"
        if f_now < s_now and f_now < f_prev and s_now <= s_prev:
            return "BEAR"
        return "FLAT"

    def _micro_bias(self, sdf: pd.DataFrame) -> str:
        """15s structure: EMA 3 vs EMA 8."""
        ema_f = _ema(sdf["close"], EMA_ENTRY_FAST)
        ema_s = _ema(sdf["close"], EMA_ENTRY_SLOW)
        if float(ema_f.iloc[-1]) > float(ema_s.iloc[-1]):
            return "BULL"
        if float(ema_f.iloc[-1]) < float(ema_s.iloc[-1]):
            return "BEAR"
        return "FLAT"

    # ---- entry trigger (15s) -----------------------------------------------

    def _entry_trigger(self, sdf: pd.DataFrame, direction: str) -> bool:
        """
        Trigger A: EMA 3 crossing EMA 8 in trade direction on the last candle.
        Trigger B: pullback that tagged EMA 8 (within tolerance) and closed
                   back on the trend side with a decisive candle.
        """
        ema_f = _ema(sdf["close"], EMA_ENTRY_FAST)
        ema_s = _ema(sdf["close"], EMA_ENTRY_SLOW)
        atr_s = _atr(sdf, 10)

        f_prev, s_prev = float(ema_f.iloc[-2]), float(ema_s.iloc[-2])
        f_now, s_now = float(ema_f.iloc[-1]), float(ema_s.iloc[-1])

        last = sdf.iloc[-1]
        lo, hi, cl = float(last["low"]), float(last["high"]), float(last["close"])
        ema8 = s_now
        tol = PULLBACK_ATR_TOL * max(float(atr_s.iloc[-1]), 1e-12)

        if direction == "BUY":
            cross = f_prev <= s_prev and f_now > s_now
            pullback = (lo <= ema8 + tol) and (cl > ema8) and (f_now > s_now)
            return cross or pullback
        else:
            cross = f_prev >= s_prev and f_now < s_now
            pullback = (hi >= ema8 - tol) and (cl < ema8) and (f_now < s_now)
            return cross or pullback

    # ---- main --------------------------------------------------------------

    def analyze(self, data: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> str:
        candles = None
        signal_candles = None
        if isinstance(data, dict):
            candles = data.get("candles")
            signal_candles = data.get("signal_candles")
        elif isinstance(data, (list, pd.DataFrame)):
            candles = data

        df1 = _to_dataframe(candles)
        sdf = _to_dataframe(signal_candles)

        if df1 is None or len(df1) < max(ATR_MEDIAN_LOOKBACK + ATR_PERIOD, 60):
            return "NO_SIGNAL"
        if sdf is None or len(sdf) < max(EMA_ENTRY_SLOW + 4, STOCH_K + STOCH_D + 2):
            return "NO_SIGNAL"

        # ============ HARD FILTER H1 — triple-timeframe alignment ============
        df5 = _resample_to_5m(df1)
        if df5 is None:
            return "NO_SIGNAL"

        macro = self._macro_bias(df5)
        trend = self._trend_bias(df1)
        micro = self._micro_bias(sdf)

        if macro == "FLAT" or trend == "FLAT" or micro == "FLAT":
            return "NO_SIGNAL"
        if not (macro == trend == micro):
            return "NO_SIGNAL"

        direction = "BUY" if macro == "BULL" else "SELL"

        # ============ HARD FILTER H2 — trending market (ADX) =================
        adx = _adx(df1, ADX_PERIOD)
        adx_now = float(adx.iloc[-1])
        if not np.isfinite(adx_now) or adx_now < ADX_MIN:
            return "NO_SIGNAL"

        # ============ HARD FILTER H3 — volatility regime (ATR) ===============
        atr = _atr(df1, ATR_PERIOD)
        atr_now = float(atr.iloc[-1])
        atr_median = float(atr.tail(ATR_MEDIAN_LOOKBACK).median())
        if atr_median <= 0 or not np.isfinite(atr_now):
            return "NO_SIGNAL"
        atr_ratio = atr_now / atr_median
        if not (ATR_RATIO_MIN <= atr_ratio <= ATR_RATIO_MAX):
            return "NO_SIGNAL"

        # ============ HARD FILTER H4 — room to nearest swing (S/R) ===========
        close_1m = float(df1["close"].iloc[-1])
        recent = df1.iloc[-(SR_LOOKBACK + SR_EXCLUDE_LAST):-SR_EXCLUDE_LAST]
        swing_high = float(recent["high"].max())
        swing_low = float(recent["low"].min())

        if direction == "BUY":
            room = swing_high - close_1m
            at_or_through = close_1m >= swing_high - SR_BREAK_TOL_ATR * atr_now
        else:
            room = close_1m - swing_low
            at_or_through = close_1m <= swing_low + SR_BREAK_TOL_ATR * atr_now

        if not at_or_through and room < SR_MIN_ROOM_ATR * atr_now:
            return "NO_SIGNAL"

        # ============ HARD FILTER H5 — healthy RSI zone =======================
        rsi = _rsi(df1["close"], RSI_PERIOD)
        rsi_now = float(rsi.iloc[-1])
        if direction == "BUY" and not (RSI_BUY_MIN <= rsi_now <= RSI_BUY_MAX):
            return "NO_SIGNAL"
        if direction == "SELL" and not (RSI_SELL_MIN <= rsi_now <= RSI_SELL_MAX):
            return "NO_SIGNAL"

        # ============ ENTRY TRIGGER (15s) =====================================
        if not self._entry_trigger(sdf, direction):
            return "NO_SIGNAL"

        # ============ CONFIRMATION SCORE (need >= MIN_SCORE of 5) =============
        score = 0

        # C1 — MACD histogram momentum on 1m
        hist = _macd_hist(df1["close"])
        h_now, h_prev = float(hist.iloc[-1]), float(hist.iloc[-2])
        if direction == "BUY" and h_now > h_prev and h_now > 0:
            score += 1
        elif direction == "SELL" and h_now < h_prev and h_now < 0:
            score += 1

        # C2 — Stochastic cross on 15s, not exhausted
        k, d = _stochastic(sdf, STOCH_K, STOCH_D)
        k_now, k_prev = float(k.iloc[-1]), float(k.iloc[-2])
        d_now, d_prev = float(d.iloc[-1]), float(d.iloc[-2])
        if direction == "BUY" and k_prev <= d_prev and k_now > d_now and k_now < STOCH_OB:
            score += 1
        elif direction == "SELL" and k_prev >= d_prev and k_now < d_now and k_now > STOCH_OS:
            score += 1

        # C3 — decisive signal candle
        last = sdf.iloc[-1]
        o, h, l, c = (float(last["open"]), float(last["high"]),
                      float(last["low"]), float(last["close"]))
        rng = max(h - l, 1e-12)
        body_ratio = abs(c - o) / rng
        if direction == "BUY":
            close_pos = (c - l) / rng          # 1.0 = closed at the very high
            if c > o and body_ratio >= BODY_MIN_RATIO and close_pos >= (1.0 - CLOSE_ZONE):
                score += 1
        else:
            close_pos = (h - c) / rng          # 1.0 = closed at the very low
            if c < o and body_ratio >= BODY_MIN_RATIO and close_pos >= (1.0 - CLOSE_ZONE):
                score += 1

        # C4 — previous 15s candle does not strongly oppose
        prev = sdf.iloc[-2]
        po, pc = float(prev["open"]), float(prev["close"])
        prev_rng = max(float(prev["high"]) - float(prev["low"]), 1e-12)
        prev_body = abs(pc - po) / prev_rng
        opposing = (pc < po) if direction == "BUY" else (pc > po)
        if not (opposing and prev_body >= 0.6):
            score += 1

        # C5 — Bollinger positioning on 1m: right side of midline, not pierced
        bb_up, bb_mid, bb_lo = _bollinger(df1["close"], 20, 2.0)
        mid, up, lo_b = float(bb_mid.iloc[-1]), float(bb_up.iloc[-1]), float(bb_lo.iloc[-1])
        if np.isfinite(mid):
            if direction == "BUY" and mid < close_1m <= up:
                score += 1
            elif direction == "SELL" and lo_b <= close_1m < mid:
                score += 1

        if score < MIN_SCORE:
            return "NO_SIGNAL"

        logger.info(
            f"[MTFSniper] 🎯 VALID SIGNAL: {direction} | Macro={macro}, Trend={trend}, Micro={micro} | Score={score}/5"
        )
        return direction
