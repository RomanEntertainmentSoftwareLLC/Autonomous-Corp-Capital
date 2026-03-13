#!/usr/bin/env python3
"""Clone a company and mutate the clone in one workflow."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPT_DIR = Path(__file__).resolve().parent
COMPANIES_DIR = SCRIPT_DIR.parent / "companies"
CLONE_SCRIPT = SCRIPT_DIR / "clone_company.py"
MUTATE_SCRIPT = SCRIPT_DIR / "mutate_company.py"
from tools.company_metadata import read_metadata
#from tools.company_metadata import read_metadata


def run_command(command: List[str]) -> None:
    print(f"Running: {' '.join(command)}")
    result = subprocess.run(command, check=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone and mutate a company in one go")
    parser.add_argument("parent", help="Existing parent company to clone")
    parser.add_argument("child", help="Child company id to create")
    parser.add_argument("--seed", type=int, help="Optional seed for deterministic mutation")
    parser.add_argument("--force", action="store_true", help="Overwrite child if it already exists")
    args = parser.parse_args()

    child_dir = COMPANIES_DIR / args.child
    if child_dir.exists() and not args.force:
        print(f"Child company '{args.child}' already exists (use --force to replace)")
        sys.exit(1)

    clone_cmd = [sys.executable, str(CLONE_SCRIPT), args.parent, args.child]
    if args.force:
        clone_cmd.append("--force")
    run_command(clone_cmd)

    mutate_cmd = [sys.executable, str(MUTATE_SCRIPT), args.child]
    if args.seed is not None:
        mutate_cmd.extend(["--seed", str(args.seed)])
    run_command(mutate_cmd)

    metadata = read_metadata(args.child)
    parent = metadata.get("parent_company", args.parent)
    generation = metadata.get("generation", "<unknown>")

    print("Evolution complete")
    print(f"Child config ready at companies/{args.child}/config.yaml")
    print(f"Summary: parent={parent}, child={args.child}, generation={generation}")
    print(f"Run: .venv/bin/python3 trade-bot.py --company {args.child} --mode backtest --iterations 4 --loop-feed")


if __name__ == "__main__":
    main()
