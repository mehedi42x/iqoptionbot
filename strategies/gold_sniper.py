import time

class Strategy:
    def __init__(self):
        # ১৫ সেকেন্ডের ক্যান্ডেল ডেটা
        self.candles_15s = []
        self.current_candle_15s = None
        self.last_checked_15s_start = 0
        
        # ৬০ সেকেন্ড (১ মিনিট) ক্যান্ডেল ডেটা
        self.candles_60s = []
        self.current_candle_60s = None
        self.last_checked_60s_start = 0

    def update_market_data(self, price, raw_data):
        """লাইভ প্রাইস থেকে ১৫ সেকেন্ড এবং ৬০ সেকেন্ডের ক্যান্ডেল তৈরি করবে এবং ক্লোজড ক্যান্ডেল হ্যান্ডেল করবে"""
        if price <= 0: return
        
        current_time = time.time()
        
        # --- 15 Second Candle Builder ---
        start_15s = (current_time // 15) * 15
        if self.current_candle_15s is None:
            self.current_candle_15s = {'open': price, 'high': price, 'low': price, 'close': price, 'start': start_15s}
        elif start_15s > self.current_candle_15s['start']:
            # আগের ১৫ সেকেন্ডের ক্যান্ডেলটি এখন অফিশিয়ালি ক্লোজ হয়ে গেছে! এটিকে লিস্টে যুক্ত করবো
            self.candles_15s.append(self.current_candle_15s)
            if len(self.candles_15s) > 100: self.candles_15s.pop(0)
            # নতুন ক্যান্ডেল শুরু
            self.current_candle_15s = {'open': price, 'high': price, 'low': price, 'close': price, 'start': start_15s}
        else:
            self.current_candle_15s['high'] = max(self.current_candle_15s['high'], price)
            self.current_candle_15s['low'] = min(self.current_candle_15s['low'], price)
            self.current_candle_15s['close'] = price

        # --- 60 Second Candle Builder ---
        start_60s = (current_time // 60) * 60
        if self.current_candle_60s is None:
            self.current_candle_60s = {'open': price, 'high': price, 'low': price, 'close': price, 'start': start_60s}
        elif start_60s > self.current_candle_60s['start']:
            # আগের ১ মিনিটের ক্যান্ডেলটি এখন অফিশিয়ালি ক্লোজ হয়ে গেছে! এটিকে লিস্টে যুক্ত করবো
            self.candles_60s.append(self.current_candle_60s)
            if len(self.candles_60s) > 100: self.candles_60s.pop(0)
            # নতুন ক্যান্ডেল শুরু
            self.current_candle_60s = {'open': price, 'high': price, 'low': price, 'close': price, 'start': start_60s}
        else:
            self.current_candle_60s['high'] = max(self.current_candle_60s['high'], price)
            self.current_candle_60s['low'] = min(self.current_candle_60s['low'], price)
            self.current_candle_60s['close'] = price

    def _calculate_ema_series(self, candles, period):
        """শুধুমাত্র ক্লোজ হয়ে যাওয়া ক্যান্ডেলগুলোর ওপর ভিত্তি করে EMA ক্যালকুলেশন"""
        if len(candles) < period + 1: 
            return None
        
        prices = [c['close'] for c in candles]
        k = 2 / (period + 1)
        
        ema = sum(prices[:period]) / period
        ema_list = [ema]
        for p in prices[period:]:
            ema = (p - ema) * k + ema
            ema_list.append(ema)
            
        if len(ema_list) >= 2:
            return ema_list[-2:] # সর্বশেষ দুটি ক্লোজড ক্যান্ডেলের EMA ভ্যালু
        return None

    def check_signal(self, current_price):
        """এন্ট্রি লজিক: শুধুমাত্র নতুন ১৫ সেকেন্ডের ক্যান্ডেল শুরু হওয়ার পর (অর্থাৎ আগের ক্যান্ডেল ক্লোজ হওয়ার পর) চেক করবে"""
        # নিশ্চিত করবো যে আমাদের কাছে এটলিস্ট নতুন ক্লোজড ক্যান্ডেল আছে
        if len(self.candles_60s) < 13 or len(self.candles_15s) < 13:
            return None

        # ডুপ্লিকেট সিগন্যাল এড়ানোর জন্য চেক করব যে এই ১৫ সেকেন্ডের ব্লকে অলরেডি চেক করা হয়েছে কি না
        latest_15s_start = self.candles_15s[-1]['start']
        if latest_15s_start == self.last_checked_15s_start:
            return None # একই ক্যান্ডেলে বারবার চেক করবে না

        # ১ মিনিটের ক্যান্ডেলে EMA 9 এবং 12 (ক্লোজড ক্যান্ডেল দিয়ে ট্রেন্ড চেক)
        ema_9_60s = self._calculate_ema_series(self.candles_60s, 9)
        ema_12_60s = self._calculate_ema_series(self.candles_60s, 12)
        
        # ১৫ সেকেন্ডের ক্যান্ডেলে EMA 2 এবং 3 (ক্লোজড ক্যান্ডেল দিয়ে ক্রসওভার চেক)
        ema_2_15s = self._calculate_ema_series(self.candles_15s, 2)
        ema_3_15s = self._calculate_ema_series(self.candles_15s, 3)

        if not all([ema_9_60s, ema_12_60s, ema_2_15s, ema_3_15s]):
            return None

        # চেক করার পর এই ব্লকের স্টার্ট টাইম সেভ করে রাখব যাতে ডুপ্লিকেট না হয়
        self.last_checked_15s_start = latest_15s_start

        curr_ema_9_60s = ema_9_60s[-1]
        curr_ema_12_60s = ema_12_60s[-1]

        is_uptrend = curr_ema_9_60s > curr_ema_12_60s
        is_downtrend = curr_ema_9_60s < curr_ema_12_60s

        prev_ema_2, curr_ema_2 = ema_2_15s[0], ema_2_15s[1]
        prev_ema_3, curr_ema_3 = ema_3_15s[0], ema_3_15s[1]

        # ক্রসওভার শুধুমাত্র ক্লোজড ক্যান্ডেলের ডেটা দিয়ে কনফার্ম হচ্ছে
        cross_up_15s = (prev_ema_2 <= prev_ema_3) and (curr_ema_2 > curr_ema_3)
        cross_down_15s = (prev_ema_2 >= prev_ema_3) and (curr_ema_2 < curr_ema_3)

        if is_uptrend and cross_up_15s:
            return "BUY"
            
        if is_downtrend and cross_down_15s:
            return "SELL"

        return None

    def check_close_signal(self, position, current_price, live_pnl):
        """ট্রেড ক্লোজ লজিক: ১৫ সেকেন্ডের ক্যান্ডেল ক্লোজ হওয়ার পর EMA 9 এবং 12 এর ক্রসওভার চেক করবে"""
        if len(self.candles_15s) < 13:
            return False

        ema_9_15s = self._calculate_ema_series(self.candles_15s, 9)
        ema_12_15s = self._calculate_ema_series(self.candles_15s, 12)

        if not ema_9_15s or not ema_12_15s:
            return False

        prev_ema_9, curr_ema_9 = ema_9_15s[0], ema_9_15s[1]
        prev_ema_12, curr_ema_12 = ema_12_15s[0], ema_12_15s[1]

        direction = position.get("dir", "")

        if direction == "BUY":
            # Buy ক্লোজ হবে যদি ক্লোজড ক্যান্ডেলে EMA 9, EMA 12 কে উপর থেকে নিচে ক্রস করে
            cross_down = (prev_ema_9 >= prev_ema_12) and (curr_ema_9 < curr_ema_12)
            if cross_down:
                return True
                
        elif direction == "SELL":
            # Sell ক্লোজ হবে যদি ক্লোজড ক্যান্ডেলে EMA 9, EMA 12 কে নিচ থেকে উপরে ক্রস করে
            cross_up = (prev_ema_9 <= prev_ema_12) and (curr_ema_9 > curr_ema_12)
            if cross_up:
                return True

        return False
