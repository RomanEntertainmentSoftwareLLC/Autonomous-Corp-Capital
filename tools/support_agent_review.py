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
SUPPORT_DIR = ROOT / "state" / "support_reviews"
MEMORY_ROOT = ROOT / "ai_agents_memory"

TASK_DESCRIPTIONS = {
    "coordination": "coordinate the next practical follow-up from the latest governance packet and identify one handoff problem.",
    "operations": "review operational friction, idle work, evidence cleanup, and one useful Bob-level action that does not burn tokens.",
    "research": "summarize what external or cached context is missing before the next paper proof and what should be researched later.",
    "simulation": "identify one scenario the system should simulate before trusting the next paper proof.",
    "evolution": "identify one safe agent/process improvement based on the latest review packet.",
    "archive": "summarize what should be archived as durable organizational memory.",
    "grant_followup": "turn the latest Grant cliff notes into one concrete role-specific action.",
    "evidence_cleanup": "identify one evidence gap that must be closed before roadmap step #7 paper proof.",
}

ROLE_HINTS = {
    "pam": "Front Desk Administrator / coordinator. Keep it practical, organized, and brief.",
    "bob": "Operations Worker. Be useful, not decorative. No generic synergy speech unless it becomes a concrete action.",
    "rowan": "Researcher. Focus on missing context and evidence gaps.",
    "atlas": "Market Simulator. Focus on scenarios, stress cases, and what-if thinking.",
    "sloane": "Evolution Specialist. Focus on safe improvement loops, not broad redesign.",
    "june": "Archivist. Focus on durable notes, board memory, and what should be preserved.",
}


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


def _read_text(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:] if limit and len(text) > limit else text


def _read_jsonl(path: Path, limit: int = 1000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit and len(lines) > limit:
        lines = lines[-limit:]
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _clip(value: Any, limit: int = 1800) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text).strip("_") or "review"


def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"


def _infer_task(agent_id: str) -> str:
    low = agent_id.lower()
    if low.startswith("pam_"):
        return "coordination"
    if low.startswith("bob_"):
        return "operations"
    if low.startswith("rowan_"):
        return "research"
    if low.startswith("atlas_"):
        return "simulation"
    if low.startswith("sloane_"):
        return "evolution"
    if low.startswith("june_"):
        return "archive"
    return "evidence_cleanup"


def _role_hint(agent_id: str) -> str:
    low = agent_id.lower()
    for key, hint in ROLE_HINTS.items():
        if low.startswith(key + "_"):
            return hint
    return "Support agent. Stay role-bound, concise, and useful."


def _latest_file(pattern: str) -> Path | None:
    files = list(ROOT.glob(pattern))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _build_context(run_dir: Path | None, agent_id: str, task: str) -> dict[str, Any]:
    run_id = run_dir.name if run_dir else "NO_RUN"
    art = run_dir / "artifacts" if run_dir else ROOT / "missing_run_artifacts"

    target_state = _read_json(art / "target_state.json", {})
    grant_briefing = _read_json(art / "grant_briefing.json", {})
    decisions = _read_jsonl(art / "paper_decisions.jsonl", limit=50)
    trades = _read_jsonl(art / "paper_trades.jsonl", limit=50)

    latest_grant_notes = _latest_file("state/grant_speeches/*_grant_cliff_notes.json")
    grant_notes = _read_json(latest_grant_notes, {}) if latest_grant_notes else {}

    review_files = {
        "ledger": _latest_file("state/ledger_reviews/*_ledger_review.txt"),
        "helena": _latest_file("state/helena_reviews/*_helena_review.txt"),
        "axiom": _latest_file("state/axiom_reviews/*_axiom_review.txt"),
        "vivienne": _latest_file("state/vivienne_reviews/*_vivienne_review.txt"),
        "selene": _latest_file("state/selene_reviews/*_selene_review.txt"),
        "ariadne": _latest_file("state/ariadne_reviews/*_ariadne_review.txt"),
        "yam_yam": _latest_file("state/executive_reviews/*_yam_yam_review.txt"),
    }

    return {
        "run_id": run_id,
        "agent_id": agent_id,
        "task": task,
        "task_description": TASK_DESCRIPTIONS.get(task, task),
        "role_hint": _role_hint(agent_id),
        "target_state": target_state,
        "grant_briefing_summary": {
            "market": grant_briefing.get("market"),
            "target_status": grant_briefing.get("target_status"),
            "leader": grant_briefing.get("leader"),
            "laggard": grant_briefing.get("laggard"),
            "weak_agents_flagged": grant_briefing.get("weak_agents_flagged"),
        },
        "latest_decisions_sample": decisions[-10:],
        "latest_trades_sample": trades[-10:],
        "latest_grant_notes_file": str(latest_grant_notes) if latest_grant_notes else None,
        "latest_grant_notes": grant_notes,
        "governance_review_excerpts": {
            name: _clip(_read_text(path, limit=2500), 1400) if path else ""
            for name, path in review_files.items()
        },
    }


def _build_prompt(context: dict[str, Any]) -> str:
    return f"""You are {context['agent_id']} in Autonomous Corp Capital.

Role hint:
{context['role_hint']}

Task:
{context['task_description']}

Use the context below. Stay concise. Do not ramble. Do not invent missing facts.
Return exactly these sections:

1. Role-specific finding:
2. One concrete next action:
3. Memory-worthy lesson:

Context:
{json.dumps(context, indent=2, ensure_ascii=False)[:12000]}
"""


def _call_agent(agent_id: str, prompt: str, timeout: int = 240) -> str:
    cmd = [_resolve_openclaw_bin(), "agent", "--agent", agent_id, "--message", prompt]
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
    output = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"openclaw exited {proc.returncode}: {err or output}")
    return output or err or ""


def _award_xp(agent_id: str, run_id: str, task: str, xp: float, reason: str, context_note: str) -> dict[str, Any]:
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
        event_type=f"Support Review: {task}",
        xp_delta=xp,
        before_xp=before.get("xp"),
        after_xp=after.get("xp"),
        before_level=before.get("level"),
        after_level=after.get("level"),
        context=f"run_id={run_id} | sessions={after.get('sessions')}",
        reason=reason,
    )
    if append_memory_notes:
        append_memory_notes(
            [agent_id],
            [context_note],
            section="Support role lessons",
            source=f"support:{task}:{run_id}",
        )
    return {"before": before, "after": after, "xp_delta": xp}


def run_review(agent_id: str, task: str | None, run_id: str | None, dry_run: bool = False) -> None:
    task = task or _infer_task(agent_id)
    run_dir = _run_dir_from_id(run_id)
    context = _build_context(run_dir, agent_id, task)
    prompt = _build_prompt(context)
    actual_run_id = context["run_id"]
    safe = _safe_name(f"{actual_run_id}_{agent_id}_{task}")

    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    context_path = SUPPORT_DIR / f"{safe}_context.json"
    prompt_path = SUPPORT_DIR / f"{safe}_prompt.txt"
    review_path = SUPPORT_DIR / f"{safe}_review.txt"
    event_path = SUPPORT_DIR / f"{safe}_rpg_event.json"

    context_path.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    prompt_path.write_text(prompt, encoding="utf-8")

    if dry_run:
        print(f"Dry run saved context to: {context_path}")
        print(f"Dry run saved prompt to: {prompt_path}")
        print(prompt[:3000])
        return

    review = _call_agent(agent_id, prompt)
    review_path.write_text(review + "\n", encoding="utf-8")

    event = _award_xp(
        agent_id,
        actual_run_id,
        task,
        xp=3.0,
        reason=f"Completed a role-bound support review for task '{task}' and saved an artifact.",
        context_note=f"Completed {task} support review for {actual_run_id}; focus on one concrete next action and no decorative token burn.",
    )
    event_path.write_text(json.dumps(event, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Support review saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"{agent_id} XP: {event['before'].get('xp')} -> {event['after'].get('xp')} | sessions={event['after'].get('sessions')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Activate one support/company agent for a specific role-bound review.")
    parser.add_argument("--agent", required=True, help="Agent id, e.g. bob_company_001 or pam_company_001.")
    parser.add_argument("--task", default=None, choices=sorted(TASK_DESCRIPTIONS), help="Task preset. Defaults from agent role.")
    parser.add_argument("--run-id", default=None, help="Run id. Defaults to latest run.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_review(args.agent, args.task, args.run_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
