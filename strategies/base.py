from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict


@dataclass
class Signal:
    action: str        # "buy", "sell", "close"
    instrument: str
    confidence: float = 1.0
    reason: str = ""
    leverage: int = 10
    amount: float = 10.0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class BaseStrategy(ABC):
    def __init__(self, name: str = "BaseStrategy"):
        self.name = name

    @abstractmethod
    def get_signal(self, data: Dict) -> Optional[Signal]:
        """
        data dict-এ থাকবে:
        - candles: {timeframe: pd.DataFrame}
        - current_price: float
        - position: dict or None
        - balance: float
        - equity: float
        """
        pass
