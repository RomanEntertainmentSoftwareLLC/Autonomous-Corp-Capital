#!/usr/bin/env python3
"""Choose a parent company based on recent results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def iter_log_entries(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def summarize_trade_log(path: Path) -> Tuple[float, float]:
    total_trades = 0
    realized = 0.0
    last_entries: Dict[str, dict] = {}

    for entry in iter_log_entries(path):
        if entry.get("executed"):
            total_trades += 1
            pnl = entry.get("pnl")
            if isinstance(pnl, (int, float)):
                realized += pnl
        symbol = entry.get("symbol", "UNKNOWN")
        last_entries[symbol] = entry

    if not last_entries:
        return 0.0, 0.0

    account = sum(
        e.get("cash_after", 0.0) + e.get("position_after", 0.0) * e.get("price", 0.0)
        for e in last_entries.values()
    )

    return account, realized


def choose_parent(metric: str) -> None:
    if not RESULTS_DIR.exists():
        print("No results directory found.")
        return

    candidates: List[Tuple[str, str, float, float]] = []
    for company_dir in sorted(RESULTS_DIR.iterdir()):
        if not company_dir.is_dir():
            continue
        for mode_dir in sorted(company_dir.iterdir()):
            if not mode_dir.is_dir():
                continue
            log_path = mode_dir / "trade-log.jsonl"
            if not log_path.exists():
                continue
            account, realized = summarize_trade_log(log_path)
            candidates.append((company_dir.name, mode_dir.name, account, realized))

    if not candidates:
        print("No completed companies found in results.")
        return

    if metric == "account_value":
        key = lambda row: row[2]
    else:
        key = lambda row: row[3]

    best = max(candidates, key=key)
    metric_value = best[2] if metric == "account_value" else best[3]

    print("Parent selection summary:")
    for company, mode, account, realized in candidates:
        print(f"  {company} ({mode}) — account_value=${account:.2f} | realized_pnl=${realized:.2f}")
    print("\nChosen parent:")
    print(
        f"  {best[0]} ({best[1]}) with {metric} = ${metric_value:.2f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Select a parent company for evolution")
    parser.add_argument(
        "--metric",
        choices=["account_value", "realized_pnl"],
        default="account_value",
        help="Metric to maximize when choosing parent",
    )
    args = parser.parse_args()

    choose_parent(args.metric)


if __name__ == "__main__":
    main()
