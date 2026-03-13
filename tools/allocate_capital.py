#!/usr/bin/env python3
"""Allocate capital based on treasury and company performance."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "data" / "warehouse.sqlite"
TREASURY = ROOT / "state" / "treasury.yaml"
COMPANIES_DIR = ROOT / "companies"
LIFECYCLE_EXCLUDE = {"RETIRED", "ARCHIVED"}


def load_treasury() -> dict:
    if not TREASURY.exists():
        return {}
    with TREASURY.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_treasury(data: dict) -> None:
    with TREASURY.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def load_metadata(company: str) -> dict:
    path = COMPANIES_DIR / company / "metadata.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}

def save_metadata(company: str, data: dict) -> None:
    path = COMPANIES_DIR / company / "metadata.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def fetch_performance() -> list[dict]:
    if not WAREHOUSE.exists():
        raise SystemExit("Warehouse not initialized; run tools/init_warehouse.py first.")
    with sqlite3.connect(WAREHOUSE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT company, account_value, realized_pnl, unrealized_pnl, drawdown FROM latest_company_results"
        )
        rows = []
        for company, account, realized, unrealized, drawdown in cursor.fetchall():
            rows.append({
                "company": company,
                "account": account or 0.0,
                "realized": realized or 0.0,
                "unrealized": unrealized or 0.0,
                "drawdown": drawdown or 0.0,
            })
        return rows


def compute_fitness(metrics: dict) -> float:
    return metrics["realized"] + 0.25 * metrics["unrealized"] - 2 * metrics["drawdown"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Allocate treasury capital to companies")
    args = parser.parse_args()

    treasury = load_treasury()
    allocatable = treasury.get("allocatable_capital", 0.0)
    performance = fetch_performance()
    allocations: dict[str, float] = {}
    fitness_map = {}

    for entry in performance:
        company = entry["company"]
        meta = load_metadata(company)
        state = meta.get("lifecycle_state", "NEW")
        if state in LIFECYCLE_EXCLUDE:
            print(f"Skipping {company} (state={state})")
            continue
        fitness_map[company] = max(0.0, compute_fitness(entry))

    total_fitness = sum(fitness_map.values())
    if total_fitness <= 0:
        print("No positive fitness; leaving capital unallocated")
        treasury["unallocated_capital"] = allocatable
    else:
        total_allocated = 0.0
        for company, fit in fitness_map.items():
            amount = (fit / total_fitness) * allocatable
            allocations[company] = amount
            total_allocated += amount
        treasury["unallocated_capital"] = max(0.0, allocatable - total_allocated)
    treasury["company_allocations"] = allocations
    treasury["last_updated"] = datetime.utcnow().isoformat() + "Z"
    save_treasury(treasury)

    print("Treasury allocations:")
    for company, amount in allocations.items():
        meta = load_metadata(company)
        percent = (amount / allocatable * 100) if allocatable else 0.0
        meta["allocation_percent"] = round(percent, 2)
        meta["allocation_amount"] = round(amount, 2)
        meta["allocation_status"] = "active"
        meta["last_rebalance_at"] = treasury["last_updated"]
        save_metadata(company, meta)
        print(f"  {company}: ${amount:,.2f} ({percent:.1f}%)")
    print(f"Unallocated capital: ${treasury.get('unallocated_capital', 0.0):,.2f}")


if __name__ == "__main__":
    main()
