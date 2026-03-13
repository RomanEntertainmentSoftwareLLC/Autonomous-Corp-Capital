"""ML-powered strategy that uses a trained model to predict signals."""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional

from tradebot.ml_model import MODEL_PATH, MLModel
from tradebot.strategies.base import Signal, StrategyMetadata, StrategyProtocol
from tradebot.strategies.rsi import RSITracker

logger = logging.getLogger(__name__)

COLUMNS = [
    "ema_fast",
    "ema_slow",
    "ema_spread",
    "rsi",
    "price_change_1",
    "price_change_2",
    "price_change_3",
    "momentum_3",
    "slope_3",
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


class MLTraderStrategy(StrategyProtocol):
    name = "ml_trader"
    metadata = StrategyMetadata(
        name=name,
        description="ML classifier-based signal generator using saved models.",
        category="ml",
        required_config=("model_path",),
        supports_ml=True,
        version="1.0",
        author="OpenClaw ML",
        risk_profile="high",
        parameters=("model_path", "ml_confidence_threshold"),
    )

    def __init__(self, symbol_config: Dict[str, object]) -> None:
        self.symbol = symbol_config.get("name", "UNKNOWN")
        self.lookback = 20
        self.prices: Deque[float] = deque(maxlen=self.lookback)
        self.rsi_period = symbol_config.get("rsi_period", 14)
        self.rsi_tracker = RSITracker(self.rsi_period)
        self.confidence_threshold = float(symbol_config.get("ml_confidence_threshold", 0.6))
        self.ml_model: Optional[MLModel] = None
        model_path = symbol_config.get("model_path")
        try:
            self.ml_model = MLModel(Path(model_path)) if model_path else MLModel()
        except FileNotFoundError as exc:
            logger.warning(
                "ML model not found at %s; MLTraderStrategy will hold until a model is trained",
                model_path or MODEL_PATH,
            )
            logger.debug("ML load error: %s", exc)
        except Exception as exc:
            logger.error("Failed to load ML model: %s", exc)
        self.last_emaspread: float = 0.0
        self.ema_fast: Optional[float] = None
        self.ema_slow: Optional[float] = None

    def _ema(self, period: int, last: Optional[float]) -> Optional[float]:
        if len(self.prices) < period:
            return None
        values = list(self.prices)[-period:]
        alpha = 2 / (period + 1)
        if last is None:
            return sum(values) / period
        return (self.prices[-1] - last) * alpha + last

    def _build_features(self, price: float) -> Dict[str, object]:
        self.prices.append(price)
        fast = self._ema(6, self.ema_fast)
        slow = self._ema(21, self.ema_slow)
        self.ema_fast = fast
        self.ema_slow = slow
        spread = (fast - slow) if fast and slow else 0.0
        rsi = self.rsi_tracker.update(price)

        history = list(self.prices)
        changes = []
        for lookback in (1, 2, 3):
            if len(history) > lookback:
                changes.append(price - history[-lookback - 1])
            else:
                changes.append(0.0)
        momentum = changes[-1]
        slope = momentum / 3 if len(history) >= 3 else 0.0

        window = history[-3:] if len(history) >= 3 else []
        rising = len(window) == 3 and window[0] < window[1] < window[2]
        falling = len(window) == 3 and window[0] > window[1] > window[2]
        reversal_after_decline = (
            len(window) == 3 and window[0] > window[1] > window[2] and price > window[-1]
        )
        reversal_after_rise = (
            len(window) == 3 and window[0] < window[1] < window[2] and price < window[-1]
        )
        burst = abs(momentum) > max(abs(changes[0]), abs(changes[1]), 1e-6) * 1.25
        exhaustion = (rising and changes[0] < 0) or (falling and changes[0] > 0)

        features = {
            "ema_fast": fast or 0.0,
            "ema_slow": slow or 0.0,
            "ema_spread": spread,
            "rsi": rsi or 0.0,
            "price_change_1": changes[0],
            "price_change_2": changes[1],
            "price_change_3": changes[2],
            "momentum_3": momentum,
            "slope_3": slope,
            "pattern_three_rising": rising,
            "pattern_three_falling": falling,
            "pattern_reversal_after_two_decline": reversal_after_decline,
            "pattern_reversal_after_two_rise": reversal_after_rise,
            "pattern_short_momentum_burst": burst,
            "pattern_short_exhaustion": exhaustion,
            "higher_highs": rising,
            "higher_lows": len(window) == 3 and window[0] < window[2],
            "lower_highs": len(window) == 3 and window[0] > window[2],
            "lower_lows": falling,
        }
        return features

    def update(self, price: float) -> Signal:
        features = self._build_features(price)
        if not self.ml_model:
            return Signal(direction="HOLD", confidence=0.0, reason="Waiting for ML model")
        result = self.ml_model.predict(features)
        confidence = result.get("confidence", 0.0)
        prediction = result.get("prediction")
        if confidence < self.confidence_threshold or prediction not in {1, -1}:
            return Signal(direction="HOLD", confidence=confidence, reason="Low confidence ML signal")
        direction = "BUY" if prediction > 0 else "SELL"
        reason = "ML model" if confidence >= self.confidence_threshold else "Low confidence ML signal"
        return Signal(direction=direction, confidence=confidence, reason=reason)
