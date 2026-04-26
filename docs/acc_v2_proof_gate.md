# ACC V2 Proof Gate

This patch adds proof tooling, not more trading behavior.

New tools:
- `tools/v2_readiness_report.py`
- `tools/post_run_governance_runner.py`
- `tools/orion_rowan_separation_audit.py`
- `tools/regime_readiness_report.py`

Purpose:
- summarize V2 readiness in one place
- manually run the full governance chain without starting a paper run
- verify Orion/Rowan role separation
- verify whether regime detection is merely present or actually runtime-visible

Do not treat V2 as done because files exist.
V2 is done when ML, warehouse persistence, governance chain, token/cost controls, memory, and paper-proof artifacts all survive real runs.
