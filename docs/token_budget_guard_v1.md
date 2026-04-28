# Token Budget Guard v1

Adds a token-free budget guard report.

Tools added or updated:

    tools/token_budget_guard.py
    tools/v2_readiness_gate.py

Purpose:

    Turn Ledger usage telemetry into simple budget stages.

Stages:

    NORMAL      below 70%
    CAUTION     70% or more
    DEGRADED    80% or more
    RESTRICTED  90% or more
    EMERGENCY   98% or more

Default budget:

    ACC_TOKEN_BUDGET_USD=1.00

Override example:

    ACC_TOKEN_BUDGET_USD=5.00 PYTHONNOUSERSITE=1 python3 tools/token_budget_guard.py

Readiness refresh:

    PYTHONNOUSERSITE=1 python3 tools/v2_readiness_gate.py --refresh

This is a reporting/control foundation, not full enforcement yet.
