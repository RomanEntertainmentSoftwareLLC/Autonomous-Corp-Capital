#!/usr/bin/env python3
"""Boardroom-style summary of company status and results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

import yaml

from tools.company_metadata import read_metadata
from tradebot.strategies.factory import resolve_strategy_name

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
COMPANIES_DIR = Path(__file__).resolve().parent.parent / "companies"


def iter_log_entries(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            yield json.loads(line)


def summarize_trade_log(path: Path) -> Dict[str, Any]:
    last_per_symbol: Dict[str, Dict[str, Any]] = {}
    trades = 0
    wins = 0
    losses = 0
    realized = 0.0
    account_history: List[float] = []

    for entry in iter_log_entries(path):
        sym = entry.get("symbol", "UNKNOWN")
        last_per_symbol[sym] = entry
        if entry.get("executed"):
            trades += 1
            pnl = entry.get("pnl")
            if isinstance(pnl, (int, float)):
                realized += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
        cash = entry.get("cash_after", 0.0)
        position = entry.get("position_after", 0.0)
        price = entry.get("price", 0.0)
        account_history.append(cash + position * price)

    if not last_per_symbol:
        return {
            "account_value": 0.0,
            "realized_pnl": realized,
            "unrealized_pnl": 0.0,
            "total_trades": trades,
            "win_rate": None,
            "max_drawdown": None,
        }

    account_value = sum(
        e.get("cash_after", 0.0) + e.get("position_after", 0.0) * e.get("price", 0.0)
        for e in last_per_symbol.values()
    )
    unrealized = sum(e.get("unrealized_pnl", 0.0) for e in last_per_symbol.values())

    win_rate = None
    if wins + losses > 0:
        win_rate = wins / (wins + losses) * 100

    max_account = max(account_history) if account_history else account_value
    drawdown = None
    if max_account > 0:
        drawdown = max(0.0, (max_account - account_value) / max_account * 100)

    return {
        "account_value": account_value,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_trades": trades,
        "win_rate": win_rate,
        "max_drawdown": drawdown,
    }


def collect_results(company: str) -> List[Dict[str, Any]]:
    results = []
    company_dir = RESULTS_DIR / company
    if not company_dir.exists():
        return results

    for mode_dir in sorted(company_dir.iterdir()):
        if not mode_dir.is_dir():
            continue
        log_path = mode_dir / "trade-log.jsonl"
        if not log_path.exists():
            continue
        summary = summarize_trade_log(log_path)
        summary["mode"] = mode_dir.name
        summary["log_path"] = log_path
        summary["timestamp"] = log_path.stat().st_mtime
        results.append(summary)
    return results


def load_config(company: str) -> Dict[str, Any]:
    path = COMPANIES_DIR / company / "config.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def strategies_used(config: Dict[str, Any]) -> List[str]:
    symbols = config.get("symbols", [])
    seen = []
    for symbol in symbols:
        name = symbol.get("name") or "UNKNOWN"
        strategy = resolve_strategy_name(symbol)
        if strategy not in seen:
            seen.append(strategy)
    return seen


def format_currency(value: float) -> str:
    return f"${value:,.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize company statuses for the board")
    parser.add_argument("--metric", choices=["account_value", "realized_pnl"], default="account_value")
    args = parser.parse_args()

    companies = sorted(p.name for p in COMPANIES_DIR.iterdir() if p.is_dir())
    if not companies:
        print("No companies found.")
        return

    report_rows = []
    for company in companies:
        metadata = read_metadata(company)
        generation = metadata.get("generation", "<unknown>")
        parent = metadata.get("parent_company", "<none>")
        config = load_config(company)
        strategies = strategies_used(config)
        results = collect_results(company)
        if not results:
            latest = {
                "mode": "<none>",
                "account_value": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "total_trades": 0,
                "win_rate": None,
                "max_drawdown": None,
            }
        else:
            latest = max(results, key=lambda r: (r[args.metric], r["timestamp"]))
        report_rows.append(
            {
                "company": company,
                "generation": generation,
                "parent": parent,
                "latest_mode": latest["mode"],
                "account_value": latest["account_value"],
                "realized_pnl": latest["realized_pnl"],
                "unrealized_pnl": latest["unrealized_pnl"],
                "total_trades": latest["total_trades"],
                "win_rate": latest.get("win_rate"),
                "max_drawdown": latest.get("max_drawdown"),
                "strategies": strategies,
            }
        )

    report_rows.sort(key=lambda r: r[args.metric], reverse=True)

    print("Board report — company status overview")
    print("=" * 60)
    for row in report_rows:
        print(
            f"{row['company']} (gen {row['generation']}, parent={row['parent']})"
        )
        print(f"  Latest mode: {row['latest_mode']}")
        print(
            f"  Account value: {format_currency(row['account_value'])}  Realized PnL: {format_currency(row['realized_pnl'])}"
        )
        print(f"  Unrealized PnL: {format_currency(row['unrealized_pnl'])}")
        win = f"{row['win_rate']:.2f}%" if row['win_rate'] is not None else "N/A"
        drawdown = f"{row['max_drawdown']:.2f}%" if row['max_drawdown'] is not None else "N/A"
        print(f"  Trades: {row['total_trades']}  Win rate: {win}  Max drawdown: {drawdown}")
        print(f"  Strategies: {', '.join(row['strategies']) if row['strategies'] else '<none>'}")
        print("-" * 60)


def run() -> None:
    main()


if __name__ == "__main__":
    run()
