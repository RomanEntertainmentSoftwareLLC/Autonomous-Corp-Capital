"""ACC V3-A deterministic market-regime helpers.

This module is intentionally token-free and side-effect-free. It does not
place trades, call agents, or mutate runtime state. It turns a small set of
market snapshots into a compact regime/posture object that later runtime code
can record in traces and, only after testing, use as a safety input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

REGIME_UPTREND = "uptrend"
REGIME_DOWNTREND = "downtrend"
REGIME_SIDEWAYS_CHOP = "sideways_chop"
REGIME_BROAD_RED_MARKET = "broad_red_market"
REGIME_MIXED_SELECTIVE = "mixed_selective"
REGIME_VOLATILITY_SHOCK = "volatility_shock"
REGIME_UNKNOWN = "unknown"

POSTURE_SELECTIVE_LONG = "selective_long"
POSTURE_WAIT = "wait"
POSTURE_RESTRICTED = "restricted"
POSTURE_DEFENSIVE = "defensive"
POSTURE_OBSERVE = "observe"


@dataclass(frozen=True)
class MarketRegime:
    """Small, serializable regime report."""

    regime: str
    confidence: float
    posture: str
    breadth_green: int
    breadth_red: int
    breadth_total: int
    average_change_pct: float
    max_abs_change_pct: float
    btc_change_pct: float | None = None
    eth_change_pct: float | None = None
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_regime": self.regime,
            "regime_confidence": round(float(self.confidence), 6),
            "risk_posture": self.posture,
            "breadth_green": int(self.breadth_green),
            "breadth_red": int(self.breadth_red),
            "breadth_total": int(self.breadth_total),
            "average_change_pct": round(float(self.average_change_pct), 6),
            "max_abs_change_pct": round(float(self.max_abs_change_pct), 6),
            "btc_change_pct": None if self.btc_change_pct is None else round(float(self.btc_change_pct), 6),
            "eth_change_pct": None if self.eth_change_pct is None else round(float(self.eth_change_pct), 6),
            "reasons": list(self.reasons),
        }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or "").upper()


def snapshot_change_pct(snapshot: Mapping[str, Any]) -> float:
    """Return a percent-change proxy from a normalized snapshot or candidate row.

    Values are expected to be decimal percent changes:
    0.012 means +1.2%.
    """

    for key in (
        "change_pct",
        "pct_change",
        "price_change_pct",
        "price_change_1",
        "momentum_3",
        "policy_signal_score",
        "signal_score",
    ):
        if key in snapshot:
            return _safe_float(snapshot.get(key), 0.0)

    price = _safe_float(snapshot.get("price"), 0.0)
    last_price = _safe_float(snapshot.get("last_price"), 0.0)
    if price > 0.0 and last_price > 0.0:
        return (price - last_price) / last_price
    return 0.0


def classify_market_regime(snapshots: Sequence[Mapping[str, Any]]) -> MarketRegime:
    """Classify a simple market regime from current rows.

    This is V3-A foundation logic, not a final trading edge. It favors clear,
    explainable thresholds over cleverness so tests and operator reports can
    show exactly why a regime was chosen.
    """

    rows = [row for row in snapshots if isinstance(row, Mapping)]
    if not rows:
        return MarketRegime(
            regime=REGIME_UNKNOWN,
            confidence=0.0,
            posture=POSTURE_OBSERVE,
            breadth_green=0,
            breadth_red=0,
            breadth_total=0,
            average_change_pct=0.0,
            max_abs_change_pct=0.0,
            reasons=["no market snapshots supplied"],
        )

    changes = [snapshot_change_pct(row) for row in rows]
    total = len(changes)
    green = sum(1 for value in changes if value > 0.0)
    red = sum(1 for value in changes if value < 0.0)
    avg = sum(changes) / total if total else 0.0
    max_abs = max((abs(value) for value in changes), default=0.0)
    red_ratio = red / total if total else 0.0
    green_ratio = green / total if total else 0.0

    btc = next((snapshot_change_pct(row) for row in rows if _symbol(row) == "BTC-USD"), None)
    eth = next((snapshot_change_pct(row) for row in rows if _symbol(row) == "ETH-USD"), None)

    reasons: List[str] = [
        f"breadth green={green} red={red} total={total}",
        f"average_change_pct={avg:.6f}",
    ]

    if max_abs >= 0.045:
        return MarketRegime(
            regime=REGIME_VOLATILITY_SHOCK,
            confidence=min(1.0, max_abs / 0.08),
            posture=POSTURE_RESTRICTED,
            breadth_green=green,
            breadth_red=red,
            breadth_total=total,
            average_change_pct=avg,
            max_abs_change_pct=max_abs,
            btc_change_pct=btc,
            eth_change_pct=eth,
            reasons=reasons + ["max absolute change exceeds volatility shock threshold"],
        )

    majors_red = (btc is not None and btc < -0.003) and (eth is not None and eth < -0.003)
    if red_ratio >= 0.70 and avg < -0.003 and majors_red:
        return MarketRegime(
            regime=REGIME_BROAD_RED_MARKET,
            confidence=min(1.0, 0.55 + red_ratio / 2.0),
            posture=POSTURE_RESTRICTED,
            breadth_green=green,
            breadth_red=red,
            breadth_total=total,
            average_change_pct=avg,
            max_abs_change_pct=max_abs,
            btc_change_pct=btc,
            eth_change_pct=eth,
            reasons=reasons + ["broad red breadth with BTC and ETH negative"],
        )

    majors_green = (btc is not None and btc > 0.003) and (eth is not None and eth > 0.003)
    if green_ratio >= 0.65 and avg > 0.003 and majors_green:
        return MarketRegime(
            regime=REGIME_UPTREND,
            confidence=min(1.0, 0.50 + green_ratio / 2.0),
            posture=POSTURE_SELECTIVE_LONG,
            breadth_green=green,
            breadth_red=red,
            breadth_total=total,
            average_change_pct=avg,
            max_abs_change_pct=max_abs,
            btc_change_pct=btc,
            eth_change_pct=eth,
            reasons=reasons + ["broad green breadth with BTC and ETH positive"],
        )

    if red_ratio >= 0.65 and avg < -0.002:
        return MarketRegime(
            regime=REGIME_DOWNTREND,
            confidence=min(1.0, 0.45 + red_ratio / 2.0),
            posture=POSTURE_DEFENSIVE,
            breadth_green=green,
            breadth_red=red,
            breadth_total=total,
            average_change_pct=avg,
            max_abs_change_pct=max_abs,
            btc_change_pct=btc,
            eth_change_pct=eth,
            reasons=reasons + ["negative breadth without full broad-red confirmation"],
        )

    if green_ratio >= 0.65 and avg > 0.002:
        return MarketRegime(
            regime=REGIME_MIXED_SELECTIVE,
            confidence=min(1.0, 0.40 + green_ratio / 2.5),
            posture=POSTURE_SELECTIVE_LONG,
            breadth_green=green,
            breadth_red=red,
            breadth_total=total,
            average_change_pct=avg,
            max_abs_change_pct=max_abs,
            btc_change_pct=btc,
            eth_change_pct=eth,
            reasons=reasons + ["positive breadth without major-coin confirmation"],
        )

    return MarketRegime(
        regime=REGIME_SIDEWAYS_CHOP,
        confidence=0.45,
        posture=POSTURE_WAIT,
        breadth_green=green,
        breadth_red=red,
        breadth_total=total,
        average_change_pct=avg,
        max_abs_change_pct=max_abs,
        btc_change_pct=btc,
        eth_change_pct=eth,
        reasons=reasons + ["mixed/low-conviction breadth"],
    )


def classify_market_regime_dict(snapshots: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Convenience wrapper for JSONL report writers."""

    return classify_market_regime(snapshots).to_dict()
