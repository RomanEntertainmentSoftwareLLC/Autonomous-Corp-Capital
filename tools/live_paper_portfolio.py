"""Paper portfolio and capital allocation tracker."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

DEFAULT_TREASURY = 100.0
RESERVE_PERCENTAGE = 0.6
DEPLOYABLE_PERCENTAGE = 0.4
DEFAULT_COMPANIES = ["company_001", "company_002", "company_003", "company_004"]


class PortfolioState:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.parent_total = DEFAULT_TREASURY
        self.reserve = self.parent_total * RESERVE_PERCENTAGE
        self.deployable = self.parent_total * DEPLOYABLE_PERCENTAGE
        self.allocations: Dict[str, float] = {comp: self.deployable / len(DEFAULT_COMPANIES) for comp in DEFAULT_COMPANIES}
        self.positions: Dict[str, Dict[str, float]] = {comp: {} for comp in DEFAULT_COMPANIES}
        self.cash: Dict[str, float] = self.allocations.copy()
        self.realized: Dict[str, float] = {comp: 0.0 for comp in DEFAULT_COMPANIES}
        self.unrealized: Dict[str, float] = {comp: 0.0 for comp in DEFAULT_COMPANIES}
        self.parent_equity = self.reserve + sum(self.cash.values())
        self.allocation_snapshot()

    def allocation_snapshot(self) -> None:
        payload = {
            "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "parent_total": self.parent_total,
            "reserve_amount": self.reserve,
            "deployable_amount": self.deployable,
            "per_company_allocation": self.allocations,
        }
        (self.run_dir / "artifacts" / "allocation_state.json").write_text(json.dumps(payload, indent=2))

    def apply_decision(self, decision: Dict[str, object]) -> None:
        company = decision["company_id"]
        symbol = decision["symbol"]
        price = decision["price"]
        decision_type = decision["decision"]
        cash = self.cash.get(company, 0.0)
        entry = self.positions[company].get(symbol, 0.0)
        size = 1.0
        if decision_type == "BUY" and cash >= price * size and price > 0:
            self.positions[company][symbol] = entry + size
            self.cash[company] = cash - price * size
            trade = self._build_trade(decision, "BUY", size)
            self._log_trade(trade)
        elif decision_type == "SELL" and entry >= size and price > 0:
            self.positions[company][symbol] = entry - size
            self.cash[company] = cash + price * size
            pnl = (price - (price * 0.99)) * size
            self.realized[company] += pnl
            trade = self._build_trade(decision, "SELL", size)
            self._log_trade(trade)
        else:
            trade = self._build_trade(decision, "HOLD", 0)
            self._log_trade(trade)
        self._write_portfolio_snapshot(decision)

    def _build_trade(self, decision: Dict[str, object], action: str, size: float) -> Dict[str, object]:
        return {
            "timestamp": decision["timestamp"],
            "company_id": decision["company_id"],
            "symbol": decision["symbol"],
            "action": action,
            "size": size,
            "price": decision["price"],
            "decision_confidence": decision["confidence"],
        }

    def _log_trade(self, trade: Dict[str, object]) -> None:
        with (self.run_dir / "artifacts" / "paper_trades.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trade) + "\n")

    def _write_portfolio_snapshot(self, decision: Dict[str, object]) -> None:
        snapshot = {
            "timestamp": decision["timestamp"],
            "parent_equity": self.reserve + sum(self.cash.values()),
            "company": decision["company_id"],
            "cash": self.cash.get(decision["company_id"], 0.0),
            "positions": self.positions[decision["company_id"]],
            "realized_pnl": self.realized[decision["company_id"]],
        }
        with (self.run_dir / "artifacts" / "portfolio_state.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot) + "\n")
