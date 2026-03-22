from datetime import datetime, timedelta, timezone

from tools.live_decision_engine import LIVE_PATTERN_SCORE_MAX_ABS, build_live_pattern_payload
from tools.live_run import apply_orion_bias_before_ranking, candidate_ranking_score


UTC = timezone.utc


def candidate(symbol="BTC-USD"):
    return {
        "company_id": "company_001",
        "symbol": symbol,
        "decision": "BUY",
        "policy_signal_score": 0.01,
        "ml_signal_score": 0.02,
        "model_score": 0.7,
        "pattern_score": 0.0,
        "ranking_score": 0.43,
    }


def report(text, ts, **extra):
    payload = {
        "timestamp": ts.isoformat(),
        "analysis_summary": text,
        "research_summary": "",
        "ideas": [],
        "hypotheses": [],
        "evidence": [],
    }
    payload.update(extra)
    return payload


def test_orion_fresh_bullish_match_applies_point_zero_two(monkeypatch):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "tools.live_run.collect_agent_reports",
        lambda company: {"Orion": [report("BTC-USD bullish catalyst from exchange listing", now - timedelta(hours=1))]},
    )
    rows = apply_orion_bias_before_ranking([candidate()], now=now)
    assert rows[0]["orion_bias"] == 0.02
    assert rows[0]["orion_bias_applied"] is True


def test_orion_stale_report_applies_zero(monkeypatch):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "tools.live_run.collect_agent_reports",
        lambda company: {"Orion": [report("BTC-USD bullish catalyst from exchange listing", now - timedelta(hours=25))]},
    )
    rows = apply_orion_bias_before_ranking([candidate()], now=now)
    assert rows[0]["orion_bias"] == 0.0
    assert rows[0]["orion_bias_reason"] == "stale_report"


def test_orion_unclear_or_missing_data_halves_magnitude(monkeypatch):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "tools.live_run.collect_agent_reports",
        lambda company: {
            "Orion": [
                report(
                    "BTC-USD bullish catalyst but outlook remains unclear",
                    now - timedelta(hours=1),
                    missing_data=["order_flow"],
                )
            ]
        },
    )
    rows = apply_orion_bias_before_ranking([candidate()], now=now)
    assert rows[0]["orion_bias"] == 0.01
    assert rows[0]["orion_bias_reason"] == "bullish_catalyst_halved_for_uncertainty"


def test_orion_no_symbol_match_is_zero(monkeypatch):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "tools.live_run.collect_agent_reports",
        lambda company: {"Orion": [report("ETH-USD bullish catalyst from exchange listing", now - timedelta(hours=1))]},
    )
    rows = apply_orion_bias_before_ranking([candidate()], now=now)
    assert rows[0]["orion_bias"] == 0.0
    assert rows[0]["orion_bias_reason"] == "no_symbol_match"


def test_close_only_rising_falling_patterns_are_bounded():
    rising = build_live_pattern_payload(
        {"symbol": "BTC-USD"},
        [{"close": 100}, {"close": 101}, {"close": 102}],
        0.01,
        {"ml_signal_score": 0.02},
        "pseudo_snapshot_ohlc",
        0.35,
    )
    falling = build_live_pattern_payload(
        {"symbol": "BTC-USD"},
        [{"close": 102}, {"close": 101}, {"close": 100}],
        -0.01,
        {"ml_signal_score": -0.02},
        "pseudo_snapshot_ohlc",
        0.35,
    )
    assert rising["pattern_score"] == LIVE_PATTERN_SCORE_MAX_ABS
    assert falling["pattern_score"] == -LIVE_PATTERN_SCORE_MAX_ABS
    assert abs(rising["pattern_score"]) <= LIVE_PATTERN_SCORE_MAX_ABS
    assert abs(falling["pattern_score"]) <= LIVE_PATTERN_SCORE_MAX_ABS


def test_no_ohlc_means_no_fake_strat_label():
    payload = build_live_pattern_payload(
        {"symbol": "BTC-USD"},
        [{"close": 100}, {"close": 101}, {"close": 102}],
        0.01,
        {"ml_signal_score": 0.02},
        "pseudo_snapshot_ohlc",
        0.35,
    )
    assert payload["strat_available"] is False
    assert payload["strat_pattern"] is None
    assert payload["pattern_engine_mode"] == "close_only_3step"


def test_ranking_order_changes_when_orion_and_pattern_apply(monkeypatch):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "tools.live_run.collect_agent_reports",
        lambda company: {"Orion": [report("BTC-USD bullish catalyst from exchange listing", now - timedelta(hours=1))]},
    )
    low = candidate("BTC-USD")
    low["ranking_score"] = candidate_ranking_score({**low, "pattern_score": 0.015})
    low["pattern_score"] = 0.015
    high = candidate("ETH-USD")
    high["ranking_score"] = candidate_ranking_score(high)
    high["policy_signal_score"] = 0.011
    rows = apply_orion_bias_before_ranking([high, low], now=now)
    ranked = sorted(rows, key=lambda row: row["ranking_score"], reverse=True)
    assert ranked[0]["symbol"] == "BTC-USD"
