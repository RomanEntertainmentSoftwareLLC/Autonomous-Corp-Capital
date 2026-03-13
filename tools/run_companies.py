#!/usr/bin/env python3
"""Launcher for running multiple companies simultaneously."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.lifecycle_filter import load_state as load_lifecycle_state, should_include as should_include_state

SCRIPT_DIR = Path(__file__).resolve().parent
TRADE_BOT = SCRIPT_DIR.parent / "trade-bot.py"
COMPANIES_ROOT = SCRIPT_DIR.parent / "companies"
STATE_FILE = SCRIPT_DIR.parent / "state" / "risk_governor.json"


@dataclass
class LaunchSpec:
    company: str
    mode: str
    iterations: int
    loop_feed: bool


def parse_company_spec(raw: str, defaults: LaunchSpec) -> LaunchSpec:
    parts = raw.split(":")
    company = parts[0]
    if not company:
        raise ValueError("Company name cannot be empty")

    mode = parts[1] if len(parts) > 1 and parts[1] else defaults.mode
    iterations = defaults.iterations
    if len(parts) > 2 and parts[2]:
        iterations = int(parts[2])

    loop_feed = defaults.loop_feed
    if len(parts) > 3 and parts[3]:
        token = parts[3].lower()
        if token in {"loop", "loop-feed", "loopfeed"}:
            loop_feed = True
        elif token in {"noloop", "no-loop", "no_loop"}:
            loop_feed = False
        else:
            raise ValueError(f"Unknown loop token '{parts[3]}' for {company}")

    return LaunchSpec(company=company, mode=mode, iterations=iterations, loop_feed=loop_feed)


def parse_manifest(path: Path, defaults: LaunchSpec) -> List[LaunchSpec]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest file '{path}' not found")

    data = yaml.safe_load(path)
    if data is None:
        return []

    entries = data if isinstance(data, list) else data.get("companies") if isinstance(data, dict) else None
    if entries is None:
        raise ValueError("Manifest must be a list or a dict with a 'companies' key")

    specs: List[LaunchSpec] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each manifest entry must be a mapping")
        company = entry.get("company")
        if not company:
            raise ValueError("Manifest entry missing 'company' field")
        mode = entry.get("mode", defaults.mode)
        iterations = int(entry.get("iterations", defaults.iterations))
        loop_feed = bool(entry.get("loop_feed", defaults.loop_feed))
        specs.append(LaunchSpec(company=company, mode=mode, iterations=iterations, loop_feed=loop_feed))
    return specs


def resolve_company_config(company: str) -> Path:
    config_path = COMPANIES_ROOT / company / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Company config missing for '{company}' at {config_path}")
    return config_path


def load_governor_state() -> Dict[str, Optional[str]]:
    if not STATE_FILE.exists():
        return {"status": "ACTIVE"}
    with STATE_FILE.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def launch_processes(specs: Sequence[LaunchSpec]) -> None:
    state = load_governor_state()
    if state.get("status") == "HALTED":
        reason = state.get("halt_reason") or "Risk governor halted trading"
        print("Governor HALT detected:", reason)
        return

    processes = []
    LOG_DIR = SCRIPT_DIR.parent / "logs"
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("[launcher] launching companies:")
    print(f"{'Company':<12} {'Mode':<10} {'Iters':<6} {'Loop':<5} {'Log File'}")
    for spec in specs:
        log_name = f"{spec.company}-{spec.mode}.log"
        log_path = LOG_DIR / log_name
        print(f"{spec.company:<12} {spec.mode:<10} {spec.iterations:<6} {str(spec.loop_feed):<5} {log_path}")

    for spec in specs:
        resolve_company_config(spec.company)
        cmd = [sys.executable, str(TRADE_BOT), "--company", spec.company, "--mode", spec.mode, "--iterations", str(spec.iterations)]
        if spec.loop_feed:
            cmd.append("--loop-feed")
        log_name = f"{spec.company}-{spec.mode}.log"
        log_path = LOG_DIR / log_name
        log_file = open(log_path, "a", encoding="utf-8")
        print(f"[launcher] starting {spec.company} ({spec.mode}) iterations={spec.iterations} loop-feed={spec.loop_feed}")
        print(f"[launcher] command: {shlex.join(cmd)}")
        print(f"[launcher] logging to {log_path}")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        processes.append((spec, proc, log_file, log_path))

    interrupted = False
    try:
        for spec, proc, log_file, _ in processes:
            ret = proc.wait()
            log_file.flush()
            print(f"[launcher] {spec.company} exited with code {ret}")
    except KeyboardInterrupt:
        interrupted = True
        print("[launcher] interrupted; terminating remaining processes...")
        for spec, proc, log_file, _ in processes:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            log_file.flush()
        print("[launcher] shutdown complete; all child processes terminated.")
        raise
    finally:
        for _, _, log_file, _ in processes:
            log_file.close()
        if interrupted and processes:
            summary = ", ".join(f"{spec.company}-{spec.mode}" for spec, *_ in processes)
            print(f"[launcher] terminated companies: {summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch multiple companies concurrently")
    parser.add_argument("--company", action="append", help="Company spec: name[:mode[:iterations[:loop]]] (loop=loop-feed to enable)")
    parser.add_argument("--manifest", type=Path, help="Optional manifest file describing companies")
    parser.add_argument("--mode", default="backtest", help="Default mode for all companies")
    parser.add_argument("--iterations", type=int, default=20, help="Default iteration count for all companies")
    parser.add_argument("--loop-feed", action="store_true", help="Default loop-feed behavior")
    parser.add_argument("--include-paused", action="store_true", help="Include paused companies in the launch")
    args = parser.parse_args()

    defaults = LaunchSpec(company="", mode=args.mode, iterations=args.iterations, loop_feed=args.loop_feed)
    specs: List[LaunchSpec] = []

    if args.manifest:
        specs.extend(parse_manifest(args.manifest, defaults))
    if args.company:
        for raw in args.company:
            specs.append(parse_company_spec(raw, defaults))

    if not specs:
        parser.error("Provide at least one --company spec or a --manifest file")

    def filter_specs(items: List[LaunchSpec]) -> List[LaunchSpec]:
        filtered = []
        for spec in items:
            state = load_lifecycle_state(spec.company)
            if should_include_state(state, include_paused=args.include_paused):
                filtered.append(spec)
            else:
                print(f"Skipping {spec.company} (state={state})")
        return filtered

    specs = filter_specs(specs)
    if not specs:
        parser.error("No companies eligible for launch after lifecycle filtering")

    launch_processes(specs)


if __name__ == "__main__":
    main()
