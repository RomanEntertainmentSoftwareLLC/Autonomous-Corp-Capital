"""Shared prompt/context helpers for Pam and the global adapters."""

from __future__ import annotations

from typing import Any, Dict, List

from tools.agent_roles import ALLOWED_RECIPIENTS, ROLE_SPECS, ROLE_STRUCTURED_OUTPUT
from tools.agent_runtime import (
    gather_company_insights,
    gather_global_finance_insights,
    gather_global_risk_insights,
    gather_global_treasury_insights,
    load_policy,
    persona_description,
    policy_description,
    summarize_queue,
)

TREASURY_ROLES = {"master treasurer", "inspector general", "constitutional arbiter", "ombudsman", "master ceo"}
RISK_ROLES = {"risk officer", "inspector general", "constitutional arbiter", "ombudsman", "master ceo"}
FINANCE_ROLES = {"master cfo", "inspector general", "constitutional arbiter", "ombudsman", "master ceo"}


def build_prompt(
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
    role_key = role_type.lower()
    role_spec = ROLE_SPECS.get(role_type, ROLE_SPECS.get("administrative_coordinator", ""))
    structured = ROLE_STRUCTURED_OUTPUT.get(role_type, ROLE_STRUCTURED_OUTPUT["administrative_coordinator"])
    policy = load_policy(agent_info)
    insights = gather_company_insights(scope, target_scope, queue)
    queue_summary = summarize_queue(queue)
    global_insights = gather_global_treasury_insights() if role_key in TREASURY_ROLES else {}
    global_risk_insights = gather_global_risk_insights() if role_key in RISK_ROLES else {}
    global_finance_insights = gather_global_finance_insights() if role_key in FINANCE_ROLES else {}
    prompt: Dict[str, Any] = {
        "role_type": role_type,
        "role_spec": role_spec,
        "structured_output": structured,
        "persona": persona,
        "persona_description": persona_description(persona),
        "policy": policy,
        "policy_description": policy_description(policy),
        "scope": scope,
        "agent_scope": scope,
        "target_scope": target_scope,
        "allowed_recipients": ALLOWED_RECIPIENTS,
        "queue_summary": queue_summary,
        "recent_inbox": inbox,
        "recent_outbox": outbox,
        "company_insights": insights,
        "message": message,
    }
    if global_insights:
        prompt["global_insights"] = global_insights
    if global_risk_insights:
        prompt["global_risk_insights"] = global_risk_insights
    if global_finance_insights:
        prompt["global_finance_insights"] = global_finance_insights
    return prompt
