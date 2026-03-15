"""Role definitions and routing helpers shared across the Pam pipeline."""

from __future__ import annotations

from typing import Dict, List, Tuple

TASK_TYPES: List[Tuple[str, str, str]] = [
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
    ("lifecycle", "lifecycle_action", "Master CEO"),
    ("ecosystem", "ecosystem_direction", "Master CEO"),
    ("global direction", "ecosystem_direction", "Master CEO"),
    ("master direction", "ecosystem_direction", "Master CEO"),
    ("executive mandate", "ecosystem_direction", "Master CEO"),
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
    ("audit", "oversight_review", "Inspector General"),
    ("oversight", "oversight_review", "Inspector General"),
    ("integrity", "oversight_review", "Inspector General"),
    ("abuse", "oversight_review", "Inspector General"),
    ("scope", "oversight_review", "Inspector General"),
    ("overreach", "oversight_review", "Inspector General"),
    ("watchdog", "oversight_review", "Inspector General"),
    ("complaint", "appeal_triage", "Ombudsman / Appeals Officer"),
    ("appeal", "appeal_triage", "Ombudsman / Appeals Officer"),
    ("fairness", "appeal_triage", "Ombudsman / Appeals Officer"),
    ("grievance", "appeal_triage", "Ombudsman / Appeals Officer"),
    ("procedural", "appeal_triage", "Ombudsman / Appeals Officer"),
    ("constitutional", "constitutional_review", "Constitutional Arbiter"),
    ("arbiter", "constitutional_review", "Constitutional Arbiter"),
    ("authority", "constitutional_review", "Constitutional Arbiter"),
    ("dispute", "constitutional_review", "Constitutional Arbiter"),
    ("constitutional law", "constitutional_review", "Constitutional Arbiter"),
]

ALLOWED_RECIPIENTS: List[str] = sorted({entry[2] for entry in TASK_TYPES})

ROLE_SPECS: Dict[str, str] = {
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
    "Inspector General": (
        "Mara is the Inspector General. She audits the whole organization, flags abuse, scope drift, and suspicious loops, and escalates integrity findings without acting as an executive."
    ),
    "Constitutional Arbiter": (
        "Justine is the Constitutional Arbiter. She interprets the constitution, resolves authority disputes, and rules on scope compliance without running the system."
    ),
    "Ombudsman / Appeals Officer": (
        "Owen is the Ombudsman / Appeals Officer. He receives appeals, cares for fairness, and routes complaints to Mara, Justine, or Jacob without ruling them himself."
    ),
    "Master CEO": (
        "Yam Yam is the Master CEO. She defines ecosystem-level strategy, lifecycle direction, and branch coordination without overriding constitutional limits."
    ),
    "Low Tier Operations Worker": (
        "Bob is the low-tier operations worker who handles safe, repetitive chores and reports plainly."
    ),
}

ROLE_STRUCTURED_OUTPUT: Dict[str, Dict[str, Any]] = {
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
    "Constitutional Arbiter": {
        "required_keys": ["reply_text", "constitutional_ruling", "authority_interpretation", "branch_balance_decision", "scope_validity", "dispute_summary", "recommendation", "packets"],
        "default_queue_action": "none",
        "description": "Return constitutional rulings, authority interpretations, and dispute packets for the oversight council."
    },
    "Inspector General": {
        "required_keys": ["reply_text", "audit_summary", "integrity_warning", "branch_overreach_warning", "suspicious_pattern_alert", "compliance_concern", "recommendation", "packets"],
        "default_queue_action": "none",
        "description": "Return audit packets, integrity warnings, suspicious-pattern alerts, and compliance concerns for oversight recipients."
    },
    "Ombudsman / Appeals Officer": {
        "required_keys": ["reply_text", "appeal_intake_summary", "complaint_triage_decision", "fairness_summary", "procedural_guidance", "recommendation", "packets"],
        "default_queue_action": "none",
        "description": "Return appeal intake summaries, fairness notes, and routing packets for the oversight council."
    },
    "Master CEO": {
        "required_keys": ["reply_text", "executive_summary", "ecosystem_direction", "lifecycle_decision", "branch_coordination_directive", "strategic_recommendation", "request_more_evidence", "packets"],
        "default_queue_action": "none",
        "description": "Return ecosystem executive direction, lifecycle calls, and branch coordination packets without bypassing constitutional lanes."
    },
    "Low Tier Operations Worker": {
        "required_keys": ["reply_text", "op_summary", "artifacts", "status", "packets"],
        "default_queue_action": "none",
        "description": "Bob handles safe operational chores."
    }
}
