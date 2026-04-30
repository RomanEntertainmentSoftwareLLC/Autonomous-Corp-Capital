"""ACC V3-A market-weather reporting helpers.

Market weather is the operator-friendly summary above raw regime labels. It is
safe to compute in tests and reports because it is deterministic and has no
side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence

from tools.market_regime import MarketRegime, classify_market_regime


@dataclass(frozen=True)
class MarketWeather:
    market_regime: str
    risk_posture: str
    best_posture: str
    breadth_green: int
    breadth_red: int
    breadth_total: int
    breadth_green_ratio: float
    breadth_red_ratio: float
    volatility_proxy: float
    btc_direction: str
    eth_direction: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_regime": self.market_regime,
            "risk_posture": self.risk_posture,
            "best_posture": self.best_posture,
            "breadth_green": self.breadth_green,
            "breadth_red": self.breadth_red,
            "breadth_total": self.breadth_total,
            "breadth_green_ratio": round(float(self.breadth_green_ratio), 6),
            "breadth_red_ratio": round(float(self.breadth_red_ratio), 6),
            "volatility_proxy": round(float(self.volatility_proxy), 6),
            "btc_direction": self.btc_direction,
            "eth_direction": self.eth_direction,
            "reasons": list(self.reasons),
        }


def _direction(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value > 0.002:
        return "up"
    if value < -0.002:
        return "down"
    return "flat"


def _best_posture(regime: MarketRegime) -> str:
    if regime.regime in {"broad_red_market", "volatility_shock"}:
        return "wait_or_reduce"
    if regime.regime == "downtrend":
        return "defensive_wait"
    if regime.regime in {"uptrend", "mixed_selective"}:
        return "selective_long"
    if regime.regime == "sideways_chop":
        return "wait_for_confirmation"
    return "observe"


def build_market_weather(snapshots: Sequence[Mapping[str, Any]]) -> MarketWeather:
    regime = classify_market_regime(snapshots)
    total = regime.breadth_total or 0
    green_ratio = regime.breadth_green / total if total else 0.0
    red_ratio = regime.breadth_red / total if total else 0.0

    return MarketWeather(
        market_regime=regime.regime,
        risk_posture=regime.posture,
        best_posture=_best_posture(regime),
        breadth_green=regime.breadth_green,
        breadth_red=regime.breadth_red,
        breadth_total=regime.breadth_total,
        breadth_green_ratio=green_ratio,
        breadth_red_ratio=red_ratio,
        volatility_proxy=regime.max_abs_change_pct,
        btc_direction=_direction(regime.btc_change_pct),
        eth_direction=_direction(regime.eth_change_pct),
        reasons=regime.reasons,
    )


def build_market_weather_dict(snapshots: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return build_market_weather(snapshots).to_dict()
