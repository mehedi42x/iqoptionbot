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
    # Only 60s timeframe is needed
    required_timeframes = [60]
    MAX_1M_CANDLES = 300

    EMA_FAST_1M = 9
    EMA_SLOW_1M = 12
    ATR_PERIOD = 14
    RANGE_ATR_MULT = 1.2
    MIN_BODY_RATIO = 0.50
    MOM_POS_MIN = 0.60
    MOM_POS_MAX = 0.85
    REV_POS_MIN = 0.90
    SKIP_HOURS_UTC = {3, 20, 21, 22}
    ENABLE_REVERSAL = True

    def __init__(self):
        self.reset()

    def reset(self):
        self.candles_1m = []
        self.ema9_1m = None
        self.ema12_1m = None
        self.atr_1m = None
        self.market_direction = "NEUTRAL"
        self.last_1m_timestamp = None
        self.last_signal_timestamp = None
        self.last_signal = None
        self.last_module = None
        self.no_trade = True
        self.no_trade_reason = "EMA_NOT_READY"

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
    def _ema(values, period):
        if len(values) < period:
            return None
        ema = sum(values[:period]) / period
        alpha = 2.0 / (period + 1.0)
        for v in values[period:]:
            ema = v * alpha + ema * (1.0 - alpha)
        return ema

    @staticmethod
    def _atr(candles, period):
        if len(candles) < period + 1:
            return None
        trs = []
        for i in range(len(candles) - period, len(candles)):
            cur, prev = candles[i], candles[i - 1]
            trs.append(
                max(
                    cur.high - cur.low,
                    abs(cur.high - prev.close),
                    abs(cur.low - prev.close),
                )
            )
        return sum(trs) / period

    @staticmethod
    def _utc_hour(ts):
        if ts > 1e11:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).hour

    def _update_1m(self):
        completed = self.candles_1m[:-1]
        self.last_module = None

        if len(completed) < max(self.EMA_SLOW_1M, self.ATR_PERIOD + 1):
            self.ema9_1m = self.ema12_1m = self.atr_1m = None
            self.market_direction = "NEUTRAL"
            self.no_trade, self.no_trade_reason = True, "EMA_NOT_READY"
            return None

        closes = [c.close for c in completed]
        self.ema9_1m = self._ema(closes, self.EMA_FAST_1M)
        self.ema12_1m = self._ema(closes, self.EMA_SLOW_1M)
        self.atr_1m = self._atr(completed, self.ATR_PERIOD)

        if self.ema9_1m > self.ema12_1m:
            self.market_direction = "BULLISH"
        elif self.ema9_1m < self.ema12_1m:
            self.market_direction = "BEARISH"
        else:
            self.market_direction = "NEUTRAL"
            self.no_trade, self.no_trade_reason = True, "EMA_FLAT"
            return None

        k = completed[-1]
        rng = k.high - k.low
        
        if rng <= 0 or self.atr_1m is None or self.atr_1m <= 0:
            self.no_trade, self.no_trade_reason = True, "FLAT_CANDLE"
            return None

        # Time filter
        if self._utc_hour(k.timestamp) in self.SKIP_HOURS_UTC:
            self.no_trade, self.no_trade_reason = True, "SKIP_HOUR"
            return None

        # Candle color filter
        bullish = k.close > k.open
        bearish = k.close < k.open
        
        if self.market_direction == "BULLISH" and not bullish:
            self.no_trade, self.no_trade_reason = True, "CANDLE_COLOUR_MISMATCH"
            return None
        if self.market_direction == "BEARISH" and not bearish:
            self.no_trade, self.no_trade_reason = True, "CANDLE_COLOUR_MISMATCH"
            return None

        # Impulse size
        if rng < self.RANGE_ATR_MULT * self.atr_1m:
            self.no_trade, self.no_trade_reason = True, "RANGE_TOO_SMALL"
            return None
        if abs(k.close - k.open) / rng < self.MIN_BODY_RATIO:
            self.no_trade, self.no_trade_reason = True, "BODY_TOO_SMALL"
            return None

        # Close position inside candle range
        pos = (k.close - k.low) / rng if bullish else (k.high - k.close) / rng
        trend_sig = "CALL" if self.market_direction == "BULLISH" else "PUT"

        if self.MOM_POS_MIN <= pos <= self.MOM_POS_MAX:
            self.last_module = "MOMENTUM"
            self.no_trade, self.no_trade_reason = False, None
            return trend_sig

        if self.ENABLE_REVERSAL and pos >= self.REV_POS_MIN:
            self.last_module = "REVERSAL"
            self.no_trade, self.no_trade_reason = False, None
            return "PUT" if trend_sig == "CALL" else "CALL"

        self.no_trade, self.no_trade_reason = True, "CLOSE_POSITION_OUT_OF_ZONE"
        return None

    def update_candle(self, timeframe, candle):
        try:
            timeframe = int(timeframe)
            candle = self._normalize_candle(candle)
        except (TypeError, ValueError):
            return None

        if timeframe == 60:
            new_candle = not (
                self.last_1m_timestamp and candle.timestamp == self.last_1m_timestamp
            )
            
            if new_candle:
                self.last_1m_timestamp = candle.timestamp
                self.candles_1m.append(candle)
                if len(self.candles_1m) > self.MAX_1M_CANDLES:
                    self.candles_1m.pop(0)
            else:
                self.candles_1m[-1] = candle

            signal = self._update_1m()

            if not new_candle or signal is None or len(self.candles_1m) < 2:
                return None

            closed_ts = self.candles_1m[-2].timestamp
            if closed_ts == self.last_signal_timestamp:
                return None

            self.last_signal_timestamp = closed_ts
            self.last_signal = signal
            return signal

        return None

    def update_60s(self, candle):
        return self.update_candle(60, candle)

    def get_status(self):
        return {
            "direction": self.market_direction,
            "ema9_1m": self.ema9_1m,
            "ema12_1m": self.ema12_1m,
            "atr_1m": self.atr_1m,
            "no_trade": self.no_trade,
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
            "last_module": self.last_module,
            "last_signal_timestamp": self.last_signal_timestamp,
        }
