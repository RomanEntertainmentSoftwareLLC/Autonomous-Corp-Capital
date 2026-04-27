#!/usr/bin/env python3
"""Rank ACC agents for future activation.

This is a read-only planning tool. It does not call agents and does not award XP.
It exists to make the idle/zero-XP workforce visible without flooding terminal output.

Important: OpenClaw config is the source of truth for real agents. Backup and
workspace folders are intentionally not used for discovery by default because
old clone/copy mistakes can leave duplicate nested folders that look like fake
agents.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("ACC_ROOT", "/opt/openclaw/.openclaw/workspace"))
OPENCLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", "/opt/openclaw/.openclaw/openclaw.json"))
MEMORY_ROOT = ROOT / "ai_agents_memory"
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

MASTER_AGENTS = {"main", "selene", "helena", "vivienne", "ariadne", "ledger", "axiom", "grant_cardone"}
WATCHDOG_AGENTS = {"mara", "justine", "owen"}
SWE_AGENTS = {"nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea"}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _agent_id(entry: dict[str, Any]) -> str | None:
    for key in ("id", "agent_id", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _iter_config_agent_entries(config: Any) -> list[dict[str, Any]]:
    """Return real agent entries from supported OpenClaw config shapes."""
    if not isinstance(config, dict):
        return []
    raw = config.get("agents")
    if isinstance(raw, dict):
        agent_list = raw.get("list")
        if isinstance(agent_list, list):
            return [item for item in agent_list if isinstance(item, dict) and _agent_id(item)]

        rows: list[dict[str, Any]] = []
        for key, value in raw.items():
            if key in {"defaults", "list"}:
                continue
            if isinstance(value, dict):
                rows.append({"id": key, **value})
        return [item for item in rows if _agent_id(item)]

    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and _agent_id(item)]
    return []


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


def _branch_for_agent(agent_id: str, workspace: str = "") -> str:
    p = workspace.lower()
    if agent_id in MASTER_AGENTS or "master_branch" in p:
        return "master"
    if agent_id in WATCHDOG_AGENTS or "watchdog_branch" in p:
        return "watchdog"
    if agent_id in SWE_AGENTS or "swe_branch" in p:
        return "swe"
    return "company"


def discover_agents() -> dict[str, dict[str, Any]]:
    """Discover only configured OpenClaw agents.

    This avoids false activation candidates such as bianca_cfo_company_001 that
    can come from backup folder names rather than actual registered agent ids.
    """
    config = _read_json(OPENCLAW_CONFIG) or _read_json(ROOT / "openclaw.json") or {}
    agents: dict[str, dict[str, Any]] = {}
    for entry in _iter_config_agent_entries(config):
        aid = _agent_id(entry)
        if not aid:
            continue
        workspace = str(entry.get("workspace") or entry.get("workspacePath") or entry.get("path") or "")
        agents[aid] = {
            "agent_id": aid,
            "workspace": workspace,
            "source": "openclaw.json",
        }
    agents.setdefault("main", {"agent_id": "main", "workspace": str(ROOT), "source": "root"})
    return agents


def score_agent(info: dict[str, Any]) -> dict[str, Any]:
    aid = info["agent_id"]
    branch = _branch_for_agent(aid, info.get("workspace", ""))
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
        if "_company_" in aid:
            role = aid.split("_company_", 1)[0]
            base += PRIORITY.get(role, 0) / 5.0

    zero_bonus = 30 if xp <= 0 and sessions <= 0 else 0
    no_history_penalty = 5 if not history_path.exists() else 0
    missing_memory_bonus = 8 if not memory_path.exists() else 0
    score = round(base + zero_bonus + missing_memory_bonus + no_history_penalty - min(xp / 20.0, 20.0), 2)

    if branch == "swe":
        rationale = "SWE branch is intentionally later; keep visible but do not prioritize before runtime/governance proof."
    elif xp <= 0 and sessions <= 0:
        rationale = "Idle/zero-XP configured agent; needs a real event-driven job and memory file coverage."
    elif not memory_path.exists():
        rationale = "Already active, but missing ai_agents_memory/MEMORY.md; initialize memory before deeper wiring."
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
        "source": info.get("source", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ACC agent activation queue reports from registered OpenClaw agents only.")
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
        f"Config: {OPENCLAW_CONFIG}",
        f"Agents considered: {len(rows)}",
        f"SWE included: {args.include_swe}",
        "Discovery source: openclaw.json registered agents only",
        "",
        "Top activation candidates:",
    ]
    for r in rows[: args.limit]:
        lines.append(
            f"- {r['agent_id']} | branch={r['branch']} | priority={r['priority_score']} | "
            f"xp={r['xp']} sessions={r['sessions']} | state={r['has_rpg_state']} history={r['has_rpg_history']} memory={r['has_memory']} | {r['rationale']}"
        )
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    js.write_text(json.dumps({"root": str(ROOT), "config": str(OPENCLAW_CONFIG), "rows": rows}, indent=2), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote: {txt}")
    print(f"Wrote: {js}")


if __name__ == "__main__":
    main()
