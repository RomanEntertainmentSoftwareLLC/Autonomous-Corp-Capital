# Live Run Warehouse Ingest Fix v1

Adds live-run artifact ingestion to `tools/ingest_results_to_db.py`.

## Why

The existing warehouse ingest tool only read legacy `results/<company>/<mode>` logs. Fresh ACC paper runs write richer artifacts under:

```text
state/live_runs/<run_id>/artifacts/
```

So ML and decision trace reports could prove fresh run activity while `data/warehouse.sqlite` stayed empty unless an older legacy results folder was ingested.

## What changed

- Adds `--live-run <run_id|path|latest>` to `tools/ingest_results_to_db.py`.
- Adds `--latest-live-run` shortcut.
- Ingests `paper_decisions.jsonl`, `paper_trades.jsonl`, `portfolio_state.jsonl`, and `company_packets.jsonl`.
- Creates one warehouse `runs` row per company found in a live run.
- Populates ticks, features, trades, trade_facts, results, evaluations, and company_performance where data is available.
- Keeps the older legacy `results/<company>/<mode>` ingest behavior unchanged.
- Updates `scripts/live_run_systemd.py` to attempt post-run live artifact ingestion automatically unless `ACC_SKIP_WAREHOUSE_INGEST=1`.

## Verify

```bash
PYTHONNOUSERSITE=1 python3 -m py_compile tools/ingest_results_to_db.py scripts/live_run_systemd.py

PYTHONNOUSERSITE=1 python3 tools/ingest_results_to_db.py --live-run latest
PYTHONNOUSERSITE=1 python3 tools/db_status.py
PYTHONNOUSERSITE=1 python3 tools/warehouse_audit.py
```

Expected: warehouse row counts increase and `warehouse_audit.py` reports `warehouse_has_data`.
