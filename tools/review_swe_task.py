#!/usr/bin/env python3
"""Generate a reviewer report for an SWE task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

TASK_LOG = Path("tasks/task_runs.json")
PATCH_SUMMARY = Path("tasks/patch_summary.json")
TEST_LOG = Path("tasks/test_history.json")
REPORT_DIR = Path("tasks/reviews")


def load_task(task_id: str) -> Dict[str, any]:
    if not TASK_LOG.exists():
        raise SystemExit("No task log found")
    runs = json.loads(TASK_LOG.read_text())
    for run in reversed(runs):
        if run.get("task_id") == task_id:
            return run
    raise SystemExit(f"Task {task_id} not found in log")


def load_patch_summary() -> Dict[str, any]:
    if not PATCH_SUMMARY.exists():
        return {}
    return json.loads(PATCH_SUMMARY.read_text())


def load_test_history(task_id: str) -> List[str]:
    if not TEST_LOG.exists():
        return []
    history = json.loads(TEST_LOG.read_text())
    return [entry for entry in history if entry.get("task_id") == task_id]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a reviewer report for an SWE task")
    parser.add_argument("task_id", help="Task id to generate report for")
    args = parser.parse_args()

    task = load_task(args.task_id)
    patch = load_patch_summary()
    tests = load_test_history(args.task_id)

    report = {
        "task_id": args.task_id,
        "reviewer_status": "pending",
        "issues_found": [],
        "notes": [],
        "task_metadata": task,
        "patch_summary": patch,
        "test_history": tests,
    }

    REPORT_DIR.mkdir(exist_ok=True)
    out_path = REPORT_DIR / f"review_{args.task_id}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Review report generated: {out_path}")


if __name__ == "__main__":
    main()
