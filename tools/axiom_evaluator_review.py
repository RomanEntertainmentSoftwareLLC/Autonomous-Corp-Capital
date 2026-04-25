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
except Exception:  # pragma: no cover - fallback for partial installs
    append_memory_notes = None  # type: ignore

RUNS_DIR = ROOT / "state" / "live_runs"
AXIOM_DIR = ROOT / "state" / "axiom_reviews"
AXIOM_RPG_STATE = ROOT / "ai_agents_memory" / "axiom" / "RPG_STATE.md"
AXIOM_RPG_HISTORY = ROOT / "ai_agents_memory" / "axiom" / "RPG_HISTORY.md"
AXIOM_MEMORY = ROOT / "ai_agents_memory" / "axiom" / "MEMORY.md"


def _latest_run_dir() -> Path | None:
    if not RUNS_DIR.exists():
        return None
    runs = [p for p in RUNS_DIR.glob("run_*") if p.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def _run_dir_from_id(run_id: str | None) -> Path | None:
    if run_id:
        p = RUNS_DIR / run_id
        return p if p.exists() else p
    return _latest_run_dir()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl(path: Path, limit: int = 2000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return rows
    # For large runs, summarize the tail because it is most relevant to final state.
    if limit and len(lines) > limit:
        lines = lines[-limit:]
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


def _clip(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"


def _counter_text(counter: Counter, max_items: int = 8) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in counter.most_common(max_items))


def _summarize_decisions(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "paper_decisions.jsonl")
    decisions = Counter(str(r.get("decision") or r.get("final_decision") or "UNKNOWN") for r in rows)
    execution = Counter(str(r.get("execution_state") or "UNKNOWN") for r in rows)
    evidence_winners = Counter(str(r.get("evidence_winner") or "UNKNOWN") for r in rows)
    stages = Counter()
    stage_actions = Counter()
    trace_rows = 0
    ml_scores = 0
    ml_missing = 0
    margins: list[float] = []
    for r in rows:
        if r.get("ml_signal_score") is None:
            ml_missing += 1
        else:
            ml_scores += 1
        try:
            margin = r.get("evidence_margin")
            if margin is not None:
                margins.append(float(margin))
        except Exception:
            pass
        trace = r.get("decision_path_trace") or r.get("decision_trace") or []
        if isinstance(trace, list) and trace:
            trace_rows += 1
            for item in trace:
                if not isinstance(item, dict):
                    continue
                stage = str(item.get("stage") or "unknown")
                stages[stage] += 1
                if item.get("changed_decision") or item.get("triggered") or item.get("applied"):
                    stage_actions[stage] += 1
    avg_margin = round(sum(margins) / len(margins), 4) if margins else None
    return {
        "rows": len(rows),
        "decisions": dict(decisions),
        "execution": dict(execution),
        "evidence_winners": dict(evidence_winners),
        "trace_rows": trace_rows,
        "trace_stage_counts": dict(stages),
        "trace_action_counts": dict(stage_actions),
        "ml_scores_present": ml_scores,
        "ml_scores_missing": ml_missing,
        "avg_evidence_margin": avg_margin,
    }


def _summarize_packets(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "company_packets.jsonl")
    modes = Counter(str(r.get("packet_generation_mode") or "UNKNOWN") for r in rows)
    fresh = Counter(str(r.get("fresh_committee") or "UNKNOWN") for r in rows)
    fallback = Counter(str(r.get("fallback_reason") or "None") for r in rows)
    roles_len = Counter(len(r.get("live_roles_responded") or []) for r in rows)
    companies = Counter(str(r.get("company_id") or r.get("company") or "UNKNOWN") for r in rows)
    return {
        "rows": len(rows),
        "modes": dict(modes),
        "fresh_committee": dict(fresh),
        "fallback_reasons": dict(fallback),
        "live_roles_lengths": dict(roles_len),
        "companies": dict(companies),
    }


def _summarize_trades(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "paper_trades.jsonl")
    sides = Counter(str(r.get("side") or r.get("decision") or "UNKNOWN") for r in rows)
    symbols = Counter(str(r.get("symbol") or "UNKNOWN") for r in rows)
    companies = Counter(str(r.get("company") or r.get("company_id") or "UNKNOWN") for r in rows)
    return {"rows": len(rows), "sides": dict(sides), "symbols": dict(symbols.most_common(8)), "companies": dict(companies)}


def _summarize_portfolio(art: Path) -> dict[str, Any]:
    rows = _read_jsonl(art / "portfolio_state.jsonl")
    latest_by_company: dict[str, dict[str, Any]] = {}
    for r in rows:
        company = str(r.get("company") or r.get("company_id") or "UNKNOWN")
        latest_by_company[company] = r
    compact: dict[str, Any] = {}
    for company, r in sorted(latest_by_company.items()):
        compact[company] = {
            "cash": r.get("cash"),
            "equity": r.get("equity") or r.get("total_equity"),
            "realized_pnl": r.get("realized_pnl"),
            "unrealized_pnl": r.get("unrealized_pnl"),
            "open_positions_count": r.get("open_positions_count"),
        }
    return {"rows": len(rows), "coverage": len(latest_by_company), "latest_by_company": compact}


def _summarize_usage(art: Path) -> dict[str, Any]:
    ledger = _read_jsonl(art / "ledger_usage.jsonl")
    bridge = _read_jsonl(art / "bridge_usage.jsonl")
    outcomes = Counter(str(r.get("outcome") or "UNKNOWN") for r in ledger + bridge)
    agents = Counter(str(r.get("agent") or "UNKNOWN") for r in ledger + bridge)
    total_tokens = 0
    token_rows = 0
    for r in ledger + bridge:
        value = r.get("total_tokens")
        if value is not None:
            try:
                total_tokens += int(value)
                token_rows += 1
            except Exception:
                pass
    return {
        "ledger_rows": len(ledger),
        "bridge_rows": len(bridge),
        "outcomes": dict(outcomes),
        "top_agents": dict(agents.most_common(10)),
        "token_rows": token_rows,
        "total_tokens_known": total_tokens if token_rows else None,
    }


def _summarize_stats() -> dict[str, Any]:
    try:
        from tools.agent_stats_report import build_rows
        rows = build_rows()
    except Exception:
        return {"available": False}
    zero = [r for r in rows if float(r.get("xp") or 0.0) <= 0]
    active = [r for r in rows if float(r.get("sessions") or 0.0) > 0]
    top = sorted(rows, key=lambda r: (-float(r.get("xp") or 0.0), -float(r.get("sessions") or 0.0), str(r.get("agent"))))[:10]
    master_ids = {"main", "selene", "helena", "vivienne", "ariadne", "ledger", "axiom", "grant_cardone"}
    master = [r for r in rows if r.get("agent") in master_ids]
    return {
        "available": True,
        "total_agents": len(rows),
        "zero_xp_count": len(zero),
        "active_count": len(active),
        "top_agents": [
            {
                "agent": r.get("agent"),
                "xp": r.get("xp"),
                "sessions": r.get("sessions"),
                "usefulness": r.get("usefulness"),
                "judgment": r.get("judgment"),
                "evidence_quality": r.get("evidence_quality"),
                "rpg_exists": r.get("rpg_exists"),
                "history_exists": r.get("history_exists"),
            }
            for r in top
        ],
        "master_agents": [
            {
                "agent": r.get("agent"),
                "xp": r.get("xp"),
                "sessions": r.get("sessions"),
                "rpg_exists": r.get("rpg_exists"),
                "history_exists": r.get("history_exists"),
            }
            for r in master
        ],
    }


def _build_context(run_dir: Path | None) -> dict[str, Any]:
    art = run_dir / "artifacts" if run_dir else None
    target = _read_json(art / "target_state.json", {}) if art else {}
    grant = _read_json(art / "grant_briefing.json", {}) if art else _read_json(ROOT / "state" / "grant" / "latest_grant_briefing.json", {})
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name if run_dir else "no_run_found",
        "run_dir": str(run_dir) if run_dir else None,
        "target_state": target,
        "grant_briefing_summary": {
            "recommended_speech_type": grant.get("recommended_speech_type"),
            "market": grant.get("market"),
            "target_state": grant.get("target_state"),
            "committee_health": grant.get("committee_health"),
            "review_flags": grant.get("review_flags"),
        },
        "decision_summary": _summarize_decisions(art) if art else {},
        "packet_summary": _summarize_packets(art) if art else {},
        "trade_summary": _summarize_trades(art) if art else {},
        "portfolio_summary": _summarize_portfolio(art) if art else {},
        "usage_summary": _summarize_usage(art) if art else {},
        "agent_stats_summary": _summarize_stats(),
    }


def _json_block(obj: Any, limit: int = 5000) -> str:
    text = json.dumps(obj, indent=2, sort_keys=True, default=str)
    return _clip(text, limit)


def _build_prompt(context: dict[str, Any]) -> str:
    return f"""
Axiom, perform an ACC evaluator review.

This is an actual runtime evaluation job, not an identity check. Your job is to judge evidence quality, usefulness, waste, fake productivity, and governance risk from the latest available run/artifacts.

Rules:
- Use only the provided facts.
- Do not invent missing numbers.
- Be concise and operational.
- Recommend rewards/penalties or follow-up reviews, but do not claim you applied them.
- Focus on whether the system is honest enough for the next paper-test gate.

Context summary:
{_json_block(context, 7000)}

Required output:
1. Evaluator verdict: one short paragraph.
2. Evidence quality findings: 3-5 bullets.
3. Agent/workforce findings: 3-5 bullets, including idle or zero-XP concerns if supported.
4. Decision-trace / ML findings: 3-5 bullets.
5. Cost/token discipline findings: 2-4 bullets.
6. Recommended actions before the next paper run: 3-5 bullets.
7. Memory-worthy lessons: 3 bullets max.
""".strip()


def _call_axiom(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    openclaw_bin = _resolve_openclaw_bin()
    return subprocess.run(
        [openclaw_bin, "agent", "--agent", "axiom", "--message", prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _extract_memory_notes(review_text: str) -> list[str]:
    lines = [line.strip() for line in str(review_text or "").splitlines() if line.strip()]
    notes: list[str] = []
    capture = False
    for line in lines:
        low = line.lower()
        if "memory-worthy" in low or "memory worthy" in low or "lessons" in low:
            capture = True
            continue
        if capture:
            if len(notes) >= 3:
                break
            if line.startswith(("-", "•", "1.", "2.", "3.")):
                cleaned = line.lstrip("-• ").strip()
                cleaned = re.sub(r"^\d+\.\s*", "", cleaned).strip()
                if cleaned:
                    notes.append(cleaned)
    if not notes:
        notes = ["Axiom completed an evaluator review; see state/axiom_reviews for full output and recommendations."]
    return notes[:3]


def _fallback_append_memory(notes: list[str], source: str) -> None:
    AXIOM_MEMORY.parent.mkdir(parents=True, exist_ok=True)
    if AXIOM_MEMORY.exists():
        text = AXIOM_MEMORY.read_text(encoding="utf-8", errors="replace")
    else:
        text = "# MEMORY.md\n\n_Agent-local durable memory._\n\n"
    date = datetime.now(timezone.utc).date().isoformat()
    block = "\n## Evaluation lessons\n" + "\n".join(f"- {date}: [{source}] {n}" for n in notes) + "\n"
    AXIOM_MEMORY.write_text(text.rstrip() + "\n" + block, encoding="utf-8")


def _update_axiom_rpg(run_id: str, dry_run: bool = False) -> dict[str, Any]:
    before = load_rpg_state(AXIOM_RPG_STATE)
    after = update_xp(before, 7.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["judgment"] = min(100.0, float(after.get("judgment") or 0.0) + 2.0)
    after["reliability"] = min(100.0, float(after.get("reliability") or 0.0) + 1.0)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 2.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 3.0)
    after["cost_efficiency"] = min(100.0, float(after.get("cost_efficiency") or 0.0) + 1.0)
    saved = after if dry_run else save_rpg_state(AXIOM_RPG_STATE, after)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "axiom",
        "role": "Evaluator / AI Consultant",
        "event": "axiom_evaluator_review",
        "run_id": run_id,
        "xp_delta": 7.0,
        "before_xp": float(before.get("xp") or 0.0),
        "after_xp": float(saved.get("xp") or 0.0),
        "sessions": int(saved.get("sessions") or 0),
    }
    if not dry_run:
        append_human_rpg_history(
            AXIOM_RPG_HISTORY,
            timestamp=event["timestamp"],
            agent_id="axiom",
            event_type="Evaluator Review",
            xp_delta=event["xp_delta"],
            before_xp=event["before_xp"],
            after_xp=event["after_xp"],
            before_level=before.get("level"),
            after_level=saved.get("level"),
            context=f"run_id={run_id} | sessions={event['sessions']}",
            reason="Axiom evaluated ACC run evidence, agent usefulness, token discipline, ML/decision trace readiness, and recommended next controls.",
        )
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Axiom evaluator review and award RPG XP.")
    parser.add_argument("--run-id", default=None, help="Specific run id. Defaults to latest run.")
    parser.add_argument("--timeout", type=int, default=420, help="OpenClaw agent timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Build prompt/context only; do not call agent or update XP.")
    args = parser.parse_args()

    run_dir = _run_dir_from_id(args.run_id)
    context = _build_context(run_dir)
    run_id = str(context.get("run_id") or args.run_id or "no_run_found")
    prompt = _build_prompt(context)

    AXIOM_DIR.mkdir(parents=True, exist_ok=True)
    context_path = AXIOM_DIR / f"{run_id}_axiom_context.json"
    prompt_path = AXIOM_DIR / f"{run_id}_axiom_prompt.txt"
    review_path = AXIOM_DIR / f"{run_id}_axiom_review.txt"
    event_path = AXIOM_DIR / f"{run_id}_axiom_rpg_event.json"

    context_path.write_text(json.dumps(context, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        print(f"Dry run. Context saved to: {context_path}")
        print(f"Dry run. Prompt saved to: {prompt_path}")
        return

    result = _call_axiom(prompt, args.timeout)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    review_path.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Axiom review failed with exit code {result.returncode}. Output saved to {review_path}")

    event = _update_axiom_rpg(run_id, dry_run=False)
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    notes = _extract_memory_notes(output)
    if append_memory_notes is not None:
        append_memory_notes(["axiom"], notes, section="Evaluation lessons", source="axiom_review")
    else:
        _fallback_append_memory(notes, "axiom_review")

    print(output.strip())
    print()
    print(f"Context saved to: {context_path}")
    print(f"Prompt saved to: {prompt_path}")
    print(f"Review saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"Axiom XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")


if __name__ == "__main__":
    main()
