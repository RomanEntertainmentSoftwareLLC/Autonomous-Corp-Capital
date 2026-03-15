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
