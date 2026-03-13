"""RSI mean reversion strategy implementation."""

from typing import Optional

from tradebot.strategies.base import Signal, StrategyMetadata, StrategyProtocol
from tradebot.strategies.rsi import RSITracker


class RSIMeanReversionStrategy(StrategyProtocol):
    name = "rsi_mean_reversion"
    metadata = StrategyMetadata(
        name=name,
        description="RSI mean reversion with configurable thresholds.",
        category="mean_reversion",
        required_config=("rsi_period", "rsi_buy", "rsi_sell"),
        supports_ml=False,
        version="2.0",
        author="OpenClaw Strategies",
        risk_profile="low",
        parameters=("rsi_period", "rsi_buy", "rsi_sell"),
    )

    def __init__(self, symbol_config: dict) -> None:
        self.rsi_period = symbol_config.get("rsi_period", 14)
        self.rsi_buy = symbol_config.get("rsi_buy", 30)
        self.rsi_sell = symbol_config.get("rsi_sell", 70)
        self.rsi_tracker = RSITracker(self.rsi_period)
        self.position_open = False

    def update(self, price: float) -> Signal:
        rsi = self.rsi_tracker.update(price)
        direction = "HOLD"
        confidence = 0.0
        reason = "Awaiting RSI extremes"

        if rsi is not None:
            if rsi <= self.rsi_buy and not self.position_open:
                direction = "BUY"
                confidence = min(1.0, max(0.2, (self.rsi_buy - rsi) / max(self.rsi_buy, 1)))
                reason = f"RSI {rsi:.2f} below threshold {self.rsi_buy}"
                self.position_open = True
            elif rsi >= self.rsi_sell and self.position_open:
                direction = "SELL"
                confidence = min(1.0, max(0.2, (rsi - self.rsi_sell) / max(100 - self.rsi_sell, 1)))
                reason = f"RSI {rsi:.2f} above threshold {self.rsi_sell}"
                self.position_open = False
            else:
                reason = f"RSI {rsi:.2f} (waiting for extreme)"

        return Signal(direction=direction, confidence=confidence, reason=reason)
