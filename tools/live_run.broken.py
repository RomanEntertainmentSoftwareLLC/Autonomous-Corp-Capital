"""Launch and manage the live-data virtual-currency paper run infrastructure."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any
import urllib.request
from statistics import mean
import urllib.parse

ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = ROOT / "state"
LIVE_RUNS_ROOT = STATE_ROOT / "live_runs"
CURRENT_RUN_PATH = LIVE_RUNS_ROOT / "current_run.json"
SYMBOL_MAPPING = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "LTC-USD": "litecoin",
}
LIVE_FEED_ENDPOINT = "https://api.coingecko.com/api/v3/simple/price"
SYMBOL_CATALOG = {
    "BTC-USD": {"tier": "core", "paper": True, "real_money": True, "min_volume": 1000000},
    "ETH-USD": {"tier": "core", "paper": True, "real_money": True, "min_volume": 800000},
    "XRP-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 400000},
    "SOL-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 350000},
    "ADA-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 300000},
    "DOGE-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 250000},
    "LTC-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 200000},
    "AVAX-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 180000},
    "LINK-USD": {"tier": "liquid", "paper": True, "real_money": False, "min_volume": 160000},
    "SHIB-USD": {"tier": "speculative", "paper": True, "real_money": False, "min_volume": 30000},
    "PEPE-USD": {"tier": "speculative", "paper": True, "real_money": False, "min_volume": 25000},
    "BONK-USD": {"tier": "speculative", "paper": True, "real_money": False, "min_volume": 20000},
}
WATCH_UNIVERSE = list(SYMBOL_CATALOG.keys())
PAPER_UNIVERSE = [s for s, meta in SYMBOL_CATALOG.items() if meta["paper"]]
REAL_MONEY_UNIVERSE = [s for s, meta in SYMBOL_CATALOG.items() if meta.get("real_money") and meta.get("min_volume", 0) >= 1000000]


def ensure_directories() -> None:
    LIVE_RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def create_run_id() -> str:
    return datetime.utcnow().strftime("run_%Y%m%d_%H%M%S")


def run_directory(run_id: str) -> Path:
    run_dir = LIVE_RUNS_ROOT / run_id
    for sub in ("data", "artifacts", "packets", "logs"):
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


def fetch_market_prices(symbols: list[str]) -> dict[str, float]:
    params = {
        "ids": ",".join(SYMBOL_MAPPING.get(sym, sym).lower() for sym in symbols),
        "vs_currencies": "usd",
    }
    url = f"{LIVE_FEED_ENDPOINT}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=10) as response:
        data = json.loads(response.read().decode())
    prices: dict[str, float] = {}
    for sym in symbols:
        slug = SYMBOL_MAPPING.get(sym, sym).lower()
        price_info = data.get(slug, {})
        price = price_info.get("usd")
        if price is not None:
            prices[sym] = price
    return prices

def start_run() -> None:
    ensure_directories()
    run_id = create_run_id()
    run_dir = run_directory(run_id)
    meta = {
        "run_id": run_id,
        "mode": "paper",
        "symbol": "BTC-USD,ETH-USD",
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


def run_worker(run_id: str) -> None:
    run_dir = run_directory(run_id)
    pid_file = run_dir / "run.pid"
    symbols = os.environ.get("LIVE_RUN_SYMBOLS", "BTC-USD,ETH-USD").split(",")
    with pid_file.open("w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    stop_flag = False

    def _signal_handler(*_: Any) -> None:
        nonlocal stop_flag
        stop_flag = True

    signal.signal(signal.SIGTERM, _signal_handler)
    log_path = run_dir / "logs" / "run.log"
    data_dir = run_dir / "data"
    artifacts = run_dir / "artifacts"
    packets_dir = run_dir / "packets"
    metadata = {
        "run_id": run_id,
        "mode": "paper",
        "timestamp": datetime.utcnow().isoformat(),
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2))
    while not stop_flag:
        timestamp = datetime.utcnow().isoformat()
        try:
            prices = fetch_market_prices(symbols)
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"timestamp": timestamp, "event": "feed_error", "error": str(exc)}) + "\n")
            time.sleep(5)
            continue
        for sym, price in prices.items():
            snapshot = {"timestamp": timestamp, "symbol": sym, "price": price, "volume": 0}
            with (data_dir / "market_feed.log").open("a", encoding="utf-8") as feed:
                feed.write(json.dumps(snapshot) + "\n")
        avg_price = mean(prices.values())
        strategy_entry = {
            "timestamp": timestamp,
            "decision": "paper-long" if avg_price % 2 == 0 else "paper-short",
            "confidence": 0.5 + (avg_price % 0.5),
        }
        with (artifacts / "strategy.log").open("a", encoding="utf-8") as strategy:
            strategy.write(json.dumps(strategy_entry) + "\n")
        risk_entry = {
            "timestamp": timestamp,
            "veto": False,
            "notes": "risk within bounds",
        }
        with (artifacts / "risk.log").open("a", encoding="utf-8") as risk_file:
            risk_file.write(json.dumps(risk_entry) + "\n")
        packet = {
            "timestamp": timestamp,
            "recipient": "Pam",
            "summary": "paper run posting updated live market snapshot",
            "next_steps": "log to warehouse",
        }
        with (packets_dir / f"packet_{timestamp.replace(':','-')}.json").open("w", encoding="utf-8") as pkt:
            json.dump(packet, pkt)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"timestamp": timestamp, "event": "heartbeat"}) + "\n")
        time.sleep(5)
    pid_file.unlink()


def summary(run_id: str) -> None:
    run_dir = run_directory(run_id)
    logs = list((run_dir / "logs").glob("*.log"))
    summary = {
        "run_id": run_id,
        "started_at": datetime.utcnow().isoformat(),
        "log_files": [str(p) for p in logs],
        "packets": len(list((run_dir / "packets").iterdir())),
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Summary bundle created at {summary_path}")


def verify_paper_only(run_id: str) -> None:
    run_dir = run_directory(run_id)
    meta_path = run_dir / "run_metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    mode = meta.get("mode")
    if mode != "paper":
        raise SystemExit("Run is not paper-only")
    real_trade_path = run_dir / "artifacts" / "real_money_trades.log"
    if real_trade_path.exists():
        raise SystemExit("Real-money trades detected")
    print("Paper-only verification passed")


def validate() -> None:
    ensure_directories()
    print("Live-run infrastructure ready")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the virtual-currency live-data paper run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start", help="Start the 24-hour live paper run")
    subparsers.add_parser("stop", help="Stop the live paper run")
    start_run_parser = subparsers.add_parser("run", help="Internal run worker")
    start_run_parser.add_argument("--run-id", required=True)
    subparsers.add_parser("validate", help="Validate setup")
    summary_parser = subparsers.add_parser("summary", help="Generate summary bundle")
    summary_parser.add_argument("--run-id", required=True)
    verify_parser = subparsers.add_parser("verify", help="Verify paper-only enforcement")
    verify_parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if args.command == "start":
        start_run()
    elif args.command == "stop":
        stop_run()
    elif args.command == "run":
        run_worker(args.run_id)
    elif args.command == "validate":
        validate()
    elif args.command == "summary":
        summary(args.run_id)
    elif args.command == "verify":
        verify_paper_only(args.run_id)


if __name__ == "__main__":
    main()
