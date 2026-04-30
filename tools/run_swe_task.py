#!/usr/bin/env python3
"""Prepare a sandbox environment for an SWE task."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"
SANDBOX_DIR = ROOT / "sandbox"
LOG_PATH = ROOT / "tasks" / "task_runs.json"

REQUIRED_FIELDS = [
    "task_id",
    "title",
    "description",
    "allowed_files",
    "forbidden_files",
    "acceptance_criteria",
    "test_commands",
    "reviewer_notes",
]


def load_task(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise SystemExit(f"Task file {path} did not contain a mapping")
    missing = [key for key in REQUIRED_FIELDS if key not in data]
    if missing:
        raise SystemExit(f"Task file missing required fields: {', '.join(missing)}")
    return data


def ensure_sandbox(task_id: str) -> Path:
    SANDBOX_DIR.mkdir(exist_ok=True)
    sandbox = SANDBOX_DIR / task_id
    if not sandbox.exists():
        print(f"Creating sandbox directory {sandbox}")
        sandbox.mkdir(parents=True)
    else:
        print(f"Reusing existing sandbox {sandbox}")
    # Optionally create git worktree
    worktree = sandbox / "workspace"
    if not worktree.exists():
        print("Creating git worktree for sandbox")
        subprocess.run(["git", "worktree", "add", str(worktree)], cwd=ROOT)
    else:
        print("Git worktree already exists")
    return worktree


def record_run(task_id: str, metadata: Dict[str, Any]) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    runs = []
    if LOG_PATH.exists():
        runs = json.loads(LOG_PATH.read_text())
    entry = {
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
    }
    runs.append(entry)
    LOG_PATH.write_text(json.dumps(runs, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an SWE task sandbox")
    parser.add_argument("task_file", type=Path, help="Path to the task YAML file")
    args = parser.parse_args()
    task = load_task(args.task_file)
    print("Preparing SWE task:")
    print(f"  id: {task['task_id']}")
    print(f"  title: {task['title']}")
    print(f"  description: {task['description']}")
    print("Allowed file scope:")
    for allowed in task["allowed_files"]:
        print(f"  - {allowed}")
    print("Forbidden files:")
    for forbidden in task["forbidden_files"]:
        print(f"  - {forbidden}")
    sandbox = ensure_sandbox(task["task_id"])
    metadata = {
        "allowed_files": task["allowed_files"],
        "forbidden_files": task["forbidden_files"],
        "sandbox": str(sandbox),
        "tests": task["test_commands"],
    }
    record_run(task["task_id"], metadata)
    print("Sandbox ready for the SWE agent.")


if __name__ == "__main__":
    main()
