"""Shared runtime helpers for agent-style prompts."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "agents.yaml"
STATE_ROOT = ROOT / "state" / "agents"
UNIVERSAL_PERSONA_PATH = ROOT / "personas" / "universal.json"
AGENT_PERSONA_DIR = ROOT / "personas" / "agents"
COMPANIES_DIR = ROOT / "companies"
TREASURY_PATH = ROOT / "state" / "treasury.yaml"
DEFAULT_QUEUE = {
    "new": [],
    "assigned": [],
    "in_progress": [],
    "blocked": [],
    "completed": [],
    "escalated": [],
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
        cleaned_value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), cleaned_value)


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


def read_agent_outbox_reports(agent_prefix: str, target_scope: str, limit: int = 3) -> List[Dict[str, Any]]:
    path = STATE_ROOT / f"{agent_prefix}_{target_scope}" / "outbox.jsonl"
    if not path.exists():
        return []
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    reports: List[Dict[str, Any]] = []
    for raw in lines[-limit:]:
        try:
            entry = json.loads(raw)
        except Exception:
            continue
        response = entry.get("response", {})
        report: Dict[str, Any] = {
            "timestamp": entry.get("timestamp"),
            "task_type": response.get("task_type"),
            "priority": response.get("priority"),
            "summary": response.get("summary"),
            "reply_text": response.get("reply_text"),
            "analysis_summary": response.get("analysis_summary"),
            "recommendation": response.get("recommendation"),
            "research_summary": response.get("research_summary"),
            "ideas": response.get("ideas"),
            "hypotheses": response.get("hypotheses"),
            "evidence": response.get("evidence"),
            "missing_data": response.get("missing_data"),
            "suggested_followup": response.get("suggested_followup"),
        }
        report = {k: v for k, v in report.items() if v}
        if report:
            reports.append(report)
    return reports


def collect_agent_reports(target_scope: str) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "Pam": read_agent_outbox_reports("pam", target_scope),
        "Iris": read_agent_outbox_reports("iris", target_scope),
        "Vera": read_agent_outbox_reports("vera", target_scope),
        "Rowan": read_agent_outbox_reports("rowan", target_scope),
        "Bianca": read_agent_outbox_reports("bianca", target_scope),
        "Bob": read_agent_outbox_reports("bob", target_scope),
        "Sloane": read_agent_outbox_reports("sloane", target_scope),
        "Atlas": read_agent_outbox_reports("atlas", target_scope),
        "Lucian": read_agent_outbox_reports("lucian", target_scope),
        "June": read_agent_outbox_reports("june", target_scope),
    }


def detect_target_scope(message: str, default: str) -> str:
    lowered = message.lower()
    match = re.search(r"(company_\d+)", lowered)
    return match.group(1) if match else default


def gather_company_insights(scope: str, target_scope: str, queue: Dict[str, Any] | None = None) -> Dict[str, Any]:
    insights: Dict[str, Any] = {"scope": scope, "target_scope": target_scope}
    comp_dir = COMPANIES_DIR / target_scope
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
    manager_action = None
    for action in manager_actions.get("actions", []):
        if action.get("company") == target_scope:
            manager_action = action
            break
    insights["manager_action"] = manager_action
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
    queue_snapshot = queue or {}
    insights["queue_entries"] = queue_snapshot
    insights["allocation"] = {
        "amount": metadata.get("allocation_amount"),
        "percent": metadata.get("allocation_percent"),
        "status": metadata.get("allocation_status"),
    }
    capital_usage = {
        "allocated": metadata.get("allocation_amount"),
    }
    if manager_action and manager_action.get("account_value") is not None:
        capital_usage["manager_account_value"] = manager_action.get("account_value")
    insights["capital_usage"] = capital_usage
    insights["budget_posture"] = metadata.get("allocation_status") or "unknown"
    treasury_path = ROOT / "state" / "treasury.yaml"
    insights["treasury_snapshot"] = load_yaml_file(treasury_path)
    insights["agent_reports"] = collect_agent_reports(target_scope)
    file_checks = {
        "trade_logs": [],
        "result_logs": [],
    }
    for pattern in ("trade*.jsonl", "trade_log*.jsonl"):
        for path in comp_dir.rglob(pattern):
            if path.is_file():
                file_checks["trade_logs"].append(str(path))
    results_dir = ROOT / "results" / target_scope
    if results_dir.exists():
        for path in results_dir.rglob("*.jsonl"):
            if path.is_file():
                file_checks["result_logs"].append(str(path))
    insights["file_checks"] = file_checks
    return insights


def gather_global_treasury_insights() -> Dict[str, Any]:
    treasury_snapshot = load_yaml_file(TREASURY_PATH)
    companies: List[Dict[str, Any]] = []
    for comp_dir in sorted(COMPANIES_DIR.iterdir()):
        if not comp_dir.is_dir():
            continue
        metadata = load_yaml_file(comp_dir / "metadata.yaml")
        if not metadata:
            continue
        cfo_reports = read_agent_outbox_reports("bianca", comp_dir.name)
        lucian_reports = read_agent_outbox_reports("lucian", comp_dir.name)
        latest_cfo = cfo_reports[-1] if cfo_reports else {}
        latest_lucian = lucian_reports[-1] if lucian_reports else {}
        companies.append({
            "company_id": comp_dir.name,
            "lifecycle": metadata.get("lifecycle_state", "unknown"),
            "allocation_percent": metadata.get("allocation_percent"),
            "allocation_status": metadata.get("allocation_status"),
            "cfo_posture": latest_cfo.get("spending_posture"),
            "cfo_summary": latest_cfo.get("financial_health_summary", latest_cfo.get("cash_runway_caution")),
            "ceo_decision": latest_lucian.get("decision"),
            "ceo_summary": latest_lucian.get("executive_summary"),
        })
    return {
        "treasury_snapshot": treasury_snapshot,
        "companies": companies,
        "active_company_count": len(companies),
        "allocation_summary": [c.get("allocation_percent") for c in companies if c.get("allocation_percent") is not None],
    }


def gather_global_risk_insights() -> Dict[str, Any]:
    treasury = gather_global_treasury_insights()
    escalations: List[Dict[str, Any]] = []
    for agent_dir in STATE_ROOT.iterdir():
        if not agent_dir.is_dir():
            continue
        log_path = agent_dir / "escalations.jsonl"
        if not log_path.exists():
            continue
        for line in log_path.read_text().splitlines():
            try:
                entry = json.loads(line)
            except Exception:
                continue
            escalations.append({"agent": agent_dir.name, "entry": entry})
    risk_flags = [c for c in treasury.get("companies", []) if c.get("lifecycle") in ("danger", "retired")]
    return {
        "treasury": treasury.get("treasury_snapshot", {}),
        "companies": treasury.get("companies", []),
        "escalations": escalations,
        "risk_flags": risk_flags,
    }



def gather_global_finance_insights() -> Dict[str, Any]:
    treasury = gather_global_treasury_insights()
    companies = []
    for comp in treasury.get("companies", []):
        efficiency = None
        if comp.get("allocation_percent") not in (None, "unknown"):
            efficiency = float(comp.get("allocation_percent"))
        companies.append({
            "company_id": comp.get("company_id"),
            "lifecycle": comp.get("lifecycle"),
            "allocation_percent": efficiency,
            "cfo_posture": comp.get("cfo_posture"),
            "cfo_summary": comp.get("cfo_summary"),
            "ceo_summary": comp.get("ceo_summary"),
        })
    inefficiencies = [c for c in companies if c.get("allocation_percent") and c.get("allocation_percent") < 20]
    sustainability = "fragile" if any(c.get("lifecycle") == "at_risk" for c in companies) else "stable"
    return {
        "treasury_snapshot": treasury.get("treasury_snapshot", {}),
        "companies": companies,
        "inefficiencies": inefficiencies,
        "sustainability": sustainability,
    }

