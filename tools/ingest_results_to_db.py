#!/usr/bin/env python3
"""Ingest trading results into the SQLite warehouse."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting_utils import compute_fitness, determine_evaluation_state

RESULTS_DIR = ROOT / "results"
WAREHOUSE = ROOT / "data" / "warehouse.sqlite"


def parse_timestamp(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return raw


def load_json_lines(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_company_metadata(company: str) -> Dict[str, Any]:
    metadata_path = ROOT / "companies" / company / "metadata.yaml"
    if not metadata_path.exists():
        return {}
    with metadata_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def ensure_company(cursor: sqlite3.Cursor, name: str) -> int:
    cursor.execute("SELECT id FROM companies WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute("INSERT INTO companies (name) VALUES (?)", (name,))
    return cursor.lastrowid


def ensure_analytics_company(
    cursor: sqlite3.Cursor,
    company_id: int,
    metadata: Dict[str, Any],
    strategy: str,
    start_time: str,
) -> None:
    parent = metadata.get("parent_company")
    generation = metadata.get("generation")
    status = metadata.get("lifecycle_state", "active")
    notes = metadata.get("notes")
    created_at = metadata.get("created_at") or start_time
    cursor.execute(
        """
        INSERT INTO analytics_companies (company_id, created_at, status, parent_company, generation, strategy_name, notes)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(company_id) DO UPDATE SET
            status = excluded.status,
            parent_company = COALESCE(excluded.parent_company, analytics_companies.parent_company),
            generation = COALESCE(excluded.generation, analytics_companies.generation),
            strategy_name = excluded.strategy_name,
            notes = COALESCE(excluded.notes, analytics_companies.notes)
        """,
        (
            company_id,
            created_at,
            status,
            parent,
            generation,
            strategy,
            notes,
        ),
    )


def existing_run(cursor: sqlite3.Cursor, company_id: int, mode: str, start_time: str) -> bool:
    cursor.execute(
        "SELECT id FROM runs WHERE company_id = ? AND mode = ? AND start_time = ?",
        (company_id, mode, start_time),
    )
    return cursor.fetchone() is not None


def summarize_trades(trade_entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, int, float]:
    executed = [entry for entry in trade_entries if entry.get("executed")]
    trade_count = len(executed)
    wins = sum(1 for entry in executed if (entry.get("pnl") or 0) > 0)
    win_rate = (wins / trade_count * 100) if trade_count else 0.0
    return executed, trade_count, wins, win_rate


def record_trade_facts(
    cursor: sqlite3.Cursor,
    company_id: int,
    run_id: int,
    executed_trades: List[Dict[str, Any]],
) -> None:
    for entry in executed_trades:
        timestamp = parse_timestamp(entry.get("timestamp", ""))
        cursor.execute(
            "INSERT INTO trade_facts (company_id, run_id, timestamp, symbol, action, price, units, pnl, source) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                company_id,
                run_id,
                timestamp,
                entry.get("symbol"),
                entry.get("signal") or entry.get("direction"),
                entry.get("price"),
                entry.get("trade_units", 0.0),
                entry.get("pnl"),
                entry.get("source"),
            ),
        )


def record_evaluation(
    cursor: sqlite3.Cursor,
    company_id: int,
    run_id: int,
    timestamp: str,
    symbol: str | None,
    account_value: float,
    realized_pnl: float,
    unrealized_pnl: float,
    trade_count: int,
    win_rate: float,
    max_drawdown: float,
    fitness: float | None,
) -> None:
    cursor.execute(
        """
        INSERT INTO evaluations (company_id, run_id, timestamp, symbol, account_value, realized_pnl, unrealized_pnl, trade_count, win_rate, max_drawdown, regime, fitness)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            company_id,
            run_id,
            timestamp,
            symbol,
            account_value,
            realized_pnl,
            unrealized_pnl,
            trade_count,
            win_rate,
            max_drawdown,
            None,
            fitness,
        ),
    )


def upsert_company_performance(
    cursor: sqlite3.Cursor,
    company_id: int,
    timestamp: str,
    metrics: Dict[str, Any],
    fitness: float | None,
    metadata: Dict[str, Any],
    evaluation_state: str,
    latest_regime: str,
) -> None:
    allocation_percent = metadata.get("allocation_percent") or metadata.get("allocation", {}).get("percent")
    allocation_amount = metadata.get("allocation_amount") or metadata.get("allocation", {}).get("amount")
    lifecycle_state = metadata.get("lifecycle_state", evaluation_state)
    cursor.execute(
        """
        INSERT INTO company_performance (company_id, last_evaluated_at, latest_fitness, latest_account_value, latest_realized_pnl, latest_unrealized_pnl, latest_trade_count, latest_win_rate, latest_drawdown, latest_regime, lifecycle_state, allocation_percent, allocation_amount)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(company_id) DO UPDATE SET
            last_evaluated_at = excluded.last_evaluated_at,
            latest_fitness = excluded.latest_fitness,
            latest_account_value = excluded.latest_account_value,
            latest_realized_pnl = excluded.latest_realized_pnl,
            latest_unrealized_pnl = excluded.latest_unrealized_pnl,
            latest_trade_count = excluded.latest_trade_count,
            latest_win_rate = excluded.latest_win_rate,
            latest_drawdown = excluded.latest_drawdown,
            latest_regime = COALESCE(excluded.latest_regime, company_performance.latest_regime),
            lifecycle_state = excluded.lifecycle_state,
            allocation_percent = COALESCE(excluded.allocation_percent, company_performance.allocation_percent),
            allocation_amount = COALESCE(excluded.allocation_amount, company_performance.allocation_amount)
        """,
        (
            company_id,
            timestamp,
            fitness,
            metrics.get("account_value", 0.0),
            metrics.get("realized_pnl", 0.0),
            metrics.get("unrealized_pnl", 0.0),
            metrics.get("trade_count", 0),
            metrics.get("win_rate", 0.0),
            metrics.get("drawdown", 0.0),
            latest_regime,
            lifecycle_state,
            allocation_percent,
            allocation_amount,
        ),
    )


def ingest_run(cursor: sqlite3.Cursor, company_id: int, company: str, mode: str) -> None:
    path = RESULTS_DIR / company / mode
    signal_log = load_json_lines(path / "signal-log.jsonl")
    trade_log = load_json_lines(path / "trade-log.jsonl")
    feature_log = load_json_lines(path / "feature-log.jsonl")

    all_entries: List[Dict[str, Any]] = []
    all_entries.extend(signal_log)
    all_entries.extend(trade_log)
    if not all_entries:
        print(f"Skipping {company}-{mode}: no logs")
        return

    timestamps = [parse_timestamp(entry.get("timestamp", "")) for entry in all_entries if entry.get("timestamp")]
    if not timestamps:
        print(f"Skipping {company}-{mode}: no timestamps")
        return
    start_time = min(timestamps)
    latest_timestamp = max(timestamps)

    if existing_run(cursor, company_id, mode, start_time):
        print(f"Run {company}-{mode} already ingested")
        return

    strategy_names: set[str] = set()
    for entry in all_entries:
        strat = entry.get("strategy")
        if strat:
            strategy_names.add(strat)
    strategy_label = ", ".join(sorted(strategy_names)) if strategy_names else "unknown"
    cursor.execute(
        "INSERT INTO runs (company_id, mode, strategy, start_time, status) VALUES (?,?,?,?,?)",
        (company_id, mode, strategy_label, start_time, "completed"),
    )
    run_id = cursor.lastrowid

    tick_map: Dict[Tuple[str, str], int] = {}
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

    executed_trades, trade_count, wins, win_rate = summarize_trades(trade_log)

    symbol_latest: Dict[str, Dict[str, Any]] = {}

    def update_symbol_state(entry: Dict[str, Any]) -> None:
        symbol = entry.get("symbol")
        if not symbol:
            return
        entry_ts = parse_timestamp(entry.get("timestamp", ""))
        prev = symbol_latest.get(symbol, {}).get("timestamp")
        if prev and entry_ts < prev:
            return
        symbol_latest[symbol] = {
            "timestamp": entry_ts,
            "account_value": entry.get("account_value", entry.get("cash_after", 0.0)) or 0.0,
            "realized_pnl_total": entry.get("realized_pnl_total", entry.get("pnl", 0.0)) or 0.0,
            "unrealized_pnl": entry.get("unrealized_pnl", 0.0) or 0.0,
            "drawdown": entry.get("max_drawdown_percent", 0.0) or 0.0,
            "trade_count": entry.get("trade_count", 0) or 0,
            "strategy": entry.get("strategy"),
        }

    for entry in trade_log:
        update_symbol_state(entry)
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
                entry.get("trade_units", 0.0),
                entry.get("price"),
                entry.get("pnl"),
            ),
        )

    for entry in signal_log:
        update_symbol_state(entry)

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
        aggregated_account = sum(m.get("account_value", 0.0) for m in symbol_latest.values()) or (
            last.get("account_value", last.get("cash_after", 0.0)) or 0.0
        )
        aggregated_realized = sum(m.get("realized_pnl_total", 0.0) for m in symbol_latest.values()) or (
            last.get("realized_pnl_total", last.get("pnl", 0.0)) or 0.0
        )
        aggregated_unrealized = sum(m.get("unrealized_pnl", 0.0) for m in symbol_latest.values()) or (
            last.get("unrealized_pnl", 0.0) or 0.0
        )
        aggregated_drawdown = max((m.get("drawdown", 0.0) for m in symbol_latest.values()), default=0.0)
        metrics_payload = {
            "account_value": aggregated_account,
            "realized_pnl": aggregated_realized,
            "unrealized_pnl": aggregated_unrealized,
            "drawdown": aggregated_drawdown,
            "trade_count": trade_count,
            "win_rate": win_rate,
        }
        cursor.execute(
            "INSERT INTO results (run_id, account_value, realized_pnl, unrealized_pnl, drawdown) VALUES (?,?,?,?,?)",
            (
                run_id,
                metrics_payload["account_value"],
                metrics_payload["realized_pnl"],
                metrics_payload["unrealized_pnl"],
                metrics_payload["drawdown"],
            ),
        )
        metadata = load_company_metadata(company)
        eval_state, _ = determine_evaluation_state(metrics_payload)
        fitness_value = compute_fitness(metrics_payload)
        ensure_analytics_company(cursor, company_id, metadata, strategy_label, start_time)
        record_trade_facts(cursor, company_id, run_id, executed_trades)
        symbol_field = None
        if len(symbol_latest) > 1:
            symbol_field = "MULTI"
        elif symbol_latest:
            symbol_field = next(iter(symbol_latest))
        record_evaluation(
            cursor,
            company_id,
            run_id,
            latest_timestamp,
            symbol_field,
            metrics_payload["account_value"],
            metrics_payload["realized_pnl"],
            metrics_payload["unrealized_pnl"],
            metrics_payload["trade_count"],
            metrics_payload["win_rate"],
            metrics_payload["drawdown"],
            fitness_value,
        )
        latest_regime = "unknown"
        upsert_company_performance(
            cursor,
            company_id,
            latest_timestamp,
            metrics_payload,
            fitness_value,
            metadata,
            eval_state,
            latest_regime,
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
