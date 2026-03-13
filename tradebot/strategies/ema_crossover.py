"""EMA crossover strategy implementation."""

from collections import deque
from typing import Deque, Optional

from tradebot.strategies.base import Signal, StrategyProtocol, StrategyMetadata
from tradebot.strategies.rsi import RSITracker


class EMACrossoverStrategy(StrategyProtocol):
    name = "ema_crossover"
    metadata = StrategyMetadata(
        name=name,
        description="EMA crossover with optional RSI confirmation.",
        category="trend",
        required_config=("ema_fast", "ema_slow"),
        supports_ml=False,
        version="1.0",
        author="OpenClaw Strategies",
        risk_profile="medium",
        parameters=("ema_fast", "ema_slow", "rsi_period", "rsi_buy", "rsi_sell"),
    )

    def __init__(self, symbol_config: dict) -> None:
        self.fast_period = symbol_config.get("ema_fast", 6)
        self.slow_period = symbol_config.get("ema_slow", 21)
        self.rsi_period = symbol_config.get("rsi_period", 14)

        lookback = max(self.fast_period, self.slow_period) + 5
        self.prices: Deque[float] = deque(maxlen=lookback)
        self.last_fast: Optional[float] = None
        self.last_slow: Optional[float] = None
        self.prev_relation: Optional[str] = None
        self.rsi_tracker = RSITracker(self.rsi_period)
        self.current_rsi: Optional[float] = None

    def _ema(self, period: int, last_ema: Optional[float]) -> Optional[float]:
        if len(self.prices) < period:
            return None

        prices = list(self.prices)[-period:]
        if last_ema is None:
            return sum(prices) / period

        alpha = 2 / (period + 1)
        return (self.prices[-1] - last_ema) * alpha + last_ema

    def update(self, price: float) -> Signal:
        self.prices.append(price)
        fast = self._ema(self.fast_period, self.last_fast)
        slow = self._ema(self.slow_period, self.last_slow)
        rsi = self.rsi_tracker.update(price)

        direction = "HOLD"
        reason = "Awaiting EMA crossover"
        confidence = 0.0

        if fast is not None and slow is not None:
            relation = "above" if fast > slow else "below" if fast < slow else "equal"
            reason = f"EMA fast {fast:.2f} vs slow {slow:.2f}"

            if self.prev_relation == "below" and relation == "above":
                direction = "BUY"
                confidence = min(1.0, max(0.2, (fast - slow) / slow))
                reason = "Bullish EMA crossover"
            elif self.prev_relation == "above" and relation == "below":
                direction = "SELL"
                confidence = min(1.0, max(0.2, (slow - fast) / slow))
                reason = "Bearish EMA crossover"

            self.prev_relation = relation

        self.last_fast = fast
        self.last_slow = slow
        self.current_rsi = rsi

        return Signal(direction=direction, confidence=confidence, reason=reason)
