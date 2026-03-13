#!/usr/bin/env python3
"""Summarize the git patch produced by an SWE task."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
TASK_LOG = ROOT / "tasks" / "task_runs.json"


def git_diff_summary() -> Dict[str, Any]:
    stat = subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip().splitlines()
    diffstat = subprocess.check_output(["git", "diff", "--stat"], cwd=ROOT, text=True)
    diff = subprocess.check_output(["git", "diff"], cwd=ROOT, text=True)
    return {
        "files_changed": [line for line in stat if line],
        "diffstat": diffstat.strip(),
        "diff_summary": diff[:2048],
    }


def load_last_task() -> Dict[str, Any]:
    if not TASK_LOG.exists():
        return {}
    runs = json.loads(TASK_LOG.read_text())
    return runs[-1] if runs else {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize patch for current SWE task")
    parser.add_argument("--task-id", help="Optional task id to highlight")
    args = parser.parse_args()
    summary = git_diff_summary()
    print("Patch summary:")
    print("Files changed:")
    for entry in summary["files_changed"]:
        print(f"  {entry}")
    print("\nDiffstat:")
    print(summary["diffstat"])
    print("\nShort diff output (truncated):")
    print(summary["diff_summary"])

    task = load_last_task()
    if task:
        print("\nRelated task metadata:")
        print(f"  task_id: {task.get('task_id')}")
        print(f"  sandbox: {task['metadata'].get('sandbox')}")
        if args.task_id and task.get('task_id') != args.task_id:
            print(f"  (warning: last executed task {task.get('task_id')} differs from requested {args.task_id})")
    else:
        print("\nNo task log found. Run tools/run_swe_task.py first.")


if __name__ == "__main__":
    main()
