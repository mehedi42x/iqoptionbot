import time

class Strategy:
    def __init__(self):
        self.last_direction = "sell"
        self.entry_time = 0

    def update_market_data(self, price, data=None):
        pass

    def check_signal(self, current_price):
        if self.last_direction == "sell":
            self.last_direction = "buy"
        else:
            self.last_direction = "sell"

        self.entry_time = time.time()
        return self.last_direction

    def check_close_signal(self, position, current_price, live_pnl):
        open_time = position.get("open_time") or self.entry_time
        if open_time and (time.time() - open_time >= 60):
            return True
        return False
