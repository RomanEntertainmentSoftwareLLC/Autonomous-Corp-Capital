"""Lightweight smoke tests covering key roles, lifecycle ops, and packet schemas."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import yaml

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
ENV = dict(os.environ, PYTHONPATH=str(ROOT))


def run_agent(agent: str, message: str) -> Dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(TOOLS / "pam.py"), "--agent", agent, message],
        check=True,
        capture_output=True,
        text=True,
        env=ENV,
    )
    data = json.loads(result.stdout)
    assert data.get("from") == agent, f"Unexpected from for {agent}"
    packets = data.get("packets")
    if packets is not None:
        assert isinstance(packets, list) and packets, "Packets missing"
        for packet in packets:
            assert "recipient" in packet and "summary" in packet and "next_steps" in packet
    return data


def cleanup_clone(company: str, manifest_path: Path) -> None:
    for candidate in (ROOT / "companies" / company, ROOT / "state" / "archive" / "companies" / company):
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
    for agents_dir in (ROOT / "state" / "agents", ROOT / "state" / "archive" / "agents"):
        for path in agents_dir.glob(f"*_{company}"):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
    if manifest_path.exists():
        manifest_path.unlink()

def prune_smoke_agents() -> None:
    config_path = ROOT / "config" / "agents.yaml"
    data = yaml.safe_load(config_path.read_text()) or {}
    entries = data.get("agents", [])
    filtered = [entry for entry in entries if entry.get("scope") != "company_smoke"]
    if len(filtered) != len(entries):
        data["agents"] = filtered
        config_path.write_text(yaml.safe_dump(data, sort_keys=False))


def count_global_agents() -> int:
    config_path = ROOT / "config" / "agents.yaml"
    data = yaml.safe_load(config_path.read_text()) or {}
    return sum(1 for entry in data.get("agents", []) if entry.get("agent_kind") != "company_local")


def smoke_lifecycle() -> None:
    initial_global = count_global_agents()
    clone_cmd = [sys.executable, str(TOOLS / "clone_company.py"), "company_001", "company_smoke"]
    subprocess.run(clone_cmd, check=True, env=ENV)
    test_retire_cmd = [
        sys.executable,
        str(TOOLS / "company_lifecycle.py"),
        "test-retire",
        "company_smoke",
    ]
    result = subprocess.run(test_retire_cmd, check=True, capture_output=True, text=True, env=ENV)
    manifest_line = next((line for line in result.stdout.splitlines() if line.startswith("Test retirement recorded at ")), "")
    if not manifest_line:
        raise SystemExit("Cannot find manifest path from test-retire output")
    manifest_path = Path(manifest_line.split("Test retirement recorded at ", 1)[1].strip())
    if not manifest_path.exists():
        raise SystemExit(f"Expected manifest {manifest_path} missing")
    roster_sync_cmd = [sys.executable, str(TOOLS / "company_lifecycle.py"), "roster-sync"]
    subprocess.run(roster_sync_cmd, check=True, env=ENV)
    post_sync_global = count_global_agents()
    assert post_sync_global == initial_global, "Global agent registry changed after roster-sync"
    prune_smoke_agents()
    cleanup_clone("company_smoke", manifest_path)


def main() -> None:
    branches = [
        ("bianca_company_001", "Can you sum up company_001 runway?"),
        ("master_treasurer", "How healthy is the treasury?"),
        ("senior_software_engineer", "Integration risk on shared runtime?"),
        ("inspector_general", "Any branch overreach right now?"),
    ]
    for agent, message in branches:
        run_agent(agent, message)
    run_agent("product_manager", "What should the engineering team build next?")
    run_agent("qa", "Is this release ready from QA?")
    smoke_lifecycle()
    print("Smoke tests passed")


if __name__ == "__main__":
    main()
