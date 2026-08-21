from .base import BaseStrategy

class EMA:
    def __init__(self, period):
        self.period = period
        self.k = 2 / (period + 1)
        self.value = None

    def update(self, price):
        if self.value is None:
            self.value = price
        else:
            self.value = price * self.k + self.value * (1 - self.k)
        return self.value


class Strategy(BaseStrategy):

    def __init__(self):
        # 5 Minute Timeframe (Primary Trend)
        self.ema40 = EMA(40)
        self.primary_trend = None
        self._current_5m = None
        self._last_closed_5m = None

        # 1 Minute Timeframe (Secondary Trend)
        self.ema9 = EMA(9)
        self.ema12 = EMA(12)
        self.secondary_trend = None
        self._current_1m = None
        self._last_closed_1m = None

        # 15 Second Timeframe (Signal Execution)
        self.ema2 = EMA(2)
        self.ema3 = EMA(3)
        self.prev_ema2 = None
        self.prev_ema3 = None
        self._current_15s = None
        self._last_closed_15s = None

    def update_5m(self, candle):
        t = candle.get("from") or candle.get("at")

        if t is None:
            return

        if self._current_5m is None:
            self._current_5m = candle.copy()
            return

        current_t = (
            self._current_5m.get("from")
            or self._current_5m.get("at")
        )

        if t == current_t:
            self._current_5m = candle.copy()
            return

        closed_candle = self._current_5m
        close = closed_candle.get("close")

        if close is not None:
            # Update EMA 40 and set Primary Trend
            ema_val = self.ema40.update(close)
            if ema_val is not None:
                if close > ema_val:
                    self.primary_trend = "up"
                elif close < ema_val:
                    self.primary_trend = "down"

        self._last_closed_5m = current_t
        self._current_5m = candle.copy()

    def update_1m(self, candle):
        t = candle.get("from") or candle.get("at")

        if t is None:
            return

        if self._current_1m is None:
            self._current_1m = candle.copy()
            return

        current_t = (
            self._current_1m.get("from")
            or self._current_1m.get("at")
        )

        if t == current_t:
            self._current_1m = candle.copy()
            return

        closed_candle = self._current_1m
        close = closed_candle.get("close")

        if close is not None:
            e9 = self.ema9.update(close)
            e12 = self.ema12.update(close)

            if e9 is not None and e12 is not None:
                if e9 > e12:
                    self.secondary_trend = "up"
                elif e9 < e12:
                    self.secondary_trend = "down"

        self._last_closed_1m = current_t
        self._current_1m = candle.copy()

    def update_15s(self, candle):
        t = candle.get("from") or candle.get("at")

        if t is None:
            return

        if self._current_15s is None:
            self._current_15s = candle.copy()
            return

        current_t = (
            self._current_15s.get("from")
            or self._current_15s.get("at")
        )

        if t == current_t:
            self._current_15s = candle.copy()
            return

        closed_candle = self._current_15s
        close = closed_candle.get("close")

        if close is not None:
            self.prev_ema2 = self.ema2.value
            self.prev_ema3 = self.ema3.value

            self.ema2.update(close)
            self.ema3.update(close)

        self._last_closed_15s = current_t
        self._current_15s = candle.copy()

    def check_signal(self):
        # যদি ৫ মিনিট বা ১ মিনিটের ট্রেন্ড সেট না হয়ে থাকে, তবে সিগন্যাল বাতিল হবে
        if self.primary_trend is None or self.secondary_trend is None:
            return None

        # যদি ৫ মিনিট এবং ১ মিনিটের ট্রেন্ড একই দিকে না থাকে, তবে ট্রেড নেওয়া হবে না
        if self.primary_trend != self.secondary_trend:
            return None

        if self.prev_ema2 is None or self.prev_ema3 is None:
            return None

        if self.ema2.value is None or self.ema3.value is None:
            return None

        # 15s EMA 2 & 3 Crossover logic
        crossed_up = (
            self.prev_ema2 <= self.prev_ema3
            and self.ema2.value > self.ema3.value
        )

        crossed_down = (
            self.prev_ema2 >= self.prev_ema3
            and self.ema2.value < self.ema3.value
        )

        # Final Confirmation: Primary (5m) & Secondary (1m) trends match the 15s crossover signal
        if self.primary_trend == "up" and self.secondary_trend == "up" and crossed_up:
            return "call"

        if self.primary_trend == "down" and self.secondary_trend == "down" and crossed_down:
            return "put"

        return None
