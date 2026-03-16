"""Decision engine for live paper trading."""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Dict, Optional

ML_MODEL_PATH = "models/strategy.ml"


class DecisionResult(Dict[str, object]):
    pass


def compute_signal(snapshot: Dict[str, object], last_price: Optional[float]) -> float:
    price = snapshot.get("price") or 0.0
    if last_price is None:
        return 0.0
    if last_price == 0:
        return 0.0
    return (price - last_price) / last_price


def map_score_to_decision(score: float) -> str:
    if score > 0.005:
        return "BUY"
    if score < -0.005:
        return "SELL"
    return "HOLD"


def build_decision(snapshot: Dict[str, object], company_id: str, last_price: Optional[float]) -> DecisionResult:
    price = snapshot.get("price") or 0.0
    signal_score = compute_signal(snapshot, last_price)
    decision = map_score_to_decision(signal_score)
    result = DecisionResult(
        {
            "timestamp": snapshot.get("timestamp") or datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "company_id": company_id,
            "symbol": snapshot.get("symbol"),
            "price": price,
            "decision": decision,
            "confidence": round(min(abs(signal_score) * 100, 1.0), 4),
            "model_score": None,
            "signal_score": round(signal_score, 6),
            "threshold_used": 0.005,
            "notes": "signal-based scoring",
        }
    )
    result["ml_scoring_active"] = False
    result["signal_scoring_active"] = True
    return result
