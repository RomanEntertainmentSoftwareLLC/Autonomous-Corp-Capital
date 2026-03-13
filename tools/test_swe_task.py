#!/usr/bin/env python3
"""Run test commands specified in an SWE task manifest."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

import yaml

REQUIRED_FIELDS = ["task_id", "test_commands"]


def load_task(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not data:
        raise SystemExit(f"Empty task file {path}")
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise SystemExit(f"Task file missing fields: {', '.join(missing)}")
    return data


def run_command(cmd: str) -> bool:
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True)
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SWE task tests")
    parser.add_argument("task_file", type=Path, help="Path to the task YAML file")
    args = parser.parse_args()

    task = load_task(args.task_file)
    commands: List[str] = task["test_commands"]
    if not isinstance(commands, list) or not commands:
        raise SystemExit("test_commands must be a non-empty list of shell strings")

    print(f"Executing tests for {task['task_id']}")
    failures: List[str] = []
    for command in commands:
        success = run_command(command)
        if not success:
            failures.append(command)
    print("\nTest summary:")
    print(f"  total: {len(commands)}")
    print(f"  passed: {len(commands) - len(failures)}")
    print(f"  failed: {len(failures)}")
    if failures:
        print("  failed commands:")
        for cmd in failures:
            print(f"    - {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
