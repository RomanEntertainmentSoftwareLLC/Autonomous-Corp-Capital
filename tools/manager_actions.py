#!/usr/bin/env python3
"""Export manager-approved actions into a reviewable manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

import tools.manager_decide as md
from tools.company_metadata import read_metadata

MANIFEST_PATH = ROOT / "manager_actions.yaml"


def collect_actions(metric: str) -> List[Dict[str, Any]]:
    companies = sorted(p.name for p in (ROOT / "companies").iterdir() if p.is_dir())
    actions = []
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
        status = md.gate_status(rec)
        action = {
            "company": company,
            "parent": parent,
            "generation": generation,
            "mode": best["mode"],
            "account_value": best["account_value"],
            "realized_pnl": best["realized_pnl"],
            "recommendation": rec,
            "reason": reason,
            "tester_status": status["tester_status"],
            "reviewer_status": status["reviewer_status"],
            "strategies": strat,
        }
        if rec == "CLONE":
            child_id = f"{company}_gen{int(generation) + 1 if isinstance(generation, int) or str(generation).isdigit() else generation}_clone"
            if generation == "<unknown>":
                child_id = f"{company}_clone"
            action["target_child"] = child_id
            action["details"] = f"Clone {company} into {child_id}."
        elif rec == "TEST_MORE":
            action["mutate"] = True
            action["details"] = f"Test {company} more thoroughly."
        elif rec == "RETIRE":
            action["details"] = f"Retire {company} after review."
        else:
            action["details"] = f"Continue monitoring {company}."
        actions.append(action)
    return actions


def emit_manifest(actions: List[Dict[str, Any]], path: Path) -> None:
    manifest = {"generated_at": Path().resolve().as_posix(), "actions": actions}
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    print(f"Wrote manager action manifest to {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate manager action manifest")
    parser.add_argument("--metric", choices=["account_value", "realized_pnl"], default="account_value")
    parser.add_argument("--output", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()

    actions = collect_actions(args.metric)
    emit_manifest(actions, args.output)


if __name__ == "__main__":
    main()
