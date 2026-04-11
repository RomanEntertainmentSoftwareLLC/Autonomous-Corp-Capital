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


__all__ = [
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
    "score_mina_verified_test_report_completion",
    "score_verified_report_completion",
    "format_rpg_identity_line",
    "format_rpg_summary",
    "update_xp",
    "xp_to_next_level",
]
