#!/usr/bin/env python3
"""Reset the risk governor to ACTIVE state."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state" / "risk_governor.json"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"status": "ACTIVE"}
    with STATE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the risk governor to ACTIVE")
    parser.add_argument("--note", help="Optional note explaining the reset")
    args = parser.parse_args()

    state = load_state()
    state.update(
        {
            "status": "ACTIVE",
            "halted_at": None,
            "halt_reason": None,
            "triggered_rule": None,
            "notes": args.note or f"Reset at {datetime.now(timezone.utc).isoformat()}"
        }
    )
    save_state(state)
    print("Risk governor reset to ACTIVE")


if __name__ == "__main__":
    main()
