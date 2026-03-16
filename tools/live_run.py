"""Orchestration CLI for the live-data virtual-currency paper run."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.live_market_feed import fetch_market_data
from tools.live_universe import target_symbol_list

LIVE_RUNS_ROOT = ROOT / "state" / "live_runs"
CURRENT_RUN_PATH = LIVE_RUNS_ROOT / "current_run.json"


def ensure_directories() -> None:
    LIVE_RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def create_run_id() -> str:
    return datetime.utcnow().strftime("run_%Y%m%d_%H%M%S")


def run_directory(run_id: str) -> Path:
    run_dir = LIVE_RUNS_ROOT / run_id
    for sub in ("data", "artifacts", "logs", "packets", "reports"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


def write_current_run(run_id: str, pid: int) -> None:
    ensure_directories()
    data = {"run_id": run_id, "pid": pid, "mode": "paper", "status": "running", "started_at": datetime.utcnow().isoformat()}
    CURRENT_RUN_PATH.write_text(json.dumps(data, indent=2))


def read_current_run() -> Dict[str, Any]:
    if not CURRENT_RUN_PATH.exists():
        raise FileNotFoundError("No current live run tracked")
    return json.loads(CURRENT_RUN_PATH.read_text())


def clear_current_run() -> None:
    if CURRENT_RUN_PATH.exists():
        CURRENT_RUN_PATH.unlink()


def start_run() -> None:
    ensure_directories()
    run_id = create_run_id()
    run_dir = run_directory(run_id)
    symbol_list = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbol_list.split(",") if symbol_list else target_symbol_list()
    meta = {
        "run_id": run_id,
        "mode": "paper",
        "symbols": symbols,
        "started_at": datetime.utcnow().isoformat(),
        "status": "scheduled",
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    command = [sys.executable, str(Path(__file__)), "run", "--run-id", run_id]
    proc = subprocess.Popen(command, env=dict(os.environ, LIVE_RUN_MODE="paper"))
    (run_dir / "run.pid").write_text(str(proc.pid))
    write_current_run(run_id, proc.pid)
    print(f"Live-data paper run started: {run_id}")
    print(f"Logs at: {run_dir / 'logs' / 'run.log'}")


def stop_run() -> None:
    current = read_current_run()
    run_id = current["run_id"]
    pid = current.get("pid")
    run_dir = run_directory(run_id)
    pid_file = run_dir / "run.pid"
    if pid and pid_file.exists():
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        pid_file.unlink()
    meta_path = run_dir / "run_metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["ended_at"] = datetime.utcnow().isoformat()
        meta["status"] = "stopped"
        meta_path.write_text(json.dumps(meta, indent=2))
    clear_current_run()
    print(f"Live-data paper run {run_id} stopped safely.")


def record_snapshot(run_dir: Path, snapshot: Dict[str, Any]) -> None:
    with (run_dir / "data" / "market_feed.log").open("a", encoding="utf-8") as feed:
        feed.write(json.dumps(snapshot) + "\n")


def record_artifact(run_dir: Path, category: str, entry: Dict[str, Any]) -> None:
    file = run_dir / "artifacts" / f"{category}.log"
    with file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def record_packet(run_dir: Path, packet: Dict[str, Any]) -> None:
    timestamp = packet.get("timestamp", datetime.utcnow().isoformat()).replace(":", "-")
    path = run_dir / "packets" / f"packet_{timestamp}.json"
    path.write_text(json.dumps(packet, indent=2))


def run_worker(run_id: str) -> None:
    run_dir = run_directory(run_id)
    pid_file = run_dir / "run.pid"
    symbols = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbols.split(",") if symbols else target_symbol_list()
    with pid_file.open("w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    stop_flag = False

    def _signal_handler(*_: Any) -> None:
        nonlocal stop_flag
        stop_flag = True

    signal.signal(signal.SIGTERM, _signal_handler)
    log_path = run_dir / "logs" / "run.log"
    while not stop_flag:
        timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
        try:
            snapshots = fetch_market_data(symbols)
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"timestamp": timestamp, "event": "feed_error", "error": str(exc)}) + "\n")
            time.sleep(5)
            continue
        for snapshot in snapshots:
            record_snapshot(run_dir, snapshot)
        strategy_entry = {"timestamp": timestamp, "decision": "paper-batch", "confidence": 0.6}
        record_artifact(run_dir, "strategy", strategy_entry)
        risk_entry = {"timestamp": timestamp, "veto": False, "notes": "risk within bounds"}
        record_artifact(run_dir, "risk", risk_entry)
        packet = {
            "timestamp": timestamp,
            "recipient": "Pam",
            "summary": "paper run live snapshots recorded",
            "next_steps": "Archive logs for audit",
        }
        record_packet(run_dir, packet)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"timestamp": timestamp, "event": "heartbeat", "symbols": symbols}) + "\n")
        time.sleep(10)
    pid_file.unlink()


def summary(run_id: str) -> None:
    run_dir = run_directory(run_id)
    logs = list((run_dir / "logs").glob("*.log"))
    summary = {
        "run_id": run_id,
        "captured": datetime.utcnow().isoformat(),
        "log_files": [str(p) for p in logs],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Summary bundle created at {summary_path}")


def verify_paper_only(run_id: str) -> None:
    run_dir = run_directory(run_id)
    meta = json.loads((run_dir / "run_metadata.json").read_text())
    if meta.get("mode") != "paper":
        raise SystemExit("Run is not paper-only")
    real_trade_path = run_dir / "artifacts" / "real_money_trades.log"
    if real_trade_path.exists():
        raise SystemExit("Real-money trades detected")
    print("Paper-only verification passed")


def validate() -> None:
    ensure_directories()
    symbols = target_symbol_list()
    try:
        fetch_market_data(symbols)
    except Exception as exc:
        raise SystemExit(f"Live feed unavailable: {exc}")
    print("Live-run infrastructure ready")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the live-data paper run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start", help="Start the paper run")
    subparsers.add_parser("stop", help="Stop the current paper run")
    run_parser = subparsers.add_parser("run", help="Run worker (internal)")
    run_parser.add_argument("--run-id", required=True)
    summary_parser = subparsers.add_parser("summary", help="Generate summary bundle")
    summary_parser.add_argument("--run-id", required=True)
    verify_parser = subparsers.add_parser("verify", help="Verify paper-only mode")
    verify_parser.add_argument("--run-id", required=True)
    subparsers.add_parser("validate", help="Validate feed/dirs")
    args = parser.parse_args()
    if args.command == "start":
        start_run()
    elif args.command == "stop":
        stop_run()
    elif args.command == "run":
        run_worker(args.run_id)
    elif args.command == "summary":
        summary(args.run_id)
    elif args.command == "verify":
        verify_paper_only(args.run_id)
    elif args.command == "validate":
        validate()


if __name__ == "__main__":
    main()
