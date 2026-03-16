"""Orchestration CLI for the live-data virtual-currency paper run."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List
import urllib.error

from tools.live_decision_engine import build_decision, DecisionResult
from tools.live_market_feed import fetch_market_data
from tools.live_orchestra import orchestrate
from tools.live_paper_portfolio import PortfolioState
from tools.live_universe import target_symbol_list

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIVE_RUNS_ROOT = ROOT / "state" / "live_runs"
CURRENT_RUN_PATH = LIVE_RUNS_ROOT / "current_run.json"
LIVE_RUN_POLL_SECONDS = int(os.getenv("LIVE_RUN_POLL_SECONDS", "60"))
LIVE_RUN_BACKOFF_BASE = int(os.getenv("LIVE_RUN_BACKOFF_SECONDS", "60"))
COMPANIES = ["company_001", "company_002", "company_003", "company_004"]


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


def start_run(duration_hours: float = 0.0) -> None:
    ensure_directories()
    run_id = create_run_id()
    run_dir = run_directory(run_id)
    symbol_list = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbol_list.split(",") if symbol_list else target_symbol_list()
    meta = {
        "run_id": run_id,
        "mode": "paper",
        "symbols": symbols,
        "duration_hours": duration_hours,
        "started_at": datetime.utcnow().isoformat(),
        "status": "scheduled",
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    command = [sys.executable, str(Path(__file__)), "run", "--run-id", run_id, "--duration-hours", str(duration_hours)]
    proc = subprocess.Popen(command, env=dict(os.environ, LIVE_RUN_MODE="paper"))
    (run_dir / "run.pid").write_text(str(proc.pid))
    write_current_run(run_id, proc.pid)
    print(f"Live-data paper run started: {run_id}")
    print(f"Logs at: {run_dir / 'logs' / 'run.log'}")


def stop_run(run_id: str | None = None) -> None:
    current = {}
    try:
        current = read_current_run()
    except FileNotFoundError:
        pass
    target_run = run_id or current.get("run_id")
    if not target_run:
        raise SystemExit("No run_id provided and no current run tracked")
    pid = current.get("pid") if current.get("run_id") == target_run else None
    run_dir = run_directory(target_run)
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
    if current.get("run_id") == target_run:
        clear_current_run()
    print(f"Live-data paper run {target_run} stopped safely.")


def record_snapshot(run_dir: Path, snapshot: Dict[str, Any]) -> None:
    with (run_dir / "data" / "market_feed.log").open("a", encoding="utf-8") as feed:
        feed.write(json.dumps(snapshot) + "\n")


def run_worker(run_id: str, duration_hours: float = 0.0) -> None:
    run_dir = run_directory(run_id)
    pid_file = run_dir / "run.pid"
    symbols = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbols.split(",") if symbols else target_symbol_list()
    portfolio = PortfolioState(run_dir)
    with pid_file.open("w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    stop_flag = False
    backoff = 0
    end_time = datetime.utcnow() + timedelta(hours=duration_hours) if duration_hours > 0 else None
    last_prices: Dict[str, float] = {}
    cycle = 0

    def _signal_handler(*_: Any) -> None:
        nonlocal stop_flag
        stop_flag = True

    signal.signal(signal.SIGTERM, _signal_handler)
    log_path = run_dir / "logs" / "run.log"
    while not stop_flag and (not end_time or datetime.utcnow() < end_time):
        cycle += 1
        timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
        try:
            snapshots = fetch_market_data(symbols)
            backoff = 0
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                backoff = max(LIVE_RUN_BACKOFF_BASE, backoff * 2 or LIVE_RUN_BACKOFF_BASE)
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"timestamp": timestamp, "event": "rate_limit", "retry": backoff}) + "\n")
                time.sleep(backoff)
                continue
            raise
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"timestamp": timestamp, "event": "feed_error", "error": str(exc)}) + "\n")
            time.sleep(LIVE_RUN_POLL_SECONDS)
            continue
        anomalies: List[str] = []
        for company in COMPANIES:
            for snapshot in snapshots:
                symbol = snapshot["symbol"]
                decision = build_decision(snapshot, company, last_prices.get((company, symbol)))
                last_prices[(company, symbol)] = snapshot.get("price") or last_prices.get((company, symbol), 0.0)
                record_snapshot(run_dir, snapshot)
                with (run_dir / "artifacts" / "paper_decisions.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(decision) + "\n")
                portfolio.apply_decision(decision)
                if abs(decision.get("signal_score", 0)) > 0.05:
                    anomalies.append(f"{company}:{symbol}")
        orchestrate(run_dir, cycle, anomalies)
        strategy_entry = {"timestamp": timestamp, "decision": "ml-driven", "confidence": 0.7}
        risk_entry = {"timestamp": timestamp, "veto": bool(anomalies), "notes": "risk event" if anomalies else "all good"}
        with (run_dir / "artifacts" / "strategy.log").open("a", encoding="utf-8") as strategy:
            strategy.write(json.dumps(strategy_entry) + "\n")
        with (run_dir / "artifacts" / "risk.log").open("a", encoding="utf-8") as risk_file:
            risk_file.write(json.dumps(risk_entry) + "\n")
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"timestamp": timestamp, "event": "heartbeat", "symbols": symbols}) + "\n")
        time.sleep(LIVE_RUN_POLL_SECONDS)
    pid_file.unlink(missing_ok=True)


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
    snapshots = fetch_market_data(symbols)
    if not snapshots:
        raise SystemExit("Feed returned no snapshot data")
    for snapshot in snapshots:
        if snapshot.get("price") is None or not snapshot.get("timestamp"):
            raise SystemExit("Invalid snapshot data from feed")
    run_dir = run_directory("validate_temp")
    for path in (run_dir / "data" / "market_feed.log", run_dir / "artifacts" / "strategy.log", run_dir / "logs" / "run.log"):
        path.write_text("")
    (run_dir / "artifacts" / "real_money_trades.log").write_text("")
    print("Live-run infrastructure ready")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the live-data paper run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start", help="Start the paper run")
    start_parser.add_argument("--duration-hours", type=float, default=0.0)
    stop_parser = subparsers.add_parser("stop", help="Stop the current paper run")
    stop_parser.add_argument("--run-id", help="Explicit run id to stop")
    run_parser = subparsers.add_parser("run", help="Run worker (internal)")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--duration-hours", type=float, default=0.0)
    summary_parser = subparsers.add_parser("summary", help="Generate summary bundle")
    summary_parser.add_argument("--run-id", required=True)
    verify_parser = subparsers.add_parser("verify", help="Verify paper-only mode")
    verify_parser.add_argument("--run-id", required=True)
    subparsers.add_parser("validate", help="Validate feed/dirs")
    args = parser.parse_args()
    if args.command == "start":
        start_run(duration_hours=args.duration_hours)
    elif args.command == "stop":
        stop_run(run_id=args.run_id)
    elif args.command == "run":
        run_worker(args.run_id, duration_hours=args.duration_hours)
    elif args.command == "summary":
        summary(args.run_id)
    elif args.command == "verify":
        verify_paper_only(args.run_id)
    elif args.command == "validate":
        validate()


if __name__ == "__main__":
    main()
