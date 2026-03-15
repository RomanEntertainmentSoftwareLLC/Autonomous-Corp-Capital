#!/usr/bin/env python3
"""Evaluate company lifecycle transitions using metadata and results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import sqlite3
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting_utils import compute_fitness, determine_evaluation_state

WAREHOUSE = ROOT / "data" / "warehouse.sqlite"
COMPANIES_DIR = ROOT / "companies"
LIFECYCLE_CONFIG = ROOT / "config" / "lifecycle.yaml"

LIFECYCLE_RULES = [
    "UNTESTED",
    "NEW",
    "TESTING",
    "ACTIVE",
    "PROMOTED",
    "DECLINING",
    "PAUSED",
    "RETIRED",
    "ARCHIVED",
]


def percentile_value(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(round((percentile / 100.0) * (len(sorted_values) - 1)))
    index = max(0, min(len(sorted_values) - 1, index))
    return sorted_values[index]



def load_metadata() -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for company_dir in COMPANIES_DIR.iterdir():
        if not company_dir.is_dir():
            continue
        meta_path = company_dir / "metadata.yaml"
        data: Dict[str, Any] = {}
        if meta_path.exists():
            data = yaml.safe_load(meta_path.open("r", encoding="utf-8")) or {}
        mapping[company_dir.name] = data
    return mapping


def save_metadata(company: str, data: Dict[str, Any]) -> None:
    path = COMPANIES_DIR / company / "metadata.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh)


def evaluate_state(
    company: str,
    state: str,
    metrics: Dict[str, float],
    promotion_threshold: float,
    retirement_threshold: float,
    config: Dict[str, float],
    decline_strikes: int,
    promotion_streak: int,
) -> str:
    if state not in LIFECYCLE_RULES:
        state = "NEW"
    if not metrics:
        return "UNTESTED"
    score = compute_fitness(metrics)
    account = metrics.get("account", 0)
    drawdown = metrics.get("drawdown", 0)
    decline_limit = int(config.get("decline_strike_count", 3))
    pause_after_decline = config.get("pause_after_decline", 8)
    promotion_min_runs = int(config.get("promotion_min_runs", 2))

    if state in {"NEW", "UNTESTED"}:
        return "TESTING"
    if state == "TESTING":
        if account > 105 and metrics.get("trade_count", 0) >= promotion_min_runs:
            return "ACTIVE"
        return "TESTING"
    if state == "ACTIVE":
        if score >= promotion_threshold:
            return "PROMOTED"
        if score <= retirement_threshold or drawdown > pause_after_decline:
            return "DECLINING"
        return "ACTIVE"
    if state == "PROMOTED":
        if score < promotion_threshold * 0.5:
            return "ACTIVE"
        return "PROMOTED"
    if state == "DECLINING":
        if decline_strikes >= decline_limit and drawdown > pause_after_decline:
            return "PAUSED"
        if score >= promotion_threshold and metrics.get("trade_count", 0) >= promotion_min_runs:
            return "ACTIVE"
        return "DECLINING"
    if state == "PAUSED":
        if decline_strikes >= decline_limit * 2:
            return "RETIRED"
        if score > promotion_threshold:
            return "ACTIVE"
        return "PAUSED"
    if state == "RETIRED":
        return "ARCHIVED"
    return state


def load_lifecycle_config() -> Dict[str, float]:
    if not LIFECYCLE_CONFIG.exists():
        return {}
    with LIFECYCLE_CONFIG.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {k: float(v) for k, v in data.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate lifecycle transitions for companies")
    parser.add_argument("--json", type=Path, help="Write transitions to JSON")
    args = parser.parse_args()

    if not WAREHOUSE.exists():
        raise SystemExit("Warehouse not initialized; run tools/init_warehouse.py first")

    metadata = load_metadata()
    config = load_lifecycle_config()
    promotion_percentile = float(config.get("promotion_percentile", 90))
    retirement_percentile = float(config.get("retirement_percentile", 20))
    transitions = []

    with sqlite3.connect(WAREHOUSE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT latest_fitness FROM company_performance WHERE latest_fitness IS NOT NULL")
        fitness_scores = [row[0] for row in cursor.fetchall() if row[0] is not None]
        promotion_threshold = percentile_value(fitness_scores, promotion_percentile)
        retirement_threshold = percentile_value(fitness_scores, retirement_percentile)
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
                   ac.strategy_name
            FROM companies c
            LEFT JOIN company_performance cp ON cp.company_id = c.id
            LEFT JOIN analytics_companies ac ON ac.company_id = c.id
            """
        )
        rows = cursor.fetchall()

    for row in rows:
        (
            company,
            account_value,
            realized,
            row_unrealized,
            trade_count,
            win_rate,
            drawdown,
            regime,
            canonical_state,
            fitness_value,
            strategy_hint,
        ) = row
        meta = metadata.setdefault(company, {})
        current_state = meta.get("lifecycle_state") or canonical_state or "NEW"
        decline_strikes = int(meta.get("decline_strikes", 0))
        promotion_streak = int(meta.get("promotion_streak", 0))
        metrics: Dict[str, float] = {}
        if account_value is not None:
            metrics = {
                "account": account_value,
                "realized_pnl": realized or 0.0,
                "unrealized_pnl": row_unrealized or 0.0,
                "win_rate": win_rate or 0.0,
                "drawdown": drawdown or 0.0,
                "trade_count": int(trade_count or 0),
            }
        eval_state, eval_reason = determine_evaluation_state(metrics)
        new_state = evaluate_state(
            company,
            current_state,
            metrics,
            promotion_threshold,
            retirement_threshold,
            config,
            decline_strikes,
            promotion_streak,
        )
        transitions.append(
            {
                "company": company,
                "current_state": current_state,
                "new_state": new_state,
                "strategy": strategy_hint,
                "account": account_value,
                "fitness": fitness_value,
                "evaluation_state": eval_state,
                "evaluation_reason": eval_reason,
                "unrealized": row_unrealized,
            }
        )
        decline_strikes = decline_strikes + 1 if new_state == "DECLINING" else 0
        promotion_streak = promotion_streak + 1 if new_state == "PROMOTED" else 0
        meta["lifecycle_state"] = new_state
        meta["decline_strikes"] = decline_strikes
        meta["promotion_streak"] = promotion_streak
        meta["last_fitness"] = fitness_value
        meta["evaluation_state"] = eval_state
        meta["evaluation_reason"] = eval_reason
        company_path = COMPANIES_DIR / company
        if company_path.exists():
            save_metadata(company, meta)
        account_display = f"{account_value:>8.2f}" if account_value is not None else "N/A"
        fitness_display = f"{fitness_value:>6.2f}" if fitness_value is not None else "N/A"
        strategy_label = strategy_hint or meta.get("strategy") or "N/A"
        print(f"Company: {company}")
        print(f"  Lifecycle: {current_state} -> {new_state}")
        print(f"  Eval state: {eval_state}")
        if eval_reason:
            print(f"  Reason: {eval_reason}")
        print(f"  Strategy: {strategy_label:<12} account={account_display} fitness={fitness_display}")
        print()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(transitions, indent=2))
        print(f"Lifecycle transitions written to {args.json}")


if __name__ == "__main__":
    main()
    try:
        from tools.company_roster import roster_sync
    except ImportError:
        pass
    else:
        roster_sync()
