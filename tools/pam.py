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
    detect_target_scope,
    ensure_state,
    load_env_file,
    load_persona,
    read_queue,
    write_queue,
)
from tools.agent_packets import build_packet, normalize_role
from tools.agent_context import build_prompt
from tools.agent_reports import load_agent_histories

from tools.llm_client import OpenAIAdapter, SimpleLLMAdapter
from tools.openclaw_agent_bridge import OpenClawAdapter

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


def choose_adapter(agent_id: str, agent_info: Dict[str, Any]) -> OpenClawAdapter:
 return OpenClawAdapter(agent_id)


def _ledger_paths(prompt: Dict[str, Any]) -> tuple[Path, Path | None]:
    usage_path = ROOT / "state" / "agents" / "ledger" / "usage.jsonl"
    run_id = prompt.get("run_id") or os.environ.get("ACC_RUN_ID")
    run_usage_path = None
    if isinstance(run_id, str) and run_id:
        run_usage_path = ROOT / "state" / "live_runs" / run_id / "artifacts" / "ledger_usage.jsonl"
    return usage_path, run_usage_path


def _ledger_size(path: Path | None) -> int:
    if path is None or not path.exists():
        return -1
    try:
        return int(path.stat().st_size)
    except Exception:
        return -1


def _append_pam_usage_telemetry(
    prompt: Dict[str, Any],
    outcome: str,
    provider: str,
    model: str,
    error: str | None = None,
) -> None:
    target_scope = prompt.get("target_scope")
    company = target_scope if isinstance(target_scope, str) and target_scope.startswith("company_") else None
    run_id = prompt.get("run_id") or os.environ.get("ACC_RUN_ID")
    telemetry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": prompt.get("agent_id"),
        "company": company,
        "run_id": run_id,
        "cycle": prompt.get("cycle"),
        "model": model,
        "provider": provider,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost": None,
        "outcome": outcome,
    }
    if error is not None:
        telemetry["bridge_error"] = error
    usage_path, run_usage_path = _ledger_paths(prompt)
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    with usage_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(telemetry) + "\n")
    if run_usage_path is not None:
        run_usage_path.parent.mkdir(parents=True, exist_ok=True)
        with run_usage_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(telemetry) + "\n")


def merge_structured_fields(packet: Dict[str, Any], prompt: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
 structured = prompt.get("structured_output", {}) or {}
 required_keys = structured.get("required_keys", []) or []
 for key in required_keys:
  if key in response:
   packet[key] = response.get(key)
 if "packets" in response:
  packet["packets"] = response.get("packets", [])
 return packet


def main() -> None:
    parser = argparse.ArgumentParser(description="Pam front desk coordinator")
    parser.add_argument("--agent", required=True, help="Agent ID from config/agents.yaml")
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

    inbox_history, outbox_history = load_agent_histories(state_path)
    persona = load_persona(agent_info)
    target_scope = detect_target_scope(message, scope)
    prompt = build_prompt(agent_info, scope, message, queue, inbox_history, outbox_history, persona, target_scope)
    run_id = os.environ.get("ACC_RUN_ID")
    cycle = os.environ.get("ACC_CYCLE")
    if run_id is not None:
        prompt["run_id"] = run_id
    if cycle is not None:
        prompt["cycle"] = cycle
    if os.environ.get("LIVE_RUN_PROOF_TELEMETRY", "").lower() in {"1", "true", "yes", "on"} and message.startswith("Paper-proof telemetry probe."):
        proof_prompt = {
            "agent_id": args.agent,
            "target_scope": target_scope,
            "cycle": cycle,
            "run_id": run_id,
            "role_spec": "Proof telemetry probe",
            "persona_description": "Return a minimal JSON object for a paper proof run.",
            "structured_output": {
                "description": "Paper-proof telemetry probe",
                "required_keys": ["status"],
                "default_queue_action": "none",
            },
        }
        response = OpenAIAdapter().reason(message, proof_prompt)
        print(json.dumps({
            "reply_text": response.get("reply_text", "Proof telemetry probe recorded."),
            "priority": response.get("priority", "low"),
            "queue_action": response.get("queue_action", "none"),
            "status": response.get("status", "ok"),
            "escalation": response.get("escalation", False),
            "task_type": response.get("task_type", "proof_telemetry"),
            "requested_action": response.get("requested_action", "Proof telemetry probe only"),
        }))
        return
    resolved_target_scope = prompt.get("target_scope", scope)
    adapter = choose_adapter(args.agent, agent_info)
    usage_path, run_usage_path = _ledger_paths(prompt)
    usage_size_before = _ledger_size(usage_path)
    run_usage_size_before = _ledger_size(run_usage_path)
    try:
     response = adapter.reason(message, prompt)
    except Exception as exc:
     fallback_adapter = SimpleLLMAdapter()
     response = fallback_adapter.reason(message, prompt)
     response.setdefault("priority", "medium")
     response.setdefault("queue_action", prompt["structured_output"]["default_queue_action"])
     response.setdefault("status", "ok")
     response["bridge_fallback_used"] = True
     response["bridge_error"] = str(exc)
     response["bridge_failed"] = False

    usage_size_after = _ledger_size(usage_path)
    run_usage_size_after = _ledger_size(run_usage_path)
    if usage_size_after == usage_size_before and run_usage_size_after == run_usage_size_before:
        _append_pam_usage_telemetry(
            prompt,
            outcome="fallback" if response.get("bridge_fallback_used") else "success",
            provider="python_role_fallback" if response.get("bridge_fallback_used") else "pam_runtime",
            model=adapter.__class__.__name__,
            error=str(response.get("bridge_error") or "") or None,
        )

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
    packet = merge_structured_fields(packet, prompt, response)

    role_type = normalize_role(prompt.get("role_type", "")).lower()
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
    elif role_type == "master ceo":
        packet["executive_summary"] = response.get("executive_summary", "")
        packet["ecosystem_direction"] = response.get("ecosystem_direction", "")
        packet["lifecycle_decision"] = response.get("lifecycle_decision", "")
        packet["branch_coordination_directive"] = response.get("branch_coordination_directive", "")
        packet["strategic_recommendation"] = response.get("strategic_recommendation", "")
        packet["request_more_evidence"] = response.get("request_more_evidence", "")
        packet["packets"] = response.get("packets", [])
    elif "ombudsman" in role_type:
        packet["appeal_intake_summary"] = response.get("appeal_intake_summary", "")
        packet["complaint_triage_decision"] = response.get("complaint_triage_decision", "")
        packet["fairness_summary"] = response.get("fairness_summary", "")
        packet["procedural_guidance"] = response.get("procedural_guidance", "")
        packet["recommendation"] = response.get("recommendation", "")
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
