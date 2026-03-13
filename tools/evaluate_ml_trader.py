#!/usr/bin/env python3
"""Evaluate ML trader vs baseline strategies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def iter_log(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def summarize(path: Path) -> Dict[str, object]:
    trades = 0
    wins = 0
    realized = 0.0
    last: Dict[str, object] = {}
    account_history: List[float] = []

    for entry in iter_log(path):
        last = entry
        if entry.get("executed"):
            trades += 1
            pnl = entry.get("pnl")
            if isinstance(pnl, (int, float)):
                realized += pnl
                if pnl > 0:
                    wins += 1
        cash = entry.get("cash_after", 0.0)
        position = entry.get("position_after", 0.0)
        price = entry.get("price", 0.0)
        account_history.append(cash + position * price)

    if not last:
        return {"trades": 0, "account_value": 0.0, "realized_pnl": 0.0, "win_rate": None, "max_drawdown": None}

    account = sum(
        entry.get("cash_after", 0.0) + entry.get("position_after", 0.0) * entry.get("price", 0.0)
        for entry in [last]
    )
    win_rate = wins / trades * 100 if trades else None
    max_account = max(account_history) if account_history else account
    drawdown = None
    if max_account > 0 and account < max_account:
        drawdown = (max_account - account) / max_account * 100

    return {
        "account_value": account,
        "realized_pnl": realized,
        "trades": trades,
        "win_rate": win_rate,
        "max_drawdown": drawdown,
        "symbol": last.get("symbol"),
        "strategy": last.get("strategy"),
        "mode": last.get("mode"),
    }


def collect_company(company: str) -> Dict[str, Dict[str, object]]:
    base = RESULTS_DIR / company
    metrics: Dict[str, Dict[str, object]] = {}
    if not base.exists():
        return metrics
    for mode_dir in sorted(base.iterdir()):
        if not mode_dir.is_dir():
            continue
        log_path = mode_dir / "trade-log.jsonl"
        if not log_path.exists():
            continue
        metrics[mode_dir.name] = summarize(log_path)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare strategy performance")
    parser.add_argument("companies", nargs="*", default=["company_001", "company_002", "company_004"], help="Companies to compare")
    parser.add_argument("--mode", default="backtest", help="Mode to compare (backtest/paper)")
    args = parser.parse_args()
    rows = []
    for company in args.companies:
        data = collect_company(company).get(args.mode)
        if not data:
            continue
        rows.append((company, data))
    if not rows:
        print("No results found")
        return
    print("Strategy comparison (mode=", args.mode, ")", sep="")
    print("company | strategy | trades | account | realized | win % | drawdown")
    print("-" * 80)
    for company, data in rows:
        win = f"{data['win_rate']:.2f}%" if data["win_rate"] is not None else "N/A"
        draw = f"{data['max_drawdown']:.2f}%" if data["max_drawdown"] is not None else "N/A"
        strategy = data.get("strategy") or "<multi>"
        print(
            f"{company:<10} | {strategy:<20} | {data['trades']:>6} | ${data['account_value']:>7.2f} | "
            f"${data['realized_pnl']:>7.2f} | {win:<6} | {draw:<6}"
        )


if __name__ == "__main__":
    main()
