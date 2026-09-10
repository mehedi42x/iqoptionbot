from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Candle:
    timestamp: float
    open: float
    high: float
    low: float
    close: float


class Strategy:
    """MTF-Volume — U4 = MS2 (1m legs) + E1B (30s sniper leg) + G1M (fresh-30s confirm).

    Multi-timeframe volume system. Beats MS2-on-window (Aug20-Sep10) on ALL FOUR:
    count +14.1% (3986 -> 4549), WR 59.18% -> 59.40%, TR +$120.1 -> +$149.6,
    HO +$240.4 -> +$277.1 (@$1, 85% payout). Lab: lab_mtf.py + lab_mtf2.py.

    Legs (tie order at same entry ts: MS2 > E1B > G1M, enforced explicitly):
      MS2  1m fades, verbatim multisignal_v2 rules (FADE/SKIP/MONSTER/CALM_MID/
           SKIP_CALM). Signal-bar hour; weak {8,9,10,11,13,14} + h{12,15}
           trimmed (calm-mids exempt).
      E1B  30s entries, ENTRY hour in {21,22} UTC; 30s fade pos>=0.80;
           30s-range / 1m-ctx-ATR60mean < 1.0 (small-bar sniper).
           Skipped where MS2 already fired at the same entry ts.
      G1M  1m entries: 1m-mid 0.85<=pos<0.93 (non-skip, non-weak, calm-mid
           exempt bands apply via MS2 first) confirmed by the FRESH second-half
           30s bar (pos>=0.90, same side). Evaluated on the 30s :00 arrival so
           both inputs are closed; skipped where MS2/E1B already fired.

    1m context for 30s legs = last 1m bar with ts <= entry-60 (order-independent).
    ATR60mean / calm / trend replicate lab_mtf.py exactly (trailing windows
    INCLUSIVE of the ctx bar; calm needs ctx_idx>=60, trend needs ctx_idx>=50).
    """

    required_timeframes = [30, 60]
    MAX_1M_CANDLES = 300
    MAX_30S_CANDLES = 400

    # ---- MS2 1m legs (verbatim multisignal_v2) ----
    POS_MIN = 0.93
    POS_MIN_SKIP = 0.80
    POS_MIN_SKIP_CALM = 0.75
    POS_MIN_CALM_MID = 0.85
    SKIP_HOURS_UTC = {3, 20, 21, 22}
    SKIP_CALM_HOURS_UTC = {20, 21, 22}
    MONSTER_HOURS_UTC = {19, 23}
    MONSTER_POS_MIN = 0.90
    TRIM_WEAK_HOURS = {8, 9, 10, 11, 13, 14}
    TRIM_H1215_HOURS = {12, 15}
    VOL_FAST = 5
    VOL_SLOW = 60
    VOL_CALM_MAX = 0.864
    ENABLE_SKIP_EXTENSION = True
    ENABLE_HOUR_TRIM = True
    ENABLE_NORMAL_FADES = True
    ENABLE_MONSTER_LOWER = True
    ENABLE_SKIP_CALM_LOWER = True
    ENABLE_H1215_TRIM = True
    ENABLE_CALM_MID = True

    # ---- E1B 30s sniper leg ----
    E1B_HOURS_UTC = {21, 22}
    E1B_POS_MIN = 0.80
    E1B_SIZE_MAX = 1.0

    # ---- G1M fresh-30s confirm leg ----
    G1M_POS_LO = 0.85
    G1M_POS_HI = 0.93
    G1M_FRESH_POS_MIN = 0.90

    def __init__(self):
        self.reset()

    def reset(self):
        self.candles_1m = []
        self.candles_30s = []
        self.last_1m_timestamp = None
        self.last_30s_timestamp = None
        self.last_ms2_entry_ts = None
        self.last_e1b_entry_ts = None
        self.last_g1m_entry_ts = None
        self.last_signal = None
        self.last_module = None
        self.last_pos = None
        self.last_vol_ratio = None
        self.last_regime = None
        self.atr_1m = None
        self.market_direction = "NEUTRAL"
        self.no_trade = True
        self.no_trade_reason = "WAIT_FIRST_CANDLE"

    def get_required_timeframes(self):
        return list(self.required_timeframes)

    @staticmethod
    def _value(candle, key, default=None):
        if isinstance(candle, dict):
            return candle.get(key, default)
        return getattr(candle, key, default)

    def _normalize_candle(self, candle):
        ts = (
            self._value(candle, "timestamp")
            or self._value(candle, "from")
            or self._value(candle, "time")
            or self._value(candle, "to")
        )
        if ts is None:
            raise ValueError("Candle timestamp missing")

        o = self._value(candle, "open")
        c = self._value(candle, "close")
        h = self._value(candle, "high")
        if h is None:
            h = self._value(candle, "max")
        l = self._value(candle, "low")
        if l is None:
            l = self._value(candle, "min")

        if o is None or c is None or h is None or l is None:
            raise ValueError("Incomplete OHLC candle")

        return Candle(float(ts), float(o), float(h), float(l), float(c))

    @staticmethod
    def _utc_hour(ts):
        if ts > 1e11:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).hour

    @staticmethod
    def _fade(c):
        rng = c.high - c.low
        if rng <= 0 or c.close == c.open:
            return None
        bullish = c.close > c.open
        pos = (c.close - c.low) / rng if bullish else (c.high - c.close) / rng
        return {"pos": pos, "dir": "PUT" if bullish else "CALL", "rng": rng}

    def _ms2_legs(self, completed):
        """MS2 decision on closed 1m bars. Returns (signal, module, reason)."""
        self.last_pos = None
        if len(completed) < 1:
            return None, None, "WAIT_FIRST_CANDLE"

        k = completed[-1]
        f = self._fade(k)
        if f is None:
            rng = k.high - k.low
            return None, None, ("FLAT_CANDLE" if rng <= 0 else "DOJI")
        pos = f["pos"]
        self.last_pos = pos

        hour = self._utc_hour(k.timestamp)
        if self.ENABLE_HOUR_TRIM and hour in self.TRIM_WEAK_HOURS:
            return None, None, "WEAK_HOUR"

        skip_hour = hour in self.SKIP_HOURS_UTC
        if skip_hour and not self.ENABLE_SKIP_EXTENSION:
            return None, None, "SKIP_HOUR"
        if not skip_hour and not self.ENABLE_NORMAL_FADES:
            return None, None, "NORMAL_DISABLED"
        monster = (
            self.ENABLE_MONSTER_LOWER
            and not skip_hour
            and hour in self.MONSTER_HOURS_UTC
        )

        self.last_vol_ratio = None
        self.last_regime = None
        calm = False
        if len(completed) >= self.VOL_SLOW:
            trailing = [c.high - c.low for c in completed[-self.VOL_SLOW:]]
            slow = sum(trailing) / self.VOL_SLOW
            if slow > 0:
                fast = sum(trailing[-self.VOL_FAST:]) / self.VOL_FAST
                self.last_vol_ratio = fast / slow
                self.last_regime = "calm" if self.last_vol_ratio < self.VOL_CALM_MAX else "normal"
                calm = self.last_regime == "calm"

        skip_calm = (
            self.ENABLE_SKIP_CALM_LOWER
            and skip_hour
            and hour in self.SKIP_CALM_HOURS_UTC
            and calm
        )
        calm_mid_ok = (
            self.ENABLE_CALM_MID
            and not skip_hour
            and calm
            and pos >= self.POS_MIN_CALM_MID
            and pos < 0.90
        )
        if self.ENABLE_H1215_TRIM and hour in self.TRIM_H1215_HOURS and not calm_mid_ok:
            return None, None, "H1215_TRIM"
        if skip_hour:
            threshold = self.POS_MIN_SKIP_CALM if skip_calm else self.POS_MIN_SKIP
        else:
            threshold = self.MONSTER_POS_MIN if monster else self.POS_MIN

        if pos >= threshold:
            if skip_hour:
                module = "FADE_SKIP_CALM" if (skip_calm and pos < self.POS_MIN_SKIP) else "FADE_SKIP"
            else:
                module = "FADE_MONSTER" if (monster and pos < self.POS_MIN) else "FADE"
            return f["dir"], module, None

        if calm_mid_ok:
            return f["dir"], "FADE_CALM_MID", None

        return None, None, "POS_BELOW_THRESHOLD"

    def _ctx_1m(self, entry_ts):
        """Index of last 1m bar with ts <= entry_ts-60 (lab ctx1m)."""
        want = entry_ts - 60
        for idx in range(len(self.candles_1m) - 1, -1, -1):
            if self.candles_1m[idx].timestamp <= want:
                return idx
        return None

    def _atr60mean(self, ctx_idx):
        if ctx_idx is None or ctx_idx < 60:
            return None
        tot = 0.0
        for i in range(ctx_idx - 59, ctx_idx + 1):
            tot += self.candles_1m[i].high - self.candles_1m[i].low
        return tot / 60.0

    def _e1b_leg(self, entry_ts):
        """30s sniper leg. Entry candle already appended. Returns (sig, mod, reason)."""
        if len(self.candles_30s) < 2:
            return None, None, "WAIT_30S"
        if self._utc_hour(entry_ts) not in self.E1B_HOURS_UTC:
            return None, None, "E1B_HOUR"
        if entry_ts == self.last_ms2_entry_ts:
            return None, None, "E1B_MS2_TIE"
        f = self._fade(self.candles_30s[-2])
        if f is None:
            return None, None, "E1B_BAD_BAR"
        if f["pos"] < self.E1B_POS_MIN:
            return None, None, "E1B_POS"
        ctx = self._ctx_1m(entry_ts)
        atr = self._atr60mean(ctx)
        if atr is None or atr <= 0:
            return None, None, "WARMUP_1M_CTX"
        self.atr_1m = atr
        if f["rng"] / atr >= self.E1B_SIZE_MAX:
            return None, None, "E1B_SIZE"
        return f["dir"], "E1B_30S", None

    def _g1m_leg(self, entry_ts):
        """Fresh-30s-confirm leg on 1m entries. Returns (sig, mod, reason)."""
        if entry_ts % 60 != 0:
            return None, None, "G1M_ALIGN"
        if entry_ts == self.last_ms2_entry_ts or entry_ts == self.last_e1b_entry_ts:
            return None, None, "G1M_TIE"
        sig = None
        for c in reversed(self.candles_1m):
            if c.timestamp < entry_ts:
                sig = c
                break
        if sig is None:
            return None, None, "WAIT_1M"
        f = self._fade(sig)
        if f is None:
            return None, None, "G1M_BAD_1M"
        hour = self._utc_hour(sig.timestamp)
        if hour in self.TRIM_WEAK_HOURS or hour in self.SKIP_HOURS_UTC:
            return None, None, "G1M_HOUR"
        if not (self.G1M_POS_LO <= f["pos"] < self.G1M_POS_HI):
            return None, None, "G1M_POS"
        fresh = None
        for c in reversed(self.candles_30s):
            if c.timestamp == sig.timestamp + 30:
                fresh = c
                break
            if c.timestamp < sig.timestamp + 30:
                break
        if fresh is None:
            return None, None, "G1M_NO_FRESH"
        ff = self._fade(fresh)
        if ff is None or ff["pos"] < self.G1M_FRESH_POS_MIN or ff["dir"] != f["dir"]:
            return None, None, "G1M_FRESH"
        return f["dir"], "G1M_FRESH30", None

    def _push(self, lst, candle, last_attr, maxlen):
        last = getattr(self, last_attr)
        if last is not None and candle.timestamp == last:
            lst[-1] = candle
            return False
        setattr(self, last_attr, candle.timestamp)
        lst.append(candle)
        if len(lst) > maxlen:
            lst.pop(0)
        return True

    def update_candle(self, timeframe, candle):
        try:
            timeframe = int(timeframe)
            candle = self._normalize_candle(candle)
        except (TypeError, ValueError):
            return None

        if timeframe == 60:
            new_candle = self._push(self.candles_1m, candle, "last_1m_timestamp", self.MAX_1M_CANDLES)
            signal, module, reason = self._ms2_legs(self.candles_1m[:-1])
            self.last_module = module
            if not new_candle or signal is None or len(self.candles_1m) < 2:
                self.no_trade, self.no_trade_reason = True, (reason or "WAIT_FIRST_CANDLE")
                return None
            entry_ts = self.candles_1m[-1].timestamp
            if entry_ts == self.last_ms2_entry_ts:
                self.no_trade, self.no_trade_reason = True, "DEDUP_MS2"
                return None
            self.last_ms2_entry_ts = entry_ts
            self.last_signal = signal
            self.no_trade, self.no_trade_reason = False, None
            return signal

        if timeframe == 30:
            new_candle = self._push(self.candles_30s, candle, "last_30s_timestamp", self.MAX_30S_CANDLES)
            if not new_candle or len(self.candles_30s) < 2:
                self.no_trade, self.no_trade_reason = True, "WAIT_30S"
                return None
            entry_ts = self.candles_30s[-1].timestamp
            signal, module, reason = self._e1b_leg(entry_ts)
            if signal is not None:
                if entry_ts == self.last_e1b_entry_ts:
                    self.no_trade, self.no_trade_reason = True, "DEDUP_E1B"
                    return None
                self.last_e1b_entry_ts = entry_ts
                self.last_module = module
                self.last_signal = signal
                self.no_trade, self.no_trade_reason = False, None
                return signal
            e1b_reason = reason
            signal, module, reason = self._g1m_leg(entry_ts)
            if signal is not None:
                if entry_ts == self.last_g1m_entry_ts:
                    self.no_trade, self.no_trade_reason = True, "DEDUP_G1M"
                    return None
                self.last_g1m_entry_ts = entry_ts
                self.last_module = module
                self.last_signal = signal
                self.no_trade, self.no_trade_reason = False, None
                return signal
            self.last_module = None
            self.no_trade, self.no_trade_reason = True, (reason or e1b_reason or "NO_30S")
            return None

        return None

    def update_60s(self, candle):
        return self.update_candle(60, candle)

    def update_30s(self, candle):
        return self.update_candle(30, candle)

    def get_status(self):
        return {
            "direction": self.market_direction,
            "ema9_1m": None,
            "ema12_1m": None,
            "atr_1m": self.atr_1m,
            "last_pos": self.last_pos,
            "vol_ratio": self.last_vol_ratio,
            "regime": self.last_regime,
            "no_trade": self.no_trade,
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
            "last_module": self.last_module,
            "last_ms2_entry_ts": self.last_ms2_entry_ts,
            "last_e1b_entry_ts": self.last_e1b_entry_ts,
            "last_g1m_entry_ts": self.last_g1m_entry_ts,
        }
