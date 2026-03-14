#!/usr/bin/env python3
"""Scan the repo for obvious issues to generate SWE tasks."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Iterator, List

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MARKERS = ["TODO", "FIXME"]


def find_argparse_without_help(path: Path) -> Iterator[Path]:
    text = path.read_text(errors='ignore')
    return (m.start() for m in re.finditer(r"ArgumentParser\([^)]*\)", text))


def scan_files() -> List[str]:
    issues = []
    for path in ROOT.rglob("*.py"):
        if path.match("tools/run_swe_task.py"):
            continue
        text = path.read_text(errors='ignore')
        for marker in DEFAULT_MARKERS:
            if marker in text:
                issues.append(f"{path}: contains marker {marker}")
        if "argparse" in text and "help=" not in text:
            issues.append(f"{path}: argparse helper missing descriptive help text")
        if "DEFAULT_CONFIG_PATH" in text and not str(path.parent).startswith(str(ROOT)):
            issues.append(f"{path}: references DEFAULT_CONFIG_PATH but not in repo? check {text}")
    return issues


def scan_configs() -> List[str]:
    issues = []
    for path in ROOT.rglob("*.yaml"):
        if "config" in path.name:
            text = path.read_text(errors='ignore')
            for line in text.splitlines():
                if ':' in line and line.strip().endswith(':'):
                    continue
            # look for referenced file path
            for match in re.findall(r"\b([\w\-/]+\.json)\b", text):
                if not (ROOT / match).exists():
                    issues.append(f"{path}: references missing file {match}")
    return issues


def scan_results() -> List[str]:
    issues = []
    results_dir = ROOT / "results"
    if not results_dir.exists():
        issues.append("results/ directory missing")
        return issues
    for company_dir in results_dir.iterdir():
        if not company_dir.is_dir():
            continue
        for mode_dir in company_dir.iterdir():
            if not mode_dir.is_dir():
                continue
            for expected in ["trade-log.jsonl", "signal-log.jsonl", "feature-log.jsonl"]:
                if not (mode_dir / expected).exists():
                    issues.append(f"Missing {expected} in {mode_dir}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan repo for candidate SWE tasks")
    args = parser.parse_args()

    print("Repo scan report")
    print("Scanning python files...")
    issues = scan_files()
    issues += scan_configs()
    issues += scan_results()

    if not issues:
        print("No issues detected (nice job!)")
        return

    for issue in issues:
        print(f"- {issue}")

    print(f"Detected {len(issues)} potential tasks.")


if __name__ == "__main__":
    main()
