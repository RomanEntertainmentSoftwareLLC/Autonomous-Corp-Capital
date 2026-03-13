#!/usr/bin/env python3
"""Bob v1: Simple result-log summarizer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Iterable


RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def iter_log_entries(log_path: Path) -> Iterable[dict]:
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def summarize_trade_log(log_path: Path) -> dict:
    total_trades = 0
    wins = 0
    losses = 0
    realized_pnl = 0.0
    symbols = {}

    for entry in iter_log_entries(log_path):
        symbol = entry.get("symbol", "UNKNOWN")
        executed = entry.get("executed") is True
        pnl = entry.get("pnl")
        if executed:
            total_trades += 1
            if pnl is not None:
                realized_pnl += pnl
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
        symbols[symbol] = entry

    win_rate = None
    trade_decisions = wins + losses
    if trade_decisions:
        win_rate = wins / trade_decisions * 100

    cash = sum(entry.get("cash_after", 0.0) for entry in symbols.values())
    position = sum(entry.get("position_after", 0.0) for entry in symbols.values())
    unrealized = sum(entry.get("unrealized_pnl", 0.0) for entry in symbols.values())
    account_values = [
        entry.get("cash_after", 0.0) + entry.get("position_after", 0.0) * entry.get("price", 0.0)
        for entry in symbols.values()
    ]
    account_value = sum(account_values)

    drawdowns = [entry.get("max_drawdown_percent") for entry in symbols.values() if entry.get("max_drawdown_percent") is not None]
    max_drawdown = max(drawdowns) if drawdowns else None

    return {
        "total_trades": total_trades,
        "cash": cash,
        "position": position,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized,
        "account_value": account_value,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
    }


def report(company: str, mode: str | None = None) -> None:
    company_dir = RESULTS_DIR / company
    if not company_dir.exists():
        raise FileNotFoundError(f"No logs found for company {company}")

    mode_dirs = [mode] if mode else sorted(x.name for x in company_dir.iterdir() if x.is_dir())
    for mode_name in mode_dirs:
        log_path = company_dir / mode_name / "trade-log.jsonl"
        if not log_path.exists():
            print(f"Skipping {mode_name}: missing trade-log.jsonl")
            continue

        summary = summarize_trade_log(log_path)
        print("=" * 60)
        print(f"Bob v1 report — company={company} mode={mode_name}")
        print("=" * 60)
        print(f"Total trades:    {summary['total_trades']}")
        print(f"Cash:            ${summary['cash']:.2f}")
        print(f"Position size:   {summary['position']:.6f}")
        print(f"Realized PnL:    ${summary['realized_pnl']:.2f}")
        print(f"Unrealized PnL:  ${summary['unrealized_pnl']:.2f}")
        print(f"Account value:   ${summary['account_value']:.2f}")
        win_rate = summary['win_rate']
        if win_rate is not None:
            print(f"Win rate:        {win_rate:.2f}%")
        else:
            print("Win rate:        N/A")
        if summary['max_drawdown'] is not None:
            print(f"Max drawdown:    {summary['max_drawdown']:.2f}%")
        else:
            print("Max drawdown:    N/A")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bob v1 summary over result logs")
    parser.add_argument("company", help="Company folder name under results/")
    parser.add_argument("--mode", help="Optional specific mode directory (e.g., backtest)")
    args = parser.parse_args()
    report(args.company, args.mode)


if __name__ == "__main__":
    main()
