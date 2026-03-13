"""Strategy collection entry points."""

from tradebot.strategies.base import Signal, StrategyProtocol
from tradebot.strategies.ema_crossover import EMACrossoverStrategy
from tradebot.strategies.ml_trader import MLTraderStrategy
from tradebot.strategies.rsi_mean_reversion import RSIMeanReversionStrategy

__all__ = [
    "Signal",
    "StrategyProtocol",
    "EMACrossoverStrategy",
    "MLTraderStrategy",
    "RSIMeanReversionStrategy",
]
