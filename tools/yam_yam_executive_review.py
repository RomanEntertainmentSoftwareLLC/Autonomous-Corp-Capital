#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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
from tools.memory_writer import append_memory_notes
RUNS_DIR = ROOT / "state" / "live_runs"
BRIEFING_PATH = ROOT / "state" / "grant" / "latest_grant_briefing.json"
EXEC_REVIEW_DIR = ROOT / "state" / "executive_reviews"
AXIOM_REVIEW_DIR = ROOT / "state" / "axiom_reviews"
VIVIENNE_REVIEW_DIR = ROOT / "state" / "vivienne_reviews"
LEDGER_REVIEW_DIR = ROOT / "state" / "ledger_reviews"
HELENA_REVIEW_DIR = ROOT / "state" / "helena_reviews"
GRANT_SPEECH_DIR = ROOT / "state" / "grant_speeches"
SELENE_REVIEW_DIR = ROOT / "state" / "selene_reviews"
ARIADNE_REVIEW_DIR = ROOT / "state" / "ariadne_reviews"
MAIN_RPG_STATE = ROOT / "ai_agents_memory" / "main" / "RPG_STATE.md"
MAIN_RPG_HISTORY = ROOT / "ai_agents_memory" / "main" / "RPG_HISTORY.md"
MAIN_MEMORY = ROOT / "MEMORY.md"


def _latest_run_dir() -> Path:
    runs = [p for p in RUNS_DIR.glob("run_*") if p.is_dir()]
    if not runs:
        raise SystemExit(f"No run folders found under {RUNS_DIR}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _resolve_openclaw_bin() -> str:
    return (
        os.environ.get("OPENCLAW_BIN")
        or shutil.which("openclaw")
        or "/home/psych/.npm-global/bin/openclaw"
    )


def _clip(text: Any, limit: int = 900) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _ensure_briefing(run_id: str | None) -> dict[str, Any]:
    """Build/read the latest Grant briefing so Yam Yam reviews facts, not vibes."""
    # Prefer building fresh from the current run artifacts when possible.
    try:
        from tools.grant_briefing_builder import build_briefing, run_dir_from_arg

        run_dir = run_dir_from_arg(run_id) if run_id else _latest_run_dir()
        briefing = build_briefing(run_dir)
        out_path = run_dir / "artifacts" / "grant_briefing.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(briefing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        BRIEFING_PATH.parent.mkdir(parents=True, exist_ok=True)
        BRIEFING_PATH.write_text(json.dumps(briefing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return briefing
    except Exception:
        briefing = _read_json(BRIEFING_PATH, {})
        if not briefing:
            raise
        return briefing


def _company_lines(briefing: dict[str, Any]) -> list[str]:
    board = briefing.get("company_scoreboard") or {}
    companies = board.get("companies") or {}
    ranked = board.get("ranked") or []
    lines: list[str] = []
    for row in ranked[:4]:
        company = row.get("company")
        data = companies.get(company, {}) if isinstance(companies, dict) else {}
        lines.append(
            f"- {company}: rank={data.get('rank')}, status={data.get('status')}, "
            f"pnl_vs_allocation={data.get('pnl_vs_allocation')}, "
            f"realized={data.get('realized_pnl')}, unrealized={data.get('unrealized_pnl')}, "
            f"open_positions={data.get('open_positions_count')}, trades={data.get('trade_count')}"
        )
    return lines or ["- No company scoreboard rows available."]


def _weak_agent_lines(briefing: dict[str, Any]) -> list[str]:
    axiom = briefing.get("axiom_metrics") or {}
    weak = axiom.get("weak_agents") or []
    lines: list[str] = []
    for item in weak[:8]:
        lines.append(
            f"- {item.get('agent_id')}: usefulness={item.get('usefulness')}, "
            f"judgment={item.get('judgment')}, evidence={item.get('evidence_quality')}, "
            f"waste={item.get('waste_penalty')}, fake={item.get('fake_productivity_penalty')}"
        )
    return lines or ["- No weak agents flagged."]



def _read_latest_text(folder: Path, run_id: str | None, suffix: str, missing: str, limit: int = 2400) -> str:
    candidates: list[Path] = []
    if run_id:
        candidates.append(folder / f"{run_id}_{suffix}.txt")
    if folder.exists():
        candidates.extend(sorted(folder.glob(f"*_{suffix}.txt"), key=lambda p: p.stat().st_mtime, reverse=True))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return _clip(text, limit)
    return missing


def _read_axiom_review(run_id: str | None) -> str:
    """Return the latest Axiom evaluator review for this run, if available.

    Axiom is the evidence judge. Yam Yam is the executive synthesizer.
    Keeping this read-only and optional lets Yam Yam use Axiom when present
    without making executive review fragile if Axiom fails.
    """
    candidates: list[Path] = []
    if run_id:
        candidates.append(AXIOM_REVIEW_DIR / f"{run_id}_axiom_review.txt")
    if AXIOM_REVIEW_DIR.exists():
        candidates.extend(sorted(AXIOM_REVIEW_DIR.glob("*_axiom_review.txt"), key=lambda p: p.stat().st_mtime, reverse=True))
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return _clip(text, 2400)
    return "No Axiom evaluator review available yet."


def _read_vivienne_review(run_id: str | None) -> str:
    """Return the latest Vivienne financial truth review for this run, if available.

    Vivienne is the financial truth judge. Yam Yam should know whether the P/L,
    target status, and portfolio coverage are trustworthy before making executive
    directives. This remains optional so Yam Yam can still run if Vivienne fails.
    """
    candidates: list[Path] = []
    if run_id:
        candidates.append(VIVIENNE_REVIEW_DIR / f"{run_id}_vivienne_review.txt")
    if VIVIENNE_REVIEW_DIR.exists():
        candidates.extend(sorted(VIVIENNE_REVIEW_DIR.glob("*_vivienne_review.txt"), key=lambda p: p.stat().st_mtime, reverse=True))
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return _clip(text, 2400)
    return "No Vivienne financial truth review available yet."


def _read_ledger_review(run_id: str | None) -> str:
    """Return the latest Ledger cost governance review for this run, if available."""
    return _read_latest_text(
        LEDGER_REVIEW_DIR,
        run_id,
        "ledger_review",
        "No Ledger token/cost governance review available yet.",
        1800,
    )


def _read_helena_review(run_id: str | None) -> str:
    """Return the latest Helena risk review for this run, if available."""
    return _read_latest_text(
        HELENA_REVIEW_DIR,
        run_id,
        "helena_review",
        "No Helena risk review available yet.",
        1800,
    )


def _read_grant_speech(run_id: str | None) -> str:
    """Return the latest Grant pressure speech for this run, if available."""
    return _read_latest_text(
        GRANT_SPEECH_DIR,
        run_id,
        "grant_speech",
        "No Grant pressure speech available yet.",
        1600,
    )



def _read_selene_review(run_id: str | None) -> str:
    """Return the latest Selene treasury review for this run, if available."""
    return _read_latest_text(
        SELENE_REVIEW_DIR,
        run_id,
        "selene_review",
        "No Selene treasury review available yet.",
        1800,
    )


def _read_ariadne_review(run_id: str | None) -> str:
    """Return the latest Ariadne workforce review for this run, if available."""
    return _read_latest_text(
        ARIADNE_REVIEW_DIR,
        run_id,
        "ariadne_review",
        "No Ariadne workforce review available yet.",
        1800,
    )


def _build_prompt(briefing: dict[str, Any], axiom_review: str | None = None, vivienne_review: str | None = None, ledger_review: str | None = None, helena_review: str | None = None, grant_speech: str | None = None, selene_review: str | None = None, ariadne_review: str | None = None) -> str:
    market = briefing.get("market") or {}
    target = briefing.get("target_state") or {}
    committee = briefing.get("committee_health") or {}
    usage = briefing.get("usage_summary") or {}
    flags = briefing.get("review_flags") or []

    prompt = f"""
Yam Yam, perform a Master CEO post-run executive review for Autonomous Corp Capital.

This is an actual runtime job. Do not give a generic identity answer. Review the facts, make executive observations, and issue concise next directives.

Use ONLY the briefing facts below. Do not invent numbers.

Run:
- run_id: {briefing.get('run_id')}
- recommended_speech_type: {briefing.get('recommended_speech_type')}
- review_flags: {', '.join(map(str, flags)) if flags else 'none'}

Market:
- condition: {market.get('condition')}
- bias: {market.get('bias')}
- volatility: {market.get('volatility')}
- summary: {_clip(market.get('summary'), 500)}

Targets:
- starting equity: {target.get('starting_equity')}
- current equity estimate: {target.get('current_equity_estimate')}
- total P/L estimate: {target.get('total_pnl_estimate')}
- floor target equity: {target.get('floor_target_equity')}
- goal target equity: {target.get('goal_target_equity')}
- stretch target equity: {target.get('stretch_target_equity')}
- target status: {target.get('target_status')}

Company scoreboard:
{chr(10).join(_company_lines(briefing))}

Committee health:
- status: {committee.get('status')}
- fallback packets: {committee.get('fallback_packets')} / {committee.get('packet_count')}
- fresh committee packets: {committee.get('fresh_committee_packets')}
- timeout packets: {committee.get('timeout_packets')}

Axiom weak-agent flags from Grant briefing:
{chr(10).join(_weak_agent_lines(briefing))}

Latest Axiom evaluator review:
{_clip(axiom_review, 2400) if axiom_review else "No Axiom evaluator review available yet."}

Latest Vivienne financial truth review:
{_clip(vivienne_review, 2400) if vivienne_review else "No Vivienne financial truth review available yet."}

Latest Ledger token/cost governance review:
{_clip(ledger_review, 1800) if ledger_review else "No Ledger token/cost governance review available yet."}

Latest Helena risk review:
{_clip(helena_review, 1800) if helena_review else "No Helena risk review available yet."}

Latest Grant pressure speech:
{_clip(grant_speech, 1600) if grant_speech else "No Grant pressure speech available yet."}

Latest Selene treasury review:
{_clip(selene_review, 1600) if selene_review else "No Selene treasury review available yet."}

Latest Ariadne workforce review:
{_clip(ariadne_review, 1600) if ariadne_review else "No Ariadne workforce review available yet."}

Usage telemetry:
- ledger rows: {usage.get('ledger_rows')}
- bridge rows: {usage.get('bridge_rows')}
- token counts available: {usage.get('token_counts_available')}

Required output:
1. Executive verdict: one paragraph.
2. What actually happened: 3-5 bullets.
3. Financial/accounting trust: 2-4 bullets based on Vivienne if available.
4. Risk and cost governance: 2-4 bullets based on Helena and Ledger if available.
5. Treasury and workforce governance: 2-4 bullets based on Selene and Ariadne if available.
6. Who needs pressure or review: 3-5 bullets.
7. Next directives: 3-5 bullets.
8. Memory-worthy cliff notes: 3 bullets max.

Keep it concise, direct, and operational. You are the Master CEO. Act like it.
""".strip()
    return prompt


def _call_openclaw_main(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    openclaw_bin = _resolve_openclaw_bin()
    return subprocess.run(
        [openclaw_bin, "agent", "--agent", "main", "--message", prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _extract_response(stdout: str) -> str:
    text = stdout.strip()
    if not text:
        return ""
    # OpenClaw output contains banner/art. Keep full text for evidence, but also allow memory notes to be concise.
    marker = "◇"
    if marker in text:
        return text.split(marker, 1)[-1].strip()
    return text


def _update_yam_yam_rpg(run_id: str, review_text: str, dry_run: bool = False) -> dict[str, Any]:
    before = load_rpg_state(MAIN_RPG_STATE)
    after = update_xp(before, 8.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["judgment"] = min(100.0, float(after.get("judgment") or 0.0) + 2.0)
    after["reliability"] = min(100.0, float(after.get("reliability") or 0.0) + 1.0)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 2.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 1.0)
    after["consistency"] = min(100.0, float(after.get("consistency") or 0.0) + 1.0)
    saved = after if dry_run else save_rpg_state(MAIN_RPG_STATE, after)

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "main",
        "role": "Master CEO",
        "event": "yam_yam_post_run_executive_review",
        "run_id": run_id,
        "xp_delta": 8.0,
        "before_xp": float(before.get("xp") or 0.0),
        "after_xp": float(saved.get("xp") or 0.0),
        "sessions": int(saved.get("sessions") or 0),
    }

    if not dry_run:
        append_human_rpg_history(
            MAIN_RPG_HISTORY,
            timestamp=event["timestamp"],
            agent_id="main",
            event_type="Post-Run Executive Review",
            xp_delta=event["xp_delta"],
            before_xp=event["before_xp"],
            after_xp=event["after_xp"],
            before_level=before.get("level"),
            after_level=saved.get("level"),
            context=f"run_id={run_id} | sessions={event['sessions']}",
            reason="Yam Yam reviewed the latest run, produced an executive artifact, issued directives, and created memory-worthy cliff notes.",
        )
    return event


def _append_memory_note(run_id: str, review_text: str, dry_run: bool = False) -> None:
    # Keep root Yam Yam memory concise. Full output lives in state/executive_reviews.
    response = _extract_response(review_text)
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    snippets = []
    capture = False
    for line in lines:
        low = line.lower()
        if "memory-worthy" in low or "cliff notes" in low:
            capture = True
            continue
        if capture:
            if len(snippets) >= 3:
                break
            if line.startswith(("-", "1.", "2.", "3.", "•")):
                snippets.append(line.lstrip("-• "))
    if not snippets:
        snippets = ["Completed post-run executive review; see state/executive_reviews for full output."]

    note = [
        "",
        "## Executive review memory",
        f"- {datetime.now(timezone.utc).date().isoformat()} | run {run_id}: " + " ".join(snippets[:3]),
    ]
    if not dry_run:
        MAIN_MEMORY.parent.mkdir(parents=True, exist_ok=True)
        existing = MAIN_MEMORY.read_text(encoding="utf-8", errors="replace") if MAIN_MEMORY.exists() else "# MEMORY\n"
        MAIN_MEMORY.write_text(existing.rstrip() + "\n" + "\n".join(note) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Yam Yam's post-run Master CEO review and award RPG XP.")
    parser.add_argument("--run-id", default=None, help="Specific run id. Defaults to latest run.")
    parser.add_argument("--timeout", type=int, default=420, help="OpenClaw agent timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Build prompt only; do not call agent or update XP.")
    args = parser.parse_args()

    briefing = _ensure_briefing(args.run_id)
    run_id = str(briefing.get("run_id") or args.run_id or "unknown")
    axiom_review = _read_axiom_review(run_id)
    vivienne_review = _read_vivienne_review(run_id)
    ledger_review = _read_ledger_review(run_id)
    helena_review = _read_helena_review(run_id)
    grant_speech = _read_grant_speech(run_id)
    selene_review = _read_selene_review(run_id)
    ariadne_review = _read_ariadne_review(run_id)
    prompt = _build_prompt(
        briefing,
        axiom_review=axiom_review,
        vivienne_review=vivienne_review,
        ledger_review=ledger_review,
        helena_review=helena_review,
        grant_speech=grant_speech,
        selene_review=selene_review,
        ariadne_review=ariadne_review,
    )

    EXEC_REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    prompt_path = EXEC_REVIEW_DIR / f"{run_id}_yam_yam_prompt.txt"
    output_path = EXEC_REVIEW_DIR / f"{run_id}_yam_yam_review.txt"
    event_path = EXEC_REVIEW_DIR / f"{run_id}_yam_yam_rpg_event.json"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        print(f"Dry run. Prompt saved to: {prompt_path}")
        return

    result = _call_openclaw_main(prompt, args.timeout)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    output_path.write_text(output, encoding="utf-8")

    if result.returncode != 0:
        raise SystemExit(f"Yam Yam review failed with exit code {result.returncode}. Output saved to {output_path}")

    event = _update_yam_yam_rpg(run_id, output, dry_run=False)
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _append_memory_note(run_id, output, dry_run=False)

    print(output.strip())
    print()
    print(f"Prompt saved to: {prompt_path}")
    print(f"Review saved to: {output_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"Yam Yam XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")


if __name__ == "__main__":
    main()
