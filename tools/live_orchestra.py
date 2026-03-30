"""Orchestrate disciplined branch participation for live paper runs."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

BRANCH_PARTICIPANTS = {
    "company_local": ["Iris", "Vera", "Bianca", "Lucian", "June", "Pam"],
    "master": ["Selene", "Helena", "Vivienne", "Yam Yam"],
    "watchdog": ["Mara", "Justine", "Owen"],
}


def branch_packet(run_dir: Path, role: str, summary: str, participants: List[str]) -> None:
    packet = {
        "timestamp": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(),
        "role": role,
        "summary": summary,
        "participants": participants,
    }
    path = run_dir / "packets" / f"packet_{role}_{int(time.time())}.json"
    path.write_text(json.dumps(packet, indent=2))


def orchestrate(run_dir: Path, cycle: int, cycle_decisions: List[Dict[str, Any]], anomalies: List[str]) -> None:
    if cycle % 5 == 0 and cycle_decisions:
        participants = BRANCH_PARTICIPANTS["company_local"]
        summary = (
            f"Orchestration summary: cycle produced {len(cycle_decisions)} executed decision(s); "
            "company_local packet records meta-level routing only, not verified fresh direct participation by each listed role."
        )
        branch_packet(run_dir, "company_local", summary, participants)
        master_summary = (
            "Meta summary from cycle data: master packet reflects orchestration-level oversight context only, not verified fresh direct participation by each listed role."
        )
        branch_packet(run_dir, "master", master_summary, BRANCH_PARTICIPANTS["master"])
    if anomalies:
        summary = (
            f"Anomaly meta summary: detected anomalies = {', '.join(anomalies)}; watchdog packet records orchestration-level escalation context only, "
            "not verified fresh direct participation by each listed role."
        )
        branch_packet(run_dir, "watchdog", summary, BRANCH_PARTICIPANTS["watchdog"])
