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

MEMORY_ROOT = ROOT / "ai_agents_memory"
REPUBLIC_DIR = ROOT / "state" / "republic_reviews"
WATCHDOGS = ["mara", "justine", "owen"]


def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"


def _latest_file(pattern: str) -> Path | None:
    files = list(ROOT.glob(pattern))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _read_text(path: Path | None, limit: int = 2500) -> str:
    if not path or not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:] if limit and len(text) > limit else text


def _clip(value: Any, limit: int = 1800) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _state_summary(agent_id: str) -> dict[str, Any]:
    state = load_rpg_state(MEMORY_ROOT / agent_id / "RPG_STATE.md")
    hist = MEMORY_ROOT / agent_id / "RPG_HISTORY.md"
    mem = MEMORY_ROOT / agent_id / "MEMORY.md"
    return {
        "agent_id": agent_id,
        "xp": state.get("xp"),
        "level": state.get("level"),
        "sessions": state.get("sessions"),
        "evidence_quality": state.get("evidence_quality"),
        "usefulness": state.get("usefulness"),
        "waste_penalty": state.get("waste_penalty"),
        "fake_productivity_penalty": state.get("fake_productivity_penalty"),
        "has_history": hist.exists(),
        "has_memory": mem.exists(),
        "recent_history": _clip(_read_text(hist, limit=1200), 800),
    }


def _build_context(lucian_agent: str) -> dict[str, Any]:
    latest_reviews = {
        "yam_yam": _latest_file("state/executive_reviews/*_yam_yam_review.txt"),
        "axiom": _latest_file("state/axiom_reviews/*_axiom_review.txt"),
        "vivienne": _latest_file("state/vivienne_reviews/*_vivienne_review.txt"),
        "ledger": _latest_file("state/ledger_reviews/*_ledger_review.txt"),
        "helena": _latest_file("state/helena_reviews/*_helena_review.txt"),
        "ariadne": _latest_file("state/ariadne_reviews/*_ariadne_review.txt"),
        "selene": _latest_file("state/selene_reviews/*_selene_review.txt"),
        "june": _latest_file("state/board_archives/*_june_archive.txt"),
    }
    return {
        "review_type": "watchdog_accountability",
        "lucian_agent": lucian_agent,
        "purpose": "Company-side republic check: who watches the watchdogs?",
        "watchdog_state": [_state_summary(a) for a in WATCHDOGS],
        "latest_governance_excerpts": {
            k: _clip(_read_text(v, limit=2500), 1300) for k, v in latest_reviews.items()
        },
        "expected_republic_balance": [
            "Watchdogs may audit master branch abuse.",
            "Master branch may audit company performance.",
            "Company CEOs may challenge watchdog overreach, inactivity, weak evidence, or decorative behavior.",
            "Justine should not be untouchable; constitutional authority must still be reviewable.",
            "Yam Yam remains executive authority, but the republic must avoid one-way power.",
        ],
    }


def _build_prompt(context: dict[str, Any]) -> str:
    return f"""You are {context['lucian_agent']}, a company CEO in Autonomous Corp Capital.

You are performing the first company-side watchdog accountability review.
The point is not to attack the watchdogs. The point is to complete the republic loop:
watchdogs watch master, master watches companies, and company leadership may challenge watchdog overreach or inactivity.

Return exactly these sections:

1. Watchdog conduct assessment:
2. Evidence of overreach, inactivity, or acceptable restraint:
3. Company-side challenge, if any:
4. Recommendation to Yam Yam / Justine:

Rules:
- Be fair.
- Do not invent misconduct.
- If the watchdogs simply have no evidence of activity yet, say that clearly.
- Keep the response concise.

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


def _award_xp(agent_id: str, xp: float, reason: str) -> dict[str, Any]:
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
        event_type="Republic Watchdog Accountability Review",
        xp_delta=xp,
        before_xp=before.get("xp"),
        after_xp=after.get("xp"),
        before_level=before.get("level"),
        after_level=after.get("level"),
        context=f"sessions={after.get('sessions')}",
        reason=reason,
    )
    if append_memory_notes:
        append_memory_notes(
            [agent_id],
            ["Company CEOs may challenge watchdog overreach, inactivity, or weak evidence as part of the republic balance loop."],
            section="Republic governance lessons",
            source="watchdog_accountability",
        )
    return {"before": before, "after": after, "xp_delta": xp}


def main() -> None:
    parser = argparse.ArgumentParser(description="Let a company Lucian review watchdog conduct as a republic balance check.")
    parser.add_argument("--company", default="001", choices=["001", "002", "003", "004"])
    parser.add_argument("--agent", default=None, help="Override Lucian agent id.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    lucian_agent = args.agent or f"lucian_company_{args.company}"
    context = _build_context(lucian_agent)
    prompt = _build_prompt(context)

    REPUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"{stamp}_{lucian_agent}_watchdog_accountability"
    context_path = REPUBLIC_DIR / f"{base}_context.json"
    prompt_path = REPUBLIC_DIR / f"{base}_prompt.txt"
    review_path = REPUBLIC_DIR / f"{base}_review.txt"
    event_path = REPUBLIC_DIR / f"{base}_rpg_event.json"

    context_path.write_text(json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    prompt_path.write_text(prompt, encoding="utf-8")

    if args.dry_run:
        print(f"Dry run context saved to: {context_path}")
        print(f"Dry run prompt saved to: {prompt_path}")
        print(prompt[:3000])
        return

    review = _call_agent(lucian_agent, prompt)
    review_path.write_text(review + "\n", encoding="utf-8")
    event = _award_xp(
        lucian_agent,
        4.0,
        "Completed first company-side watchdog accountability review and saved a republic balance artifact.",
    )
    event_path.write_text(json.dumps(event, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Republic review saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"{lucian_agent} XP: {event['before'].get('xp')} -> {event['after'].get('xp')} | sessions={event['after'].get('sessions')}")


if __name__ == "__main__":
    main()
