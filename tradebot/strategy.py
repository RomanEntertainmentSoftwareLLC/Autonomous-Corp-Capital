"""Shim layer keeping the legacy strategy import stable."""

from tradebot.strategies.base import Signal
from tradebot.strategies.ema_crossover import EMACrossoverStrategy

Strategy = EMACrossoverStrategy

__all__ = ["Signal", "Strategy", "EMACrossoverStrategy"]
