#!/usr/bin/env python3
"""Rank ACC agents for future activation.

This is a read-only planning tool. It does not call agents and does not award XP.
It exists to make the idle/zero-XP workforce visible without flooding terminal output.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("ACC_ROOT", "/opt/openclaw/.openclaw/workspace"))
MEMORY_ROOT = ROOT / "ai_agents_memory"
BACKUP_ROOT = ROOT / "ai_agents_backup"
REPORTS = ROOT / "reports"

PRIORITY = {
    "axiom": 100,
    "vivienne": 95,
    "helena": 90,
    "grant_cardone": 88,
    "ledger": 86,
    "ariadne": 84,
    "selene": 80,
    "june": 65,
    "pam": 62,
    "atlas": 60,
    "sloane": 58,
    "bob": 50,
    "mara": 40,
    "justine": 38,
    "owen": 36,
    "nadia": 10,
    "tessa": 10,
    "marek": 10,
    "eli": 10,
    "noah": 10,
    "mina": 10,
    "gideon": 10,
    "sabine": 10,
    "rhea": 10,
}

ROLE_PRIORITY = {
    "master": 80,
    "watchdog": 35,
    "swe": 10,
    "company": 45,
}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _value_from_rpg(text: str, field: str, default: float = 0.0) -> float:
    # Supports the Markdown table written by tools.rpg_state.
    pattern = rf"\|\s*{re.escape(field)}\s*\|\s*([^|]+)\|"
    m = re.search(pattern, text, flags=re.I)
    if not m:
        return default
    try:
        return float(str(m.group(1)).strip())
    except Exception:
        return default


def _agent_id_from_backup_folder(folder: Path) -> str:
    name = folder.name
    if name == "yam_yam":
        return "main"
    if name == "axiom_evaluator":
        return "axiom"
    if name == "grant_cardone_revenue_expansion_officer":
        return "grant_cardone"
    mapping = {
        "vivienne_master_cfo": "vivienne",
        "selene_master_treasurer": "selene",
        "helena_risk_officer": "helena",
        "ariadne_ai_agent_resources": "ariadne",
        "ledger_token_cost_controller": "ledger",
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
    if name in mapping:
        return mapping[name]
    m = re.search(r"([a-z]+(?:_[a-z]+)?_company_\d{3})$", name)
    return m.group(1) if m else name


def _branch_for_path(path: str, agent_id: str) -> str:
    p = path.lower()
    if agent_id in {"main", "selene", "helena", "vivienne", "ariadne", "ledger", "axiom", "grant_cardone"} or "master_branch" in p:
        return "master"
    if agent_id in {"mara", "justine", "owen"} or "watchdog_branch" in p:
        return "watchdog"
    if agent_id in {"nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea"} or "swe_branch" in p:
        return "swe"
    return "company"


def discover_agents() -> dict[str, dict[str, Any]]:
    agents: dict[str, dict[str, Any]] = {}
    if BACKUP_ROOT.exists():
        for ag in sorted(BACKUP_ROOT.rglob("AGENTS.md")):
            folder = ag.parent
            aid = _agent_id_from_backup_folder(folder)
            agents.setdefault(aid, {"agent_id": aid, "workspace": str(folder), "source": "ai_agents_backup"})
    if MEMORY_ROOT.exists():
        for folder in sorted(MEMORY_ROOT.iterdir()):
            if folder.is_dir():
                aid = folder.name
                agents.setdefault(aid, {"agent_id": aid, "workspace": "", "source": "ai_agents_memory"})
    agents.setdefault("main", {"agent_id": "main", "workspace": str(ROOT), "source": "root"})
    return agents


def score_agent(info: dict[str, Any]) -> dict[str, Any]:
    aid = info["agent_id"]
    branch = _branch_for_path(info.get("workspace", ""), aid)
    state_path = MEMORY_ROOT / aid / "RPG_STATE.md"
    history_path = MEMORY_ROOT / aid / "RPG_HISTORY.md"
    memory_path = MEMORY_ROOT / aid / "MEMORY.md"
    text = _read_text(state_path)
    xp = _value_from_rpg(text, "xp", 0.0)
    sessions = _value_from_rpg(text, "sessions", 0.0)
    usefulness = _value_from_rpg(text, "usefulness", 0.0)
    evidence = _value_from_rpg(text, "evidence_quality", 0.0)
    base = PRIORITY.get(aid, 0)
    if base <= 0:
        base = ROLE_PRIORITY.get(branch, 20)
        if "company_" in aid:
            role = aid.split("_company_")[0]
            base += PRIORITY.get(role, 0) / 5.0
    zero_bonus = 30 if xp <= 0 and sessions <= 0 else 0
    no_history_penalty = 5 if not history_path.exists() else 0
    score = round(base + zero_bonus + no_history_penalty - min(xp / 20.0, 20.0), 2)
    if branch == "swe":
        rationale = "SWE branch is intentionally later; keep visible but do not prioritize before runtime/governance proof."
    elif xp <= 0 and sessions <= 0:
        rationale = "Idle/zero-XP agent; needs a real event-driven job before it stops filing its nails."
    else:
        rationale = "Already active; monitor or deepen role wiring rather than first activation."
    return {
        "agent_id": aid,
        "branch": branch,
        "priority_score": score,
        "xp": xp,
        "sessions": sessions,
        "usefulness": usefulness,
        "evidence_quality": evidence,
        "has_rpg_state": state_path.exists(),
        "has_rpg_history": history_path.exists(),
        "has_memory": memory_path.exists(),
        "rationale": rationale,
        "workspace": info.get("workspace", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ACC agent activation queue reports.")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--include-swe", action="store_true")
    args = parser.parse_args()

    rows = [score_agent(v) for v in discover_agents().values()]
    if not args.include_swe:
        rows = [r for r in rows if r["branch"] != "swe"]
    rows.sort(key=lambda r: (-r["priority_score"], r["branch"], r["agent_id"]))

    REPORTS.mkdir(parents=True, exist_ok=True)
    txt = REPORTS / "agent_activation_queue.txt"
    js = REPORTS / "agent_activation_queue.json"
    lines = [
        "ACC AGENT ACTIVATION QUEUE",
        "==========================",
        f"Root: {ROOT}",
        f"Agents considered: {len(rows)}",
        f"SWE included: {args.include_swe}",
        "",
        "Top activation candidates:",
    ]
    for r in rows[: args.limit]:
        lines.append(
            f"- {r['agent_id']} | branch={r['branch']} | priority={r['priority_score']} | "
            f"xp={r['xp']} sessions={r['sessions']} | state={r['has_rpg_state']} history={r['has_rpg_history']} memory={r['has_memory']} | {r['rationale']}"
        )
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    js.write_text(json.dumps({"root": str(ROOT), "rows": rows}, indent=2), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote: {txt}")
    print(f"Wrote: {js}")


if __name__ == "__main__":
    main()
