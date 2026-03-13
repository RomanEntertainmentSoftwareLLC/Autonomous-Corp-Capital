#!/usr/bin/env python3
"""Simple decision engine for trading companies."""

from __future__ import annotations

import argparse
import json
import yaml
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from typing import Any, Dict, Iterable, List, Tuple

from tools.company_metadata import read_metadata
from tradebot.strategies.factory import resolve_strategy_name

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
COMPANIES_DIR = Path(__file__).resolve().parent.parent / "companies"


def iter_log_entries(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            yield json.loads(text)


def summarize(path: Path) -> Dict[str, Any]:
    trades = 0
    wins = 0
    realized = 0.0
    latest_account = 0.0
    latest_unrealized = 0.0
    creatures = {}

    for entry in iter_log_entries(path):
        sym = entry.get("symbol", "UNKNOWN")
        creatures[sym] = entry
        if entry.get("executed"):
            trades += 1
            pnl = entry.get("pnl")
            if isinstance(pnl, (int, float)):
                realized += pnl
                if pnl > 0:
                    wins += 1
        latest_account = sum(
            e.get("cash_after", 0.0) + e.get("position_after", 0.0) * e.get("price", 0.0)
            for e in creatures.values()
        )
        latest_unrealized = sum(e.get("unrealized_pnl", 0.0) for e in creatures.values())

    win_rate = None
    if trades > 0:
        win_rate = wins / trades * 100
    drawdown = None
    if creatures:
        high = max(
            e.get("cash_after", 0.0) + e.get("position_after", 0.0) * e.get("price", 0.0)
            for e in creatures.values()
        )
        if high > 0 and latest_account < high:
            drawdown = (high - latest_account) / high * 100

    return {
        "mode": path.parent.name,
        "account_value": latest_account,
        "realized_pnl": realized,
        "unrealized_pnl": latest_unrealized,
        "trades": trades,
        "win_rate": win_rate,
        "drawdown": drawdown,
    }


def collect(company: str) -> List[Dict[str, Any]]:
    results = []
    base = RESULTS_DIR / company
    if not base.exists():
        return results
    for mode_dir in sorted(base.iterdir()):
        if not mode_dir.is_dir():
            continue
        file = mode_dir / "trade-log.jsonl"
        if not file.exists():
            continue
        results.append(summarize(file))
    return results


def load_config(company: str) -> Dict[str, Any]:
    path = COMPANIES_DIR / company / "config.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def strategies(config: Dict[str, Any]) -> List[str]:
    names = []
    for symbol in config.get("symbols", []):
        strat = resolve_strategy_name(symbol)
        if strat not in names:
            names.append(strat)
    return names


def score(company: str, row: Dict[str, Any]) -> float:
    return row["account_value"] + row["realized_pnl"] * 10


def decide(company: str, row: Dict[str, Any]) -> Tuple[str, str]:
    if row["account_value"] > 150 and row["realized_pnl"] >= 0 and row["trades"] >= 2:
        return "CLONE", "Strong occupant—recommend cloning"
    if row["realized_pnl"] >= 0:
        return "KEEP", "Stable; keep running"
    if row["account_value"] < 50:
        return "RETIRE", "Account dwindling; consider retiring"
    return "TEST_MORE", "Mixed results; need more data"


def gate_status(rec: str) -> Dict[str, str]:
    if rec == "CLONE":
        return {"tester_status": "pending", "reviewer_status": "pending"}
    if rec == "TEST_MORE":
        return {"tester_status": "pending", "reviewer_status": "pending"}
    return {"tester_status": "pass", "reviewer_status": "pass"}


def _strategy_insight(recommendation: str, strat: List[str]) -> str:
    if not strat:
        return ""
    primary = strat[0]
    if recommendation == "CLONE":
        return f"(clone strategy '{primary}' to spread success)"
    if recommendation == "RETIRE":
        return f"(retire '{primary}' to cut losses)"
    if recommendation == "TEST_MORE":
        return f"(consider testing alternative strategy after '{primary}')"
    return f"(keep running '{primary}')"


def _state_adjustment(recommendation: str, state: str) -> (str, str):
    note = ""
    rec = recommendation
    if state in {"RETIRED", "ARCHIVED"}:
        rec = "RETIRE"
        note = "(already retired)"
    elif state == "PROMOTED":
        rec = "CLONE"
        note = "(promoted strategy)"
    elif state == "DECLINING" and recommendation not in {"RETIRE", "PAUSE"}:
        rec = "TEST_MORE"
        note = "(declining; collect more data)"
    return rec, note


def main() -> None:
    parser = argparse.ArgumentParser(description="Manager decision engine")
    parser.add_argument("--metric", choices=["account_value", "realized_pnl"], default="account_value")
    args = parser.parse_args()

    companies = sorted(p.name for p in COMPANIES_DIR.iterdir() if p.is_dir())
    decisions = []
    for company in companies:
        metadata = read_metadata(company)
        parent = metadata.get("parent_company", "<none>")
        generation = metadata.get("generation", "<unknown>")
        config = load_config(company)
        strat = strategies(config)
        results = collect(company)
        best = None
        if results:
            best = max(results, key=lambda r: (r[args.metric], r["account_value"]))
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
        state = metadata.get("lifecycle_state", "NEW")
        recommendation, reason = decide(company, best)
        adjusted_rec, state_note = _state_adjustment(recommendation, state)
        statuses = gate_status(adjusted_rec)
        decisions.append(
            (
                company,
                parent,
                generation,
                best,
                adjusted_rec,
                f"{reason} {state_note}".strip()
                if state_note
                else reason,
                strat,
                state,
                statuses,
            )
        )

    decisions.sort(key=lambda d: score(d[0], d[3]), reverse=True)

    print("Manager decisions:")
    print("=" * 60)
    for company, parent, generation, best, rec, reason, strat, state, statuses in decisions:
        win_rate = f"{best['win_rate']:.2f}%" if best['win_rate'] is not None else "N/A"
        drawdown = f"{best['drawdown']:.2f}%" if best['drawdown'] is not None else "N/A"
        strategy_list = ", ".join(strat) if strat else "<none>"
        print(f"{company} (gen {generation}, parent={parent}, state={state})")
        print(f"  Latest mode: {best['mode']}  Account: ${best['account_value']:.2f}  Realized: ${best['realized_pnl']:.2f}")
        print(f"  Trades: {best['trades']}  Win rate: {win_rate}  Drawdown: {drawdown}")
        print(f"  Strategies: {strategy_list}")
        strategy_note = _strategy_insight(rec, strat)
        print(f"  Recommendation: {rec} — {reason} {strategy_note}")
        print(f"  Tester status: {statuses['tester_status']}  Reviewer status: {statuses['reviewer_status']}")
        print("-" * 60)

    if not decisions:
        print("No companies found.")
        return

    top = decisions[0]
    worst = decisions[-1]
    clone_targets = [d for d in decisions if d[4] == "CLONE"]
    retire_targets = [d for d in decisions if d[4] == "RETIRE"]
    clone_candidate = clone_targets[0] if clone_targets else top
    retire_candidate = retire_targets[0] if retire_targets else worst
    avg_account = sum(d[3]["account_value"] for d in decisions) / len(decisions)
    print("Board meeting summary:")
    print(f"  Top company: {top[0]} (account ${top[3]['account_value']:.2f}, strategy mix: {', '.join(top[6]) or '<none>'})")
    print(f"  Worst company: {worst[0]} (state={worst[7]}, account ${worst[3]['account_value']:.2f})")
    print(f"  Proposed clone target: {clone_candidate[0]} (recommendation {clone_candidate[4]}, tester {clone_candidate[8]['tester_status']}, reviewer {clone_candidate[8]['reviewer_status']})")
    print(f"  Proposed retirement target: {retire_candidate[0]} (recommendation {retire_candidate[4]})")
    print(f"  General note: average account across companies is ${avg_account:.2f}, win rates range around {', '.join(str(d[3].get('win_rate', 'N/A')) for d in decisions)}.")
