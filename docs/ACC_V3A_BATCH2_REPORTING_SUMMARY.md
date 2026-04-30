# ACC V3-A Batch 2 Reporting Summary

## Scope

Batch 2 adds a read-only V3-A regime/posture report tool.

This batch does not change trading behavior.

## Completed

Added:

- tools/v3a_regime_posture_report.py
- tests/test_v3a_regime_posture_report.py

The report reads candidate decision rows from the latest or selected run and summarizes:

- market regime
- market weather
- risk posture
- best posture
- decision counts
- WAIT reason counts
- top ranked candidates

## Safety

This batch does not:

- change BUY / SELL / WAIT behavior
- place trades
- call agents
- call OpenClaw
- call Hermes
- mutate portfolios
- mutate company state
- affect live-trade gates

## Commands

Run report against latest run:

    python3 tools/v3a_regime_posture_report.py --run-id latest

Write report to a file:

    python3 tools/v3a_regime_posture_report.py --run-id latest --out reports/v3a_regime_posture_report.txt

Print JSON:

    python3 tools/v3a_regime_posture_report.py --run-id latest --json

## Tests

Recommended tests:

    pytest -q tests/test_market_regime.py tests/test_market_weather.py tests/test_universe_ranker.py tests/test_v3a_regime_posture_report.py
    pytest -q tests/test_live_runtime_audit.py tests/test_pattern_engine.py

## Next Batch

Batch 3 should wire V3-A fields into candidate traces in report-only mode.

Runtime decision influence should still wait until later.
