"""Breakout strategy that watches recent ranges for breakouts."""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional

from tradebot.strategies.base import Signal, StrategyMetadata, StrategyProtocol


class BreakoutStrategy(StrategyProtocol):
    name = "breakout"
    metadata = StrategyMetadata(
        name=name,
        description="Detects price breaks outside a recent high/low range.",
        category="breakout",
        required_config=("lookback", "threshold"),
        supports_ml=False,
    )

    def __init__(self, symbol_config: Dict[str, object]) -> None:
        self.lookback = int(symbol_config.get("lookback", 10))
        self.threshold = float(symbol_config.get("threshold", 0.002))
        self.prices: Deque[float] = deque(maxlen=self.lookback)
        self.last_signal = "HOLD"

    def update(self, price: float) -> Signal:
        self.prices.append(price)
        if len(self.prices) < self.lookback:
            return Signal(direction="HOLD", confidence=0.0, reason="warming up")

        high = max(self.prices)
        low = min(self.prices)

        if price > high * (1 + self.threshold):
            self.last_signal = "BUY"
            return Signal(direction="BUY", confidence=0.7, reason="Breakout above recent high")
        if price < low * (1 - self.threshold):
            self.last_signal = "SELL"
            return Signal(direction="SELL", confidence=0.7, reason="Breakout below recent low")

        return Signal(direction="HOLD", confidence=0.1, reason="Within range")
