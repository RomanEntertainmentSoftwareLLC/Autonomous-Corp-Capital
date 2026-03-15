#!/usr/bin/env python3
"""Per-company Pam front desk coordinator with persona awareness."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.llm_client import OpenAIAdapter, SimpleLLMAdapter

CONFIG_PATH = ROOT / "config" / "agents.yaml"
STATE_ROOT = ROOT / "state" / "agents"
UNIVERSAL_PERSONA_PATH = ROOT / "personas" / "universal.json"
AGENT_PERSONA_DIR = ROOT / "personas" / "agents"

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

ALLOWED_RECIPIENTS = sorted({entry[2] for entry in TASK_TYPES})
ROLE_SPEC = "Pam is the front desk admin; she triages, routes, summarizes, and tracks."


class PamError(Exception):
    pass


def load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def merge_personas(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_personas(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_persona(agent_info: Dict[str, str]) -> Dict[str, Any]:
    persona_id = agent_info.get("persona", agent_info.get("id"))
    universal = load_json_file(UNIVERSAL_PERSONA_PATH)
    agent_persona = load_json_file(AGENT_PERSONA_DIR / f"{persona_id}.json")
    return merge_personas(universal, agent_persona)


def persona_description(persona: Dict[str, Any]) -> str:
    lines: List[str] = []
    identity = persona.get("identity", {})
    if identity:
        impression = identity.get("core_impression")
        if impression:
            lines.append(f"Identity: {impression}")
    tone = persona.get("tone", {})
    if tone:
        lines.append(f"Tone: {tone.get('style')} ({tone.get('formality')})")
    bias = persona.get("operational_bias", {})
    if bias:
        keys = ", ".join([k for k, v in bias.items() if v])
        if keys:
            lines.append(f"Bias: {keys}")
    return " | ".join(lines) if lines else ""


def load_agents() -> Dict[str, Dict[str, str]]:
    if not CONFIG_PATH.exists():
        raise PamError(f"Agents config not found at {CONFIG_PATH}")
    data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    agents: Dict[str, Dict[str, str]] = {}
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


def read_queue(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return DEFAULT_QUEUE.copy()


def write_queue(path: Path, queue: Dict[str, Any]) -> None:
    path.write_text(json.dumps(queue, indent=2))


def summarize_queue(queue: Dict[str, Any]) -> Dict[str, int]:
    return {k: len(queue.get(k, [])) for k in DEFAULT_QUEUE.keys()}


def read_history(path: Path, limit: int = 5) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    history: List[Dict[str, Any]] = []
    for raw in lines[-limit:]:
        try:
            history.append(json.loads(raw))
        except Exception:
            continue
    return history


def append_log(path: Path, entry: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def create_prompt(agent_info: Dict[str, str], scope: str, message: str, queue: Dict[str, Any], inbox: List[Dict[str, Any]], outbox: List[Dict[str, Any]], persona: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "role_spec": ROLE_SPEC,
        "scope": scope,
        "allowed_recipients": ALLOWED_RECIPIENTS,
        "queue_summary": summarize_queue(queue),
        "recent_inbox": inbox,
        "recent_outbox": outbox,
        "task_rules": TASK_TYPES,
        "persona": persona,
        "persona_description": persona_description(persona),
        "message": message,
    }


def choose_adapter(agent_id: str) -> SimpleLLMAdapter | OpenAIAdapter:
    if agent_id == "pam_company_001":
        try:
            return OpenAIAdapter()
        except EnvironmentError:
            return SimpleLLMAdapter()
    return SimpleLLMAdapter()


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
    scope = agent_info.get("scope", "global")

    state_path = ensure_state(args.agent)
    queue_path = state_path / "queue.json"
    queue = read_queue(queue_path)
    inbox_history = read_history(state_path / "inbox.jsonl")
    outbox_history = read_history(state_path / "outbox.jsonl")

    if args.show_queue:
        print(json.dumps(queue, indent=2))
        return

    persona = load_persona(agent_info)
    prompt = create_prompt(agent_info, scope, message, queue, inbox_history, outbox_history, persona)
    adapter = choose_adapter(args.agent)
    response = adapter.reason(message, prompt)

    now = datetime.utcnow().isoformat() + "+00:00"
    task_id = str(uuid.uuid4())
    recipient = response.get("recipient", "Analyst")
    priority = response.get("priority", "medium")
    queue_action = response.get("queue_action", "create")

    packet = {
        "task_id": task_id,
        "from": args.sender,
        "to": recipient,
        "company_scope": scope,
        "task_type": response.get("task_type", "general_triage"),
        "priority": priority,
        "summary": message if len(message) < 140 else message[:137] + "...",
        "context": [
            f"Captured at {now}",
            f"Agent: {agent_info.get('name', args.agent)}",
            response.get("reply_text", ""),
        ],
        "requested_action": response.get("requested_action", ""),
        "status": "new",
        "escalate_to": "YamYam" if response.get("escalate") else "",
        "reply_text": response.get("reply_text", ""),
    }

    if queue_action in ("create", "update"):
        queue_entry = {
            "task_id": task_id,
            "summary": packet["summary"],
            "priority": packet["priority"],
            "assigned_to": recipient,
            "status": "new",
            "timestamp": now,
        }
        queue.setdefault("new", []).append(queue_entry)
        write_queue(queue_path, queue)

    if response.get("escalate"):
        append_log(state_path / "escalations.jsonl", {
            "timestamp": now,
            "task_id": task_id,
            "reason": response.get("reply_text", ""),
            "recipient": recipient,
        })

    append_log(state_path / "inbox.jsonl", {
        "timestamp": now,
        "sender": args.sender,
        "message": message,
        "task_id": task_id,
    })

    append_log(state_path / "outbox.jsonl", {"timestamp": now, "response": packet})

    print(json.dumps(packet, indent=2))


if __name__ == "__main__":
    try:
        main()
    except PamError as exc:
        sys.exit(str(exc))
