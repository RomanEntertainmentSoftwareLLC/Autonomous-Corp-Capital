#!/usr/bin/env python3
"""Audit and apply phased Hermes model routing for OpenClaw/ACC agents.

This tool intentionally changes only explicit per-agent `model` fields in
openclaw.json. It does not change the default model, because a default flip can
quietly route unreviewed or future agents to Hermes.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CONFIG_PATH = Path(os.environ.get("OPENCLAW_CONFIG", "/opt/openclaw/.openclaw/openclaw.json"))
HERMES_MODEL = os.environ.get("HERMES_MODEL", "hermes/hermes-agent")
ROWAN_HERMES_MODEL = os.environ.get("ROWAN_HERMES_MODEL", "hermes_rowan/hermes-agent")
COMPANIES = ("001", "002", "003", "004")

MASTER_PHASE_0 = ("main",)
MASTER_PHASE_1 = ("axiom", "vivienne", "helena", "ledger")
MASTER_PHASE_2 = ("grant_cardone", "ariadne", "selene")
WATCHDOGS = ("mara", "justine", "owen")
SWE = ("nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea")

COMPANY_CORE_ROLES = ("lucian", "bianca", "iris", "vera", "orion", "rowan")
COMPANY_SUPPORT_ROLES = ("pam", "bob", "sloane", "atlas", "june")


def _company_ids(roles: Iterable[str]) -> tuple[str, ...]:
    return tuple(f"{role}_company_{company}" for company in COMPANIES for role in roles)


PHASES: dict[str, tuple[str, ...]] = {
    "phase0": MASTER_PHASE_0,
    "phase1": MASTER_PHASE_1,
    "phase2": MASTER_PHASE_2,
    "company_core": _company_ids(COMPANY_CORE_ROLES),
    "company_support": _company_ids(COMPANY_SUPPORT_ROLES),
    "watchdogs": WATCHDOGS,
    "swe": SWE,
}
PHASES["all_non_swe"] = tuple(dict.fromkeys(
    PHASES["phase0"]
    + PHASES["phase1"]
    + PHASES["phase2"]
    + PHASES["company_core"]
    + PHASES["company_support"]
    + PHASES["watchdogs"]
))
PHASES["all"] = tuple(dict.fromkeys(PHASES["all_non_swe"] + PHASES["swe"]))

PHASE_ALIASES = {
    "phase_0": "phase0",
    "phase-0": "phase0",
    "0": "phase0",
    "phase_1": "phase1",
    "phase-1": "phase1",
    "1": "phase1",
    "phase_2": "phase2",
    "phase-2": "phase2",
    "2": "phase2",
    "company-core": "company_core",
    "company-support": "company_support",
    "all-non-swe": "all_non_swe",
}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_phase(name: str) -> str:
    normalized = PHASE_ALIASES.get(name.strip(), name.strip())
    if normalized not in PHASES:
        raise ValueError(f"Unknown phase '{name}'. Supported phases: {', '.join(PHASES)}")
    return normalized


def _iter_agent_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return mutable agent dictionaries from supported OpenClaw config shapes."""
    agents = config.get("agents")
    if isinstance(agents, dict):
        agent_list = agents.get("list")
        if isinstance(agent_list, list):
            return [item for item in agent_list if isinstance(item, dict)]

        # Defensive support for older map-style registries: {"main": { ... }}.
        rows: list[dict[str, Any]] = []
        for key, value in agents.items():
            if key in {"defaults", "list"}:
                continue
            if isinstance(value, dict):
                value.setdefault("id", key)
                rows.append(value)
        return rows

    if isinstance(agents, list):
        return [item for item in agents if isinstance(item, dict)]

    return []


def _agent_id(entry: dict[str, Any]) -> str | None:
    for key in ("id", "agent_id", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _agent_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for entry in _iter_agent_entries(config):
        aid = _agent_id(entry)
        if aid:
            out[aid] = entry
    return out


def _target_model(agent_id: str) -> str:
    if agent_id == "rowan" or agent_id.startswith("rowan_company_"):
        return ROWAN_HERMES_MODEL
    return HERMES_MODEL


def _current_model(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "<missing>"
    value = entry.get("model")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        primary = value.get("primary")
        return str(primary) if primary is not None else json.dumps(value, sort_keys=True)
    if value is None:
        return "<unset>"
    return str(value)


def _status_for(entry: dict[str, Any] | None, agent_id: str) -> str:
    if entry is None:
        return "MISSING"
    current = _current_model(entry)
    target = _target_model(agent_id)
    if current == target:
        return "OK"
    return "CHANGE"


def _rows_for(config: dict[str, Any], agent_ids: Iterable[str]) -> list[dict[str, str]]:
    by_id = _agent_map(config)
    rows = []
    for aid in agent_ids:
        entry = by_id.get(aid)
        rows.append({
            "agent": aid,
            "current_model": _current_model(entry),
            "target_model": _target_model(aid),
            "status": _status_for(entry, aid),
        })
    return rows


def _print_rows(title: str, rows: list[dict[str, str]]) -> None:
    print(title)
    print("=" * len(title))
    widths = {
        "agent": max([len("agent")] + [len(r["agent"]) for r in rows]),
        "status": max([len("status")] + [len(r["status"]) for r in rows]),
        "current_model": max([len("current_model")] + [len(r["current_model"]) for r in rows]),
        "target_model": max([len("target_model")] + [len(r["target_model"]) for r in rows]),
    }
    header = (
        f"{'agent':<{widths['agent']}}  "
        f"{'status':<{widths['status']}}  "
        f"{'current_model':<{widths['current_model']}}  "
        f"{'target_model':<{widths['target_model']}}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['agent']:<{widths['agent']}}  "
            f"{row['status']:<{widths['status']}}  "
            f"{row['current_model']:<{widths['current_model']}}  "
            f"{row['target_model']:<{widths['target_model']}}"
        )


def _backup_config(config_path: Path) -> Path:
    backup_path = config_path.with_name(f"{config_path.name}.bak.hermes_rollout_{_utc_stamp()}")
    shutil.copy2(config_path, backup_path)
    return backup_path


def audit(config_path: Path) -> int:
    config = _load_json(config_path)
    print(f"Config: {config_path}")
    print(f"Hermes model: {HERMES_MODEL}")
    print(f"Rowan Hermes model: {ROWAN_HERMES_MODEL}")
    print()
    for phase in ("phase0", "phase1", "phase2", "company_core", "company_support", "watchdogs", "swe"):
        rows = _rows_for(config, PHASES[phase])
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        print(f"{phase}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print()
    rows = _rows_for(config, PHASES["all"])
    _print_rows("Hermes rollout audit", rows)
    missing = [r["agent"] for r in rows if r["status"] == "MISSING"]
    if missing:
        print("\nMissing configured agents:")
        for aid in missing:
            print(f"- {aid}")
    return 0


def apply_phase(config_path: Path, phase: str, apply: bool) -> int:
    phase = _normalize_phase(phase)
    config = _load_json(config_path)
    by_id = _agent_map(config)
    rows = _rows_for(config, PHASES[phase])
    _print_rows(f"Hermes rollout {phase} {'apply' if apply else 'dry run'}", rows)

    missing = [r for r in rows if r["status"] == "MISSING"]
    changes = [r for r in rows if r["status"] == "CHANGE"]

    if missing:
        print("\nWARNING: These phase agents were not found in openclaw.json and will be skipped:")
        for row in missing:
            print(f"- {row['agent']}")

    if not apply:
        print("\nDry run only. Re-run with --apply to write changes.")
        return 0

    if not changes:
        print("\nNo model changes required. Config was not rewritten.")
        return 0

    backup = _backup_config(config_path)
    for row in changes:
        entry = by_id.get(row["agent"])
        if entry is not None:
            entry["model"] = row["target_model"]
    _write_json(config_path, config)
    print(f"\nApplied {len(changes)} model change(s).")
    print(f"Backup: {backup}")
    print(f"Updated: {config_path}")
    return 0


def list_phases() -> int:
    print("Supported Hermes rollout phases:")
    for name, agent_ids in PHASES.items():
        print(f"- {name}: {len(agent_ids)} agent(s)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit or apply phased Hermes routing in openclaw.json.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to openclaw.json")
    parser.add_argument("--audit", action="store_true", help="Audit all known rollout targets without writing changes")
    parser.add_argument("--phase", choices=sorted(PHASES.keys()), help="Rollout phase to inspect/apply")
    parser.add_argument("--apply", action="store_true", help="Actually write model changes for --phase")
    parser.add_argument("--list-phases", action="store_true", help="Print supported phases and exit")
    args = parser.parse_args()

    if args.list_phases:
        raise SystemExit(list_phases())
    if args.audit:
        raise SystemExit(audit(args.config))
    if args.phase:
        raise SystemExit(apply_phase(args.config, args.phase, args.apply))

    parser.error("Use --audit, --list-phases, or --phase PHASE [--apply].")


if __name__ == "__main__":
    main()
