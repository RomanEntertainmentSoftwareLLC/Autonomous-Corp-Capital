#!/usr/bin/env python3
"""Initialize missing RPG/memory files for ACC agents.

This is intentionally conservative: it creates missing ai_agents_memory/<agent>/
files, but it does not overwrite existing RPG_STATE.md, RPG_HISTORY.md, or
MEMORY.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("ACC_ROOT", "/opt/openclaw/.openclaw/workspace"))
OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", "/opt/openclaw/.openclaw/openclaw.json"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.rpg_state import append_human_rpg_history, default_rpg_state, save_rpg_state

MEMORY_ROOT = ROOT / "ai_agents_memory"
BACKUP_ROOT = ROOT / "ai_agents_backup"
REPORTS = ROOT / "reports"

ROLE_MAP = {
    "analyst": "Iris",
    "archivist": "June",
    "ceo": "Lucian",
    "cfo": "Bianca",
    "front_desk_administrator": "Pam",
    "manager": "Vera",
    "market_simulator": "Atlas",
    "operations_worker": "Bob",
    "researcher": "Rowan",
    "strategist": "Orion",
    "evolution_specialist": "Sloane",
    "master_cfo": "Vivienne",
    "master_treasurer": "Selene",
    "risk_officer": "Helena",
    "ai_agent_resources": "Ariadne",
    "token_cost_controller": "Ledger",
    "axiom_evaluator": "Axiom",
    "revenue_expansion_officer": "Grant Cardone",
    "yam_yam": "Yam Yam",
    "inspector_general": "Mara",
    "constitutional_arbiter": "Justine",
    "ombudsman": "Owen",
    "product_manager": "Nadia",
    "scrum_master": "Tessa",
    "senior_software_architect": "Marek",
    "senior_software_engineer": "Eli",
    "junior_software_engineer": "Noah",
    "tester": "Mina",
    "code_reviewer": "Gideon",
    "qa": "Sabine",
    "infrastructure": "Rhea",
}

@dataclass(frozen=True)
class AgentCandidate:
    agent_id: str
    source: str
    path: str
    display_name: str = ""
    role_hint: str = ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _slug_from_agent_folder(path: Path) -> str:
    name = path.name.strip()
    # Prefer explicit *_company_### ids when available.
    m = re.search(r"([a-z]+(?:_[a-z]+)?_company_\d{3})$", name)
    if m:
        return m.group(1)
    mapping = {
        "vivienne_master_cfo": "vivienne",
        "selene_master_treasurer": "selene",
        "helena_risk_officer": "helena",
        "ariadne_ai_agent_resources": "ariadne",
        "ledger_token_cost_controller": "ledger",
        "axiom_evaluator": "axiom",
        "grant_cardone_revenue_expansion_officer": "grant_cardone",
        "mara_inspector_general": "mara",
        "justine_constitutional_arbiter": "justine",
        "owen_ombudsman": "owen",
        "nadia_product_manager": "nadia",
        "tessa_scrum_master": "tessa",
        "marek_senior_software_architect": "marek",
        "eli_senior_software_engineer": "eli",
        "noah_junior_software_engineer": "noah",
        "mina_tester": "mina",
        "gideon_code_reviewer": "gideon",
        "sabine_qa": "sabine",
        "rhea_infrastructure": "rhea",
    }
    return mapping.get(name, name)


def _display_from_path(path: Path, agent_id: str) -> tuple[str, str]:
    parts = path.parts
    role_hint = ""
    for part in reversed(parts):
        if part in ROLE_MAP:
            role_hint = part
            break
    display = ROLE_MAP.get(role_hint, "")
    if not display:
        display = agent_id.replace("_", " ").title()
    return display, role_hint


def agents_from_backup() -> list[AgentCandidate]:
    out: list[AgentCandidate] = []
    if not BACKUP_ROOT.exists():
        return out
    for ag in sorted(BACKUP_ROOT.rglob("AGENTS.md")):
        folder = ag.parent
        agent_id = _slug_from_agent_folder(folder)
        # Main/Yam Yam backup lives under master_branch/yam_yam but active id is main.
        if folder.name == "yam_yam":
            agent_id = "main"
        display, role_hint = _display_from_path(folder, agent_id)
        out.append(AgentCandidate(agent_id, "ai_agents_backup", str(folder), display, role_hint))
    return out


def agents_from_openclaw_config() -> list[AgentCandidate]:
    cfg = _read_json(OPENCLAW_CONFIG) or _read_json(ROOT / "openclaw.json")
    out: list[AgentCandidate] = []
    if not isinstance(cfg, dict):
        return out
    candidates: list[tuple[str, Any]] = []
    for key in ("agents", "agentRegistry", "agent_registry"):
        value = cfg.get(key)
        if isinstance(value, dict):
            candidates.extend((str(k), v) for k, v in value.items())
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    aid = item.get("id") or item.get("name") or item.get("agent")
                    if aid:
                        candidates.append((str(aid), item))
    for agent_id, item in candidates:
        workspace = ""
        if isinstance(item, dict):
            workspace = str(item.get("workspace") or item.get("workspacePath") or item.get("path") or "")
        display, role_hint = _display_from_path(Path(workspace), agent_id)
        out.append(AgentCandidate(agent_id, "openclaw.json", workspace, display, role_hint))
    return out


def collect_agents() -> list[AgentCandidate]:
    by_id: dict[str, AgentCandidate] = {}
    for item in agents_from_backup() + agents_from_openclaw_config():
        if not item.agent_id:
            continue
        by_id.setdefault(item.agent_id, item)
    # Ensure main exists even if backup/config discovery missed it.
    by_id.setdefault("main", AgentCandidate("main", "root", str(ROOT), "Yam Yam", "yam_yam"))
    return sorted(by_id.values(), key=lambda x: x.agent_id)


def initialize_agent(agent: AgentCandidate, dry_run: bool = False) -> dict[str, Any]:
    agent_dir = MEMORY_ROOT / agent.agent_id
    state_path = agent_dir / "RPG_STATE.md"
    history_path = agent_dir / "RPG_HISTORY.md"
    memory_path = agent_dir / "MEMORY.md"
    actions: list[str] = []

    if not state_path.exists():
        actions.append("create RPG_STATE.md")
        if not dry_run:
            save_rpg_state(state_path, default_rpg_state())
    if not history_path.exists():
        actions.append("create RPG_HISTORY.md")
        if not dry_run:
            append_human_rpg_history(
                history_path,
                agent_id=agent.agent_id,
                event_type="RPG Initialization",
                xp_delta=0,
                reason="RPG history created so future work can explain XP gains and penalties in human-readable form.",
                context=f"display_name={agent.display_name or 'unknown'} role={agent.role_hint or 'unknown'} source={agent.source}",
            )
    if not memory_path.exists():
        actions.append("create MEMORY.md")
        if not dry_run:
            agent_dir.mkdir(parents=True, exist_ok=True)
            memory_path.write_text(
                "# MEMORY.md\n\n"
                "Durable operating memory for this agent. Store concise lessons, important facts, working tools, failed approaches, board directives, and role-specific improvements here.\n",
                encoding="utf-8",
            )
    return {
        "agent_id": agent.agent_id,
        "display_name": agent.display_name,
        "role_hint": agent.role_hint,
        "source": agent.source,
        "path": agent.path,
        "actions": actions,
        "changed": bool(actions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize missing RPG/MEMORY files for discovered ACC agents.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be created without writing files.")
    args = parser.parse_args()

    agents = collect_agents()
    results = [initialize_agent(a, dry_run=args.dry_run) for a in agents]
    changed = [r for r in results if r["changed"]]

    REPORTS.mkdir(parents=True, exist_ok=True)
    report = REPORTS / "rpg_initialize_missing_agents.txt"
    json_report = REPORTS / "rpg_initialize_missing_agents.json"
    lines = [
        "ACC RPG INITIALIZATION REPORT",
        "=============================",
        f"Root: {ROOT}",
        f"Discovered agents: {len(agents)}",
        f"Agents needing file creation: {len(changed)}",
        f"Dry run: {args.dry_run}",
        "",
    ]
    for r in changed:
        lines.append(f"- {r['agent_id']} ({r.get('display_name') or 'unknown'}): {', '.join(r['actions'])}")
    if not changed:
        lines.append("No missing RPG/MEMORY files detected.")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_report.write_text(json.dumps({"root": str(ROOT), "dry_run": args.dry_run, "results": results}, indent=2), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nWrote: {report}")
    print(f"Wrote: {json_report}")


if __name__ == "__main__":
    main()
