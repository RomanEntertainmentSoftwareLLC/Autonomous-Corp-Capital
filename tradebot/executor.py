"""Legacy Executor compatibility wrapper."""

from typing import Any, Dict

from tradebot.execution import ExecutionEngine
from tradebot.portfolio import Portfolio
from tradebot.risk import RiskManager


class Executor:
    """Wrapper that keeps the old Executor API while using the new modules."""

    def __init__(self, symbol_config: Dict[str, Any], risk_config: Dict[str, Any]) -> None:
        starting_balance = symbol_config.get("starting_balance", 100.0)
        portfolio = Portfolio(cash=starting_balance)
        self._risk = RiskManager(symbol_config, risk_config, portfolio)
        self._execution = ExecutionEngine(portfolio)

    def evaluate_signal(self, signal: Dict[str, Any], tick: Dict[str, Any]):
        decision = self._risk.evaluate_signal(signal, tick)
        return self._execution.apply(decision, tick)

    def portfolio_snapshot(self, price: float) -> Dict[str, Any]:
        return self._execution.portfolio_snapshot(price)
