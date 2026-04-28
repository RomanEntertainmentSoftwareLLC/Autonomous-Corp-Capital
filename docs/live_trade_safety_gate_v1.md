# Live Trade Safety Gate v1

Adds explicit live-trade safety for supervised ACC runs.

Changed:

    scripts/live_run_systemd.py
    tools/live_trade_safety_audit.py
    tools/v2_readiness_gate.py

Default behavior:

    Paper mode remains the default.

A supervised run can only request live trading with:

    --live-trade

Even with that flag, live trading is refused unless both safety gates are set:

    ACC_ENABLE_LIVE_TRADING=1
    ACC_LIVE_TRADE_CONFIRM=I_UNDERSTAND_THIS_IS_REAL_MONEY

Safety audit:

    PYTHONNOUSERSITE=1 python3 tools/live_trade_safety_audit.py

Readiness gate refresh:

    PYTHONNOUSERSITE=1 python3 tools/v2_readiness_gate.py --refresh

Purpose:

    Make live trading impossible to trigger accidentally before serious proof and human approval.
