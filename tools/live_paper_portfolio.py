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
    def __init__(self, run_dir: Path, parent_total: float | None = None, companies: List[str] | None = None):
        self.run_dir = run_dir
        self.companies = list(companies or DEFAULT_COMPANIES)
        self.parent_total = float(parent_total if parent_total is not None else DEFAULT_TREASURY)
        self.reserve = self.parent_total * RESERVE_PERCENTAGE
        self.deployable = self.parent_total * DEPLOYABLE_PERCENTAGE
        self.allocations: Dict[str, float] = {comp: self.deployable / len(self.companies) for comp in self.companies}
        self.positions: Dict[str, Dict[str, float]] = {comp: {} for comp in self.companies}
        self.cash: Dict[str, float] = self.allocations.copy()
        self.realized: Dict[str, float] = {comp: 0.0 for comp in self.companies}
        self.unrealized: Dict[str, float] = {comp: 0.0 for comp in self.companies}
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
        size = self._determine_size(decision)
        entry = self.positions[company].get(symbol, 0.0)
        if decision_type == "BUY" and cash >= price * size and price > 0 and size > 0:
            self.positions[company][symbol] = entry + size
            self.cash[company] = cash - price * size
            trade = self._build_trade(decision, "BUY", size)
            self._log_trade(trade)
        elif decision_type == "SELL" and entry >= size and price > 0 and size > 0:
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
            "policy_name": decision.get("policy_name"),
            "company_posture": decision.get("company_posture"),
            "size_multiplier": decision.get("size_multiplier"),
            "sizing_rationale": decision.get("sizing_rationale"),
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

    def _determine_size(self, decision: Dict[str, object]) -> float:
        company = decision["company_id"]
        price = float(decision["price"])
        confidence = float(decision.get("confidence", 0.0))
        size_multiplier = float(decision.get("size_multiplier", 1.0))
        cash = self.cash.get(company, 0.0)
        if price <= 0 or cash <= 0:
            return 0.0
        base = cash * min(confidence, 0.9) * max(size_multiplier, 0.0)
        size = min(base / price, 2.0)
        return max(min(size, cash / price), 0.0)

    def reallocation_step(self) -> None:
        avg_equity = sum(self.cash.values()) / len(self.cash) if self.cash else 0
        changes = []
        for company, eq in self.cash.items():
            change = 0.0
            if eq > avg_equity * 1.05:
                change = min(eq * 0.05, self.deployable * 0.02)
            elif eq < avg_equity * 0.95:
                change = -min(eq * 0.03, self.allocations[company] * 0.02)
            if change != 0:
                old_alloc = self.allocations[company]
                self.allocations[company] = max(self.allocations[company] + change, 0.0)
                self.cash[company] += change
                changes.append({
                    "company": company,
                    "old_alloc": old_alloc,
                    "new_alloc": self.allocations[company],
                    "change": change,
                })
        self.allocation_snapshot()
        if changes:
            with (self.run_dir / "artifacts" / "allocation_state.json").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
                    "changes": changes,
                }) + "\n")
