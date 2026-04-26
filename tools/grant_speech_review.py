#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
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

RUNS_DIR = ROOT / "state" / "live_runs"
GRANT_DIR = ROOT / "state" / "grant_speeches"
GRANT_RPG_STATE = ROOT / "ai_agents_memory" / "grant_cardone" / "RPG_STATE.md"
GRANT_RPG_HISTORY = ROOT / "ai_agents_memory" / "grant_cardone" / "RPG_HISTORY.md"
MEMORY_ROOT = ROOT / "ai_agents_memory"


def _latest_run_dir() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    runs = [p for p in RUNS_DIR.glob("run_*") if p.is_dir()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def _run_dir_from_id(run_id: str | None) -> Path | None:
    return RUNS_DIR / run_id if run_id else _latest_run_dir()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return default


def _clip(value: Any, limit: int = 2200) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"


def _latest_review_text(folder: Path, suffix: str, run_id: str | None) -> str:
    candidates: list[Path] = []
    if run_id:
        candidates.append(folder / f"{run_id}_{suffix}.txt")
    if folder.exists():
        candidates.extend(sorted(folder.glob(f"*_{suffix}.txt"), key=lambda p: p.stat().st_mtime, reverse=True))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        text = _read_text(path).strip()
        if text:
            return text
    return ""


def _build_context(run_dir: Path) -> dict[str, Any]:
    run_id = run_dir.name
    art = run_dir / "artifacts"
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "target_state": _read_json(art / "target_state.json", {}),
        "grant_briefing": _read_json(art / "grant_briefing.json", _read_json(ROOT / "state" / "grant" / "latest_grant_briefing.json", {})),
        "ledger_review_excerpt": _clip(_latest_review_text(ROOT / "state" / "ledger_reviews", "ledger_review", run_id), 1200) or "No Ledger review available yet.",
        "helena_review_excerpt": _clip(_latest_review_text(ROOT / "state" / "helena_reviews", "helena_review", run_id), 1200) or "No Helena review available yet.",
        "axiom_review_excerpt": _clip(_latest_review_text(ROOT / "state" / "axiom_reviews", "axiom_review", run_id), 1200) or "No Axiom review available yet.",
        "vivienne_review_excerpt": _clip(_latest_review_text(ROOT / "state" / "vivienne_reviews", "vivienne_review", run_id), 1200) or "No Vivienne review available yet.",
    }


def _build_prompt(context: dict[str, Any], speech_type: str) -> str:
    return f"""
Grant Cardone, deliver a controlled ACC revenue-expansion pressure speech.

This is an actual organizational leadership job. You are not here to hallucinate revenue. You are here to turn the facts below into focused pressure, ambition, and execution discipline.

Rules:
- Use only the facts provided.
- Be intense, short, and specific.
- Do not claim real profits unless the artifacts prove them.
- Do not use generic motivational filler.
- Do not write a giant essay.
- End with exactly 3 short "Cliff Notes for agents" bullets that listeners can store in MEMORY.md.

Speech type: {speech_type}

Context:
{_clip(json.dumps(context, indent=2, sort_keys=True, default=str), 8000)}

Required output:
1. Grant speech: 1-3 short paragraphs.
2. Pressure targets: 3 bullets.
3. Cliff Notes for agents: exactly 3 bullets.
""".strip()


def _call_grant(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_resolve_openclaw_bin(), "agent", "--agent", "grant_cardone", "--message", prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _extract_cliff_notes(text: str) -> list[str]:
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    notes: list[str] = []
    capture = False
    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if "cliff notes" in low or "cliff-notes" in low:
            capture = True
            continue
        if capture and stripped:
            if stripped.startswith(("-", "•", "1.", "2.", "3.")):
                cleaned = re.sub(r"^[-•\s]*", "", stripped)
                cleaned = re.sub(r"^\d+\.\s*", "", cleaned).strip()
                if cleaned:
                    notes.append(cleaned)
                if len(notes) >= 3:
                    break
            elif len(notes) >= 3:
                break
    if not notes:
        notes = ["Grant delivered pressure briefing; review state/grant_speeches for full speech."]
    return notes[:3]


def _update_grant_rpg(run_id: str, dry_run: bool = False) -> dict[str, Any]:
    before = load_rpg_state(GRANT_RPG_STATE)
    after = update_xp(before, 6.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["speed"] = min(100.0, float(after.get("speed") or 0.0) + 1.0)
    after["judgment"] = min(100.0, float(after.get("judgment") or 0.0) + 1.0)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 2.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 1.0)
    saved = after if dry_run else save_rpg_state(GRANT_RPG_STATE, after)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "grant_cardone",
        "event": "grant_pressure_speech",
        "run_id": run_id,
        "xp_delta": 6.0,
        "before_xp": float(before.get("xp") or 0.0),
        "after_xp": float(saved.get("xp") or 0.0),
        "sessions": int(saved.get("sessions") or 0),
    }
    if not dry_run:
        append_human_rpg_history(
            GRANT_RPG_HISTORY,
            timestamp=event["timestamp"],
            agent_id="grant_cardone",
            event_type="Revenue Pressure Speech",
            xp_delta=event["xp_delta"],
            before_xp=event["before_xp"],
            after_xp=event["after_xp"],
            before_level=before.get("level"),
            after_level=saved.get("level"),
            context=f"run_id={run_id} | sessions={event['sessions']}",
            reason="Grant delivered a fact-grounded pressure speech and generated memory cliff notes for agent listeners.",
        )
    return event


def _award_listener_xp(listener: str, run_id: str, dry_run: bool = False) -> dict[str, Any]:
    state_path = MEMORY_ROOT / listener / "RPG_STATE.md"
    hist_path = MEMORY_ROOT / listener / "RPG_HISTORY.md"
    before = load_rpg_state(state_path)
    after = update_xp(before, 1.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["consistency"] = min(100.0, float(after.get("consistency") or 0.0) + 0.5)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 0.5)
    saved = after if dry_run else save_rpg_state(state_path, after)
    event = {
        "agent_id": listener,
        "run_id": run_id,
        "xp_delta": 1.0,
        "before_xp": float(before.get("xp") or 0.0),
        "after_xp": float(saved.get("xp") or 0.0),
        "sessions": int(saved.get("sessions") or 0),
    }
    if not dry_run:
        append_human_rpg_history(
            hist_path,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=listener,
            event_type="Grant Speech Attendance",
            xp_delta=1.0,
            before_xp=event["before_xp"],
            after_xp=event["after_xp"],
            before_level=before.get("level"),
            after_level=saved.get("level"),
            context=f"run_id={run_id} | sessions={event['sessions']}",
            reason="Agent attended Grant pressure briefing and stored concise cliff notes in MEMORY.md.",
        )
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Grant Cardone pressure speech and optionally push cliff notes to listener memories.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--speech-type", default=os.getenv("GRANT_SPEECH_TYPE", "post_run_pressure"))
    parser.add_argument("--listener", action="append", default=[], help="Agent id to receive Grant cliff notes. Can be repeated. Example: --listener bob_company_001")
    parser.add_argument("--listeners", default=os.getenv("GRANT_SPEECH_LISTENERS", ""), help="Comma-separated listener ids.")
    parser.add_argument("--no-listener-xp", action="store_true", help="Write notes but do not award listener attendance XP.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_dir = _run_dir_from_id(args.run_id)
    if run_dir is None:
        raise SystemExit(f"No run folders found under {RUNS_DIR}")
    run_id = run_dir.name
    context = _build_context(run_dir)
    prompt = _build_prompt(context, args.speech_type)

    listeners = list(args.listener)
    if args.listeners:
        listeners.extend([x.strip() for x in args.listeners.split(",") if x.strip()])
    # Preserve order while deduping.
    listeners = list(dict.fromkeys(listeners))

    GRANT_DIR.mkdir(parents=True, exist_ok=True)
    context_path = GRANT_DIR / f"{run_id}_grant_context.json"
    prompt_path = GRANT_DIR / f"{run_id}_grant_prompt.txt"
    speech_path = GRANT_DIR / f"{run_id}_grant_speech.txt"
    notes_path = GRANT_DIR / f"{run_id}_grant_cliff_notes.json"
    event_path = GRANT_DIR / f"{run_id}_grant_rpg_event.json"
    context_path.write_text(json.dumps(context, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        print(f"Dry run. Context saved to: {context_path}")
        print(f"Dry run. Prompt saved to: {prompt_path}")
        print(f"Listeners: {listeners if listeners else 'none'}")
        return

    result = _call_grant(prompt, args.timeout)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    speech_path.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Grant speech failed with exit code {result.returncode}. Output saved to {speech_path}")

    notes = _extract_cliff_notes(output)
    listener_events: list[dict[str, Any]] = []
    if append_memory_notes is not None:
        append_memory_notes(["grant_cardone"], notes, section="Revenue pressure lessons", source=f"grant:{run_id}")
        if listeners:
            append_memory_notes(listeners, notes, section="Grant speech notes", source=f"grant:{run_id}")
    if listeners and not args.no_listener_xp:
        for listener in listeners:
            listener_events.append(_award_listener_xp(listener, run_id, dry_run=False))

    event = _update_grant_rpg(run_id, dry_run=False)
    event["listeners"] = listeners
    event["listener_events"] = listener_events
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    notes_path.write_text(json.dumps({"run_id": run_id, "notes": notes, "listeners": listeners}, indent=2) + "\n", encoding="utf-8")

    print(output.strip())
    print()
    print(f"Context saved to: {context_path}")
    print(f"Prompt saved to: {prompt_path}")
    print(f"Speech saved to: {speech_path}")
    print(f"Cliff notes saved to: {notes_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"Grant XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")
    if listeners:
        print(f"Listener notes written for: {', '.join(listeners)}")


if __name__ == "__main__":
    main()
