"""Simulated execution engine for paper/backtest trading."""

import time
from typing import Any, Dict

from tradebot.portfolio import Portfolio
from tradebot.risk import TradeDecision


class ExecutionEngine:
    """Handles the application of approved trades onto the portfolio state."""

    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    def _finalize_decision(self, decision: TradeDecision, price: float) -> TradeDecision:
        self.portfolio.update_stats(price)
        snapshot = self.portfolio.snapshot(price)
        decision.realized_pnl_total = snapshot["realized_pnl"]
        decision.max_drawdown_percent = snapshot["max_drawdown_percent"]
        decision.win_rate_percent = snapshot["win_rate_percent"]
        return decision

    def apply(self, decision: TradeDecision, tick: Dict[str, Any]) -> TradeDecision:
        price = tick["price"]
        now = time.time()
        decision.price = price
        decision.source = tick.get("source", "unknown")

        if not decision.allowed or decision.trade_units <= 0:
            decision.executed = False
            decision.cash_after = round(self.portfolio.cash, 2)
            decision.position_after = round(self.portfolio.position_units, 6)
            decision.account_value = round(self.portfolio.account_value(price), 2)
            decision.unrealized_pnl = round(self.portfolio.unrealized_pnl(price), 2)
            decision.trade_count = self.portfolio.trade_count
            return self._finalize_decision(decision, price)

        if decision.action == "BUY":
            units = decision.trade_units
            self.portfolio.position_units += units
            self.portfolio.cash -= units * price
            self.portfolio.entry_price = price
            self.portfolio.trade_count += 1
            self.portfolio.last_action = "BUY"
            self.portfolio.last_action_time = now
            decision.executed = True
            decision.cash_after = round(self.portfolio.cash, 2)
            decision.position_after = round(self.portfolio.position_units, 6)
            decision.reason = "Simulation BUY executed"
        elif decision.action == "SELL":
            units = decision.trade_units
            revenue = units * price
            pnl = revenue - units * self.portfolio.entry_price
            self.portfolio.cash += revenue
            self.portfolio.realized_pnl += pnl
            if pnl > 0:
                self.portfolio.win_trades += 1
            elif pnl < 0:
                self.portfolio.loss_trades += 1
            self.portfolio.position_units = 0.0
            self.portfolio.entry_price = 0.0
            self.portfolio.trade_count += 1
            self.portfolio.last_action = "SELL"
            self.portfolio.last_action_time = now
            decision.executed = True
            decision.cash_after = round(self.portfolio.cash, 2)
            decision.position_after = 0.0
            decision.pnl = round(pnl, 2)
            decision.reason = "Simulation SELL executed"
        else:
            decision.executed = False

        decision.account_value = round(self.portfolio.account_value(price), 2)
        decision.unrealized_pnl = round(self.portfolio.unrealized_pnl(price), 2)
        decision.trade_count = self.portfolio.trade_count
        return self._finalize_decision(decision, price)

    def portfolio_snapshot(self, price: float) -> Dict[str, Any]:
        return self.portfolio.snapshot(price)
