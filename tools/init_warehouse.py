#!/usr/bin/env python3
"""Initialize the trading data warehouse schema."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_PATH = ROOT / "data" / "warehouse.sqlite"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    mode TEXT NOT NULL,
    strategy TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    status TEXT,
    metrics TEXT
);

CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    timestamp TEXT,
    symbol TEXT,
    price REAL,
    signal TEXT,
    features TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    tick_id INTEGER NOT NULL REFERENCES ticks(id),
    direction TEXT,
    quantity REAL,
    price REAL,
    pnl REAL
);

CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_id INTEGER NOT NULL REFERENCES ticks(id),
    payload TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    account_value REAL,
    realized_pnl REAL,
    unrealized_pnl REAL,
    drawdown REAL,
    metrics TEXT
);

CREATE VIEW IF NOT EXISTS latest_company_results AS
SELECT companies.name AS company,
       runs.mode,
       runs.strategy,
       results.account_value,
       results.realized_pnl,
       results.unrealized_pnl,
       results.drawdown,
       runs.start_time,
       runs.status
FROM companies
JOIN runs ON runs.company_id = companies.id
JOIN results ON results.run_id = runs.id
WHERE runs.id IN (
    SELECT id FROM runs r2
    WHERE r2.company_id = runs.company_id
    ORDER BY r2.start_time DESC
)
;

CREATE VIEW IF NOT EXISTS leaderboard_basis AS
SELECT companies.name AS company,
       runs.mode,
       runs.strategy,
       results.account_value,
       results.realized_pnl,
       results.drawdown,
       runs.start_time
FROM companies
JOIN runs ON runs.company_id = companies.id
JOIN results ON results.run_id = runs.id
ORDER BY runs.start_time DESC;

CREATE VIEW IF NOT EXISTS latest_run_summary AS
SELECT runs.id AS run_id,
       companies.name AS company,
       runs.mode,
       runs.strategy,
       runs.start_time,
       runs.end_time,
       runs.status,
       results.account_value,
       results.realized_pnl,
       results.unrealized_pnl,
       results.drawdown
FROM runs
JOIN companies ON companies.id = runs.company_id
JOIN results ON results.run_id = runs.id
WHERE runs.start_time IN (
    SELECT MAX(start_time) FROM runs r3 WHERE r3.company_id = runs.company_id
);
"""


def init_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        cursor.executescript(SCHEMA)
        conn.commit()
    print(f"Initialized warehouse at {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or upgrade the trading warehouse schema")
    parser.add_argument("--path", type=Path, default=WAREHOUSE_PATH, help="Path to the SQLite warehouse file")
    args = parser.parse_args()
    init_database(args.path)


if __name__ == "__main__":
    main()
