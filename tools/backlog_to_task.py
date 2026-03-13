#!/usr/bin/env python3
"""Convert backlog items into structured SWE tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

TASKS_DIR = Path("tasks")
TEMPLATE_FIELDS = [
    "task_id",
    "title",
    "description",
    "allowed_files",
    "forbidden_files",
    "acceptance_criteria",
    "test_commands",
    "reviewer_notes",
]


def load_backlog(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_task(backlog_item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": backlog_item.get("id", ""),
        "title": backlog_item.get("title", "SWE Task"),
        "description": backlog_item.get("description", ""),
        "allowed_files": backlog_item.get("files", []),
        "forbidden_files": backlog_item.get("forbidden", []),
        "acceptance_criteria": backlog_item.get("acceptance", ["Deliverable meets requirements"]),
        "test_commands": backlog_item.get("tests", []),
        "reviewer_notes": backlog_item.get("notes", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an SWE task from a backlog entry")
    parser.add_argument("backlog", type=Path, help="Path to backlog JSON file")
    parser.add_argument("task_id", help="Backlog item ID to convert")
    args = parser.parse_args()

    backlog = load_backlog(args.backlog)
    item = next((entry for entry in backlog if entry.get("id") == args.task_id), None)
    if not item:
        raise SystemExit("Backlog item not found")

    task = build_task(item)
    TASKS_DIR.mkdir(exist_ok=True)
    out_path = TASKS_DIR / f"{task['task_id']}.yaml"
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(task, fh, sort_keys=False)
    print(f"Created task manifesto: {out_path}")


if __name__ == "__main__":
    main()
