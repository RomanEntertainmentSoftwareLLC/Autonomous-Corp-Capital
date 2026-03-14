#!/usr/bin/env python3
"""Run a smoke-test suite covering the core platform flow."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.python_helper import ensure_repo_root, python_cmd

ensure_repo_root()

@dataclass
class SmokeCommand:
    name: str
    command: List[str]


BASIC_COMMANDS: List[SmokeCommand] = [
    SmokeCommand("compileall", python_cmd(["-m", "compileall", "-q", "."])),
    SmokeCommand("validate company", python_cmd(["tools/validate_company.py", "company_001"])),
    SmokeCommand("validate genome", python_cmd(["tools/validate_genome.py", "company_001"])),
    SmokeCommand("compile genome", python_cmd(["tools/compile_genome.py", "company_001"])),
    SmokeCommand("mutate company", python_cmd(["tools/mutate_company.py", "company_001", "--seed", "1"])),
    SmokeCommand("init warehouse", python_cmd(["tools/init_warehouse.py"])),
    SmokeCommand("ingest results", python_cmd(["tools/ingest_results_to_db.py"])),
    SmokeCommand("query strategy performance", python_cmd(["tools/query_warehouse.py", "strategy_performance"])),
    SmokeCommand("query best strategy", python_cmd(["tools/query_warehouse.py", "best_strategy_by_symbol"])),
    SmokeCommand("query ema params", python_cmd(["tools/query_warehouse.py", "ema_param_profitability"])),
    SmokeCommand("evaluate lifecycle", python_cmd(["tools/evaluate_lifecycle.py"])),
    SmokeCommand("leaderboard", python_cmd(["tools/leaderboard.py"])),
    SmokeCommand("manager decide", python_cmd(["tools/manager_decide.py"])),
    SmokeCommand("manager report", python_cmd(["tools/manager_report.py"])),
    SmokeCommand("generate backlog", python_cmd(["tools/generate_backlog.py"])),
    SmokeCommand("scrum board show", python_cmd(["tools/scrum_board.py", "show"])),
]

TRADE_COMMAND = SmokeCommand(
    "run trade-bot",
    python_cmd([
        "trade-bot.py",
        "--company",
        "company_001",
        "--mode",
        "backtest",
        "--iterations",
        "20",
        "--loop-feed",
    ]),
)


def run_commands(commands: Iterable[SmokeCommand]) -> None:
    for smoke in commands:
        print(f"\n--- Running: {smoke.name} ---")
        result = subprocess.run(smoke.command, check=False)
        if result.returncode != 0:
            raise SystemExit(f"Smoke test '{smoke.name}' failed with exit {result.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpenClaw platform smoke tests")
    parser.add_argument(
        "--skip-trade", action="store_true", help="Skip the heavy trade-bot run at the end"
    )
    args = parser.parse_args()

    commands = list(BASIC_COMMANDS)
    if not args.skip_trade:
        commands.append(TRADE_COMMAND)

    run_commands(commands)
    print("\nSmoke test completed successfully.")


if __name__ == "__main__":
    main()
