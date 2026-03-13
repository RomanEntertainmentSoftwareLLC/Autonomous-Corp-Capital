"""A second mean reversion strategy using SMA deviation."""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional

from tradebot.strategies.base import Signal, StrategyMetadata, StrategyProtocol


class MeanReversionV2Strategy(StrategyProtocol):
    name = "mean_reversion_v2"
    metadata = StrategyMetadata(
        name=name,
        description="Mean reversion based on deviation from short-term SMA.",
        category="mean_reversion",
        required_config=("sma_period", "z_threshold"),
        supports_ml=False,
    )

    def __init__(self, symbol_config: Dict[str, object]) -> None:
        self.period = int(symbol_config.get("sma_period", 10))
        self.z_threshold = float(symbol_config.get("z_threshold", 1.4))
        self.prices: Deque[float] = deque(maxlen=self.period)

    def update(self, price: float) -> Signal:
        self.prices.append(price)
        if len(self.prices) < self.period:
            return Signal(direction="HOLD", confidence=0.0, reason="warming up")
        sma = sum(self.prices) / len(self.prices)
        variance = sum((p - sma) ** 2 for p in self.prices) / len(self.prices)
        std = variance ** 0.5
        if std == 0:
            return Signal(direction="HOLD", confidence=0.0, reason="flat" )
        z = (price - sma) / std
        if z >= self.z_threshold:
            return Signal(direction="SELL", confidence=min(1.0, z / 3), reason="Price above SMA (z=%.2f)" % z)
        if z <= -self.z_threshold:
            return Signal(direction="BUY", confidence=min(1.0, -z / 3), reason="Price below SMA (z=%.2f)" % z)
        return Signal(direction="HOLD", confidence=0.2, reason="Near SMA")
