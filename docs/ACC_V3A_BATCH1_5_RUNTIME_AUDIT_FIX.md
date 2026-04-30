# ACC V3-A Batch 1.5 Runtime Audit Alignment

## Purpose

Batch 1.5 restored existing runtime audit semantics after V3-A Batch 1 testing revealed pre-existing failures in the current runtime audit suite.

## What changed

- Restored real-OHLC bootstrap as enabled by default in `tools/live_decision_engine.py`.
- Preserved the existing test contract where real-OHLC bootstrap can promote a qualifying WAIT candidate.
- Restored `signal_plus_pattern` scoring labels for confirmed aligned pattern decisions.
- Preserved flat-account SELL blocking behavior through `flat_account_sell_block`.
- Restored ranked WAIT candidate promotion on high-confidence real-OHLC evidence in `tools/live_run.py`.

## What did not change

This was not a V3-A trading behavior rollout.

It did not:

- add market regime runtime wiring
- add market weather runtime wiring
- change live-trade behavior
- call agents
- call Hermes
- mutate portfolio state
- add dashboard behavior

## Tests

Recommended tests:

    pytest -q tests/test_market_regime.py tests/test_market_weather.py tests/test_universe_ranker.py
    pytest -q tests/test_live_runtime_audit.py tests/test_pattern_engine.py
