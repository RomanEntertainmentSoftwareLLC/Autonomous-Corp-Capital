from tools.universe_ranker import rank_universe_candidates, score_universe_candidate


def test_score_universe_candidate_is_explainable():
    row = score_universe_candidate({
        "company_id": "company_001",
        "symbol": "BTC-USD",
        "policy_signal_score": 0.01,
        "ml_signal_score": 0.02,
        "model_score": 0.75,
        "pattern_score": 0.005,
    })
    assert row["symbol"] == "BTC-USD"
    assert row["universe_rank_score"] > 0
    assert any(reason.startswith("policy=") for reason in row["reasons"])


def test_rank_universe_candidates_orders_highest_score_first():
    ranked = rank_universe_candidates([
        {
            "company_id": "company_001",
            "symbol": "WEAK-USD",
            "policy_signal_score": 0.001,
            "model_score": 0.51,
        },
        {
            "company_id": "company_001",
            "symbol": "STRONG-USD",
            "policy_signal_score": 0.02,
            "ml_signal_score": 0.02,
            "model_score": 0.8,
        },
    ])
    assert ranked[0]["symbol"] == "STRONG-USD"
    assert ranked[0]["universe_rank"] == 1
    assert ranked[1]["universe_rank"] == 2
