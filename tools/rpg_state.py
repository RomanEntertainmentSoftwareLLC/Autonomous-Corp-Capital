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
from pathlib import Path
from typing import Any, Dict

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


__all__ = [
    "RPG_STATE_FIELDS",
    "current_level_threshold",
    "default_rpg_state",
    "derive_intelligence",
    "is_verified_report_completion",
    "level_from_xp",
    "load_rpg_state",
    "migrate_rpg_state_file",
    "save_rpg_state",
    "score_verified_report_completion",
    "format_rpg_identity_line",
    "format_rpg_summary",
    "update_xp",
    "xp_to_next_level",
]
