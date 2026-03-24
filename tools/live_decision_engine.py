"""Decision engine for live paper trading."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, List, Any

from tools.pattern_engine import evaluate_patterns

LIVE_PATTERN_SCORE_MAX_ABS = 0.015

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



def map_score_to_decision(score: float, threshold: float) -> str:
    if score > threshold:
        return "BUY"
    if score < -threshold:
        return "SELL"
    return "HOLD"



def build_live_ml_features(price: float, last_price: Optional[float]) -> Dict[str, float]:
    signal = 0.0 if last_price in (None, 0) else (price - last_price) / last_price
    higher = 1.0 if signal > 0 else 0.0
    lower = 1.0 if signal < 0 else 0.0
    return {
        "ema_fast": float(price),
        "ema_slow": float(last_price or price),
        "ema_spread": float(price - (last_price or price)),
        "rsi": 0.0,
        "price_change_1": float(signal),
        "price_change_2": 0.0,
        "price_change_3": 0.0,
        "momentum_3": float(signal),
        "slope_3": float(signal),
        "pattern_three_rising": 0.0,
        "pattern_three_falling": 0.0,
        "pattern_reversal_after_two_decline": 0.0,
        "pattern_reversal_after_two_rise": 0.0,
        "pattern_short_momentum_burst": higher,
        "pattern_short_exhaustion": lower,
        "higher_highs": higher,
        "higher_lows": higher,
        "lower_highs": lower,
        "lower_lows": lower,
    }



def infer_ml_signal(snapshot: Dict[str, object], last_price: Optional[float]) -> Dict[str, object]:
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
    features = build_live_ml_features(price, last_price)
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
        "ml_feature_coverage": 1.0,
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
    raw_signal_score = compute_signal(snapshot, last_price)
    adjusted_signal_score = raw_signal_score * float(policy["signal_multiplier"])
    threshold = float(policy["threshold"])
    signal_decision = map_score_to_decision(adjusted_signal_score, threshold)
    ml_result = infer_ml_signal(snapshot, last_price)

    decision = signal_decision
    notes = f"signal-only scoring under {policy['policy_name']}"
    scoring_method = "signal_only"
    if ml_result["ml_scoring_active"]:
        model_score = float(ml_result["model_score"])
        if signal_decision == "BUY" and model_score < 0.5:
            decision = "HOLD"
        elif signal_decision == "SELL" and model_score > 0.5:
            decision = "HOLD"
        notes = f"signal confirmed by real ML artifact under {policy['policy_name']}"
        scoring_method = "ml_plus_signal"

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
    if decision in {"BUY", "SELL"} and (
        pattern_result["matched_context"]["candle_source"] != "real_ohlc"
        or not pattern_result["detected_patterns"]
        or not pattern_result["pattern_confirmation"].get("satisfied")
    ):
        decision = "HOLD"
    if (
        decision in {"BUY", "SELL"}
        and pattern_result["matched_context"]["candle_source"] == "real_ohlc"
        and pattern_result["detected_patterns"]
        and pattern_result["pattern_confirmation"].get("satisfied")
        and ml_result["ml_scoring_active"]
        and ml_result["model_score"] is not None
    ):
        model_score = float(ml_result["model_score"])
        if decision == "BUY" and model_score <= 0.55:
            decision = "HOLD"
        elif decision == "SELL" and model_score >= 0.45:
            decision = "HOLD"

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
        }
    )
    result.update(ml_result)
    result["signal_scoring_active"] = True
    return result
