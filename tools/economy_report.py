#!/usr/bin/env python3
"""Report virtual economy state for the autonomous trading lab."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
TREASURY = ROOT / "state" / "treasury.yaml"
WAREHOUSE = ROOT / "data" / "warehouse.sqlite"
COMPANIES_DIR = ROOT / "companies"


def load_treasury() -> Dict[str, float]:
    if not TREASURY.exists():
        raise SystemExit("Treasury file missing; run allocate_capital first")
    with TREASURY.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_fitness() -> Dict[str, float]:
    fitness: Dict[str, float] = {}
    if not WAREHOUSE.exists():
        return fitness
    with sqlite3.connect(WAREHOUSE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT companies.name, results.realized_pnl, results.unrealized_pnl, results.drawdown FROM companies JOIN runs ON runs.company_id = companies.id JOIN results ON results.run_id = runs.id ORDER BY results.account_value DESC"
        )
        for company, realized, unrealized, drawdown in cursor.fetchall():
            score = (realized or 0.0) + 0.25 * (unrealized or 0.0) - 2 * (drawdown or 0.0)
            fitness[company] = score
    return fitness


def load_lifecycle(company: str) -> str:
    path = COMPANIES_DIR / company / "metadata.yaml"
    if not path.exists():
        return "NEW"
    data = yaml.safe_load(path.open("r", encoding="utf-8")) or {}
    return data.get("lifecycle_state", "NEW")


def main() -> None:
    treasury = load_treasury()
    fitness_map = load_fitness()
    allocations = treasury.get("company_allocations", {})
    print("Autonomous economy report")
    print("=" * 60)
    print(f"Total capital:    ${treasury.get('total_capital', 0):,.2f}")
    print(f"Reserve capital:  ${treasury.get('reserve_capital', 0):,.2f}")
    print(f"Allocatable:      ${treasury.get('allocatable_capital', 0):,.2f}")
    print(f"Unallocated:      ${treasury.get('unallocated_capital', 0):,.2f}")
    print("=" * 60)
    print("Company allocations:")
    print("company        lifecycle     percent  amount     fitness")
    print("--------------------------------------------------------")
    for company, amount in allocations.items():
        percent = (amount / treasury.get("allocatable_capital", 1)) * 100 if treasury.get("allocatable_capital") else 0
        state = load_lifecycle(company)
        fitness = fitness_map.get(company, 0.0)
        print(
            f"{company:<14} {state:<12} {percent:>7.2f}%  ${amount:>8.2f}  {fitness:>8.2f}"
        )
    print("=" * 60)


if __name__ == "__main__":
    main()