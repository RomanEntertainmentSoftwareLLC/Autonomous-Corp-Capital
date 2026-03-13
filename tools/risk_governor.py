#!/usr/bin/env python3
"""Simple risk governor that scans company results and enforces global limits."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "global_risk.yaml"
STATE_PATH = ROOT / "state" / "risk_governor.json"
RESULTS_DIR = ROOT / "results"
EVENT_LOG = ROOT / "state" / "risk_events.log"


def parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def summarize_log(path: Path) -> Dict[str, Optional[float]]:
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

    for line in path.open("r", encoding="utf-8"):
        if not line.strip():
            continue
        entry = json.loads(line)
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


def load_config() -> Dict[str, float]:
    if not CONFIG_PATH.exists():
        raise SystemExit("Global risk config missing")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_state() -> Dict[str, Optional[str]]:
    if not STATE_PATH.exists():
        return {"status": "ACTIVE", "notes": "System is operating normally."}
    with STATE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(state: Dict[str, Optional[str]]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def log_event(entry: str) -> None:
    EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(entry + "\n")


def evaluate() -> Dict[str, Optional[str]]:
    config = load_config()
    summaries = {}
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None
    total_open_positions = 0
    total_trades = 0
    max_account_sum = 0.0
    latest_account_sum = 0.0

    for company_dir in sorted(RESULTS_DIR.iterdir()):
        if not company_dir.is_dir():
            continue
        for mode_dir in company_dir.iterdir():
            log_path = mode_dir / "trade-log.jsonl"
            if not log_path.exists():
                continue
            summary = summarize_log(log_path)
            if not summary:
                continue
            key = f"{company_dir.name}-{mode_dir.name}"
            summaries[key] = summary
            total_trades += summary.get("trades", 0) or 0
            max_account_sum += summary.get("account_value", 0.0) or 0.0
            latest_account_sum += summary.get("account_value", 0.0) or 0.0
            open_positions = 1 if summary.get("alpha") is not None else 0
            total_open_positions += open_positions
            start = summary.get("start_time")
            end = summary.get("end_time")
            if start and (earliest is None or start < earliest):
                earliest = start
            if end and (latest is None or end > latest):
                latest = end

    system_drawdown = None
    if max_account_sum > 0 and latest_account_sum < max_account_sum:
        system_drawdown = (max_account_sum - latest_account_sum) / max_account_sum * 100

    trades_per_hour = None
    if earliest and latest and earliest != latest:
        hours = max(1.0, (latest - earliest).total_seconds() / 3600)
        trades_per_hour = total_trades / hours

    state = load_state()
    violations = []
    for name, summary in summaries.items():
        drawdown = summary.get("max_drawdown")
        if drawdown is not None and drawdown > config.get("max_company_drawdown_percent", 0):
            violations.append((name, "max_company_drawdown_percent", drawdown))
    if system_drawdown is not None and system_drawdown > config.get("max_system_drawdown_percent", 0):
        violations.append(("system", "max_system_drawdown_percent", system_drawdown))
    if trades_per_hour and trades_per_hour > config.get("max_trades_per_hour", 0):
        violations.append(("system", "max_trades_per_hour", trades_per_hour))
    if total_open_positions > config.get("max_total_open_positions", 0):
        violations.append(("system", "max_total_open_positions", total_open_positions))

    now = datetime.now(timezone.utc).isoformat()
    result = {"status": "ACTIVE", "rule": None, "reason": None, "timestamp": now}
    if violations:
        name, rule, value = violations[0]
        reason = f"{rule} violation ({value}) in {name}"
        result.update({
            "status": "HALTED",
            "rule": rule,
            "reason": reason,
            "timestamp": now,
        })
        state.update({
            "status": "HALTED",
            "halted_at": now,
            "halt_reason": reason,
            "triggered_rule": rule,
            "notes": f"System halted by governor; {reason}",
        })
        log_event(f"{now} HALT {rule} -> {name}: {value}")
        print("SYSTEM HALT: trading paused by risk governor")
        print(f"Rule triggered: {reason}")
    else:
        state.update({
            "status": "ACTIVE",
            "halted_at": None,
            "halt_reason": None,
            "triggered_rule": None,
            "notes": "All checks passed.",
        })
        result.update({"status": "ACTIVE", "reason": "None"})
        print("Risk governor remains ACTIVE")
    save_state(state)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate global risk limits based on results")
    parser.add_argument("--json", type=Path, help="Write governor summary to JSON")
    args = parser.parse_args()
    summary = evaluate()
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, indent=2))
        print(f"Wrote summary to {args.json}")


if __name__ == "__main__":
    main()
