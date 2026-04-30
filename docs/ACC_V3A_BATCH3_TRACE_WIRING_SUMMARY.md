# ACC V3-A Batch 3 Trace Wiring Summary

## Scope

Batch 3 wires V3-A regime, weather, ranking, and WAIT-reason fields into candidate traces.

This is report-only enrichment. It does not change trading behavior.

## Completed

Updated:

- tools/live_run.py

Added:

- tests/test_v3a_candidate_trace_fields.py

Candidate rows may now include:

- v3a_market_regime
- v3a_risk_posture
- v3a_best_posture
- v3a_market_weather
- v3a_universe_rank
- v3a_universe_rank_score
- v3a_rank_reasons
- wait_reason
- wait_reason_detail

## Safety

This batch does not:

- change BUY / SELL / WAIT decisions
- alter ranking_score
- place trades
- call agents
- call OpenClaw
- call Hermes
- mutate portfolios
- mutate company state
- affect live-trade gates

## Why this matters

The runtime can now record why the market context looked favorable, hostile, uncertain, or selective before ACC begins using that context as a decision input.

This creates visibility before behavior change.

## Tests

Recommended tests:

    pytest -q tests/test_market_regime.py tests/test_market_weather.py tests/test_universe_ranker.py tests/test_v3a_regime_posture_report.py tests/test_v3a_candidate_trace_fields.py
    pytest -q tests/test_live_runtime_audit.py tests/test_pattern_engine.py

## Next Batch

Batch 4 should generate a real latest-run V3-A report from candidate_decisions.jsonl and verify that candidate rows include V3-A fields after a short paper run.

Decision influence remains out of scope until later.
