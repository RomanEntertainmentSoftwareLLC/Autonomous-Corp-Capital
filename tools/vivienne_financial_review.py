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
VIVIENNE_DIR = ROOT / "state" / "vivienne_reviews"
VIVIENNE_RPG_STATE = ROOT / "ai_agents_memory" / "vivienne" / "RPG_STATE.md"
VIVIENNE_RPG_HISTORY = ROOT / "ai_agents_memory" / "vivienne" / "RPG_HISTORY.md"


def _latest_run_dir() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    runs = [p for p in RUNS_DIR.glob("run_*") if p.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def _run_dir_from_id(run_id: str | None) -> Path | None:
    if run_id:
        return RUNS_DIR / run_id
    return _latest_run_dir()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl(path: Path, limit: int = 5000) -> list[dict[str, Any]]:
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


def _clip(value: Any, limit: int = 1200) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"


def _summarize_portfolio(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "portfolio_state.jsonl")
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        company = str(row.get("company") or row.get("company_id") or "UNKNOWN")
        latest[company] = row

    company_summary: dict[str, Any] = {}
    deployable_equity = 0.0
    deployable_known = 0
    for company, row in sorted(latest.items()):
        equity = _num(row.get("equity") or row.get("total_equity"))
        cash = _num(row.get("cash"))
        realized = _num(row.get("realized_pnl"), 0.0)
        unrealized = _num(row.get("unrealized_pnl"), 0.0)
        inferred_equity = equity if equity is not None else ((cash or 0.0) + (unrealized or 0.0))
        if inferred_equity is not None:
            deployable_equity += float(inferred_equity)
            deployable_known += 1
        company_summary[company] = {
            "cash": cash,
            "equity": equity,
            "inferred_equity": inferred_equity,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "open_positions_count": row.get("open_positions_count"),
        }
    return {
        "rows": len(rows),
        "coverage": len(latest),
        "expected_companies": 4,
        "coverage_status": "complete" if len(latest) >= 4 else "partial",
        "deployable_equity_estimate": round(deployable_equity, 8) if deployable_known else None,
        "latest_by_company": company_summary,
    }


def _summarize_decisions(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "paper_decisions.jsonl")
    decisions = Counter(str(r.get("decision") or r.get("final_decision") or "UNKNOWN") for r in rows)
    execution = Counter(str(r.get("execution_state") or "UNKNOWN") for r in rows)
    evidence = Counter(str(r.get("evidence_winner") or "UNKNOWN") for r in rows)
    ml_scores = sum(1 for r in rows if r.get("ml_signal_score") is not None)
    trace_rows = sum(1 for r in rows if isinstance(r.get("decision_path_trace"), list) and r.get("decision_path_trace"))
    return {
        "rows": len(rows),
        "decisions": dict(decisions),
        "execution": dict(execution),
        "evidence_winners": dict(evidence),
        "ml_score_rows": ml_scores,
        "decision_trace_rows": trace_rows,
    }


def _summarize_trades(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "paper_trades.jsonl")
    sides = Counter(str(r.get("side") or r.get("decision") or "UNKNOWN") for r in rows)
    companies = Counter(str(r.get("company") or r.get("company_id") or "UNKNOWN") for r in rows)
    symbols = Counter(str(r.get("symbol") or "UNKNOWN") for r in rows)
    return {"rows": len(rows), "sides": dict(sides), "companies": dict(companies), "symbols": dict(symbols.most_common(10))}


def _build_context(run_dir: Path) -> dict[str, Any]:
    art = run_dir / "artifacts"
    target_state = _read_json(art / "target_state.json", {})
    grant_briefing = _read_json(art / "grant_briefing.json", {})
    portfolio = _summarize_portfolio(art)
    decisions = _summarize_decisions(art)
    trades = _summarize_trades(art)

    flags: list[str] = []
    if portfolio.get("coverage_status") != "complete":
        flags.append(f"partial_portfolio_coverage_{portfolio.get('coverage')}_of_4")
    target_status = str((target_state.get("total") or {}).get("status") or target_state.get("target_status") or "unknown")
    if "negative" in target_status or "unknown" in target_status:
        flags.append(f"target_status_{target_status}")
    if decisions.get("rows") and not decisions.get("decision_trace_rows"):
        flags.append("decisions_missing_trace")
    if decisions.get("rows") and not decisions.get("ml_score_rows"):
        flags.append("ml_scores_missing_from_decisions")

    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "target_state": target_state,
        "grant_briefing_summary": {
            "recommended_speech_type": grant_briefing.get("recommended_speech_type"),
            "target_status": ((grant_briefing.get("target_state") or {}).get("target_status")),
            "current_equity_estimate": ((grant_briefing.get("target_state") or {}).get("current_equity_estimate")),
            "total_pnl_estimate": ((grant_briefing.get("target_state") or {}).get("total_pnl_estimate")),
            "leader": ((grant_briefing.get("company_scoreboard") or {}).get("leader")),
            "laggard": ((grant_briefing.get("company_scoreboard") or {}).get("laggard")),
        },
        "portfolio_summary": portfolio,
        "decision_summary": decisions,
        "trade_summary": trades,
        "financial_flags": flags,
    }


def _build_prompt(context: dict[str, Any]) -> str:
    return f"""
Vivienne, perform a Master CFO financial truth review for Autonomous Corp Capital.

This is an actual runtime governance job. Do not give a generic identity answer.
Use only the facts below. Your job is to tell the truth about money, coverage, targets, accounting, fake losses, fake profits, and whether Grant/Yam Yam should trust the run numbers.

Run: {context.get('run_id')}

Financial flags:
{json.dumps(context.get('financial_flags'), indent=2)}

Target state:
{_clip(json.dumps(context.get('target_state'), indent=2), 2800)}

Grant briefing summary:
{json.dumps(context.get('grant_briefing_summary'), indent=2)}

Portfolio summary:
{_clip(json.dumps(context.get('portfolio_summary'), indent=2), 2400)}

Decision summary:
{json.dumps(context.get('decision_summary'), indent=2)}

Trade summary:
{json.dumps(context.get('trade_summary'), indent=2)}

Required output:
1. Financial verdict: one paragraph.
2. Accounting truth: 3-5 bullets.
3. Profit/loss confidence: say trusted, partial, or untrusted and why.
4. Issues Yam Yam must know: 3-5 bullets.
5. Memory-worthy finance lessons: 3 bullets max.

Be concise, skeptical, and financially ruthless. Do not hype tiny gains. Do not treat missing coverage as real loss unless the artifacts prove it.
""".strip()


def _call_vivienne(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_resolve_openclaw_bin(), "agent", "--agent", "vivienne", "--message", prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _update_rpg(run_id: str, dry_run: bool = False) -> dict[str, Any]:
    before = load_rpg_state(VIVIENNE_RPG_STATE)
    after = update_xp(before, 7.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["accuracy"] = min(100.0, float(after.get("accuracy") or 0.0) + 1.0)
    after["judgment"] = min(100.0, float(after.get("judgment") or 0.0) + 2.0)
    after["reliability"] = min(100.0, float(after.get("reliability") or 0.0) + 1.0)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 2.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 2.0)
    saved = after if dry_run else save_rpg_state(VIVIENNE_RPG_STATE, after)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "vivienne",
        "event": "vivienne_financial_truth_review",
        "run_id": run_id,
        "xp_delta": 7.0,
        "before_xp": float(before.get("xp") or 0.0),
        "after_xp": float(saved.get("xp") or 0.0),
        "sessions": int(saved.get("sessions") or 0),
    }
    if not dry_run:
        append_human_rpg_history(
            VIVIENNE_RPG_HISTORY,
            timestamp=event["timestamp"],
            agent_id="vivienne",
            event_type="Financial Truth Review",
            xp_delta=event["xp_delta"],
            before_xp=event["before_xp"],
            after_xp=event["after_xp"],
            before_level=before.get("level"),
            after_level=saved.get("level"),
            context=f"run_id={run_id} | sessions={event['sessions']}",
            reason="Vivienne reviewed run accounting, target trustworthiness, portfolio coverage, and profit/loss confidence for executive governance.",
        )
    return event


def _append_memory(run_id: str, review_text: str) -> None:
    if append_memory_notes is None:
        return
    lines = [line.strip().lstrip("-•1234567890. ") for line in review_text.splitlines() if line.strip()]
    notes = []
    capture = False
    for line in lines:
        low = line.lower()
        if "memory-worthy" in low or "finance lessons" in low:
            capture = True
            continue
        if capture and line:
            notes.append(line)
            if len(notes) >= 3:
                break
    if not notes:
        notes = [f"Completed financial truth review for {run_id}; see state/vivienne_reviews for details."]
    append_memory_notes(["vivienne"], notes, section="Financial truth lessons", source=f"vivienne:{run_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Vivienne's Master CFO financial truth review and award RPG XP.")
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

    VIVIENNE_DIR.mkdir(parents=True, exist_ok=True)
    context_path = VIVIENNE_DIR / f"{run_id}_vivienne_context.json"
    prompt_path = VIVIENNE_DIR / f"{run_id}_vivienne_prompt.txt"
    review_path = VIVIENNE_DIR / f"{run_id}_vivienne_review.txt"
    event_path = VIVIENNE_DIR / f"{run_id}_vivienne_rpg_event.json"
    context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        print(f"Dry run. Context saved to: {context_path}")
        print(f"Dry run. Prompt saved to: {prompt_path}")
        return

    result = _call_vivienne(prompt, args.timeout)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    review_path.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Vivienne review failed with exit code {result.returncode}. Output saved to {review_path}")

    event = _update_rpg(run_id, dry_run=False)
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _append_memory(run_id, output)

    print(output.strip())
    print()
    print(f"Context saved to: {context_path}")
    print(f"Prompt saved to: {prompt_path}")
    print(f"Review saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"Vivienne XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")


if __name__ == "__main__":
    main()
