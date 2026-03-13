"""Synthetic market generator for self-play training."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List

from random import Random


REGIME_CONFIG = {
    "trending_up": {"drift": 0.002, "vol": 0.001},
    "trending_down": {"drift": -0.002, "vol": 0.001},
    "ranging": {"drift": 0.0, "vol": 0.0008},
    "high_volatility": {"drift": 0.0, "vol": 0.0035},
    "low_volatility": {"drift": 0.0, "vol": 0.0003},
    "shock_event": {"drift": 0.0, "vol": 0.0025},
}


@dataclass
class SyntheticTick:
    timestamp: datetime
    symbol: str
    price: float
    source: str = "sim"

    def as_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "symbol": self.symbol,
            "price": self.price,
            "source": self.source,
        }


class SyntheticMarketGenerator:
    """Generate deterministic price streams for different regimes."""

    def __init__(
        self,
        symbol: str = "SIM/TEST",
        regime: str = "ranging",
        start_price: float = 100.0,
        interval_seconds: int = 60,
        seed: int | None = None,
    ) -> None:
        if regime not in REGIME_CONFIG:
            raise ValueError(f"Unknown regime '{regime}' (available: {list(REGIME_CONFIG)})")
        self.symbol = symbol
        self.regime = regime
        self.price = start_price
        self.interval = timedelta(seconds=interval_seconds)
        self.random = Random(seed)
        self.state = REGIME_CONFIG[regime]
        self.time = datetime.utcnow()
        self.shock_pending = regime == "shock_event"

    def _apply_regime(self) -> float:
        drift = self.state["drift"]
        vol = self.state["vol"]
        shock = 0.0
        if self.shock_pending and self.random.random() < 0.05:
            shock = self.price * 0.02 * (1 if self.random.random() < 0.5 else -1)
            self.shock_pending = False
        delta = drift * self.price + vol * self.price * self.random.gauss(0, 1) + shock
        return max(0.001, self.price + delta)

    def generate(self, steps: int = 100) -> Iterable[SyntheticTick]:
        for _ in range(steps):
            self.price = self._apply_regime()
            tick = SyntheticTick(timestamp=self.time, symbol=self.symbol, price=self.price)
            yield tick
            self.time += self.interval

    def as_feed(self, steps: int = 100) -> List[dict]:
        return [tick.as_dict() for tick in self.generate(steps)]


def example_usage() -> None:
    market = SyntheticMarketGenerator(symbol="BTC-USD", regime="trending_up", seed=1234)
    for tick in market.generate(5):
        print(tick.as_dict())


if __name__ == "__main__":
    example_usage()
