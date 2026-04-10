from datetime import datetime, timedelta, timezone
import json

from tools.live_decision_engine import LIVE_PATTERN_SCORE_MAX_ABS, build_live_pattern_payload
from tools.live_run import apply_orion_bias_before_ranking, candidate_ranking_score, _fetch_orion_headlines


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



def live_article(ts, title="BTC-USD catalyst from live provider"):
    return [
        {
            "title": title,
            "url": "https://example.com/article",
            "source": "Reuters",
            "published_at": ts.isoformat(),
            "retrieved_at": ts.isoformat(),
            "source_provenance": "newsapi",
        }
    ]


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



def test_orion_allowed_live_search_updates_governor(monkeypatch, tmp_path):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    state_path = tmp_path / "search_governor.json"
    cache_path = tmp_path / "headlines_cache.jsonl"
    monkeypatch.setattr("tools.live_run.ORION_SEARCH_GOVERNOR_PATH", state_path)
    monkeypatch.setattr("tools.live_run.ORION_CACHE_PATH", cache_path)
    calls = []
    monkeypatch.setattr("tools.live_run._orion_live_search", lambda symbol, max_age_hours=24.0, limit=3: calls.append(symbol) or live_article(now))

    rows = _fetch_orion_headlines("btc-usd", actor_name="Orion")

    assert rows == live_article(now)
    assert calls == ["BTC-USD"]
    state = json.loads(state_path.read_text())
    assert state["daily_used"] == 1
    assert state["monthly_used"] == 1
    assert state["last_reset_day"] == datetime.utcnow().date().isoformat()
    assert state["last_reset_month"] == datetime.utcnow().strftime("%Y-%m")



def test_rowan_is_blocked_from_orion_live_search(monkeypatch, tmp_path):
    state_path = tmp_path / "search_governor.json"
    cache_path = tmp_path / "headlines_cache.jsonl"
    monkeypatch.setattr("tools.live_run.ORION_SEARCH_GOVERNOR_PATH", state_path)
    monkeypatch.setattr("tools.live_run.ORION_CACHE_PATH", cache_path)
    monkeypatch.setattr("tools.live_run._orion_live_search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Rowan should not reach live Orion search")))

    rows = _fetch_orion_headlines("btc-usd", actor_name="Rowan")

    assert rows == []
    assert not state_path.exists()
    assert not cache_path.exists()



def test_duplicate_orion_query_reuses_fresh_cache(monkeypatch, tmp_path):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    state_path = tmp_path / "search_governor.json"
    cache_path = tmp_path / "headlines_cache.jsonl"
    monkeypatch.setattr("tools.live_run.ORION_SEARCH_GOVERNOR_PATH", state_path)
    monkeypatch.setattr("tools.live_run.ORION_CACHE_PATH", cache_path)
    calls = []
    monkeypatch.setattr("tools.live_run._orion_live_search", lambda symbol, max_age_hours=24.0, limit=3: calls.append(symbol) or live_article(now, title=f"{symbol} catalyst from live provider"))

    first = _fetch_orion_headlines("btc-usd", actor_name="Orion")
    second = _fetch_orion_headlines(" BTC-usd ", actor_name="Orion")

    assert first == second
    assert calls == ["BTC-USD"]
    state = json.loads(state_path.read_text())
    assert state["daily_used"] == 1
    assert state["monthly_used"] == 1


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
