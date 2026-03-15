"""Packet assembly helpers for all agents."""

from __future__ import annotations

from typing import Any, Dict, Tuple


def resolve_packet_targets(response: Dict[str, Any]) -> Tuple[str, str]:
    recipient = response.get("recipient", "")
    handoff_override = response.get("handoff_to")
    if handoff_override:
        return "user", handoff_override
    if recipient and recipient.lower() not in ("analyst", "user", ""):
        return "user", recipient
    return "user", ""


def normalize_role(role: str) -> str:
    if not role:
        return ""
    normalized = role.replace("_", " ").replace("-", " ")
    normalized = normalized.title()
    replacements = {"Cfo": "CFO", "Qa": "QA", "Treasure": "Treasurer", "Risk Officer": "Risk Officer", "Ceo": "CEO", "Master Ceo": "Master CEO"}
    for key, value in replacements.items():
        normalized = normalized.replace(key, value)
    return normalized


def build_packet(
    agent_info: Dict[str, Any],
    prompt: Dict[str, Any],
    response: Dict[str, Any],
    message: str,
    queue_action: str,
    priority: str,
    task_id: str,
    timestamp: str,
) -> Dict[str, Any]:
    to, handoff_to = resolve_packet_targets(response)
    lower_msg = message.lower()
    if not handoff_to and ("helena" in lower_msg or "risk officer" in lower_msg):
        handoff_to = "Risk Officer"
    role = normalize_role(agent_info.get("role") or prompt.get("role_type", ""))
    agent_scope = prompt.get("scope", agent_info.get("scope", "global"))
    target_scope = prompt.get("target_scope", agent_scope)
    task_type = response.get("task_type", "general_triage")
    if handoff_to == "Risk Officer" and task_type == "general_triage":
        task_type = "risk_review"
    requested_action = response.get("requested_action")
    override_reply = response.get("reply_text", "")
    if handoff_to:
        requested_action = f"{handoff_to}: handle {task_type} for {target_scope}"
        if not override_reply or "Analyst" in override_reply:
            override_reply = f"I've routed this to {handoff_to} for {task_type}."
    elif not requested_action:
        requested_action = f"{role or agent_info.get('name', agent_info.get('id', ''))}: respond to {task_type}"
    status = response.get("status")
    escalate_to = response.get("escalate_to") or ("Yam Yam" if response.get("escalation") else "")
    direct_reply = to == "user" and not handoff_to and queue_action == "none"
    if queue_action == "none" and not response.get("escalation"):
        status = "completed"
    elif not status:
        status = "new"
    if direct_reply:
        status = "completed"
        escalate_to = ""
    return {
        "task_id": task_id,
        "from": agent_info.get("id", ""),
        "requested_action": requested_action,
        "to": to,
        "handoff_to": handoff_to,
        "role": role,
        "agent_scope": agent_scope,
        "target_scope": target_scope,
        "task_type": task_type,
        "priority": priority,
        "summary": message if len(message) < 140 else message[:137] + "...",
        "reply_text": override_reply,
        "queue_action": queue_action,
        "status": status,
        "escalate_to": escalate_to,
        "context": [
            f"Captured at {timestamp}",
            f"Agent: {agent_info.get('name', agent_info.get('id', ''))}",
            override_reply,
        ],
    }
