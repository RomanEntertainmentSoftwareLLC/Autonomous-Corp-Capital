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
LIVE_TRADE_CONFIRM_PHRASE = "I_UNDERSTAND_THIS_IS_REAL_MONEY"


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


def run_post_run_reports(run_id: str, run_dir: Path) -> None:
    """Run standard proof reports after warehouse ingest."""
    if os.environ.get("ACC_SKIP_POST_RUN_REPORTS", "").strip().lower() in {"1", "true", "yes", "on"}:
        print(f"Post-run reports skipped for {run_id}", flush=True)
        update_metadata(run_dir, post_run_reports={"status": "skipped", "skipped_at": utc_now()})
        return

    reports = [
        ("db_status", [sys.executable, "tools/db_status.py"]),
        ("decision_trace_report", [sys.executable, "tools/decision_trace_report.py"]),
        ("ml_readiness_report", [sys.executable, "tools/ml_readiness_report.py"]),
        ("warehouse_audit", [sys.executable, "tools/warehouse_audit.py"]),
    ]

    log_path = run_dir / "logs" / "post_run_reports.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.setdefault("PYTHONNOUSERSITE", "1")
    report_timeout = env_int("ACC_POST_RUN_REPORT_TIMEOUT_SECONDS", 120)

    results: list[dict[str, Any]] = []

    print(f"Post-run reports starting for {run_id}", flush=True)

    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"[{utc_now()}] post-run reports starting for {run_id}\n")

        for name, cmd in reports:
            started = utc_now()
            log.write(f"\n[{started}] RUN {name}: {' '.join(cmd)}\n")

            try:
                completed = subprocess.run(
                    cmd,
                    cwd=str(ROOT),
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=report_timeout,
                )

                output = completed.stdout or ""
                log.write(output)
                if output and not output.endswith("\n"):
                    log.write("\n")

                ok = completed.returncode == 0
                ended = utc_now()

                log.write(f"[{ended}] DONE {name}: returncode={completed.returncode}\n")

                results.append({
                    "name": name,
                    "returncode": completed.returncode,
                    "started_at": started,
                    "ended_at": ended,
                    "ok": ok,
                })

                status = "OK" if ok else f"FAILED rc={completed.returncode}"
                print(f"Post-run report {name}: {status}", flush=True)

            except subprocess.TimeoutExpired as exc:
                ended = utc_now()
                log.write(f"[{ended}] TIMEOUT {name}: {exc!r}\n")
                results.append({
                    "name": name,
                    "returncode": None,
                    "started_at": started,
                    "ended_at": ended,
                    "ok": False,
                    "timeout": True,
                })
                print(f"WARNING: post-run report {name} timed out", flush=True)

            except Exception as exc:
                ended = utc_now()
                log.write(f"[{ended}] ERROR {name}: {exc!r}\n")
                results.append({
                    "name": name,
                    "returncode": None,
                    "started_at": started,
                    "ended_at": ended,
                    "ok": False,
                    "error": repr(exc),
                })
                print(f"WARNING: post-run report {name} failed: {exc!r}", flush=True)

    ok_count = sum(1 for result in results if result.get("ok"))

    update_metadata(
        run_dir,
        post_run_reports={
            "status": "completed" if ok_count == len(results) else "completed_with_failures",
            "completed_at": utc_now(),
            "ok_count": ok_count,
            "total": len(results),
            "log_path": str(log_path),
            "results": results,
        },
    )

    print(f"Post-run reports completed for {run_id}: {ok_count}/{len(results)} OK", flush=True)


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
        live_trade=bool(args.live_trade),
    )
    return 0



def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def live_trade_requested_is_authorized() -> tuple[bool, list[str]]:
    """Return whether live trading is explicitly authorized by operator gates."""
    failures: list[str] = []

    if not env_bool("ACC_ENABLE_LIVE_TRADING", False):
        failures.append("ACC_ENABLE_LIVE_TRADING must be set to 1/true/yes/on")

    confirm = os.getenv("ACC_LIVE_TRADE_CONFIRM", "")
    if confirm != LIVE_TRADE_CONFIRM_PHRASE:
        failures.append(f"ACC_LIVE_TRADE_CONFIRM must equal {LIVE_TRADE_CONFIRM_PHRASE!r}")

    return (not failures), failures


def assert_live_trade_safety(live_trade: bool) -> None:
    """Fail closed unless live trading was deliberately requested and confirmed."""
    if not live_trade:
        return

    ok, failures = live_trade_requested_is_authorized()
    if not ok:
        details = "; ".join(failures)
        raise SystemExit(
            "Refusing live trading. Paper is the default-safe mode. "
            f"To proceed, pass --live-trade and satisfy safety gates: {details}"
        )



def supervisor_main(live_trade: bool = False) -> int:
    assert_live_trade_safety(live_trade)
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
        "mode": "live" if live_trade else "paper",
        "live_trade_requested": bool(live_trade),
        "live_trade_safety": {
            "requires_flag": "--live-trade",
            "requires_env": "ACC_ENABLE_LIVE_TRADING",
            "requires_confirmation_env": "ACC_LIVE_TRADE_CONFIRM",
            "confirmation_phrase": LIVE_TRADE_CONFIRM_PHRASE,
        },
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

    mode_label = "LIVE-TRADE" if live_trade else "paper"
    print(f"Systemd live-data {mode_label} run starting: {run_id}", flush=True)
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
    if live_trade:
        child_cmd.append("--live-trade")

    proc: subprocess.Popen[Any] | None = None
    exit_code = 0
    try:
        update_metadata(run_dir, status="running", supervisor_started_worker_at=utc_now())
        child_env = os.environ.copy()
        child_env.setdefault("PYTHONNOUSERSITE", "1")
        child_env["LIVE_RUN_MODE"] = "live" if live_trade else "paper"
        child_env.setdefault("ACC_SKIP_CHILD_POST_RUN_GOVERNANCE", "1")
        proc = subprocess.Popen(child_cmd, cwd=str(ROOT), env=child_env, start_new_session=True)
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
        run_post_run_reports(run_id, run_dir)
        update_metadata(run_dir, supervisor_completed_at=utc_now(), supervisor_exit_code=exit_code)

    return exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ACC live-data paper cycle under a supervising wrapper.")
    parser.add_argument("--worker-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-id", help=argparse.SUPPRESS)
    parser.add_argument("--duration-hours", type=float, default=0.0, help=argparse.SUPPRESS)
    parser.add_argument("--virtual-currency", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--live-trade", action="store_true", help="Explicitly request real-money live trading; requires env safety gates.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker_child:
        if not args.run_id:
            raise SystemExit("--worker-child requires --run-id")
        return worker_child_main(args)
    return supervisor_main(live_trade=bool(args.live_trade))


if __name__ == "__main__":
    raise SystemExit(main())
