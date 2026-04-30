# ACC V3-A Batch 4 Closeout

## Scope

This closeout locks in the V3-A trace-audit proof and supporting cleanup.

## Completed

### V3-A trace proof

A short supervised paper run was executed:

    PYTHONNOUSERSITE=1 python3 scripts/live_run_systemd.py --duration-hours 0.03 --virtual-currency 250

Run ID:

    run_20260430_034554

The corrected supervisor timeout was confirmed:

    Hard timeout: 228.0s including 120s grace

The V3-A trace field audit passed:

    Status: PASS
    Reason: all_required_v3a_trace_fields_present
    Candidate rows: 96
    BUY: 70
    HOLD_POSITION: 6
    WAIT: 20
    WAIT rows missing wait_reason/wait_reason_detail fields: 0

### Runtime proof

The run ingested into the warehouse for all four companies and post-run reports completed successfully:

    db_status: OK
    decision_trace_report: OK
    ml_readiness_report: OK
    warehouse_audit: OK

### CLI duration fix

`scripts/live_run_systemd.py` now honors CLI-provided `--duration-hours` and `--virtual-currency` instead of letting supervisor mode silently fall back to environment/default values.

This fixed the bug where:

    --duration-hours 0.03

was supervised as:

    24 hours + 120 seconds grace

instead of:

    108 seconds + 120 seconds grace

### Datetime cleanup

Active runtime/support modules were cleaned up to avoid deprecated `datetime.utcnow()` usage. Backup and broken legacy files were intentionally not modified.

### Dependency warning handling

`PYTHONNOUSERSITE=1` was used to avoid mixing user-local NumPy 2.4.4 with system SciPy 1.11.4.

## Files added or updated

V3-A modules and reports:

- tools/market_regime.py
- tools/market_weather.py
- tools/universe_ranker.py
- tools/v3a_regime_posture_report.py
- tools/v3a_trace_field_audit.py

Runtime wiring and fixes:

- tools/live_run.py
- tools/live_decision_engine.py
- scripts/live_run_systemd.py
- tools/live_paper_portfolio.py
- tools/ingest_results_to_db.py
- tools/live_orchestra.py
- tools/run_swe_task.py
- tools/allocate_capital.py
- tools/live_market_feed.py
- tools/self_play.py
- tools/evolve_genome.py

Tests:

- tests/test_market_regime.py
- tests/test_market_weather.py
- tests/test_universe_ranker.py
- tests/test_v3a_regime_posture_report.py
- tests/test_v3a_candidate_trace_fields.py
- tests/test_v3a_trace_field_audit.py
- tests/test_live_run_systemd_cli_duration.py

Reports:

- reports/v3a_trace_field_audit.txt
- reports/v3a_regime_posture_report.txt

## Safety

This batch does not add real-money behavior.

It does not:

- change live-trade gates
- call agents
- call Hermes
- mutate portfolios directly
- bypass V2 safety checks
- add dashboard behavior
- add PayPal/treasury automation

## Known follow-up

The supervisor timeout is now calculated correctly. However, the worker still needed supervisor termination at the hard timeout and then exited with return code 0. Because the run ingested cleanly and all post-run reports completed, this is acceptable for tonight.

Later follow-up:

- inspect why the worker does not gracefully self-end before supervisor hard timeout
- decide whether the worker loop needs cleaner duration shutdown semantics

## Test commands used

    PYTHONNOUSERSITE=1 pytest -q tests/test_live_run_systemd_cli_duration.py
    PYTHONNOUSERSITE=1 pytest -q tests/test_market_regime.py tests/test_market_weather.py tests/test_universe_ranker.py tests/test_v3a_regime_posture_report.py tests/test_v3a_candidate_trace_fields.py tests/test_v3a_trace_field_audit.py
    PYTHONNOUSERSITE=1 pytest -q tests/test_live_runtime_audit.py tests/test_pattern_engine.py

## Result

ACC V3-A now has deterministic market-regime helpers, market-weather summaries, universe ranking helpers, trace wiring, WAIT reason fields, a posture report, and a real-run trace field audit proof.

This is the first working ACC V3-A market-awareness layer.
