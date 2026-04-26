#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
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

def _read_jsonl(path: Path, limit: int = 10000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    if limit and len(lines) > limit:
        lines = lines[-limit:]
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
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

def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"

def _read_latest_review(folder: Path, run_id: str, suffix: str, limit: int = 1800) -> str:
    candidates = [folder / f"{run_id}_{suffix}.txt"]
    if folder.exists():
        candidates.extend(sorted(folder.glob(f"*_{suffix}.txt"), key=lambda p: p.stat().st_mtime, reverse=True))
    seen: set[Path] = set()
    for p in candidates:
        if p in seen or not p.exists():
            continue
        seen.add(p)
        text = p.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return _clip(text, limit)
    return ""

def _summarize_file_presence(art: Path) -> dict[str, Any]:
    names = [
        "target_state.json", "grant_briefing.json", "portfolio_state.jsonl", "paper_decisions.jsonl",
        "paper_trades.jsonl", "company_packets.jsonl", "ledger_usage.jsonl", "bridge_usage.jsonl",
    ]
    out: dict[str, Any] = {}
    for name in names:
        p = art / name
        out[name] = {"exists": p.exists(), "size": p.stat().st_size if p.exists() else 0}
    return out

def _summarize_decisions(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "paper_decisions.jsonl")
    decisions = Counter(str(r.get("decision") or r.get("final_decision") or "UNKNOWN") for r in rows)
    evidence = Counter(str(r.get("evidence_winner") or "UNKNOWN") for r in rows)
    return {
        "rows": len(rows),
        "decisions": dict(decisions),
        "evidence_winners": dict(evidence),
        "ml_score_rows": sum(1 for r in rows if r.get("ml_signal_score") is not None),
        "trace_rows": sum(1 for r in rows if isinstance(r.get("decision_path_trace"), list) and r.get("decision_path_trace")),
    }

def _summarize_portfolio(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "portfolio_state.jsonl")
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        company = str(row.get("company") or row.get("company_id") or "UNKNOWN")
        latest[company] = row
    return {"rows": len(rows), "coverage": len(latest), "coverage_status": "complete" if len(latest) >= 4 else "partial", "companies": sorted(latest)}

def _summarize_usage(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "ledger_usage.jsonl") + _read_jsonl(art / "bridge_usage.jsonl")
    agents = Counter(str(r.get("agent") or r.get("agent_id") or "UNKNOWN") for r in rows)
    models = Counter(str(r.get("model") or "UNKNOWN") for r in rows)
    total_tokens = 0
    token_rows = 0
    for r in rows:
        try:
            if r.get("total_tokens") is not None:
                total_tokens += int(float(r.get("total_tokens")))
                token_rows += 1
        except Exception:
            pass
    return {"rows": len(rows), "token_rows": token_rows, "total_tokens_known": total_tokens if token_rows else None, "top_agents": dict(agents.most_common(10)), "models": dict(models.most_common(10))}

SELENE_DIR = ROOT / "state" / "selene_reviews"
SELENE_RPG_STATE = ROOT / "ai_agents_memory" / "selene" / "RPG_STATE.md"
SELENE_RPG_HISTORY = ROOT / "ai_agents_memory" / "selene" / "RPG_HISTORY.md"

def _build_context(run_dir: Path) -> dict[str, Any]:
    art = run_dir / "artifacts"
    run_id = run_dir.name
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "target_state": _read_json(art / "target_state.json", {}),
        "grant_briefing": _read_json(art / "grant_briefing.json", {}),
        "portfolio_summary": _summarize_portfolio(art),
        "decision_summary": _summarize_decisions(art),
        "ledger_review": _read_latest_review(ROOT / "state" / "ledger_reviews", run_id, "ledger_review", 1800),
        "vivienne_review": _read_latest_review(ROOT / "state" / "vivienne_reviews", run_id, "vivienne_review", 1800),
        "helena_review": _read_latest_review(ROOT / "state" / "helena_reviews", run_id, "helena_review", 1800),
    }

def _build_prompt(context: dict[str, Any]) -> str:
    return f"""
Selene, perform a Master Treasurer treasury review for Autonomous Corp Capital.

This is an actual runtime governance job. Do not give a generic identity answer.
Your job is treasury truth: reserve safety, deployable capital, whether capital allocation is grounded, and whether the system should preserve cash, continue paper mode, or tighten controls.

Run: {context.get('run_id')}

Target state:
{_clip(json.dumps(context.get('target_state'), indent=2), 2600)}

Portfolio summary:
{json.dumps(context.get('portfolio_summary'), indent=2)}

Decision summary:
{json.dumps(context.get('decision_summary'), indent=2)}

Ledger cost review:
{context.get('ledger_review') or 'No Ledger review available.'}

Vivienne financial truth review:
{context.get('vivienne_review') or 'No Vivienne review available.'}

Helena risk review:
{context.get('helena_review') or 'No Helena review available.'}

Required output:
1. Treasury verdict: one paragraph.
2. Reserve/deployable truth: 3-5 bullets.
3. Capital allocation concerns: 3-5 bullets.
4. Conditions before any serious paper proof or future live money: 3-5 bullets.
5. Memory-worthy treasury lessons: 3 bullets max.

Be conservative. Never recommend live money unless paper proof and safeguards are real.
""".strip()

def _call_agent(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_resolve_openclaw_bin(), "agent", "--agent", "selene", "--message", prompt], text=True, capture_output=True, timeout=timeout)

def _update_rpg(run_id: str) -> dict[str, Any]:
    before = load_rpg_state(SELENE_RPG_STATE)
    after = update_xp(before, 7.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["accuracy"] = min(100.0, float(after.get("accuracy") or 0.0) + 1.0)
    after["judgment"] = min(100.0, float(after.get("judgment") or 0.0) + 2.0)
    after["reliability"] = min(100.0, float(after.get("reliability") or 0.0) + 1.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 2.0)
    saved = save_rpg_state(SELENE_RPG_STATE, after)
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), "agent_id": "selene", "event": "treasury_review", "run_id": run_id, "xp_delta": 7.0, "before_xp": float(before.get("xp") or 0.0), "after_xp": float(saved.get("xp") or 0.0), "sessions": int(saved.get("sessions") or 0)}
    append_human_rpg_history(SELENE_RPG_HISTORY, timestamp=event["timestamp"], agent_id="selene", event_type="Treasury Review", xp_delta=event["xp_delta"], before_xp=event["before_xp"], after_xp=event["after_xp"], before_level=before.get("level"), after_level=saved.get("level"), context=f"run_id={run_id} | sessions={event['sessions']}", reason="Selene reviewed reserve safety, deployable capital, and treasury conditions for paper proof and future live-money discipline.")
    return event

def _append_memory(run_id: str, text: str) -> None:
    if append_memory_notes is None:
        return
    notes: list[str] = []
    capture = False
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•1234567890. ")
        low = line.lower()
        if "memory-worthy" in low or "treasury lessons" in low:
            capture = True
            continue
        if capture and line:
            notes.append(line)
            if len(notes) >= 3:
                break
    if not notes:
        notes = [f"Completed treasury review for {run_id}; see state/selene_reviews for reserve and deployable capital guidance."]
    append_memory_notes(["selene"], notes, section="Treasury lessons", source=f"selene:{run_id}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Run Selene's Master Treasurer review.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_dir = _run_dir_from_id(args.run_id)
    if run_dir is None:
        raise SystemExit(f"No run folders found under {RUNS_DIR}")
    context = _build_context(run_dir)
    run_id = str(context.get("run_id"))
    prompt = _build_prompt(context)
    SELENE_DIR.mkdir(parents=True, exist_ok=True)
    context_path = SELENE_DIR / f"{run_id}_selene_context.json"
    prompt_path = SELENE_DIR / f"{run_id}_selene_prompt.txt"
    review_path = SELENE_DIR / f"{run_id}_selene_review.txt"
    event_path = SELENE_DIR / f"{run_id}_selene_rpg_event.json"
    context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    if args.dry_run:
        print(f"Dry run. Context saved to: {context_path}")
        print(f"Dry run. Prompt saved to: {prompt_path}")
        return
    result = _call_agent(prompt, args.timeout)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    review_path.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Selene review failed with exit code {result.returncode}. Output saved to {review_path}")
    event = _update_rpg(run_id)
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _append_memory(run_id, output)
    print(output.strip())
    print()
    print(f"Context saved to: {context_path}")
    print(f"Prompt saved to: {prompt_path}")
    print(f"Review saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"Selene XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")

if __name__ == "__main__":
    main()
