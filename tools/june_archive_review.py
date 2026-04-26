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

JUNE_AGENT = os.getenv("JUNE_ARCHIVE_AGENT", "june_company_001")
JUNE_DIR = ROOT / "state" / "board_archives"
JUNE_RPG_STATE = ROOT / "ai_agents_memory" / JUNE_AGENT / "RPG_STATE.md"
JUNE_RPG_HISTORY = ROOT / "ai_agents_memory" / JUNE_AGENT / "RPG_HISTORY.md"
REVIEW_SOURCES = {
    "ledger": (ROOT / "state" / "ledger_reviews", "ledger_review"),
    "helena": (ROOT / "state" / "helena_reviews", "helena_review"),
    "axiom": (ROOT / "state" / "axiom_reviews", "axiom_review"),
    "vivienne": (ROOT / "state" / "vivienne_reviews", "vivienne_review"),
    "selene": (ROOT / "state" / "selene_reviews", "selene_review"),
    "ariadne": (ROOT / "state" / "ariadne_reviews", "ariadne_review"),
    "grant": (ROOT / "state" / "grant_speeches", "grant_speech"),
    "yam_yam": (ROOT / "state" / "executive_reviews", "yam_yam_review"),
}

def _build_context(run_dir: Path) -> dict[str, Any]:
    art = run_dir / "artifacts"
    run_id = run_dir.name
    reviews = {name: _read_latest_review(folder, run_id, suffix, 1500) for name, (folder, suffix) in REVIEW_SOURCES.items()}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "file_presence": _summarize_file_presence(art),
        "portfolio_summary": _summarize_portfolio(art),
        "decision_summary": _summarize_decisions(art),
        "reviews": reviews,
    }

def _build_prompt(context: dict[str, Any]) -> str:
    return f"""
June, perform an archivist board packet summary for Autonomous Corp Capital.

This is an actual runtime archive job. Do not give a generic identity answer.
Your job is to preserve the governance record: what happened, who reviewed it, what the unresolved action items are, and what should be easy to find later.

Run: {context.get('run_id')}

File presence:
{json.dumps(context.get('file_presence'), indent=2)}

Portfolio summary:
{json.dumps(context.get('portfolio_summary'), indent=2)}

Decision summary:
{json.dumps(context.get('decision_summary'), indent=2)}

Governance reviews packet:
{_clip(json.dumps(context.get('reviews'), indent=2), 6400)}

Required output:
1. Archive verdict: one paragraph.
2. Board packet summary: 5-8 bullets.
3. Open action items: 5-10 bullets.
4. Evidence gaps to preserve for next run: 3-6 bullets.
5. Memory-worthy archive lessons: 3 bullets max.

Be concise and archival. Preserve facts, not hype.
""".strip()

def _call_agent(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_resolve_openclaw_bin(), "agent", "--agent", JUNE_AGENT, "--message", prompt], text=True, capture_output=True, timeout=timeout)

def _update_rpg(run_id: str) -> dict[str, Any]:
    before = load_rpg_state(JUNE_RPG_STATE)
    after = update_xp(before, 5.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["reliability"] = min(100.0, float(after.get("reliability") or 0.0) + 1.0)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 1.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 2.0)
    saved = save_rpg_state(JUNE_RPG_STATE, after)
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), "agent_id": JUNE_AGENT, "event": "board_archive", "run_id": run_id, "xp_delta": 5.0, "before_xp": float(before.get("xp") or 0.0), "after_xp": float(saved.get("xp") or 0.0), "sessions": int(saved.get("sessions") or 0)}
    append_human_rpg_history(JUNE_RPG_HISTORY, timestamp=event["timestamp"], agent_id=JUNE_AGENT, event_type="Board Archive", xp_delta=event["xp_delta"], before_xp=event["before_xp"], after_xp=event["after_xp"], before_level=before.get("level"), after_level=saved.get("level"), context=f"run_id={run_id} | sessions={event['sessions']}", reason="June archived the governance packet, open action items, and evidence gaps for later review.")
    return event

def _append_memory(run_id: str, text: str) -> None:
    if append_memory_notes is None:
        return
    notes: list[str] = []
    capture = False
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•1234567890. ")
        low = line.lower()
        if "memory-worthy" in low or "archive lessons" in low:
            capture = True
            continue
        if capture and line:
            notes.append(line)
            if len(notes) >= 3:
                break
    if not notes:
        notes = [f"Archived board packet for {run_id}; see state/board_archives for details."]
    append_memory_notes([JUNE_AGENT], notes, section="Archive lessons", source=f"june:{run_id}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Run June's governance archive summary.")
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
    JUNE_DIR.mkdir(parents=True, exist_ok=True)
    context_path = JUNE_DIR / f"{run_id}_june_context.json"
    prompt_path = JUNE_DIR / f"{run_id}_june_prompt.txt"
    review_path = JUNE_DIR / f"{run_id}_june_archive.txt"
    event_path = JUNE_DIR / f"{run_id}_june_rpg_event.json"
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
        raise SystemExit(f"June archive failed with exit code {result.returncode}. Output saved to {review_path}")
    event = _update_rpg(run_id)
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _append_memory(run_id, output)
    print(output.strip())
    print()
    print(f"Context saved to: {context_path}")
    print(f"Prompt saved to: {prompt_path}")
    print(f"Archive saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"{JUNE_AGENT} XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")

if __name__ == "__main__":
    main()
