#!/usr/bin/env python3
"""Create a read-only Hermes rollout plan for ACC agents.

This does not modify openclaw.json. It audits available config/provider clues and
writes a phased plan so Hermes can be rolled out without a mass breakage event.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("ACC_ROOT", "/opt/openclaw/.openclaw/workspace"))
CONFIG_PATH = Path(os.environ.get("OPENCLAW_CONFIG", "/opt/openclaw/.openclaw/openclaw.json"))
BACKUP_ROOT = ROOT / "ai_agents_backup"
MEMORY_ROOT = ROOT / "ai_agents_memory"
REPORTS = ROOT / "reports"

PHASES = [
    ("phase_0_verify", ["main"], "Verify Yam Yam/main has the expected second-brain behavior before expanding."),
    ("phase_1_executive_truth", ["axiom", "vivienne", "helena", "ledger"], "Evidence, financial truth, risk, and token-cost oversight."),
    ("phase_2_revenue_workforce", ["grant_cardone", "ariadne", "selene"], "Revenue pressure, workforce allocation, and treasury guidance."),
    ("phase_3_company_core", ["lucian", "bianca", "iris", "vera", "orion", "rowan"], "Company decision core, applied by company suffix. Rowan uses the Rowan Hermes provider."),
    ("phase_4_support_roles", ["pam", "bob", "sloane", "atlas", "june"], "Support roles once event routing is clear."),
    ("phase_5_watchdogs", ["mara", "justine", "owen"], "Watchdogs after governance triggers are stable."),
    ("phase_6_swe_later", ["nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea"], "SWE branch later, ticket-driven only."),
]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _agent_id_from_folder(folder: Path) -> str:
    name = folder.name
    mapping = {
        "yam_yam": "main",
        "axiom_evaluator": "axiom",
        "grant_cardone_revenue_expansion_officer": "grant_cardone",
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


def _agent_id(entry: dict[str, Any]) -> str | None:
    for key in ("id", "agent_id", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _model_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        primary = value.get("primary")
        if primary is not None:
            return str(primary)
        return json.dumps(value, sort_keys=True)
    if value is None:
        return "unknown"
    return str(value)


def _iter_config_agents(cfg: Any) -> list[dict[str, Any]]:
    if not isinstance(cfg, dict):
        return []
    raw = cfg.get("agents")
    if isinstance(raw, dict):
        agent_list = raw.get("list")
        if isinstance(agent_list, list):
            return [item for item in agent_list if isinstance(item, dict) and _agent_id(item)]
        rows = []
        for key, value in raw.items():
            if key in {"defaults", "list"}:
                continue
            if isinstance(value, dict):
                rows.append({"id": key, **value})
        return [item for item in rows if _agent_id(item)]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and _agent_id(item)]
    return []


def discover_agents(model_by_agent: dict[str, str]) -> list[str]:
    # The real OpenClaw config is the source of truth. Filesystem discovery is
    # fallback only, otherwise backup/template folders create false duplicate agents.
    if model_by_agent:
        return sorted(model_by_agent.keys())

    ids: set[str] = set()
    if BACKUP_ROOT.exists():
        for ag in BACKUP_ROOT.rglob("AGENTS.md"):
            ids.add(_agent_id_from_folder(ag.parent))
    if MEMORY_ROOT.exists():
        for p in MEMORY_ROOT.iterdir():
            if p.is_dir():
                ids.add(p.name)
    ids.add("main")
    return sorted(ids)


def _providers_and_agent_models(cfg: Any) -> tuple[list[str], dict[str, str]]:
    providers: set[str] = set()
    models: dict[str, str] = {}
    if not isinstance(cfg, dict):
        return [], models

    models_section = cfg.get("models")
    if isinstance(models_section, dict):
        provider_map = models_section.get("providers")
        if isinstance(provider_map, dict):
            providers.update(str(k) for k in provider_map.keys())

    for key in ("providers", "modelProviders", "model_providers"):
        val = cfg.get(key)
        if isinstance(val, dict):
            providers.update(str(k) for k in val.keys())
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and (item.get("name") or item.get("id")):
                    providers.add(str(item.get("name") or item.get("id")))

    auth = cfg.get("auth")
    if isinstance(auth, dict):
        profiles = auth.get("profiles")
        if isinstance(profiles, dict):
            for profile in profiles.values():
                if isinstance(profile, dict) and profile.get("provider"):
                    providers.add(str(profile["provider"]))

    for item in _iter_config_agents(cfg):
        aid = _agent_id(item)
        if aid:
            models[aid] = _model_text(item.get("model"))
    return sorted(providers), models


def _matches_phase(agent_id: str, keys: list[str]) -> bool:
    if agent_id in keys:
        return True
    for key in keys:
        if agent_id.startswith(key + "_company_"):
            return True
    return False


def build_plan(root: Path, config_path: Path) -> tuple[list[str], dict[str, Any]]:
    cfg = _read_json(config_path) or _read_json(root / "openclaw.json")
    providers, model_by_agent = _providers_and_agent_models(cfg)
    agents = discover_agents(model_by_agent)
    hermes_provider_names = [p for p in providers if "hermes" in p.lower()]
    current_hermes_agents = [aid for aid, model in model_by_agent.items() if "hermes" in model.lower()]

    phase_rows = []
    assigned: set[str] = set()
    for phase, keys, reason in PHASES:
        phase_agents = [a for a in agents if a not in assigned and _matches_phase(a, keys)]
        assigned.update(phase_agents)
        phase_rows.append({"phase": phase, "reason": reason, "agents": phase_agents})
    leftovers = [a for a in agents if a not in assigned]
    if leftovers:
        phase_rows.append({"phase": "phase_unknown_review", "reason": "Discovered but not classified; inspect before rollout.", "agents": leftovers})

    lines = [
        "ACC HERMES ROLLOUT PLAN",
        "=======================",
        f"Root: {root}",
        f"Config inspected: {config_path if config_path.exists() else root / 'openclaw.json'}",
        f"Discovered configured agents: {len(agents)}",
        f"Providers: {', '.join(providers) if providers else 'none detected'}",
        f"Hermes-like providers: {', '.join(hermes_provider_names) if hermes_provider_names else 'none detected'}",
        f"Agents currently using Hermes-like model/provider: {len(current_hermes_agents)}",
        "",
        "Rules:",
        "- Do not mass-flip all agents at once.",
        "- Verify one phase with smoke tests before the next phase.",
        "- Keep MEMORY.md as file memory; Hermes is the second brain, not the only brain.",
        "- Watch token burn before expanding Hermes beyond executive governance.",
        "",
    ]
    for row in phase_rows:
        lines.append(f"## {row['phase']}")
        lines.append(row["reason"])
        if row["agents"]:
            for a in row["agents"]:
                model = model_by_agent.get(a, "unknown")
                mem = MEMORY_ROOT / a / "MEMORY.md"
                hist = MEMORY_ROOT / a / "RPG_HISTORY.md"
                lines.append(f"- {a} | current_model={model or 'unknown'} | memory={mem.exists()} | history={hist.exists()}")
        else:
            lines.append("- none discovered")
        lines.append("")

    json_report = {
        "root": str(root),
        "config_path": str(config_path),
        "providers": providers,
        "hermes_provider_names": hermes_provider_names,
        "current_hermes_agents": sorted(current_hermes_agents),
        "agent_count": len(agents),
        "model_by_agent": model_by_agent,
        "phases": phase_rows,
    }
    return lines, json_report


def main() -> None:
    global ROOT, CONFIG_PATH, BACKUP_ROOT, MEMORY_ROOT, REPORTS

    parser = argparse.ArgumentParser(description="Create a read-only phased Hermes rollout plan from the real OpenClaw config.")
    parser.add_argument("--root", type=Path, default=ROOT, help="ACC workspace root")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="Path to openclaw.json")
    args = parser.parse_args()

    ROOT = args.root
    CONFIG_PATH = args.config
    BACKUP_ROOT = ROOT / "ai_agents_backup"
    MEMORY_ROOT = ROOT / "ai_agents_memory"
    REPORTS = ROOT / "reports"

    lines, json_report = build_plan(ROOT, CONFIG_PATH)
    REPORTS.mkdir(parents=True, exist_ok=True)
    txt = REPORTS / "hermes_rollout_plan.txt"
    js = REPORTS / "hermes_rollout_plan.json"
    txt.write_text("\n".join(lines), encoding="utf-8")
    js.write_text(json.dumps(json_report, indent=2, sort_keys=True), encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote: {txt}")
    print(f"Wrote: {js}")


if __name__ == "__main__":
    main()
