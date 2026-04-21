#!/usr/bin/env python3
"""ACC Target Engine v1.

Builds an objective target state for a live/paper run.

This is intentionally deterministic. Agents such as Grant, Vivienne, Axiom,
and the dashboard should consume this file instead of inventing target math.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/openclaw/.openclaw/workspace")
RUNS_DIR = ROOT / "state" / "live_runs"
LATEST_TARGET = ROOT / "state" / "targets" / "latest_target_state.json"

COMPANIES = ["company_001", "company_002", "company_003", "company_004"]

DEFAULT_FLOOR_MULTIPLIER = 1.04
DEFAULT_GOAL_MULTIPLIER = 1.20
DEFAULT_STRETCH_MULTIPLIER = 2.00
DEFAULT_GRANT_10X_MULTIPLIER = 10.00


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def round_money(value: float | None, places: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), places)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def latest_run_dir() -> Path:
    runs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    if not runs:
        raise SystemExit(f"No run folders found under {RUNS_DIR}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def run_dir_from_arg(run_id: str | None) -> Path:
    if not run_id:
        return latest_run_dir()
    p = RUNS_DIR / run_id
    if not p.exists():
        raise SystemExit(f"Run folder not found: {p}")
    return p


def position_value(snapshot: dict[str, Any]) -> float:
    details = snapshot.get("positions_detail") or {}
    total = 0.0
    if isinstance(details, dict):
        for item in details.values():
            if not isinstance(item, dict):
                continue
            qty = safe_float(item.get("qty"), 0.0) or 0.0
            mark = safe_float(item.get("mark_price"), safe_float(item.get("entry_price"), 0.0)) or 0.0
            total += qty * mark
    return total


def latest_company_snapshots(portfolio_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in portfolio_rows:
        company = row.get("company")
        if isinstance(company, str) and company:
            latest[company] = row
    return latest


def company_equity(snapshot: dict[str, Any]) -> float:
    cash = safe_float(snapshot.get("cash"), 0.0) or 0.0
    market_value = position_value(snapshot)
    equity = cash + market_value
    if abs(equity) > 1e-12:
        return equity
    for key in ("equity", "account_value"):
        if key in snapshot:
            fallback = safe_float(snapshot.get(key), None)
            if fallback is not None:
                return float(fallback)
    return cash


def build_targets(starting_equity: float, current_equity: float | None) -> dict[str, Any]:
    floor = starting_equity * DEFAULT_FLOOR_MULTIPLIER
    goal = starting_equity * DEFAULT_GOAL_MULTIPLIER
    stretch = starting_equity * DEFAULT_STRETCH_MULTIPLIER
    grant_10x = starting_equity * DEFAULT_GRANT_10X_MULTIPLIER

    if current_equity is None:
        status = "unknown_current_equity"
        pnl = None
        distances = {
            "floor": None,
            "goal": None,
            "stretch": None,
            "grant_10x": None,
        }
    else:
        pnl = current_equity - starting_equity
        if current_equity >= grant_10x:
            status = "hit_grant_10x"
        elif current_equity >= stretch:
            status = "hit_stretch"
        elif current_equity >= goal:
            status = "hit_goal"
        elif current_equity >= floor:
            status = "hit_floor"
        elif pnl >= 0:
            status = "green_but_below_floor"
        else:
            status = "negative"
        distances = {
            "floor": floor - current_equity,
            "goal": goal - current_equity,
            "stretch": stretch - current_equity,
            "grant_10x": grant_10x - current_equity,
        }

    return {
        "starting_equity": round_money(starting_equity),
        "current_equity": round_money(current_equity),
        "pnl": round_money(pnl),
        "targets": {
            "floor": round_money(floor),
            "goal": round_money(goal),
            "stretch": round_money(stretch),
            "grant_10x": round_money(grant_10x),
        },
        "profit_targets": {
            "floor": round_money(floor - starting_equity),
            "goal": round_money(goal - starting_equity),
            "stretch": round_money(stretch - starting_equity),
            "grant_10x": round_money(grant_10x - starting_equity),
        },
        "distances": {k: round_money(v) for k, v in distances.items()},
        "status": status,
    }


def build_target_state_from_run(run_dir: Path, write: bool = False) -> dict[str, Any]:
    artifacts = run_dir / "artifacts"
    allocation = read_json(artifacts / "allocation_state.json", {}) or {}
    portfolio_rows = read_jsonl(artifacts / "portfolio_state.jsonl")

    parent_total = safe_float(allocation.get("parent_total"), 0.0) or 0.0
    reserve_amount = safe_float(allocation.get("reserve_amount"), 0.0) or 0.0
    deployable_amount = safe_float(allocation.get("deployable_amount"), 0.0) or 0.0

    per_company = allocation.get("per_company_allocation") or {}
    if not deployable_amount and isinstance(per_company, dict):
        deployable_amount = sum((safe_float(v, 0.0) or 0.0) for v in per_company.values())

    if not parent_total:
        parent_total = reserve_amount + deployable_amount

    latest = latest_company_snapshots(portfolio_rows)
    companies_with_snapshot = sorted(c for c in COMPANIES if c in latest)
    missing_companies = sorted(c for c in COMPANIES if c not in latest)
    complete = len(companies_with_snapshot) == len(COMPANIES)

    company_states: dict[str, Any] = {}
    partial_deployable_equity = 0.0
    for company in COMPANIES:
        snap = latest.get(company)
        starting_allocation = safe_float(per_company.get(company), 0.0) if isinstance(per_company, dict) else 0.0
        if snap:
            equity = company_equity(snap)
            realized = safe_float(snap.get("realized_pnl"), 0.0) or 0.0
            unrealized = safe_float(snap.get("unrealized_pnl"), 0.0) or 0.0
            cash = safe_float(snap.get("cash"), 0.0) or 0.0
            pos_value = position_value(snap)
            partial_deployable_equity += equity
            current = equity
            pnl = equity - (starting_allocation or 0.0)
            snapshot_available = True
        else:
            current = None
            pnl = None
            realized = None
            unrealized = None
            cash = None
            pos_value = None
            snapshot_available = False

        company_states[company] = {
            "starting_allocation": round_money(starting_allocation),
            "snapshot_available": snapshot_available,
            "display_imputed": not snapshot_available,
            "display_equity": round_money(current if snapshot_available else starting_allocation),
            "current_equity": round_money(current),
            "pnl_vs_allocation": round_money(pnl),
            "cash": round_money(cash),
            "position_value": round_money(pos_value),
            "realized_pnl": round_money(realized),
            "unrealized_pnl": round_money(unrealized),
        }

    missing_allocation = 0.0
    if isinstance(per_company, dict):
        missing_allocation = sum((safe_float(per_company.get(c), 0.0) or 0.0) for c in missing_companies)

    # Truth fields: total/deployable current equity is only known when every
    # expected company has reported a portfolio snapshot. Do not treat a missing
    # company as a $0 balance or fake a loss.
    current_deployable_equity = partial_deployable_equity if complete else None
    current_total_equity = reserve_amount + current_deployable_equity if current_deployable_equity is not None else None

    # Display/imputation fields: safe for charts while a run is still warming up.
    # Missing companies are shown at their starting allocation until their first
    # snapshot appears. These values must not be used as verified accounting.
    imputed_deployable_equity = partial_deployable_equity + missing_allocation if portfolio_rows else None
    imputed_total_equity = reserve_amount + imputed_deployable_equity if imputed_deployable_equity is not None else None

    total_targets = build_targets(parent_total, current_total_equity)
    deployable_targets = build_targets(deployable_amount, current_deployable_equity)

    if not portfolio_rows:
        portfolio_status = "no_portfolio_snapshots"
    elif complete:
        portfolio_status = "complete"
    else:
        portfolio_status = "partial"

    # Backwards-compatible top-level fields used by Grant v1 and older tooling.
    target_state = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "source_files": {
            "allocation_state": str(artifacts / "allocation_state.json"),
            "portfolio_state": str(artifacts / "portfolio_state.jsonl"),
        },
        "portfolio_coverage": {
            "status": portfolio_status,
            "expected_companies": len(COMPANIES),
            "companies_with_snapshot": len(companies_with_snapshot),
            "complete": complete,
            "present": companies_with_snapshot,
            "missing": missing_companies,
            "missing_allocation": round_money(missing_allocation),
        },
        "allocation": {
            "parent_total": round_money(parent_total),
            "reserve_amount": round_money(reserve_amount),
            "deployable_amount": round_money(deployable_amount),
            "per_company_allocation": {
                str(k): round_money(safe_float(v, 0.0) or 0.0)
                for k, v in per_company.items()
            } if isinstance(per_company, dict) else {},
        },
        "total": total_targets,
        "deployable": deployable_targets,
        "companies": company_states,
        "display": {
            "imputed_for_chart_only": not complete,
            "imputed_deployable_equity": round_money(imputed_deployable_equity),
            "imputed_total_equity": round_money(imputed_total_equity),
            "imputed_deployable_pnl": round_money(imputed_deployable_equity - deployable_amount if imputed_deployable_equity is not None else None),
            "imputed_total_pnl": round_money(imputed_total_equity - parent_total if imputed_total_equity is not None else None),
            "warning": "Partial portfolio coverage; imputed values are for chart display only." if not complete else None,
        },
        "chart": {
            "baseline_equity": deployable_targets["starting_equity"],
            "ceiling_target_name": "goal",
            "ceiling_target_equity": deployable_targets["targets"]["goal"],
            "floor_target_equity": deployable_targets["targets"]["floor"],
            "goal_target_equity": deployable_targets["targets"]["goal"],
            "stretch_target_equity": deployable_targets["targets"]["stretch"],
            "grant_10x_target_equity": deployable_targets["targets"]["grant_10x"],
            "display_current_equity": round_money(imputed_deployable_equity),
        },
        # Legacy flat fields: total-equity view.
        "starting_equity": total_targets["starting_equity"],
        "current_equity_estimate": total_targets["current_equity"],
        "reserve_amount": round_money(reserve_amount),
        "deployable_starting_equity": deployable_targets["starting_equity"],
        "deployable_current_equity": deployable_targets["current_equity"],
        "total_pnl_estimate": total_targets["pnl"],
        "floor_target_equity": total_targets["targets"]["floor"],
        "goal_target_equity": total_targets["targets"]["goal"],
        "stretch_target_equity": total_targets["targets"]["stretch"],
        "grant_10x_target_equity": total_targets["targets"]["grant_10x"],
        "floor_profit_target": total_targets["profit_targets"]["floor"],
        "goal_profit_target": total_targets["profit_targets"]["goal"],
        "stretch_profit_target": total_targets["profit_targets"]["stretch"],
        "grant_10x_profit_target": total_targets["profit_targets"]["grant_10x"],
        "distance_to_floor": total_targets["distances"]["floor"],
        "distance_to_goal": total_targets["distances"]["goal"],
        "distance_to_stretch": total_targets["distances"]["stretch"],
        "distance_to_grant_10x": total_targets["distances"]["grant_10x"],
        "target_status": total_targets["status"],
    }

    if write:
        write_target_state(run_dir, target_state)

    return target_state


def write_target_state(run_dir: Path, target_state: dict[str, Any]) -> tuple[Path, Path]:
    out = run_dir / "artifacts" / "target_state.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(target_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    LATEST_TARGET.parent.mkdir(parents=True, exist_ok=True)
    LATEST_TARGET.write_text(json.dumps(target_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out, LATEST_TARGET


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ACC target_state.json for a live/paper run.")
    parser.add_argument("--run-id", default=None, help="Run id to process. Defaults to latest run.")
    parser.add_argument("--out", default=None, help="Optional output path. Default writes to run artifacts/target_state.json and state/targets/latest_target_state.json.")
    parser.add_argument("--print-summary", action="store_true", help="Print a compact target summary.")
    args = parser.parse_args()

    run_dir = run_dir_from_arg(args.run_id)
    target_state = build_target_state_from_run(run_dir, write=False)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(target_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        latest = LATEST_TARGET
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(json.dumps(target_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        out, latest = write_target_state(run_dir, target_state)

    print(f"Wrote: {out}")
    print(f"Wrote: {latest}")

    if args.print_summary:
        total = target_state["total"]
        deployable = target_state["deployable"]
        coverage = target_state["portfolio_coverage"]
        print()
        print("TARGET ENGINE SUMMARY")
        print("=====================")
        print(f"Run: {target_state['run_id']}")
        print(f"Portfolio coverage: {coverage['status']} ({coverage['companies_with_snapshot']}/{coverage['expected_companies']})")
        print(f"Total equity: start={total['starting_equity']} current={total['current_equity']} pnl={total['pnl']} status={total['status']}")
        print(f"Total targets: floor={total['targets']['floor']} goal={total['targets']['goal']} stretch={total['targets']['stretch']} grant_10x={total['targets']['grant_10x']}")
        print(f"Deployable equity: start={deployable['starting_equity']} current={deployable['current_equity']} pnl={deployable['pnl']} status={deployable['status']}")
        print(f"Deployable chart ceiling: {target_state['chart']['ceiling_target_name']}={target_state['chart']['ceiling_target_equity']}")


if __name__ == "__main__":
    main()
