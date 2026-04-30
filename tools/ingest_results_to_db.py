#!/usr/bin/env python3
"""Ingest trading results into the SQLite warehouse."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting_utils import compute_fitness, determine_evaluation_state

RESULTS_DIR = ROOT / "results"
LIVE_RUNS_DIR = ROOT / "state" / "live_runs"
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


def _latest_live_run_dir() -> Path | None:
    if not LIVE_RUNS_DIR.exists():
        return None
    runs = [p for p in LIVE_RUNS_DIR.glob("run_*") if p.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def _resolve_live_run(value: str | None) -> Path | None:
    if not value or value == "latest":
        return _latest_live_run_dir()
    candidate = Path(value)
    if candidate.exists():
        return candidate
    candidate = LIVE_RUNS_DIR / value
    if candidate.exists():
        return candidate
    return None


def _first_value(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return default


def _row_timestamp(row: Dict[str, Any], fallback: str = "") -> str:
    raw = _first_value(row, "timestamp", "time", "created_at", "started_at", default=fallback)
    return parse_timestamp(str(raw or fallback or ""))


def _row_company(row: Dict[str, Any]) -> str:
    return str(_first_value(row, "company_id", "company", "company_name", default="unknown_company") or "unknown_company")


def _row_symbol(row: Dict[str, Any]) -> str | None:
    value = _first_value(row, "symbol", "ticker", "asset", default=None)
    return str(value) if value is not None else None


def _row_action(row: Dict[str, Any]) -> str | None:
    value = _first_value(row, "action", "decision", "final_decision", "execution_action", "signal", "direction", default=None)
    return str(value).upper() if value is not None else None


def _row_price(row: Dict[str, Any]) -> float | None:
    value = _first_value(row, "price", "mark_price", "last_price", "close", default=None)
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _row_units(row: Dict[str, Any]) -> float:
    value = _first_value(row, "trade_units", "units", "quantity", "qty", "shares", default=0.0)
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _row_pnl(row: Dict[str, Any]) -> float:
    value = _first_value(row, "pnl", "realized_pnl", "realized_pnl_total", default=0.0)
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _row_metric_float(row: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    value = _first_value(row, *keys, default=default)
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _run_metadata(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "run_metadata.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _choose_latest_by_symbol(rows: List[Dict[str, Any]], fallback_timestamp: str) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        symbol = _row_symbol(row) or "PORTFOLIO"
        ts = _row_timestamp(row, fallback_timestamp)
        prev = latest.get(symbol)
        if prev and ts < prev.get("timestamp", ""):
            continue
        latest[symbol] = {"timestamp": ts, "row": row}
    return latest


def _make_live_metrics(
    company: str,
    portfolio_rows: List[Dict[str, Any]],
    trade_rows: List[Dict[str, Any]],
    decision_rows: List[Dict[str, Any]],
    fallback_timestamp: str,
) -> tuple[Dict[str, Any], str, str | None]:
    company_portfolio = [r for r in portfolio_rows if _row_company(r) == company]
    company_trades = [r for r in trade_rows if _row_company(r) == company]
    company_decisions = [r for r in decision_rows if _row_company(r) == company]
    latest_by_symbol = _choose_latest_by_symbol(company_portfolio or company_trades or company_decisions, fallback_timestamp)
    latest_rows = [v["row"] for v in latest_by_symbol.values()]

    executed_trades = [r for r in company_trades if r.get("executed", True) is not False]
    trade_count = len(executed_trades)
    wins = sum(1 for r in executed_trades if _row_pnl(r) > 0)
    win_rate = (wins / trade_count * 100.0) if trade_count else 0.0

    if latest_rows:
        account_value = sum(_row_metric_float(r, "account_value", "equity", "cash_after", default=0.0) for r in latest_rows)
        realized = sum(_row_metric_float(r, "realized_pnl_total", "realized_pnl", "pnl", default=0.0) for r in latest_rows)
        unrealized = sum(_row_metric_float(r, "unrealized_pnl", default=0.0) for r in latest_rows)
        drawdown = max((_row_metric_float(r, "max_drawdown_percent", "drawdown", default=0.0) for r in latest_rows), default=0.0)
    else:
        account_value = sum(_row_metric_float(r, "account_value", "cash_after", default=0.0) for r in company_trades)
        realized = sum(_row_pnl(r) for r in executed_trades)
        unrealized = 0.0
        drawdown = 0.0

    latest_timestamp = max(
        [_row_timestamp(r, fallback_timestamp) for r in (company_portfolio + company_trades + company_decisions)] or [fallback_timestamp]
    )
    symbol_field = "MULTI" if len(latest_by_symbol) > 1 else (next(iter(latest_by_symbol)) if latest_by_symbol else None)
    return {
        "account_value": account_value,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "drawdown": drawdown,
        "trade_count": trade_count,
        "win_rate": win_rate,
    }, latest_timestamp, symbol_field


def ingest_live_run(cursor: sqlite3.Cursor, run_dir: Path) -> None:
    """Ingest state/live_runs/<run_id>/artifacts JSONL into the warehouse.

    Legacy ingest reads results/<company>/<mode>. Fresh paper runs write richer
    artifacts under state/live_runs. This path preserves the legacy warehouse
    schema by creating one warehouse run per company found in the live-run
    artifacts, using ticks/features/trades/results/evaluations rows.
    """
    artifacts = run_dir / "artifacts"
    if not artifacts.exists():
        print(f"Skipping {run_dir.name}: no artifacts directory")
        return

    metadata = _run_metadata(run_dir)
    fallback_timestamp = parse_timestamp(str(metadata.get("started_at") or datetime.now(timezone.utc).isoformat()))
    decision_rows = load_json_lines(artifacts / "paper_decisions.jsonl")
    trade_rows = load_json_lines(artifacts / "paper_trades.jsonl")
    portfolio_rows = load_json_lines(artifacts / "portfolio_state.jsonl")
    packet_rows = load_json_lines(artifacts / "company_packets.jsonl")

    all_rows: List[Dict[str, Any]] = []
    all_rows.extend(decision_rows)
    all_rows.extend(trade_rows)
    all_rows.extend(portfolio_rows)
    if not all_rows:
        print(f"Skipping {run_dir.name}: no decision/trade/portfolio artifacts")
        return

    companies = sorted({_row_company(r) for r in all_rows if _row_company(r) != "unknown_company"})
    if not companies:
        companies = ["system"]

    for company in companies:
        company_decisions = [r for r in decision_rows if _row_company(r) == company]
        company_trades = [r for r in trade_rows if _row_company(r) == company]
        company_portfolio = [r for r in portfolio_rows if _row_company(r) == company]
        company_packets = [r for r in packet_rows if _row_company(r) == company]
        if not (company_decisions or company_trades or company_portfolio or company_packets):
            continue

        company_id = ensure_company(cursor, company)
        timestamps = [_row_timestamp(r, fallback_timestamp) for r in (company_decisions + company_trades + company_portfolio)]
        start_time = min(timestamps) if timestamps else fallback_timestamp
        end_time = max(timestamps) if timestamps else fallback_timestamp
        mode = "paper_live"
        if existing_run(cursor, company_id, mode, start_time):
            print(f"Run {company}-{mode}-{run_dir.name} already ingested")
            continue

        strategies = {
            str(_first_value(r, "strategy", "decision_path", default=""))
            for r in (company_decisions + company_trades)
            if _first_value(r, "strategy", "decision_path", default="")
        }
        strategy_label = ", ".join(sorted(strategies)) if strategies else "live_paper"
        metrics, latest_timestamp, symbol_field = _make_live_metrics(
            company, portfolio_rows, trade_rows, decision_rows, fallback_timestamp
        )
        run_metrics = {
            "source_live_run_id": run_dir.name,
            "decision_rows": len(company_decisions),
            "trade_rows": len(company_trades),
            "portfolio_rows": len(company_portfolio),
            "packet_rows": len(company_packets),
            **metrics,
        }
        cursor.execute(
            "INSERT INTO runs (company_id, mode, strategy, start_time, end_time, status, metrics) VALUES (?,?,?,?,?,?,?)",
            (company_id, mode, strategy_label, start_time, end_time, "completed", json.dumps(run_metrics, sort_keys=True)),
        )
        run_id = cursor.lastrowid

        tick_map: Dict[Tuple[str, str | None], int] = {}
        for row in company_decisions:
            ts = _row_timestamp(row, fallback_timestamp)
            symbol = _row_symbol(row)
            action = _row_action(row)
            features_payload = {
                "features": row.get("features") or row.get("ml_features") or {},
                "ml_signal_score": row.get("ml_signal_score"),
                "ml_feature_coverage": row.get("ml_feature_coverage"),
                "ml_scoring_active": row.get("ml_scoring_active"),
                "evidence_winner": row.get("evidence_winner"),
                "evidence_margin": row.get("evidence_margin"),
                "decision_trace_summary": row.get("decision_trace_summary"),
                "source": "live_run.paper_decisions",
            }
            cursor.execute(
                "INSERT INTO ticks (run_id, timestamp, symbol, price, signal, features) VALUES (?,?,?,?,?,?)",
                (run_id, ts, symbol, _row_price(row), action, json.dumps(features_payload, sort_keys=True)),
            )
            tick_id = cursor.lastrowid
            tick_map[(ts, symbol)] = tick_id
            cursor.execute(
                "INSERT INTO features (tick_id, payload) VALUES (?,?)",
                (tick_id, json.dumps(features_payload, sort_keys=True)),
            )

        def ensure_tick(row: Dict[str, Any], source: str) -> int:
            ts = _row_timestamp(row, fallback_timestamp)
            symbol = _row_symbol(row)
            key = (ts, symbol)
            if key in tick_map:
                return tick_map[key]
            action = _row_action(row)
            payload = {"source": source, "row": row}
            cursor.execute(
                "INSERT INTO ticks (run_id, timestamp, symbol, price, signal, features) VALUES (?,?,?,?,?,?)",
                (run_id, ts, symbol, _row_price(row), action, json.dumps(payload, sort_keys=True, default=str)),
            )
            tick_map[key] = cursor.lastrowid
            return tick_map[key]

        executed_trades = [r for r in company_trades if r.get("executed", True) is not False]
        for row in executed_trades:
            tick_id = ensure_tick(row, "live_run.paper_trades")
            cursor.execute(
                "INSERT INTO trades (run_id, tick_id, direction, quantity, price, pnl) VALUES (?,?,?,?,?,?)",
                (run_id, tick_id, _row_action(row), _row_units(row), _row_price(row), _row_pnl(row)),
            )
            cursor.execute(
                "INSERT INTO trade_facts (company_id, run_id, timestamp, symbol, action, price, units, pnl, source) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    company_id,
                    run_id,
                    _row_timestamp(row, fallback_timestamp),
                    _row_symbol(row),
                    _row_action(row),
                    _row_price(row),
                    _row_units(row),
                    _row_pnl(row),
                    f"live_run:{run_dir.name}",
                ),
            )

        cursor.execute(
            "INSERT INTO results (run_id, account_value, realized_pnl, unrealized_pnl, drawdown, metrics) VALUES (?,?,?,?,?,?)",
            (
                run_id,
                metrics["account_value"],
                metrics["realized_pnl"],
                metrics["unrealized_pnl"],
                metrics["drawdown"],
                json.dumps(run_metrics, sort_keys=True),
            ),
        )
        company_metadata = load_company_metadata(company)
        eval_state, _ = determine_evaluation_state(metrics)
        fitness_value = compute_fitness(metrics)
        ensure_analytics_company(cursor, company_id, company_metadata, strategy_label, start_time)
        record_evaluation(
            cursor,
            company_id,
            run_id,
            latest_timestamp,
            symbol_field,
            metrics["account_value"],
            metrics["realized_pnl"],
            metrics["unrealized_pnl"],
            metrics["trade_count"],
            metrics["win_rate"],
            metrics["drawdown"],
            fitness_value,
        )
        upsert_company_performance(
            cursor,
            company_id,
            latest_timestamp,
            metrics,
            fitness_value,
            company_metadata,
            eval_state,
            "unknown",
        )
        print(f"Ingested live run {run_dir.name} {company} to run {run_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest logs into the trading warehouse")
    parser.add_argument("--mode", help="Optional legacy results/<company>/<mode> filter")
    parser.add_argument("--company", help="Optional legacy company filter")
    parser.add_argument("--live-run", help="Ingest state/live_runs artifacts by run id, path, or 'latest'")
    parser.add_argument("--latest-live-run", action="store_true", help="Shortcut for --live-run latest")
    args = parser.parse_args()

    if not WAREHOUSE.exists():
        print("Warehouse not initialized. Run tools/init_warehouse.py first.")
        return

    with sqlite3.connect(WAREHOUSE) as conn:
        cursor = conn.cursor()
        if args.live_run or args.latest_live_run:
            run_dir = _resolve_live_run(args.live_run or "latest")
            if not run_dir:
                print("No matching live run found under state/live_runs.")
                return
            ingest_live_run(cursor, run_dir)
        else:
            if not RESULTS_DIR.exists():
                print("No results directory found; nothing to ingest.")
                return
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
