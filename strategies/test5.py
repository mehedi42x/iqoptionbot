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


class RSI:
    def __init__(self, period=14):
        self.period = period
        self.avg_gain = None
        self.avg_loss = None
        self.prev_price = None
        self.value = None
        self.prices = []

    def update(self, price):
        if self.prev_price is None:
            self.prev_price = price
            return None

        change = price - self.prev_price
        self.prev_price = price
        gain = max(change, 0)
        loss = max(-change, 0)

        if self.avg_gain is None:
            self.prices.append((gain, loss))
            if len(self.prices) == self.period:
                self.avg_gain = sum(g for g, l in self.prices) / self.period
                self.avg_loss = sum(l for g, l in self.prices) / self.period
                if self.avg_loss == 0:
                    self.value = 100.0
                else:
                    rs = self.avg_gain / self.avg_loss
                    self.value = 100 - (100 / (1 + rs))
        else:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period
            if self.avg_loss == 0:
                self.value = 100.0
            else:
                rs = self.avg_gain / self.avg_loss
                self.value = 100 - (100 / (1 + rs))

        return self.value


class Strategy(BaseStrategy):

    def __init__(self):
        # 5-minute candle indicators (EMA 9 & EMA 12)
        self.ema9_5m = EMA(9)
        self.ema12_5m = EMA(12)
        self.prev_ema9_5m = None
        self.prev_ema12_5m = None
        self.trend_5m = None

        # 1-minute candle indicators (EMA 5 & EMA 10)
        self.ema5_1m = EMA(5)
        self.ema10_1m = EMA(10)
        self.trend_1m = None

        # 15-second candle indicators (RSI 14)
        self.rsi_15s = RSI(14)
        self.prev_rsi = None
        self.rsi_buy_trigger = False
        self.rsi_sell_trigger = False

        # Candle Tracking Variables
        self._current_5m = None
        self._last_closed_5m = None

        self._current_1m = None
        self._last_closed_1m = None

        self._current_15s = None
        self._last_closed_15s = None

    def update_5m(self, candle):
        t = candle.get("from") or candle.get("at")
        if t is None:
            return

        if self._current_5m is None:
            self._current_5m = candle.copy()
            return

        current_t = self._current_5m.get("from") or self._current_5m.get("at")
        if t == current_t:
            self._current_5m = candle.copy()
            return

        closed_candle = self._current_5m
        close = closed_candle.get("close")

        if close is not None:
            self.prev_ema9_5m = self.ema9_5m.value
            self.prev_ema12_5m = self.ema12_5m.value

            e9 = self.ema9_5m.update(close)
            e12 = self.ema12_5m.update(close)

            if self.prev_ema9_5m is not None and self.prev_ema12_5m is not None:
                # Both EMAs must slope in the exact same direction (One-directional condition)
                is_sloping_up = (e9 > self.prev_ema9_5m) and (e12 > self.prev_ema12_5m) and (e9 > e12)
                is_sloping_down = (e9 < self.prev_ema9_5m) and (e12 < self.prev_ema12_5m) and (e9 < e12)

                if is_sloping_up:
                    self.trend_5m = "up"
                elif is_sloping_down:
                    self.trend_5m = "down"
                else:
                    self.trend_5m = None

        self._last_closed_5m = current_t
        self._current_5m = candle.copy()

    def update_1m(self, candle):
        t = candle.get("from") or candle.get("at")
        if t is None:
            return

        if self._current_1m is None:
            self._current_1m = candle.copy()
            return

        current_t = self._current_1m.get("from") or self._current_1m.get("at")
        if t == current_t:
            self._current_1m = candle.copy()
            return

        closed_candle = self._current_1m
        close = closed_candle.get("close")

        if close is not None:
            e5 = self.ema5_1m.update(close)
            e10 = self.ema10_1m.update(close)

            if e5 is not None and e10 is not None:
                if e5 > e10:
                    self.trend_1m = "up"
                elif e5 < e10:
                    self.trend_1m = "down"
                else:
                    self.trend_1m = None

        self._last_closed_1m = current_t
        self._current_1m = candle.copy()

    def update_15s(self, candle):
        t = candle.get("from") or candle.get("at")
        if t is None:
            return

        if self._current_15s is None:
            self._current_15s = candle.copy()
            return

        current_t = self._current_15s.get("from") or self._current_15s.get("at")
        if t == current_t:
            self._current_15s = candle.copy()
            return

        closed_candle = self._current_15s
        close = closed_candle.get("close")

        if close is not None:
            self.prev_rsi = self.rsi_15s.value
            curr_rsi = self.rsi_15s.update(close)

            self.rsi_buy_trigger = False
            self.rsi_sell_trigger = False

            if self.prev_rsi is not None and curr_rsi is not None:
                # RSI 50 Crossover Signals
                rsi_cross_up = (self.prev_rsi <= 50) and (curr_rsi > 50)
                rsi_cross_down = (self.prev_rsi >= 50) and (curr_rsi < 50)

                # RSI 50 Retest and Bounce Signals (48-52 range)
                rsi_retest_up = (48 <= self.prev_rsi <= 52) and (curr_rsi > self.prev_rsi) and (curr_rsi > 50)
                rsi_retest_down = (48 <= self.prev_rsi <= 52) and (curr_rsi < self.prev_rsi) and (curr_rsi < 50)

                if rsi_cross_up or rsi_retest_up:
                    self.rsi_buy_trigger = True
                if rsi_cross_down or rsi_retest_down:
                    self.rsi_sell_trigger = True

        self._last_closed_15s = current_t
        self._current_15s = candle.copy()

    def check_signal(self):
        if self.trend_5m == "up" and self.trend_1m == "up" and self.rsi_buy_trigger:
            self.rsi_buy_trigger = False
            return "call"

        if self.trend_5m == "down" and self.trend_1m == "down" and self.rsi_sell_trigger:
            self.rsi_sell_trigger = False
            return "put"

        return None
