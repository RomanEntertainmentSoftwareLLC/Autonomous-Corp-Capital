#!/usr/bin/env python3
"""Simple warehouse query tool with built-in analytics."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "data" / "warehouse.sqlite"
COMPANIES_DIR = ROOT / "companies"


def load_lineage() -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    for company_dir in COMPANIES_DIR.iterdir():
        if not company_dir.is_dir():
            continue
        meta_path = company_dir / "metadata.yaml"
        if not meta_path.exists():
            continue
        data = yaml.safe_load(meta_path.open("r", encoding="utf-8")) or {}
        mapping[company_dir.name] = {
            "generation": str(data.get("generation", "<unknown>")),
            "parent": data.get("parent_company", "<none>"),
        }
    return mapping
METADATA_PATH = COMPANIES_DIR / "metadata"


def load_generation_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for company_dir in COMPANIES_DIR.iterdir():
        if not company_dir.is_dir():
            continue
        meta_path = company_dir / "metadata.yaml"
        if not meta_path.exists():
            continue
        data = yaml.safe_load(meta_path.open("r", encoding="utf-8")) or {}
        mapping[company_dir.name] = str(data.get("generation", "<unknown>"))
    return mapping


def query_strategy_performance(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT runs.strategy,
               COUNT(evaluations.evaluation_id) AS runs,
               AVG(evaluations.account_value) AS avg_account,
               AVG(evaluations.realized_pnl) AS avg_realized
        FROM evaluations
        JOIN runs ON runs.id = evaluations.run_id
        GROUP BY runs.strategy
        ORDER BY avg_account DESC
        LIMIT 10
        """
    )
    print("Strategy performance (from canonical evaluations):")
    print("strategy         runs  avg_account  avg_realized")
    for row in cursor.fetchall():
        strategy, runs, avg_account, avg_realized = row
        avg_account = avg_account or 0.0
        avg_realized = avg_realized or 0.0
        print(f"{strategy:<15} {runs:>4}  {avg_account:>11.2f}  {avg_realized:>12.2f}")


def query_company_fitness(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT companies.name, runs.mode, runs.strategy, results.account_value, results.realized_pnl, results.drawdown
        FROM companies
        JOIN runs ON runs.company_id = companies.id
        JOIN results ON results.run_id = runs.id
        ORDER BY results.account_value DESC
        LIMIT 10
    """
    )
    print("Company fitness:")
    print("company        mode      strategy         account  realized  drawdown")
    for row in cursor.fetchall():
        company, mode, strategy, account, realized, drawdown = row
        print(f"{company:<14} {mode:<8} {strategy:<15} ${account:>8.2f}  ${realized:>7.2f}  {drawdown or 0:>8.2f}")


def query_generation_effects(conn: sqlite3.Connection) -> None:
    lineage = load_lineage()
    generation_map = {k: v["generation"] for k, v in lineage.items()}
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT companies.name, results.account_value, results.realized_pnl, runs.mode
        FROM companies
        JOIN runs ON runs.company_id = companies.id
        JOIN results ON results.run_id = runs.id
        ORDER BY companies.name, results.account_value DESC
    """
    )
    print("Mutation generation effects:")
    print("company        generation  mode      account  realized")
    for company, account, realized, mode in cursor.fetchall():
        gen = generation_map.get(company, "<unknown>")
        print(f"{company:<14} {gen:<11} {mode:<8} ${account:>8.2f}  ${realized:>7.2f}")


def query_symbol_trades(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ticks.symbol, COUNT(trades.id) AS trade_count
        FROM ticks
        JOIN trades ON trades.tick_id = ticks.id
        GROUP BY ticks.symbol
        ORDER BY trade_count DESC
        LIMIT 10
    """
    )
    print("Top symbols by trade count:")
    print("symbol         trades")
    for symbol, trades in cursor.fetchall():
        print(f"{symbol:<14} {trades:>6}")


def query_best_strategy_by_symbol(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT trade_facts.symbol,
               runs.strategy,
               COUNT(*) AS trade_count,
               AVG(trade_facts.pnl) AS avg_pnl
        FROM trade_facts
        JOIN runs ON runs.id = trade_facts.run_id
        GROUP BY trade_facts.symbol, runs.strategy
        ORDER BY trade_facts.symbol, avg_pnl DESC
        """
    )
    print("Best strategy by symbol (ranked by avg trade PnL):")
    print("symbol   strategy           trades  avg_pnl")
    for row in cursor.fetchall():
        symbol, strategy, trades, avg_pnl = row
        avg_pnl = avg_pnl or 0.0
        print(f"{symbol:<8} {strategy:<18} {trades:>6}  {avg_pnl:>9.2f}")


def query_ema_param_profitability(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            ticks.symbol,
            json_extract(ticks.features, '$.ema_fast') AS ema_fast,
            json_extract(ticks.features, '$.ema_slow') AS ema_slow,
            runs.strategy,
            COUNT(DISTINCT runs.id) AS run_count,
            AVG(results.realized_pnl) AS avg_realized_pnl,
            AVG(results.drawdown) AS avg_drawdown,
            AVG(results.account_value) AS avg_account
        FROM runs
        JOIN results ON results.run_id = runs.id
        JOIN ticks ON ticks.run_id = runs.id
        WHERE runs.strategy LIKE '%ema%'
        GROUP BY ticks.symbol, ema_fast, ema_slow, runs.strategy
        ORDER BY avg_realized_pnl DESC
        LIMIT 20
        """
    )
    print("Profitable EMA parameter combos:")
    print("symbol   strategy           ema_fast  ema_slow  runs  avg_realized  avg_drawdown  avg_account")
    for row in cursor.fetchall():
        symbol, ema_fast, ema_slow, strategy, runs, avg_realized, avg_drawdown, avg_account = row
        print(
            f"{symbol:<8} {strategy:<18} {ema_fast or 0:<9} {ema_slow or 0:<9} {runs:>4}  {avg_realized:>12.2f}  {avg_drawdown or 0:>12.2f}  {avg_account:>11.2f}"
        )


def query_company_profit_ranking(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT companies.name,
               SUM(trade_facts.pnl) AS total_profit,
               COUNT(trade_facts.trade_id) AS trade_count
        FROM trade_facts
        JOIN companies ON companies.id = trade_facts.company_id
        GROUP BY companies.id
        ORDER BY total_profit DESC
        """
    )
    print("Company profit ranking:")
    print("company        profit     trades")
    rows = cursor.fetchall()
    if not rows:
        print("No canonical profit data available yet.")
        return
    for name, profit, trades in rows:
        profit = profit or 0.0
        print(f"{name:<15} {profit:>10.2f}  {trades:>6}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Query the trading warehouse for built-in insights")
    parser.add_argument("query", choices=[
        "strategy_performance",
        "company_fitness",
        "generation_effects",
        "symbol_trades",
        "best_strategy_by_symbol",
        "ema_param_profitability",
        "company_profit_ranking",
    ], help="Name of the predefined query to run")
    parser.add_argument("--db", type=Path, default=WAREHOUSE, help="Path to the warehouse.sqlite file")
    args = parser.parse_args()

    if not args.db.exists():
        print("Warehouse database not found. Run tools/init_warehouse.py first.")
        return

    with sqlite3.connect(args.db) as conn:
        if args.query == "strategy_performance":
            query_strategy_performance(conn)
        elif args.query == "company_fitness":
            query_company_fitness(conn)
        elif args.query == "generation_effects":
            query_generation_effects(conn)
        elif args.query == "symbol_trades":
            query_symbol_trades(conn)
        elif args.query == "best_strategy_by_symbol":
            query_best_strategy_by_symbol(conn)
        elif args.query == "ema_param_profitability":
            query_ema_param_profitability(conn)
        elif args.query == "company_profit_ranking":
            query_company_profit_ranking(conn)


if __name__ == "__main__":
    main()
