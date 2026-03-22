from tools.live_decision_engine import build_decision
from tools.pattern_engine import evaluate_patterns, strat_bar_type


def c(o, h, l, cl, ts="t"):
    return {"open": o, "high": h, "low": l, "close": cl, "timestamp": ts}


def warmup():
    candles = []
    price = 100.0
    for i in range(10):
        candles.append(c(price, price + 2, price - 2, price + 1, f"w{i}"))
        price += 0.5
    return candles


def test_strat_bar_typing():
    prev = c(10, 12, 8, 11)
    assert strat_bar_type(prev, c(11, 11.5, 8.5, 10.5)) == "1"
    assert strat_bar_type(prev, c(11, 13, 8.5, 12.5)) == "2U"
    assert strat_bar_type(prev, c(11, 11.5, 7.5, 8.0)) == "2D"
    assert strat_bar_type(prev, c(11, 13, 7.5, 12.0)) == "3"


def test_strat_212_bull():
    candles = warmup() + [
        c(100, 101, 99, 100.5, "p0"),
        c(100.5, 103, 99.5, 102, "p1"),  # 2U
        c(101.6, 102.5, 100.2, 101.8, "p2"),  # 1
        c(101.9, 104.5, 101.0, 104.2, "p3"),  # 2U
    ]
    result = evaluate_patterns(candles, {"symbol": "ETH-USD", "policy_signal_score": 0.1, "ml_signal_score": 0.2})
    assert result["pattern_flags"]["strat_212_bull"] == 1
    assert result["pattern_dir"] == 1


def test_strat_312_bear():
    candles = warmup() + [
        c(100, 101, 99, 100.5, "p0"),
        c(100.5, 102.5, 98.0, 99.0, "p1"),  # 3
        c(99.5, 101.5, 98.5, 100.0, "p2"),  # 1
        c(99.8, 100.3, 96.5, 97.0, "p3"),  # 2D
    ]
    result = evaluate_patterns(candles, {"symbol": "BTC-USD", "policy_signal_score": -0.1, "ml_signal_score": -0.2})
    assert result["pattern_flags"]["strat_312_bear"] == 1
    assert result["pattern_dir"] == -1


def test_strat_22_continuation_vs_reversal():
    bull = warmup() + [
        c(100, 101, 99, 100.5, "p0"),
        c(100.5, 103, 99.5, 102, "p1"),
        c(102.1, 104.0, 100.0, 103.5, "p2"),
        c(103.6, 105.0, 100.5, 104.4, "p3"),
    ]
    result_bull = evaluate_patterns(bull, {"policy_signal_score": 0.1, "ml_signal_score": 0.2})
    assert result_bull["pattern_flags"]["strat_22_continuation_bull"] == 1

    bear_to_bull = warmup() + [
        c(100, 101, 99, 100.5, "q0"),
        c(100.4, 100.8, 97.5, 98.0, "q1"),
        c(98.2, 102.5, 98.0, 101.8, "q2"),
        c(101.9, 103.0, 98.5, 102.6, "q3"),
    ]
    result_rev = evaluate_patterns(bear_to_bull, {"policy_signal_score": 0.1, "ml_signal_score": 0.2})
    assert result_rev["pattern_flags"]["strat_22_reversal_bull"] == 1


def test_morning_star():
    candles = warmup() + [
        c(110, 111, 103, 104, "a"),
        c(102.0, 102.5, 101.5, 102.1, "b"),
        c(103, 109.5, 102.5, 109.2, "c"),
    ]
    result = evaluate_patterns(candles, {"policy_signal_score": 0.2, "ml_signal_score": 0.3})
    assert result["pattern_flags"]["morning_star"] == 1


def test_evening_star():
    candles = warmup() + [
        c(104, 111, 103, 110, "a"),
        c(111.5, 112.0, 111.0, 111.6, "b"),
        c(110.5, 111.0, 104.0, 105.0, "c"),
    ]
    result = evaluate_patterns(candles, {"policy_signal_score": -0.2, "ml_signal_score": -0.3})
    assert result["pattern_flags"]["evening_star"] == 1


def test_three_white_soldiers():
    candles = warmup() + [
        c(100, 106.1, 99.8, 106, "a"),
        c(105.8, 112.1, 105.5, 112, "b"),
        c(111.8, 118.1, 111.5, 118, "c"),
    ]
    result = evaluate_patterns(candles, {"policy_signal_score": 0.2, "ml_signal_score": 0.3})
    assert result["pattern_flags"]["three_white_soldiers"] == 1


def test_three_black_crows():
    candles = warmup() + [
        c(118, 118.1, 111.8, 112, "a"),
        c(112.2, 112.3, 105.8, 106, "b"),
        c(106.1, 106.2, 99.8, 100, "c"),
    ]
    result = evaluate_patterns(candles, {"policy_signal_score": -0.2, "ml_signal_score": -0.3})
    assert result["pattern_flags"]["three_black_crows"] == 1


def test_three_inside_patterns():
    up = warmup() + [
        c(110, 111, 102, 103, "a"),
        c(104, 108, 103.5, 107, "b"),
        c(107.1, 112, 106.9, 111.5, "c"),
    ]
    result_up = evaluate_patterns(up, {"policy_signal_score": 0.2, "ml_signal_score": 0.3})
    assert result_up["pattern_flags"]["three_inside_up"] == 1

    down = warmup() + [
        c(103, 111, 102, 110, "a"),
        c(109, 109.5, 105, 106, "b"),
        c(105.5, 106, 100, 101, "c"),
    ]
    result_down = evaluate_patterns(down, {"policy_signal_score": -0.2, "ml_signal_score": -0.3})
    assert result_down["pattern_flags"]["three_inside_down"] == 1


def test_three_outside_patterns():
    up = warmup() + [
        c(110, 111, 103, 104, "a"),
        c(103.5, 112, 103.0, 111.5, "b"),
        c(111.6, 115, 111.4, 114.5, "c"),
    ]
    result_up = evaluate_patterns(up, {"policy_signal_score": 0.2, "ml_signal_score": 0.3})
    assert result_up["pattern_flags"]["three_outside_up"] == 1

    down = warmup() + [
        c(104, 111, 103, 110, "a"),
        c(110.5, 111.0, 102.5, 103.0, "b"),
        c(102.9, 103.1, 99.0, 99.5, "c"),
    ]
    result_down = evaluate_patterns(down, {"policy_signal_score": -0.2, "ml_signal_score": -0.3})
    assert result_down["pattern_flags"]["three_outside_down"] == 1


def test_stale_flat_invalid_ohlc_edge_cases():
    flat = warmup() + [c(100, 100, 100, 100, "a"), c(100, 100, 100, 100, "b"), c(100, 100, 100, 100, "c")]
    result_flat = evaluate_patterns(flat, {"policy_signal_score": 0.1, "ml_signal_score": 0.1})
    assert result_flat["pattern_dir"] == 0
    assert result_flat["pattern_strength"] == 0.0

    invalids = [c(10, 9, 11, 10, "bad1"), c(10, 9, 11, 10, "bad2"), c(10, 9, 11, 10, "bad3")]
    result_invalid = evaluate_patterns(invalids, {"policy_signal_score": 0.1, "ml_signal_score": 0.1})
    assert result_invalid["pattern_dir"] == 0
    assert result_invalid["pattern_strength"] == 0.0


def test_candle_quality_normalization_real_vs_pseudo():
    candles = warmup() + [
        c(100, 101, 99, 100.5, "p0"),
        c(100.5, 103, 99.5, 102, "p1"),
        c(101.6, 102.5, 100.2, 101.8, "p2"),
        c(101.9, 104.5, 101.0, 104.2, "p3"),
    ]
    pseudo = evaluate_patterns(
        candles,
        {
            "symbol": "ETH-USD",
            "policy_signal_score": 0.1,
            "ml_signal_score": 0.2,
            "candle_source": "pseudo_snapshot_ohlc",
            "candle_confidence": 0.9,
        },
    )
    real = evaluate_patterns(
        candles,
        {
            "symbol": "ETH-USD",
            "policy_signal_score": 0.1,
            "ml_signal_score": 0.2,
            "candle_source": "real_ohlc",
            "candle_confidence": 0.4,
        },
    )
    assert pseudo["matched_context"]["candle_source"] == "pseudo_snapshot_ohlc"
    assert pseudo["matched_context"]["candle_confidence"] <= 0.49
    assert real["matched_context"]["candle_source"] == "real_ohlc"
    assert real["matched_context"]["candle_confidence"] >= 0.5
    assert pseudo["matched_context"]["candle_confidence"] < real["matched_context"]["candle_confidence"]


def test_live_decision_artifact_exposes_candle_quality_fields():
    candle_history = warmup() + [
        {
            **c(100.5, 103, 99.5, 102, "p1"),
            "candle_source": "pseudo_snapshot_ohlc",
            "candle_confidence": 0.35,
        },
        {
            **c(101.6, 102.5, 100.2, 101.8, "p2"),
            "candle_source": "pseudo_snapshot_ohlc",
            "candle_confidence": 0.35,
        },
        {
            **c(101.9, 104.5, 101.0, 104.2, "p3"),
            "candle_source": "pseudo_snapshot_ohlc",
            "candle_confidence": 0.35,
        },
    ]
    decision = build_decision(
        {
            "timestamp": "2026-03-22T00:00:00+00:00",
            "symbol": "ETH-USD",
            "price": 104.2,
            "orion_bias": 0.1,
            "volume_confirmation": 1.0,
        },
        "company_001",
        last_price=100.0,
        candle_history=candle_history,
    )
    for key in (
        "pattern_flags",
        "pattern_dir",
        "pattern_strength",
        "pattern_contribution",
        "pattern_confirmation",
        "candle_source",
        "candle_confidence",
    ):
        assert key in decision
    assert decision["candle_source"] == "pseudo_snapshot_ohlc"
    assert decision["candle_confidence"] == 0.35
    assert decision["matched_context"]["candle_source"] == "pseudo_snapshot_ohlc"
    assert decision["matched_context"]["candle_confidence"] == 0.35
