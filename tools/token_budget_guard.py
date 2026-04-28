#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def refresh_ledger_summary() -> None:
    subprocess.run(
        [sys.executable, "tools/ledger_usage_summary.py"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONNOUSERSITE": os.environ.get("PYTHONNOUSERSITE", "1")},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )


def stage_for(percent: float) -> tuple[str, str, list[str]]:
    if percent >= 98.0:
        return (
            "EMERGENCY",
            "No new risky entries. Deterministic protection mode only unless Jacob explicitly overrides.",
            [
                "block_new_risky_entries",
                "skip_low_stakes_committees",
                "deterministic_buy_sell_hold_only",
                "premium_models_only_for_safety_or_recovery",
            ],
        )

    if percent >= 90.0:
        return (
            "RESTRICTED",
            "Only high-confidence critical calls. Prefer deterministic execution and preserve remaining AI budget.",
            [
                "block_low_value_agent_calls",
                "skip_company_committee_unless_high_confidence",
                "prefer_deterministic_execution",
                "reserve_premium_models_for_governance",
            ],
        )

    if percent >= 80.0:
        return (
            "DEGRADED",
            "Reduce committee chatter and low-stakes analysis. Cheaper/deterministic paths preferred.",
            [
                "reduce_committee_chatter",
                "avoid_duplicate_analysis",
                "prefer_cached_reports",
                "use_deterministic_prechecks",
            ],
        )

    if percent >= 70.0:
        return (
            "CAUTION",
            "Budget warning. Keep calls useful, short, and evidence-backed.",
            [
                "watch_burn_rate",
                "discourage_fluff",
                "avoid_unnecessary_premium_calls",
            ],
        )

    return (
        "NORMAL",
        "Budget use is below caution threshold.",
        [
            "normal_cost_discipline",
            "continue_telemetry",
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="ACC token budget guard using Ledger usage summary.")
    parser.add_argument("--budget-usd", type=float, default=num(os.getenv("ACC_TOKEN_BUDGET_USD"), 1.0))
    parser.add_argument("--no-refresh", action="store_true", help="Do not refresh ledger_usage_summary first.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero for RESTRICTED or EMERGENCY.")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)

    if not args.no_refresh:
        try:
            refresh_ledger_summary()
        except Exception:
            pass

    ledger = load_json(REPORTS / "ledger_usage_summary.json")
    totals = ledger.get("totals") if isinstance(ledger.get("totals"), dict) else {}

    estimated_cost = num(totals.get("estimated_cost"), 0.0)
    total_tokens = num(totals.get("total_tokens"), 0.0)
    calls = num(totals.get("calls"), 0.0)
    budget = max(args.budget_usd, 0.000001)
    percent = (estimated_cost / budget) * 100.0

    stage, recommendation, actions = stage_for(percent)

    summary = {
        "generated_at": utc_now(),
        "budget_usd": budget,
        "estimated_cost": estimated_cost,
        "budget_used_percent": percent,
        "total_tokens": total_tokens,
        "calls": calls,
        "stage": stage,
        "recommendation": recommendation,
        "degradation_actions": actions,
        "thresholds": {
            "caution": 70,
            "degraded": 80,
            "restricted": 90,
            "emergency": 98,
        },
        "source": "reports/ledger_usage_summary.json",
    }

    json_path = REPORTS / "token_budget_guard.json"
    txt_path = REPORTS / "token_budget_guard.txt"

    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "ACC Token Budget Guard",
        "======================",
        f"Generated: {summary['generated_at']}",
        f"Stage: {stage}",
        f"Budget USD: {budget:.6f}",
        f"Estimated cost: {estimated_cost:.6f}",
        f"Budget used: {percent:.2f}%",
        f"Calls: {int(calls)}",
        f"Total tokens: {int(total_tokens)}",
        "",
        f"Recommendation: {recommendation}",
        "",
        "Degradation actions:",
    ]

    for action in actions:
        lines.append(f"- {action}")

    lines.extend([
        "",
        "Thresholds:",
        "- 70%: CAUTION",
        "- 80%: DEGRADED",
        "- 90%: RESTRICTED",
        "- 98%: EMERGENCY",
        "",
        f"Wrote: {json_path}",
        f"Wrote: {txt_path}",
    ])

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    if args.strict and stage in {"RESTRICTED", "EMERGENCY"}:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
