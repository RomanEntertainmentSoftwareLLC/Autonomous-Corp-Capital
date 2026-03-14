"""Risk approval helpers for the trade bot."""

import time
from dataclasses import dataclass
from typing import Any, Dict

from tradebot.portfolio import Portfolio


@dataclass
class TradeDecision:
    direction: str
    reason: str
    allowed: bool
    block_reason: str
    action: str
    executed: bool
    cash_before: float
    cash_after: float
    position_before: float
    position_after: float
    account_value: float
    price: float
    source: str
    pnl: float | None = None
    trade_count: int = 0
    unrealized_pnl: float = 0.0
    trade_units: float = 0.0
    strategy_name: str | None = None
    realized_pnl_total: float = 0.0
    max_drawdown_percent: float = 0.0
    win_rate_percent: float = 0.0


class RiskManager:
    """Handles risk approvals for BUY/SELL signals."""

    def __init__(self, symbol_config: Dict[str, Any], risk_config: Dict[str, Any], portfolio: Portfolio) -> None:
        self.portfolio = portfolio
        self.symbol = symbol_config.get("name", "UNKNOWN")
        self.order_value = symbol_config.get("order_size", 5.0)
        self.min_balance = risk_config.get("min_balance", 25.0)
        self.max_daily_trades = risk_config.get("max_daily_trades", 20)
        self.max_position_fraction = risk_config.get("max_position_size", 0.5)
        self.cooldown_seconds = risk_config.get("cooldown_seconds", 60)

    def evaluate_signal(self, signal: Dict[str, Any], tick: Dict[str, Any]) -> TradeDecision:
        direction = signal.get("direction", "HOLD")
        price = tick["price"]
        now = time.time()
        cash_before = round(self.portfolio.cash, 2)
        position_before = round(self.portfolio.position_units, 6)

        decision = TradeDecision(
            direction=direction,
            reason=signal.get("reason", ""),
            allowed=False,
            block_reason="",
            action="HOLD",
            executed=False,
            cash_before=cash_before,
            cash_after=cash_before,
            position_before=position_before,
            position_after=position_before,
            account_value=round(self.portfolio.account_value(price), 2),
            price=price,
            source=tick.get("source", "unknown"),
            unrealized_pnl=round(self.portfolio.unrealized_pnl(price), 2),
            trade_count=self.portfolio.trade_count,
        )

        if direction in {"BUY", "SELL"} and self._is_cooldown_active(direction, now):
            delay = self.cooldown_seconds - (now - self.portfolio.last_action_time)
            decision.block_reason = f"{direction} blocked by cooldown ({int(delay)}s remaining)"
            decision.reason = "Cooldown guard"
            return decision

        if direction == "BUY":
            units = self._can_buy(price)
            decision.trade_units = units
            if units > 0:
                decision.allowed = True
                decision.action = "BUY"
                decision.reason = "Risk guard approved BUY"
            else:
                decision.block_reason = "Risk guard blocked BUY"
        elif direction == "SELL":
            if self.portfolio.position_units > 0:
                decision.allowed = True
                decision.action = "SELL"
                decision.trade_units = self.portfolio.position_units
                decision.reason = "Risk guard approved SELL"
            else:
                decision.block_reason = "No position to SELL"
        else:
            decision.block_reason = "Signal is HOLD"

        return decision

    def _can_buy(self, price: float) -> float:
        if self.portfolio.trade_count >= self.max_daily_trades:
            return 0.0
        if self.portfolio.cash - self.min_balance <= 0:
            return 0.0
        if self.portfolio.position_units > 0:
            return 0.0
        units = self._proposed_units(price)
        if units <= 0:
            return 0.0
        proposed_value = units * price
        account = self.portfolio.account_value(price)
        if proposed_value > account * self.max_position_fraction:
            return 0.0
        return units

    def _proposed_units(self, price: float) -> float:
        available = max(0.0, self.portfolio.cash - self.min_balance)
        purchase_value = min(self.order_value, available)
        if purchase_value <= 0:
            return 0.0
        return purchase_value / price

    def _is_cooldown_active(self, direction: str, now: float) -> bool:
        if self.portfolio.last_action != direction:
            return False
        return (now - self.portfolio.last_action_time) < self.cooldown_seconds
