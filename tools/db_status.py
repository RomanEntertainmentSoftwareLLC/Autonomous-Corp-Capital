#!/usr/bin/env python3
"""Report health/status of the trading warehouse."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "warehouse.sqlite"


def table_count(cursor: sqlite3.Cursor, table: str) -> int:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    return cursor.fetchone()[0]


def latest_insertion(cursor: sqlite3.Cursor) -> str:
    cursor.execute(
        "SELECT companies.name, runs.mode, runs.start_time FROM runs JOIN companies ON companies.id = runs.company_id ORDER BY runs.start_time DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if not row:
        return "<none>"
    company, mode, start_time = row
    return f"{company} ({mode}) @ {start_time}"


def main() -> None:
    if not DB_PATH.exists():
        print("Warehouse not initialized. Run tools/init_warehouse.py first.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        print(f"Warehouse: {DB_PATH}")
        print("Table counts:")
        for table in ["companies", "runs", "ticks", "trades", "features", "results"]:
            print(f"  {table}: {table_count(cursor, table)} rows")
        cursor.execute("SELECT COUNT(DISTINCT runs.id) FROM runs")
        total_runs = cursor.fetchone()[0]
        print(f"Total runs: {total_runs}")
        print(f"Latest run: {latest_insertion(cursor)}")


if __name__ == "__main__":
    main()
