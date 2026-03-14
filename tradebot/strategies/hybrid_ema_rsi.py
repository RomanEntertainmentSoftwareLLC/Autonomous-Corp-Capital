"""Hybrid EMA/RSI strategy plugin."""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional

from tradebot.strategies.base import Signal, StrategyMetadata, StrategyProtocol


class HybridEMARsiStrategy(StrategyProtocol):
    name = "hybrid_ema_rsi"
    metadata = StrategyMetadata(
        name=name,
        description="EMA crossover confirmed by RSI confirmation zones.",
        category="hybrid",
        required_config=("ema_fast", "ema_slow", "rsi_period", "rsi_oversold", "rsi_overbought"),
        supports_ml=False,
        version="1.0",
        author="OpenClaw Hybrid",
        risk_profile="medium",
        parameters=("ema_fast", "ema_slow", "rsi_period", "rsi_oversold", "rsi_overbought"),
    )

    def __init__(self, symbol_config: Dict[str, object]) -> None:
        self.fast_period = int(symbol_config.get("ema_fast", 6))
        self.slow_period = int(symbol_config.get("ema_slow", 21))
        self.rsi_period = int(symbol_config.get("rsi_period", 14))
        self.rsi_oversold = int(symbol_config.get("rsi_oversold", symbol_config.get("rsi_buy", 30)))
        self.rsi_overbought = int(symbol_config.get("rsi_overbought", symbol_config.get("rsi_sell", 70)))
        lookback = max(self.fast_period, self.slow_period) + 5
        self.prices: Deque[float] = deque(maxlen=lookback)
        self.rsi_vals: Deque[float] = deque(maxlen=self.rsi_period)
        self.last_price: Optional[float] = None
        self.last_fast: Optional[float] = None
        self.last_slow: Optional[float] = None

    def _ema(self, period: int, last: Optional[float]) -> Optional[float]:
        if len(self.prices) < period:
            return None
        values = list(self.prices)[-period:]
        alpha = 2 / (period + 1)
        if last is None:
            return sum(values) / period
        return (self.prices[-1] - last) * alpha + last

    def _rsi(self, price: float) -> Optional[float]:
        if self.last_price is None:
            self.last_price = price
            return None
        delta = price - self.last_price
        self.last_price = price
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        self.rsi_vals.append(gain if gain else -loss)
        if len(self.rsi_vals) < self.rsi_period:
            return None
        avg_gain = sum(v for v in self.rsi_vals if v > 0) / self.rsi_period
        avg_loss = sum(-v for v in self.rsi_vals if v < 0) / self.rsi_period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def update(self, price: float) -> Signal:
        self.prices.append(price)
        fast = self._ema(self.fast_period, self.last_fast)
        slow = self._ema(self.slow_period, self.last_slow)
        self.last_fast = fast
        self.last_slow = slow
        rsi = self._rsi(price)
        signal = "HOLD"
        confidence = 0.0
        reason = "Awaiting confirmation"
        if fast and slow and rsi is not None:
            if fast > slow and rsi < self.rsi_overbought:
                signal = "BUY"
                confidence = min(1.0, (fast - slow) / slow + (1 - (rsi / 100)))
                reason = "Bullish EMA while RSI remains below overbought"
            elif fast < slow and rsi > self.rsi_oversold:
                signal = "SELL"
                confidence = min(1.0, (slow - fast) / slow + (rsi / 100))
                reason = "Bearish EMA while RSI is above oversold"
        return Signal(direction=signal, confidence=confidence, reason=reason)
