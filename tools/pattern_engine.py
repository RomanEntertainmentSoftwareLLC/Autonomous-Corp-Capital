"""Deterministic candle-pattern engine for live ranking features."""

from __future__ import annotations

from typing import Any, Dict, List

CANDLE_SETTINGS: Dict[str, Dict[str, Any]] = {
    "BodyLong": {"avg_period": 10, "factor": 1.0, "range_type": "RealBody"},
    "BodyShort": {"avg_period": 10, "factor": 1.0, "range_type": "RealBody"},
    "BodyDoji": {"avg_period": 10, "factor": 0.1, "range_type": "HighLow"},
    "ShadowVeryShort": {"avg_period": 10, "factor": 0.1, "range_type": "HighLow"},
    "Near": {"avg_period": 5, "factor": 0.2, "range_type": "HighLow"},
    "Far": {"avg_period": 5, "factor": 0.6, "range_type": "HighLow"},
    "Equal": {"avg_period": 5, "factor": 0.05, "range_type": "HighLow"},
}
STAR_PENETRATION = 0.3
PATTERN_WEIGHT = 0.04
PATTERN_CLAMP = 0.10
SUPPORTED_PATTERNS = [
    "strat_212_bull",
    "strat_212_bear",
    "strat_312_bull",
    "strat_312_bear",
    "strat_22_continuation_bull",
    "strat_22_continuation_bear",
    "strat_22_reversal_bull",
    "strat_22_reversal_bear",
    "strat_122_revstrat_bull",
    "strat_122_revstrat_bear",
    "strat_13_revstrat_bull",
    "strat_13_revstrat_bear",
    "morning_star",
    "evening_star",
    "three_white_soldiers",
    "three_black_crows",
    "three_inside_up",
    "three_inside_down",
    "three_outside_up",
    "three_outside_down",
    "abandoned_baby_bull",
    "abandoned_baby_bear",
]


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0



def _normalize_candle_quality(context: Dict[str, Any]) -> Dict[str, Any]:
    source = str(context.get("candle_source") or "unknown")
    confidence = _safe_float(context.get("candle_confidence"))
    if source == "pseudo_snapshot_ohlc":
        confidence = min(max(confidence or 0.35, 0.0), 0.49)
    elif source == "real_ohlc":
        confidence = min(max(confidence or 1.0, 0.5), 1.0)
    else:
        source = "unknown"
        confidence = 0.0
    return {"candle_source": source, "candle_confidence": round(confidence, 4)}



def _normalize_candle(raw: Dict[str, Any]) -> Dict[str, Any]:
    open_ = _safe_float(raw.get("open"))
    high = _safe_float(raw.get("high"))
    low = _safe_float(raw.get("low"))
    close = _safe_float(raw.get("close"))
    if high < max(open_, close):
        high = max(open_, close)
    if low > min(open_, close):
        low = min(open_, close)
    return {
        "timestamp": raw.get("timestamp"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "valid": high >= low and max(open_, close) <= high and min(open_, close) >= low,
    }



def real_body(candle: Dict[str, Any]) -> float:
    return abs(_safe_float(candle.get("close")) - _safe_float(candle.get("open")))



def upper_shadow(candle: Dict[str, Any]) -> float:
    return max(0.0, _safe_float(candle.get("high")) - max(_safe_float(candle.get("open")), _safe_float(candle.get("close"))))



def lower_shadow(candle: Dict[str, Any]) -> float:
    return max(0.0, min(_safe_float(candle.get("open")), _safe_float(candle.get("close"))) - _safe_float(candle.get("low")))



def high_low_range(candle: Dict[str, Any]) -> float:
    return max(0.0, _safe_float(candle.get("high")) - _safe_float(candle.get("low")))



def candle_color(candle: Dict[str, Any]) -> int:
    if _safe_float(candle.get("close")) > _safe_float(candle.get("open")):
        return 1
    if _safe_float(candle.get("close")) < _safe_float(candle.get("open")):
        return -1
    return 0



def real_body_gap_up(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    return min(current["open"], current["close"]) > max(previous["open"], previous["close"])



def real_body_gap_down(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    return max(current["open"], current["close"]) < min(previous["open"], previous["close"])



def candle_gap_up(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    return current["low"] > previous["high"]



def candle_gap_down(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
    return current["high"] < previous["low"]



def _range_value(candle: Dict[str, Any], range_type: str) -> float:
    if range_type == "RealBody":
        return real_body(candle)
    return high_low_range(candle)



def rolling_setting_average(candles: List[Dict[str, Any]], end_index: int, setting_name: str) -> float:
    setting = CANDLE_SETTINGS[setting_name]
    period = int(setting["avg_period"])
    start = max(0, end_index - period)
    window = candles[start:end_index]
    if not window:
        return 0.0
    values = [_range_value(candle, setting["range_type"]) for candle in window]
    return sum(values) / len(values)



def _threshold(candles: List[Dict[str, Any]], idx: int, setting_name: str) -> float:
    setting = CANDLE_SETTINGS[setting_name]
    return rolling_setting_average(candles, idx, setting_name) * float(setting["factor"])



def is_long_body(candles: List[Dict[str, Any]], idx: int) -> bool:
    return real_body(candles[idx]) >= _threshold(candles, idx, "BodyLong")



def is_short_body(candles: List[Dict[str, Any]], idx: int) -> bool:
    return real_body(candles[idx]) <= _threshold(candles, idx, "BodyShort")



def is_doji(candles: List[Dict[str, Any]], idx: int) -> bool:
    return real_body(candles[idx]) <= _threshold(candles, idx, "BodyDoji")



def is_very_short_upper_shadow(candles: List[Dict[str, Any]], idx: int) -> bool:
    return upper_shadow(candles[idx]) <= _threshold(candles, idx, "ShadowVeryShort")



def strat_bar_type(previous: Dict[str, Any], current: Dict[str, Any]) -> str:
    breaks_high = current["high"] > previous["high"]
    breaks_low = current["low"] < previous["low"]
    if breaks_high and breaks_low:
        return "3"
    if breaks_high:
        return "2U"
    if breaks_low:
        return "2D"
    return "1"



def _direction_from_bar_type(bar_type: str) -> int:
    if bar_type == "2U":
        return 1
    if bar_type == "2D":
        return -1
    return 0



def _detect_strat(candles: List[Dict[str, Any]], flags: Dict[str, int]) -> Dict[str, Any]:
    debug: Dict[str, Any] = {}
    if len(candles) < 4:
        return debug
    types = [strat_bar_type(candles[i - 1], candles[i]) for i in range(1, len(candles))]
    last_three = types[-3:]
    t1, t2, t3 = last_three
    debug["strat_last_three"] = last_three
    d1, d3 = _direction_from_bar_type(t1), _direction_from_bar_type(t3)

    if t1 in {"2U", "2D"} and t2 == "1" and t3 in {"2U", "2D"}:
        if d1 != 0 and d3 == d1:
            flags[f"strat_212_{'bull' if d3 > 0 else 'bear'}"] = 1
    if t1 == "3" and t2 == "1" and t3 in {"2U", "2D"}:
        flags[f"strat_312_{'bull' if d3 > 0 else 'bear'}"] = 1
    if t1 in {"2U", "2D"} and t2 in {"2U", "2D"}:
        if d1 == d3:
            flags[f"strat_22_continuation_{'bull' if d3 > 0 else 'bear'}"] = 1
        elif d1 != 0 and d3 != 0:
            flags[f"strat_22_reversal_{'bull' if d3 > 0 else 'bear'}"] = 1
    if t1 == "1" and t2 in {"2U", "2D"} and t3 in {"2U", "2D"} and _direction_from_bar_type(t2) != _direction_from_bar_type(t3):
        flags[f"strat_122_revstrat_{'bull' if d3 > 0 else 'bear'}"] = 1
    if t1 == "1" and t2 == "3":
        close_now = candles[-1]["close"]
        if close_now > candles[-2]["high"]:
            flags["strat_13_revstrat_bull"] = 1
        elif close_now < candles[-2]["low"]:
            flags["strat_13_revstrat_bear"] = 1
    return debug



def _detect_classical(candles: List[Dict[str, Any]], flags: Dict[str, int]) -> Dict[str, Any]:
    debug: Dict[str, Any] = {}
    if len(candles) < 3:
        return debug
    a, b, c = candles[-3], candles[-2], candles[-1]
    ai, bi, ci = len(candles) - 3, len(candles) - 2, len(candles) - 1
    body_mid_a = (a["open"] + a["close"]) / 2.0
    debug["classical_window"] = [a.get("timestamp"), b.get("timestamp"), c.get("timestamp")]

    if candle_color(a) == -1 and is_long_body(candles, ai) and is_short_body(candles, bi) and candle_color(c) == 1 and c["close"] >= body_mid_a + real_body(a) * STAR_PENETRATION:
        flags["morning_star"] = 1
    if candle_color(a) == 1 and is_long_body(candles, ai) and is_short_body(candles, bi) and candle_color(c) == -1 and c["close"] <= body_mid_a - real_body(a) * STAR_PENETRATION:
        flags["evening_star"] = 1

    if all(candle_color(x) == 1 for x in (a, b, c)) and all(is_long_body(candles, idx) for idx in (ai, bi, ci)) and b["close"] > a["close"] and c["close"] > b["close"] and all(is_very_short_upper_shadow(candles, idx) for idx in (ai, bi, ci)):
        flags["three_white_soldiers"] = 1
    if all(candle_color(x) == -1 for x in (a, b, c)) and all(is_long_body(candles, idx) for idx in (ai, bi, ci)) and b["close"] < a["close"] and c["close"] < b["close"] and all(is_very_short_upper_shadow(candles, idx) for idx in (ai, bi, ci)):
        flags["three_black_crows"] = 1

    if candle_color(a) == -1 and candle_color(b) == 1 and max(b["open"], b["close"]) < a["open"] and min(b["open"], b["close"]) > a["close"] and c["close"] > a["open"]:
        flags["three_inside_up"] = 1
    if candle_color(a) == 1 and candle_color(b) == -1 and max(b["open"], b["close"]) < a["close"] and min(b["open"], b["close"]) > a["open"] and c["close"] < a["open"]:
        flags["three_inside_down"] = 1

    if candle_color(a) == -1 and candle_color(b) == 1 and b["close"] > a["open"] and b["open"] < a["close"] and c["close"] > b["close"]:
        flags["three_outside_up"] = 1
    if candle_color(a) == 1 and candle_color(b) == -1 and b["open"] > a["close"] and b["close"] < a["open"] and c["close"] < b["close"]:
        flags["three_outside_down"] = 1

    if is_doji(candles, bi) and candle_gap_down(b, a) and candle_gap_up(c, b) and candle_color(c) == 1:
        flags["abandoned_baby_bull"] = 1
    if is_doji(candles, bi) and candle_gap_up(b, a) and candle_gap_down(c, b) and candle_color(c) == -1:
        flags["abandoned_baby_bear"] = 1
    return debug



def _confirmation(candles: List[Dict[str, Any]], pattern_dir: int, context: Dict[str, Any]) -> Dict[str, Any]:
    if not candles or pattern_dir == 0:
        return {"satisfied": False, "signals": []}
    latest = candles[-1]
    signals: List[str] = []
    breakout_ref = candles[-2] if len(candles) >= 2 else latest
    if pattern_dir > 0 and latest["close"] > breakout_ref["high"]:
        signals.append("break_pattern_high")
    if pattern_dir < 0 and latest["close"] < breakout_ref["low"]:
        signals.append("break_pattern_low")
    ml_signal = _safe_float(context.get("ml_signal_score"))
    if pattern_dir > 0 and ml_signal > 0:
        signals.append("supportive_ml_score")
    if pattern_dir < 0 and ml_signal < 0:
        signals.append("supportive_ml_score")
    signal_score = _safe_float(context.get("policy_signal_score"))
    if pattern_dir > 0 and signal_score > 0:
        signals.append("supportive_signal_score")
    if pattern_dir < 0 and signal_score < 0:
        signals.append("supportive_signal_score")
    orion_bias = _safe_float(context.get("orion_bias"))
    if pattern_dir > 0 and orion_bias > 0:
        signals.append("supportive_orion_thesis")
    if pattern_dir < 0 and orion_bias < 0:
        signals.append("supportive_orion_thesis")
    volume = _safe_float(context.get("volume_confirmation"))
    if volume > 0:
        signals.append("volume_volatility_confirmation")
    return {"satisfied": bool(signals), "signals": signals}



def evaluate_patterns(candles: List[Dict[str, Any]], context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    context = context or {}
    candle_quality = _normalize_candle_quality(context)
    normalized = [_normalize_candle(c) for c in candles][-20:]
    flags = {name: 0 for name in SUPPORTED_PATTERNS}
    if len(normalized) < 3 or any(not candle["valid"] or high_low_range(candle) <= 0 for candle in normalized[-3:]):
        return {
            "pattern_flags": flags,
            "pattern_dir": 0,
            "pattern_strength": 0.0,
            "pattern_contribution": 0.0,
            "pattern_confirmation": {"satisfied": False, "signals": []},
            "pattern_debug": {"reason": "insufficient_or_invalid_ohlc"},
            "matched_context": {
                "symbol": context.get("symbol"),
                "timeframe": context.get("timeframe", "live_tick"),
                **candle_quality,
            },
        }

    strat_debug = _detect_strat(normalized, flags)
    classical_debug = _detect_classical(normalized, flags)
    bull = sum(v for k, v in flags.items() if k.endswith("_bull") or k in {"morning_star", "three_white_soldiers", "three_inside_up", "three_outside_up"})
    bear = sum(v for k, v in flags.items() if k.endswith("_bear") or k in {"evening_star", "three_black_crows", "three_inside_down", "three_outside_down"})
    pattern_dir = 1 if bull > bear else -1 if bear > bull else 0
    matched = [name for name, value in flags.items() if value]
    raw_strength = min(1.0, 0.35 * len(matched)) if pattern_dir != 0 else 0.0
    confirmation = _confirmation(normalized, pattern_dir, context)
    pattern_strength = raw_strength if confirmation["satisfied"] else 0.0
    pattern_contribution = max(-PATTERN_CLAMP, min(PATTERN_CLAMP, pattern_dir * pattern_strength * PATTERN_WEIGHT))
    return {
        "pattern_flags": flags,
        "pattern_dir": pattern_dir,
        "pattern_strength": round(pattern_strength, 4),
        "pattern_contribution": round(pattern_contribution, 6),
        "pattern_confirmation": confirmation,
        "pattern_debug": {
            "matched_patterns": matched,
            "strat_debug": strat_debug,
            "classical_debug": classical_debug,
            "raw_strength": round(raw_strength, 4),
        },
        "matched_context": {
            "symbol": context.get("symbol"),
            "timeframe": context.get("timeframe", "live_tick"),
            **candle_quality,
        },
    }
