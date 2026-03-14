#!/usr/bin/env python3
"""Boardroom-style summary of company status and results."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.company_metadata import read_metadata
from tools.python_helper import ensure_repo_root
from tools.reporting_utils import compute_fitness, determine_evaluation_state
from tradebot.strategies.factory import resolve_strategy_name

ensure_repo_root()

WAREHOUSE = ROOT / "data" / "warehouse.sqlite"
COMPANIES_DIR = ROOT / "companies"


def load_config(company: str) -> Dict[str, Any]:
    path = COMPANIES_DIR / company / "config.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def strategies_used(config: Dict[str, Any]) -> List[str]:
    symbols = config.get("symbols", [])
    seen: List[str] = []
    for symbol in symbols:
        strategy = resolve_strategy_name(symbol)
        if strategy not in seen:
            seen.append(strategy)
    return seen


def format_currency(value: float) -> str:
    return f"${value:,.2f}"


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
               ac.strategy_name,
               ac.parent_company,
               ac.generation
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
            "parent_company": row[12],
            "generation": row[13],
        }
    return mapping


def build_metrics(performance: Dict[str, Any]) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    if not performance or performance.get("account_value") is None:
        return metrics
    metrics["account"] = performance.get("account_value", 0.0)
    metrics["realized_pnl"] = performance.get("realized_pnl", 0.0) or 0.0
    metrics["unrealized_pnl"] = performance.get("unrealized_pnl", 0.0) or 0.0
    metrics["trade_count"] = int(performance.get("trade_count") or 0)
    metrics["win_rate"] = performance.get("win_rate", 0.0) or 0.0
    metrics["drawdown"] = performance.get("drawdown", 0.0) or 0.0
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize company statuses for the board")
    parser.add_argument("--metric", choices=["account_value", "realized_pnl"], default="account_value")
    args = parser.parse_args()

    companies = sorted(p.name for p in COMPANIES_DIR.iterdir() if p.is_dir())
    if not companies:
        print("No companies found.")
        return

    performance_map: Dict[str, Dict[str, Any]] = {}
    if WAREHOUSE.exists():
        with sqlite3.connect(WAREHOUSE) as conn:
            performance_map = load_performance_map(conn)
    report_rows: List[Dict[str, Any]] = []

    for company in companies:
        metadata = read_metadata(company)
        generation = metadata.get("generation") or performance_map.get(company, {}).get("generation", "<unknown>")
        parent = metadata.get("parent_company") or performance_map.get(company, {}).get("parent_company", "<none>")
        config = load_config(company)
        strategies = strategies_used(config)
        performance = performance_map.get(company, {})
        metrics = build_metrics(performance)
        eval_state, eval_reason = determine_evaluation_state(metrics)
        fitness_value = performance.get("fitness")
        if fitness_value is None and metrics:
            fitness_value = compute_fitness(metrics)
        trades_value = performance.get("trade_count")
        trades_display = str(trades_value) if trades_value is not None else "-"
        strategy_label = performance.get("strategy_name") or (", ".join(strategies) if strategies else "N/A")
        fitness_display = f"{fitness_value:.2f}" if fitness_value is not None else "N/A"
        state_label = performance.get("state") or metadata.get("lifecycle_state", "UNTESTED")
        evaluation_note = eval_reason
        if not performance or performance.get("fitness") is None:
            evaluation_note = evaluation_note or "Canonical analytics row pending"
        account_value = performance.get("account_value") or 0.0
        report_rows.append(
            {
                "company": company,
                "generation": generation,
                "parent": parent,
                "latest_mode": performance.get("latest_mode", "<none>"),
                "account_value": account_value,
                "realized_pnl": performance.get("realized_pnl", 0.0) or 0.0,
                "unrealized_pnl": performance.get("unrealized_pnl", 0.0) or 0.0,
                "total_trades": performance.get("trade_count", 0) or 0,
                "win_rate": performance.get("win_rate"),
                "max_drawdown": performance.get("drawdown"),
                "strategies": strategies,
                "state": state_label,
                "strategy_display": strategy_label,
                "trades_display": trades_display,
                "fitness_display": fitness_display,
                "fitness_value": fitness_value,
                "evaluation_note": evaluation_note,
            }
        )

    report_rows.sort(key=lambda r: r[args.metric], reverse=True)

    print("Company Status Report")
    print("=" * 60)
    for row in report_rows:
        print(f"{row['company']} (gen {row['generation']}, parent={row['parent']})")
        print(f" state: {row['state']}")
        print(f" strategy: {row['strategy_display']}")
        print(f" trades: {row['trades_display']}  fitness: {row['fitness_display']}")
        if row['evaluation_note']:
            print(f" note: {row['evaluation_note']}")
        print(f"  Latest mode: {row['latest_mode']}  Account value: {format_currency(row['account_value'])}  Realized PnL: {format_currency(row['realized_pnl'])}")
        print(f"  Unrealized PnL: {format_currency(row['unrealized_pnl'])}")
        win = f"{row['win_rate']:.2f}%" if row['win_rate'] is not None else "N/A"
        drawdown = f"{row['max_drawdown']:.2f}%" if row['max_drawdown'] is not None else "N/A"
        print(f"  Trades recorded: {row['total_trades']}  Win rate: {win}  Max drawdown: {drawdown}")
        print(f"  Strategies: {', '.join(row['strategies']) if row['strategies'] else '<none>'}")
        print("-" * 60)


def run() -> None:
    main()


if __name__ == "__main__":
    run()
