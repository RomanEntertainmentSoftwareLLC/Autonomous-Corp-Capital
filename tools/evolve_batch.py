#!/usr/bin/env python3
"""Batch evolution helper that clones + mutates multiple child companies."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

SCRIPT_DIR = Path(__file__).resolve().parent
CLONE_SCRIPT = SCRIPT_DIR / "clone_company.py"
MUTATE_SCRIPT = SCRIPT_DIR / "mutate_company.py"


def run_command(command: List[str]) -> None:
    print(f"Running: {' '.join(command)}")
    subprocess.run(command, check=True)


def build_child_id(prefix: str, index: int) -> str:
    return f"{prefix}{index:03d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone a parent company into several mutated children")
    parser.add_argument("parent", help="Parent company id to base evolutions on")
    parser.add_argument("--count", type=int, default=3, help="Number of children to create")
    parser.add_argument("--prefix", default="company_", help="Prefix for generated child ids")
    parser.add_argument("--seed", type=int, default=0, help="Base seed for deterministic mutations (incremented per child)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing child ids")
    args = parser.parse_args()

    children = [build_child_id(args.prefix, i + 1) for i in range(args.count)]

    for idx, child in enumerate(children):
        print(f"=== evolving child {child} (seed {args.seed + idx}) ===")
        clone_cmd = [sys.executable, str(CLONE_SCRIPT), args.parent, child]
        if args.force:
            clone_cmd.append("--force")
        run_command(clone_cmd)

        mutate_cmd = [sys.executable, str(MUTATE_SCRIPT), child, "--seed", str(args.seed + idx)]
        run_command(mutate_cmd)

    print("Batch evolution complete")
    print(f"Children created: {', '.join(children)}")
    print("You can run them via trade-bot.py or list them in a manifest.")


if __name__ == "__main__":
    main()
