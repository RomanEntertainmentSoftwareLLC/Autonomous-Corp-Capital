#!/usr/bin/env python3
"""Rank companies by canonical performance state."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.python_helper import ensure_repo_root

ensure_repo_root()

WAREHOUSE = ROOT / "data" / "warehouse.sqlite"
COMPANIES_DIR = ROOT / "companies"


def load_performance_map(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.name,
               cp.latest_account_value,
               cp.latest_realized_pnl,
               cp.latest_unrealized_pnl,
               cp.latest_trade_count,
               cp.latest_win_rate,
               cp.latest_drawdown,
               cp.latest_regime,
               cp.lifecycle_state,
               cp.latest_fitness,
               lrs.mode,
               ac.strategy_name
        FROM companies c
        LEFT JOIN company_performance cp ON cp.company_id = c.id
        LEFT JOIN analytics_companies ac ON ac.company_id = c.id
        LEFT JOIN latest_run_summary lrs ON lrs.company = c.name
        """
    )
    mapping: Dict[str, Dict[str, Any]] = {}
    for row in cursor.fetchall():
        mapping[row[0]] = {
            "account_value": row[1],
            "realized_pnl": row[2],
            "unrealized_pnl": row[3],
            "trade_count": row[4],
            "win_rate": row[5],
            "drawdown": row[6],
            "regime": row[7],
            "state": row[8],
            "fitness": row[9],
            "latest_mode": row[10],
            "strategy_name": row[11],
        }
    return mapping


def recommend(fitness: float | None) -> str:
    if fitness is None:
        return "N/A"
    if fitness >= 30:
        return "CLONE"
    if fitness <= -40:
        return "RETIRE"
    if fitness >= 0:
        return "KEEP"
    return "TEST_MORE"


def main() -> None:
    parser = argparse.ArgumentParser(description="Leaderboard of companies by performance")
    parser.add_argument("--mode", help="Optional mode filter (backtest/paper)")
    parser.add_argument("--company", help="Optional company filter to narrow the table")
    args = parser.parse_args()

    companies = sorted(p.name for p in COMPANIES_DIR.iterdir() if p.is_dir())
    if args.company:
        companies = [c for c in companies if c == args.company]
    if not companies:
        print("No companies found.")
        return

    performance_map: Dict[str, Dict[str, Any]] = {}
    if WAREHOUSE.exists():
        with sqlite3.connect(WAREHOUSE) as conn:
            performance_map = load_performance_map(conn)

    display_rows: List[Dict[str, Any]] = []
    for company in companies:
        performance = performance_map.get(company, {})
        fitness_value = performance.get("fitness")
        strategy_label = performance.get("strategy_name") or "N/A"
        trades_value = performance.get("trade_count")
        trades_display = str(trades_value) if trades_value is not None else "-"
        fitness_label = f"{fitness_value:.2f}" if fitness_value is not None else "N/A"
        state_label = performance.get("state") or "UNTESTED"
        mode_label = performance.get("latest_mode") or "<none>"
        evaluation_reason = None
        if not performance or performance.get("fitness") is None:
            evaluation_reason = "Canonical analytics row pending"
        display_rows.append(
            {
                "company": company,
                "state": state_label,
                "strategy_display": strategy_label,
                "trades_display": trades_display,
                "fitness": fitness_value,
                "fitness_label": fitness_label,
                "recommendation": recommend(fitness_value),
                "mode": mode_label,
                "evaluation_reason": evaluation_reason,
            }
        )

    def fitness_sort_key(row: Dict[str, Any]) -> float:
        value = row.get("fitness")
        return value if value is not None else float("-inf")

    display_rows.sort(key=fitness_sort_key, reverse=True)

    print("Leaderboard — company evaluation state")
    print("=" * 80)
    print(
        f"{'company':<14} {'state':<10} {'strategy':<20} {'trades':>6} {'fitness':>8} {'recommend':<10} {'mode':<10}"
    )
    for row in display_rows:
        print(
            f"{row['company']:<14} {row['state']:<10} {row['strategy_display']:<20} {row['trades_display']:>6} "
            f"{row['fitness_label']:>8} {row['recommendation']:<10} {row['mode']:<10}"
        )
        if row['evaluation_reason']:
            print(f"  note: {row['evaluation_reason']}")


if __name__ == "__main__":
    main()
