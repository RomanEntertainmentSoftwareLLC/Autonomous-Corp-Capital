"""Orchestrate branch participation for live paper runs."""
from __future__ import annotations
import time


import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

BRANCHES = {
    "company_local": ["Iris", "Vera", "Bianca", "Lucian", "June", "Pam"],
    "master": ["Selene", "Helena", "Vivienne", "Yam Yam"],
    "watchdog": ["Mara", "Justine", "Owen"],
}


def branch_packet(run_dir: Path, branch: str, summary: str) -> None:
    packet = {
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "branch": branch,
        "summary": summary,
        "participants": BRANCHES.get(branch, []),
    }
    path = run_dir / "packets" / f"packet_{branch}_{int(time.time())}.json"
    path.write_text(json.dumps(packet, indent=2))


def orchestrate(run_dir: Path, cycle: int, cycle_decisions: List[Dict[str, Any]], anomalies: List[str]) -> None:
    if cycle % 5 == 0:
        branch_packet(run_dir, "company_local", f"Company cycle {cycle}: {len(cycle_decisions)} decisions logged.")
        branch_packet(run_dir, "master", "Master branches reviewed treasury posture and reinforced reserve discipline.")
    if anomalies:
        branch_packet(run_dir, "watchdog", f"Anomalies detected: {', '.join(anomalies)}")
