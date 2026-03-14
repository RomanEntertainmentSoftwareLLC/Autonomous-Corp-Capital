#!/usr/bin/env python3
"""Create a genome-based child company from a parent."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.python_helper import ensure_repo_root, python_executable

import yaml

ROOT = Path(__file__).resolve().parent.parent
ensure_repo_root()
COMPANIES_DIR = ROOT / "companies"
METADATA_FILE = "metadata.yaml"
GENOME_FILE = "genome.yaml"


def load_metadata(company: str) -> Dict[str, any]:
    path = COMPANIES_DIR / company / METADATA_FILE
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_metadata(company: str, data: Dict[str, any]) -> None:
    path = COMPANIES_DIR / company / METADATA_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evolve a company genome into a child")
    parser.add_argument("parent", help="Parent company id")
    parser.add_argument("child", help="Child company id to create")
    parser.add_argument("--strategy", help="Force a strategy name (uses registry names)")
    parser.add_argument("--strategy-switch", action="store_true", help="Cycle to the next strategy")
    parser.add_argument("--seed", type=int, help="Optional mutation seed")
    args = parser.parse_args()

    parent_dir = COMPANIES_DIR / args.parent
    child_dir = COMPANIES_DIR / args.child
    if not parent_dir.exists():
        raise SystemExit(f"Parent company {args.parent} not found")
    if child_dir.exists():
        raise SystemExit(f"Child {args.child} already exists")

    shutil.copytree(parent_dir, child_dir)
    print(f"Cloned parent {args.parent} -> child {args.child}")

    mutate_cmd = [python_executable(), "tools/mutate_company.py", args.child]
    if args.strategy:
        mutate_cmd.extend(["--strategy", args.strategy])
    if args.strategy_switch:
        mutate_cmd.append("--strategy-switch")
    if args.seed is not None:
        mutate_cmd.extend(["--seed", str(args.seed)])
    subprocess.run(mutate_cmd, check=True)

    subprocess.run([python_executable(), "tools/validate_genome.py", args.child], check=True)
    subprocess.run([python_executable(), "tools/compile_genome.py", args.child], check=True)

    parent_meta = load_metadata(args.parent)
    child_meta = parent_meta.copy()
    child_meta["company_id"] = args.child
    child_meta["parent_company"] = args.parent
    child_meta["generation"] = int(parent_meta.get("generation", 0)) + 1
    child_meta["mutation_source"] = f"genome evo from {args.parent}"
    child_meta["lifecycle_state"] = "NEW"
    child_meta["last_fitness"] = None
    child_meta.setdefault("notes", "")
    child_meta["notes"] += f"\nEvolved from {args.parent} at {datetime.utcnow().isoformat()}"
    save_metadata(args.child, child_meta)

    print(f"Evolved genome saved for {args.child}. Run the appropriate tests before backing this up.")


if __name__ == "__main__":
    main()
