#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from tools.init_warehouse import init_database, WAREHOUSE_PATH
from tools.ingest_results_to_db import ingest_live_run


TERMINAL_STATUSES = {"completed", "stopped", "timed_out", "interrupted", "failed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_float(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def load_metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run_metadata.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def update_metadata(run_dir: Path, **updates: object) -> None:
    path = run_dir / "run_metadata.json"
    meta = load_metadata(run_dir)
    meta.update(updates)
    path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_warehouse_ingest(run_id: str, run_dir: Path) -> None:
    if os.environ.get("ACC_SKIP_WAREHOUSE_INGEST", "").strip().lower() in {"1", "true", "yes", "on"}:
        print(f"Warehouse ingest skipped for {run_id}", flush=True)
        return

    try:
        if not WAREHOUSE_PATH.exists():
            init_database(WAREHOUSE_PATH)
        with sqlite3.connect(WAREHOUSE_PATH) as conn:
            ingest_live_run(conn.cursor(), run_dir)
            conn.commit()
        print(f"Warehouse ingest completed for {run_id}", flush=True)
    except Exception as exc:
        print(f"WARNING: warehouse ingest failed for {run_id}: {exc!r}", flush=True)


def terminate_process_group(proc: subprocess.Popen[Any], *, term_grace_seconds: int) -> None:
    """Terminate/kill the worker process group without killing this supervisor."""
    if proc.poll() is not None:
        return

    pgid = proc.pid
    print(f"Hard timeout: terminating worker process group pgid={pgid}", flush=True)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception as exc:
        print(f"WARNING: process-group SIGTERM failed: {exc!r}; falling back to terminate()", flush=True)
        proc.terminate()

    try:
        proc.wait(timeout=max(1, term_grace_seconds))
        print(f"Worker exited after SIGTERM with return code {proc.returncode}", flush=True)
        return
    except subprocess.TimeoutExpired:
        print(f"Worker ignored SIGTERM for {term_grace_seconds}s; sending SIGKILL", flush=True)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception as exc:
        print(f"WARNING: process-group SIGKILL failed: {exc!r}; falling back to kill()", flush=True)
        proc.kill()
    proc.wait()
    print(f"Worker killed with return code {proc.returncode}", flush=True)


def worker_child_main(args: argparse.Namespace) -> int:
    run_worker(
        args.run_id,
        duration_hours=float(args.duration_hours or 0.0),
        virtual_currency=args.virtual_currency,
    )
    return 0


def supervisor_main() -> int:
    duration_hours = env_float("ACC_DURATION_HOURS", 24.0)
    virtual_currency = env_float("ACC_VIRTUAL_CURRENCY", 250.0)
    timeout_grace_seconds = env_int("ACC_RUN_HARD_TIMEOUT_GRACE_SECONDS", 120)
    term_grace_seconds = env_int("ACC_RUN_TERMINATE_GRACE_SECONDS", 20)

    ensure_directories()
    run_id = create_run_id()
    run_dir = run_directory(run_id)

    symbol_list = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = [s.strip() for s in symbol_list.split(",") if s.strip()] if symbol_list else target_symbol_list()
    virtual_budget = virtual_currency_context(virtual_currency)

    effective_duration_hours = float(duration_hours or 0.0)
    hard_timeout_seconds = None
    if effective_duration_hours > 0:
        hard_timeout_seconds = max(1.0, effective_duration_hours * 3600.0 + float(timeout_grace_seconds))

    meta = {
        "run_id": run_id,
        "mode": "paper",
        "symbols": symbols,
        "duration_hours": duration_hours,
        "hard_timeout_seconds": hard_timeout_seconds,
        "hard_timeout_grace_seconds": timeout_grace_seconds,
        "terminate_grace_seconds": term_grace_seconds,
        "started_at": utc_now(),
        "status": "scheduled",
        "supervisor_pid": os.getpid(),
        **virtual_budget,
        "virtual_currency_note": "testing-only virtual capital pool; not real brokerage cash",
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_dir / "run.pid").write_text(str(os.getpid()), encoding="utf-8")
    write_current_run(run_id, os.getpid())

    print(f"Systemd live-data paper run starting: {run_id}", flush=True)
    print(f"Logs at: {run_dir / 'logs' / 'run.log'}", flush=True)
    if hard_timeout_seconds is None:
        print("Hard timeout: disabled because ACC_DURATION_HOURS <= 0", flush=True)
    else:
        print(f"Hard timeout: {hard_timeout_seconds:.1f}s including {timeout_grace_seconds}s grace", flush=True)

    child_cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-child",
        "--run-id",
        run_id,
        "--duration-hours",
        str(effective_duration_hours),
    ]
    if virtual_currency is not None:
        child_cmd.extend(["--virtual-currency", str(virtual_currency)])

    proc: subprocess.Popen[Any] | None = None
    exit_code = 0
    try:
        update_metadata(run_dir, status="running", supervisor_started_worker_at=utc_now())
        proc = subprocess.Popen(child_cmd, cwd=str(ROOT), start_new_session=True)
        write_current_run(run_id, proc.pid, pgid=proc.pid)
        update_metadata(run_dir, worker_pid=proc.pid, worker_pgid=proc.pid)

        try:
            return_code = proc.wait(timeout=hard_timeout_seconds) if hard_timeout_seconds is not None else proc.wait()
        except subprocess.TimeoutExpired:
            exit_code = 124
            update_metadata(run_dir, status="timed_out", timed_out_at=utc_now(), timeout_reason="worker exceeded ACC_DURATION_HOURS plus grace")
            terminate_process_group(proc, term_grace_seconds=term_grace_seconds)
        else:
            exit_code = int(return_code or 0)
            meta_after_worker = load_metadata(run_dir)
            worker_status = meta_after_worker.get("status")
            if exit_code == 0:
                if worker_status not in TERMINAL_STATUSES:
                    update_metadata(run_dir, status="completed", completed_at=utc_now(), worker_return_code=exit_code)
            else:
                update_metadata(run_dir, status="failed", failed_at=utc_now(), worker_return_code=exit_code)

    except KeyboardInterrupt:
        exit_code = 130
        update_metadata(run_dir, status="interrupted", interrupted_at=utc_now())
        print(f"Interrupted by operator for {run_id}", flush=True)
        if proc is not None:
            terminate_process_group(proc, term_grace_seconds=term_grace_seconds)
    finally:
        run_warehouse_ingest(run_id, run_dir)
        update_metadata(run_dir, supervisor_completed_at=utc_now(), supervisor_exit_code=exit_code)

    return exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ACC live-data paper cycle under a supervising wrapper.")
    parser.add_argument("--worker-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument("--duration-hours", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--virtual-currency", type=float, default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker_child:
        if not args.run_id:
            raise SystemExit("--worker-child requires --run-id")
        return worker_child_main(args)
    return supervisor_main()


if __name__ == "__main__":
    raise SystemExit(main())
