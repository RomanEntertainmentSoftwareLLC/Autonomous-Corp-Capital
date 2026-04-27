#!/usr/bin/env python3
"""Initialize missing RPG/memory files for ACC agents.

This is intentionally conservative: it creates missing ai_agents_memory/<agent>/
files, but it does not overwrite existing RPG_STATE.md, RPG_HISTORY.md, or
MEMORY.md.

Important: OpenClaw config is the source of truth for real agents. Backup and
workspace folders are not used for discovery by default, because clone/copy
mistakes can leave duplicate nested folders that look like fake agents.
"""
from __future__ import annotations

import argparse
import json
import os
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
REPORTS = ROOT / "reports"
SWE_AGENTS = {"nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea"}


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


def _identity(entry: dict[str, Any]) -> tuple[str, str]:
    ident = entry.get("identity")
    if isinstance(ident, dict):
        display = str(ident.get("name") or "").strip()
        role = str(ident.get("theme") or "").strip()
        return display, role
    return "", ""


def agents_from_openclaw_config() -> list[AgentCandidate]:
    cfg = _read_json(OPENCLAW_CONFIG) or _read_json(ROOT / "openclaw.json")
    out: list[AgentCandidate] = []
    for entry in _iter_config_agent_entries(cfg):
        agent_id = _agent_id(entry)
        if not agent_id:
            continue
        workspace = str(entry.get("workspace") or entry.get("workspacePath") or entry.get("path") or "")
        display, role_hint = _identity(entry)
        if not display:
            display = agent_id
        out.append(AgentCandidate(agent_id, "openclaw.json", workspace, display, role_hint))
    out.append(AgentCandidate("main", "root", str(ROOT), "Yam Yam", "Master CEO"))

    # Deduplicate while preserving the config row over the fallback main row.
    by_id: dict[str, AgentCandidate] = {}
    for item in out:
        if not item.agent_id:
            continue
        by_id.setdefault(item.agent_id, item)
    return sorted(by_id.values(), key=lambda x: x.agent_id)


def is_swe(agent_id: str) -> bool:
    return agent_id in SWE_AGENTS


def initialize_agent(agent: AgentCandidate, dry_run: bool = False) -> dict[str, Any]:
    agent_dir = MEMORY_ROOT / agent.agent_id
    state_path = agent_dir / "RPG_STATE.md"
    history_path = agent_dir / "RPG_HISTORY.md"
    memory_path = agent_dir / "MEMORY.md"
    actions: list[str] = []

    if not state_path.exists():
        actions.append("create RPG_STATE.md")
        if not dry_run:
            agent_dir.mkdir(parents=True, exist_ok=True)
            save_rpg_state(state_path, default_rpg_state())
    if not history_path.exists():
        actions.append("create RPG_HISTORY.md")
        if not dry_run:
            agent_dir.mkdir(parents=True, exist_ok=True)
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
                "Durable operating memory for this agent. Store concise lessons, important facts, working tools, failed approaches, "
                "board directives, role-specific improvements, and anything that helps the agent perform better over time.\n",
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
    parser = argparse.ArgumentParser(description="Initialize missing RPG/MEMORY files for registered ACC agents only.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be created without writing files.")
    parser.add_argument("--exclude-swe", action="store_true", help="Skip SWE agents for now. Useful if following non-SWE-only activation phases.")
    args = parser.parse_args()

    agents = agents_from_openclaw_config()
    if args.exclude_swe:
        agents = [a for a in agents if not is_swe(a.agent_id)]

    results = [initialize_agent(a, dry_run=args.dry_run) for a in agents]
    changed = [r for r in results if r["changed"]]

    REPORTS.mkdir(parents=True, exist_ok=True)
    report = REPORTS / "rpg_initialize_missing_agents.txt"
    json_report = REPORTS / "rpg_initialize_missing_agents.json"
    lines = [
        "ACC RPG INITIALIZATION REPORT",
        "=============================",
        f"Root: {ROOT}",
        f"Config: {OPENCLAW_CONFIG}",
        f"Discovery source: openclaw.json registered agents only",
        f"Discovered agents: {len(agents)}",
        f"Agents needing file creation: {len(changed)}",
        f"Dry run: {args.dry_run}",
        f"Exclude SWE: {args.exclude_swe}",
        "",
    ]
    for r in changed:
        lines.append(f"- {r['agent_id']} ({r.get('display_name') or 'unknown'}): {', '.join(r['actions'])}")
    if not changed:
        lines.append("No missing RPG/MEMORY files detected.")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_report.write_text(json.dumps({"root": str(ROOT), "dry_run": args.dry_run, "exclude_swe": args.exclude_swe, "results": results}, indent=2), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nWrote: {report}")
    print(f"Wrote: {json_report}")


if __name__ == "__main__":
    main()
