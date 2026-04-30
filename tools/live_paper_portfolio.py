"""Paper portfolio and capital allocation tracker."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_TREASURY = 100.0
RESERVE_PERCENTAGE = 0.6
DEPLOYABLE_PERCENTAGE = 0.4
DEFAULT_COMPANIES = ["company_001", "company_002", "company_003", "company_004"]


class PortfolioState:
    def __init__(self, run_dir: Path, parent_total: float | None = None, companies: List[str] | None = None):
        self.run_dir = run_dir
        (self.run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self.companies = list(companies or DEFAULT_COMPANIES)
        self.parent_total = float(parent_total if parent_total is not None else DEFAULT_TREASURY)
        self.reserve = self.parent_total * RESERVE_PERCENTAGE
        self.deployable = self.parent_total * DEPLOYABLE_PERCENTAGE
        self.allocations: Dict[str, float] = {comp: self.deployable / len(self.companies) for comp in self.companies}
        self.positions: Dict[str, Dict[str, float]] = {comp: {} for comp in self.companies}
        self.position_meta: Dict[str, Dict[str, Dict[str, float]]] = {comp: {} for comp in self.companies}
        self.last_marks: Dict[str, Dict[str, float]] = {comp: {} for comp in self.companies}
        self.cash: Dict[str, float] = self.allocations.copy()
        self.realized: Dict[str, float] = {comp: 0.0 for comp in self.companies}
        self.unrealized: Dict[str, float] = {comp: 0.0 for comp in self.companies}
        self.parent_equity = self.reserve + sum(self.cash.values())
        self.tick_index = 0
        self.max_open_positions = max(1, int(os.environ.get("ACC_MAX_OPEN_POSITIONS_PER_COMPANY", "6")))
        self.allocation_snapshot()

    def allocation_snapshot(self) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parent_total": self.parent_total,
            "reserve_amount": self.reserve,
            "deployable_amount": self.deployable,
            "per_company_allocation": self.allocations,
        }
        (self.run_dir / "artifacts" / "allocation_state.json").write_text(json.dumps(payload, indent=2))

    def mark_price(self, company: str, symbol: str, price: float) -> None:
        company = str(company)
        symbol = str(symbol)
        price = float(price or 0.0)
        if price > 0.0:
            self.last_marks.setdefault(company, {})[symbol] = price

    def _company_unrealized(self, company: str) -> float:
        total = 0.0
        for symbol, qty in self.positions.get(company, {}).items():
            meta = self.position_meta.get(company, {}).get(symbol) or {}
            entry_price = float(meta.get("entry_price") or 0.0)
            mark_price = float(self.last_marks.get(company, {}).get(symbol) or entry_price or 0.0)
            if qty > 0.0 and entry_price > 0.0 and mark_price > 0.0:
                total += (mark_price - entry_price) * qty
        self.unrealized[company] = total
        return total

    def get_position_snapshot(self, company: str, symbol: str) -> Dict[str, Any]:
        company = str(company)
        symbol = str(symbol)
        qty = float(self.positions.get(company, {}).get(symbol, 0.0) or 0.0)
        meta = self.position_meta.get(company, {}).get(symbol) or {}
        entry_price = float(meta.get("entry_price") or 0.0)
        entry_tick = int(meta.get("entry_tick") or 0)
        held_ticks = max(0, int(self.tick_index) - entry_tick) if qty > 0.0 and entry_tick else 0
        mark_price = float(self.last_marks.get(company, {}).get(symbol) or entry_price or 0.0)
        unrealized_pnl = (mark_price - entry_price) * qty if qty > 0.0 and entry_price > 0.0 else 0.0
        open_positions_count = sum(1 for value in self.positions.get(company, {}).values() if float(value or 0.0) > 0.0)
        return {
            "position_state": qty,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "unrealized_pnl": unrealized_pnl,
            "held_ticks": held_ticks,
            "open_positions_count": open_positions_count,
            "max_open_positions": self.max_open_positions,
            "cash_snapshot": self.cash.get(company, 0.0),
        }

    def company_snapshot(self, company: str) -> Dict[str, Any]:
        positions_detail: Dict[str, Dict[str, float]] = {}
        for symbol, qty in self.positions.get(company, {}).items():
            if float(qty or 0.0) <= 0.0:
                continue
            meta = self.position_meta.get(company, {}).get(symbol) or {}
            entry_price = float(meta.get("entry_price") or 0.0)
            entry_tick = int(meta.get("entry_tick") or 0)
            held_ticks = max(0, int(self.tick_index) - entry_tick) if entry_tick else 0
            mark_price = float(self.last_marks.get(company, {}).get(symbol) or entry_price or 0.0)
            unrealized_pnl = (mark_price - entry_price) * float(qty or 0.0) if entry_price > 0.0 else 0.0
            positions_detail[symbol] = {
                "qty": float(qty or 0.0),
                "entry_price": entry_price,
                "mark_price": mark_price,
                "unrealized_pnl": unrealized_pnl,
                "held_ticks": held_ticks,
            }
        unrealized = self._company_unrealized(company)
        self.parent_equity = self.reserve + sum(self.cash.values()) + sum(self.unrealized.values())
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parent_equity": self.parent_equity,
            "company": company,
            "cash": self.cash.get(company, 0.0),
            "positions": {symbol: meta["qty"] for symbol, meta in positions_detail.items()},
            "positions_detail": positions_detail,
            "realized_pnl": self.realized[company],
            "unrealized_pnl": unrealized,
            "open_positions_count": len(positions_detail),
        }

    def apply_decision(self, decision: Dict[str, object]) -> None:
        company = str(decision["company_id"])
        symbol = str(decision["symbol"])
        price = float(decision["price"])
        decision_type = str(decision["decision"])
        self.tick_index = max(self.tick_index, int(decision.get("cycle") or self.tick_index + 1))
        self.mark_price(company, symbol, price)
        cash = self.cash.get(company, 0.0)
        size = self._determine_size(decision)
        entry = float(self.positions[company].get(symbol, 0.0) or 0.0)
        if decision_type == "BUY" and cash >= price * size and price > 0 and size > 0:
            if entry <= 0.0 and sum(1 for value in self.positions[company].values() if float(value or 0.0) > 0.0) >= self.max_open_positions:
                trade = self._build_trade(decision, "HOLD", 0)
                trade["skip_reason"] = "max_open_positions"
                self._log_trade(trade)
                self._write_portfolio_snapshot(decision)
                return
            new_qty = entry + size
            prior_meta = self.position_meta[company].get(symbol) or {}
            prior_entry_price = float(prior_meta.get("entry_price") or 0.0)
            entry_tick = int(prior_meta.get("entry_tick") or self.tick_index)
            if entry > 0.0 and prior_entry_price > 0.0:
                weighted_entry = ((entry * prior_entry_price) + (size * price)) / new_qty
            else:
                weighted_entry = price
                entry_tick = self.tick_index
            self.positions[company][symbol] = new_qty
            self.position_meta[company][symbol] = {"entry_price": weighted_entry, "entry_tick": entry_tick}
            self.cash[company] = cash - price * size
            trade = self._build_trade(decision, "BUY", size)
            trade["entry_price"] = weighted_entry
            self._log_trade(trade)
        elif decision_type == "SELL" and entry >= size and price > 0 and size > 0:
            prior_meta = self.position_meta[company].get(symbol) or {}
            prior_entry_price = float(prior_meta.get("entry_price") or price)
            remaining = entry - size
            self.cash[company] = cash + price * size
            pnl = (price - prior_entry_price) * size
            self.realized[company] += pnl
            if remaining > 1e-12:
                self.positions[company][symbol] = remaining
                self.position_meta[company][symbol] = {
                    "entry_price": prior_entry_price,
                    "entry_tick": int(prior_meta.get("entry_tick") or self.tick_index),
                }
            else:
                self.positions[company].pop(symbol, None)
                self.position_meta[company].pop(symbol, None)
            trade = self._build_trade(decision, "SELL", size)
            trade["entry_price"] = prior_entry_price
            trade["realized_pnl"] = pnl
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
            "cycle": decision.get("cycle"),
            "held_ticks": decision.get("held_ticks"),
            "pnl_pct": decision.get("pnl_pct"),
            "forced_exit_reason": decision.get("forced_exit_reason"),
        }

    def _log_trade(self, trade: Dict[str, object]) -> None:
        with (self.run_dir / "artifacts" / "paper_trades.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(trade) + "\n")

    def _write_portfolio_snapshot(self, decision: Dict[str, object]) -> None:
        snapshot = self.company_snapshot(str(decision["company_id"]))
        snapshot["timestamp"] = decision["timestamp"]
        with (self.run_dir / "artifacts" / "portfolio_state.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot) + "\n")

    def _determine_size(self, decision: Dict[str, object]) -> float:
        company = str(decision["company_id"])
        symbol = str(decision["symbol"])
        decision_type = str(decision.get("decision") or "").upper()
        price = float(decision["price"])
        confidence = float(decision.get("confidence", 0.0))
        size_multiplier = float(decision.get("size_multiplier", 1.0))
        cash = self.cash.get(company, 0.0)
        existing = float(self.positions.get(company, {}).get(symbol, 0.0) or 0.0)
        if decision_type == "SELL":
            return max(existing, 0.0)
        if price <= 0 or cash <= 0:
            return 0.0
        open_positions = sum(1 for value in self.positions.get(company, {}).values() if float(value or 0.0) > 0.0)
        slot_pressure = 1.0
        if open_positions >= max(1, self.max_open_positions - 1):
            slot_pressure = 0.6
        base = cash * min(max(confidence, 0.05), 0.9) * max(size_multiplier, 0.0) * slot_pressure
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
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "changes": changes,
                }) + "\n")
