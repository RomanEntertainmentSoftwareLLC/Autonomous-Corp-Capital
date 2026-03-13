#!/usr/bin/env python3
"""Manage a simple scrum board for the AI trading organization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

BOARD_FILE = Path(__file__).resolve().parent.parent / "scrum_board.json"
BACKLOG_TOOL = Path(__file__).resolve().parent / "generate_backlog.py"

STATES = ["BACKLOG", "READY", "IN_PROGRESS", "TESTING", "REVIEW", "DONE"]


def load_board() -> Dict[str, List[Dict[str, str]]]:
    if not BOARD_FILE.exists():
        return {state: [] for state in STATES}
    return json.loads(BOARD_FILE.read_text())


def save_board(board: Dict[str, List[Dict[str, str]]]) -> None:
    BOARD_FILE.write_text(json.dumps(board, indent=2))


def initialize_board(metric: str) -> None:
    import subprocess
    result = subprocess.run([".venv/bin/python3", str(BACKLOG_TOOL), "--metric", metric], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit("Backlog generation failed")
    data = json.loads(result.stdout)
    board = {state: [] for state in STATES}
    for item in data["items"]:
        entry = {
            "company": item["company"],
            "action": item["action"],
            "details": item["details"],
            "recommendation": item["recommendation"],
            "priority": item["priority"],
        }
        board["BACKLOG"].append(entry)
    save_board(board)
    print(f"Initialized scrum board with {len(board['BACKLOG'])} items")


def move_task(company: str, target: str) -> None:
    if target not in STATES:
        raise SystemExit(f"Invalid state {target}")
    board = load_board()
    found = None
    source = None
    for state, items in board.items():
        for idx, entry in enumerate(items):
            if entry["company"] == company:
                found = entry
                source = state
                del items[idx]
                break
        if found:
            break
    if not found:
        raise SystemExit(f"Company {company} not found on board")
    board[target].append(found)
    save_board(board)
    print(f"Moved {company} from {source} to {target}")


def show_board() -> None:
    board = load_board()
    for state in STATES:
        print(f"{state}:")
        for entry in board[state]:
            print(f"  - {entry['company']} ({entry['recommendation']}, {entry['priority']}): {entry['action']}")
    print(f"Board saved at {BOARD_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage scrum board")
    sub = parser.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="Initialize board from manager backlog")
    init.add_argument("--metric", choices=["account_value", "realized_pnl"], default="account_value")
    sub.add_parser("show", help="Show current board")
    move = sub.add_parser("move", help="Move company to a new state")
    move.add_argument("company")
    move.add_argument("state", choices=STATES)
    args = parser.parse_args()

    if args.cmd == "init":
        initialize_board(args.metric)
    elif args.cmd == "show":
        show_board()
    elif args.cmd == "move":
        move_task(args.company, args.state)


if __name__ == "__main__":
    main()
