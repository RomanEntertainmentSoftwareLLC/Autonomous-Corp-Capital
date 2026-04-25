"""Decision engine for live paper trading."""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, List, Any

from tools.pattern_engine import evaluate_patterns

LIVE_PATTERN_SCORE_MAX_ABS = 0.015


EXIT_STOP_LOSS_PCT = float(os.environ.get("ACC_EXIT_STOP_LOSS_PCT", "0.015"))
EXIT_TAKE_PROFIT_PCT = float(os.environ.get("ACC_EXIT_TAKE_PROFIT_PCT", "0.02"))
EXIT_MAX_HOLD_TICKS = int(os.environ.get("ACC_EXIT_MAX_HOLD_TICKS", "18"))
EXIT_NEGATIVE_SIGNAL_MULTIPLIER = float(os.environ.get("ACC_EXIT_NEGATIVE_SIGNAL_MULTIPLIER", "0.6"))

ROOT = Path(__file__).resolve().parent.parent
ML_MODEL_PATH = ROOT / "models" / "ml_model.pkl"
ML_COLUMNS = [
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


class DecisionResult(Dict[str, object]):
    pass


COMPANY_POLICIES: Dict[str, Dict[str, object]] = {
    "company_001": {
        "policy_name": "balanced_baseline",
        "company_posture": "balanced baseline",
        "threshold": 0.005,
        "signal_multiplier": 1.0,
        "size_multiplier": 1.0,
        "sizing_rationale": "baseline participation with standard confirmation",
    },
    "company_002": {
        "policy_name": "defensive_confirmed",
        "company_posture": "defensive",
        "threshold": 0.0075,
        "signal_multiplier": 0.85,
        "size_multiplier": 0.6,
        "sizing_rationale": "smaller size after stricter confirmation",
    },
    "company_003": {
        "policy_name": "momentum_fast",
        "company_posture": "momentum-seeking",
        "threshold": 0.003,
        "signal_multiplier": 1.2,
        "size_multiplier": 1.35,
        "sizing_rationale": "faster participation with larger momentum sizing",
    },
    "company_004": {
        "policy_name": "experimental_probe",
        "company_posture": "experimental but controlled",
        "threshold": 0.004,
        "signal_multiplier": 1.05,
        "size_multiplier": 0.4,
        "sizing_rationale": "small exploratory size with controlled risk",
    },
}


@lru_cache(maxsize=1)
def _load_ml_runtime() -> Dict[str, object]:
    if not ML_MODEL_PATH.exists():
        return {
            "active": False,
            "reason": f"model artifact missing at {ML_MODEL_PATH}",
            "model": None,
            "joblib": None,
        }

    try:
        joblib = importlib.import_module("joblib")
    except ModuleNotFoundError:
        site_packages = sorted((ROOT / ".venv" / "lib").glob("python*/site-packages"))
        for candidate in site_packages:
            if candidate.exists() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
        try:
            joblib = importlib.import_module("joblib")
        except ModuleNotFoundError:
            return {
                "active": False,
                "reason": "model artifact exists but ML runtime dependencies are unavailable",
                "model": None,
                "joblib": None,
            }

    try:
        model = joblib.load(ML_MODEL_PATH)
    except Exception as exc:  # pragma: no cover - defensive reporting
        return {
            "active": False,
            "reason": f"failed to load model artifact: {exc}",
            "model": None,
            "joblib": joblib,
        }

    return {"active": True, "reason": "loaded", "model": model, "joblib": joblib}


def company_policy(company_id: str) -> Dict[str, object]:
    return COMPANY_POLICIES.get(company_id, COMPANY_POLICIES["company_001"])



def compute_signal(snapshot: Dict[str, object], last_price: Optional[float]) -> float:
    price = snapshot.get("price") or 0.0
    if last_price is None:
        return 0.0
    if last_price == 0:
        return 0.0
    return (price - last_price) / last_price



def map_score_to_decision(score: float, threshold: float, position_state: float = 0.0) -> str:
    if score > threshold:
        return "BUY"
    if score < -threshold:
        return "SELL"
    return "HOLD_POSITION" if float(position_state) > 0 else "WAIT"



def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _ema(values: List[float], period: int) -> float:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return 0.0
    alpha = 2.0 / (float(period) + 1.0)
    ema = clean[0]
    for value in clean[1:]:
        ema = (value * alpha) + (ema * (1.0 - alpha))
    return float(ema)


def _rsi(values: List[float], period: int = 14) -> float:
    clean = [float(v) for v in values if v is not None]
    if len(clean) < 2:
        return 50.0
    deltas = [clean[i] - clean[i - 1] for i in range(1, len(clean))]
    window = deltas[-period:] if len(deltas) >= period else deltas
    if not window:
        return 50.0
    gains = [d for d in window if d > 0.0]
    losses = [-d for d in window if d < 0.0]
    avg_gain = sum(gains) / len(window)
    avg_loss = sum(losses) / len(window)
    if avg_loss == 0.0 and avg_gain == 0.0:
        return 50.0
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _pct_change(values: List[float], periods: int) -> float:
    if len(values) <= periods:
        return 0.0
    base = values[-1 - periods]
    if base == 0.0:
        return 0.0
    return float((values[-1] - base) / base)


def _extract_ml_closes(price: float, last_price: Optional[float], candle_history: Optional[List[Dict[str, Any]]]) -> List[float]:
    closes: List[float] = []
    for candle in candle_history or []:
        close = _safe_float((candle or {}).get("close"), 0.0)
        if close > 0.0:
            closes.append(close)
    if not closes and last_price not in (None, 0):
        closes.append(float(last_price or 0.0))
    if price > 0.0 and (not closes or closes[-1] != float(price)):
        closes.append(float(price))
    return closes[-64:]


def build_live_ml_features(
    price: float,
    last_price: Optional[float],
    candle_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, float]:
    """Build live ML features with training-compatible semantics.

    This fixes the earlier placeholder feature bug where live inference used
    price as ema_fast, last_price as ema_slow, and rsi=0. Those values did not
    match training rows and made ML confidence unreliable.
    """
    closes = _extract_ml_closes(price, last_price, candle_history)
    signal = 0.0 if last_price in (None, 0) else (price - float(last_price or 0.0)) / float(last_price or price or 1.0)

    ema_fast = _ema(closes, 12) if closes else float(price)
    ema_slow = _ema(closes, 26) if closes else float(last_price or price)
    ema_spread = 0.0 if ema_slow == 0.0 else (ema_fast - ema_slow) / ema_slow
    rsi = _rsi(closes, 14)

    price_change_1 = _pct_change(closes, 1) if len(closes) >= 2 else float(signal)
    price_change_2 = _pct_change(closes, 2)
    price_change_3 = _pct_change(closes, 3)
    momentum_3 = price_change_3
    slope_3 = ((closes[-1] - closes[-3]) / closes[-3] / 2.0) if len(closes) >= 3 and closes[-3] else price_change_1

    last3 = closes[-3:] if len(closes) >= 3 else []
    last4 = closes[-4:] if len(closes) >= 4 else []
    three_rising = bool(last3 and last3[0] < last3[1] < last3[2])
    three_falling = bool(last3 and last3[0] > last3[1] > last3[2])
    reversal_after_two_decline = bool(last4 and last4[0] > last4[1] > last4[2] and last4[3] > last4[2])
    reversal_after_two_rise = bool(last4 and last4[0] < last4[1] < last4[2] and last4[3] < last4[2])
    short_momentum_burst = bool(price_change_1 > 0.0 and price_change_2 > 0.0 and price_change_3 > 0.0)
    short_exhaustion = bool(price_change_1 < 0.0 and price_change_2 < 0.0 and price_change_3 < 0.0)

    highs = [_safe_float((c or {}).get("high"), 0.0) for c in (candle_history or [])[-3:]]
    lows = [_safe_float((c or {}).get("low"), 0.0) for c in (candle_history or [])[-3:]]
    if not any(highs):
        highs = list(last3)
    if not any(lows):
        lows = list(last3)
    higher_highs = bool(len(highs) >= 3 and highs[0] < highs[1] < highs[2])
    higher_lows = bool(len(lows) >= 3 and lows[0] < lows[1] < lows[2])
    lower_highs = bool(len(highs) >= 3 and highs[0] > highs[1] > highs[2])
    lower_lows = bool(len(lows) >= 3 and lows[0] > lows[1] > lows[2])

    return {
        "ema_fast": float(ema_fast),
        "ema_slow": float(ema_slow),
        "ema_spread": float(ema_spread),
        "rsi": float(rsi),
        "price_change_1": float(price_change_1),
        "price_change_2": float(price_change_2),
        "price_change_3": float(price_change_3),
        "momentum_3": float(momentum_3),
        "slope_3": float(slope_3),
        "pattern_three_rising": 1.0 if three_rising else 0.0,
        "pattern_three_falling": 1.0 if three_falling else 0.0,
        "pattern_reversal_after_two_decline": 1.0 if reversal_after_two_decline else 0.0,
        "pattern_reversal_after_two_rise": 1.0 if reversal_after_two_rise else 0.0,
        "pattern_short_momentum_burst": 1.0 if short_momentum_burst else 0.0,
        "pattern_short_exhaustion": 1.0 if short_exhaustion else 0.0,
        "higher_highs": 1.0 if higher_highs else 0.0,
        "higher_lows": 1.0 if higher_lows else 0.0,
        "lower_highs": 1.0 if lower_highs else 0.0,
        "lower_lows": 1.0 if lower_lows else 0.0,
    }


def infer_ml_signal(
    snapshot: Dict[str, object],
    last_price: Optional[float],
    candle_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, object]:
    runtime = _load_ml_runtime()
    if not runtime["active"]:
        return {
            "ml_scoring_active": False,
            "model_score": None,
            "ml_signal_score": None,
            "decision_path": "signal-only fallback",
            "ml_inference_status": "unavailable",
            "ml_inference_reason": runtime["reason"],
            "ml_model_artifact_path": str(ML_MODEL_PATH),
            "ml_feature_columns": ML_COLUMNS,
            "ml_feature_coverage": 0.0,
        }

    price = float(snapshot.get("price") or 0.0)
    features = build_live_ml_features(price, last_price, candle_history)
    history_len = len(_extract_ml_closes(price, last_price, candle_history))
    coverage = 1.0 if history_len >= 4 else 0.55 if history_len >= 2 else 0.25
    vector = [[features[col] for col in ML_COLUMNS]]
    model = runtime["model"]
    classes = list(getattr(model, "classes_", []))
    if hasattr(model, "predict_proba") and 1 in classes:
        probs = model.predict_proba(vector)[0]
        up_idx = classes.index(1)
        up_prob = float(probs[up_idx])
    else:
        pred = float(model.predict(vector)[0])
        up_prob = 1.0 if pred > 0 else 0.0

    return {
        "ml_scoring_active": True,
        "model_score": round(up_prob, 4),
        "ml_signal_score": round((up_prob - 0.5) * 2.0, 6),
        "decision_path": "ml+signal",
        "ml_inference_status": "active",
        "ml_inference_reason": "loaded real model artifact",
        "ml_model_artifact_path": str(ML_MODEL_PATH),
        "ml_feature_columns": ML_COLUMNS,
        "ml_feature_coverage": round(coverage, 4),
        "ml_live_feature_sample": {k: round(float(v), 6) for k, v in features.items() if k in {"ema_fast", "ema_slow", "ema_spread", "rsi", "price_change_1", "price_change_2", "price_change_3"}},
        "ml_live_history_len": history_len,
    }


def _close_only_pattern_payload(
    candle_history: List[Dict[str, Any]],
    symbol: Any,
    candle_source: str,
    candle_confidence: Any,
) -> Dict[str, Any]:
    closes = [float(c.get("close") or 0.0) for c in candle_history[-4:] if c]
    detected_patterns: List[str] = []
    pattern_score = 0.0
    if len(closes) >= 3:
        last_three = closes[-3:]
        if last_three[0] < last_three[1] < last_three[2]:
            detected_patterns.append("close_three_rising")
            pattern_score = LIVE_PATTERN_SCORE_MAX_ABS
        elif last_three[0] > last_three[1] > last_three[2]:
            detected_patterns.append("close_three_falling")
            pattern_score = -LIVE_PATTERN_SCORE_MAX_ABS
    if not detected_patterns and len(closes) >= 2:
        last_two = closes[-2:]
        if last_two[0] < last_two[1]:
            detected_patterns.append("close_bootstrap_rising")
            pattern_score = LIVE_PATTERN_SCORE_MAX_ABS
        elif last_two[0] > last_two[1]:
            detected_patterns.append("close_bootstrap_falling")
            pattern_score = -LIVE_PATTERN_SCORE_MAX_ABS
    if not detected_patterns and candle_history:
        last_candle = candle_history[-1] or {}
        open_ = float(last_candle.get("open") or 0.0)
        close = float(last_candle.get("close") or 0.0)
        if open_ and close > open_:
            detected_patterns.append("close_bootstrap_rising")
            pattern_score = LIVE_PATTERN_SCORE_MAX_ABS
        elif open_ and close < open_:
            detected_patterns.append("close_bootstrap_falling")
            pattern_score = -LIVE_PATTERN_SCORE_MAX_ABS
    if len(closes) >= 4:
        prev_three = closes[-4:-1]
        last_close = closes[-1]
        if prev_three[0] > prev_three[1] > prev_three[2] and last_close > prev_three[-1]:
            detected_patterns.append("close_reversal_after_two_decline")
            pattern_score = max(pattern_score, 0.01)
        elif prev_three[0] < prev_three[1] < prev_three[2] and last_close < prev_three[-1]:
            detected_patterns.append("close_reversal_after_two_rise")
            pattern_score = min(pattern_score, -0.01)
    pattern_dir = 1 if pattern_score > 0 else -1 if pattern_score < 0 else 0
    return {
        "pattern_flags": {},
        "pattern_dir": pattern_dir,
        "pattern_strength": round(abs(pattern_score) / LIVE_PATTERN_SCORE_MAX_ABS, 4) if pattern_score else 0.0,
        "pattern_contribution": round(pattern_score, 6),
        "pattern_confirmation": {"satisfied": bool(detected_patterns), "signals": ["close_only_three_step"] if detected_patterns else []},
        "pattern_debug": {"engine_mode": "close_only_3step", "reason": "price_only_live_feed_no_real_ohlc", "detected_patterns": detected_patterns},
        "matched_context": {
            "symbol": symbol,
            "timeframe": "live_tick",
            "candle_source": candle_source,
            "candle_confidence": candle_confidence,
        },
        "detected_patterns": detected_patterns,
        "pattern_score": round(pattern_score, 6),
        "pattern_engine_mode": "close_only_3step",
        "strat_pattern": None,
        "strat_available": False,
    }



def _real_ohlc_pattern_payload(
    candle_history: List[Dict[str, Any]],
    symbol: Any,
    adjusted_signal_score: float,
    ml_result: Dict[str, object],
    snapshot: Dict[str, object],
    candle_source: str,
    candle_confidence: Any,
) -> Dict[str, Any]:
    pattern_result = evaluate_patterns(
        candle_history,
        {
            "symbol": symbol,
            "timeframe": "live_tick",
            "ml_signal_score": ml_result.get("ml_signal_score") or 0.0,
            "policy_signal_score": adjusted_signal_score,
            "orion_bias": snapshot.get("orion_bias") or 0.0,
            "volume_confirmation": snapshot.get("volume_confirmation") or 0.0,
            "candle_source": candle_source,
            "candle_confidence": candle_confidence,
        },
    )
    matched_patterns = list(pattern_result.get("pattern_debug", {}).get("matched_patterns") or [])
    strat_pattern = next((name for name in matched_patterns if name.startswith("strat_")), None)
    pattern_score = max(-LIVE_PATTERN_SCORE_MAX_ABS, min(LIVE_PATTERN_SCORE_MAX_ABS, float(pattern_result.get("pattern_contribution") or 0.0)))
    pattern_result.update(
        {
            "detected_patterns": matched_patterns,
            "pattern_score": round(pattern_score, 6),
            "pattern_engine_mode": "ohlc_pattern_engine",
            "strat_pattern": strat_pattern,
            "strat_available": True,
        }
    )
    pattern_result["pattern_contribution"] = round(pattern_score, 6)
    return pattern_result



def build_live_pattern_payload(
    snapshot: Dict[str, object],
    candle_history: Optional[List[Dict[str, Any]]],
    adjusted_signal_score: float,
    ml_result: Dict[str, object],
    candle_source: str,
    candle_confidence: Any,
) -> Dict[str, Any]:
    history = candle_history or []
    if candle_source == "real_ohlc":
        return _real_ohlc_pattern_payload(
            history,
            snapshot.get("symbol"),
            adjusted_signal_score,
            ml_result,
            snapshot,
            candle_source,
            candle_confidence,
        )
    return _close_only_pattern_payload(history, snapshot.get("symbol"), candle_source, candle_confidence)




def _signal_direction(score: float, threshold: float, position_state: float = 0.0) -> str:
    if score > threshold:
        return "BUY"
    if score < -threshold:
        return "SELL" if position_state > 0 else "WAIT"
    return "WAIT"


def _add_evidence(evidence: List[Dict[str, object]], source: str, direction: str, score: float, weight: float, reason: str) -> None:
    bounded = max(0.0, min(1.0, abs(float(score))))
    evidence.append(
        {
            "source": source,
            "direction": direction,
            "score": round(bounded, 6),
            "weight": round(float(weight), 6),
            "weighted_score": round(bounded * float(weight), 6),
            "reason": reason,
        }
    )




def _append_decision_trace(decision_path_trace: List[Dict[str, Any]], stage: str, **fields: Any) -> None:
    """Append a human/debug friendly breadcrumb for the decision combat log.

    This is intentionally lightweight and JSON-serializable so paper_decisions,
    company packets, Axiom reviews, and future RPG/XP attribution can explain
    exactly which stage changed BUY/SELL/WAIT/HOLD_POSITION.
    """
    item: Dict[str, Any] = {"stage": stage}
    item.update(fields)
    decision_path_trace.append(item)


def build_decision_evidence(
    adjusted_signal_score: float,
    threshold: float,
    position_state: float,
    ml_result: Dict[str, object],
    pattern_result: Dict[str, Any],
    policy_name: str,
) -> Dict[str, object]:
    evidence: List[Dict[str, object]] = []
    signal_strength = min(1.0, abs(adjusted_signal_score) / max(threshold, 1e-9))
    _add_evidence(evidence, "policy_signal", _signal_direction(adjusted_signal_score, threshold, position_state), signal_strength, 1.0, f"policy signal under {policy_name}")

    ml_score = ml_result.get("ml_signal_score")
    if ml_result.get("ml_scoring_active") and ml_score is not None:
        ml_score_float = float(ml_score)
        _add_evidence(evidence, "ml_model", _signal_direction(ml_score_float, 0.10, position_state), abs(ml_score_float), 1.2, "live ML model probability converted to directional score")
    else:
        _add_evidence(evidence, "ml_model", "WAIT", 0.35, 0.8, str(ml_result.get("ml_inference_reason") or "ML unavailable"))

    pattern_dir = int(pattern_result.get("pattern_dir") or 0)
    pattern_strength = float(pattern_result.get("pattern_strength") or 0.0)
    if pattern_result.get("pattern_confirmation", {}).get("satisfied") and pattern_dir != 0:
        _add_evidence(evidence, "pattern_engine", "BUY" if pattern_dir > 0 else "SELL", pattern_strength, 1.4, "confirmed 3-step/pattern evidence")
    else:
        _add_evidence(evidence, "pattern_engine", "WAIT", 0.55, 1.1, "pattern confirmation missing or weak")

    totals = {"BUY": 0.0, "SELL": 0.0, "WAIT": 0.0}
    for item in evidence:
        direction = str(item.get("direction") or "WAIT")
        if direction not in totals:
            direction = "WAIT"
        totals[direction] += float(item.get("weighted_score") or 0.0)
    totals = {k: round(v, 6) for k, v in totals.items()}
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    winner, winner_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = round(winner_score - runner_up_score, 6)
    if winner in {"BUY", "SELL"} and margin < 0.15:
        final = "WAIT"
        reason = f"{winner} evidence margin {margin} below 0.15 safety threshold"
    else:
        final = winner
        reason = f"{winner} has strongest weighted evidence margin {margin}"
    if final == "SELL" and position_state <= 0:
        final = "WAIT"
        reason = "flat account blocks SELL despite evidence"
    return {
        "decision_evidence": evidence,
        "evidence_scores": totals,
        "evidence_winner": winner,
        "evidence_margin": margin,
        "evidence_decision": final,
        "evidence_reason": reason,
    }


def build_decision(
    snapshot: Dict[str, object],
    company_id: str,
    last_price: Optional[float],
    candle_history: Optional[List[Dict[str, Any]]] = None,
) -> DecisionResult:
    price = snapshot.get("price") or 0.0
    latest_candle = (candle_history or [None])[-1] or {}
    candle_source = snapshot.get("candle_source") or latest_candle.get("candle_source") or "unknown"
    candle_confidence = snapshot.get("candle_confidence")
    if candle_confidence in (None, ""):
        candle_confidence = latest_candle.get("candle_confidence", 0.0)
    policy = company_policy(company_id)
    position_state = float(snapshot.get("position_state") or 0.0)
    decision_path_trace: List[Dict[str, Any]] = []
    _append_decision_trace(
        decision_path_trace,
        "input_context",
        company_id=company_id,
        symbol=snapshot.get("symbol"),
        price=float(price or 0.0),
        last_price=None if last_price is None else float(last_price),
        position_state=position_state,
        candle_source=str(candle_source),
        candle_confidence=_safe_float(candle_confidence, 0.0),
        policy_name=str(policy["policy_name"]),
    )
    raw_signal_score = compute_signal(snapshot, last_price)
    _append_decision_trace(
        decision_path_trace,
        "base_signal",
        raw_signal_score=round(raw_signal_score, 6),
        reason="price-vs-last_price policy signal",
    )
    if (
        raw_signal_score == 0.0
        and str(candle_source).lower() == "real_ohlc"
        and float(candle_confidence or 0.0) >= 0.7
    ):
        candle_open = float(latest_candle.get("open") or 0.0)
        candle_close = float(latest_candle.get("close") or price or 0.0)
        if candle_open > 0.0 and candle_close != candle_open:
            raw_signal_score = (candle_close - candle_open) / candle_open
            _append_decision_trace(
                decision_path_trace,
                "real_ohlc_signal_override",
                raw_signal_score=round(raw_signal_score, 6),
                reason="computed signal from latest real OHLC candle open/close because last_price signal was zero",
            )
        elif len(candle_history or []) >= 2:
            prev_close = float((candle_history or [])[ -2].get("close") or 0.0)
            if prev_close > 0.0 and candle_close != prev_close:
                raw_signal_score = (candle_close - prev_close) / prev_close
                _append_decision_trace(
                    decision_path_trace,
                    "real_ohlc_signal_override",
                    raw_signal_score=round(raw_signal_score, 6),
                    reason="computed signal from prior real OHLC close because last_price signal was zero",
                )
    adjusted_signal_score = raw_signal_score * float(policy["signal_multiplier"])
    threshold = float(policy["threshold"])
    signal_decision = map_score_to_decision(adjusted_signal_score, threshold, position_state)
    _append_decision_trace(
        decision_path_trace,
        "policy_signal",
        raw_signal_score=round(raw_signal_score, 6),
        adjusted_signal_score=round(adjusted_signal_score, 6),
        threshold=threshold,
        signal_multiplier=float(policy["signal_multiplier"]),
        signal_decision=signal_decision,
        reason="mapped adjusted policy signal to preliminary decision",
    )
    ml_result = infer_ml_signal(snapshot, last_price, candle_history)
    _append_decision_trace(
        decision_path_trace,
        "ml_inference",
        active=bool(ml_result.get("ml_scoring_active")),
        model_score=ml_result.get("model_score"),
        ml_signal_score=ml_result.get("ml_signal_score"),
        feature_coverage=ml_result.get("ml_feature_coverage"),
        history_len=ml_result.get("ml_live_history_len"),
        status=ml_result.get("ml_inference_status"),
        reason=ml_result.get("ml_inference_reason"),
    )

    decision = signal_decision
    notes = f"signal-only scoring under {policy['policy_name']}"
    scoring_method = "signal_only"
    decision_before_ml_confirmation = decision
    if ml_result["ml_scoring_active"]:
        model_score = float(ml_result["model_score"])
        if signal_decision == "BUY" and model_score < 0.5:
            decision = "HOLD_POSITION" if position_state > 0 else "WAIT"
        elif signal_decision == "SELL" and model_score > 0.5:
            decision = "HOLD_POSITION" if position_state > 0 else "WAIT"
        notes = f"signal confirmed by real ML artifact under {policy['policy_name']}"
        scoring_method = "ml_plus_signal"
    _append_decision_trace(
        decision_path_trace,
        "ml_confirmation_filter",
        before=decision_before_ml_confirmation,
        after=decision,
        active=bool(ml_result.get("ml_scoring_active")),
        model_score=ml_result.get("model_score"),
        scoring_method=scoring_method,
        reason="ML can demote policy BUY/SELL when model probability disagrees",
    )

    confidence_base = abs(adjusted_signal_score) / threshold if threshold > 0 else 0.0
    if ml_result["ml_scoring_active"] and ml_result["model_score"] is not None:
        ml_confidence = abs(float(ml_result["model_score"]) - 0.5) * 2.0
        confidence = min((confidence_base + ml_confidence) / 2.0, 1.0)
    else:
        confidence = min(confidence_base, 1.0)

    pattern_result = build_live_pattern_payload(
        snapshot,
        candle_history,
        adjusted_signal_score,
        ml_result,
        str(candle_source),
        candle_confidence,
    )
    _append_decision_trace(
        decision_path_trace,
        "pattern_engine",
        pattern_engine_mode=pattern_result.get("pattern_engine_mode"),
        detected_patterns=list(pattern_result.get("detected_patterns") or []),
        pattern_dir=pattern_result.get("pattern_dir"),
        pattern_strength=pattern_result.get("pattern_strength"),
        pattern_score=pattern_result.get("pattern_score"),
        confirmation_satisfied=bool((pattern_result.get("pattern_confirmation") or {}).get("satisfied")),
        reason="evaluated live pattern/3-step confirmation evidence",
    )
    evidence_result = build_decision_evidence(
        adjusted_signal_score,
        threshold,
        position_state,
        ml_result,
        pattern_result,
        str(policy["policy_name"]),
    )
    _append_decision_trace(
        decision_path_trace,
        "evidence_fusion",
        scores=evidence_result.get("evidence_scores"),
        winner=evidence_result.get("evidence_winner"),
        margin=evidence_result.get("evidence_margin"),
        evidence_decision=evidence_result.get("evidence_decision"),
        reason=evidence_result.get("evidence_reason"),
    )
    decision_before_evidence = decision
    scoring_method_before_evidence = scoring_method
    if evidence_result["evidence_decision"] in {"BUY", "SELL"}:
        decision = str(evidence_result["evidence_decision"])
        notes = str(evidence_result["evidence_reason"])
        scoring_method = "weighted_evidence_fusion"
    elif decision in {"BUY", "SELL"}:
        notes = f"{notes}; evidence caution: {evidence_result['evidence_reason']}"
    else:
        decision = "HOLD_POSITION" if position_state > 0 else "WAIT"
        notes = str(evidence_result["evidence_reason"])
        scoring_method = "weighted_evidence_fusion"
    _append_decision_trace(
        decision_path_trace,
        "evidence_application",
        before=decision_before_evidence,
        after=decision,
        scoring_before=scoring_method_before_evidence,
        scoring_after=scoring_method,
        reason=notes,
    )
    demoted_by_pattern_gate = False
    decision_before_pattern_gate = decision
    if decision in {"BUY", "SELL"} and (
        not pattern_result["detected_patterns"]
        or not pattern_result["pattern_confirmation"].get("satisfied")
    ):
        demoted_by_pattern_gate = True
        decision = "HOLD_POSITION" if position_state > 0 else "WAIT"
    _append_decision_trace(
        decision_path_trace,
        "pattern_gate",
        before=decision_before_pattern_gate,
        after=decision,
        demoted=demoted_by_pattern_gate,
        confirmation_satisfied=bool((pattern_result.get("pattern_confirmation") or {}).get("satisfied")),
        detected_patterns=list(pattern_result.get("detected_patterns") or []),
        reason="BUY/SELL requires detected pattern confirmation unless later recovery deliberately re-promotes",
    )
    pattern_recovery_before = decision
    pattern_recovery_triggered = False
    pattern_recovery_mode = None
    if decision == "WAIT" and position_state <= 0:
        pattern_aligned = (
            pattern_result["pattern_dir"] != 0
            and pattern_result["pattern_confirmation"].get("satisfied")
            and (
                adjusted_signal_score == 0.0
                or (adjusted_signal_score > 0 and pattern_result["pattern_dir"] > 0)
                or (adjusted_signal_score < 0 and pattern_result["pattern_dir"] < 0)
            )
        )
        # Intentional recovery path: a high-confidence real-OHLC signal can
        # re-promote a decision that was WAIT or demoted by the pattern gate.
        # The decision_path_trace records this explicitly so Axiom/operator
        # review can decide later whether this behavior is useful or reckless.
        real_ohlc_bootstrap = (
            pattern_result["matched_context"]["candle_source"] == "real_ohlc"
            and float(pattern_result["matched_context"]["candle_confidence"] or 0.0) >= 0.7
            and adjusted_signal_score != 0.0
        )
        if pattern_aligned:
            if adjusted_signal_score > 0:
                decision = "BUY"
            elif adjusted_signal_score < 0:
                decision = "SELL"
            else:
                decision = "BUY" if pattern_result["pattern_dir"] > 0 else "SELL"
            notes = f"signal + pattern confirmation under {policy['policy_name']}"
            scoring_method = "signal_plus_pattern"
            pattern_recovery_triggered = True
            pattern_recovery_mode = "signal_plus_pattern"
        elif real_ohlc_bootstrap and (signal_decision == "WAIT" or demoted_by_pattern_gate):
            decision = "BUY" if adjusted_signal_score > 0 else "SELL"
            notes = f"signal + real_ohlc bootstrap under {policy['policy_name']}"
            scoring_method = "signal_plus_real_ohlc"
            pattern_recovery_triggered = True
            pattern_recovery_mode = "signal_plus_real_ohlc"
    _append_decision_trace(
        decision_path_trace,
        "pattern_recovery",
        before=pattern_recovery_before,
        after=decision,
        triggered=pattern_recovery_triggered,
        mode=pattern_recovery_mode,
        demoted_by_pattern_gate=demoted_by_pattern_gate,
        reason="pattern alignment or real-OHLC bootstrap can re-promote WAIT after gate review",
    )

    forced_exit_reason = ""
    entry_price = float(snapshot.get("entry_price") or 0.0)
    held_ticks = int(snapshot.get("held_ticks") or 0)
    pnl_pct = ((price - entry_price) / entry_price) if entry_price > 0.0 else 0.0
    bearish_pattern = bool(pattern_result["pattern_confirmation"].get("satisfied")) and int(pattern_result["pattern_dir"] or 0) < 0
    negative_signal = adjusted_signal_score <= -(threshold * EXIT_NEGATIVE_SIGNAL_MULTIPLIER)
    take_profit_ready = entry_price > 0.0 and pnl_pct >= EXIT_TAKE_PROFIT_PCT and adjusted_signal_score <= max(threshold * 0.25, 0.0)
    stop_loss_hit = entry_price > 0.0 and pnl_pct <= -EXIT_STOP_LOSS_PCT
    stale_position = held_ticks >= EXIT_MAX_HOLD_TICKS and adjusted_signal_score <= max(threshold * 0.25, 0.0)

    if decision == "SELL" and position_state <= 0:
        decision = "WAIT"
        notes = f"flat account blocks sell under {policy['policy_name']}"
        scoring_method = "flat_account_sell_block"
        _append_decision_trace(
            decision_path_trace,
            "flat_account_sell_block",
            before="SELL",
            after=decision,
            position_state=position_state,
            reason="cannot SELL while flat",
        )

    decision_before_exit_rules = decision
    if position_state > 0:
        if stop_loss_hit:
            decision = "SELL"
            forced_exit_reason = "stop_loss"
            notes = f"risk stop triggered under {policy['policy_name']}"
            scoring_method = "risk_exit"
        elif take_profit_ready:
            decision = "SELL"
            forced_exit_reason = "take_profit"
            notes = f"take profit triggered under {policy['policy_name']}"
            scoring_method = "profit_exit"
        elif stale_position and (decision in {"WAIT", "HOLD_POSITION"} or negative_signal):
            decision = "SELL"
            forced_exit_reason = "max_hold"
            notes = f"max hold exit triggered under {policy['policy_name']}"
            scoring_method = "time_exit"
        elif bearish_pattern and negative_signal:
            decision = "SELL"
            forced_exit_reason = "signal_reversal"
            notes = f"bearish reversal exit triggered under {policy['policy_name']}"
            scoring_method = "reversal_exit"
    _append_decision_trace(
        decision_path_trace,
        "exit_rules",
        before=decision_before_exit_rules,
        after=decision,
        forced_exit_reason=forced_exit_reason or None,
        entry_price=round(entry_price, 8),
        held_ticks=held_ticks,
        pnl_pct=round(pnl_pct, 6),
        stop_loss_hit=bool(stop_loss_hit),
        take_profit_ready=bool(take_profit_ready),
        stale_position=bool(stale_position),
        bearish_pattern=bool(bearish_pattern),
        negative_signal=bool(negative_signal),
        reason="checked stop-loss, take-profit, max-hold, and reversal exits",
    )

    decision_before_final_ml_guard = decision
    if (
        not forced_exit_reason
        and decision in {"BUY", "SELL"}
        and pattern_result["matched_context"]["candle_source"] == "real_ohlc"
        and pattern_result["detected_patterns"]
        and pattern_result["pattern_confirmation"].get("satisfied")
        and ml_result["ml_scoring_active"]
        and ml_result["model_score"] is not None
    ):
        model_score = float(ml_result["model_score"])
        if decision == "BUY" and model_score <= 0.55:
            decision = "HOLD_POSITION" if position_state > 0 else "WAIT"
        elif decision == "SELL" and model_score >= 0.45:
            decision = "HOLD_POSITION" if position_state > 0 else "WAIT"
    _append_decision_trace(
        decision_path_trace,
        "final_ml_guard",
        before=decision_before_final_ml_guard,
        after=decision,
        active=bool(
            not forced_exit_reason
            and pattern_result["matched_context"]["candle_source"] == "real_ohlc"
            and pattern_result["detected_patterns"]
            and pattern_result["pattern_confirmation"].get("satisfied")
            and ml_result["ml_scoring_active"]
            and ml_result["model_score"] is not None
        ),
        model_score=ml_result.get("model_score"),
        reason="final ML sanity guard can demote weak BUY/SELL after pattern confirmation",
    )
    _append_decision_trace(
        decision_path_trace,
        "final_decision",
        final_decision=decision,
        scoring_method=scoring_method,
        notes=notes,
        confidence=round(confidence, 4),
        reason="final output after policy, ML, evidence, pattern gate, recovery, exits, and final guard",
    )

    result = DecisionResult(
        {
            "timestamp": snapshot.get("timestamp") or datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
            "company_id": company_id,
            "symbol": snapshot.get("symbol"),
            "price": price,
            "decision": decision,
            "confidence": round(confidence, 4),
            "signal_score": round(raw_signal_score, 6),
            "policy_signal_score": round(adjusted_signal_score, 6),
            "threshold_used": threshold,
            "policy_name": policy["policy_name"],
            "company_posture": policy["company_posture"],
            "size_multiplier": float(policy["size_multiplier"]),
            "sizing_rationale": policy["sizing_rationale"],
            "notes": notes,
            "scoring_method": scoring_method,
            "decision_path_trace": decision_path_trace,
            "decision_trace_summary": " -> ".join(str(item.get("stage")) for item in decision_path_trace),
            "decision_evidence": evidence_result["decision_evidence"],
            "evidence_scores": evidence_result["evidence_scores"],
            "evidence_winner": evidence_result["evidence_winner"],
            "evidence_margin": evidence_result["evidence_margin"],
            "evidence_reason": evidence_result["evidence_reason"],
            "pattern_flags": pattern_result["pattern_flags"],
            "pattern_dir": pattern_result["pattern_dir"],
            "pattern_strength": pattern_result["pattern_strength"],
            "pattern_contribution": pattern_result["pattern_contribution"],
            "pattern_confirmation": pattern_result["pattern_confirmation"],
            "pattern_debug": pattern_result["pattern_debug"],
            "matched_context": pattern_result["matched_context"],
            "candle_source": pattern_result["matched_context"]["candle_source"],
            "candle_confidence": pattern_result["matched_context"]["candle_confidence"],
            "detected_patterns": pattern_result["detected_patterns"],
            "pattern_score": pattern_result["pattern_score"],
            "pattern_engine_mode": pattern_result["pattern_engine_mode"],
            "strat_pattern": pattern_result["strat_pattern"],
            "strat_available": pattern_result["strat_available"],
            "entry_price": entry_price,
            "held_ticks": held_ticks,
            "pnl_pct": round(pnl_pct, 6),
            "forced_exit_reason": forced_exit_reason or None,
        }
    )
    result.update(ml_result)
    result["signal_scoring_active"] = True
    return result
