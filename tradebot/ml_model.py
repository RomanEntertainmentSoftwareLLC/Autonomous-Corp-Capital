"""ML inference helper for trading feature vectors."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import joblib

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "ml_model.pkl"
NUMERIC_COLUMNS = [
    "ema_fast",
    "ema_slow",
    "ema_spread",
    "rsi",
    "price_change_1",
    "price_change_2",
    "price_change_3",
    "momentum_3",
    "slope_3",
]
PATTERN_FLAGS = [
    "pattern_three_rising",
    "pattern_three_falling",
    "pattern_reversal_after_two_decline",
    "pattern_reversal_after_two_rise",
    "pattern_short_momentum_burst",
    "pattern_short_exhaustion",
    "higher_highs",
    "higher_lows",
    "lower_highs",
    "lower_lows",
]

logger = logging.getLogger(__name__)


class MLModel:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = (path or MODEL_PATH).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"ML model not found at {self.path}")
        self.clf = joblib.load(self.path)

    def _vectorize(self, features: Dict[str, Any]) -> List[float]:
        vector: List[float] = []
        for col in NUMERIC_COLUMNS:
            value = features.get(col)
            try:
                vector.append(float(value) if value not in (None, "") else 0.0)
            except (ValueError, TypeError):
                vector.append(0.0)
        for flag in PATTERN_FLAGS:
            value = features.get(flag)
            if isinstance(value, bool):
                vector.append(1.0 if value else 0.0)
            elif isinstance(value, str):
                vector.append(1.0 if value.lower() == "true" else 0.0)
            else:
                vector.append(1.0 if value else 0.0)
        return vector

    def predict(self, features: Dict[str, Any]) -> Dict[str, Any]:
        vector = self._vectorize(features)
        label = self.clf.predict([vector])[0]
        result = {"prediction": int(label)}
        if hasattr(self.clf, "predict_proba"):
            probs = self.clf.predict_proba([vector])[0]
            result["confidence"] = float(max(probs))
            result["probabilities"] = {int(c): float(p) for c, p in zip(self.clf.classes_, probs)}
        return result


def available_models() -> Iterable[Path]:
    model_dir = MODEL_PATH.parent
    if not model_dir.exists():
        return []
    return sorted(model_dir.glob("*.pkl"))
