"""Safe fallback replies for the master/global/watchdog roles using rich context."""

from __future__ import annotations

from typing import Dict, Any, List

GLOBAL_WATCHDOG_ROLES = {
    "Master Treasurer",
    "Risk Officer",
    "Master CFO",
    "Master CEO",
    "Inspector General",
    "Constitutional Arbiter",
    "Ombudsman / Appeals Officer",
}


def _global_context_blob(prompt: Dict[str, Any]) -> Dict[str, Any]:
    insights = prompt.get("company_insights", {}) or {}
    companies = insights.get("company_summary") or []
    status_line = ", ".join(
        f"{c.get('company_id', 'unknown')}({c.get('status', 'unknown')})" for c in companies if c.get("company_id")
    )
    queue = prompt.get("queue_summary") or {}
    queue_line = ", ".join(f"{k}:{v}" for k, v in queue.items() if v) or "queue idle"
    active_count = insights.get("active_company_count") or len(insights.get("active_companies") or []) or len(companies)
    active_line = f"{active_count} active companies" if active_count else "no active companies"
    lifecycle = insights.get("lifecycle_history") or insights.get("metadata_summary") or "lifecycle status pending"
    treasury = prompt.get("global_insights") or {}
    treasury_snapshot = treasury.get("treasury_snapshot") or treasury.get("reserve_snapshot") or treasury
    reserve_note = (
        treasury_snapshot.get("reserve_percent")
        or treasury_snapshot.get("reserve_capital")
        or treasury_snapshot.get("reserves")
        or "unknown reserves"
    )
    risk = prompt.get("global_risk_insights") or {}
    risk_flags = risk.get("risk_flags") or []
    escalations = risk.get("escalations") or []
    risk_line = (
        f"{len(risk_flags)} risk flags; {len(escalations)} escalations"
        if risk_flags or escalations
        else "no risk flags"
    )
    finance = prompt.get("global_finance_insights") or {}
    finance_note = finance.get("sustainability") or "sustainability unknown"
    audit_history = insights.get("agent_reports", {}).get("audit", [])
    policy_note = prompt.get("policy_description") or ""
    return {
        "status_line": status_line or "companies status data missing",
        "queue_line": queue_line,
        "active_line": active_line,
        "lifecycle": lifecycle,
        "treasury_note": f"reserves {reserve_note}",
        "risk_line": risk_line,
        "finance_note": finance_note,
        "audit_history": audit_history,
        "policy_note": policy_note,
        "active_companies": [c.get("company_id") for c in companies if c.get("company_id")],
    }


def _packets_for_role(role: str, context: Dict[str, Any]) -> List[Dict[str, str]]:
    base = [
        {
            "recipient": "Jacob",
            "summary": context.get("status_line", "Status summary unavailable."),
            "next_steps": "Monitor the leadership lane for further direction.",
        }
    ]
    if role == "Master Treasurer":
        base.append(
            {
                "recipient": "Risk Officer",
                "summary": context["risk_line"],
                "next_steps": "Confirm veto posture before allocating new capital.",
            }
        )
    if role == "Risk Officer":
        base.append(
            {
                "recipient": "Master Treasurer",
                "summary": context["treasury_note"],
                "next_steps": "Ensure treasury reserves match the risk posture.",
            }
        )
    return base


def build_global_watchdog_fallback(role: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
    context = _global_context_blob(prompt)
    agent_scope = prompt.get("agent_scope", prompt.get("scope", "global"))
    base_reply = (
        f"{role}@{agent_scope} sees {context['active_line']}; {context['status_line']}."
        f" Queue: {context['queue_line']}. {context['treasury_note']}; {context['risk_line']}."
    )
    payload = {
        "reply_text": base_reply,
        "packets": _packets_for_role(role, context),
        "task_type": "global_review",
        "priority": "medium",
        "queue_action": "none",
    }
    if role == "Master Treasurer":
        payload.update(
            {
                "global_treasury_summary": f"{context['status_line']} | {context['treasury_note']}",
                "reserve_posture": "cautious" if "unknown" in context['treasury_note'] else "steady",
                "allocation_recommendation": "Hold allocations until reserves recover." if "unknown" in context['treasury_note'] else "Allow calculated deployments.",
            }
        )
    elif role == "Risk Officer":
        payload.update(
            {
                "global_risk_summary": context["risk_line"],
                "constraint_warnings": "No new constraints." if context["risk_line"] == "no risk flags" else "Review risk flags immediately.",
                "veto_recommendations": "Hold risky proposals." if context["risk_line"] != "no risk flags" else "Continue with approved plans.",
            }
        )
    elif role == "Master CFO":
        payload.update(
            {
                "global_financial_summary": f"{context['finance_note']}; lifecycle: {context['lifecycle']}",
                "efficiency_notes": "Sustainability notes stable." if "steady" in context["finance_note"] else "Re-examine portfolio efficiency.",
                "sustainability_findings": context["finance_note"],
            }
        )
    elif role == "Master CEO":
        payload.update(
            {
                "executive_summary": f"{context['lifecycle']} across {context['active_line']}",
                "lifecycle_direction": "Hold/new testing" if "unknown" in context['lifecycle'] else "Push forward with the current phase.",
                "ecosystem_recommendation": "Coordinate Selene/Helena before cloning new companies.",
            }
        )
    elif role == "Inspector General":
        payload.update(
            {
                "audit_summary": f"Audit history count: {len(context['audit_history'])}",
                "suspicious_patterns": "Flags present" if context["risk_line"] != "no risk flags" else "No suspicious patterns detected.",
                "integrity_findings": "Integrity holds." if context["risk_line"] == "no risk flags" else "Integrity under watch.",
            }
        )
    elif role == "Constitutional Arbiter":
        payload.update(
            {
                "constitutional_summary": f"{context['policy_note']} | {context['lifecycle']}",
                "authority_findings": "Authorities appear aligned." if "active" in context["active_line"] else "Review authority lines.",
                "ruling_recommendation": "Refer to Justine for disputed lanes.",
            }
        )
    elif role == "Ombudsman / Appeals Officer":
        payload.update(
            {
                "appeals_summary": f"Appeals context from {context['active_line']}",
                "complaint_routing": "Send major issues to Mara/Justine.",
                "fairness_findings": "Fairness posture steady." if context["risk_line"] == "no risk flags" else "Fairness needs review.",
            }
        )
    return payload
