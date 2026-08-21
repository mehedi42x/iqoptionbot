from collections import deque
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

    def __init__(self, trend_lookback=10, min_efficiency_ratio=0.35, min_ema_gap_pct=0.0005):
        """
        trend_lookback       : choppiness মাপার জন্য কতগুলো 1m candle পিছনে দেখবে
        min_efficiency_ratio : এর নিচে হলে market কে "choppy" ধরে নিয়ে trend আটকে দেওয়া হবে (0-1 রেঞ্জ)
        min_ema_gap_pct      : EMA9-EMA12 এর মধ্যে ন্যূনতম দূরত্ব (শতাংশ), না হলে flat trend ধরা হবে
        """
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

        # --- choppiness filter এর জন্য ---
        self.trend_lookback = trend_lookback
        self.min_efficiency_ratio = min_efficiency_ratio
        self.min_ema_gap_pct = min_ema_gap_pct
        self._closes_1m = deque(maxlen=trend_lookback + 1)

    # ------------------------------------------------------------------
    # Choppiness filter helpers
    # ------------------------------------------------------------------
    def _efficiency_ratio(self):
        """
        Kaufman Efficiency Ratio.
        মান ১-এর কাছাকাছি -> পরিষ্কার trending market
        মান ০-এর কাছাকাছি -> choppy/ranging market (একবার লাল একবার সবুজ করে ঘোরা)
        """
        closes = list(self._closes_1m)
        if len(closes) < 3:
            return None

        net_change = abs(closes[-1] - closes[0])
        total_movement = sum(
            abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))
        )

        if total_movement == 0:
            return 0.0

        return net_change / total_movement

    def _ema_gap_ok(self):
        """
        EMA9 আর EMA12 এর মধ্যে দূরত্ব যথেষ্ট কিনা।
        দূরত্ব কম মানে EMA দুটো প্রায় সমান্তরাল -> flat market, trend নেই।
        """
        if self.ema9.value is None or self.ema12.value is None:
            return False

        gap = abs(self.ema9.value - self.ema12.value)
        gap_pct = gap / self.ema12.value if self.ema12.value else 0

        return gap_pct >= self.min_ema_gap_pct

    # ------------------------------------------------------------------
    # Candle updates
    # ------------------------------------------------------------------
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
            self._closes_1m.append(close)

            e9 = self.ema9.update(close)
            e12 = self.ema12.update(close)

            er = self._efficiency_ratio()
            gap_ok = self._ema_gap_ok()

            # ---- choppiness filter ----
            if er is not None and er < self.min_efficiency_ratio:
                self.trend = None          # market এলোমেলো, ranging -> কোনো trade না
            elif not gap_ok:
                self.trend = None          # EMA প্রায় সমতল -> real trend নেই
            elif e9 > e12:
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
