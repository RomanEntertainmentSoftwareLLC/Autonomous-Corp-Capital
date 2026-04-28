#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def run_cmd(name: str, cmd: list[str], timeout: int = 180) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=None,
        )
        return {"name": name, "ok": completed.returncode == 0, "returncode": completed.returncode, "output": completed.stdout or ""}
    except subprocess.TimeoutExpired as exc:
        return {"name": name, "ok": False, "timeout": True, "returncode": None, "output": exc.stdout or ""}
    except Exception as exc:
        return {"name": name, "ok": False, "error": repr(exc), "returncode": None, "output": ""}


def status(ok: bool, warn: bool = False) -> str:
    if ok:
        return "OK"
    if warn:
        return "WARN"
    return "FAIL"


def main() -> int:
    parser = argparse.ArgumentParser(description="ACC V2 readiness gate summary.")
    parser.add_argument("--refresh", action="store_true", help="Refresh token-free reports before checking.")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)

    refreshed = []
    if args.refresh:
        commands = [
            ("db_status", [sys.executable, "tools/db_status.py"]),
            ("decision_trace_report", [sys.executable, "tools/decision_trace_report.py"]),
            ("ml_readiness_report", [sys.executable, "tools/ml_readiness_report.py"]),
            ("warehouse_audit", [sys.executable, "tools/warehouse_audit.py"]),
            ("ledger_usage_summary", [sys.executable, "tools/ledger_usage_summary.py"]),
        ]
        for name, cmd in commands:
            refreshed.append(run_cmd(name, cmd))

    ml = read_text(REPORTS / "ml_readiness_report.txt")
    warehouse = read_text(REPORTS / "warehouse_audit.txt")
    decision = read_text(REPORTS / "decision_trace_report_latest.txt")
    ledger = read_text(REPORTS / "ledger_usage_summary.txt")
    governance = read_text(REPORTS / "v2_governance_smoke_latest.txt")

    checks: list[dict[str, Any]] = []

    checks.append({
        "name": "ML readiness",
        "status": status("Verdict: ready_or_active" in ml),
        "detail": "ready_or_active" if "Verdict: ready_or_active" in ml else "not proven in latest report",
    })

    checks.append({
        "name": "Warehouse persistence",
        "status": status("Verdict: warehouse_has_data" in warehouse),
        "detail": "warehouse_has_data" if "Verdict: warehouse_has_data" in warehouse else "warehouse not proven",
    })

    no_trace_missing = "Rows without trace: 0" in decision
    has_decision_rows = "Decision rows: 0" not in decision and "Decision rows:" in decision
    checks.append({
        "name": "Decision traces",
        "status": status(no_trace_missing and has_decision_rows, warn=no_trace_missing),
        "detail": "trace rows clean" if no_trace_missing and has_decision_rows else ("no missing traces, but latest run may have zero decisions" if no_trace_missing else "missing traces or no report"),
    })

    usage_found = "Verdict: usage_found" in ledger
    checks.append({
        "name": "Token/cost telemetry",
        "status": status(usage_found, warn="Verdict: no_usage_rows_found" in ledger),
        "detail": "usage rows found" if usage_found else "no usage rows found or report missing",
    })

    gov_ok = "Result:" in governance and "/5 OK" in governance
    checks.append({
        "name": "Governance smoke",
        "status": status(gov_ok, warn=bool(governance)),
        "detail": "governance chain report exists" if governance else "no governance smoke report yet",
    })

    live_run_text = read_text(ROOT / "scripts" / "live_run_systemd.py")
    checks.append({
        "name": "Process supervisor",
        "status": status("terminate_process_group" in live_run_text and "start_new_session=True" in live_run_text),
        "detail": "process group timeout appears wired" if "terminate_process_group" in live_run_text else "timeout supervisor not detected",
    })

    checks.append({
        "name": "Auto post-run reports",
        "status": status("run_post_run_reports" in live_run_text, warn=False),
        "detail": "post-run reports wired" if "run_post_run_reports" in live_run_text else "post-run reports not detected",
    })

    ok_count = sum(1 for c in checks if c["status"] == "OK")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")

    overall = "READY_FOR_SHORT_PAPER_PROOF" if fail_count == 0 and ok_count >= 5 else "NOT_READY_YET"
    if fail_count == 0 and warn_count:
        overall = "READY_WITH_WARNINGS"

    summary = {
        "generated_at": utc_now(),
        "overall": overall,
        "ok_count": ok_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "checks": checks,
        "refreshed": refreshed,
    }

    json_path = REPORTS / "v2_readiness_gate.json"
    txt_path = REPORTS / "v2_readiness_gate.txt"

    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "ACC V2 Readiness Gate",
        "=====================",
        f"Generated: {summary['generated_at']}",
        f"Overall: {overall}",
        f"OK={ok_count} WARN={warn_count} FAIL={fail_count}",
        "",
        "Checks:",
    ]

    for c in checks:
        lines.append(f"- {c['status']}: {c['name']} — {c['detail']}")

    if refreshed:
        lines.extend(["", "Refresh commands:"])
        for r in refreshed:
            lines.append(f"- {'OK' if r.get('ok') else 'FAIL'}: {r['name']} rc={r.get('returncode')}")

    lines.extend(["", f"Wrote: {json_path}", f"Wrote: {txt_path}"])

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
