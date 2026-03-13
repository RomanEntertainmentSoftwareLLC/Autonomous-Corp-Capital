#!/usr/bin/env python3
"""Flatten feature logs into a CSV dataset for ML."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"

COLUMNS = [
    "company",
    "mode",
    "symbol",
    "strategy",
    "ema_fast",
    "ema_slow",
    "ema_spread",
    "rsi",
    "price_change_1",
    "price_change_2",
    "price_change_3",
    "momentum_3",
    "slope_3",
    "pattern_three_rising",
    "pattern_three_falling",
    "pattern_reversal_after_two_decline",
    "pattern_reversal_after_two_rise",
    "pattern_short_momentum_burst",
    "pattern_short_exhaustion",
    "higher_highs",
    "higher_lows",
    "lower_highs",
    "lower_lows",
]


def iter_feature_logs(target_label: str, company: Optional[str] = None, mode: Optional[str] = None) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    target_paths: List[Path] = []

    if company and mode:
        feature_path = RESULTS_DIR / company / mode / "feature-log.jsonl"
        if not feature_path.exists():
            raise SystemExit(f"Feature log missing: {feature_path}")
        target_paths = [feature_path]
    else:
        for company_dir in sorted(RESULTS_DIR.iterdir()):
            if not company_dir.is_dir():
                continue
            for mode_dir in sorted(company_dir.iterdir()):
                feature_path = mode_dir / "feature-log.jsonl"
                if feature_path.exists():
                    target_paths.append(feature_path)

    for feature_path in target_paths:
        company_name = feature_path.parents[1].name
        mode_name = feature_path.parents[0].name
        with feature_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                payload = json.loads(line)
                label = payload.get(target_label)
                if label is None:
                    continue
                row = {
                    "company": company_name,
                    "mode": mode_name,
                    "symbol": payload.get("symbol"),
                    "strategy": payload.get("strategy"),
                    target_label: label,
                }
                for col in COLUMNS:
                    if col in payload:
                        row[col] = payload[col]
                rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate feature logs into a csv-ready dataset for ML training (default scans every company/mode unless filters are supplied).",
        epilog="Example: python3 tools/build_ml_dataset.py --company company_001 --mode paper --target future_direction_5_ticks --output ml_datasets/company_001_paper.csv",
    )
    parser.add_argument(
        "--company",
        help="Optional company id to restrict the dataset to (default scans every company).",
    )
    parser.add_argument(
        "--mode",
        help="Optional mode (backtest/paper) to restrict the dataset; requires --company.",
    )
    parser.add_argument(
        "--target",
        default="future_direction_5_ticks",
        help="Target label column name for this dataset (alias --label).",
    )
    parser.add_argument(
        "--label",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output",
        default="ml_dataset.csv",
        help="Destination path for the CSV dataset output.",
    )
    args = parser.parse_args()
    label = args.target if args.target else args.label
    if not label:
        parser.error("--target (or --label) is required")
    rows = iter_feature_logs(label, company=args.company, mode=args.mode)
    if not rows:
        print("No rows collected")
        return
    columns = COLUMNS + [label]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})
    print(f"Wrote {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
