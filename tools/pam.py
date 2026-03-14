#!/usr/bin/env python3
"""Per-company Pam front desk coordinator."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "agents.yaml"
STATE_ROOT = ROOT / "state" / "agents"

DEFAULT_QUEUE = {
    "new": [],
    "assigned": [],
    "in_progress": [],
    "blocked": [],
    "completed": [],
    "escalated": [],
}

PRIORITY_KEYWORDS = {
    "emergency": "emergency",
    "urgent": "high",
    "risk": "high",
    "escalate": "high",
    "block": "high",
    "now": "high",
    "low": "low",
    "monitor": "medium",
}

TASK_TYPES = [
    ("risk", "risk_review", "Risk Officer"),
    ("treasury", "treasury_review", "Master Treasurer"),
    ("lifecycle", "lifecycle_action", "YamYam"),
    ("software", "software_task", "Product Manager"),
    ("bug", "bug_fix", "SWE"),
    ("meeting", "meeting_prep", "Scrum Master"),
    ("report", "status_report", "Analyst"),
    ("analysis", "analysis", "Analyst"),
]


class PamError(Exception):
    pass


def load_agents() -> dict[str, dict[str, str]]:
    if not CONFIG_PATH.exists():
        raise PamError(f"Agents config not found at {CONFIG_PATH}")
    data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    agents = {}
    for entry in data.get("agents", []):
        agent_id = entry.get("id")
        if agent_id:
            agents[agent_id] = entry
    return agents


def ensure_state(agent_id: str) -> Path:
    path = STATE_ROOT / agent_id
    path.mkdir(parents=True, exist_ok=True)
    for fname, default in [
        ("inbox.jsonl", None),
        ("outbox.jsonl", None),
        ("queue.json", DEFAULT_QUEUE),
        ("escalations.jsonl", None),
        ("meetings.jsonl", None),
    ]:
        fpath = path / fname
        if default is None:
            if not fpath.exists():
                fpath.write_text("")
        else:
            if not fpath.exists():
                fpath.write_text(json.dumps(default, indent=2))
    return path


def read_queue(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return DEFAULT_QUEUE.copy()


def write_queue(path: Path, queue: dict) -> None:
    path.write_text(json.dumps(queue, indent=2))


def classify_priority(message: str) -> str:
    lowered = message.lower()
    for keyword, priority in PRIORITY_KEYWORDS.items():
        if keyword in lowered:
            return priority
    return "medium"


def classify_task(message: str) -> tuple[str, str]:
    lowered = message.lower()
    for keyword, task_type, recipient in TASK_TYPES:
        if keyword in lowered:
            return task_type, recipient
    return "general_triage", "Analyst"


def append_log(path: Path, entry: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pam front desk coordinator")
    parser.add_argument("--agent", default="pam", help="Agent ID from config/agents.yaml")
    parser.add_argument("--sender", default="user", help="Identity of the requester")
    parser.add_argument("--show-queue", action="store_true")
    parser.add_argument("message", nargs="+", help="Message or request for Pam")
    args = parser.parse_args()

    message = " ".join(args.message).strip()
    if not message:
        parser.error("Message cannot be empty")

    agents = load_agents()
    if args.agent not in agents:
        raise PamError(f"Unknown agent '{args.agent}' (check config/agents.yaml)")
    agent_info = agents[args.agent]
    state_path = ensure_state(args.agent)
    queue_path = state_path / "queue.json"
    queue = read_queue(queue_path)

    if args.show_queue:
        print(json.dumps(queue, indent=2))
        return

    now = datetime.utcnow().isoformat() + "+00:00"
    priority = classify_priority(message)
    task_type, recipient = classify_task(message)
    task_id = str(uuid.uuid4())
    scope = agent_info.get("scope", "global")
    status = "new"

    packet = {
        "task_id": task_id,
        "from": args.sender,
        "to": recipient,
        "company_scope": scope,
        "task_type": task_type,
        "priority": priority,
        "summary": message if len(message) < 100 else message[:97] + "...",
        "context": [
            f"Captured at {now}",
            f"Agent: {agent_info.get('name', args.agent)}",
        ],
        "requested_action": f"{recipient}: handle {task_type} for {scope}",
        "status": status,
        "escalate_to": "" if priority != "emergency" else "YamYam",
    }

    queue_entry = {
        "task_id": task_id,
        "summary": packet["summary"],
        "priority": priority,
        "assigned_to": recipient,
        "status": status,
        "timestamp": now,
    }
    queue.setdefault("new", []).append(queue_entry)
    write_queue(queue_path, queue)

    inbox_entry = {
        "timestamp": now,
        "sender": args.sender,
        "message": message,
        "task_id": task_id,
    }
    append_log(state_path / "inbox.jsonl", inbox_entry)

    outbox_entry = {
        "timestamp": now,
        "response": packet,
    }
    append_log(state_path / "outbox.jsonl", outbox_entry)

    print(json.dumps(packet, indent=2))


if __name__ == "__main__":
    try:
        main()
    except PamError as exc:
        sys.exit(str(exc))
