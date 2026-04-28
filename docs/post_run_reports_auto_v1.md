# Post-Run Reports Auto v1

This patch updates `scripts/live_run_systemd.py` so every supervised paper cycle automatically runs the core proof reports after warehouse ingest:

- `tools/decision_trace_report.py`
- `tools/ml_readiness_report.py`
- `tools/warehouse_audit.py`

## Why

The operator should not have to manually run the same verification commands after every paper cycle.

## Behavior

After the worker exits, times out, or is interrupted, the supervisor:

1. Attempts warehouse ingest.
2. Runs post-run reports best-effort.
3. Writes report output to:

```text
state/live_runs/<run_id>/logs/post_run_reports.log