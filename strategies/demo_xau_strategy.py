from datetime import datetime
from .base import BaseStrategy, Signal

class DemoXAUStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("Demo_XAU_1Min_Cycle")
        self.last_trade_time = None
        self.is_buy_turn = True   # পর্যায়ক্রমে buy/sell

    def get_signal(self, data: dict):
        position = data.get('position')
        now = datetime.now()

        if self.last_trade_time is None:
            self.last_trade_time = now
            self.is_buy_turn = True
            return Signal("buy", "XAUUSD", 1.0, "Demo Initial Buy", leverage=10, amount=10)

        minutes_passed = (now - self.last_trade_time).total_seconds() / 60.0

        if position and minutes_passed >= 1.0:
            self.last_trade_time = now
            return Signal("close", "XAUUSD", 1.0, "Demo 1 Minute Close", leverage=10, amount=10)

        if not position and minutes_passed >= 0.3:
            self.last_trade_time = now
            action = "buy" if self.is_buy_turn else "sell"
            self.is_buy_turn = not self.is_buy_turn
            return Signal(action, "XAUUSD", 1.0, f"Demo Cycle - {action.upper()}", leverage=10, amount=10)

        return None
