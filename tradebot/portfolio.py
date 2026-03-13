"""Virtual portfolio state for a company’s trading activities."""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Portfolio:
    cash: float
    position_units: float = 0.0
    entry_price: float = 0.0
    trade_count: int = 0
    last_action: str | None = None
    last_action_time: float = 0.0
    realized_pnl: float = 0.0
    win_trades: int = 0
    loss_trades: int = 0
    max_account_value: float = 0.0
    max_drawdown: float = 0.0

    def __post_init__(self) -> None:
        if self.max_account_value <= 0:
            self.max_account_value = self.cash

    def account_value(self, last_price: float) -> float:
        return self.cash + self.position_units * last_price

    def unrealized_pnl(self, last_price: float) -> float:
        if self.position_units <= 0 or self.entry_price <= 0:
            return 0.0
        return (last_price - self.entry_price) * self.position_units

    def update_stats(self, last_price: float) -> None:
        account_value = self.account_value(last_price)
        if account_value > self.max_account_value:
            self.max_account_value = account_value
        if self.max_account_value > 0:
            drawdown = (self.max_account_value - account_value) / self.max_account_value * 100
            self.max_drawdown = max(self.max_drawdown, drawdown)

    def snapshot(self, last_price: float) -> Dict[str, Any]:
        account_value = round(self.account_value(last_price), 2)
        unrealized = round(self.unrealized_pnl(last_price), 2)
        closed_trades = self.win_trades + self.loss_trades
        win_rate = round((self.win_trades / closed_trades) * 100, 2) if closed_trades else 0.0
        avg_entry = round(self.entry_price, 4) if self.position_units > 0 else 0.0
        return {
            "cash": round(self.cash, 2),
            "position_units": round(self.position_units, 6),
            "average_entry_price": avg_entry,
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": unrealized,
            "account_value": account_value,
            "total_trades": self.trade_count,
            "wins": self.win_trades,
            "losses": self.loss_trades,
            "win_rate_percent": win_rate,
            "max_drawdown_percent": round(self.max_drawdown, 2),
        }
