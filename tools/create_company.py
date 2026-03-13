#!/usr/bin/env python3
"""Helper to bootstrap a new company config under companies/."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml


BASE_CONFIG = Path(__file__).resolve().parent.parent / "tradebot" / "config.yaml"
COMPANIES_DIR = Path(__file__).resolve().parent.parent / "companies"


def load_base_config() -> dict:
    if not BASE_CONFIG.exists():
        raise FileNotFoundError(f"Base config not found at {BASE_CONFIG}")
    with open(BASE_CONFIG, "r", encoding="utf-8") as fh:
        template = yaml.safe_load(fh) or {}
    if not isinstance(template, dict):
        raise ValueError("Base config must be a mapping type")
    return template


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a company config folder")
    parser.add_argument("company_id", help="ID for the new company (e.g., company_003)")
    parser.add_argument(
        "--symbol",
        help="Optional symbol override to seed the company config",
        default=None,
    )
    args = parser.parse_args()

    company_id = args.company_id.strip()
    if not company_id:
        print("Company ID is required", file=sys.stderr)
        sys.exit(1)

    destination = COMPANIES_DIR / company_id
    if destination.exists():
        print(f"{destination} already exists", file=sys.stderr)
        sys.exit(1)

    template = load_base_config()
    template["company_id"] = company_id

    if args.symbol:
        template["symbols"] = [
            {
                **template.get("symbols", [{}])[0],
                "name": args.symbol,
            }
        ]

    destination.mkdir(parents=True, exist_ok=False)
    config_path = destination / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(template, fh, sort_keys=False)

    print(f"Created company config at {config_path}")


if __name__ == "__main__":
    main()
