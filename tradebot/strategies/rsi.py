"""Shared RSI helper for multiple strategies."""

from collections import deque
from typing import Deque, Optional


class RSITracker:
    def __init__(self, period: int) -> None:
        self.period = max(1, period)
        self.gains: Deque[float] = deque(maxlen=self.period)
        self.losses: Deque[float] = deque(maxlen=self.period)
        self.last_price: Optional[float] = None

    def update(self, price: float) -> Optional[float]:
        if self.last_price is None:
            self.last_price = price
            return None

        delta = price - self.last_price
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        self.gains.append(gain)
        self.losses.append(loss)
        self.last_price = price

        if len(self.gains) < self.period or len(self.losses) < self.period:
            return None

        avg_gain = sum(self.gains) / self.period
        avg_loss = sum(self.losses) / self.period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
