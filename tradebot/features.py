"""Feature extractor and logger for ML-ready signals and pattern detection."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class PendingLabelState:
    remaining: int
    filled: bool = False


class FeatureLogger:
    """Tracks tick history, patterns, and future labels."""

    HORIZONS = [3, 5, 10]

    def __init__(self, results_dir: Path, history_window: int = 20) -> None:
        self.results_dir = results_dir
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.results_dir / "feature-log.jsonl"
        self.history = deque(maxlen=history_window)
        self.pending: List[Dict[str, Any]] = []
        self.tick_counter = 0

    def record_tick(
        self,
        tick: Dict[str, Any],
        signal: Any,
        decision: Any,
        strategy: Any,
    ) -> None:
        price = float(tick["price"])
        self._advance_pending(price)
        features = self._build_features(price, tick, signal, decision, strategy)

        record = {
            "features": features,
            "base_price": price,
            "horizons": {h: PendingLabelState(remaining=h) for h in self.HORIZONS},
            "labels": {},
        }

        self.pending.append(record)
        self.history.append(price)
        self.tick_counter += 1

    def _advance_pending(self, future_price: float) -> None:
        completed = []

        for record in self.pending:
            for horizon, state in record["horizons"].items():
                if state.filled:
                    continue

                state.remaining -= 1
                if state.remaining <= 0:
                    self._fill_label(record, horizon, future_price)
                    state.filled = True

            if all(state.filled for state in record["horizons"].values()):
                completed.append(record)

        for record in completed:
            self._write_record(record)
            self.pending.remove(record)

    def _fill_label(
        self,
        record: Dict[str, Any],
        horizon: int,
        future_price: float,
    ) -> None:
        base_price = record["base_price"]
        future_return = self._safe_return(base_price, future_price)
        record["labels"][f"future_return_{horizon}_ticks"] = round(future_return, 6)
        record["labels"][f"future_direction_{horizon}_ticks"] = self._direction_from_return(
            future_return
        )

    @staticmethod
    def _safe_return(base: float, future: float) -> float:
        if not base:
            return 0.0
        return (future - base) / base

    @staticmethod
    def _direction_from_return(value: float) -> int:
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    def _build_features(
        self,
        price: float,
        tick: Dict[str, Any],
        signal: Any,
        decision: Any,
        strategy: Any,
    ) -> Dict[str, Any]:
        history_snapshot = list(self.history)

        price_changes = {
            "price_change_1": self._price_change(price, history_snapshot, 1),
            "price_change_2": self._price_change(price, history_snapshot, 2),
            "price_change_3": self._price_change(price, history_snapshot, 3),
        }
        price_changes["momentum_3"] = price_changes["price_change_3"]

        momentum_3 = price_changes["momentum_3"]
        slope_3 = momentum_3 / 3 if len(history_snapshot) >= 3 else 0.0
        pattern_flags = self._detect_patterns(history_snapshot, price, price_changes)

        ema_fast = getattr(strategy, "last_fast", None)
        ema_slow = getattr(strategy, "last_slow", None)
        ema_spread = (ema_fast - ema_slow) if ema_fast and ema_slow else 0.0

        features = {
            "tick_index": self.tick_counter,
            "timestamp": tick["timestamp"],
            "symbol": tick["symbol"],
            "price": price,
            "source": tick.get("source", "unknown"),
            "ema_fast": round(ema_fast, 6) if ema_fast else None,
            "ema_slow": round(ema_slow, 6) if ema_slow else None,
            "ema_spread": round(ema_spread, 6),
            "rsi": round(getattr(strategy, "current_rsi", None), 2)
            if getattr(strategy, "current_rsi", None) is not None
            else None,
            "price_change_1": round(price_changes["price_change_1"], 6),
            "price_change_2": round(price_changes["price_change_2"], 6),
            "price_change_3": round(price_changes["price_change_3"], 6),
            "momentum_3": round(momentum_3, 6),
            "slope_3": round(slope_3, 6),
            "current_signal": signal.direction,
            "current_action": decision.action,
            "fake_cash": round(decision.cash_after, 2),
            "fake_position": round(decision.position_after, 6),
        }

        features.update(pattern_flags)
        return features

    def _price_change(self, price: float, history: List[float], lookback: int) -> float:
        if len(history) < lookback:
            return 0.0
        return price - history[-lookback]

    def _detect_patterns(
        self,
        history: List[float],
        price: float,
        price_changes: Dict[str, float],
    ) -> Dict[str, Any]:
        window = []
        if len(history) >= 2:
            window = [history[-2], history[-1], price]

        prev_three = history[-3:] if len(history) >= 3 else []

        rising = len(window) == 3 and window[0] < window[1] < window[2]
        falling = len(window) == 3 and window[0] > window[1] > window[2]

        reversal_after_decline = (
            len(prev_three) == 3
            and prev_three[0] > prev_three[1] > prev_three[2]
            and price > prev_three[-1]
        )

        reversal_after_rise = (
            len(prev_three) == 3
            and prev_three[0] < prev_three[1] < prev_three[2]
            and price < prev_three[-1]
        )

        burst = False
        if price_changes.get("momentum_3") and price_changes.get("price_change_2"):
            dominant = max(
                abs(price_changes["price_change_1"]),
                abs(price_changes["price_change_2"]),
            )
            if dominant and abs(price_changes["momentum_3"]) > dominant * 1.25:
                burst = True

        exhaustion = (
            (rising and price_changes["price_change_1"] < 0)
            or (falling and price_changes["price_change_1"] > 0)
        )

        higher_highs = rising
        higher_lows = len(window) == 3 and window[0] < window[2]
        lower_highs = len(window) == 3 and window[0] > window[2]
        lower_lows = falling

        pattern_flags = {
            "pattern_three_rising": rising,
            "pattern_three_falling": falling,
            "pattern_reversal_after_two_decline": reversal_after_decline,
            "pattern_reversal_after_two_rise": reversal_after_rise,
            "pattern_short_momentum_burst": burst,
            "pattern_short_exhaustion": exhaustion,
            "higher_highs": higher_highs,
            "higher_lows": higher_lows,
            "lower_highs": lower_highs,
            "lower_lows": lower_lows,
        }

        detected = [name for name, flag in pattern_flags.items() if flag]
        pattern_flags["detected_patterns"] = detected
        return pattern_flags

    def _write_record(self, record: Dict[str, Any]) -> None:
        payload = {**record["features"], **record["labels"]}
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")