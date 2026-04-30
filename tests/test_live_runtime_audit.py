from datetime import datetime, timezone, timedelta, timezone
import json
import signal

import pytest

from tools.live_decision_engine import LIVE_PATTERN_SCORE_MAX_ABS, build_decision, build_live_pattern_payload
from tools.live_run import (
    _bootstrap_last_prices_from_previous_run,
    _fetch_orion_headlines,
    apply_orion_bias_before_ranking,
    build_live_candle,
    candidate_ranking_score,
    rank_and_select_candidates,
    stop_run,
)


UTC = timezone.utc


def candidate(symbol="BTC-USD"):
    return {
        "company_id": "company_001",
        "symbol": symbol,
        "decision": "WAIT",
        "policy_signal_score": 0.01,
        "ml_signal_score": 0.02,
        "model_score": 0.7,
        "pattern_score": 0.0,
        "ranking_score": 0.43,
        "position_state": 0.0,
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


def test_orion_text_only_signal_survives_failed_live_fetch(monkeypatch):
    now = datetime(2026, 3, 22, 1, 0, tzinfo=UTC)
    monkeypatch.setattr(
        "tools.live_run.collect_agent_reports",
        lambda company: {"Orion": [report("BTC-USD bullish catalyst from exchange listing", now - timedelta(hours=1))]},
    )

    def failed_fetch(*args, **kwargs):
        import tools.live_run as live_run

        live_run.ORION_LAST_FETCH_STATE = "provider_fails"
        return []

    monkeypatch.setattr("tools.live_run._fetch_orion_headlines", failed_fetch)
    rows = apply_orion_bias_before_ranking([candidate()], now=now)
    assert rows[0]["orion_bias"] == 0.02
    assert rows[0]["orion_quality_state"] == "legacy_text_only"
    assert rows[0]["orion_fetch_state"] == "provider_fails"



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
    assert state["last_reset_day"] == datetime.now(timezone.utc).date().isoformat()
    assert state["last_reset_month"] == datetime.now(timezone.utc).strftime("%Y-%m")



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


def test_close_only_bootstrap_history_can_preserve_direction_when_signal_aligns():
    payload = build_live_pattern_payload(
        {"symbol": "BTC-USD"},
        [{"open": 100, "close": 101}],
        0.01,
        {"policy_signal_score": 0.01, "ml_signal_score": 0.02},
        "pseudo_snapshot_ohlc",
        0.35,
    )
    assert payload["pattern_dir"] == 1
    assert payload["pattern_confirmation"]["satisfied"] is True
    assert payload["pattern_score"] == LIVE_PATTERN_SCORE_MAX_ABS


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


def test_ranked_wait_candidate_promotes_when_one_signal_and_evidence_align():
    row = candidate("BTC-USD")
    row.update(
        {
            "policy_signal_score": 0.011,
            "ml_signal_score": 0.0,
            "model_score": 0.71,
            "ranking_score": 0.352,
            "pattern_confirmation": {"satisfied": True},
            "pattern_dir": 1,
            "orion_bias": 0.02,
            "orion_bias_applied": True,
            "detected_patterns": ["bullish catalyst"],
        }
    )

    ranked = rank_and_select_candidates([row])

    assert ranked[0]["decision"] == "BUY"
    assert ranked[0]["execution_state"] == "executed"
    assert ranked[0]["decision_promoted_from"] == "WAIT"


def test_ranked_wait_candidate_promotes_on_real_ohlc_even_without_pattern_or_orion_evidence():
    row = candidate("BTC-USD")
    row.update(
        {
            "policy_signal_score": 0.011,
            "ml_signal_score": 0.0,
            "model_score": 0.71,
            "ranking_score": 0.352,
            "pattern_confirmation": {"satisfied": False},
            "pattern_dir": 0,
            "orion_bias": 0.0,
            "orion_bias_applied": False,
            "candle_source": "real_ohlc",
            "candle_confidence": 0.7,
        }
    )

    ranked = rank_and_select_candidates([row])

    assert ranked[0]["decision"] == "BUY"
    assert ranked[0]["execution_state"] == "executed"
    assert ranked[0]["decision_promoted_from"] == "WAIT"


def test_ranked_wait_candidate_stays_wait_without_score_or_evidence():
    row = candidate("BTC-USD")
    row.update(
        {
            "policy_signal_score": 0.0,
            "ml_signal_score": 0.0,
            "model_score": 0.5,
            "ranking_score": 0.0,
            "pattern_confirmation": {"satisfied": False},
            "pattern_dir": 0,
            "orion_bias": 0.0,
            "orion_bias_applied": False,
        }
    )

    ranked = rank_and_select_candidates([row])

    assert ranked[0]["decision"] == "WAIT"
    assert ranked[0]["execution_state"] == "skipped"
    assert ranked[0]["skip_reason"] == "hold_candidate"


def test_real_ohlc_wait_candidate_gets_small_ranking_floor():
    row = candidate("BTC-USD")
    row.update(
        {
            "policy_signal_score": 0.0,
            "ml_signal_score": 0.0,
            "model_score": 0.5,
            "pattern_score": 0.0,
            "decision": "WAIT",
            "candle_source": "real_ohlc",
            "candle_confidence": 0.7,
            "ranking_score": 0.0,
            "position_state": 0.0,
        }
    )

    assert candidate_ranking_score(row) == 0.0001


def test_owned_position_keeps_hold_position_during_decision_build():
    snapshot = {
        "symbol": "BTC-USD",
        "price": 101.0,
        "position_state": 1.0,
        "candle_source": "real_ohlc",
        "candle_confidence": 0.8,
    }
    decision = build_decision(snapshot, "company_001", last_price=100.0, candle_history=[{"open": 100.0, "close": 101.0}])

    assert decision["decision"] == "HOLD_POSITION"


def test_flat_zero_signal_candidate_promotes_on_aligned_pattern_confirmation():
    snapshot = {
        "symbol": "BTC-USD",
        "price": 102.0,
        "position_state": 0.0,
    }
    candle_history = [
        {"close": 100.0},
        {"close": 101.0},
        {"close": 102.0},
    ]

    decision = build_decision(snapshot, "company_001", last_price=102.0, candle_history=candle_history)

    assert decision["decision"] == "BUY"
    assert decision["scoring_method"] == "signal_plus_pattern"
    assert decision["notes"] == "signal + pattern confirmation under balanced_baseline"



def test_first_real_ohlc_candle_uses_previous_price_when_available():
    candle = build_live_candle(
        {
            "symbol": "BTC-USD",
            "timestamp": "2026-04-12T18:00:00+00:00",
            "price": 102.0,
        },
        last_price=101.8,
    )

    assert candle["candle_source"] == "real_ohlc"
    assert candle["candle_confidence"] == 0.7
    assert candle["open"] == 101.8
    assert candle["close"] == 102.0
    assert candle["high"] == 102.0
    assert candle["low"] == 101.8



def test_wait_candidate_can_promote_on_real_ohlc_bootstrap_when_signal_is_nonzero():
    snapshot = {
        "symbol": "BTC-USD",
        "price": 102.0,
        "position_state": 0.0,
        "candle_source": "real_ohlc",
        "candle_confidence": 0.7,
    }
    candle_history = [{"open": 101.8, "close": 102.0}]

    decision = build_decision(snapshot, "company_001", last_price=101.8, candle_history=candle_history)

    assert decision["decision"] == "BUY"
    assert decision["scoring_method"] == "signal_plus_real_ohlc"
    assert decision["notes"] == "signal + real_ohlc bootstrap under balanced_baseline"



def test_bootstrap_last_prices_from_previous_run_uses_prior_feed_state(tmp_path, monkeypatch):
    runs_root = tmp_path / "live_runs"
    previous_run = runs_root / "run_20260412_223234"
    current_run = runs_root / "run_20260412_223235"
    (previous_run / "data").mkdir(parents=True)
    (current_run / "data").mkdir(parents=True)
    (previous_run / "data" / "market_feed.log").write_text(
        "\n".join(
            [
                json.dumps({"symbol": "BTC-USD", "price": 101.8}),
                json.dumps({"symbol": "SOL-USD", "price": 81.25}),
                json.dumps({"symbol": "BTC-USD", "price": 102.1}),
            ]
        )
        + "\n"
    )
    monkeypatch.setattr("tools.live_run.LIVE_RUNS_ROOT", runs_root)

    bootstrapped = _bootstrap_last_prices_from_previous_run("run_20260412_223235", ["BTC-USD", "SOL-USD", "DOGE-USD"])

    assert bootstrapped[("company_001", "BTC-USD")] == 102.1
    assert bootstrapped[("company_004", "SOL-USD")] == 81.25
    assert ("company_001", "DOGE-USD") not in bootstrapped


def test_wait_candidate_can_bootstrap_nonzero_signal_from_real_ohlc_even_without_last_price():
    snapshot = {
        "symbol": "BTC-USD",
        "price": 102.0,
        "position_state": 0.0,
        "candle_source": "real_ohlc",
        "candle_confidence": 0.7,
    }
    candle_history = [{"open": 101.8, "close": 102.0}]

    decision = build_decision(snapshot, "company_001", last_price=None, candle_history=candle_history)

    assert decision["signal_score"] > 0
    assert decision["policy_signal_score"] > 0
    assert decision["decision"] == "BUY"



def test_wait_candidate_can_bootstrap_from_previous_real_ohlc_close_when_current_candle_is_flat():
    snapshot = {
        "symbol": "BTC-USD",
        "price": 101.0,
        "position_state": 0.0,
        "candle_source": "real_ohlc",
        "candle_confidence": 0.7,
    }
    candle_history = [
        {"open": 100.0, "close": 100.0, "candle_source": "real_ohlc", "candle_confidence": 0.7},
        {"open": 101.0, "close": 101.0, "candle_source": "real_ohlc", "candle_confidence": 0.7},
    ]

    decision = build_decision(snapshot, "company_001", last_price=None, candle_history=candle_history)

    assert decision["signal_score"] > 0
    assert decision["policy_signal_score"] > 0
    assert decision["decision"] == "BUY"




def test_flat_account_sell_signal_is_blocked_to_wait():
    snapshot = {
        "symbol": "BTC-USD",
        "price": 99.0,
        "position_state": 0.0,
        "candle_source": "real_ohlc",
        "candle_confidence": 0.8,
    }

    decision = build_decision(snapshot, "company_001", last_price=100.0, candle_history=[{"open": 100.0, "close": 99.0, "candle_source": "real_ohlc", "candle_confidence": 0.8}])

    assert decision["signal_score"] < 0
    assert decision["decision"] == "WAIT"
    assert decision["scoring_method"] == "flat_account_sell_block"


def test_ranked_wait_candidate_does_not_promote_to_sell_when_flat():
    row = candidate("BTC-USD")
    row.update(
        {
            "policy_signal_score": -0.011,
            "ml_signal_score": 0.0,
            "model_score": 0.29,
            "ranking_score": 0.352,
            "pattern_confirmation": {"satisfied": False},
            "pattern_dir": 0,
            "orion_bias": 0.0,
            "orion_bias_applied": False,
            "candle_source": "real_ohlc",
            "candle_confidence": 0.7,
            "position_state": 0.0,
        }
    )

    ranked = rank_and_select_candidates([row])

    assert ranked[0]["decision"] == "WAIT"
    assert ranked[0]["execution_state"] == "skipped"
    assert ranked[0]["skip_reason"] == "hold_candidate"


def test_direct_flat_sell_candidate_is_demoted_before_execution():
    row = candidate("BTC-USD")
    row.update(
        {
            "decision": "SELL",
            "ranking_score": 0.25,
            "position_state": 0.0,
        }
    )

    ranked = rank_and_select_candidates([row])

    assert ranked[0]["decision"] == "WAIT"
    assert ranked[0]["decision_demoted_from"] == "SELL"
    assert ranked[0]["decision_demotion_reason"] == "flat_account_sell_block"
    assert ranked[0]["execution_state"] == "skipped"
    assert ranked[0]["skip_reason"] == "hold_candidate"

def test_stop_run_refuses_false_safe_when_process_group_survives(monkeypatch, tmp_path):
    run_dir = tmp_path / "run_20260412_050000"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "packets").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "data").mkdir(parents=True)
    (run_dir / "run.pid").write_text("111")
    (run_dir / "run_metadata.json").write_text(json.dumps({"run_id": "run_20260412_050000", "status": "running"}))

    monkeypatch.setattr("tools.live_run.read_current_run", lambda: {"run_id": "run_20260412_050000", "pid": 111, "pgid": 222})
    monkeypatch.setattr("tools.live_run.run_directory", lambda run_id: run_dir)
    monkeypatch.setattr("tools.live_run.os.killpg", lambda pgid, sig: None)
    monkeypatch.setattr("tools.live_run._wait_for_process_group_exit", lambda pgid, timeout: True)
    observed = []
    monkeypatch.setattr("tools.live_run._process_group_is_alive", lambda pgid: observed.append(pgid) or (pgid == 222))
    monkeypatch.setattr("tools.live_run._pid_is_alive", lambda pid: False)
    monkeypatch.setattr("tools.live_run.write_daily_digest", lambda run_id: None)
    monkeypatch.setattr("tools.live_run.clear_current_run", lambda: None)

    with pytest.raises(SystemExit, match="still alive"):
        stop_run()

    assert observed[-1] == 222


def test_stop_run_escalates_to_worker_pid_when_process_group_exits_but_worker_survives(monkeypatch, tmp_path):
    run_dir = tmp_path / "run_20260412_050100"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "packets").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "data").mkdir(parents=True)
    (run_dir / "run.pid").write_text("111")
    (run_dir / "run_metadata.json").write_text(json.dumps({"run_id": "run_20260412_050100", "status": "running"}))

    monkeypatch.setattr("tools.live_run.read_current_run", lambda: {"run_id": "run_20260412_050100", "pid": 111, "pgid": 222})
    monkeypatch.setattr("tools.live_run.run_directory", lambda run_id: run_dir)
    monkeypatch.setattr("tools.live_run.os.killpg", lambda pgid, sig: None)
    monkeypatch.setattr("tools.live_run._wait_for_process_group_exit", lambda pgid, timeout: True)
    pid_checks = []
    kill_calls = []
    pid_state = {"alive": True}

    def fake_pid_is_alive(pid):
        pid_checks.append(pid)
        return pid_state["alive"] if pid == 111 else False

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if pid == 111 and sig == signal.SIGKILL:
            pid_state["alive"] = False

    monkeypatch.setattr("tools.live_run._process_group_is_alive", lambda pgid: False)
    monkeypatch.setattr("tools.live_run._pid_is_alive", fake_pid_is_alive)
    monkeypatch.setattr("tools.live_run.os.kill", fake_kill)
    monkeypatch.setattr("tools.live_run._wait_for_pid_exit", lambda pid, timeout: pid == 111 and not pid_state["alive"])
    monkeypatch.setattr("tools.live_run.write_daily_digest", lambda run_id: None)
    monkeypatch.setattr("tools.live_run.clear_current_run", lambda: None)

    stop_run()

    assert pid_checks[-1] == 111
    assert kill_calls[-1] == (111, signal.SIGKILL)


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



def test_buy_candidate_is_demoted_when_company_is_full():
    row = candidate("BTC-USD")
    row.update({
        "decision": "BUY",
        "ranking_score": 0.25,
        "position_state": 0.0,
        "open_positions_count": 6,
    })

    ranked = rank_and_select_candidates([row])

    assert ranked[0]["decision"] == "WAIT"
    assert ranked[0]["decision_demotion_reason"] == "max_open_positions"
    assert ranked[0]["skip_reason"] == "hold_candidate"
