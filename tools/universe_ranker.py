"""ACC V3-A explainable universe ranking helpers.

This module ranks candidates without executing trades. It can be used by tests
and future reports before it is wired into runtime decisions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def score_universe_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    policy = abs(_safe_float(candidate.get("policy_signal_score"), 0.0))
    ml = abs(_safe_float(candidate.get("ml_signal_score"), 0.0))
    pattern = abs(_safe_float(candidate.get("pattern_score") or candidate.get("pattern_contribution"), 0.0))
    model_confidence = abs(_safe_float(candidate.get("model_score"), 0.5) - 0.5) * 2.0
    orion = abs(_safe_float(candidate.get("orion_bias"), 0.0))
    volatility_penalty = min(abs(_safe_float(candidate.get("volatility_proxy"), 0.0)), 0.05)
    risk_penalty = 0.05 if candidate.get("vetoed_by_risk") else 0.0

    final_score = round(policy + ml + pattern + model_confidence + orion - volatility_penalty - risk_penalty, 6)

    reasons = [
        f"policy={policy:.6f}",
        f"ml={ml:.6f}",
        f"pattern={pattern:.6f}",
        f"model_confidence={model_confidence:.6f}",
    ]
    if orion:
        reasons.append(f"orion={orion:.6f}")
    if volatility_penalty:
        reasons.append(f"volatility_penalty={volatility_penalty:.6f}")
    if risk_penalty:
        reasons.append("risk_penalty=0.050000")

    return {
        "symbol": candidate.get("symbol"),
        "company_id": candidate.get("company_id"),
        "universe_rank_score": final_score,
        "trend_score": round(policy, 6),
        "ml_score_component": round(ml, 6),
        "pattern_score_component": round(pattern, 6),
        "confidence_component": round(model_confidence, 6),
        "volatility_penalty": round(volatility_penalty, 6),
        "risk_penalty": round(risk_penalty, 6),
        "reasons": reasons,
    }


def rank_universe_candidates(candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    scored = [score_universe_candidate(candidate) for candidate in candidates]
    scored.sort(key=lambda row: row["universe_rank_score"], reverse=True)
    for index, row in enumerate(scored, start=1):
        row["universe_rank"] = index
    return scored
