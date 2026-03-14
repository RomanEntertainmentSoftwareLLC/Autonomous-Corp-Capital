#!/usr/bin/env python3
"""Ingest trading results into the SQLite warehouse."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
WAREHOUSE = ROOT / "data" / "warehouse.sqlite"


def parse_timestamp(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return raw


def load_json_lines(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def ensure_company(cursor: sqlite3.Cursor, name: str) -> int:
    cursor.execute("SELECT id FROM companies WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute("INSERT INTO companies (name) VALUES (?)", (name,))
    return cursor.lastrowid


def existing_run(cursor: sqlite3.Cursor, company_id: int, mode: str, start_time: str) -> bool:
    cursor.execute(
        "SELECT id FROM runs WHERE company_id = ? AND mode = ? AND start_time = ?",
        (company_id, mode, start_time),
    )
    return cursor.fetchone() is not None


def ingest_run(cursor: sqlite3.Cursor, company_id: int, company: str, mode: str) -> None:
    path = RESULTS_DIR / company / mode
    signal_log = load_json_lines(path / "signal-log.jsonl")
    trade_log = load_json_lines(path / "trade-log.jsonl")
    feature_log = load_json_lines(path / "feature-log.jsonl")

    entries = signal_log or trade_log or feature_log
    if not entries:
        print(f"Skipping {company}-{mode}: no logs")
        return

    timestamps = [parse_timestamp(entry.get("timestamp", "")) for entry in entries if entry.get("timestamp")]
    if not timestamps:
        print(f"Skipping {company}-{mode}: no timestamps")
        return
    start_time = min(timestamps)

    if existing_run(cursor, company_id, mode, start_time):
        print(f"Run {company}-{mode} already ingested")
        return

    strategy = entries[0].get("strategy", "unknown")
    cursor.execute(
        "INSERT INTO runs (company_id, mode, strategy, start_time, status) VALUES (?,?,?,?,?)",
        (company_id, mode, strategy, start_time, "completed"),
    )
    run_id = cursor.lastrowid

    tick_map = {}
    for entry in signal_log:
        timestamp = parse_timestamp(entry.get("timestamp", ""))
        cursor.execute(
            "INSERT INTO ticks (run_id, timestamp, symbol, price, signal, features) VALUES (?,?,?,?,?,?)",
            (
                run_id,
                timestamp,
                entry.get("symbol"),
                entry.get("price"),
                entry.get("signal"),
                json.dumps(entry.get("features", {})),
            ),
        )
        tick_map[(timestamp, entry.get("symbol"))] = cursor.lastrowid

    for entry in trade_log:
        if not entry.get("executed"):
            continue
        timestamp = parse_timestamp(entry.get("timestamp", ""))
        symbol = entry.get("symbol")
        tick_id = tick_map.get((timestamp, symbol))
        cursor.execute(
            "INSERT INTO trades (run_id, tick_id, direction, quantity, price, pnl) VALUES (?,?,?,?,?,?)",
            (
                run_id,
                tick_id,
                entry.get("signal"),
                entry.get("position_after", 0.0),
                entry.get("price"),
                entry.get("pnl"),
            ),
        )

    for entry in feature_log:
        timestamp = parse_timestamp(entry.get("timestamp", ""))
        symbol = entry.get("symbol")
        tick_id = tick_map.get((timestamp, symbol))
        cursor.execute(
            "INSERT INTO features (tick_id, payload) VALUES (?,?)",
            (tick_id, json.dumps(entry.get("features", {}))),
        )

    if trade_log:
        last = trade_log[-1]
        cursor.execute(
            "INSERT INTO results (run_id, account_value, realized_pnl, unrealized_pnl, drawdown) VALUES (?,?,?,?,?)",
            (
                run_id,
                last.get("cash_after", 0.0),
                last.get("pnl", 0.0),
                last.get("unrealized_pnl", 0.0),
                last.get("max_drawdown_percent", 0.0),
            ),
        )
    print(f"Ingested {company}-{mode} to run {run_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest logs into the trading warehouse")
    parser.add_argument("--mode", help="Optional mode filter")
    parser.add_argument("--company", help="Optional company filter")
    args = parser.parse_args()

    if not WAREHOUSE.exists():
        print("Warehouse not initialized. Run tools/init_warehouse.py first.")
        return

    if not RESULTS_DIR.exists():
        print("No results directory found; nothing to ingest.")
        return

    with sqlite3.connect(WAREHOUSE) as conn:
        cursor = conn.cursor()
        for company_dir in sorted(RESULTS_DIR.iterdir()):
            if not company_dir.is_dir():
                continue
            company = company_dir.name
            if args.company and args.company != company:
                continue
            company_id = ensure_company(cursor, company)
            for mode_dir in sorted(company_dir.iterdir()):
                if not mode_dir.is_dir():
                    continue
                mode = mode_dir.name
                if args.mode and args.mode != mode:
                    continue
                ingest_run(cursor, company_id, company, mode)
        conn.commit()


if __name__ == "__main__":
    main()
