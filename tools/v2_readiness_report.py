#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/openclaw/.openclaw/workspace")
REPORTS = ROOT / "reports"
RUNS = ROOT / "state" / "live_runs"

CORE_TOOLS = [
    "tools/live_run.py",
    "tools/live_decision_engine.py",
    "tools/ml_readiness_report.py",
    "tools/warehouse_audit.py",
    "tools/decision_trace_report.py",
    "tools/ledger_cost_review.py",
    "tools/helena_risk_review.py",
    "tools/axiom_evaluator_review.py",
    "tools/vivienne_financial_review.py",
    "tools/selene_treasury_review.py",
    "tools/ariadne_workforce_review.py",
    "tools/grant_speech_review.py",
    "tools/yam_yam_executive_review.py",
    "tools/june_archive_review.py",
    "tools/hermes_inventory_audit.py",
    "tools/hermes_rollout_plan.py",
    "tools/agent_activation_queue.py",
    "tools/support_agent_review.py",
    "tools/grant_listener_notes.py",
    "tools/lucian_watchdog_accountability_review.py",
]

GOVERNANCE_ARTIFACTS = {
    "ledger": "state/ledger_reviews/*_ledger_review.txt",
    "helena": "state/helena_reviews/*_helena_review.txt",
    "axiom": "state/axiom_reviews/*_axiom_review.txt",
    "vivienne": "state/vivienne_reviews/*_vivienne_review.txt",
    "selene": "state/selene_reviews/*_selene_review.txt",
    "ariadne": "state/ariadne_reviews/*_ariadne_review.txt",
    "grant": "state/grant_speeches/*_grant_speech.txt",
    "yam_yam": "state/executive_reviews/*_yam_yam_review.txt",
    "june": "state/board_archives/*_june_archive.txt",
}

MASTER_AGENTS = ["main", "ledger", "helena", "axiom", "vivienne", "selene", "ariadne", "grant_cardone"]


def _run(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-3000:],
            "stderr": (proc.stderr or "")[-3000:],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "stdout": "", "stderr": ""}


def _latest_run_dir() -> Path | None:
    if not RUNS.exists():
        return None
    runs = [p for p in RUNS.glob("run_*") if p.is_dir()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def _count(pattern: str) -> int:
    return len(list(ROOT.glob(pattern)))


def _file_exists(path: str) -> bool:
    return (ROOT / path).exists()


def _latest(pattern: str) -> str | None:
    files = list(ROOT.glob(pattern))
    if not files:
        return None
    return str(max(files, key=lambda p: p.stat().st_mtime).relative_to(ROOT))


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path, limit: int = 250) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) > limit:
        lines = lines[-limit:]
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _agent_state(agent_id: str) -> dict[str, Any]:
    mem = ROOT / "ai_agents_memory" / agent_id
    state = mem / "RPG_STATE.md"
    hist = mem / "RPG_HISTORY.md"
    memory = mem / "MEMORY.md"
    text = state.read_text(encoding="utf-8", errors="replace") if state.exists() else ""
    xp = None
    sessions = None
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("xp:"):
            try:
                xp = float(line.split(":", 1)[1].strip().split()[0])
            except Exception:
                pass
        if low.startswith("sessions:"):
            try:
                sessions = int(float(line.split(":", 1)[1].strip().split()[0]))
            except Exception:
                pass
    return {
        "agent_id": agent_id,
        "has_rpg_state": state.exists(),
        "has_rpg_history": hist.exists(),
        "has_memory": memory.exists(),
        "xp": xp,
        "sessions": sessions,
    }


def _backup_health() -> dict[str, Any]:
    backup = ROOT / "ai_agents_backup"
    counts = {
        "AGENTS.md": len(list(backup.glob("**/AGENTS.md"))) if backup.exists() else 0,
        "IDENTITY.md": len(list(backup.glob("**/IDENTITY.md"))) if backup.exists() else 0,
        "SOUL.md": len(list(backup.glob("**/SOUL.md"))) if backup.exists() else 0,
        "MEMORY.md": len(list(backup.glob("**/MEMORY.md"))) if backup.exists() else 0,
        "USER.md": len(list(backup.glob("**/USER.md"))) if backup.exists() else 0,
        "TOOLS.md": len(list(backup.glob("**/TOOLS.md"))) if backup.exists() else 0,
        "HEARTBEAT.md": len(list(backup.glob("**/HEARTBEAT.md"))) if backup.exists() else 0,
    }
    nested = []
    if backup.exists():
        for p in backup.glob("**/*"):
            if p.is_dir():
                s = str(p.relative_to(backup))
                parts = s.split("/")
                for i in range(len(parts) - 1):
                    if parts[i] == parts[i + 1] and parts[i].endswith("_branch"):
                        nested.append(s)
    return {"counts": counts, "nested_duplicate_dirs": nested[:50], "healthy_64": all(v == 64 for v in counts.values())}


def _decision_health(run_dir: Path | None) -> dict[str, Any]:
    if not run_dir:
        return {"has_run": False}
    rows = _read_jsonl(run_dir / "artifacts" / "paper_decisions.jsonl")
    total = len(rows)
    traces = sum(1 for r in rows if r.get("decision_path_trace"))
    ml_scores = sum(1 for r in rows if r.get("ml_signal_score") is not None)
    evidence = sum(1 for r in rows if r.get("evidence_scores") or r.get("decision_evidence"))
    return {
        "has_run": True,
        "run_id": run_dir.name,
        "decision_rows": total,
        "rows_with_trace": traces,
        "rows_with_ml_score": ml_scores,
        "rows_with_evidence": evidence,
        "trace_coverage": round(traces / total, 4) if total else 0.0,
        "ml_score_coverage": round(ml_scores / total, 4) if total else 0.0,
        "evidence_coverage": round(evidence / total, 4) if total else 0.0,
    }


def _refresh_reports() -> dict[str, Any]:
    commands = {
        "ml_readiness": ["python3", "tools/ml_readiness_report.py"],
        "warehouse_audit": ["python3", "tools/warehouse_audit.py"],
        "hermes_inventory": ["python3", "tools/hermes_inventory_audit.py"],
        "agent_activation_queue": ["python3", "tools/agent_activation_queue.py"],
        "idle_employee_activation": ["python3", "tools/idle_employee_activation_report.py"],
        "decision_trace_report": ["python3", "tools/decision_trace_report.py", "--run-id", "latest"],
    }
    return {name: _run(cmd, timeout=90) for name, cmd in commands.items() if (ROOT / cmd[1]).exists()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize V2 readiness/proof status before roadmap step #7.")
    parser.add_argument("--refresh", action="store_true", help="Run supporting report tools first.")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    refresh_results = _refresh_reports() if args.refresh else {}

    run_dir = _latest_run_dir()
    present_tools = {tool: _file_exists(tool) for tool in CORE_TOOLS}
    missing_tools = [k for k, v in present_tools.items() if not v]
    compile_targets = [str(ROOT / t) for t in CORE_TOOLS if (ROOT / t).exists()]
    compile_result = _run(["python3", "-m", "py_compile", *compile_targets], timeout=120) if compile_targets else {"ok": False, "error": "no targets"}

    governance = {name: _latest(pattern) for name, pattern in GOVERNANCE_ARTIFACTS.items()}
    master_states = [_agent_state(a) for a in MASTER_AGENTS]
    backup = _backup_health()
    decision = _decision_health(run_dir)

    checklist = []
    checklist.append(("core_tools_present", len(missing_tools) == 0))
    checklist.append(("python_compile_clean", bool(compile_result.get("ok"))))
    checklist.append(("full_agent_backup_64", bool(backup["healthy_64"])))
    checklist.append(("latest_run_exists", run_dir is not None))
    checklist.append(("decision_trace_artifacts_seen", decision.get("rows_with_trace", 0) > 0))
    checklist.append(("ml_scores_seen_in_recent_decisions", decision.get("rows_with_ml_score", 0) > 0))
    checklist.append(("all_major_governance_artifacts_seen", all(governance.values())))
    checklist.append(("master_agents_have_memory", all(s["has_memory"] for s in master_states)))
    checklist.append(("master_agents_have_rpg_history", all(s["has_rpg_history"] for s in master_states)))

    done = sum(1 for _, ok in checklist if ok)
    readiness_pct = round(done / len(checklist) * 100, 1) if checklist else 0

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "readiness_pct": readiness_pct,
        "checklist": [{"name": name, "ok": ok} for name, ok in checklist],
        "missing_tools": missing_tools,
        "compile_result": compile_result,
        "backup": backup,
        "latest_run": str(run_dir.relative_to(ROOT)) if run_dir else None,
        "decision_health": decision,
        "governance_latest_artifacts": governance,
        "master_agent_states": master_states,
        "refresh_results": refresh_results,
        "remaining_v2_focus": [
            "prove ML scores after a fresh run",
            "prove warehouse persistence after a fresh run",
            "prove full post-run governance chain after a fresh run",
            "roll Hermes beyond audit into phased second-brain activation",
            "finish Orion/Rowan separation proof",
            "run roadmap step #7 paper proof only after readiness is acceptable",
        ],
    }

    lines = []
    lines.append("ACC V2 Readiness Report")
    lines.append("=" * 24)
    lines.append("")
    lines.append(f"Readiness score: {readiness_pct}% ({done}/{len(checklist)} checks)")
    lines.append(f"Latest run: {report['latest_run']}")
    lines.append("")
    lines.append("Checklist:")
    for item in report["checklist"]:
        lines.append(f"- [{'OK' if item['ok'] else 'NO'}] {item['name']}")
    lines.append("")
    lines.append("Backup counts:")
    for k, v in backup["counts"].items():
        lines.append(f"- {k}: {v}")
    if backup["nested_duplicate_dirs"]:
        lines.append("Nested duplicate dirs still present:")
        for item in backup["nested_duplicate_dirs"]:
            lines.append(f"- {item}")
    lines.append("")
    lines.append("Decision health:")
    for k, v in decision.items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("Latest governance artifacts:")
    for k, v in governance.items():
        lines.append(f"- {k}: {v or 'MISSING'}")
    lines.append("")
    lines.append("Master agent RPG/memory states:")
    for s in master_states:
        lines.append(f"- {s['agent_id']}: xp={s['xp']} sessions={s['sessions']} memory={s['has_memory']} history={s['has_rpg_history']}")
    lines.append("")
    lines.append("Remaining V2 focus:")
    for item in report["remaining_v2_focus"]:
        lines.append(f"- {item}")

    (REPORTS / "v2_readiness_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "v2_readiness_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:160]))
    print("")
    print(f"Wrote: {REPORTS / 'v2_readiness_report.txt'}")
    print(f"Wrote: {REPORTS / 'v2_readiness_report.json'}")


if __name__ == "__main__":
    main()
