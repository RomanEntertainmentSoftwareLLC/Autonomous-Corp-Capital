#!/usr/bin/env python3
"""Evaluate company lifecycle transitions using metadata and results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import sqlite3
import yaml

ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = ROOT / "data" / "warehouse.sqlite"
COMPANIES_DIR = ROOT / "companies"
LIFECYCLE_CONFIG = ROOT / "config" / "lifecycle.yaml"

FITNESS_WEIGHTS = {
    "realized_pnl": 1.0,
    "unrealized_pnl": 0.25,
    "win_rate": 0.5,
    "drawdown": -2.0,
}

LIFECYCLE_RULES = [
    "NEW",
    "TESTING",
    "ACTIVE",
    "PROMOTED",
    "DECLINING",
    "PAUSED",
    "RETIRED",
    "ARCHIVED",
]


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
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh)


def fitness(metrics: Dict[str, float]) -> float:
    score = 0.0
    score += metrics.get("realized_pnl", 0.0) * FITNESS_WEIGHTS["realized_pnl"]
    score += metrics.get("unrealized_pnl", 0.0) * FITNESS_WEIGHTS["unrealized_pnl"]
    score += metrics.get("win_rate", 0.0) * FITNESS_WEIGHTS["win_rate"]
    score += metrics.get("drawdown", 0.0) * FITNESS_WEIGHTS["drawdown"]
    return score


def load_latest_results(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT company, strategy, account_value, realized_pnl, drawdown FROM latest_company_results"
    )
    data = {}
    for company, strategy, account, realized, drawdown in cursor.fetchall():
        data[company] = {
            "strategy": strategy,
            "account": account or 0.0,
            "realized_pnl": realized or 0.0,
            "drawdown": drawdown or 0.0,
            "win_rate": 0.0,
        }
    return data


def evaluate_state(
    company: str,
    state: str,
    metrics: Dict[str, float],
    config: Dict[str, float],
    decline_strikes: int,
    promotion_streak: int,
) -> str:
    if state not in LIFECYCLE_RULES:
        state = "NEW"
    score = fitness(metrics)
    account = metrics.get("account", 0)
    drawdown = metrics.get("drawdown", 0)
    promotion_threshold = config.get("promotion_percentile", 90)
    retirement_threshold = config.get("retirement_percentile", 20)
    decline_limit = int(config.get("decline_strike_count", 3))
    pause_after_decline = config.get("pause_after_decline", 8)
    promotion_min_runs = int(config.get("promotion_min_runs", 2))

    if state == "NEW":
        return "TESTING" if metrics else "NEW"
    if state == "TESTING":
        if metrics and account > 105 and metrics.get("trade_count", 0) >= promotion_min_runs:
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
    with sqlite3.connect(WAREHOUSE) as conn:
        latest = load_latest_results(conn)
    config = load_lifecycle_config()
    transitions = []
    for company, meta in metadata.items():
        current_state = meta.get("lifecycle_state", "NEW")
        metrics = latest.get(company, {})
        decline_strikes = int(meta.get("decline_strikes", 0))
        promotion_streak = int(meta.get("promotion_streak", 0))
        score_value = fitness(metrics)
        new_state = evaluate_state(company, current_state, metrics, config, decline_strikes, promotion_streak)
        transitions.append(
            {
                "company": company,
                "current_state": current_state,
                "new_state": new_state,
                "strategy": metrics.get("strategy"),
                "account": metrics.get("account"),
                "fitness": score_value,
            }
        )
        decline_strikes = decline_strikes + 1 if new_state == "DECLINING" else 0
        promotion_streak = promotion_streak + 1 if new_state == "PROMOTED" else 0
        meta["lifecycle_state"] = new_state
        meta["decline_strikes"] = decline_strikes
        meta["promotion_streak"] = promotion_streak
        meta["last_fitness"] = score_value
        save_metadata(company, meta)
        print(
            f"{company:<12} {current_state:<10} -> {new_state:<10}  strategy={metrics.get('strategy', '<none>')}" 
            f" account={metrics.get('account', 0):>8.2f} fitness={score_value:>6.2f}"
        )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(transitions, indent=2))
        print(f"Lifecycle transitions written to {args.json}")


if __name__ == "__main__":
    main()
