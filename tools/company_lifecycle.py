#!/usr/bin/env python3
"""Lifecycle helpers for company-local rosters."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.company_roster import retire_company, restore_company, roster_sync


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage company lifecycle and roster sync")
    subparsers = parser.add_subparsers(dest="command", required=True)

    retire = subparsers.add_parser("retire", help="Archive and retire a company and its employees")
    retire.add_argument("company", help="Company id to retire (e.g., company_001)")
    retire.add_argument("--event-id", help="Optional event id for the retirement manifest")

    test_retire = subparsers.add_parser("test-retire", help="Test retiring and restoring a company")
    test_retire.add_argument("company", help="Company id to test retire")
    test_retire.add_argument("--event-id", help="Optional event id to use during the test")

    restore = subparsers.add_parser("restore", help="Restore a company from a retirement manifest")
    restore.add_argument("manifest", type=Path, help="Path to the retirement manifest JSON")

    sync = subparsers.add_parser("roster-sync", help="Ensure company rosters match active companies")

    args = parser.parse_args()

    if args.command == "retire":
        event_id = args.event_id or str(uuid.uuid4())
        manifest = retire_company(args.company, retire_mode="retire", event_id=event_id)
        print(f"Retirement manifest written to {manifest}")
    elif args.command == "test-retire":
        event_id = args.event_id or str(uuid.uuid4())
        manifest = retire_company(args.company, retire_mode="test_retire", event_id=event_id, test_mode=True)
        print(f"Test retirement recorded at {manifest}")
        print("Validating roster has removed the agents...")
        roster_sync()
        print("Restoring company and agents from archive...")
        restore_company(manifest)
        print("Restore complete. Roster synced back to active state.")
    elif args.command == "restore":
        if not args.manifest.exists():
            print(f"Manifest {args.manifest} not found", file=sys.stderr)
            sys.exit(1)
        restore_company(args.manifest)
        print(f"Company restored from {args.manifest}")
    elif args.command == "roster-sync":
        roster_sync()
        print("Roster sync complete.")


if __name__ == "__main__":
    main()
