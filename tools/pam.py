#!/usr/bin/env python3
"""Per-company Pam and Iris front desk coordinator with persona awareness."""

from __future__ import annotations

import argparse
import json
import os
import re
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

ROLE_SPECS = {
    "administrative_coordinator": (
        "Pam is the organizational coordinator. She triages, routes, summarizes, and keeps the queue tidy."
    ),
    "Analyst": (
        "Iris is the company Analyst. She reads company data, explains what is happening, identifies risks, highlights missing evidence, and suggests next areas for review. She does not make executive decisions."
    ),
    "Manager": (
        "Vera is the company Manager. She reviews Iris’s analyses, proposes practical next steps, highlights uncertainties, and escalates or requests follow-up when needed without making final approvals."
    ),
    "Researcher": (
        "Rowan is the company Researcher. She explores strategic experiments, hypotheses, and alternative paths based on Iris and Vera’s work, reporting evidence-backed possibilities without pretending they are approved."
    ),
}

ROLE_STRUCTURED_OUTPUT = {
    "administrative_coordinator": {
        "required_keys": [
            "reply_text",
            "task_type",
            "priority",
            "recipient",
            "requested_action",
            "queue_action",
            "escalate",
        ],
        "default_queue_action": "create",
        "description": "Return routing packets for the organization.",
    },
    "Analyst": {
        "required_keys": [
            "reply_text",
            "analysis_summary",
            "evidence",
            "missing_data",
            "suggested_followup",
            "escalation",
            "queue_action",
        ],
        "default_queue_action": "none",
        "description": "Return diagnostic insights, evidence, and follow-ups.",
    },
    "Manager": {
        "required_keys": [
            "reply_text",
            "recommendation",
            "rationale",
            "evidence",
            "missing_data",
            "suggested_followup",
            "escalation",
            "queue_action",
        ],
        "default_queue_action": "none",
        "description": "Return action proposals and escalation advice.",
    },
    "Researcher": {
        "required_keys": [
            "reply_text",
            "research_summary",
            "ideas",
            "hypotheses",
            "evidence",
            "missing_data",
            "suggested_followup",
            "escalation",
            "queue_action",
        ],
        "default_queue_action": "none",
        "description": "Return exploratory research insights and experiment ideas.",
    },
}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

load_env_file(ROOT / ".env")


class PamError(Exception):
    pass


def load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_yaml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
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



def detect_target_scope(message: str, default: str) -> str:
    lowered = message.lower()
    match = re.search(r"(company_\d+)", lowered)
    return match.group(1) if match else default

def gather_company_insights(scope: str, target_scope: str) -> Dict[str, Any]:
    insights: Dict[str, Any] = {"scope": scope, "target_scope": target_scope}
    comp_dir = ROOT / "companies" / target_scope
    metadata = load_yaml_file(comp_dir / "metadata.yaml")
    config = load_yaml_file(comp_dir / "config.yaml")
    insights["metadata_summary"] = metadata.get("lifecycle_state") or "unknown"
    if metadata:
        insights["lifecycle_details"] = {
            "state": metadata.get("lifecycle_state"),
            "strategy": metadata.get("lifecycle_strategy"),
            "fitness": metadata.get("last_fitness"),
        }
    insights["config_summary"] = {
        "symbols": config.get("symbols"),
        "timing": config.get("timing"),
    }
    leaderboard_path = ROOT / "leaderboard.json"
    insights["leaderboard_entries"] = []
    if leaderboard_path.exists():
        try:
            board_data = json.loads(leaderboard_path.read_text())
            rows = board_data.get("rows") if isinstance(board_data, dict) else board_data
            for entry in rows or []:
                if entry.get("company") == target_scope:
                    insights["leaderboard_entries"].append(entry)
        except Exception:
            pass
    insights["leaderboard_summary"] = (
        insights["leaderboard_entries"][0] if insights["leaderboard_entries"] else None
    )
    manager_actions = load_yaml_file(Path("manager_actions.yaml"))
    insights["manager_action"] = None
    for action in manager_actions.get("actions", []):
        if action.get("company") == target_scope:
            insights["manager_action"] = action
            break
    results_dir = ROOT / "results" / target_scope
    if results_dir.exists():
        insights["logs_present"] = True
        insights["log_paths"] = [str(p) for p in results_dir.rglob("*.jsonl")]
    else:
        insights["logs_present"] = False
    missing = []
    if not metadata:
        missing.append("metadata")
    if not config:
        missing.append("config")
    if not insights["leaderboard_entries"]:
        missing.append("leaderboard")
    if not insights["logs_present"]:
        missing.append("logs")
    if not insights.get("manager_action"):
        missing.append("manager_action")
    insights["missing_data"] = missing
    return insights

def create_prompt(
    agent_info: Dict[str, str],
    scope: str,
    message: str,
    queue: Dict[str, Any],
    inbox: List[Dict[str, Any]],
    outbox: List[Dict[str, Any]],
    persona: Dict[str, Any],
    target_scope: str,
) -> Dict[str, Any]:
    role_type = agent_info.get("role", "").strip()
    role_spec = ROLE_SPECS.get(role_type, ROLE_SPECS.get("administrative_coordinator", ""))
    structured = ROLE_STRUCTURED_OUTPUT.get(role_type, ROLE_STRUCTURED_OUTPUT["administrative_coordinator"])
    insights = gather_company_insights(scope, target_scope)
    return {
        "role_type": role_type,
        "role_spec": role_spec,
        "structured_output": structured,
        "persona": persona,
        "persona_description": persona_description(persona),
        "scope": scope,
        "target_scope": target_scope,
        "allowed_recipients": ALLOWED_RECIPIENTS,
        "queue_summary": summarize_queue(queue),
        "recent_inbox": inbox,
        "recent_outbox": outbox,
        "company_insights": insights,
        "message": message,
    }
def choose_adapter(agent_id: str) -> SimpleLLMAdapter | OpenAIAdapter:
    if agent_id.startswith("pam_company_") or agent_id.startswith("iris_company_"):
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
    parser.add_argument("message", nargs="*", help="Message or request for Pam")
    args = parser.parse_args()

    message = " ".join(args.message).strip() if args.message else ""

    agents = load_agents()
    if args.agent not in agents:
        raise PamError(f"Unknown agent '{args.agent}' (check config/agents.yaml)")
    agent_info = agents[args.agent]
    scope = agent_info.get("scope", "global")

    state_path = ensure_state(args.agent)
    queue_path = state_path / "queue.json"
    queue = read_queue(queue_path)

    if args.show_queue:
        print(json.dumps(queue, indent=2))
        return

    if not message:
        parser.error("Message cannot be empty")

    inbox_history = read_history(state_path / "inbox.jsonl")
    outbox_history = read_history(state_path / "outbox.jsonl")
    persona = load_persona(agent_info)
    target_scope = detect_target_scope(message, scope)
    prompt = create_prompt(agent_info, scope, message, queue, inbox_history, outbox_history, persona, target_scope)
    adapter = choose_adapter(args.agent)
    response = adapter.reason(message, prompt)

    now = datetime.utcnow().isoformat() + "+00:00"
    task_id = str(uuid.uuid4())
    recipient = response.get("recipient", "Analyst")
    priority = response.get("priority", "medium")
    queue_action = response.get("queue_action", prompt["structured_output"]["default_queue_action"])

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
        "escalate_to": "YamYam" if response.get("escalation") else "",
        "reply_text": response.get("reply_text", ""),
        "queue_action": queue_action,
    }

    role_type = prompt.get("role_type", "").lower()
    if role_type == "analyst":
        packet["analysis_summary"] = response.get("analysis_summary", "")
        packet["evidence"] = response.get("evidence", [])
        packet["missing_data"] = response.get("missing_data", [])
        packet["suggested_followup"] = response.get("suggested_followup", "")
    elif role_type == "manager":
        packet["recommendation"] = response.get("recommendation", "")
        packet["rationale"] = response.get("rationale", "")
        packet["evidence"] = response.get("evidence", [])
        packet["missing_data"] = response.get("missing_data", [])
        packet["suggested_followup"] = response.get("suggested_followup", "")
    elif role_type == "researcher":
        packet["research_summary"] = response.get("research_summary", "")
        packet["ideas"] = response.get("ideas", [])
        packet["hypotheses"] = response.get("hypotheses", [])
        packet["evidence"] = response.get("evidence", [])
        packet["missing_data"] = response.get("missing_data", [])
        packet["suggested_followup"] = response.get("suggested_followup", "")

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

    if response.get("escalation"):
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
