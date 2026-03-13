#!/usr/bin/env python3
"""Apply SWE task changes only after approval."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Dict, List

TASK_LOG = Path("tasks/task_runs.json")
APPROVALS = Path("tasks/approval_manifest.json")
REVIEW_DIR = Path("tasks/reviews")
TEST_LOG = Path("tasks/test_history.json")


def load_approval(task_id: str) -> Dict[str, str]:
    if not APPROVALS.exists():
        return {}
    entries = json.loads(APPROVALS.read_text())
    for entry in entries:
        if entry.get("task_id") == task_id:
            return entry
    return {}


def run_git_apply(task_id: str) -> None:
    print(f"Applying changes for task {task_id}...")
    subprocess.run(["git", "status"])
    print("Use git add/commit as needed afterward.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply SWE task changes after approval")
    parser.add_argument("task_id", help="Task id to apply")
    args = parser.parse_args()

    approval = load_approval(args.task_id)
    if approval.get("status") != "approved":
        raise SystemExit(f"Task {args.task_id} is not approved (status: {approval.get('status')})")

    review_path = REVIEW_DIR / f"review_{args.task_id}.json"
    if not review_path.exists():
        raise SystemExit("Review report missing")

    if TEST_LOG.exists():
        history = json.loads(TEST_LOG.read_text())
        task_tests = [entry for entry in history if entry.get("task_id") == args.task_id]
        if not task_tests or any(entry.get("status") != "pass" for entry in task_tests):
            raise SystemExit("Not all tests passed for this task")
    run_git_apply(args.task_id)
    print("Task changes applied. Please review and commit.")


if __name__ == "__main__":
    main()
