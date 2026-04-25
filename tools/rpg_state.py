"""Shared RPG state helpers.

This module keeps the smallest trustworthy core needed for the RPG layer:
- load/save per-agent state
- update XP and derived level
- derive intelligence from evidence-backed metrics

It intentionally does not wire runtime events or scoring triggers.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - older Python fallback
    ZoneInfo = None  # type: ignore

RPG_STATE_FIELDS = [
    "xp",
    "level",
    "title",
    "sessions",
    "current_level_threshold",
    "next_level_threshold",
    "xp_to_next_level",
    "speed",
    "accuracy",
    "reliability",
    "judgment",
    "consistency",
    "usefulness",
    "cost_efficiency",
    "evidence_quality",
    "duplication_penalty",
    "waste_penalty",
    "fake_productivity_penalty",
    "intelligence",
]

_NUMERIC_INT_FIELDS = {
    "level",
    "sessions",
    "current_level_threshold",
    "next_level_threshold",
    "xp_to_next_level",
}

_FIELD_ALIASES = {
    "xp": "xp",
    "total xp": "xp",
    "level": "level",
    "title": "title",
    "sessions": "sessions",
    "current_level_threshold": "current_level_threshold",
    "current level threshold": "current_level_threshold",
    "next_level_threshold": "next_level_threshold",
    "next level threshold": "next_level_threshold",
    "xp_to_next_level": "xp_to_next_level",
    "xp to next level": "xp_to_next_level",
    "speed": "speed",
    "accuracy": "accuracy",
    "reliability": "reliability",
    "judgment": "judgment",
    "consistency": "consistency",
    "usefulness": "usefulness",
    "cost_efficiency": "cost_efficiency",
    "cost efficiency": "cost_efficiency",
    "evidence_quality": "evidence_quality",
    "evidence quality": "evidence_quality",
    "duplication_penalty": "duplication_penalty",
    "duplication penalty": "duplication_penalty",
    "waste_penalty": "waste_penalty",
    "waste penalty": "waste_penalty",
    "fake_productivity_penalty": "fake_productivity_penalty",
    "fake productivity penalty": "fake_productivity_penalty",
    "intelligence": "intelligence",
}

# Tuned to keep the score grounded in useful, evidence-backed work.
_INTELLIGENCE_WEIGHTS = {
    "accuracy": 0.18,
    "reliability": 0.10,
    "judgment": 0.10,
    "consistency": 0.14,
    "usefulness": 0.14,
    "cost_efficiency": 0.10,
    "evidence_quality": 0.16,
    "speed": 0.08,
}
_PENALTY_WEIGHTS = {
    "duplication_penalty": 0.15,
    "waste_penalty": 0.15,
    "fake_productivity_penalty": 0.20,
}

# One narrow evidence path only: verified completion reports with a final PASS verdict.
_VERIFIED_REPORT_COMPLETION_XP_AWARD = 10.0
_VERIFIED_REPORT_COMPLETION_EVIDENCE_QUALITY_BONUS = 5.0
_MINA_TEST_REPORT_EVIDENCE_MARKERS = (
    "pytest",
    "test_live_runtime_audit",
    "tests/test_live_runtime_audit.py",
)
_MINA_TEST_REPORT_EVIDENCE_QUALITY_BONUS = 3.0
_MINA_TEST_REPORT_FAILURE_PENALTY = 5.0


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)



def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)



def _normalize_score(value: Any) -> float:
    score = _coerce_float(value, 0.0)
    if abs(score) <= 1.0:
        score *= 100.0
    return max(0.0, min(100.0, score))



def xp_to_next_level(level: int) -> int:
    level = max(1, int(level or 1))
    return 100 + 50 * (level - 1)



def current_level_threshold(level: int) -> int:
    level = max(1, int(level or 1))
    cumulative = 0
    for prior_level in range(1, level):
        cumulative += xp_to_next_level(prior_level)
    return cumulative



def level_from_xp(xp: Any) -> int:
    total_xp = max(0, int(round(_coerce_float(xp, 0.0))))
    level = 1
    cumulative = 0
    while total_xp >= cumulative + xp_to_next_level(level):
        cumulative += xp_to_next_level(level)
        level += 1
    return level



def derive_intelligence(state: Dict[str, Any]) -> float:
    positive = 0.0
    for field, weight in _INTELLIGENCE_WEIGHTS.items():
        positive += _normalize_score(state.get(field)) * weight

    penalty = 0.0
    for field, weight in _PENALTY_WEIGHTS.items():
        penalty += _normalize_score(state.get(field)) * weight

    intelligence = positive - penalty
    return round(max(0.0, min(100.0, intelligence)), 2)



def default_rpg_state() -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "xp": 0.0,
        "level": 1,
        "title": "Initiate",
        "sessions": 0,
        "current_level_threshold": 0,
        "next_level_threshold": xp_to_next_level(1),
        "xp_to_next_level": xp_to_next_level(1),
        "speed": 0.0,
        "accuracy": 0.0,
        "reliability": 0.0,
        "judgment": 0.0,
        "consistency": 0.0,
        "usefulness": 0.0,
        "cost_efficiency": 0.0,
        "evidence_quality": 0.0,
        "duplication_penalty": 0.0,
        "waste_penalty": 0.0,
        "fake_productivity_penalty": 0.0,
    }
    state["intelligence"] = derive_intelligence(state)
    return state



def _canonicalize_state(state: Dict[str, Any] | None) -> Dict[str, Any]:
    canonical = default_rpg_state()
    if not state:
        return canonical

    if "title" in state:
        title_text = str(state.get("title", "")).strip()
        canonical["title"] = title_text or canonical["title"]
    if "sessions" in state:
        canonical["sessions"] = max(0, _coerce_int(state.get("sessions"), canonical["sessions"]))

    for key in RPG_STATE_FIELDS:
        if key in {"xp", "level", "title", "sessions", "current_level_threshold", "next_level_threshold", "xp_to_next_level"}:
            continue
        if key in state:
            canonical[key] = _coerce_float(state.get(key), canonical[key])

    canonical["xp"] = max(0.0, _coerce_float(state.get("xp"), 0.0))
    canonical["level"] = level_from_xp(canonical["xp"])
    canonical["current_level_threshold"] = current_level_threshold(canonical["level"])
    canonical["xp_to_next_level"] = xp_to_next_level(canonical["level"])
    canonical["next_level_threshold"] = canonical["current_level_threshold"] + canonical["xp_to_next_level"]
    canonical["intelligence"] = derive_intelligence(canonical)
    return canonical



def load_rpg_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return default_rpg_state()

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return default_rpg_state()

    if raw.startswith("{"):
        try:
            return _canonicalize_state(json.loads(raw))
        except Exception:
            return default_rpg_state()

    parsed: Dict[str, Any] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        parts = [part.strip() for part in stripped.strip("|").split("|")]
        if len(parts) < 2:
            continue
        field_name, value_text = parts[0], parts[1]
        alias = _FIELD_ALIASES.get(field_name.lower())
        if not alias:
            continue
        if alias == "title":
            parsed[alias] = value_text.strip()
        elif alias in _NUMERIC_INT_FIELDS:
            parsed[alias] = _coerce_int(value_text, 0 if alias != "level" else 1)
        else:
            parsed[alias] = _coerce_float(value_text, 0.0)
    return _canonicalize_state(parsed)



def _format_value(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)



def _display_time_et(raw_timestamp: Any = None) -> str:
    """Return a human-readable Eastern Time timestamp for RPG history logs."""
    dt: datetime
    raw = str(raw_timestamp or "").strip()
    if raw:
        try:
            normalized = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    if ZoneInfo is not None:
        try:
            dt = dt.astimezone(ZoneInfo("America/New_York"))
            return dt.strftime("%Y-%m-%d %I:%M:%S %p %Z")
        except Exception:
            pass
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %I:%M:%S %p UTC")



def _clean_history_reason(reason: Any, fallback: str = "Completed role work.") -> str:
    text = re.sub(r"\s+", " ", str(reason or "").strip())
    return text or fallback



def append_human_rpg_history(
    history_path: Path,
    *,
    timestamp: Any = None,
    agent_id: str = "",
    event_type: str = "RPG Event",
    xp_delta: Any = 0.0,
    before_xp: Any = None,
    after_xp: Any = None,
    before_level: Any = None,
    after_level: Any = None,
    reason: Any = "",
    context: Any = "",
) -> None:
    """Append a human-readable RPG event line.

    This is intentionally Markdown text, not JSON. It is the agent's career/combat log:
    what happened, why it mattered, and how XP changed.
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if not history_path.exists():
        history_path.write_text("# RPG History\n\n", encoding="utf-8")

    xp_number = round(_coerce_float(xp_delta, 0.0), 2)
    xp_text = _format_value(xp_number)
    sign = "+" if xp_number >= 0 else ""
    time_text = _display_time_et(timestamp)
    reason_text = _clean_history_reason(reason)
    context_text = _clean_history_reason(context, "")

    parts = [f"{time_text} | {sign}{xp_text} XP | {event_type}"]
    if agent_id:
        parts.append(f"Agent: {agent_id}")
    if before_xp is not None and after_xp is not None:
        before_text = _format_value(round(_coerce_float(before_xp), 2))
        after_text = _format_value(round(_coerce_float(after_xp), 2))
        parts.append(f"XP {before_text} -> {after_text}")
    if before_level is not None and after_level is not None:
        level_note = f"Level {_format_value(before_level)} -> {_format_value(after_level)}"
        if _coerce_int(before_level, 1) != _coerce_int(after_level, 1):
            level_note += " | LEVEL UP"
        parts.append(level_note)
    if context_text:
        parts.append(context_text)
    parts.append(reason_text)

    with history_path.open("a", encoding="utf-8") as handle:
        handle.write("- " + " | ".join(parts) + "\n")



def save_rpg_state(path: Path, state: Dict[str, Any]) -> Dict[str, Any]:
    canonical = _canonicalize_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# RPG State", "", "| Field | Value |", "|-------|-------|"]
    for field in RPG_STATE_FIELDS:
        lines.append(f"| {field} | {_format_value(canonical.get(field, 0))} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return canonical



def migrate_rpg_state_file(path: Path) -> Dict[str, Any]:
    """Rewrite a legacy RPG_STATE.md file into the blended canonical schema."""
    canonical = load_rpg_state(path)
    return save_rpg_state(path, canonical)



def update_xp(state: Dict[str, Any], delta_xp: Any) -> Dict[str, Any]:
    canonical = _canonicalize_state(state)
    canonical["xp"] = max(0.0, canonical["xp"] + _coerce_float(delta_xp, 0.0))
    canonical["level"] = level_from_xp(canonical["xp"])
    canonical["current_level_threshold"] = current_level_threshold(canonical["level"])
    canonical["xp_to_next_level"] = xp_to_next_level(canonical["level"])
    canonical["next_level_threshold"] = canonical["current_level_threshold"] + canonical["xp_to_next_level"]
    canonical["intelligence"] = derive_intelligence(canonical)
    return canonical


def _extract_pass_fail_section(report_text: str) -> str:
    match = re.search(
        r"(?ims)^\s*(?:\d+\.\s*)?(?:FINAL\s+)?PASS/FAIL\s*$\n(?P<body>.*?)(?:^\s*\d+\.\s|\Z)",
        report_text,
    )
    if not match:
        return ""
    return match.group("body").strip()


def is_verified_report_completion(report_path: Path) -> bool:
    if report_path.suffix.lower() != ".txt":
        return False
    if not report_path.name.startswith("yam_step"):
        return False
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except OSError:
        return False

    body = _extract_pass_fail_section(report_text)
    if not body:
        return False

    lines = [line.strip().upper() for line in body.splitlines() if line.strip()]
    has_pass = any(line.startswith("PASS") or line.startswith("- PASS") for line in lines)
    has_fail = any(line.startswith("FAIL") or line.startswith("- FAIL") for line in lines)
    return has_pass and not has_fail


def score_verified_report_completion(state: Dict[str, Any], report_path: Path) -> Dict[str, Any]:
    canonical = _canonicalize_state(state)
    if not is_verified_report_completion(report_path):
        return canonical

    canonical["xp"] = max(0.0, canonical["xp"] + _VERIFIED_REPORT_COMPLETION_XP_AWARD)
    canonical["evidence_quality"] = min(
        100.0,
        canonical["evidence_quality"] + _VERIFIED_REPORT_COMPLETION_EVIDENCE_QUALITY_BONUS,
    )
    canonical["level"] = level_from_xp(canonical["xp"])
    canonical["current_level_threshold"] = current_level_threshold(canonical["level"])
    canonical["xp_to_next_level"] = xp_to_next_level(canonical["level"])
    canonical["next_level_threshold"] = canonical["current_level_threshold"] + canonical["xp_to_next_level"]
    canonical["intelligence"] = derive_intelligence(canonical)
    return canonical


def score_mina_verified_test_report_completion(state: Dict[str, Any], report_path: Path) -> Dict[str, Any]:
    canonical = _canonicalize_state(state)
    if get_role_scorecard("Mina")["role"] != "mina":
        return canonical

    try:
        report_text = report_path.read_text(encoding="utf-8")
    except OSError:
        return canonical

    report_text_lower = report_text.lower()
    has_test_evidence = any(marker in report_text_lower for marker in _MINA_TEST_REPORT_EVIDENCE_MARKERS)
    if not has_test_evidence:
        return canonical

    if is_verified_report_completion(report_path):
        canonical = score_verified_report_completion(canonical, report_path)
        canonical["evidence_quality"] = min(
            100.0,
            canonical["evidence_quality"] + _MINA_TEST_REPORT_EVIDENCE_QUALITY_BONUS,
        )
        canonical["intelligence"] = derive_intelligence(canonical)
        return canonical

    body = _extract_pass_fail_section(report_text)
    lines = [line.strip().upper() for line in body.splitlines() if line.strip()]
    has_fail = any(line.startswith("FAIL") or line.startswith("- FAIL") for line in lines) or "FAIL / BLOCKED" in report_text.upper()
    if has_fail:
        canonical["waste_penalty"] = min(100.0, canonical["waste_penalty"] + _MINA_TEST_REPORT_FAILURE_PENALTY)
        canonical["fake_productivity_penalty"] = min(
            100.0,
            canonical["fake_productivity_penalty"] + _MINA_TEST_REPORT_FAILURE_PENALTY,
        )
        canonical["intelligence"] = derive_intelligence(canonical)
    return canonical


_PAM_RUNTIME_PACKET_ROUTING_XP_AWARD = 6.0
_PAM_RUNTIME_PACKET_ROUTING_EVIDENCE_QUALITY_BONUS = 4.0
_PAM_RUNTIME_PACKET_ROUTING_MISSING_CONSULTATION_PENALTY = 2.0


def _load_runtime_evidence_records(evidence_path: Path) -> list[Dict[str, Any]]:
    try:
        raw = evidence_path.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not raw:
        return []

    parsed: Any
    if raw.startswith("{") or raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            if isinstance(parsed.get("top_company_activity"), list):
                return [row for row in parsed["top_company_activity"] if isinstance(row, dict)]
            return [parsed]
        if isinstance(parsed, list):
            return [row for row in parsed if isinstance(row, dict)]

    records: list[Dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except Exception:
            continue
        if isinstance(row, dict):
            records.append(row)
    return records


def score_pam_runtime_packet_routing_completion(state: Dict[str, Any], evidence_path: Path) -> Dict[str, Any]:
    canonical = _canonicalize_state(state)
    if get_role_scorecard("Pam")["role"] != "pam":
        return canonical

    records = _load_runtime_evidence_records(evidence_path)
    if not records:
        return canonical

    pam_consultations = 0
    routing_gaps = 0
    for record in records:
        consulted = [str(agent).strip() for agent in (record.get("source_agents_consulted") or []) if str(agent).strip()]
        if "Pam" in consulted:
            pam_consultations += 1
        packet_mode = str(record.get("packet_generation_mode") or "").strip().lower()
        fallback_reason = str(record.get("fallback_reason") or record.get("reason") or "").strip().lower()
        if (packet_mode in {"fallback", "cached_committee_reuse"} or fallback_reason.startswith("no_actionable") or fallback_reason.startswith("reused_recent_committee_packet")) and "Pam" not in consulted:
            routing_gaps += 1

    if pam_consultations:
        canonical["xp"] = max(0.0, canonical["xp"] + min(_PAM_RUNTIME_PACKET_ROUTING_XP_AWARD, float(pam_consultations) * _PAM_RUNTIME_PACKET_ROUTING_XP_AWARD))
        canonical["usefulness"] = min(100.0, canonical["usefulness"] + _PAM_RUNTIME_PACKET_ROUTING_EVIDENCE_QUALITY_BONUS)
        canonical["consistency"] = min(100.0, canonical["consistency"] + 2.0)
        canonical["evidence_quality"] = min(100.0, canonical["evidence_quality"] + _PAM_RUNTIME_PACKET_ROUTING_EVIDENCE_QUALITY_BONUS)

    if routing_gaps:
        canonical["waste_penalty"] = min(100.0, canonical["waste_penalty"] + float(routing_gaps) * _PAM_RUNTIME_PACKET_ROUTING_MISSING_CONSULTATION_PENALTY)
        canonical["duplication_penalty"] = min(100.0, canonical["duplication_penalty"] + float(routing_gaps) * 1.0)

    if pam_consultations or routing_gaps:
        canonical["intelligence"] = derive_intelligence(canonical)
    return canonical


_LUCIAN_LIVE_COMMITTEE_DIRECTION_XP_AWARD = 8.0
_LUCIAN_LIVE_COMMITTEE_DIRECTION_JUDGMENT_BONUS = 3.0
_LUCIAN_LIVE_COMMITTEE_DIRECTION_CONSISTENCY_BONUS = 2.0
_LUCIAN_LIVE_COMMITTEE_DIRECTION_USEFULNESS_BONUS = 2.0
_LUCIAN_LIVE_COMMITTEE_DIRECTION_EVIDENCE_QUALITY_BONUS = 4.0
_LUCIAN_LIVE_COMMITTEE_DIRECTION_FALLBACK_PENALTY = 4.0


def score_lucian_live_committee_direction_completion(state: Dict[str, Any], evidence_path: Path) -> Dict[str, Any]:
    canonical = _canonicalize_state(state)
    if get_role_scorecard("Lucian")["role"] != "lucian":
        return canonical

    records = _load_runtime_evidence_records(evidence_path)
    if not records:
        return canonical

    live_direction_count = 0
    fallback_count = 0
    for record in records:
        committee_sources = record.get("committee_sources") or {}
        lucian_meta = committee_sources.get("Lucian") or {}
        consulted = [str(agent).strip() for agent in (record.get("source_agents_consulted") or []) if str(agent).strip()]
        packet_mode = str(record.get("packet_generation_mode") or "").strip().lower()
        summary = str(lucian_meta.get("summary") or "").strip()
        if packet_mode == "live_committee_sessions" and lucian_meta.get("mode") == "live_session" and "Lucian" in consulted and summary and "|" in summary:
            live_direction_count += 1
        if packet_mode in {"fallback", "cached_committee_reuse"} or lucian_meta.get("mode") != "live_session":
            fallback_count += 1

    if live_direction_count:
        canonical["xp"] = max(0.0, canonical["xp"] + min(_LUCIAN_LIVE_COMMITTEE_DIRECTION_XP_AWARD, float(live_direction_count) * _LUCIAN_LIVE_COMMITTEE_DIRECTION_XP_AWARD))
        canonical["judgment"] = min(100.0, canonical["judgment"] + _LUCIAN_LIVE_COMMITTEE_DIRECTION_JUDGMENT_BONUS)
        canonical["consistency"] = min(100.0, canonical["consistency"] + _LUCIAN_LIVE_COMMITTEE_DIRECTION_CONSISTENCY_BONUS)
        canonical["usefulness"] = min(100.0, canonical["usefulness"] + _LUCIAN_LIVE_COMMITTEE_DIRECTION_USEFULNESS_BONUS)
        canonical["evidence_quality"] = min(100.0, canonical["evidence_quality"] + _LUCIAN_LIVE_COMMITTEE_DIRECTION_EVIDENCE_QUALITY_BONUS)

    if fallback_count:
        canonical["waste_penalty"] = min(100.0, canonical["waste_penalty"] + float(fallback_count) * _LUCIAN_LIVE_COMMITTEE_DIRECTION_FALLBACK_PENALTY)
        canonical["duplication_penalty"] = min(100.0, canonical["duplication_penalty"] + float(fallback_count) * 2.0)

    if live_direction_count or fallback_count:
        canonical["intelligence"] = derive_intelligence(canonical)
    return canonical


def score_lucian_runtime_packet_direction_completion(state: Dict[str, Any], evidence_path: Path) -> Dict[str, Any]:
    return score_lucian_live_committee_direction_completion(state, evidence_path)


_ROWAN_RESEARCH_COMPLETION_XP_AWARD = 5.0
_ROWAN_RESEARCH_COMPLETION_EVIDENCE_QUALITY_BONUS = 3.0
_ROWAN_RESEARCH_COMPLETION_USEFULNESS_BONUS = 2.0
_ROWAN_RESEARCH_BLOCKED_PENALTY = 3.0


def score_rowan_research_completion(state: Dict[str, Any], evidence_path: Path) -> Dict[str, Any]:
    canonical = _canonicalize_state(state)
    if get_role_scorecard("Rowan")["role"] != "rowan":
        return canonical

    records = _load_runtime_evidence_records(evidence_path)
    if not records:
        return canonical

    completed_research = 0
    blocked_reports = 0
    for record in records:
        response = record.get("response") if isinstance(record.get("response"), dict) else record
        if not isinstance(response, dict):
            continue

        role = str(response.get("role") or response.get("to") or "").strip().lower()
        task_type = str(response.get("task_type") or "").strip().lower()
        status = str(response.get("status") or "").strip().lower()
        if role not in {"researcher", "rowan"} and task_type not in {"research", "bridge_failure"}:
            continue

        if task_type == "bridge_failure" or status == "blocked":
            blocked_reports += 1
            continue

        research_summary = str(response.get("research_summary") or "").strip()
        ideas = [str(item).strip() for item in (response.get("ideas") or []) if str(item).strip()]
        hypotheses = [str(item).strip() for item in (response.get("hypotheses") or []) if str(item).strip()]
        evidence = [str(item).strip() for item in (response.get("evidence") or []) if str(item).strip()]
        if research_summary and ideas and hypotheses and evidence:
            completed_research += 1

    if completed_research:
        canonical["xp"] = max(0.0, canonical["xp"] + float(completed_research) * _ROWAN_RESEARCH_COMPLETION_XP_AWARD)
        canonical["usefulness"] = min(100.0, canonical["usefulness"] + _ROWAN_RESEARCH_COMPLETION_USEFULNESS_BONUS)
        canonical["evidence_quality"] = min(
            100.0,
            canonical["evidence_quality"] + _ROWAN_RESEARCH_COMPLETION_EVIDENCE_QUALITY_BONUS,
        )
        canonical["accuracy"] = min(100.0, canonical["accuracy"] + 1.0)

    if blocked_reports:
        canonical["waste_penalty"] = min(100.0, canonical["waste_penalty"] + float(blocked_reports) * _ROWAN_RESEARCH_BLOCKED_PENALTY)
        canonical["fake_productivity_penalty"] = min(
            100.0,
            canonical["fake_productivity_penalty"] + float(blocked_reports) * _ROWAN_RESEARCH_BLOCKED_PENALTY,
        )

    if completed_research or blocked_reports:
        canonical["intelligence"] = derive_intelligence(canonical)
    return canonical


def score_rowan_research_report_completion(state: Dict[str, Any], evidence_path: Path) -> Dict[str, Any]:
    return score_rowan_research_completion(state, evidence_path)


def format_rpg_identity_line(
    state: Dict[str, Any],
    agent_name: Any = None,
    organization_name: str = "Autonomous Corp Capital",
    include_stat_note: bool = False,
) -> str:
    canonical = _canonicalize_state(state)
    label = str(agent_name).strip() if isinstance(agent_name, str) and str(agent_name).strip() else "RPG agent"
    identity = f"I’m {label}, a Level {int(canonical['level'])} {canonical['title']} of {organization_name}."
    if not include_stat_note:
        return identity
    stat_note = f"Stat note: intelligence {_format_value(canonical['intelligence'])} | evidence quality {_format_value(canonical['evidence_quality'])}."
    return f"{identity}\n{stat_note}"


def format_rpg_summary(state: Dict[str, Any], agent_name: Any = None) -> str:
    canonical = _canonicalize_state(state)
    label = str(agent_name).strip() if isinstance(agent_name, str) and str(agent_name).strip() else "RPG agent"
    penalty_total = sum(
        _normalize_score(canonical.get(field))
        for field in ("duplication_penalty", "waste_penalty", "fake_productivity_penalty")
    )
    lines = [
        f"RPG summary for {label}",
        f"Title: {canonical['title']} | Sessions: {int(canonical['sessions'])}",
        f"Level: {int(canonical['level'])} | XP: {_format_value(canonical['xp'])}",
        f"Thresholds: current {_format_value(canonical['current_level_threshold'])} | next {_format_value(canonical['next_level_threshold'])} | to next {_format_value(canonical['xp_to_next_level'])}",
        f"Intelligence: {_format_value(canonical['intelligence'])}",
        f"Accuracy: {_format_value(canonical['accuracy'])} | Reliability: {_format_value(canonical['reliability'])} | Judgment: {_format_value(canonical['judgment'])}",
        f"Consistency: {_format_value(canonical['consistency'])} | Usefulness: {_format_value(canonical['usefulness'])} | Cost efficiency: {_format_value(canonical['cost_efficiency'])}",
        f"Speed: {_format_value(canonical['speed'])} | Evidence quality: {_format_value(canonical['evidence_quality'])}",
        f"Penalties: duplication {_format_value(canonical['duplication_penalty'])} | waste {_format_value(canonical['waste_penalty'])} | fake productivity {_format_value(canonical['fake_productivity_penalty'])} | total {_format_value(round(penalty_total, 2))}",
    ]
    return "\n".join(lines)


_ROLE_SCORECARD_ALIASES = {
    "pam": "pam",
    "administrative_coordinator": "pam",
    "coordinator": "pam",
    "iris": "iris",
    "analyst": "iris",
    "rowan": "rowan",
    "researcher": "rowan",
    "bianca": "bianca",
    "cfo": "bianca",
    "lucian": "lucian",
    "ceo": "lucian",
    "mina": "mina",
    "tester": "mina",
}

_ROLE_SCORECARDS = {
    "pam": {
        "primary_win_conditions": [
            "requests land in the right inboxes",
            "packets are routed cleanly",
            "task queues stay organized",
            "summaries are clear and faithful",
        ],
        "main_penalty_risks": [
            "misrouted packets",
            "duplicated inbox handling",
            "vague summaries",
            "unnecessary queue churn",
        ],
        "top_stats_to_improve": ["usefulness", "consistency", "speed", "evidence_quality"],
    },
    "iris": {
        "primary_win_conditions": [
            "missing evidence is flagged early",
            "discrepancies are identified",
            "diagnostic notes are specific",
            "the evidence trail stays usable",
        ],
        "main_penalty_risks": [
            "missed discrepancies",
            "shallow evidence checks",
            "overconfident conclusions without support",
            "repeated false alarms",
        ],
        "top_stats_to_improve": ["accuracy", "evidence_quality", "consistency", "usefulness"],
    },
    "rowan": {
        "primary_win_conditions": [
            "hypotheses are testable",
            "research questions are sharp",
            "experiments have enough detail to run",
            "blind spots are reduced",
        ],
        "main_penalty_risks": [
            "speculative work with no testable shape",
            "research churn without a question",
            "repeated ideas without evidence",
            "ungrounded brainstorming",
        ],
        "top_stats_to_improve": ["usefulness", "evidence_quality", "accuracy", "speed"],
    },
    "bianca": {
        "primary_win_conditions": [
            "spend posture stays disciplined",
            "runway is protected",
            "reckless burn is rejected",
            "decisions reflect actual financial constraints",
        ],
        "main_penalty_risks": [
            "wasteful spend",
            "ignored runway risk",
            "approval of reckless burn",
            "finance language without actual constraint analysis",
        ],
        "top_stats_to_improve": ["cost_efficiency", "usefulness", "evidence_quality", "consistency"],
    },
    "lucian": {
        "primary_win_conditions": [
            "company decisions are coherent",
            "inputs are composed into executive direction",
            "blockers are resolved cleanly",
            "execution stays aligned",
        ],
        "main_penalty_risks": [
            "contradictory directives",
            "decisions that ignore inputs",
            "premature executive closure",
            "coordination that produces churn instead of clarity",
        ],
        "top_stats_to_improve": ["judgment", "consistency", "usefulness", "reliability"],
    },
    "mina": {
        "primary_win_conditions": [
            "tests are run against shared systems",
            "coverage is real",
            "regressions are caught",
            "QA artifacts are trustworthy",
        ],
        "main_penalty_risks": [
            "shallow test claims",
            "missing coverage",
            "false sign-off",
            "repeated test noise that does not improve confidence",
        ],
        "top_stats_to_improve": ["accuracy", "reliability", "evidence_quality", "consistency"],
    },
}


def get_role_scorecard(role_or_agent: Any) -> Dict[str, Any]:
    if isinstance(role_or_agent, dict):
        candidates = [
            role_or_agent.get("role"),
            role_or_agent.get("agent"),
            role_or_agent.get("agent_name"),
            role_or_agent.get("name"),
            role_or_agent.get("title"),
            role_or_agent.get("recipient"),
            role_or_agent.get("recipient_name"),
        ]
    else:
        candidates = [role_or_agent]

    for candidate in candidates:
        if candidate is None:
            continue
        normalized = str(candidate).strip().lower().replace(" ", "_")
        normalized = _ROLE_SCORECARD_ALIASES.get(normalized, normalized)
        if normalized in _ROLE_SCORECARDS:
            scorecard = _ROLE_SCORECARDS[normalized]
            return {
                "role": normalized,
                "primary_win_conditions": list(scorecard["primary_win_conditions"]),
                "main_penalty_risks": list(scorecard["main_penalty_risks"]),
                "top_stats_to_improve": list(scorecard["top_stats_to_improve"]),
            }

    return {
        "role": "unknown",
        "primary_win_conditions": [],
        "main_penalty_risks": [],
        "top_stats_to_improve": [],
    }


def format_rpg_motivation_block(state: Dict[str, Any], role_or_agent: Any = None) -> str:
    canonical = _canonicalize_state(state)
    scorecard = get_role_scorecard(role_or_agent)
    label = str(role_or_agent).strip() if isinstance(role_or_agent, str) and str(role_or_agent).strip() else scorecard["role"]
    weakest_stats = sorted(
        [
            (field, _normalize_score(canonical.get(field)))
            for field in ("accuracy", "reliability", "judgment", "consistency", "usefulness", "cost_efficiency", "evidence_quality", "speed")
        ],
        key=lambda item: item[1],
    )[:3]
    penalties = {
        "duplication_penalty": _format_value(canonical["duplication_penalty"]),
        "waste_penalty": _format_value(canonical["waste_penalty"]),
        "fake_productivity_penalty": _format_value(canonical["fake_productivity_penalty"]),
    }
    lines = [
        f"Focus for {label}:",
        f"- Current: level {int(canonical['level'])}, XP {_format_value(canonical['xp'])}, intelligence {_format_value(canonical['intelligence'])}.",
        f"- Role scorecard: {', '.join(scorecard['primary_win_conditions']) if scorecard['primary_win_conditions'] else 'none'}.",
        f"- Improve first: {', '.join(f'{name} {_format_value(value)}' for name, value in weakest_stats)}.",
        f"- Penalty exposure: duplication {penalties['duplication_penalty']}, waste {penalties['waste_penalty']}, fake productivity {penalties['fake_productivity_penalty']}.",
    ]
    if scorecard["main_penalty_risks"]:
        lines.append(f"- Watch for: {', '.join(scorecard['main_penalty_risks'])}.")
    return "\n".join(lines)


def format_rpg_self_awareness_block(state: Dict[str, Any], role_or_agent: Any = None) -> str:
    canonical = _canonicalize_state(state)
    identity_line = format_rpg_identity_line(canonical, role_or_agent)
    summary_line = (
        f"Level {int(canonical['level'])} {canonical['title']} | "
        f"XP {_format_value(canonical['xp'])} | Intelligence {_format_value(canonical['intelligence'])}."
    )
    motivation_block = format_rpg_motivation_block(canonical, role_or_agent)
    improve_line = next(
        (
            line.replace("- Improve first:", "Improve by:", 1).strip()
            for line in motivation_block.splitlines()
            if line.startswith("- Improve first:")
        ),
        "",
    )
    lines = [identity_line, summary_line]
    if improve_line:
        lines.append(improve_line)
    return "\n".join(lines)


def _runtime_rpg_state_path(root: Path, agent_id: str) -> Path:
    return root / "ai_agents_memory" / agent_id / "RPG_STATE.md"


def _runtime_rpg_history_path(root: Path, agent_id: str) -> Path:
    return root / "ai_agents_memory" / agent_id / "RPG_HISTORY.md"


def _runtime_agent_id(company: str, role: str) -> str | None:
    role_map = {
        "Pam": "pam",
        "Iris": "iris",
        "Vera": "vera",
        "Rowan": "rowan",
        "Bianca": "bianca",
        "Lucian": "lucian",
        "Orion": "orion",
    }
    prefix = role_map.get(str(role).strip())
    if not prefix or not company:
        return None
    return f"{prefix}_{company}"


def apply_runtime_rpg_updates(root: Path, evidence_path: Path) -> Dict[str, Any]:
    records = _load_runtime_evidence_records(evidence_path)
    if not records:
        return {"updated_agents": [], "record_count": 0}

    updated_agents: list[str] = []
    per_agent_events: Dict[str, Dict[str, float]] = {}
    seen_sessions: set[tuple[str, str]] = set()

    for record in records:
        company = str(record.get("company_id") or "").strip()
        committee_sources = record.get("committee_sources") or {}
        consulted = {str(agent).strip() for agent in (record.get("source_agents_consulted") or []) if str(agent).strip()}
        packet_key = str(record.get("generated_at") or record.get("timestamp") or "")
        for role, meta in committee_sources.items():
            if role == "_committee":
                continue
            agent_id = _runtime_agent_id(company, role)
            if not agent_id:
                continue
            bucket = per_agent_events.setdefault(agent_id, {
                "xp": 0.0,
                "sessions": 0.0,
                "reliability": 0.0,
                "consistency": 0.0,
                "usefulness": 0.0,
                "evidence_quality": 0.0,
                "cost_efficiency": 0.0,
                "waste_penalty": 0.0,
            })
            if packet_key and (agent_id, packet_key) not in seen_sessions:
                bucket["sessions"] += 1.0
                seen_sessions.add((agent_id, packet_key))
            mode = str((meta or {}).get("mode") or "").strip()
            summary = str((meta or {}).get("summary") or "").strip()
            if mode == "live_session":
                bucket["xp"] += 3.0
                bucket["reliability"] += 2.0
                bucket["consistency"] += 1.0
                bucket["usefulness"] += 1.5
                bucket["evidence_quality"] += 1.5
            elif mode == "python_role_fallback":
                bucket["xp"] += 2.0
                bucket["reliability"] += 1.0
                bucket["usefulness"] += 1.0
                bucket["cost_efficiency"] += 1.5
            elif mode == "reused_cached":
                bucket["xp"] += 0.5
                bucket["consistency"] += 1.0
                bucket["cost_efficiency"] += 1.0
            elif mode.startswith("fallback_saved"):
                bucket["xp"] += 0.25
                bucket["waste_penalty"] += 0.5
            elif mode in {"live_session_failed", "missing"}:
                bucket["waste_penalty"] += 2.0
            if role in consulted and summary:
                bucket["usefulness"] += 0.5

    for agent_id, delta in per_agent_events.items():
        state_path = _runtime_rpg_state_path(root, agent_id)
        history_path = _runtime_rpg_history_path(root, agent_id)
        state = load_rpg_state(state_path)
        state["xp"] = max(0.0, float(state.get("xp") or 0.0) + delta["xp"])
        state["sessions"] = int(state.get("sessions") or 0) + int(delta["sessions"])
        for field in ("reliability", "consistency", "usefulness", "evidence_quality", "cost_efficiency"):
            state[field] = min(100.0, float(state.get(field) or 0.0) + float(delta[field]))
        state["waste_penalty"] = min(100.0, float(state.get("waste_penalty") or 0.0) + float(delta["waste_penalty"]))

        company_match = re.search(r"company_\d{3}", agent_id)
        company_id = company_match.group(0) if company_match else ""
        if agent_id.startswith("pam_") and company_id:
            state = score_pam_runtime_packet_routing_completion(state, evidence_path)
        if agent_id.startswith("lucian_") and company_id:
            state = score_lucian_runtime_packet_direction_completion(state, evidence_path)
        if agent_id.startswith("rowan_") and company_id:
            state = score_rowan_research_completion(state, evidence_path)

        saved = save_rpg_state(state_path, state)
        append_human_rpg_history(
            history_path,
            timestamp=records[-1].get("timestamp") if records and isinstance(records[-1], dict) else None,
            agent_id=agent_id,
            event_type="Runtime Evidence Batch",
            xp_delta=delta["xp"],
            before_xp=None,
            after_xp=saved["xp"],
            before_level=None,
            after_level=saved["level"],
            context=f"Processed {len(records)} runtime evidence records.",
            reason=(
                f"Credited runtime participation: sessions +{int(delta['sessions'])}, "
                f"reliability +{round(delta['reliability'], 2)}, usefulness +{round(delta['usefulness'], 2)}, "
                f"evidence +{round(delta['evidence_quality'], 2)}, cost efficiency +{round(delta['cost_efficiency'], 2)}, "
                f"waste penalty +{round(delta['waste_penalty'], 2)}."
            ),
        )
        updated_agents.append(agent_id)

    return {"updated_agents": sorted(updated_agents), "record_count": len(records)}


_RUNTIME_PACKET_BASE_XP = {
    "live_session": 3.0,
    "python_fallback": 1.5,
}

_RUNTIME_PACKET_ROLE_STAT_BONUSES = {
    "Lucian": {"judgment": 2.0, "reliability": 1.0, "usefulness": 1.0},
    "Bianca": {"cost_efficiency": 2.0, "judgment": 1.0, "evidence_quality": 1.0},
    "Vera": {"consistency": 2.0, "judgment": 1.0, "usefulness": 1.0},
    "Iris": {"accuracy": 1.0, "evidence_quality": 2.0, "usefulness": 1.0},
    "Orion": {"evidence_quality": 2.0, "accuracy": 1.0, "usefulness": 1.0},
    "Pam": {"usefulness": 2.0, "consistency": 1.0, "speed": 1.0},
}


def _history_path_for_state(path: Path) -> Path:
    return path.with_name("RPG_HISTORY.md")


def _append_rpg_history(history_path: Path, line: str) -> None:
    """Backward-compatible raw history appender.

    Prefer append_human_rpg_history for new XP events.
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if not history_path.exists():
        history_path.write_text("# RPG History\n\n", encoding="utf-8")
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(f"- {line}\n")


def _runtime_role_bonus(role_name: str, packet: Dict[str, Any], summary: str) -> tuple[float, Dict[str, float]]:
    xp_bonus = 0.0
    stat_bonus = dict(_RUNTIME_PACKET_ROLE_STAT_BONUSES.get(role_name, {}))
    approval_posture = str(packet.get("approval_posture") or "").strip().lower()
    packet_effects = [str(item).strip() for item in (packet.get("packet_effects") or []) if str(item).strip()]
    executed_count = sum(1 for item in (packet.get("top_ranked_candidates") or []) if isinstance(item, dict) and item.get("execution_state") == "executed")
    summary_lower = summary.lower()

    if executed_count and approval_posture != "company_veto":
        xp_bonus += 1.0
        stat_bonus["usefulness"] = stat_bonus.get("usefulness", 0.0) + 1.0

    if approval_posture == "company_veto" and packet_effects and role_name in {"Lucian", "Bianca", "Vera"}:
        xp_bonus += 1.0
        stat_bonus["judgment"] = stat_bonus.get("judgment", 0.0) + 1.0
        stat_bonus["reliability"] = stat_bonus.get("reliability", 0.0) + 1.0

    if "recommendation:" in summary_lower:
        xp_bonus += 0.5
        stat_bonus["evidence_quality"] = stat_bonus.get("evidence_quality", 0.0) + 1.0

    if "queue pressure" in summary_lower:
        stat_bonus["speed"] = stat_bonus.get("speed", 0.0) + 1.0

    return xp_bonus, stat_bonus


def apply_runtime_packet_rpg_updates(packet: Dict[str, Any], workspace_root: Path | None = None) -> List[Dict[str, Any]]:
    if not isinstance(packet, dict):
        return []
    committee_sources = packet.get("committee_sources") or {}
    if not isinstance(committee_sources, dict):
        return []

    workspace_root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    packet_mode = str(packet.get("packet_generation_mode") or "").strip().lower()
    if packet_mode not in {"live_committee_sessions", "fallback", "cached_committee_reuse"}:
        return []

    timestamp = str(packet.get("timestamp") or packet.get("generated_at") or "unknown")
    company_id = str(packet.get("company_id") or "global")
    events: List[Dict[str, Any]] = []

    for role_name, meta in committee_sources.items():
        if str(role_name).startswith("_") or not isinstance(meta, dict):
            continue
        mode = str(meta.get("mode") or "").strip()
        agent_id = str(meta.get("agent_id") or "").strip()
        if mode not in _RUNTIME_PACKET_BASE_XP or not agent_id:
            continue

        state_path = workspace_root / "ai_agents_memory" / agent_id / "RPG_STATE.md"
        history_path = _history_path_for_state(state_path)
        before = load_rpg_state(state_path)
        after = dict(before)

        xp_delta = _RUNTIME_PACKET_BASE_XP[mode]
        role_xp_bonus, stat_bonus = _runtime_role_bonus(str(role_name), packet, str(meta.get("summary") or ""))
        xp_delta += role_xp_bonus
        after["xp"] = float(after.get("xp") or 0.0) + xp_delta
        after["sessions"] = int(after.get("sessions") or 0) + 1
        after["consistency"] = min(100.0, float(after.get("consistency") or 0.0) + 1.0)
        after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 0.5)
        for field, delta in stat_bonus.items():
            after[field] = min(100.0, float(after.get(field) or 0.0) + float(delta))

        saved = save_rpg_state(state_path, after)
        before_level = int(before.get("level") or 1)
        after_level = int(saved.get("level") or 1)
        before_xp = float(before.get("xp") or 0.0)
        after_xp = float(saved.get("xp") or 0.0)
        xp_delta_actual = round(after_xp - before_xp, 2)
        reason_parts = [f"Contributed to {company_id} committee packet as {role_name}."]
        if mode == "live_session":
            reason_parts.append("Live OpenClaw committee response was used.")
        elif mode == "python_fallback":
            reason_parts.append("Python fallback response kept the packet moving.")
        if role_xp_bonus:
            reason_parts.append(f"Role bonus +{round(role_xp_bonus, 2)} XP for useful posture/evidence.")
        if stat_bonus:
            readable_stats = ", ".join(f"{field} +{round(value, 2)}" for field, value in sorted(stat_bonus.items()))
            reason_parts.append(f"Stat gains: {readable_stats}.")
        append_human_rpg_history(
            history_path,
            timestamp=timestamp,
            agent_id=agent_id,
            event_type="Runtime Committee Contribution",
            xp_delta=xp_delta_actual,
            before_xp=before_xp,
            after_xp=after_xp,
            before_level=before_level,
            after_level=after_level,
            context=f"{company_id} | role={role_name} | mode={mode} | sessions={int(saved.get('sessions') or 0)}",
            reason=" ".join(reason_parts),
        )
        events.append({
            "timestamp": timestamp,
            "company_id": company_id,
            "role": str(role_name),
            "agent_id": agent_id,
            "mode": mode,
            "xp_delta": round(after_xp - before_xp, 2),
            "before_xp": round(before_xp, 2),
            "after_xp": round(after_xp, 2),
            "before_level": before_level,
            "after_level": after_level,
            "sessions": int(saved.get("sessions") or 0),
        })

    return events


def format_runtime_rpg_event(event: Dict[str, Any]) -> str:
    label = f"{event.get('role')}/{event.get('agent_id')}"
    msg = (
        f"[RPG] {label} +{event.get('xp_delta', 0)} XP "
        f"({event.get('before_xp', 0)} -> {event.get('after_xp', 0)}) | "
        f"Level {event.get('after_level', 1)} | Sessions {event.get('sessions', 0)} | {event.get('company_id', 'global')}"
    )
    if event.get("after_level") != event.get("before_level"):
        msg += f" | LEVEL UP {event.get('before_level')} -> {event.get('after_level')}"
    return msg


__all__ = [
    "apply_runtime_packet_rpg_updates",
    "format_runtime_rpg_event",
    "RPG_STATE_FIELDS",
    "current_level_threshold",
    "default_rpg_state",
    "derive_intelligence",
    "get_role_scorecard",
    "is_verified_report_completion",
    "level_from_xp",
    "load_rpg_state",
    "migrate_rpg_state_file",
    "save_rpg_state",
    "score_lucian_live_committee_direction_completion",
    "score_lucian_runtime_packet_direction_completion",
    "score_mina_verified_test_report_completion",
    "score_pam_runtime_packet_routing_completion",
    "score_rowan_research_completion",
    "score_rowan_research_report_completion",
    "score_verified_report_completion",
    "apply_runtime_rpg_updates",
    "append_human_rpg_history",
    "format_rpg_identity_line",
    "format_rpg_summary",
    "update_xp",
    "xp_to_next_level",
]
