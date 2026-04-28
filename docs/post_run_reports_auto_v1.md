# Post-Run Reports Auto v1

`live_run_systemd.py` now runs token-free proof reports automatically after warehouse ingest.

Reports:

- `tools/db_status.py`
- `tools/decision_trace_report.py`
- `tools/ml_readiness_report.py`
- `tools/warehouse_audit.py`

Output goes to:

```text
state/live_runs/<run_id>/logs/post_run_reports.log