"""Strategy base interfaces and shared types."""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Protocol


@dataclass
class Signal:
    direction: str  # BUY, SELL, HOLD
    confidence: float
    reason: str


@dataclass
class StrategyMetadata:
    name: str
    description: str
    category: str
    required_config: Iterable[str]
    supports_ml: bool
    version: str = "1.0"
    author: str = "OpenClaw Team"
    risk_profile: str = "medium"
    parameters: Iterable[str] = tuple()


class StrategyPlugin(Protocol):
    """Contract every strategy must fulfill."""

    metadata: StrategyMetadata

    def __init__(self, symbol_config: Dict[str, Any]) -> None:
        ...

    def update(self, price: float) -> Signal:
        ...


StrategyProtocol = StrategyPlugin
