# Candidate Audit + Graceful Supervised Runs v1

This patch adds three V2 proof improvements.

1. Candidate audit rows

The live run now writes:

    state/live_runs/<run_id>/artifacts/candidate_decisions.jsonl

This captures the ranked candidate slate even when strict trading discipline executes zero trades.

2. Report fallback

The ML readiness and decision trace reports now read candidate_decisions.jsonl when paper_decisions.jsonl is empty.

That means a correct WAIT / skip-all cycle can still prove:

    ML scored candidates
    decision traces existed
    strict gates avoided weak entries

3. Supervised child governance skip

When live_run_systemd.py launches the worker child, it sets:

    ACC_SKIP_CHILD_POST_RUN_GOVERNANCE=1

This prevents the child from running expensive post-run governance before exiting. The parent supervisor still handles warehouse ingest and token-free proof reports.

Purpose:

    Make short supervised paper proofs cleaner, faster, and less likely to end in SIGKILL.
