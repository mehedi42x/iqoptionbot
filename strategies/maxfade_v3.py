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
    """MaxFade v3 — v2 + ONE validated accretive add (F1a). NO EMA.

    v2 base (W7): normal pos>=0.93, skip {3,20,21,22} pos>=0.80,
    weak {8,9,10,11,13,14} trimmed.
    v3 add: MONSTER hours {19,23} trade down to pos>=0.90
    (F1a: TRAIN 61.90%, HO 59.09%, green all 3 months, FULL ~61.6% —
    the only WR-accretive pocket found in 5 lab rounds / ~60 tests).

    Everything else tested & rejected: no validated flip exists
    (no sub-50% pocket in v2 pool), no validated cut (every pocket
    wins in >=1 split), all other adds dilutive or unvalidated.
    """

    required_timeframes = [60]

    POS_MIN = 0.93
    POS_MIN_SKIP = 0.80
    MONSTER_HOURS_UTC = {19, 23}
    MONSTER_POS_MIN = 0.90
    SKIP_HOURS_UTC = {3, 20, 21, 22}
    TRIM_WEAK_HOURS = {8, 9, 10, 11, 13, 14}
    ENABLE_SKIP_EXTENSION = True
    ENABLE_HOUR_TRIM = True
    ENABLE_NORMAL_FADES = True
    ENABLE_MONSTER_LOWER = True

    def __init__(self):
        self.reset()

    def reset(self):
        self.last_1m_timestamp = None
        self.last_candle = None
        self.last_signal_timestamp = None
        self.last_signal = None
        self.last_module = None
        self.last_pos = None
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
        threshold = self.POS_MIN_SKIP if skip_hour else (self.MONSTER_POS_MIN if monster else self.POS_MIN)

        if pos >= threshold:
            self.last_module = "FADE_SKIP" if skip_hour else ("FADE_MONSTER" if monster and pos < self.POS_MIN else "FADE")
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
            "no_trade": self.no_trade,
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
            "last_module": self.last_module,
            "last_signal_timestamp": self.last_signal_timestamp,
        }
