#!/usr/bin/env python3
"""Clone an existing company config into a new lineage branch."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

COMPANIES_DIR = Path(__file__).resolve().parent.parent / "companies"


def read_metadata(company: str) -> dict:
    meta_path = COMPANIES_DIR / company / "metadata.yaml"
    if not meta_path.exists():
        return {}
    with open(meta_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_metadata(company: str, data: dict) -> None:
    meta_path = COMPANIES_DIR / company / "metadata.yaml"
    with open(meta_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh)


def copy_config(parent: str, child: str) -> None:
    src = COMPANIES_DIR / parent / "config.yaml"
    dst_dir = COMPANIES_DIR / child
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "config.yaml"
    shutil.copy2(src, dst)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clone a company config/metadata to a new child")
    parser.add_argument("parent", help="Parent company id to clone from")
    parser.add_argument("child", help="Child company id to create")
    parser.add_argument("--force", action="store_true", help="Overwrite existing child if present")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parent_dir = COMPANIES_DIR / args.parent
    child_dir = COMPANIES_DIR / args.child

    if not parent_dir.exists():
        print(f"Parent company '{args.parent}' does not exist", file=sys.stderr)
        sys.exit(1)

    if child_dir.exists():
        if not args.force:
            print(f"Child company '{args.child}' already exists (use --force to replace)", file=sys.stderr)
            sys.exit(1)
        shutil.rmtree(child_dir)

    copy_config(args.parent, args.child)

    parent_meta = read_metadata(args.parent)
    generation = int(parent_meta.get("generation", 0)) + 1
    created_at = datetime.now(timezone.utc).isoformat()
    metadata = {
        "company_id": args.child,
        "parent_company": args.parent,
        "generation": generation,
        "mutation_source": f"clone_of_{args.parent}",
        "created_at": created_at,
        "notes": f"Cloned from {args.parent} on {created_at}",
    }
    write_metadata(args.child, metadata)

    print(f"Cloned '{args.parent}' → '{args.child}'")
    print(f"Child config ready at companies/{args.child}/config.yaml")
    print(f"Run it via: .venv/bin/python3 trade-bot.py --company {args.child} --mode backtest --iterations 4 --loop-feed")


if __name__ == "__main__":
    main()
