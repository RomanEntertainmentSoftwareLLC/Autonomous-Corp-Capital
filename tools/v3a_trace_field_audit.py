"""ACC V3-A candidate trace field audit.

This tool verifies that candidate_decisions.jsonl rows include V3-A trace
fields after Batch 3 wiring.

It is read-only. It does not change trades, portfolios, agents, OpenClaw,
Hermes, or live-trade gates.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_V3A_FIELDS = [
    "v3a_market_regime",
    "v3a_risk_posture",
    "v3a_best_posture",
    "v3a_market_weather",
    "v3a_universe_rank",
    "v3a_universe_rank_score",
    "v3a_rank_reasons",
]

WAIT_FIELDS = [
    "wait_reason",
    "wait_reason_detail",
]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def resolve_run_dir(root: Path, run_id: str | None) -> Path | None:
    live_runs = root / "state" / "live_runs"
    if not live_runs.exists():
        return None

    requested = (run_id or "latest").strip()
    if requested and requested not in {"latest", "current"}:
        direct = Path(requested)
        if direct.exists():
            return direct
        candidate = live_runs / requested
        if candidate.exists():
            return candidate
        return None

    current = _read_json(live_runs / "current_run.json")
    for key in ("run_id", "id", "current_run_id"):
        value = current.get(key)
        if value and (live_runs / str(value)).exists():
            return live_runs / str(value)

    run_dirs = [p for p in live_runs.iterdir() if p.is_dir()]
    if not run_dirs:
        return None
    return max(run_dirs, key=lambda p: p.stat().st_mtime)


def candidate_decision_path(run_dir: Path) -> Path:
    candidates = [
        run_dir / "artifacts" / "candidate_decisions.jsonl",
        run_dir / "candidate_decisions.jsonl",
        run_dir / "reports" / "candidate_decisions.jsonl",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def build_trace_field_audit(root: Path, run_id: str | None = "latest") -> Dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    run_dir = resolve_run_dir(root, run_id)

    if run_dir is None:
        return {
            "generated_at": generated_at,
            "status": "FAIL",
            "reason": "missing_run_dir",
            "run_id": run_id or "latest",
            "run_dir": None,
            "candidate_path": None,
            "candidate_rows": 0,
            "decision_counts": {},
            "missing_v3a_field_counts": {},
            "wait_rows": 0,
            "wait_rows_missing_wait_reason": 0,
        }

    candidate_path = candidate_decision_path(run_dir)
    rows = _read_jsonl(candidate_path)

    decision_counts = Counter(str(row.get("decision") or "UNKNOWN") for row in rows)
    missing_v3a = Counter()
    wait_rows = 0
    wait_missing = 0

    for row in rows:
        for field in REQUIRED_V3A_FIELDS:
            if field not in row or row.get(field) in (None, ""):
                missing_v3a[field] += 1

        if str(row.get("decision") or "").upper() == "WAIT":
            wait_rows += 1
            if not row.get("wait_reason"):
                wait_missing += 1
            if not row.get("wait_reason_detail"):
                wait_missing += 1

    if not rows:
        status = "FAIL"
        reason = "no_candidate_rows"
    elif missing_v3a:
        status = "FAIL"
        reason = "missing_v3a_fields"
    elif wait_missing:
        status = "FAIL"
        reason = "wait_rows_missing_wait_reason_fields"
    else:
        status = "PASS"
        reason = "all_required_v3a_trace_fields_present"

    return {
        "generated_at": generated_at,
        "status": status,
        "reason": reason,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "candidate_path": str(candidate_path),
        "candidate_rows": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "missing_v3a_field_counts": dict(sorted(missing_v3a.items())),
        "wait_rows": wait_rows,
        "wait_rows_missing_wait_reason": wait_missing,
    }


def render_text_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "ACC V3-A Trace Field Audit",
        "==========================",
        f"Generated at: {payload.get('generated_at')}",
        f"Status: {payload.get('status')}",
        f"Reason: {payload.get('reason')}",
        f"Run ID: {payload.get('run_id')}",
        f"Run dir: {payload.get('run_dir')}",
        f"Candidate path: {payload.get('candidate_path')}",
        f"Candidate rows: {payload.get('candidate_rows')}",
        "",
        "Decision Counts",
        "---------------",
    ]

    decision_counts = payload.get("decision_counts") or {}
    if decision_counts:
        for key, value in decision_counts.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")

    lines.extend([
        "",
        "Missing V3-A Field Counts",
        "-------------------------",
    ])

    missing = payload.get("missing_v3a_field_counts") or {}
    if missing:
        for key, value in missing.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")

    lines.extend([
        "",
        "WAIT Rows",
        "---------",
        f"WAIT rows: {payload.get('wait_rows')}",
        f"WAIT rows missing wait_reason/wait_reason_detail fields: {payload.get('wait_rows_missing_wait_reason')}",
        "",
    ])

    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit V3-A trace fields in candidate_decisions.jsonl.")
    parser.add_argument("--root", type=Path, default=ROOT, help="ACC workspace root.")
    parser.add_argument("--run-id", default="latest", help="Run id, run path, latest, or current.")
    parser.add_argument("--out", type=Path, default=None, help="Optional output text report path.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when audit status is not PASS.")
    args = parser.parse_args(argv)

    payload = build_trace_field_audit(args.root, args.run_id)

    if args.json:
        output = json.dumps(payload, indent=2, sort_keys=True)
    else:
        output = render_text_report(payload)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + ("\n" if not output.endswith("\n") else ""), encoding="utf-8")

    print(output)

    if args.strict and payload.get("status") != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
