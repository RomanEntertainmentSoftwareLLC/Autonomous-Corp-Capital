"""Registry of strategy plugins."""

from __future__ import annotations

from typing import Dict, List, Type

from tradebot.strategies.base import StrategyPlugin
from tradebot.strategies.breakout import BreakoutStrategy
from tradebot.strategies.ema_crossover import EMACrossoverStrategy
from tradebot.strategies.hybrid_ema_rsi import HybridEMARsiStrategy
from tradebot.strategies.mean_reversion_v2 import MeanReversionV2Strategy
from tradebot.strategies.ml_trader import MLTraderStrategy
from tradebot.strategies.rsi_mean_reversion import RSIMeanReversionStrategy

STRATEGY_REGISTRY: Dict[str, Type[StrategyPlugin]] = {
    BreakoutStrategy.name: BreakoutStrategy,
    EMACrossoverStrategy.name: EMACrossoverStrategy,
    HybridEMARsiStrategy.name: HybridEMARsiStrategy,
    RSIMeanReversionStrategy.name: RSIMeanReversionStrategy,
    MeanReversionV2Strategy.name: MeanReversionV2Strategy,
    MLTraderStrategy.name: MLTraderStrategy,
}


def available_strategies() -> List[str]:
    return sorted(STRATEGY_REGISTRY.keys())


def strategy_by_name(name: str) -> Type[StrategyPlugin]:
    candidate = STRATEGY_REGISTRY.get(name)
    if not candidate:
        available = ", ".join(available_strategies())
        raise ValueError(f"Strategy '{name}' is unknown. Available: {available}")
    return candidate
