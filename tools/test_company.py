#!/usr/bin/env python3
"""Simple tester for company configs."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
TRADEBOT_ENTRY = Path(__file__).resolve().parent.parent / "trade-bot.py"


def run_command(label: str, args: Sequence[str], *, expect_success: bool = True) -> bool:
    full_cmd = [sys.executable, str(TRADEBOT_ENTRY), *args]
    print(f"Running {label}: {shlex.join(full_cmd)}")
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    if expect_success and result.returncode == 0:
        print(f"[PASS] {label}")
        return True
    if not expect_success and result.returncode != 0:
        print(f"[PASS] {label} (failed as expected)")
        print(capitalize_output(result.stderr))
        return True
    print(f"[FAIL] {label}")
    print(capitalize_output(result.stdout))
    print(capitalize_output(result.stderr))
    return False


def capitalize_output(message: str) -> str:
    return message.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run basic sanity checks for a company's setup")
    parser.add_argument("company", help="Company directory name under companies/")
    parser.add_argument("--iterations", type=int, default=4, help="Number of ticks to run for paper/backtest")
    args = parser.parse_args()

    paper_cmd = ["--company", args.company, "--mode", "paper", "--iterations", str(args.iterations), "--loop-feed"]
    backtest_cmd = ["--company", args.company, "--mode", "backtest", "--iterations", str(args.iterations), "--loop-feed"]
    live_cmd = ["--company", args.company, "--mode", "live", "--iterations", "1"]

    results = []
    results.append(run_command("paper mode", paper_cmd))
    results.append(run_command("backtest mode", backtest_cmd))
    results.append(run_command("live safety", live_cmd, expect_success=False))

    if all(results):
        print("\nAll checks passed.")
        sys.exit(0)
    print("\nOne or more checks failed.")
    sys.exit(1)


if __name__ == "__main__":
    main()
