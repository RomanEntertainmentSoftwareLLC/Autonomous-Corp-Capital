#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("ACC_ROOT", "/opt/openclaw/.openclaw/workspace"))
STATE = ROOT / "state"
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
RUNS = STATE / "live_runs"


def _refresh_paths(root: Path) -> None:
    global ROOT, STATE, DATA, REPORTS, RUNS
    ROOT = root
    STATE = ROOT / "state"
    DATA = ROOT / "data"
    REPORTS = ROOT / "reports"
    RUNS = STATE / "live_runs"


def _read_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    except Exception:
        return 0


def _sqlite_files() -> list[Path]:
    """Find durable warehouse sqlite files in both legacy state/ and canonical data/.

    init_warehouse.py and db_status.py use data/warehouse.sqlite, while older
    reports only scanned state/. That made a real initialized warehouse appear
    missing. Keep both roots so old experiments are still visible.
    """
    found: set[Path] = set()
    for root in (DATA, STATE):
        if not root.exists():
            continue
        for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
            found.update(root.rglob(pattern))
    return sorted(found)


def _inspect_sqlite(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"path": str(path), "exists": path.exists(), "objects": {}, "tables": {}, "error": None}
    if not path.exists():
        return info
    try:
        con = sqlite3.connect(str(path))
        cur = con.cursor()
        objects = cur.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY type, name"
        ).fetchall()
        for name, obj_type in objects:
            meta: dict[str, Any] = {"type": obj_type}
            if obj_type == "table":
                try:
                    meta["rows"] = cur.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                except Exception as exc:
                    meta["rows"] = None
                    meta["error"] = repr(exc)
                info["tables"][name] = meta
            else:
                meta["rows"] = None
            info["objects"][name] = meta
        con.close()
    except Exception as exc:
        info["error"] = repr(exc)
    return info


def _latest_runs(limit: int = 5) -> list[dict[str, Any]]:
    if not RUNS.exists():
        return []
    runs = sorted([p for p in RUNS.glob("run_*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for run in runs:
        art = run / "artifacts"
        out.append({
            "run_id": run.name,
            "mtime": datetime.fromtimestamp(run.stat().st_mtime, tz=timezone.utc).isoformat(),
            "portfolio_rows": _read_jsonl_count(art / "portfolio_state.jsonl"),
            "decision_rows": _read_jsonl_count(art / "paper_decisions.jsonl"),
            "trade_rows": _read_jsonl_count(art / "paper_trades.jsonl"),
            "packet_rows": _read_jsonl_count(art / "company_packets.jsonl"),
            "target_state": (art / "target_state.json").exists(),
            "grant_briefing": (art / "grant_briefing.json").exists(),
        })
    return out


def build_report() -> dict[str, Any]:
    dbs = _sqlite_files()
    inspected = [_inspect_sqlite(p) for p in dbs]
    total_tables = sum(len(i.get("tables") or {}) for i in inspected)
    nonempty_tables = sum(
        1
        for i in inspected
        for t in (i.get("tables") or {}).values()
        if (t.get("rows") or 0) > 0
    )
    latest = _latest_runs()

    verdict = "warehouse_missing"
    if inspected and nonempty_tables:
        verdict = "warehouse_has_data"
    elif inspected:
        verdict = "warehouse_empty_or_unverified"
    elif any(r.get("decision_rows") or r.get("portfolio_rows") for r in latest):
        verdict = "artifact_only_no_sqlite_warehouse_found"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(ROOT),
        "state_dir_exists": STATE.exists(),
        "data_dir_exists": DATA.exists(),
        "searched_dirs": [str(DATA), str(STATE)],
        "sqlite_files": [str(p) for p in dbs],
        "sqlite_count": len(inspected),
        "table_count": total_tables,
        "nonempty_table_count": nonempty_tables,
        "sqlite_inspection": inspected,
        "latest_runs": latest,
        "verdict": verdict,
    }


def write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS / "warehouse_audit.json"
    txt_path = REPORTS / "warehouse_audit.txt"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "WAREHOUSE AUDIT",
        "===============",
        f"Verdict: {report.get('verdict')}",
        f"SQLite files: {report.get('sqlite_count')}",
        f"Tables: {report.get('table_count')} | non-empty: {report.get('nonempty_table_count')}",
        f"Data dir exists: {report.get('data_dir_exists')}",
        f"State dir exists: {report.get('state_dir_exists')}",
        "Searched dirs:",
    ]
    for path in report.get("searched_dirs") or []:
        lines.append(f"- {path}")

    lines.extend(["", "Latest runs:"])
    for r in report.get("latest_runs") or []:
        lines.append(
            f"- {r['run_id']}: decisions={r['decision_rows']} trades={r['trade_rows']} portfolio={r['portfolio_rows']} packets={r['packet_rows']} target={r['target_state']} grant={r['grant_briefing']}"
        )

    lines.append("")
    lines.append("SQLite tables:")
    for db in report.get("sqlite_inspection") or []:
        lines.append(f"- {db.get('path')} error={db.get('error')}")
        for table, meta in (db.get("tables") or {}).items():
            lines.append(f"  - {table}: rows={meta.get('rows')}")
        views = [name for name, meta in (db.get("objects") or {}).items() if meta.get("type") == "view"]
        for view in views:
            lines.append(f"  - {view}: view")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, txt_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit ACC durable warehouse / SQLite persistence and latest run artifact coverage.")
    parser.add_argument("--root", type=Path, default=ROOT, help="ACC workspace root")
    args = parser.parse_args()
    _refresh_paths(args.root)

    report = build_report()
    json_path, txt_path = write_reports(report)
    print(txt_path.read_text(encoding="utf-8"))
    print(f"Wrote: {json_path}")
    print(f"Wrote: {txt_path}")


if __name__ == "__main__":
    main()
