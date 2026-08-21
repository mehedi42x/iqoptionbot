from .base import BaseStrategy

class Strategy(BaseStrategy):
    def __init__(self):
        # ধাপ ১: ৫ মিনিটের চার্ট ডেটা (Support, Resistance, Trend)
        self.lookback_period = 10 # সাপোর্ট/রেজিস্ট্যান্স বের করার জন্য পেছনের ১০টি ক্যান্ডেল দেখবে
        self.highs_5m = []
        self.lows_5m = []
        
        self.support_level = None
        self.resistance_level = None
        self.trend = None

        # ধাপ ২: ব্রেকআউট ট্র্যাকিং
        self.breakout_direction = None
        self.breakout_level = None

        # ক্যান্ডেল স্টেট ট্র্যাকিং
        self._current_5m = None
        self._current_1m = None
        self._current_5s = None

    def update_5m(self, candle):
        """ ৫ মিনিটের চার্টে সাপোর্ট, রেজিস্ট্যান্স এবং ট্রেন্ড অ্যানালাইসিস """
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

        # ৫ মিনিটের ক্যান্ডেল ক্লোজ হয়েছে
        closed_candle = self._current_5m
        high = closed_candle.get("high")
        low = closed_candle.get("low")
        close = closed_candle.get("close")

        if high is not None and low is not None and close is not None:
            self.highs_5m.append(high)
            self.lows_5m.append(low)

            if len(self.highs_5m) > self.lookback_period:
                self.highs_5m.pop(0)
                self.lows_5m.pop(0)

            # সাপোর্ট ও রেজিস্ট্যান্স নির্ধারণ (সর্বোচ্চ High এবং সর্বনিম্ন Low)
            self.resistance_level = max(self.highs_5m)
            self.support_level = min(self.lows_5m)

            # ট্রেন্ড নির্ধারণ: প্রাইস যদি মিড-পয়েন্টের উপরে থাকে তবে Up, নিচে থাকলে Down
            mid_point = (self.resistance_level + self.support_level) / 2
            if close > mid_point:
                self.trend = "up"
            elif close < mid_point:
                self.trend = "down"

        self._current_5m = candle.copy()

    def update_1m(self, candle):
        """ ১ মিনিটের চার্টে ব্রেকআউট কনফার্মেশন """
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

        # ১ মিনিটের ক্যান্ডেল ক্লোজ হয়েছে
        closed_candle = self._current_1m
        close = closed_candle.get("close")

        if close is not None and self.resistance_level is not None and self.support_level is not None:
            # Up Trend - Resistance Breakout (১ মিনিটের ক্যান্ডেল ৫ মিনিটের রেজিস্ট্যান্স ব্রেক করলে)
            if self.trend == "up" and close > self.resistance_level:
                self.breakout_direction = "up"
                self.breakout_level = self.resistance_level
            
            # Down Trend - Support Breakout (১ মিনিটের ক্যান্ডেল ৫ মিনিটের সাপোর্ট ব্রেক করলে)
            elif self.trend == "down" and close < self.support_level:
                self.breakout_direction = "down"
                self.breakout_level = self.support_level

        self._current_1m = candle.copy()

    def update_5s(self, candle):
        """ ৫ সেকেন্ডের চার্ট লাইভ ট্র্যাকিং (Retest এর জন্য) """
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

        self._current_5s = candle.copy()

    def check_signal(self):
        """ ধাপ ৩: রিটেস্ট এবং এন্ট্রি লজিক """
        # যদি কোনো ব্রেকআউট না হয়ে থাকে, তবে সিগন্যাল দিবে না
        if self.breakout_direction is None or self.breakout_level is None:
            return None
        
        if self._current_5s is None:
            return None

        # ৫ সেকেন্ডের চার্টের বর্তমান রানিং প্রাইস
        current_price = self._current_5s.get("close") or self._current_5s.get("price")
        if current_price is None:
            return None
        
        signal = None
        
        # রিটেস্ট (Retest) লজিক
        if self.breakout_direction == "up":
            # ব্রেকআউটের পর প্রাইস রিট্রেস করে পূর্বের রেজিস্ট্যান্সের (যা এখন সাপোর্ট) কাছে ফিরে এলে Call
            if current_price <= self.breakout_level:
                signal = "call"
                
        elif self.breakout_direction == "down":
            # ব্রেকআউটের পর প্রাইস রিট্রেস করে পূর্বের সাপোর্টের (যা এখন রেজিস্ট্যান্স) কাছে ফিরে এলে Put
            if current_price >= self.breakout_level:
                signal = "put"

        # সিগন্যাল পেয়ে গেলে ব্রেকআউট স্টেট রিসেট করতে হবে (যাতে বারবার একই সিগন্যাল না পড়ে)
        if signal:
            self.breakout_direction = None
            self.breakout_level = None
            return signal

        return None
