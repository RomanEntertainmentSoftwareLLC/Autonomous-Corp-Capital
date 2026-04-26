#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path("/opt/openclaw/.openclaw/workspace")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.rpg_state import load_rpg_state

MEMORY_ROOT = ROOT / "ai_agents_memory"
REPORTS = ROOT / "reports"

MASTER_TOOLS = {
    "ledger": "python3 tools/ledger_cost_review.py",
    "helena": "python3 tools/helena_risk_review.py",
    "axiom": "python3 tools/axiom_evaluator_review.py",
    "vivienne": "python3 tools/vivienne_financial_review.py",
    "selene": "python3 tools/selene_treasury_review.py",
    "ariadne": "python3 tools/ariadne_workforce_review.py",
    "grant_cardone": "python3 tools/grant_speech_review.py",
    "main": "python3 tools/yam_yam_executive_review.py",
}

SUPPORT_TASKS = {
    "pam": "coordination",
    "bob": "operations",
    "rowan": "research",
    "atlas": "simulation",
    "sloane": "evolution",
    "june": "archive",
}

SWE = {"nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea"}
WATCHDOGS = {"mara", "justine", "owen"}


def _discover_agents() -> list[str]:
    agents: set[str] = set()
    if MEMORY_ROOT.exists():
        for p in MEMORY_ROOT.iterdir():
            if p.is_dir():
                agents.add(p.name)
    backup = ROOT / "ai_agents_backup"
    if backup.exists():
        for ag in backup.glob("**/AGENTS.md"):
            # infer from folder names where possible
            folder = ag.parent.name
            if folder == "yam_yam":
                agents.add("main")
            elif folder.endswith("_company_001") or folder.endswith("_company_002") or folder.endswith("_company_003") or folder.endswith("_company_004"):
                agents.add(folder.replace("_analyst_", "_").replace("_cfo_", "_").replace("_ceo_", "_"))
            else:
                # direct folder names like vivienne_master_cfo are not reliable, so rely mostly on memory root
                pass
    return sorted(agents)


def _role(agent_id: str) -> str:
    if agent_id in MASTER_TOOLS:
        return "master"
    if agent_id in WATCHDOGS:
        return "watchdog"
    if agent_id in SWE:
        return "swe"
    if "_company_" in agent_id:
        return "company"
    return "unknown"


def _suggest(agent_id: str) -> str:
    if agent_id in MASTER_TOOLS:
        return MASTER_TOOLS[agent_id]
    if agent_id in WATCHDOGS:
        return f"python3 tools/lucian_watchdog_accountability_review.py --dry-run  # watchdog checked by Lucian; direct watchdog activation later only on dispute"
    for prefix, task in SUPPORT_TASKS.items():
        if agent_id.startswith(prefix + "_company_"):
            return f"python3 tools/support_agent_review.py --agent {agent_id} --task {task}"
    if agent_id.startswith("lucian_company_"):
        return f"python3 tools/lucian_watchdog_accountability_review.py --agent {agent_id}"
    return f"# No activation command mapped yet for {agent_id}"


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    agents = _discover_agents()
    rows: list[dict[str, Any]] = []
    for agent_id in agents:
        state_path = MEMORY_ROOT / agent_id / "RPG_STATE.md"
        hist_path = MEMORY_ROOT / agent_id / "RPG_HISTORY.md"
        mem_path = MEMORY_ROOT / agent_id / "MEMORY.md"
        state = load_rpg_state(state_path)
        xp = float(state.get("xp") or 0)
        sessions = int(state.get("sessions") or 0)
        role = _role(agent_id)
        rows.append({
            "agent_id": agent_id,
            "role": role,
            "xp": xp,
            "sessions": sessions,
            "has_rpg_state": state_path.exists(),
            "has_rpg_history": hist_path.exists(),
            "has_memory": mem_path.exists(),
            "recommended_command": _suggest(agent_id),
        })

    zero_non_swe = [r for r in rows if r["xp"] <= 0 and r["role"] != "swe"]
    active = [r for r in rows if r["xp"] > 0]
    text: list[str] = []
    text.append("ACC Idle Employee Activation Report")
    text.append("=" * 36)
    text.append("")
    text.append(f"Agents discovered: {len(rows)}")
    text.append(f"Active agents: {len(active)}")
    text.append(f"Zero-XP non-SWE agents: {len(zero_non_swe)}")
    text.append("")
    text.append("Recommended no-paper activation commands:")
    for r in zero_non_swe:
        text.append(f"- {r['agent_id']} ({r['role']}): {r['recommended_command']}")
    text.append("")
    text.append("Suggested Grant listener dry run:")
    text.append("python3 tools/grant_listener_notes.py --branch all_non_swe --dry-run")
    text.append("")
    text.append("Suggested safe Grant listener rollout after review:")
    text.append("python3 tools/grant_listener_notes.py --branch company_001")
    text.append("")

    (REPORTS / "idle_employee_activation_report.txt").write_text("\n".join(text), encoding="utf-8")
    (REPORTS / "idle_employee_activation_report.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(REPORTS / "idle_employee_activation_report.txt")
    print("\n".join(text[:80]))


if __name__ == "__main__":
    main()
