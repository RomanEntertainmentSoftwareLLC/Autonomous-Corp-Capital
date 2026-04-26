# External Plan Context Live-Run Binding

This patch ties the planning files into the live-run stream.

New files:
- `docs/roadmap_context/*.txt`
- `tools/external_plan_context_snapshot.py`
- `tools/install_external_plan_context_hook.py`

Purpose:
- Keep the ACC roadmap, V2 plan, V3/Dreambot deltas, roster, Grant plan, and Hermes/memory notes visible to live-run governance.
- Write a concise snapshot into:
  - `state/external_plan_context/<run_id>_external_plan_context.json`
  - `state/external_plan_context/<run_id>_external_plan_context.txt`
  - `state/external_plan_context/latest_external_plan_context.*`
  - `state/live_runs/<run_id>/artifacts/external_plan_context.*` when a run artifact directory exists.

Install hook:
```bash
python3 tools/install_external_plan_context_hook.py
python3 -m py_compile tools/live_run.py tools/external_plan_context_snapshot.py tools/install_external_plan_context_hook.py
```

Disable for emergencies:
```bash
DISABLE_EXTERNAL_PLAN_CONTEXT=1
```

This is read-only/non-fatal governance context. It must never kill a live run.
