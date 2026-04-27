#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("ACC_ROOT", "/opt/openclaw/.openclaw/workspace"))
OPENCLAW_JSON = Path(os.environ.get("OPENCLAW_CONFIG", str(ROOT.parent / "openclaw.json")))
LIVE_AGENTS = ROOT.parent / "workspaces" / "ai_agents"
MEMORY_ROOT = ROOT / "ai_agents_memory"
REPORTS = ROOT / "reports"


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _walk_dict(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dict(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_dict(v)


def _agent_id(entry: dict[str, Any]) -> str | None:
    for key in ("id", "agent_id", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_agents(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract real agent rows from both modern and older OpenClaw config shapes."""
    raw = config.get("agents")
    if isinstance(raw, dict):
        agent_list = raw.get("list")
        if isinstance(agent_list, list):
            return [item for item in agent_list if isinstance(item, dict) and _agent_id(item)]

        agents: list[dict[str, Any]] = []
        for aid, meta in raw.items():
            if aid in {"defaults", "list"}:
                continue
            if isinstance(meta, dict):
                agents.append({"id": aid, **meta})
        return [item for item in agents if _agent_id(item)]

    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and _agent_id(item)]
    return []


def _provider_names(config: dict[str, Any]) -> list[str]:
    names: set[str] = set()

    models = config.get("models")
    if isinstance(models, dict):
        providers = models.get("providers")
        if isinstance(providers, dict):
            names.update(str(k) for k in providers.keys())

    providers = config.get("providers")
    if isinstance(providers, dict):
        names.update(str(k) for k in providers.keys())

    auth = config.get("auth")
    if isinstance(auth, dict):
        profiles = auth.get("profiles")
        if isinstance(profiles, dict):
            for profile in profiles.values():
                if isinstance(profile, dict) and profile.get("provider"):
                    names.add(str(profile["provider"]))

    for d in _walk_dict(config):
        for key in ("provider", "provider_name", "modelProvider"):
            if key in d and d[key] is not None:
                names.add(str(d[key]))
    return sorted(names)


def _model_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        primary = value.get("primary")
        if primary is not None:
            return str(primary)
        return json.dumps(value, sort_keys=True)
    if value is None:
        return "<unset>"
    return str(value)


def _agent_file_counts() -> dict[str, int]:
    roots = [LIVE_AGENTS, ROOT / "ai_agents_backup"]
    counts: Counter[str] = Counter()
    for root in roots:
        if not root.exists():
            continue
        label = root.name
        for name in ["AGENTS.md", "IDENTITY.md", "SOUL.md", "MEMORY.md", "USER.md", "TOOLS.md", "BOOTSTRAP.md", "HEARTBEAT.md"]:
            counts[f"{label}:{name}"] += len(list(root.rglob(name)))
    counts["ai_agents_memory:RPG_STATE.md"] = len(list(MEMORY_ROOT.rglob("RPG_STATE.md"))) if MEMORY_ROOT.exists() else 0
    counts["ai_agents_memory:RPG_HISTORY.md"] = len(list(MEMORY_ROOT.rglob("RPG_HISTORY.md"))) if MEMORY_ROOT.exists() else 0
    counts["ai_agents_memory:MEMORY.md"] = len(list(MEMORY_ROOT.rglob("MEMORY.md"))) if MEMORY_ROOT.exists() else 0
    return dict(counts)


def build_report() -> dict[str, Any]:
    config = _read_json(OPENCLAW_JSON, {})
    agents = _extract_agents(config) if isinstance(config, dict) else []
    provider_names = _provider_names(config) if isinstance(config, dict) else []
    hermes_provider_names = [p for p in provider_names if "hermes" in p.lower()]

    agent_models: list[dict[str, str]] = []
    models: Counter[str] = Counter()
    hermes_assigned: list[str] = []
    openai_assigned: list[str] = []
    missing_model: list[str] = []

    for agent in agents:
        aid = _agent_id(agent) or "<unknown>"
        model = _model_text(agent.get("model"))
        agent_models.append({"agent_id": aid, "model": model})
        models[model] += 1
        lowered = model.lower()
        if "hermes" in lowered:
            hermes_assigned.append(aid)
        if "openai" in lowered:
            openai_assigned.append(aid)
        if model in {"<unset>", "UNKNOWN"}:
            missing_model.append(aid)

    verdict = "no_openclaw_json"
    if config:
        if hermes_assigned:
            verdict = "some_agents_directly_assigned_to_hermes"
        elif hermes_provider_names:
            verdict = "hermes_provider_present_but_no_agents_assigned"
        else:
            verdict = "no_hermes_provider_detected"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT),
        "openclaw_json": str(OPENCLAW_JSON),
        "openclaw_json_exists": OPENCLAW_JSON.exists(),
        "agent_count_in_config": len(agents),
        "provider_names": provider_names,
        "hermes_provider_names": hermes_provider_names,
        "model_counts": dict(models),
        "agent_models": sorted(agent_models, key=lambda row: row["agent_id"]),
        "hermes_assigned_agents": sorted(hermes_assigned),
        "openai_assigned_agents": sorted(openai_assigned),
        "openai_assigned_count": len(openai_assigned),
        "missing_model_agents": sorted(missing_model),
        "file_counts": _agent_file_counts(),
        "verdict": verdict,
        "note": "This is an inventory/audit only. It does not modify Hermes or agent model wiring.",
    }


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS / "hermes_inventory_audit.json"
    txt_path = REPORTS / "hermes_inventory_audit.txt"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "HERMES INVENTORY AUDIT",
        "======================",
        f"Verdict: {report.get('verdict')}",
        f"Root: {report.get('root')}",
        f"OpenClaw config exists: {report.get('openclaw_json_exists')} ({report.get('openclaw_json')})",
        f"Agents in config: {report.get('agent_count_in_config')}",
        f"Providers: {', '.join(report.get('provider_names') or []) or 'none detected'}",
        f"Hermes providers: {', '.join(report.get('hermes_provider_names') or []) or 'none detected'}",
        f"Hermes assigned agents: {len(report.get('hermes_assigned_agents') or [])}",
        f"OpenAI assigned agents: {report.get('openai_assigned_count')}",
        "",
        "Model counts:",
    ]
    for model, count in sorted((report.get("model_counts") or {}).items()):
        lines.append(f"- {model}: {count}")
    lines.append("")
    lines.append("File counts:")
    for key, count in sorted((report.get("file_counts") or {}).items()):
        lines.append(f"- {key}: {count}")
    if report.get("hermes_assigned_agents"):
        lines.append("")
        lines.append("Hermes assigned agents:")
        for aid in report.get("hermes_assigned_agents") or []:
            lines.append(f"- {aid}")
    if report.get("missing_model_agents"):
        lines.append("")
        lines.append("Agents with unset/unknown model:")
        for aid in report.get("missing_model_agents") or []:
            lines.append(f"- {aid}")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, txt_path


def main() -> None:
    global ROOT, OPENCLAW_JSON, LIVE_AGENTS, MEMORY_ROOT, REPORTS

    parser = argparse.ArgumentParser(description="Inventory OpenClaw/Hermes second-brain wiring and agent memory file coverage.")
    parser.add_argument("--config", type=Path, default=OPENCLAW_JSON, help="Path to openclaw.json")
    parser.add_argument("--root", type=Path, default=ROOT, help="ACC workspace root")
    args = parser.parse_args()

    ROOT = args.root
    OPENCLAW_JSON = args.config
    LIVE_AGENTS = ROOT.parent / "workspaces" / "ai_agents"
    MEMORY_ROOT = ROOT / "ai_agents_memory"
    REPORTS = ROOT / "reports"

    report = build_report()
    json_path, txt_path = write_reports(report)
    print(txt_path.read_text(encoding="utf-8"))
    print(f"Wrote: {json_path}")
    print(f"Wrote: {txt_path}")


if __name__ == "__main__":
    main()
