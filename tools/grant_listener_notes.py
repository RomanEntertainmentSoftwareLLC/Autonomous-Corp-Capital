#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/openclaw/.openclaw/workspace")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.rpg_state import append_human_rpg_history, load_rpg_state, save_rpg_state, update_xp
try:
    from tools.memory_writer import append_memory_notes
except Exception:  # pragma: no cover
    append_memory_notes = None  # type: ignore

MEMORY_ROOT = ROOT / "ai_agents_memory"
GRANT_DIR = ROOT / "state" / "grant_speeches"

MASTER = ["main", "selene", "helena", "vivienne", "ariadne", "ledger", "axiom", "grant_cardone"]
WATCHDOG = ["mara", "justine", "owen"]
SWE = ["nadia", "tessa", "marek", "eli", "noah", "mina", "gideon", "sabine", "rhea"]
COMPANY_ROLES = ["pam", "iris", "vera", "rowan", "bianca", "lucian", "bob", "sloane", "atlas", "june", "orion"]
COMPANIES = ["001", "002", "003", "004"]


def company_agents(company: str) -> list[str]:
    return [f"{role}_company_{company}" for role in COMPANY_ROLES]


def all_company_agents() -> list[str]:
    out: list[str] = []
    for c in COMPANIES:
        out.extend(company_agents(c))
    return out


def _latest_notes_file() -> Path | None:
    if not GRANT_DIR.exists():
        return None
    files = list(GRANT_DIR.glob("*_grant_cliff_notes.json"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_run_id(path: Path) -> str:
    name = path.name
    return name.split("_grant_cliff_notes.json")[0]


def _extract_notes(obj: Any) -> list[str]:
    if isinstance(obj, list):
        return [str(x).strip() for x in obj if str(x).strip()]
    if isinstance(obj, dict):
        for key in ("cliff_notes", "notes", "agent_notes", "agent_cliff_notes", "memory_notes"):
            value = obj.get(key)
            if isinstance(value, list):
                return [str(x).strip() for x in value if str(x).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
        # tolerate {"0": "...", "1": "..."} style
        vals = [str(v).strip() for v in obj.values() if isinstance(v, str) and v.strip()]
        if vals:
            return vals
    if isinstance(obj, str) and obj.strip():
        return [obj.strip()]
    return []


def _listeners_from_args(args: argparse.Namespace) -> list[str]:
    listeners: list[str] = list(args.listener or [])
    if args.branch:
        for branch in args.branch:
            if branch == "master":
                listeners.extend(MASTER)
            elif branch == "watchdog":
                listeners.extend(WATCHDOG)
            elif branch == "companies":
                listeners.extend(all_company_agents())
            elif branch.startswith("company_"):
                listeners.extend(company_agents(branch.split("_", 1)[1]))
            elif branch == "all_non_swe":
                listeners.extend(MASTER + WATCHDOG + all_company_agents())
            elif branch == "all":
                listeners.extend(MASTER + WATCHDOG + all_company_agents() + (SWE if args.include_swe else []))
    if args.include_swe and "all" not in (args.branch or []):
        listeners.extend(SWE)
    # Grant should not take notes on his own speech unless explicitly asked
    if not args.include_grant:
        listeners = [x for x in listeners if x != "grant_cardone"]
    seen: set[str] = set()
    ordered: list[str] = []
    for item in listeners:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _award_attendance(agent_id: str, run_id: str, xp: float, note_count: int) -> dict[str, Any]:
    state_path = MEMORY_ROOT / agent_id / "RPG_STATE.md"
    history_path = MEMORY_ROOT / agent_id / "RPG_HISTORY.md"
    before = load_rpg_state(state_path)
    after = update_xp(before, xp)
    after["sessions"] = int(after.get("sessions", 0)) + 1
    save_rpg_state(state_path, after)
    append_human_rpg_history(
        history_path,
        timestamp=datetime.now(timezone.utc),
        agent_id=agent_id,
        event_type="Grant Speech Attendance",
        xp_delta=xp,
        before_xp=before.get("xp"),
        after_xp=after.get("xp"),
        before_level=before.get("level"),
        after_level=after.get("level"),
        context=f"run_id={run_id} | sessions={after.get('sessions')}",
        reason=f"Agent attended Grant pressure briefing and stored {note_count} concise cliff notes in MEMORY.md.",
    )
    return {"before_xp": before.get("xp"), "after_xp": after.get("xp"), "sessions": after.get("sessions")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Distribute latest Grant cliff notes to selected agent MEMORY.md files without re-running Grant.")
    parser.add_argument("--notes-file", default=None, help="Specific *_grant_cliff_notes.json. Defaults to latest.")
    parser.add_argument("--listener", action="append", help="Specific listener agent id. Can be repeated.")
    parser.add_argument(
        "--branch",
        action="append",
        choices=["master", "watchdog", "companies", "company_001", "company_002", "company_003", "company_004", "all_non_swe", "all"],
        help="Listener group. Can be repeated.",
    )
    parser.add_argument("--include-swe", action="store_true", help="Include SWE agents when using all.")
    parser.add_argument("--include-grant", action="store_true", help="Let Grant receive his own notes.")
    parser.add_argument("--xp", type=float, default=1.0, help="XP per listener.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    notes_path = Path(args.notes_file) if args.notes_file else _latest_notes_file()
    if not notes_path or not notes_path.exists():
        raise SystemExit("No Grant cliff notes file found.")

    raw = _read_json(notes_path)
    notes = _extract_notes(raw)
    if not notes:
        raise SystemExit(f"No cliff notes found in {notes_path}")

    listeners = _listeners_from_args(args)
    if not listeners:
        raise SystemExit("No listeners selected. Use --listener or --branch.")

    run_id = _extract_run_id(notes_path)
    print(f"Grant notes file: {notes_path}")
    print(f"Run id: {run_id}")
    print(f"Listeners ({len(listeners)}): {', '.join(listeners)}")
    print("Notes:")
    for note in notes:
        print(f"- {note}")

    if args.dry_run:
        print("Dry run only. No files changed.")
        return

    if append_memory_notes:
        append_memory_notes(
            listeners,
            notes,
            section="Grant speech notes",
            source=f"grant:{run_id}",
        )
    else:
        for agent_id in listeners:
            path = MEMORY_ROOT / agent_id / "MEMORY.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else "# MEMORY.md\n\n_Agent-local durable memory._\n\n"
            if "## Grant speech notes" not in text:
                text = text.rstrip() + "\n\n## Grant speech notes\n"
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for note in notes:
                line = f"- {date}: [grant:{run_id}] {note}"
                if line not in text:
                    text += line + "\n"
            path.write_text(text, encoding="utf-8")

    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "notes_file": str(notes_path),
        "listeners": listeners,
        "notes": notes,
        "xp_per_listener": args.xp,
        "results": {},
    }
    for agent_id in listeners:
        manifest["results"][agent_id] = _award_attendance(agent_id, run_id, args.xp, len(notes))

    out = GRANT_DIR / f"{run_id}_grant_listener_manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Listener manifest saved to: {out}")


if __name__ == "__main__":
    main()
