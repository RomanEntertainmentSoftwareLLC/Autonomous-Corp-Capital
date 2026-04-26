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
HELENA_DIR = ROOT / "state" / "helena_reviews"
HELENA_RPG_STATE = ROOT / "ai_agents_memory" / "helena" / "RPG_STATE.md"
HELENA_RPG_HISTORY = ROOT / "ai_agents_memory" / "helena" / "RPG_HISTORY.md"


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
        try:
            obj = json.loads(line.strip())
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _clip(value: Any, limit: int = 2400) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"


def _summarize_decisions(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "paper_decisions.jsonl")
    decisions = Counter(str(r.get("decision") or r.get("final_decision") or "UNKNOWN") for r in rows)
    execution = Counter(str(r.get("execution_state") or "UNKNOWN") for r in rows)
    wait_reasons = Counter(str(r.get("reason") or r.get("skip_reason") or r.get("evidence_reason") or "UNKNOWN") for r in rows)
    low_margin = 0
    pattern_demotions = 0
    bootstrap_recoveries = 0
    risk_blocks = 0
    for row in rows:
        try:
            margin = row.get("evidence_margin")
            if margin is not None and float(margin) < 0.15:
                low_margin += 1
        except Exception:
            pass
        trace = row.get("decision_path_trace") or []
        if isinstance(trace, list):
            for item in trace:
                if not isinstance(item, dict):
                    continue
                stage = str(item.get("stage") or "")
                blob = json.dumps(item, default=str).lower()
                if "pattern" in stage and ("demot" in blob or "blocked" in blob):
                    pattern_demotions += 1
                if "bootstrap" in stage and (item.get("triggered") or "re-promot" in blob or "recovery" in blob):
                    bootstrap_recoveries += 1
                if "risk" in stage and (item.get("triggered") or "block" in blob or "veto" in blob):
                    risk_blocks += 1
    return {
        "rows": len(rows),
        "decisions": dict(decisions),
        "execution": dict(execution),
        "top_wait_or_skip_reasons": dict(wait_reasons.most_common(8)),
        "low_margin_rows": low_margin,
        "pattern_demotions_estimate": pattern_demotions,
        "bootstrap_recoveries_estimate": bootstrap_recoveries,
        "risk_blocks_estimate": risk_blocks,
    }


def _summarize_portfolio(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "portfolio_state.jsonl")
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        company = str(row.get("company") or row.get("company_id") or "UNKNOWN")
        latest[company] = row
    companies: dict[str, Any] = {}
    for company, row in sorted(latest.items()):
        equity = _num(row.get("equity") or row.get("total_equity"))
        cash = _num(row.get("cash"))
        unrealized = _num(row.get("unrealized_pnl"), 0.0)
        realized = _num(row.get("realized_pnl"), 0.0)
        companies[company] = {
            "equity": equity,
            "cash": cash,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "open_positions_count": row.get("open_positions_count"),
        }
    return {"rows": len(rows), "coverage": len(latest), "latest_by_company": companies}


def _build_context(run_dir: Path) -> dict[str, Any]:
    art = run_dir / "artifacts"
    target = _read_json(art / "target_state.json", {})
    portfolio = _summarize_portfolio(art)
    decisions = _summarize_decisions(art)
    risk_flags: list[str] = []
    status = str((target.get("total") or {}).get("status") or target.get("target_status") or "unknown")
    if "negative" in status:
        risk_flags.append("negative_target_status")
    if portfolio.get("coverage", 0) < 4:
        risk_flags.append("partial_portfolio_coverage")
    if decisions.get("bootstrap_recoveries_estimate", 0) > 0:
        risk_flags.append("bootstrap_recovery_used")
    if decisions.get("low_margin_rows", 0) > 0:
        risk_flags.append("low_evidence_margin_decisions")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "target_state": target,
        "portfolio_summary": portfolio,
        "decision_risk_summary": decisions,
        "trade_summary": {
            "rows": len(_read_jsonl(art / "paper_trades.jsonl")),
        },
        "risk_flags": risk_flags,
    }


def _build_prompt(context: dict[str, Any]) -> str:
    return f"""
Helena, perform an ACC risk review.

This is an actual runtime governance job. Your job is to review drawdown risk, exposure risk, risky decision behavior, weak evidence margins, bootstrap recovery risk, and whether the next paper proof should tighten rules.

Rules:
- Use only the facts below.
- Do not invent portfolio losses or gains.
- Be concise and protective.
- Recommend specific risk controls, not generic safety talk.

Context:
{_clip(json.dumps(context, indent=2, sort_keys=True, default=str), 7000)}

Required output:
1. Risk verdict: one paragraph.
2. Risk flags: 3-5 bullets.
3. Decision-risk findings: 3-5 bullets.
4. Required controls before paper proof: 3-5 bullets.
5. Memory-worthy risk lessons: 3 bullets max.
""".strip()


def _call_helena(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_resolve_openclaw_bin(), "agent", "--agent", "helena", "--message", prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _extract_notes(text: str) -> list[str]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    notes: list[str] = []
    capture = False
    for line in lines:
        low = line.lower()
        if "memory-worthy" in low or "risk lessons" in low:
            capture = True
            continue
        if capture and line.startswith(("-", "•", "1.", "2.", "3.")):
            cleaned = re.sub(r"^[-•\s]*", "", line)
            cleaned = re.sub(r"^\d+\.\s*", "", cleaned).strip()
            if cleaned:
                notes.append(cleaned)
            if len(notes) >= 3:
                break
    return notes[:3] or ["Completed risk review; see state/helena_reviews for details."]


def _update_rpg(run_id: str, dry_run: bool = False) -> dict[str, Any]:
    before = load_rpg_state(HELENA_RPG_STATE)
    after = update_xp(before, 7.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["accuracy"] = min(100.0, float(after.get("accuracy") or 0.0) + 1.0)
    after["judgment"] = min(100.0, float(after.get("judgment") or 0.0) + 3.0)
    after["reliability"] = min(100.0, float(after.get("reliability") or 0.0) + 2.0)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 2.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 2.0)
    saved = after if dry_run else save_rpg_state(HELENA_RPG_STATE, after)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "helena",
        "event": "helena_risk_review",
        "run_id": run_id,
        "xp_delta": 7.0,
        "before_xp": float(before.get("xp") or 0.0),
        "after_xp": float(saved.get("xp") or 0.0),
        "sessions": int(saved.get("sessions") or 0),
    }
    if not dry_run:
        append_human_rpg_history(
            HELENA_RPG_HISTORY,
            timestamp=event["timestamp"],
            agent_id="helena",
            event_type="Risk Review",
            xp_delta=event["xp_delta"],
            before_xp=event["before_xp"],
            after_xp=event["after_xp"],
            before_level=before.get("level"),
            after_level=saved.get("level"),
            context=f"run_id={run_id} | sessions={event['sessions']}",
            reason="Helena reviewed drawdown risk, exposure, weak decision margins, bootstrap recovery behavior, and paper-proof risk controls.",
        )
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Helena risk review and award RPG XP.")
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

    HELENA_DIR.mkdir(parents=True, exist_ok=True)
    context_path = HELENA_DIR / f"{run_id}_helena_context.json"
    prompt_path = HELENA_DIR / f"{run_id}_helena_prompt.txt"
    review_path = HELENA_DIR / f"{run_id}_helena_review.txt"
    event_path = HELENA_DIR / f"{run_id}_helena_rpg_event.json"
    context_path.write_text(json.dumps(context, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        print(f"Dry run. Context saved to: {context_path}")
        print(f"Dry run. Prompt saved to: {prompt_path}")
        return

    result = _call_helena(prompt, args.timeout)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    review_path.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Helena review failed with exit code {result.returncode}. Output saved to {review_path}")

    event = _update_rpg(run_id, dry_run=False)
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if append_memory_notes is not None:
        append_memory_notes(["helena"], _extract_notes(output), section="Risk lessons", source=f"helena:{run_id}")

    print(output.strip())
    print()
    print(f"Context saved to: {context_path}")
    print(f"Prompt saved to: {prompt_path}")
    print(f"Review saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"Helena XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")


if __name__ == "__main__":
    main()
