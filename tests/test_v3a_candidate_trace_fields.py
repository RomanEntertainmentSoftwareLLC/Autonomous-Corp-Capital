from tools.live_run import (
    annotate_v3a_market_context,
    annotate_v3a_wait_reasons,
)


def candidate(symbol, decision="WAIT", score=0.01, company="company_001", change=0.0):
    return {
        "company_id": company,
        "symbol": symbol,
        "decision": decision,
        "change_pct": change,
        "policy_signal_score": score,
        "ml_signal_score": 0.0,
        "model_score": 0.60 if score >= 0 else 0.40,
        "ranking_score": abs(score),
        "position_state": 0.0,
    }


def test_v3a_market_context_adds_report_only_fields_without_changing_decision():
    rows = [
        candidate("BTC-USD", decision="WAIT", score=-0.01, change=-0.01),
        candidate("ETH-USD", decision="WAIT", score=-0.012, change=-0.012),
        candidate("SOL-USD", decision="BUY", score=0.004, change=0.004),
    ]
    original_decisions = [row["decision"] for row in rows]

    weather = annotate_v3a_market_context(rows)

    assert [row["decision"] for row in rows] == original_decisions
    assert weather["market_regime"] in {
        "broad_red_market",
        "downtrend",
        "sideways_chop",
        "mixed_selective",
        "uptrend",
        "volatility_shock",
    }
    for row in rows:
        assert "v3a_market_regime" in row
        assert "v3a_risk_posture" in row
        assert "v3a_best_posture" in row
        assert "v3a_market_weather" in row
        assert "v3a_universe_rank" in row
        assert "v3a_universe_rank_score" in row
        assert "v3a_rank_reasons" in row


def test_v3a_wait_reason_uses_existing_specific_reason_when_present():
    rows = [
        candidate("BTC-USD", decision="WAIT", score=0.01),
    ]
    rows[0]["decision_promotion_blocked_reason"] = "missing_bullish_pattern_confirmation"

    annotate_v3a_market_context(rows)
    annotate_v3a_wait_reasons(rows)

    assert rows[0]["decision"] == "WAIT"
    assert rows[0]["wait_reason"] == "WAIT_NEEDS_CONFIRMATION"


def test_v3a_wait_reason_marks_flat_sell_block_as_already_flat():
    rows = [
        candidate("BTC-USD", decision="WAIT", score=-0.01),
    ]
    rows[0]["decision_demotion_reason"] = "flat_account_sell_block"

    annotate_v3a_market_context(rows)
    annotate_v3a_wait_reasons(rows)

    assert rows[0]["wait_reason"] == "WAIT_ALREADY_FLAT"


def test_v3a_wait_reason_does_not_touch_buy_rows():
    rows = [
        candidate("BTC-USD", decision="BUY", score=0.02),
    ]

    annotate_v3a_market_context(rows)
    annotate_v3a_wait_reasons(rows)

    assert rows[0]["decision"] == "BUY"
    assert "wait_reason" not in rows[0]
