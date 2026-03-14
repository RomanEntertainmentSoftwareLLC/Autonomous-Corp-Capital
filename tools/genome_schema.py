"""Shared genome schema definitions for mutation, validation, and compilation."""
from __future__ import annotations

from typing import Dict, List, Tuple

FEATURE_FLAGS: List[str] = [
    "use_ema_spread",
    "use_rsi",
    "use_price_change_1",
    "use_price_change_2",
    "use_price_change_3",
    "use_momentum_3",
    "use_slope_3",
    "use_pattern_flags",
]

INDICATOR_FLAGS: List[str] = [
    "use_ema",
    "use_rsi",
    "use_volatility",
]

INDICATOR_PARAMS: Dict[str, Tuple[float, float]] = {
    "ema_fast": (3, 30),
    "ema_slow": (10, 60),
    "rsi_period": (5, 30),
    "rsi_oversold": (10, 50),
    "rsi_overbought": (50, 90),
    "momentum_period": (2, 20),
    "volatility_period": (5, 60),
}

MODEL_OPTIONS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "logistic_regression": {
        "penalty": (0.01, 10.0),
        "C": (0.01, 5.0),
    },
    "random_forest": {
        "n_estimators": (10, 200),
        "max_depth": (3, 20),
    },
}

MODEL_TYPES: List[str] = list(MODEL_OPTIONS.keys())
