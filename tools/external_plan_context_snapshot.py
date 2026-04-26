#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/openclaw/.openclaw/workspace")
DOCS_DIR = ROOT / "docs" / "roadmap_context"
RUNS_DIR = ROOT / "state" / "live_runs"
OUT_DIR = ROOT / "state" / "external_plan_context"

SOURCE_FILES = [
    "acc_openclaw_11_step_roadmap.txt",
    "acc_v2_master_plan.txt",
    "acc_v3_dreambot_deltas.txt",
    "AI_Agent_Employee_Roster.txt",
    "grant_cardone_plan.txt",
    "acc_grant_memory_hermes_additions.txt",
    "ACC_V3_additions.txt",
]

KEYWORDS = [
    "ML", "machine learning", "warehouse", "Hermes", "MEMORY.md", "RPG",
    "Axiom", "Vivienne", "Ledger", "Helena", "Grant", "Yam Yam",
    "paper", "step #7", "roadmap", "V2", "V3", "Dreambot", "Orion", "Rowan",
    "token", "cost", "dashboard", "Android", "board", "watchdog", "Lucian",
]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line.strip())
    return line.strip(" -*\t")


def _important_lines(text: str, max_lines: int = 40) -> list[str]:
    lines = []
    seen = set()
    for raw in text.splitlines():
        line = _clean_line(raw)
        if not line or len(line) < 8:
            continue
        low = line.lower()
        if any(k.lower() in low for k in KEYWORDS):
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def _read_sources() -> list[dict[str, Any]]:
    out = []
    for name in SOURCE_FILES:
        path = DOCS_DIR / name
        if not path.exists():
            path = DOCS_DIR / name.replace("_", " ")
        if not path.exists():
            out.append({"name": name, "exists": False})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        out.append({
            "name": path.name,
            "path": str(path.relative_to(ROOT)),
            "exists": True,
            "bytes": path.stat().st_size,
            "sha256": _sha256(text),
            "line_count": len(text.splitlines()),
            "important_lines": _important_lines(text),
        })
    return out


def _latest_run_dir(run_id: str | None = None) -> Path | None:
    if run_id:
        p = RUNS_DIR / run_id
        return p if p.exists() else None
    if not RUNS_DIR.exists():
        return None
    runs = [p for p in RUNS_DIR.glob("run_*") if p.is_dir()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def _v2_status_hint(sources: list[dict[str, Any]]) -> list[str]:
    text = "\n".join("\n".join(s.get("important_lines") or []) for s in sources)
    hints = []
    if "ML" in text or "machine learning" in text.lower():
        hints.append("V2 proof must verify ML readiness with real live features, loaded model, nonzero ML coverage, and training/outcome persistence.")
    if "warehouse" in text.lower():
        hints.append("Warehouse persistence must be audited before roadmap step #7 paper proof.")
    if "Hermes" in text:
        hints.append("Hermes remains a second-brain rollout item; audit first, then phase rollout rather than flipping all agents blindly.")
    if "Grant" in text:
        hints.append("Grant speeches should create cliff notes for listeners, not dump full speeches into every MEMORY.md.")
    if "paper" in text.lower():
        hints.append("Roadmap step #7 is paper proof; live money waits until governance, ML, warehouse, memory, and cost controls survive testing.")
    if not hints:
        hints.append("External roadmap files are present, but no specific V2 hints were extracted.")
    return hints


def build_snapshot(run_id: str | None = None) -> dict[str, Any]:
    sources = _read_sources()
    run_dir = _latest_run_dir(run_id)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name if run_dir else run_id,
        "source_dir": str(DOCS_DIR.relative_to(ROOT)),
        "sources": sources,
        "v2_status_hints": _v2_status_hint(sources),
        "live_run_binding": {
            "purpose": "This snapshot binds external roadmap/context files into the live-run artifact/governance flow.",
            "expected_live_run_hook": "run_external_plan_context_snapshot(run_id)",
            "disable_env": "DISABLE_EXTERNAL_PLAN_CONTEXT=1",
        },
    }


def write_snapshot(snapshot: dict[str, Any]) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = snapshot.get("run_id") or "NO_RUN"
    json_path = OUT_DIR / f"{run_id}_external_plan_context.json"
    txt_path = OUT_DIR / f"{run_id}_external_plan_context.txt"

    lines = []
    lines.append("ACC External Plan Context Snapshot")
    lines.append("=" * 34)
    lines.append("")
    lines.append(f"Timestamp: {snapshot['timestamp']}")
    lines.append(f"Run id: {snapshot.get('run_id')}")
    lines.append(f"Source dir: {snapshot.get('source_dir')}")
    lines.append("")
    lines.append("V2 / roadmap hints:")
    for item in snapshot.get("v2_status_hints") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Sources:")
    for src in snapshot.get("sources") or []:
        lines.append(f"- {src.get('name')}: {'OK' if src.get('exists') else 'MISSING'}")
        if src.get("exists"):
            lines.append(f"  path={src.get('path')} lines={src.get('line_count')} bytes={src.get('bytes')} sha256={str(src.get('sha256'))[:16]}...")
            important = src.get("important_lines") or []
            for line in important[:8]:
                lines.append(f"  * {line}")
    text = "\n".join(lines) + "\n"

    json_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    txt_path.write_text(text, encoding="utf-8")

    latest_json = OUT_DIR / "latest_external_plan_context.json"
    latest_txt = OUT_DIR / "latest_external_plan_context.txt"
    latest_json.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    latest_txt.write_text(text, encoding="utf-8")

    run_id = snapshot.get("run_id")
    if run_id:
        run_artifacts = RUNS_DIR / run_id / "artifacts"
        if run_artifacts.exists():
            shutil.copy2(json_path, run_artifacts / "external_plan_context.json")
            shutil.copy2(txt_path, run_artifacts / "external_plan_context.txt")

    return json_path, txt_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind external ACC roadmap/context docs into live-run artifacts.")
    parser.add_argument("--run-id", default=None, help="Run id. Defaults to latest run when available.")
    parser.add_argument("--print", action="store_true", help="Print text snapshot after writing.")
    args = parser.parse_args()

    snapshot = build_snapshot(args.run_id)
    json_path, txt_path = write_snapshot(snapshot)
    print(f"External plan context JSON saved to: {json_path}")
    print(f"External plan context text saved to: {txt_path}")
    if args.print:
        print(txt_path.read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    main()
