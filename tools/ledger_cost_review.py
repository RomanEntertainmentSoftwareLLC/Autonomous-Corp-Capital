#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
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
LEDGER_DIR = ROOT / "state" / "ledger_reviews"
LEDGER_RPG_STATE = ROOT / "ai_agents_memory" / "ledger" / "RPG_STATE.md"
LEDGER_RPG_HISTORY = ROOT / "ai_agents_memory" / "ledger" / "RPG_HISTORY.md"


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


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _clip(value: Any, limit: int = 1800) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _resolve_openclaw_bin() -> str:
    return os.environ.get("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/psych/.npm-global/bin/openclaw"


def _summarize_usage(art: Path) -> dict[str, Any]:
    ledger_rows = _read_jsonl(art / "ledger_usage.jsonl")
    bridge_rows = _read_jsonl(art / "bridge_usage.jsonl")
    rows = ledger_rows + bridge_rows
    agents = Counter()
    providers = Counter()
    models = Counter()
    companies = Counter()
    outcomes = Counter()
    total_tokens = 0
    total_cost = 0.0
    token_rows = 0
    cost_rows = 0
    missing_token_rows = 0
    missing_cost_rows = 0
    by_agent_tokens: defaultdict[str, int] = defaultdict(int)
    by_agent_cost: defaultdict[str, float] = defaultdict(float)

    for row in rows:
        agent = str(row.get("agent") or row.get("agent_id") or "UNKNOWN")
        provider = str(row.get("provider") or "UNKNOWN")
        model = str(row.get("model") or "UNKNOWN")
        company = str(row.get("company") or row.get("company_id") or "UNKNOWN")
        outcome = str(row.get("outcome") or row.get("status") or "UNKNOWN")
        agents[agent] += 1
        providers[provider] += 1
        models[model] += 1
        companies[company] += 1
        outcomes[outcome] += 1
        token_value = row.get("total_tokens") or row.get("tokens")
        cost_value = row.get("estimated_cost") or row.get("cost") or row.get("usd_cost") or row.get("estimated_cost_usd")
        tokens = _num(token_value)
        cost = _num(cost_value)
        if tokens is None:
            missing_token_rows += 1
        else:
            token_rows += 1
            total_tokens += int(tokens)
            by_agent_tokens[agent] += int(tokens)
        if cost is None:
            missing_cost_rows += 1
        else:
            cost_rows += 1
            total_cost += float(cost)
            by_agent_cost[agent] += float(cost)

    burn_flags: list[str] = []
    if rows and token_rows == 0:
        burn_flags.append("usage_rows_exist_but_tokens_missing")
    if rows and cost_rows == 0:
        burn_flags.append("usage_rows_exist_but_cost_missing")
    if not rows:
        burn_flags.append("no_usage_telemetry_rows")
    if total_tokens > int(os.getenv("ACC_LEDGER_TOKEN_WARNING", "250000")):
        burn_flags.append("token_warning_threshold_exceeded")

    return {
        "ledger_rows": len(ledger_rows),
        "bridge_rows": len(bridge_rows),
        "total_rows": len(rows),
        "token_rows": token_rows,
        "cost_rows": cost_rows,
        "missing_token_rows": missing_token_rows,
        "missing_cost_rows": missing_cost_rows,
        "total_tokens_known": total_tokens if token_rows else None,
        "total_cost_known": round(total_cost, 6) if cost_rows else None,
        "top_agents_by_calls": dict(agents.most_common(12)),
        "top_agents_by_tokens": dict(sorted(by_agent_tokens.items(), key=lambda kv: (-kv[1], kv[0]))[:12]),
        "top_agents_by_cost": {k: round(v, 6) for k, v in sorted(by_agent_cost.items(), key=lambda kv: (-kv[1], kv[0]))[:12]},
        "providers": dict(providers.most_common(10)),
        "models": dict(models.most_common(10)),
        "companies": dict(companies.most_common(10)),
        "outcomes": dict(outcomes.most_common(10)),
        "burn_flags": burn_flags,
    }


def _build_context(run_dir: Path) -> dict[str, Any]:
    art = run_dir / "artifacts"
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "usage_summary": _summarize_usage(art),
        "target_state": _read_json(art / "target_state.json", {}),
        "grant_briefing_summary": _read_json(art / "grant_briefing.json", {}),
    }


def _build_prompt(context: dict[str, Any]) -> str:
    return f"""
Ledger, perform an ACC token and cost governance review.

This is an actual runtime governance job. Your job is to judge token usage, model/provider cost visibility, missing telemetry, burn-rate risk, and whether the next paper proof is financially sane.

Rules:
- Use only the facts below.
- Do not invent token or cost numbers.
- Be concise and operational.
- Recommend throttles/degraded modes only when supported by the facts.
- Flag missing telemetry as a governance risk.

Context:
{_clip(json.dumps(context, indent=2, sort_keys=True, default=str), 7000)}

Required output:
1. Cost governance verdict: one paragraph.
2. Telemetry truth: 3-5 bullets.
3. Burn-rate/waste risks: 3-5 bullets.
4. Recommended cost controls before the next paper proof: 3-5 bullets.
5. Memory-worthy cost lessons: 3 bullets max.
""".strip()


def _call_ledger(prompt: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_resolve_openclaw_bin(), "agent", "--agent", "ledger", "--message", prompt],
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
        if "memory-worthy" in low or "cost lessons" in low:
            capture = True
            continue
        if capture and line.startswith(("-", "•", "1.", "2.", "3.")):
            cleaned = re.sub(r"^[-•\s]*", "", line)
            cleaned = re.sub(r"^\d+\.\s*", "", cleaned).strip()
            if cleaned:
                notes.append(cleaned)
            if len(notes) >= 3:
                break
    return notes[:3] or ["Completed cost governance review; see state/ledger_reviews for details."]


def _update_rpg(run_id: str, dry_run: bool = False) -> dict[str, Any]:
    before = load_rpg_state(LEDGER_RPG_STATE)
    after = update_xp(before, 7.0)
    after["sessions"] = int(after.get("sessions") or 0) + 1
    after["accuracy"] = min(100.0, float(after.get("accuracy") or 0.0) + 1.0)
    after["judgment"] = min(100.0, float(after.get("judgment") or 0.0) + 1.0)
    after["reliability"] = min(100.0, float(after.get("reliability") or 0.0) + 1.0)
    after["usefulness"] = min(100.0, float(after.get("usefulness") or 0.0) + 2.0)
    after["cost_efficiency"] = min(100.0, float(after.get("cost_efficiency") or 0.0) + 4.0)
    after["evidence_quality"] = min(100.0, float(after.get("evidence_quality") or 0.0) + 2.0)
    saved = after if dry_run else save_rpg_state(LEDGER_RPG_STATE, after)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent_id": "ledger",
        "event": "ledger_cost_governance_review",
        "run_id": run_id,
        "xp_delta": 7.0,
        "before_xp": float(before.get("xp") or 0.0),
        "after_xp": float(saved.get("xp") or 0.0),
        "sessions": int(saved.get("sessions") or 0),
    }
    if not dry_run:
        append_human_rpg_history(
            LEDGER_RPG_HISTORY,
            timestamp=event["timestamp"],
            agent_id="ledger",
            event_type="Cost Governance Review",
            xp_delta=event["xp_delta"],
            before_xp=event["before_xp"],
            after_xp=event["after_xp"],
            before_level=before.get("level"),
            after_level=saved.get("level"),
            context=f"run_id={run_id} | sessions={event['sessions']}",
            reason="Ledger reviewed token/cost telemetry, missing usage fields, model/provider burn risk, and cost controls before paper proof.",
        )
    return event


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Ledger token/cost governance review and award RPG XP.")
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

    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    context_path = LEDGER_DIR / f"{run_id}_ledger_context.json"
    prompt_path = LEDGER_DIR / f"{run_id}_ledger_prompt.txt"
    review_path = LEDGER_DIR / f"{run_id}_ledger_review.txt"
    event_path = LEDGER_DIR / f"{run_id}_ledger_rpg_event.json"
    context_path.write_text(json.dumps(context, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        print(f"Dry run. Context saved to: {context_path}")
        print(f"Dry run. Prompt saved to: {prompt_path}")
        return

    result = _call_ledger(prompt, args.timeout)
    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    review_path.write_text(output, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Ledger review failed with exit code {result.returncode}. Output saved to {review_path}")

    event = _update_rpg(run_id, dry_run=False)
    event_path.write_text(json.dumps(event, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if append_memory_notes is not None:
        append_memory_notes(["ledger"], _extract_notes(output), section="Cost governance lessons", source=f"ledger:{run_id}")

    print(output.strip())
    print()
    print(f"Context saved to: {context_path}")
    print(f"Prompt saved to: {prompt_path}")
    print(f"Review saved to: {review_path}")
    print(f"RPG event saved to: {event_path}")
    print(f"Ledger XP: {event['before_xp']} -> {event['after_xp']} | sessions={event['sessions']}")


if __name__ == "__main__":
    main()
