#!/usr/bin/env python3
"""Summarize the lifecycle state distribution across companies."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"
STATES = ["NEW", "TESTING", "ACTIVE", "PROMOTED", "DECLINING", "PAUSED", "RETIRED", "ARCHIVED"]


def load_lifecycle_states() -> Counter[str]:
    counter = Counter()
    for company_dir in COMPANIES_DIR.iterdir():
        if not company_dir.is_dir():
            continue
        meta_path = company_dir / "metadata.yaml"
        state = "NEW"
        if meta_path.exists():
            try:
                import yaml

                data = yaml.safe_load(meta_path.open("r", encoding="utf-8")) or {}
                state = data.get("lifecycle_state", state)
            except ImportError:
                # fallback if yaml not installed
                pass
        counter[state] += 1
    return counter


def main() -> None:
    counter = load_lifecycle_states()
    total = sum(counter.values())
    print("Lifecycle summary")
    print("=" * 40)
    for state in STATES:
        print(f"{state:<10}: {counter.get(state, 0)}")
    print("=" * 40)
    print(f"Total companies: {total}")


if __name__ == "__main__":
    main()
