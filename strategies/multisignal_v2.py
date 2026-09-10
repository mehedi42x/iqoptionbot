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
    """MultiSignal v2 — MS1 + S9b swap (60.25% WR). NO EMA.

    Written in the same structure as strategies/emacombo.py
    (candles_1m list, _update_1m, same get_status keys).

    S9b = cut L3 (h12/15 extremes: FULL 50.3% WR) + add D2
    (calm-regime 0.85-0.90 mids: FULL 56.5% WR, 3/3 months green).
    Validated as ONE combo: dW=+7, dL=-102, TR +$1,002, HO +$77.5
    (@$10), every month net-UP and losers-DOWN, WR 59.65% -> 60.25%.

    Router: weak hours trimmed; skip {3,20,21,22} >=0.80;
    skip {20,21,22}+calm >=0.75; monster {19,23} >=0.90;
    normal >=0.93; h{12,15} extremes trimmed (calm-mids still trade);
    calm-regime 0.85-0.90 mids added everywhere (normal hours).
    Toggles: ENABLE_H1215_TRIM / ENABLE_CALM_MID (both False = MS1).
    """

    # Only 60s timeframe is needed
    required_timeframes = [60]
    MAX_1M_CANDLES = 300

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
    ATR_PERIOD = 14
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
        self.candles_1m = []
        self.ema9_1m = None
        self.ema12_1m = None
        self.atr_1m = None
        self.market_direction = "NEUTRAL"
        self.last_1m_timestamp = None
        self.last_signal_timestamp = None
        self.last_signal = None
        self.last_module = None
        self.last_pos = None
        self.last_vol_ratio = None
        self.last_regime = None
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
        self.last_pos = None

        if len(completed) < 1:
            self.no_trade, self.no_trade_reason = True, "WAIT_FIRST_CANDLE"
            return None

        self.atr_1m = self._atr(completed, self.ATR_PERIOD)

        k = completed[-1]
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

        # Auto-detect: calm / normal / warming up (trailing 60 ranges)
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
            "last_pos": self.last_pos,
            "vol_ratio": self.last_vol_ratio,
            "regime": self.last_regime,
            "no_trade": self.no_trade,
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
            "last_module": self.last_module,
            "last_signal_timestamp": self.last_signal_timestamp,
        }
