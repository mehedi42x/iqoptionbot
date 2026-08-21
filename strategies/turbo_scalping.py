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
        self.ema9 = EMA(9)
        self.ema12 = EMA(12)
        self.trend = None

        self.ema2 = EMA(2)
        self.ema3 = EMA(3)
        self.prev_ema2 = None
        self.prev_ema3 = None

        self._current_1m = None
        self._last_closed_1m = None

        self._current_15s = None
        self._last_closed_15s = None

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

            if e9 > e12:
                self.trend = "up"
            elif e9 < e12:
                self.trend = "down"

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
        if self.trend is None:
            return None

        if self.prev_ema2 is None or self.prev_ema3 is None:
            return None

        if self.ema2.value is None or self.ema3.value is None:
            return None

        crossed_up = (
            self.prev_ema2 <= self.prev_ema3
            and self.ema2.value > self.ema3.value
        )

        crossed_down = (
            self.prev_ema2 >= self.prev_ema3
            and self.ema2.value < self.ema3.value
        )

        if self.trend == "up" and crossed_up:
            return "call"

        if self.trend == "down" and crossed_down:
            return "put"

        return None
