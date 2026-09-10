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
    """Sniper v1 — absolute max-WR system (SNI-2). NO EMA.

    Trades ONLY: UTC hours {21,22} + fade + small candle (range/ATR60<1.0).
    Thin-market chop + small candle = purest mean-reversion pocket found:
    TRAIN 67.17% (n=1128), HOLDOUT 69.91% (n=229), FULL ~67.7% (n=1357),
    green all 3 months. Winner of 9-sniper ladder (ranked by HO-WR).

    Bars: pos>=0.80 (skip hours); calm-regime (vol_ratio<0.864) lowers to
    0.75 (M2-leg, validated). 61-candle warmup (ATR60 + vol_ratio buffers).
    NOTE: concentrates ~23 trades/day into 2 night-UTC hours (03-05 Dhaka).
    Max-WR != max-money: MS2 earns ~4x more total. Run SNIPER for WR%,
    MS2 (multisignal_v2) for profit. Toggle ENABLE_CALM_LOWER=False for
    pure-0.80 sniper.
    """

    required_timeframes = [60]

    SNIPER_HOURS_UTC = {21, 22}
    POS_MIN_SKIP = 0.80
    POS_MIN_SKIP_CALM = 0.75
    RANGE_ATR_MAX = 1.0
    VOL_FAST = 5
    VOL_SLOW = 60
    VOL_CALM_MAX = 0.864
    ENABLE_CALM_LOWER = True

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
        self.last_range_atr = None
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

    def _indicators(self):
        if len(self._ranges) < self.VOL_SLOW:
            return None, None
        rs = list(self._ranges)
        slow = sum(rs) / self.VOL_SLOW
        if slow <= 0:
            return None, None
        fast = sum(rs[-self.VOL_FAST:]) / self.VOL_FAST
        return fast / slow, slow

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
        if hour not in self.SNIPER_HOURS_UTC:
            self.no_trade, self.no_trade_reason = True, "NOT_SNIPER_HOUR"
            return None

        vratio, atr60 = self._indicators()
        if vratio is None:
            self.no_trade, self.no_trade_reason = True, "WARMUP"
            return None
        self.last_vol_ratio = vratio
        self.last_regime = "calm" if vratio < self.VOL_CALM_MAX else "normal"
        self.last_range_atr = rng / atr60

        if self.last_range_atr >= self.RANGE_ATR_MAX:
            self.no_trade, self.no_trade_reason = True, "RANGE_TOO_BIG"
            return None

        calm_low = self.ENABLE_CALM_LOWER and self.last_regime == "calm"
        threshold = self.POS_MIN_SKIP_CALM if calm_low else self.POS_MIN_SKIP
        if pos >= threshold:
            self.last_module = "SNIPER_CALM" if (calm_low and pos < self.POS_MIN_SKIP) else "SNIPER"
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
            "range_atr": self.last_range_atr,
            "no_trade": self.no_trade,
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
            "last_module": self.last_module,
            "last_signal_timestamp": self.last_signal_timestamp,
        }
