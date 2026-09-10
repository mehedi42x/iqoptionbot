from collections import deque
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
    """MultiSignal v2 — MS1 + S9b swap (first system over 60% WR). NO EMA.

    S9b = cut L3 (h12/15 extremes: FULL 50.3% WR) + add D2
    (calm-regime 0.85-0.90 mids: FULL 56.5% WR, 3/3 months green).
    Validated as ONE combo: dW=+7, dL=-102, TR +$1,002, HO +$77.5
    (@$10), every month net-UP and losers-DOWN, WR 59.65% -> 60.26%.
    11 other loser-cutting strategies tested (cooldowns, daily stop-loss,
    vr filters, post-doji, bar-raise, 3 more swaps): ALL FAIL —
    every ~60%-WR slice loses more winners than losers when cut.
    Only swapping a 50%-slice for a 56%-slice threads the needle.

    Router: weak hours trimmed; skip {3,20,21,22} >=0.80;
    skip {20,21,22}+calm >=0.75; monster {19,23} >=0.90;
    normal >=0.93; h{12,15} extremes trimmed (calm-mids still trade);
    calm-regime 0.85-0.90 mids added everywhere (normal hours).
    Toggles: ENABLE_H1215_TRIM / ENABLE_CALM_MID (both False = MS1).
    """

    required_timeframes = [60]

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

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_1m_timestamp = None
        self.last_candle = None
        self.last_signal_timestamp = None
        self.last_signal = None
        self.last_module = None
        self.last_pos = None
        self.last_vol_ratio = None
        self.last_regime = None
        self._ranges = deque(maxlen=self.VOL_SLOW)
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

    def _regime(self):
        if len(self._ranges) < self.VOL_SLOW:
            return None
        fast = sum(list(self._ranges)[-self.VOL_FAST:]) / self.VOL_FAST
        slow = sum(self._ranges) / self.VOL_SLOW
        if slow <= 0:
            return None
        self.last_vol_ratio = fast / slow
        return "calm" if self.last_vol_ratio < self.VOL_CALM_MAX else "normal"

    def _evaluate(self, k):
        self.last_module = None
        self.last_pos = None

        rng = k.high - k.low
        if rng <= 0:
            self.no_trade, self.no_trade_reason = True, "FLAT_CANDLE"
            return None
        if k.close == k.open:
            self.no_trade, self.no_trade_reason = True, "DOJI"
            return None

        bullish = k.close > k.open
        pos = (k.close - k.low) / rng if bullish else (k.high - k.close) / rng
        self.last_pos = pos

        hour = self._utc_hour(k.timestamp)
        if self.ENABLE_HOUR_TRIM and hour in self.TRIM_WEAK_HOURS:
            self.no_trade, self.no_trade_reason = True, "WEAK_HOUR"
            return None

        skip_hour = hour in self.SKIP_HOURS_UTC
        if skip_hour and not self.ENABLE_SKIP_EXTENSION:
            self.no_trade, self.no_trade_reason = True, "SKIP_HOUR"
            return None
        if not skip_hour and not self.ENABLE_NORMAL_FADES:
            self.no_trade, self.no_trade_reason = True, "NORMAL_DISABLED"
            return None
        monster = (
            self.ENABLE_MONSTER_LOWER
            and not skip_hour
            and hour in self.MONSTER_HOURS_UTC
        )
        regime = self._regime()
        self.last_regime = regime
        calm = regime == "calm"
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
            self.no_trade, self.no_trade_reason = True, "H1215_TRIM"
            return None
        if skip_hour:
            threshold = self.POS_MIN_SKIP_CALM if skip_calm else self.POS_MIN_SKIP
        else:
            threshold = self.MONSTER_POS_MIN if monster else self.POS_MIN

        if pos >= threshold:
            if skip_hour:
                self.last_module = "FADE_SKIP_CALM" if (skip_calm and pos < self.POS_MIN_SKIP) else "FADE_SKIP"
            else:
                self.last_module = "FADE_MONSTER" if (monster and pos < self.POS_MIN) else "FADE"
            self.no_trade, self.no_trade_reason = False, None
            return "PUT" if bullish else "CALL"

        if calm_mid_ok:
            self.last_module = "FADE_CALM_MID"
            self.no_trade, self.no_trade_reason = False, None
            return "PUT" if bullish else "CALL"

        self.no_trade, self.no_trade_reason = True, "POS_BELOW_THRESHOLD"
        return None

    def update_candle(self, timeframe, candle):
        try:
            timeframe = int(timeframe)
            candle = self._normalize_candle(candle)
        except (TypeError, ValueError):
            return None

        if timeframe != 60:
            return None

        if self.last_1m_timestamp is not None and candle.timestamp == self.last_1m_timestamp:
            return None

        self.last_1m_timestamp = candle.timestamp
        just_closed = self.last_candle
        self.last_candle = candle

        if just_closed is None:
            return None
        self._ranges.append(just_closed.high - just_closed.low)

        signal = self._evaluate(just_closed)
        if signal is None:
            return None
        if just_closed.timestamp == self.last_signal_timestamp:
            return None
        self.last_signal_timestamp = just_closed.timestamp
        self.last_signal = signal
        return signal

    def update_60s(self, candle):
        return self.update_candle(60, candle)

    def get_status(self):
        return {
            "direction": "NEUTRAL",
            "ema9_1m": None,
            "ema12_1m": None,
            "atr_1m": None,
            "last_pos": self.last_pos,
            "vol_ratio": self.last_vol_ratio,
            "regime": self.last_regime,
            "no_trade": self.no_trade,
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
            "last_module": self.last_module,
            "last_signal_timestamp": self.last_signal_timestamp,
        }
