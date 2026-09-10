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
    """MTF-Sniper — S30a = 30s sniper (h21/22, pos>=0.80, size<1.0) + 1m vs-trend.

    Lab (Aug20-Sep10 window): n=403, W251/L118/D34, 68.02% WR, +$95.3R
    (@$1, 85% payout); TR 62.96% / HO 73.33%, 3/3 blocks green.
    ~19 trades/day, hours ONLY 21/22 UTC (=03-05 Dhaka).

    Signals fire on 30s arrivals only. The 60s feed is context (ATR60mean +
    SMA50/20 trend), replicated from lab_mtf.py exactly (windows INCLUSIVE
    of the ctx bar; ctx = last 1m with ts <= entry-60).
    """

    required_timeframes = [30, 60]
    MAX_1M_CANDLES = 300
    MAX_30S_CANDLES = 400

    E1B_HOURS_UTC = {21, 22}
    E1B_POS_MIN = 0.80
    E1B_SIZE_MAX = 1.0

    def __init__(self):
        self.reset()

    def reset(self):
        self.candles_1m = []
        self.candles_30s = []
        self.last_1m_timestamp = None
        self.last_30s_timestamp = None
        self.last_signal_entry_ts = None
        self.last_signal = None
        self.last_module = None
        self.last_pos = None
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

    def _snipe(self, entry_ts):
        if len(self.candles_30s) < 2:
            return None, None, "WAIT_30S"
        if self._utc_hour(entry_ts) not in self.E1B_HOURS_UTC:
            return None, None, "HOUR"
        k = self.candles_30s[-2]
        rng = k.high - k.low
        if rng <= 0:
            return None, None, "FLAT_CANDLE"
        if k.close == k.open:
            return None, None, "DOJI"
        bullish = k.close > k.open
        pos = (k.close - k.low) / rng if bullish else (k.high - k.close) / rng
        self.last_pos = pos
        if pos < self.E1B_POS_MIN:
            return None, None, "POS"
        want = entry_ts - 60
        ctx = None
        for idx in range(len(self.candles_1m) - 1, -1, -1):
            if self.candles_1m[idx].timestamp <= want:
                ctx = idx
                break
        if ctx is None or ctx < 60:
            return None, None, "WARMUP_1M_CTX"
        tot = 0.0
        for i in range(ctx - 59, ctx + 1):
            tot += self.candles_1m[i].high - self.candles_1m[i].low
        atr = tot / 60.0
        self.atr_1m = atr
        if atr <= 0 or rng / atr >= self.E1B_SIZE_MAX:
            return None, None, "SIZE"
        if ctx < 50:
            return None, None, "WARMUP_TREND"
        s50 = sum(c.close for c in self.candles_1m[ctx - 49:ctx + 1]) / 50.0
        s20 = sum(c.close for c in self.candles_1m[ctx - 19:ctx + 1]) / 20.0
        cc = self.candles_1m[ctx].close
        trend = 1 if (cc > s50 and s20 > s50) else (-1 if (cc < s50 and s20 < s50) else 0)
        direction = "PUT" if bullish else "CALL"
        vs = (trend == 1 and direction == "PUT") or (trend == -1 and direction == "CALL")
        if not vs:
            return None, None, "WITH_TREND"
        return direction, "S30A_MTF", None

    def update_candle(self, timeframe, candle):
        try:
            timeframe = int(timeframe)
            candle = self._normalize_candle(candle)
        except (TypeError, ValueError):
            return None

        if timeframe == 60:
            self._push(self.candles_1m, candle, "last_1m_timestamp", self.MAX_1M_CANDLES)
            self.no_trade, self.no_trade_reason = True, "CTX_1M"
            return None

        if timeframe == 30:
            new_candle = self._push(self.candles_30s, candle, "last_30s_timestamp", self.MAX_30S_CANDLES)
            signal, module, reason = self._snipe(self.candles_30s[-1].timestamp)
            self.last_module = module
            if not new_candle or signal is None or len(self.candles_30s) < 2:
                self.no_trade, self.no_trade_reason = True, (reason or "WAIT_30S")
                return None
            entry_ts = self.candles_30s[-1].timestamp
            if entry_ts == self.last_signal_entry_ts:
                self.no_trade, self.no_trade_reason = True, "DEDUP"
                return None
            self.last_signal_entry_ts = entry_ts
            self.last_signal = signal
            self.no_trade, self.no_trade_reason = False, None
            return signal

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
            "no_trade": self.no_trade,
            "no_trade_reason": self.no_trade_reason,
            "last_signal": self.last_signal,
            "last_module": self.last_module,
            "last_signal_entry_ts": self.last_signal_entry_ts,
        }
