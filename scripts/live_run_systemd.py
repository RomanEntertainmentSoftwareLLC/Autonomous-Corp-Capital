#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.live_run import (
    ensure_directories,
    create_run_id,
    run_directory,
    write_current_run,
    virtual_currency_context,
    run_worker,
)
from tools.live_universe import target_symbol_list


def env_float(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def main() -> None:
    duration_hours = env_float("ACC_DURATION_HOURS", 24.0)
    virtual_currency = env_float("ACC_VIRTUAL_CURRENCY", 250.0)

    ensure_directories()
    run_id = create_run_id()
    run_dir = run_directory(run_id)

    symbol_list = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbol_list.split(",") if symbol_list else target_symbol_list()
    virtual_budget = virtual_currency_context(virtual_currency)

    meta = {
        "run_id": run_id,
        "mode": "paper",
        "symbols": symbols,
        "duration_hours": duration_hours,
        "started_at": datetime.utcnow().isoformat(),
        "status": "scheduled",
        **virtual_budget,
        "virtual_currency_note": "testing-only virtual capital pool; not real brokerage cash",
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    (run_dir / "run.pid").write_text(str(os.getpid()))
    write_current_run(run_id, os.getpid())

    print(f"Systemd live-data paper run starting: {run_id}", flush=True)
    print(f"Logs at: {run_dir / 'logs' / 'run.log'}", flush=True)

    run_worker(
        run_id,
        duration_hours=float(duration_hours or 0.0),
        virtual_currency=virtual_currency,
    )


if __name__ == "__main__":
    main()
