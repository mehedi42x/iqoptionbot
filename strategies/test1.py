from .base import BaseStrategy


class Strategy(BaseStrategy):
    def __init__(self):
        # ধাপ ১: ৫ মিনিটের চার্ট ডেটা
        self.lookback_period = 10

        self.highs_5m = []
        self.lows_5m = []
        self.closes_5m = []

        self.support_level = None
        self.resistance_level = None
        self.trend = None

        # Breakout tracking
        self.breakout_direction = None
        self.breakout_level = None

        # Breakout-এর পরে price কতদূর গেছে
        self.breakout_extreme = None

        # Retest tracking
        self.retest_touched = False

        # Candle state tracking
        self._current_5m = None
        self._current_1m = None
        self._current_5s = None
        self._previous_5s = None

    def update_5m(self, candle):
        """5 মিনিটের চার্টে Support, Resistance এবং Market Structure Trend নির্ধারণ"""

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

        # আগের 5m candle close হয়েছে
        closed_candle = self._current_5m

        high = closed_candle.get("high")
        low = closed_candle.get("low")
        close = closed_candle.get("close")

        if high is not None and low is not None and close is not None:

            self.highs_5m.append(high)
            self.lows_5m.append(low)
            self.closes_5m.append(close)

            # Lookback সীমা
            if len(self.highs_5m) > self.lookback_period:
                self.highs_5m.pop(0)
                self.lows_5m.pop(0)
                self.closes_5m.pop(0)

            # --------------------------------------------------
            # Support / Resistance
            # --------------------------------------------------
            if len(self.highs_5m) >= 3:
                self.resistance_level = max(self.highs_5m[:-1])
                self.support_level = min(self.lows_5m[:-1])

            # --------------------------------------------------
            # Market Structure Trend
            # --------------------------------------------------
            if len(self.highs_5m) >= 4:

                previous_high = self.highs_5m[-3]
                latest_high = self.highs_5m[-1]

                previous_low = self.lows_5m[-3]
                latest_low = self.lows_5m[-1]

                # Higher High + Higher Low
                if latest_high > previous_high and latest_low > previous_low:
                    self.trend = "up"

                # Lower High + Lower Low
                elif latest_high < previous_high and latest_low < previous_low:
                    self.trend = "down"

        self._current_5m = candle.copy()

    def update_1m(self, candle):
        """1 মিনিটের চার্টে শক্তিশালী Breakout Confirmation"""

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

        # আগের 1m candle close হয়েছে
        closed_candle = self._current_1m

        open_price = closed_candle.get("open")
        high = closed_candle.get("high")
        low = closed_candle.get("low")
        close = closed_candle.get("close")

        if (
            open_price is not None
            and high is not None
            and low is not None
            and close is not None
            and self.resistance_level is not None
            and self.support_level is not None
        ):

            candle_range = high - low
            candle_body = abs(close - open_price)

            # Zero division protection
            if candle_range > 0:

                body_ratio = candle_body / candle_range

                # --------------------------------------------------
                # Bullish Breakout
                # --------------------------------------------------
                if self.trend == "up" and close > self.resistance_level:

                    # Candle-এর body যথেষ্ট শক্তিশালী হতে হবে
                    # এবং close candle-এর upper অংশে থাকতে হবে
                    upper_close_position = (
                        (close - low) / candle_range
                    )

                    if body_ratio >= 0.50 and upper_close_position >= 0.65:

                        self.breakout_direction = "up"
                        self.breakout_level = self.resistance_level
                        self.breakout_extreme = high
                        self.retest_touched = False

                # --------------------------------------------------
                # Bearish Breakout
                # --------------------------------------------------
                elif self.trend == "down" and close < self.support_level:

                    lower_close_position = (
                        (high - close) / candle_range
                    )

                    if body_ratio >= 0.50 and lower_close_position >= 0.65:

                        self.breakout_direction = "down"
                        self.breakout_level = self.support_level
                        self.breakout_extreme = low
                        self.retest_touched = False

        self._current_1m = candle.copy()

    def update_5s(self, candle):
        """5 সেকেন্ডের চার্টে Retest এবং Rejection tracking"""

        t = candle.get("from") or candle.get("at")
        if t is None:
            return

        if self._current_5s is None:
            self._current_5s = candle.copy()
            return

        current_t = self._current_5s.get("from") or self._current_5s.get("at")

        if t == current_t:
            self._current_5s = candle.copy()
            return

        # আগের 5s candle সংরক্ষণ
        self._previous_5s = self._current_5s.copy()

        self._current_5s = candle.copy()

    def check_signal(self):
        """Breakout → Retest → Rejection → Entry"""

        if (
            self.breakout_direction is None
            or self.breakout_level is None
            or self._current_5s is None
        ):
            return None

        candle = self._current_5s

        open_price = candle.get("open")
        high = candle.get("high")
        low = candle.get("low")
        close = candle.get("close")

        if (
            open_price is None
            or high is None
            or low is None
            or close is None
        ):
            return None

        candle_range = high - low

        if candle_range <= 0:
            return None

        body = abs(close - open_price)

        body_ratio = body / candle_range

        # ==========================================================
        # BULLISH BREAKOUT
        # ==========================================================
        if self.breakout_direction == "up":

            # Breakout-এর পর নতুন high track করা
            if self.breakout_extreme is None:
                self.breakout_extreme = high
            else:
                self.breakout_extreme = max(
                    self.breakout_extreme,
                    high
                )

            # Price breakout level থেকে কিছুটা দূরে গেছে কি না
            breakout_distance = (
                self.breakout_extreme - self.breakout_level
            )

            # খুব সামান্য breakout হলে retest ধরব না
            if breakout_distance > 0:
                required_move = max(
                    abs(self.breakout_level) * 0.0001,
                    breakout_distance * 0.25
                )

                has_moved_away = (
                    breakout_distance >= required_move
                )
            else:
                has_moved_away = False

            # ------------------------------------------------------
            # Retest
            # ------------------------------------------------------
            if has_moved_away:

                # Price আবার breakout level-এর কাছে এসেছে
                if low <= self.breakout_level:

                    self.retest_touched = True

                # --------------------------------------------------
                # Retest Rejection
                # --------------------------------------------------
                if self.retest_touched:

                    # Level-এর নিচে খুব বেশি ভেঙে গেলে setup বাতিল
                    invalidation_distance = max(
                        abs(self.breakout_level) * 0.0003,
                        breakout_distance * 0.50
                    )

                    if close < (
                        self.breakout_level - invalidation_distance
                    ):
                        self._reset_breakout()
                        return None

                    # Bullish rejection:
                    # নিচে wick + bullish close
                    lower_wick = min(
                        open_price,
                        close
                    ) - low

                    bullish_close = close > open_price

                    if (
                        bullish_close
                        and lower_wick > body
                        and body_ratio >= 0.30
                        and close >= self.breakout_level
                    ):
                        self._reset_breakout()
                        return "call"

        # ==========================================================
        # BEARISH BREAKOUT
        # ==========================================================
        elif self.breakout_direction == "down":

            # Breakout-এর পর নতুন low track করা
            if self.breakout_extreme is None:
                self.breakout_extreme = low
            else:
                self.breakout_extreme = min(
                    self.breakout_extreme,
                    low
                )

            # Breakout level থেকে price কতদূর গেছে
            breakout_distance = (
                self.breakout_level - self.breakout_extreme
            )

            if breakout_distance > 0:

                required_move = max(
                    abs(self.breakout_level) * 0.0001,
                    breakout_distance * 0.25
                )

                has_moved_away = (
                    breakout_distance >= required_move
                )
            else:
                has_moved_away = False

            # ------------------------------------------------------
            # Retest
            # ------------------------------------------------------
            if has_moved_away:

                # Price আবার breakout level-এর কাছে এসেছে
                if high >= self.breakout_level:

                    self.retest_touched = True

                # --------------------------------------------------
                # Retest Rejection
                # --------------------------------------------------
                if self.retest_touched:

                    # Level-এর উপরে বেশি উঠে গেলে setup বাতিল
                    invalidation_distance = max(
                        abs(self.breakout_level) * 0.0003,
                        breakout_distance * 0.50
                    )

                    if close > (
                        self.breakout_level + invalidation_distance
                    ):
                        self._reset_breakout()
                        return None

                    # Bearish rejection:
                    # উপরে wick + bearish close
                    upper_wick = high - max(
                        open_price,
                        close
                    )

                    bearish_close = close < open_price

                    if (
                        bearish_close
                        and upper_wick > body
                        and body_ratio >= 0.30
                        and close <= self.breakout_level
                    ):
                        self._reset_breakout()
                        return "put"

        return None

    def _reset_breakout(self):
        """Breakout state reset"""

        self.breakout_direction = None
        self.breakout_level = None
        self.breakout_extreme = None
        self.retest_touched = False
