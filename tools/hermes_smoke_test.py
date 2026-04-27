#!/usr/bin/env python3
"""Run lightweight OpenClaw agent smoke tests after Hermes rollout phases."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CONFIG_PATH = Path(os.environ.get("OPENCLAW_CONFIG", "/opt/openclaw/.openclaw/openclaw.json"))
DEFAULT_TIMEOUT = int(os.environ.get("HERMES_SMOKE_TIMEOUT", "180"))
DEFAULT_MESSAGE = (
    "Smoke test: briefly identify yourself by name and role, then state whether you can respond normally. "
    "Keep the answer concise."
)

PHASES: dict[str, tuple[str, ...]] = {
    "phase0": ("main",),
    "phase1": ("axiom", "vivienne", "helena", "ledger"),
    "phase2": ("grant_cardone", "ariadne", "selene"),
    "watchdogs": ("mara", "justine", "owen"),
    "swe": ("nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea"),
}


def _company_ids(roles: Iterable[str]) -> tuple[str, ...]:
    return tuple(f"{role}_company_{company}" for company in ("001", "002", "003", "004") for role in roles)


PHASES["company_core"] = _company_ids(("lucian", "bianca", "iris", "vera", "orion", "rowan"))
PHASES["company_support"] = _company_ids(("pam", "bob", "sloane", "atlas", "june"))
PHASES["all_non_swe"] = tuple(dict.fromkeys(
    PHASES["phase0"] + PHASES["phase1"] + PHASES["phase2"] + PHASES["company_core"] + PHASES["company_support"] + PHASES["watchdogs"]
))
PHASES["all"] = tuple(dict.fromkeys(PHASES["all_non_swe"] + PHASES["swe"]))


def _search_path() -> str:
    env_path = os.environ.get("PATH", "")
    preferred = [
        str(Path.home() / ".npm-global" / "bin"),
        str(Path.home() / ".local" / "bin"),
        str(Path(sys.executable).resolve().parent),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    parts: list[str] = []
    for item in preferred + env_path.split(os.pathsep):
        if item and item not in parts:
            parts.append(item)
    return os.pathsep.join(parts)


def _openclaw_cmd() -> list[str]:
    override = os.environ.get("OPENCLAW_BIN", "").strip()
    if override:
        return [override]
    resolved = shutil.which("openclaw", path=_search_path())
    if resolved:
        return [resolved]
    hardcoded = Path.home() / ".npm-global" / "bin" / "openclaw"
    if hardcoded.exists():
        return [str(hardcoded)]
    raise RuntimeError("Could not find openclaw executable. Set OPENCLAW_BIN to its full path.")


def _load_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _iter_agent_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return agent dictionaries from supported OpenClaw config shapes."""
    agents = config.get("agents")
    if isinstance(agents, dict):
        agent_list = agents.get("list")
        if isinstance(agent_list, list):
            return [item for item in agent_list if isinstance(item, dict)]

        rows: list[dict[str, Any]] = []
        for key, value in agents.items():
            if key in {"defaults", "list"}:
                continue
            if isinstance(value, dict):
                rows.append({"id": key, **value})
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


def _agent_model(config: dict[str, Any], agent_id: str) -> str:
    for entry in _iter_agent_entries(config):
        aid = _agent_id(entry)
        if aid == agent_id:
            return _model_text(entry.get("model"))
    return "<missing>"


def _phase_agents(args: argparse.Namespace) -> list[str]:
    agents: list[str] = []
    if args.phase0:
        agents.extend(PHASES["phase0"])
    if args.phase1:
        agents.extend(PHASES["phase1"])
    if args.phase:
        agents.extend(PHASES[args.phase])
    if args.agent:
        agents.extend(args.agent)
    return list(dict.fromkeys(agents))


def _snippet(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n... <truncated>"


def smoke_agent(agent_id: str, message: str, timeout: int, dry_run: bool) -> bool:
    print(f"\n== {agent_id} ==")
    if dry_run:
        display_bin = os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw", path=_search_path()) or "openclaw"
        print("Command:", " ".join([display_bin, "agent", "--agent", agent_id, "--message", "<message>"]))
        print("Dry run: command not executed.")
        return True

    try:
        cmd = _openclaw_cmd() + ["agent", "--agent", agent_id, "--message", message]
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        return False

    print("Command:", " ".join(cmd[:1] + ["agent", "--agent", agent_id, "--message", "<message>"]))
    env = dict(os.environ)
    env["PATH"] = _search_path()
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"FAILED: timed out after {timeout}s")
        return False

    if result.stdout.strip():
        print("stdout:")
        print(_snippet(result.stdout))
    if result.stderr.strip():
        print("stderr:")
        print(_snippet(result.stderr))
    if result.returncode == 0:
        print("PASS")
        return True
    print(f"FAILED: exit code {result.returncode}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test selected OpenClaw agents after Hermes rollout.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to openclaw.json for model reporting")
    parser.add_argument("--agent", action="append", help="Agent id to smoke test. May be repeated.")
    parser.add_argument("--phase", choices=sorted(PHASES.keys()), help="Smoke test all agents in a rollout phase")
    parser.add_argument("--phase0", action="store_true", help="Shortcut for --phase phase0")
    parser.add_argument("--phase1", action="store_true", help="Shortcut for --phase phase1")
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="Message sent to each agent")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Seconds per agent before timeout")
    parser.add_argument("--dry-run", action="store_true", help="Print commands and model status without invoking OpenClaw")
    args = parser.parse_args()

    agents = _phase_agents(args)
    if not agents:
        parser.error("Use --agent, --phase, --phase0, or --phase1.")

    config = _load_config(args.config)
    print(f"Config: {args.config}")
    print("Selected agents:")
    for aid in agents:
        print(f"- {aid} | configured_model={_agent_model(config, aid)}")

    ok = True
    for aid in agents:
        ok = smoke_agent(aid, args.message, args.timeout, args.dry_run) and ok
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
