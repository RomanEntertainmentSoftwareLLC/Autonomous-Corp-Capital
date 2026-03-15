#!/usr/bin/env python3
"""Per-company Pam and Iris front desk coordinator with persona awareness."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.agent_runtime import (
    AGENT_PERSONA_DIR,
    CONFIG_PATH,
    ROOT as AGENT_ROOT,
    STATE_ROOT,
    UNIVERSAL_PERSONA_PATH,
    append_log,
    collect_agent_reports,
    detect_target_scope,
    ensure_state,
    gather_company_insights,
    gather_global_treasury_insights,
    gather_global_risk_insights,
    gather_global_finance_insights,
    load_env_file,
    load_persona,
    persona_description,
    read_history,
    read_queue,
    summarize_queue,
    write_queue,
)
from tools.agent_packets import build_packet

from tools.llm_client import OpenAIAdapter, SimpleLLMAdapter

load_env_file(AGENT_ROOT / ".env")


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



class PamError(Exception):
    pass

TASK_TYPES = [
    ("financial", "financial_review", "Bianca"),
    ("budget", "financial_review", "Bianca"),
    ("runway", "financial_review", "Bianca"),
    ("cash", "financial_review", "Bianca"),
    ("spend", "financial_review", "Bianca"),
    ("capital", "financial_review", "Bianca"),
    ("evolution", "evolution", "Sloane"),
    ("mutation", "evolution", "Sloane"),
    ("mutate", "evolution", "Sloane"),
    ("mutations", "evolution", "Sloane"),
    ("fork", "evolution", "Sloane"),
    ("simulate", "simulation_review", "Atlas"),
    ("simulation", "simulation_review", "Atlas"),
    ("scenario", "simulation_review", "Atlas"),
    ("backtest", "simulation_review", "Atlas"),
    ("branch", "evolution", "Sloane"),
    ("artifacts", "operational_task", "Bob"),
    ("artifact", "operational_task", "Bob"),
    ("gather", "operational_task", "Bob"),
    ("collect", "operational_task", "Bob"),
    ("log", "operational_task", "Bob"),
    ("file", "operational_task", "Bob"),
    ("archive", "operational_task", "Bob"),
    ("cleanup", "operational_task", "Bob"),
    ("decision", "executive_decision", "Lucian"),
    ("direction", "executive_decision", "Lucian"),
    ("approve", "executive_decision", "Lucian"),
    ("strategy", "executive_decision", "Lucian"),
    ("hold", "executive_decision", "Lucian"),
    ("risk", "risk_review", "Risk Officer"),
    ("treasury", "treasury_review", "Master Treasurer"),
    ("portfolio", "finance_review", "Master CFO"),
    ("product", "product_review", "Product Manager"),
    ("backlog", "product_review", "Product Manager"),
    ("feature", "product_review", "Product Manager"),
    ("sprint", "execution_review", "Scrum Master"),
    ("task", "execution_review", "Scrum Master"),
    ("blocker", "execution_review", "Scrum Master"),
    ("efficiency", "finance_review", "Master CFO"),
    ("sustainability", "finance_review", "Master CFO"),
    ("health", "finance_review", "Master CFO"),
    ("risk", "risk_review", "Risk Officer"),
    ("veto", "risk_review", "Risk Officer"),
    ("compliance", "risk_review", "Risk Officer"),
    ("lifecycle", "lifecycle_action", "YamYam"),
    ("software", "software_task", "Product Manager"),
    ("bug", "bug_fix", "SWE"),
    ("meeting", "meeting_prep", "Scrum Master"),
    ("report", "status_report", "Analyst"),
    ("analysis", "analysis", "Analyst"),
    ("archive", "archival_summary", "June"),
    ("history", "archival_summary", "June"),
    ("record", "archival_summary", "June"),
    ("lessons", "archival_summary", "June"),
    ("timeline", "archival_summary", "June"),
]


ALLOWED_RECIPIENTS = sorted({entry[2] for entry in TASK_TYPES})

ROLE_SPECS = {
    "administrative_coordinator": (
        "Pam is the organizational coordinator. She triages, routes, summarizes, and keeps the queue tidy."
    ),
    "Analyst": (
        "Iris is the company Analyst. She reads company data, explains what is happening, highlights missing evidence, and suggests next areas for review without making executive calls."
    ),
    "Manager": (
        "Vera is the company Manager. She reviews Iris’s analyses, recommends next steps, and escalates or requests follow-up when required."
    ),
    "Researcher": (
        "Rowan is the company Researcher. She explores strategic experiments and reports evidence-backed ideas without claiming approvals."
    ),
    "Evolution": (
        "Sloane is the company Evolution Specialist. She turns vetted signals into controlled mutation proposals for Atlas."
    ),
    "Market Simulator": (
        "Atlas is the company Market Simulator. He compares scenarios and explains what the simulation can and cannot guarantee."
    ),
    "Archivist": (
        "June is the company Archivist. She records what happened, compiles timelines, and keeps the memory clean without drama."
    ),
    "CEO": (
        "Lucian is the company CEO. He weighs the inputs from Pam, Iris, Vera, Rowan, Bianca, and global stewards before guiding the company."
    ),
    "CFO": (
        "Bianca is the company CFO. She interprets allocation, runway, and Vera/Iris context to protect local financial sanity."
    ),
    "Master Treasurer": (
        "Selene is the global Master Treasurer. She watches the parent treasury, compares company posture, and keeps capital discipline before allocating."
    ),
    "Risk Officer": (
        "Helena is the global Risk Officer. She enforces boundaries, vetoes reckless ideas, and keeps the ecosystem within policy."
    ),
    "Master CFO": (
        "Vivienne is the global Master CFO. She reads the entire portfolio for efficiency, sustainability, and strategic financial alignment."
    ),
    "Product Manager": (
        "Nadia is the global Product Manager. She turns shared system friction into prioritized, scoped work without coding it herself."
    ),
    "Low Tier Operations Worker": (
        "Bob is the low-tier operations worker who handles safe, repetitive chores and reports plainly."
    ),
}
ROLE_STRUCTURED_OUTPUT = {
    "administrative_coordinator": {
        "required_keys": ["reply_text", "packets", "queue_action"],
        "default_queue_action": "create",
        "description": "Handle routing, queue triage, and packet creation for incoming tasks."
    },
    "Analyst": {
        "required_keys": ["reply_text", "analysis_summary", "evidence", "missing_data", "suggested_followup"],
        "default_queue_action": "none",
        "description": "Iris analyzes data, surfaces evidence, and flags missing information."
    },
    "Manager": {
        "required_keys": ["reply_text", "recommendation", "rationale", "evidence", "missing_data", "suggested_followup"],
        "default_queue_action": "none",
        "description": "Vera delivers management recommendations grounded in Iris and Rowan input."
    },
    "Researcher": {
        "required_keys": ["reply_text", "research_summary", "ideas", "hypotheses", "evidence", "missing_data", "suggested_followup"],
        "default_queue_action": "none",
        "description": "Rowan returns research-backed ideas and experiments without claiming approvals."
    },
    "Evolution": {
        "required_keys": ["reply_text", "mutation_proposal", "evolution_summary", "candidate_parameters", "candidate_strategies", "rationale", "risk_notes", "packets"],
        "default_queue_action": "none",
        "description": "Sloane crafts controlled mutation proposals for Atlas and the engineering branch."
    },
    "Market Simulator": {
        "required_keys": ["reply_text", "simulation_summary", "scenario_results", "comparative_outcomes", "confidence", "limitations", "recommendation", "packets"],
        "default_queue_action": "none",
        "description": "Atlas evaluates proposed changes under simulated scenarios and shares confidence notes."
    },
    "Archivist": {
        "required_keys": ["reply_text", "archival_summary", "decision_record", "event_summary", "memory_digest", "timeline", "lessons_learned", "unresolved_issues", "packets"],
        "default_queue_action": "none",
        "description": "June preserves memory, summarizing decisions, lessons, and unresolved issues."
    },
    "CEO": {
        "required_keys": ["reply_text", "decision", "executive_summary", "approval_decision", "rationale", "action_directive", "request_more_evidence", "packets"],
        "default_queue_action": "none",
        "description": "Lucian weighs all inputs plus global stewards before giving company direction."
    },
    "CFO": {
        "required_keys": ["reply_text", "financial_health_summary", "cash_runway_caution", "spending_posture", "recommendation", "financial_rationale", "packets"],
        "default_queue_action": "none",
        "description": "Bianca protects company runway and financial discipline."
    },
    "Master Treasurer": {
        "required_keys": ["reply_text", "global_treasury_summary", "allocation_recommendation", "reserve_posture", "allowance_recommendation", "packets"],
        "default_queue_action": "none",
        "description": "Selene safeguards the parent treasury, balancing capital across companies."
    },
    "Risk Officer": {
        "required_keys": ["reply_text", "global_risk_summary", "veto_decision", "caution_notes", "packets"],
        "default_queue_action": "none",
        "description": "Helena enforces risk boundaries and vetoes unsafe proposals."
    },
    "Master CFO": {
        "required_keys": ["reply_text", "global_financial_summary", "priority_backlog", "recommendation", "packets"],
        "default_queue_action": "none",
        "description": "Vivienne provides portfolio-level financial strategy guidance."
    },
    "Product Manager": {
        "required_keys": ["reply_text", "product_summary", "priority_backlog", "recommendation", "acceptance_criteria", "packets"],
        "default_queue_action": "none",
        "description": "Nadia turns product requests into scoped work."
    },
    "Scrum Master": {
        "required_keys": ["reply_text", "task_summary", "engineering_tasks", "blockers", "next_handoff", "packets"],
        "default_queue_action": "none",
        "description": "Tessa sequences tasks, identifies blockers, and routes work."
    },
    "Senior Software Architect": {
        "required_keys": ["reply_text", "architecture_summary", "refactor_recommendation", "module_guidance", "technical_debt", "packets"],
        "default_queue_action": "none",
        "description": "Marek guards architecture and refactor direction."
    },
    "Senior Software Engineer": {
        "required_keys": ["reply_text", "implementation_summary", "code_plan", "integration_notes", "blockers", "packets"],
        "default_queue_action": "none",
        "description": "Eli implements the hard shared work under architectural guidance."
    },
    "Junior Software Engineer": {
        "required_keys": ["reply_text", "implementation_summary", "subtasks", "escalation_notes", "blockers", "packets"],
        "default_queue_action": "none",
        "description": "Noah handles bounded helper tasks and escalates higher-risk work."
    },
    "Tester": {
        "required_keys": ["reply_text", "test_summary", "failing_cases", "coverage_notes", "recommendation", "packets"],
        "default_queue_action": "none",
        "description": "Mina validates test results and reproducibility."
    },
    "Code Reviewer": {
        "required_keys": ["reply_text", "review_summary", "review_findings", "maintainability_notes", "merge_readiness", "packets"],
        "default_queue_action": "none",
        "description": "Gideon guards code quality and merge readiness."
    },
    "QA": {
        "required_keys": ["reply_text", "qa_summary", "behavior_notes", "regression_risks", "ship_readiness", "packets"],
        "default_queue_action": "none",
        "description": "Sabine evaluates behavior, coverage, and regression safety."
    },
    "Infrastructure": {
        "required_keys": ["reply_text", "infrastructure_summary", "version_control_plan", "release_notes", "rollback_readiness", "packets"],
        "default_queue_action": "none",
        "description": "Rhea stewards branch hygiene, release flow, and rollbacks."
    },
    "Low Tier Operations Worker": {
        "required_keys": ["reply_text", "op_summary", "artifacts", "status", "packets"],
        "default_queue_action": "none",
        "description": "Bob handles safe operational chores."
    }
}

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
    role_key = role_type.lower()
    role_spec = ROLE_SPECS.get(role_type, ROLE_SPECS.get("administrative_coordinator", ""))
    structured = ROLE_STRUCTURED_OUTPUT.get(role_type, ROLE_STRUCTURED_OUTPUT["administrative_coordinator"])
    insights = gather_company_insights(scope, target_scope, queue)
    global_insights = gather_global_treasury_insights() if role_key == "master treasurer" else {}
    global_risk_insights = gather_global_risk_insights() if role_key == "risk officer" else {}
    global_finance_insights = gather_global_finance_insights() if role_key == "master cfo" else {}
    prompt = {
        "role_type": role_type,
        "role_spec": role_spec,
        "structured_output": structured,
        "persona": persona,
        "persona_description": persona_description(persona),
        "scope": scope,
        "agent_scope": scope,
        "target_scope": target_scope,
        "allowed_recipients": ALLOWED_RECIPIENTS,
        "queue_summary": summarize_queue(queue),
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
def choose_adapter(agent_id: str) -> SimpleLLMAdapter | OpenAIAdapter:
    if agent_id in ("master_treasurer", "risk_officer", "master_cfo", "product_manager", "scrum_master", "senior_software_architect", "senior_software_engineer", "junior_software_engineer", "tester", "code_reviewer", "qa") or any(agent_id.startswith(prefix) for prefix in ("pam_company_", "iris_company_", "vera_company_", "rowan_company_", "bianca_company_", "lucian_company_", "bob_company_", "sloane_company_", "atlas_company_", "june_company_")):
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
    resolved_target_scope = prompt.get("target_scope", scope)
    adapter = choose_adapter(args.agent)
    response = adapter.reason(message, prompt)

    now = datetime.now(timezone.utc).isoformat()
    task_id = str(uuid.uuid4())
    priority = response.get("priority", "medium")
    queue_action = response.get("queue_action", prompt["structured_output"]["default_queue_action"])

    packet = build_packet(
        agent_info,
        prompt,
        response,
        message,
        queue_action,
        priority,
        task_id,
        now,
    )

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
    elif role_type == "cfo":
        packet["financial_health_summary"] = response.get("financial_health_summary", "")
        packet["cash_runway_caution"] = response.get("cash_runway_caution", "")
        packet["spending_posture"] = response.get("spending_posture", "")
        packet["recommendation"] = response.get("recommendation", "")
        packet["financial_rationale"] = response.get("financial_rationale", "")
        packet["evidence"] = response.get("evidence", [])
        packet["missing_data"] = response.get("missing_data", [])
        packet["suggested_followup"] = response.get("suggested_followup", "")
        packet["packets"] = response.get("packets", [])
    elif role_type == "master treasurer":
        packet["global_treasury_summary"] = response.get("global_treasury_summary", "")
        packet["allocation_recommendation"] = response.get("allocation_recommendation", "")
        packet["reserve_posture"] = response.get("reserve_posture", "")
        packet["allowance_recommendation"] = response.get("allowance_recommendation", "")
        packet["overexposure_warnings"] = response.get("overexposure_warnings", [])
        packet["financial_rationale"] = response.get("financial_rationale", "")
        packet["packets"] = response.get("packets", [])
    elif role_type == "master cfo":
        packet["global_financial_summary"] = response.get("global_financial_summary", "")
        packet["portfolio_efficiency"] = response.get("portfolio_efficiency", "")
        packet["capital_recommendation"] = response.get("capital_recommendation", "")
        packet["sustainability_note"] = response.get("sustainability_note", "")
        packet["inefficient_companies"] = response.get("inefficient_companies", [])
        packet["ship_to_risk"] = response.get("ship_to_risk", "")
        packet["packets"] = response.get("packets", [])
    elif role_type == "risk officer":
        packet["global_risk_summary"] = response.get("global_risk_summary", "")
        packet["veto_decision"] = response.get("veto_decision", "")
        packet["caution_notes"] = response.get("caution_notes", [])
        packet["drawdown_warnings"] = response.get("drawdown_warnings", [])
        packet["overexposure_flags"] = response.get("overexposure_flags", [])
        packet["recommended_constraints"] = response.get("recommended_constraints", "")
        packet["packets"] = response.get("packets", [])
    elif role_type == "evolution":
        packet["mutation_proposal"] = response.get("mutation_proposal", "")
        packet["evolution_summary"] = response.get("evolution_summary", "")
        packet["candidate_parameters"] = response.get("candidate_parameters", [])
        packet["candidate_strategies"] = response.get("candidate_strategies", [])
        packet["rationale"] = response.get("rationale", "")
        packet["risk_notes"] = response.get("risk_notes", [])
        packet["suggested_followup"] = response.get("suggested_followup", "")
        packet["packets"] = response.get("packets", [])
    elif role_type == "market simulator":
        packet["simulation_summary"] = response.get("simulation_summary", "")
        packet["scenario_results"] = response.get("scenario_results", "")
        packet["comparative_outcomes"] = response.get("comparative_outcomes", [])
        packet["confidence"] = response.get("confidence", "")
        packet["limitations"] = response.get("limitations", "")
        packet["recommendation"] = response.get("recommendation", "")
        packet["suggested_followup"] = response.get("suggested_followup", "")
        packet["packets"] = response.get("packets", [])
    elif role_type == "archivist":
        packet["archival_summary"] = response.get("archival_summary", "")
        packet["decision_record"] = response.get("decision_record", [])
        packet["event_summary"] = response.get("event_summary", [])
        packet["memory_digest"] = response.get("memory_digest", "")
        packet["timeline"] = response.get("timeline", [])
        packet["lessons_learned"] = response.get("lessons_learned", [])
        packet["unresolved_issues"] = response.get("unresolved_issues", [])
        packet["packets"] = response.get("packets", [])
        packet["escalation"] = response.get("escalation", False)
    elif role_type == "ceo":
        packet["decision"] = response.get("decision", "")
        packet["executive_summary"] = response.get("executive_summary", "")
        packet["approval_decision"] = response.get("approval_decision", "")
        packet["rationale"] = response.get("rationale", "")
        packet["action_directive"] = response.get("action_directive", "")
        packet["request_more_evidence"] = response.get("request_more_evidence", "")
        packet["evidence"] = response.get("evidence", [])
        packet["missing_data"] = response.get("missing_data", [])
        packet["suggested_followup"] = response.get("suggested_followup", "")
        packet["packets"] = response.get("packets", [])
    if queue_action in ("create", "update"):
        assigned_to = packet.get("handoff_to") or packet.get("to")
        queue_entry = {
            "task_id": task_id,
            "summary": packet["summary"],
            "priority": packet["priority"],
            "assigned_to": assigned_to,
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
            "recipient": packet.get("handoff_to") or packet.get("to"),
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
