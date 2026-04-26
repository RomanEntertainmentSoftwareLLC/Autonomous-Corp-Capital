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

ORION_TERMS = ["fresh", "external", "serpapi", "yahoo", "signal", "strategy", "rank", "current", "live"]
ROWAN_TERMS = ["research", "cached", "context", "background", "deep", "source", "evidence", "article"]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _score(text: str, terms: list[str]) -> int:
    low = text.lower()
    return sum(low.count(t) for t in terms)


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


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    backup = ROOT / "ai_agents_backup"
    rows = []
    for md in backup.glob("**/AGENTS.md"):
        agent_dir = md.parent
        folder = agent_dir.name
        if "orion" not in folder.lower() and "rowan" not in folder.lower():
            continue
        text = "\n".join(_read(agent_dir / f) for f in ["AGENTS.md", "IDENTITY.md", "SOUL.md", "MEMORY.md"])
        rows.append({
            "path": str(agent_dir.relative_to(ROOT)),
            "folder": folder,
            "orion_term_score": _score(text, ORION_TERMS),
            "rowan_term_score": _score(text, ROWAN_TERMS),
            "has_identity": (agent_dir / "IDENTITY.md").exists(),
            "has_soul": (agent_dir / "SOUL.md").exists(),
            "has_memory": (agent_dir / "MEMORY.md").exists(),
        })

    latest = _latest_run()
    role_counts = Counter()
    if latest:
        for row in _read_jsonl(latest / "artifacts" / "company_packets.jsonl"):
            for role in row.get("live_roles_responded") or []:
                role_counts[str(role)] += 1

    issues = []
    for row in rows:
        is_orion = "orion" in row["folder"].lower()
        is_rowan = "rowan" in row["folder"].lower()
        if is_orion and row["rowan_term_score"] > row["orion_term_score"] * 1.5:
            issues.append(f"Orion-looking folder has heavier Rowan/research language: {row['path']}")
        if is_rowan and row["orion_term_score"] > row["rowan_term_score"] * 1.5:
            issues.append(f"Rowan-looking folder has heavier Orion/fresh-signal language: {row['path']}")

    report = {
        "agent_rows": rows,
        "latest_run": latest.name if latest else None,
        "latest_run_role_counts": dict(role_counts),
        "issues": issues,
        "interpretation": [
            "Roadmap Step 1 wants Orion to be fresh external signal / strategy.",
            "Roadmap Step 2 wants Rowan to be deep cached research/context.",
            "This audit checks persona wording and latest company packet role participation only; it does not prove runtime behavior alone.",
        ],
    }

    lines = ["Orion / Rowan Separation Audit", "=" * 31, ""]
    lines.append(f"Rows inspected: {len(rows)}")
    lines.append(f"Latest run: {report['latest_run']}")
    lines.append("")
    lines.append("Agent language scores:")
    for r in rows:
        lines.append(f"- {r['path']}: orion_terms={r['orion_term_score']} rowan_terms={r['rowan_term_score']} identity={r['has_identity']} soul={r['has_soul']} memory={r['has_memory']}")
    lines.append("")
    lines.append("Latest run role counts:")
    for k, v in role_counts.most_common():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("Issues:")
    if issues:
        lines.extend(f"- {x}" for x in issues)
    else:
        lines.append("- None flagged by wording heuristic.")

    (REPORTS / "orion_rowan_separation_audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "orion_rowan_separation_audit.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:160]))
    print(f"Wrote: {REPORTS / 'orion_rowan_separation_audit.txt'}")


if __name__ == "__main__":
    main()
