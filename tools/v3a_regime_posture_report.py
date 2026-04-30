"""ACC V3-A regime/posture report.

This report is read-only. It does not alter trading behavior, call agents,
call Hermes, mutate portfolios, or touch live-trade gates.

It summarizes the latest run's candidate_decisions.jsonl through the new
market regime, market weather, and universe ranking helpers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.market_regime import classify_market_regime_dict
from tools.market_weather import build_market_weather_dict
from tools.universe_ranker import rank_universe_candidates


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
    preferred = run_dir / "artifacts" / "candidate_decisions.jsonl"
    if preferred.exists():
        return preferred

    alternatives = [
        run_dir / "candidate_decisions.jsonl",
        run_dir / "reports" / "candidate_decisions.jsonl",
    ]
    for path in alternatives:
        if path.exists():
            return path
    return preferred


def _decision_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts = Counter(str(row.get("decision") or "UNKNOWN") for row in rows)
    return dict(sorted(counts.items()))


def _wait_reason_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts = Counter()
    for row in rows:
        decision = str(row.get("decision") or "").upper()
        reason = row.get("wait_reason") or row.get("decision_promotion_blocked_reason")
        if decision == "WAIT":
            counts[str(reason or "WAIT_REASON_UNSPECIFIED")] += 1
    return dict(sorted(counts.items()))


def _top_ranked(rows: Sequence[Mapping[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    ranked = rank_universe_candidates(rows)
    return ranked[:limit]


def build_report_payload(root: Path, run_id: str | None = "latest", limit: int = 10) -> Dict[str, Any]:
    run_dir = resolve_run_dir(root, run_id)
    now = datetime.now(timezone.utc).isoformat()

    if run_dir is None:
        return {
            "generated_at": now,
            "run_id": run_id or "latest",
            "run_dir": None,
            "status": "missing_run_dir",
            "candidate_rows": 0,
            "market_regime": classify_market_regime_dict([]),
            "market_weather": build_market_weather_dict([]),
            "decision_counts": {},
            "wait_reason_counts": {},
            "top_ranked": [],
            "notes": ["No live run directory could be resolved."],
        }

    candidate_path = candidate_decision_path(run_dir)
    rows = _read_jsonl(candidate_path)

    return {
        "generated_at": now,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "candidate_path": str(candidate_path),
        "status": "ok" if rows else "no_candidate_rows",
        "candidate_rows": len(rows),
        "market_regime": classify_market_regime_dict(rows),
        "market_weather": build_market_weather_dict(rows),
        "decision_counts": _decision_counts(rows),
        "wait_reason_counts": _wait_reason_counts(rows),
        "top_ranked": _top_ranked(rows, limit=limit),
        "notes": [] if rows else ["Candidate decision file was missing or empty."],
    }


def render_text_report(payload: Mapping[str, Any]) -> str:
    lines: List[str] = []
    lines.append("ACC V3-A Regime + Market Posture Report")
    lines.append("=======================================")
    lines.append(f"Generated at: {payload.get('generated_at')}")
    lines.append(f"Status: {payload.get('status')}")
    lines.append(f"Run ID: {payload.get('run_id')}")
    lines.append(f"Run dir: {payload.get('run_dir')}")
    if payload.get("candidate_path"):
        lines.append(f"Candidate path: {payload.get('candidate_path')}")
    lines.append(f"Candidate rows: {payload.get('candidate_rows')}")
    lines.append("")

    weather = payload.get("market_weather") or {}
    lines.append("Market Weather")
    lines.append("--------------")
    lines.append(f"Regime: {weather.get('market_regime')}")
    lines.append(f"Risk posture: {weather.get('risk_posture')}")
    lines.append(f"Best posture: {weather.get('best_posture')}")
    lines.append(f"Breadth: green={weather.get('breadth_green')} red={weather.get('breadth_red')} total={weather.get('breadth_total')}")
    lines.append(f"BTC direction: {weather.get('btc_direction')}")
    lines.append(f"ETH direction: {weather.get('eth_direction')}")
    lines.append(f"Volatility proxy: {weather.get('volatility_proxy')}")
    lines.append("")

    lines.append("Decision Counts")
    lines.append("---------------")
    decision_counts = payload.get("decision_counts") or {}
    if decision_counts:
        for key, value in decision_counts.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("WAIT Reason Counts")
    lines.append("------------------")
    wait_counts = payload.get("wait_reason_counts") or {}
    if wait_counts:
        for key, value in wait_counts.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("Top Ranked Candidates")
    lines.append("---------------------")
    top_ranked = payload.get("top_ranked") or []
    if top_ranked:
        for row in top_ranked:
            lines.append(
                f"{row.get('universe_rank')}. {row.get('symbol')} "
                f"score={row.get('universe_rank_score')} company={row.get('company_id')}"
            )
            for reason in row.get("reasons") or []:
                lines.append(f"   - {reason}")
    else:
        lines.append("- none")
    lines.append("")

    notes = payload.get("notes") or []
    if notes:
        lines.append("Notes")
        lines.append("-----")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only ACC V3-A regime/posture report.")
    parser.add_argument("--root", type=Path, default=ROOT, help="ACC workspace root.")
    parser.add_argument("--run-id", default="latest", help="Run id, run path, latest, or current.")
    parser.add_argument("--out", type=Path, default=None, help="Optional text report output path.")
    parser.add_argument("--json", action="store_true", help="Print JSON payload instead of text.")
    parser.add_argument("--limit", type=int, default=10, help="Number of ranked candidates to include.")
    args = parser.parse_args(argv)

    payload = build_report_payload(args.root, args.run_id, limit=args.limit)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        text = render_text_report(payload)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
