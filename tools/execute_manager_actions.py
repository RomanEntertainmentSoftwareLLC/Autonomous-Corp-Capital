#!/usr/bin/env python3
"""Execute safe manager actions from a manifest."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.company_metadata import read_metadata, write_metadata

CLONE_SCRIPT = ROOT / "tools" / "clone_company.py"
MUTATE_SCRIPT = ROOT / "tools" / "mutate_company.py"
DEFAULT_MANIFEST = ROOT / "manager_actions.yaml"


def load_manifest(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        raise SystemExit(f"Manifest not found at {path}")
    data = yaml.safe_load(path.read_text())
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        raise SystemExit("Manifest missing 'actions' list")
    return actions


def run_command(cmd: List[str], dry_run: bool) -> None:
    print(f"Running: {' '.join(cmd)}")
    if dry_run:
        print("(dry run; not executing)")
        return
    subprocess.run(cmd, check=True)


def ensure_child_name(action: Dict[str, object]) -> str:
    child = action.get("target_child")
    if not child:
        raise SystemExit(f"Clone action for {action['company']} missing target_child")
    return str(child)


def mutate_company(company: str, seed: int | None, dry_run: bool) -> None:
    cmd = [sys.executable, str(MUTATE_SCRIPT), company]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    run_command(cmd, dry_run)


def clone_company(parent: str, child: str, force: bool, mutate_child: bool, seed: int | None, dry_run: bool) -> None:
    cmd = [sys.executable, str(CLONE_SCRIPT), parent, child]
    if force:
        cmd.append("--force")
    run_command(cmd, dry_run)
    if mutate_child:
        mutate_company(child, seed, dry_run)


def set_status(company: str, status: str, dry_run: bool) -> None:
    metadata = read_metadata(company)
    metadata["status"] = status
    if dry_run:
        print(f"(dry run) would set {company} status -> {status}")
        return
    write_metadata(company, metadata)
    print(f"Set {company} status -> {status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute manager-approved actions")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run", action="store_true", help="Report actions without executing")
    parser.add_argument("--force-clone", action="store_true", help="Allow overwriting clones")
    parser.add_argument("--mutate-after-clone", action="store_true", help="Mutate clones after creation")
    parser.add_argument("--seed", type=int, help="Seed used when mutating for deterministic runs")
    args = parser.parse_args()

    actions = load_manifest(args.manifest)
    if not actions:
        print("No actions to run")
        return

    for action in actions:
        company = action.get("company")
        rec = action.get("recommendation")
        print(f"Processing {company} — recommendation {rec}")
        if rec == "CLONE":
            child = ensure_child_name(action)
            clone_company(company, child, args.force_clone, args.mutate_after_clone or action.get("mutate", False), args.seed, args.dry_run)
        elif rec == "TEST_MORE":
            mutate_company(company, args.seed, args.dry_run)
        elif rec == "RETIRE":
            set_status(company, "retired", args.dry_run)
        else:
            print(f"No automated action for recommendation {rec}")

    print("Manager actions execution complete.")


if __name__ == "__main__":
    main()
