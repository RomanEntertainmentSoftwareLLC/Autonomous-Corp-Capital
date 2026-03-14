"""Shared helpers for reporting evaluation state and fitness scoring."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

FITNESS_WEIGHTS = {
    "realized_pnl": 1.0,
    "unrealized_pnl": 0.25,
    "win_rate": 0.5,
    "drawdown": -2.0,
    "trades": -0.05,
}


def _to_float(metrics: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = metrics.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_count(metrics: Mapping[str, Any]) -> int:
    count = metrics.get("trade_count")
    if count is None:
        count = metrics.get("trades")
    try:
        return int(count or 0)
    except (TypeError, ValueError):
        return 0


def _drawdown(metrics: Mapping[str, Any]) -> float:
    if "drawdown" in metrics:
        return _to_float(metrics, "drawdown")
    if "max_drawdown" in metrics:
        return _to_float(metrics, "max_drawdown")
    return 0.0


def compute_fitness(metrics: Mapping[str, Any]) -> float:
    if not metrics:
        return 0.0
    realized = _to_float(metrics, "realized_pnl")
    unrealized = _to_float(metrics, "unrealized_pnl")
    win_rate = _to_float(metrics, "win_rate")
    drawdown = _drawdown(metrics)
    trades = _trade_count(metrics)
    score = (
        realized * FITNESS_WEIGHTS["realized_pnl"]
        + unrealized * FITNESS_WEIGHTS["unrealized_pnl"]
        + win_rate * FITNESS_WEIGHTS["win_rate"]
        + drawdown * FITNESS_WEIGHTS["drawdown"]
        + trades * FITNESS_WEIGHTS["trades"]
    )
    return score


def determine_evaluation_state(metrics: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    trades = _trade_count(metrics)
    if not metrics:
        return "UNTESTED", "No evaluation results available"
    if trades == 0:
        return "TESTED", "Results recorded but no trades executed yet"
    return "ACTIVE", None
