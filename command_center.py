#!/usr/bin/env python3
"""OpenClaw text control center for running helper scripts."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
COMPANIES_DIR = ROOT / "companies"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python3" if (ROOT / ".venv").exists() else sys.executable

MENU_OPTIONS: Dict[int, Tuple[str, Callable[[], None]]] = {}


def clear_screen() -> None:
    if os.name == "nt":
        os.system("cls")
    else:
        os.system("clear")


def prompt(text: str, choices: Optional[List[str]] = None, default: Optional[str] = None) -> str:
    while True:
        display = text
        if choices:
            display += f" [{'/'.join(choices)}]"
        if default:
            display += f" (default: {default})"
        display += ": "
        resp = input(display).strip()
        if not resp and default is not None:
            return default
        if choices and resp not in choices:
            print("Invalid choice, try again.")
            continue
        if resp:
            return resp


def run_command(command: List[str]) -> None:
    print("\nExecuting:", " ".join(command))
    subprocess.run(command)


def list_companies() -> List[str]:
    if not COMPANIES_DIR.exists():
        return []
    return sorted(p.name for p in COMPANIES_DIR.iterdir() if p.is_dir())


def choose_company(prompt_text: str) -> str:
    companies = list_companies()
    if companies:
        print("Detected companies:", ", ".join(companies))
    return prompt(prompt_text + " (enter company id)", default=companies[0] if companies else None)


def run_one_company() -> None:
    company = choose_company("Company to run")
    mode = prompt("Mode", choices=["paper", "backtest", "live"], default="backtest")
    iterations = prompt("Iterations", default="20")
    loop = prompt("Loop feed?", choices=["y", "n"], default="n")
    cmd = [VENV_PYTHON, str(ROOT / "trade-bot.py"), "--company", company, "--mode", mode, "--iterations", iterations]
    if loop.lower() == "y":
        cmd.append("--loop-feed")
    run_command(cmd)


def run_multiple_companies() -> None:
    companies = []
    while True:
        comp = prompt("Add company (blank to stop)", default="")
        if not comp:
            break
        companies.append(comp)
    if not companies:
        print("No companies provided")
        return
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "run_companies.py")]
    for comp in companies:
        cmd.extend(["--company", comp])
    run_command(cmd)


def create_company() -> None:
    company_id = prompt("New company id", default="company_new")
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "create_company.py"), company_id]
    run_command(cmd)


def clone_company() -> None:
    parent = choose_company("Parent company")
    child = prompt("Child company id")
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "clone_company.py"), parent, child]
    run_command(cmd)


def mutate_company() -> None:
    company = choose_company("Company to mutate")
    seed = prompt("Seed (optional)", default="")
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "mutate_company.py"), company]
    if seed:
        cmd.extend(["--seed", seed])
    run_command(cmd)


def evolve_company() -> None:
    parent = choose_company("Parent company")
    child = prompt("Child company id")
    seed = prompt("Seed (optional)", default="")
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "evolve_company.py"), parent, child]
    if seed:
        cmd.extend(["--seed", seed])
    run_command(cmd)


def validate_company() -> None:
    company = choose_company("Company to validate")
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "validate_company.py"), company]
    run_command(cmd)


def run_tester() -> None:
    company = choose_company("Company to test")
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "test_company.py"), company]
    run_command(cmd)


def show_leaderboard() -> None:
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "leaderboard.py")]
    run_command(cmd)


def manager_report() -> None:
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "manager_report.py")]
    run_command(cmd)


def manager_decisions() -> None:
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "manager_decide.py")]
    run_command(cmd)


def generate_backlog() -> None:
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "generate_backlog.py")]
    run_command(cmd)


def scrum_board() -> None:
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "scrum_board.py"), "show"]
    run_command(cmd)


def execute_actions() -> None:
    cmd = [VENV_PYTHON, str(TOOLS_DIR / "execute_manager_actions.py"), "--dry-run"]
    run_command(cmd)


def build_menu() -> Dict[int, Tuple[str, Callable[[], None]]]:
    return {
        1: ("Run one company", run_one_company),
        2: ("Run multiple companies", run_multiple_companies),
        3: ("Create company", create_company),
        4: ("Clone company", clone_company),
        5: ("Mutate company", mutate_company),
        6: ("Evolve company", evolve_company),
        7: ("Validate company", validate_company),
        8: ("Run tester", run_tester),
        9: ("Show leaderboard", show_leaderboard),
        10: ("Manager report", manager_report),
        11: ("Manager decisions", manager_decisions),
        12: ("Generate backlog", generate_backlog),
        13: ("Scrum board", scrum_board),
        14: ("Execute manager actions (dry run)", execute_actions),
        15: ("Exit", lambda: sys.exit(0)),
    }


def interactive_menu() -> None:
    menu = build_menu()
    while True:
        clear_screen()
        print("OpenClaw Trading Control Center")
        print("=" * 40)
        for num, (label, _) in menu.items():
            print(f"{num}. {label}")
        choice = prompt("Select option", default="15")
        if not choice.isdigit() or int(choice) not in menu:
            print("Invalid selection")
            continue
        _, action = menu[int(choice)]
        action()
        input("Press Enter to continue...")


def run_action(action_name: str) -> None:
    menu = build_menu()
    mapping = {label.lower(): func for (_, (label, func)) in menu.items() for label in [label]}
    func = mapping.get(action_name)
    if not func:
        raise SystemExit(f"Unknown action {action_name}")
    func()


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw control center")
    parser.add_argument("--action", help="Non-interactive action name")
    args = parser.parse_args()
    if args.action:
        run_action(args.action.lower())
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
