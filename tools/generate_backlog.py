#!/usr/bin/env python3
"""Generate a product-backlog list based on manager insights."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.company_metadata import read_metadata
from tradebot.strategies.factory import resolve_strategy_name
import tools.manager_decide as md

RESULTS_DIR = ROOT / "results"
COMPANIES_DIR = ROOT / "companies"


def collect_decisions(metric: str) -> List[Dict[str, object]]:
    companies = sorted(p.name for p in COMPANIES_DIR.iterdir() if p.is_dir())
    decisions = []
    for company in companies:
        metadata = read_metadata(company)
        parent = metadata.get("parent_company", "<none>")
        generation = metadata.get("generation", "<unknown>")
        config = md.load_config(company)
        strat = md.strategies(config)
        results = md.collect(company)
        if results:
            best = max(results, key=lambda r: (r[metric], r["account_value"]))
        else:
            best = {
                "mode": "<none>",
                "account_value": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "trades": 0,
                "win_rate": None,
                "drawdown": None,
            }
        rec, reason = md.decide(company, best)
        decisions.append(
            {
                "company": company,
                "parent": parent,
                "generation": generation,
                "best": best,
                "recommendation": rec,
                "reason": reason,
                "strategies": strat,
            }
        )
    decisions.sort(key=lambda d: d["best"][metric], reverse=True)
    return decisions


def build_backlog(decisions: List[Dict[str, object]]) -> List[Dict[str, object]]:
    backlog = []
    for entry in decisions:
        best = entry["best"]
        rec = entry["recommendation"]
        note = f"Last mode {best['mode']}, account ${best['account_value']:.2f}, trades {best['trades']}"
        if best.get("win_rate") is not None:
            note += f", win rate {best['win_rate']:.1f}%"
        action = None
        priority = "medium"
        if rec == "CLONE":
            action = f"Clone {entry['company']} into next generation (keep strategies {entry['strategies']})."
            priority = "high"
        elif rec == "KEEP":
            action = (
                f"Continue monitoring {entry['company']} with current strategy mix {entry['strategies']}. "
                f"Consider increasing backtest iterations if volatility grows."
            )
        elif rec == "TEST_MORE":
            action = f"Run targeted tests for {entry['company']} focusing on strategy mix {entry['strategies']} to gather more data."
            priority = "high"
        elif rec == "RETIRE":
            action = f"Prepare to retire {entry['company']} (accounts {best['account_value']:.2f}); review risk settings."
            priority = "high"
        else:
            action = f"Review decision for {entry['company']}."
        backlog.append(
            {
                "company": entry["company"],
                "recommendation": rec,
                "priority": priority,
                "action": action,
                "details": note,
            }
        )
    return backlog


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate backlog items from company performance")
    parser.add_argument("--metric", choices=["account_value", "realized_pnl"], default="account_value")
    args = parser.parse_args()

    decisions = collect_decisions(args.metric)
    backlog = build_backlog(decisions)
    output = {
        "summary": f"Generated {len(backlog)} backlog items based on {args.metric} ranking.",
        "items": backlog,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
