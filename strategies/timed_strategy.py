# strategies/timed_strategy.py
import random

def get_signal(data):
    # এটি একটি ডেমো স্ট্রাটেজি যা র‍্যান্ডমলি বাই বা সেল দিবে
    # আপনি এখানে আপনার লজিক (RSI/Moving Average) যোগ করতে পারেন
    signals = ['buy', 'sell']
    return random.choice(signals)
