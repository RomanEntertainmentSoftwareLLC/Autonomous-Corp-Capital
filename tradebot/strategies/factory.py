"""Strategy factory & registry helpers."""

from typing import Type

from tradebot.strategies.base import StrategyProtocol
from tradebot.strategies.registry import STRATEGY_REGISTRY, strategy_by_name




def resolve_strategy_name(symbol_config: dict) -> str:
    strategy_spec = symbol_config.get("strategy")
    if isinstance(strategy_spec, dict):
        strategy_name = strategy_spec.get("name")
    else:
        strategy_name = strategy_spec

    strategy_name = (strategy_name or "ema_crossover").strip().lower()
    return strategy_name


def _validate_strategy_config(symbol_config: dict, strategy_cls: Type[StrategyProtocol]) -> None:
    metadata = getattr(strategy_cls, "metadata", None)
    if not metadata:
        return
    missing = [key for key in metadata.required_config if key not in symbol_config]
    if missing:
        raise ValueError(
            f"Symbol {symbol_config.get('name')} requires {', '.join(missing)} for strategy '{metadata.name}'"
        )


def build_strategy(symbol_config: dict) -> StrategyProtocol:
    strategy_name = resolve_strategy_name(symbol_config)
    strategy_cls = strategy_by_name(strategy_name)
    _validate_strategy_config(symbol_config, strategy_cls)
    return strategy_cls(symbol_config)
