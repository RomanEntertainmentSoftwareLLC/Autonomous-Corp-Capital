"""Simple market regime tagging based on recent price behavior."""

from __future__ import annotations

from statistics import mean, stdev
from typing import Iterable, List

TREND_THRESHOLD = 0.002
VOLATILITY_HIGH = 0.012
VOLATILITY_LOW = 0.003


def classify_regime(prices: Iterable[float], lookback: int = 20) -> str:
    """Return a regime label for the last `lookback` prices."""

    recent: List[float] = [p for p in prices if p is not None]
    if len(recent) < 2:
        return "unknown"
    recent = recent[-lookback:]

    returns: List[float] = []
    for prev, curr in zip(recent, recent[1:]):
        if prev == 0:
            continue
        returns.append((curr - prev) / prev)

    if not returns:
        return "unknown"

    avg_return = mean(returns)
    vol = stdev(returns) if len(returns) > 1 else 0.0

    if vol >= VOLATILITY_HIGH:
        label = "high_volatility"
    elif vol <= VOLATILITY_LOW:
        label = "low_volatility"
    elif avg_return > TREND_THRESHOLD:
        label = "trending_up"
    elif avg_return < -TREND_THRESHOLD:
        label = "trending_down"
    else:
        label = "ranging"

    return label
