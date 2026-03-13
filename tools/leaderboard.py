#!/usr/bin/env python3
"""Rank companies by performance across results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradebot.regime import classify_regime

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def iter_log_entries(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def summarize(path: Path) -> Dict[str, object]:
    trades = 0
    wins = 0
    realized = 0.0
    account_history: List[float] = []
    latest_account = 0.0
    latest_unrealized = 0.0

    prices: List[float] = []
    starting_account: Optional[float] = None
    first_price: Optional[float] = None
    last_price: Optional[float] = None

    for entry in iter_log_entries(path):
        if entry.get("executed"):
            trades += 1
            pnl = entry.get("pnl") or 0.0
            realized += pnl
            if pnl > 0:
                wins += 1
        cash = entry.get("cash_after", 0.0)
        position = entry.get("position_after", 0.0)
        price = entry.get("price", 0.0)
        account_value = cash + position * price
        account_history.append(account_value)
        latest_account = account_value
        latest_unrealized = entry.get("unrealized_pnl", 0.0)
        if starting_account is None:
            starting_account = entry.get("cash_before", cash)
        if first_price is None and price is not None:
            first_price = price
        last_price = price
        if price is not None:
            prices.append(price)

    win_rate = wins / trades * 100 if trades else None
    max_account = max(account_history) if account_history else latest_account
    drawdown = None
    if max_account > 0 and latest_account < max_account:
        drawdown = (max_account - latest_account) / max_account * 100

    regime = classify_regime(prices)
    company_return = None
    if starting_account and starting_account != 0:
        company_return = (latest_account - starting_account) / starting_account
    benchmark_return = None
    if first_price and last_price and first_price != 0:
        benchmark_return = (last_price - first_price) / first_price
    alpha = None
    if company_return is not None and benchmark_return is not None:
        alpha = company_return - benchmark_return

    return {
        "account_value": latest_account,
        "realized_pnl": realized,
        "unrealized_pnl": latest_unrealized,
        "trades": trades,
        "win_rate": win_rate,
        "max_drawdown": drawdown,
        "regime": regime,
        "company_return": company_return,
        "benchmark_return": benchmark_return,
        "alpha": alpha,
    }


def collect(mode_filter: str | None = None, company_filter: str | None = None) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for company_dir in sorted(RESULTS_DIR.iterdir()):
        if not company_dir.is_dir():
            continue
        company_name = company_dir.name
        if company_filter and company_name != company_filter:
            continue
        for mode_dir in sorted(company_dir.iterdir()):
            if not mode_dir.is_dir():
                continue
            mode_name = mode_dir.name
            if mode_filter and mode_name != mode_filter:
                continue
            log_path = mode_dir / "trade-log.jsonl"
            if not log_path.exists():
                continue
            summary = summarize(log_path)
            rows.append(
                {
                    "company": company_name,
                    "mode": mode_name,
                    **summary,
                }
            )
    return rows


# Fitness scoring weights (tweakable)
FITNESS_WEIGHTS = {
    "realized_pnl": 1.0,
    "unrealized_pnl": 0.25,
    "win_rate": 0.5,
    "max_drawdown": -2.0,
    "trades": -0.05,
}


def score(row: Dict[str, object]) -> float:
    win_rate = row.get("win_rate") or 0.0
    drawdown = row.get("max_drawdown") or 0.0
    return (
        float(row.get("realized_pnl", 0.0)) * FITNESS_WEIGHTS["realized_pnl"]
        + float(row.get("unrealized_pnl", 0.0)) * FITNESS_WEIGHTS["unrealized_pnl"]
        + win_rate * FITNESS_WEIGHTS["win_rate"]
        + drawdown * FITNESS_WEIGHTS["max_drawdown"]
        + float(row.get("trades", 0)) * FITNESS_WEIGHTS["trades"]
    )


def recommend(fitness: float) -> str:
    if fitness >= 30:
        return "CLONE"
    if fitness <= -40:
        return "RETIRE"
    if fitness >= 0:
        return "KEEP"
    return "TEST_MORE"


def main() -> None:
    parser = argparse.ArgumentParser(description="Leaderboard of companies by performance")
    parser.add_argument("--mode", help="Optional mode filter (backtest/paper)")
    parser.add_argument("--company", help="Optional company filter to narrow the table")
    parser.add_argument("--json-output", type=Path, help="Optional JSON export path")
    args = parser.parse_args()

    rows = collect(args.mode, args.company)
    if not rows:
        print("No results found")
        return
    rows.sort(key=score, reverse=True)

    print("Leaderboard")
    print("company     mode    trades  account   realized  unrealized  win%   drawdown   fitness   alpha    regime")
    print("-----------------------------------------------------------------------------------------------")
    export_rows = []
    for row in rows:
        win = f"{row['win_rate']:.2f}%" if row["win_rate"] is not None else "N/A"
        draw = f"{row['max_drawdown']:.2f}%" if row["max_drawdown"] is not None else "N/A"
        fitness = score(row)
        regime = row.get("regime", "unknown")
        rec = recommend(fitness)
        alpha = row.get("alpha") or 0.0
        print(
            f"{row['company']:<10} {row['mode']:<7} {row['trades']:>6}  ${row['account_value']:>7.2f}  "
            f"${row['realized_pnl']:>7.2f}  ${row['unrealized_pnl']:>9.2f}  {win:<6} {draw:<6} {fitness:>9.2f} {alpha:>7.2f} {regime:<12}"
        )
        export_rows.append(
            {
                "company": row["company"],
                "mode": row["mode"],
                "trades": row["trades"],
                "account_value": row["account_value"],
                "realized_pnl": row["realized_pnl"],
                "unrealized_pnl": row["unrealized_pnl"],
                "win_rate": row["win_rate"],
                "max_drawdown": row["max_drawdown"],
                "fitness": fitness,
                "alpha": row.get("alpha"),
                "recommendation": rec,
                "regime": regime,
            }
        )
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps({"rows": export_rows}, indent=2))
        print(f"Exported leaderboard to {args.json_output}")


if __name__ == "__main__":
    main()
