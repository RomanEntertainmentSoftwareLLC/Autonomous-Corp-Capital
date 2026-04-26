#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path("/opt/openclaw/.openclaw/workspace")
REPORTS = ROOT / "reports"
RUNS = ROOT / "state" / "live_runs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _latest_run() -> Path | None:
    if not RUNS.exists():
        return None
    runs = [p for p in RUNS.glob("run_*") if p.is_dir()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _fields_seen(rows: list[dict[str, Any]], names: list[str]) -> dict[str, int]:
    return {name: sum(1 for r in rows if r.get(name) is not None) for name in names}


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    regime_files = sorted([str(p.relative_to(ROOT)) for p in ROOT.glob("**/*regime*.py") if ".git" not in str(p)])
    decision_text = _read(ROOT / "tools" / "live_decision_engine.py")
    live_run_text = _read(ROOT / "tools" / "live_run.py")

    latest = _latest_run()
    rows = _read_jsonl(latest / "artifacts" / "paper_decisions.jsonl") if latest else []
    regime_field_names = ["regime", "market_regime", "regime_signal", "regime_score", "regime_bias", "market_bias", "volatility"]
    field_counts = _fields_seen(rows, regime_field_names)

    text_has = {
        "decision_engine_mentions_regime": "regime" in decision_text.lower(),
        "live_run_mentions_regime": "regime" in live_run_text.lower(),
        "decision_engine_mentions_volatility": "volatility" in decision_text.lower(),
        "decision_engine_mentions_market_bias": "market_bias" in decision_text.lower() or "market bias" in decision_text.lower(),
    }

    verdict = "not_wired"
    if regime_files and (text_has["decision_engine_mentions_regime"] or text_has["live_run_mentions_regime"]):
        verdict = "partially_wired"
    if rows and any(v > 0 for v in field_counts.values()):
        verdict = "runtime_fields_seen"

    report = {
        "latest_run": latest.name if latest else None,
        "regime_files": regime_files,
        "text_has": text_has,
        "decision_rows": len(rows),
        "regime_field_counts": field_counts,
        "verdict": verdict,
        "recommendation": [
            "Keep this as readiness/proof first; do not add major strategy changes before reports are green.",
            "If not wired, next implementation should add regime as a scored WAIT/permission signal, not a blind BUY booster.",
            "Regime should be a gate/weight adjuster before roadmap step #7, not a hype override.",
        ],
    }

    lines = ["Regime Readiness Report", "=" * 23, ""]
    lines.append(f"Latest run: {report['latest_run']}")
    lines.append(f"Verdict: {verdict}")
    lines.append("")
    lines.append("Regime files:")
    if regime_files:
        lines.extend(f"- {x}" for x in regime_files)
    else:
        lines.append("- None found.")
    lines.append("")
    lines.append("Code mentions:")
    for k, v in text_has.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("Runtime decision fields:")
    for k, v in field_counts.items():
        lines.append(f"- {k}: {v}/{len(rows)}")
    lines.append("")
    lines.append("Recommendation:")
    for x in report["recommendation"]:
        lines.append(f"- {x}")

    (REPORTS / "regime_readiness_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "regime_readiness_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"Wrote: {REPORTS / 'regime_readiness_report.txt'}")


if __name__ == "__main__":
    main()
