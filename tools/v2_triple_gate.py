#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "live_runs"
REPORTS = ROOT / "reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def latest_run_dir() -> Path | None:
    runs = sorted(STATE.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            count += 1
    return count


def run_cmd(name: str, cmd: list[str], timeout: int) -> dict[str, Any]:
    started = utc_now()
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env={**os.environ, "PYTHONNOUSERSITE": os.environ.get("PYTHONNOUSERSITE", "1")},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return {
            "name": name,
            "cmd": cmd,
            "started_at": started,
            "ended_at": utc_now(),
            "returncode": completed.returncode,
            "ok": completed.returncode == 0,
            "output": completed.stdout or "",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "cmd": cmd,
            "started_at": started,
            "ended_at": utc_now(),
            "returncode": None,
            "ok": False,
            "timeout": True,
            "output": exc.stdout if isinstance(exc.stdout, str) else "",
            "error": repr(exc),
        }
    except Exception as exc:
        return {
            "name": name,
            "cmd": cmd,
            "started_at": started,
            "ended_at": utc_now(),
            "returncode": None,
            "ok": False,
            "error": repr(exc),
            "output": "",
        }


def latest_run_health() -> dict[str, Any]:
    run_dir = latest_run_dir()
    if not run_dir:
        return {"status": "no_runs_found"}

    artifacts = run_dir / "artifacts"
    logs = run_dir / "logs"

    metadata = read_json(run_dir / "run_metadata.json")
    run_id = run_dir.name

    counts = {
        "decisions": count_jsonl(artifacts / "paper_decisions.jsonl"),
        "trades": count_jsonl(artifacts / "paper_trades.jsonl"),
        "portfolio": count_jsonl(artifacts / "portfolio_state.jsonl"),
        "company_packets": count_jsonl(artifacts / "company_packets.jsonl"),
        "ledger_usage": count_jsonl(artifacts / "ledger_usage.jsonl"),
        "bridge_usage": count_jsonl(artifacts / "bridge_usage.jsonl"),
    }

    run_log = read_text(logs / "run.log")
    post_reports_log = read_text(logs / "post_run_reports.log")

    signals = {
        "has_post_run_reports_log": bool(post_reports_log),
        "hard_timeout_seen": "Hard timeout" in run_log or metadata.get("status") == "timed_out",
        "sigkill_seen": "SIGKILL" in run_log or metadata.get("worker_exit_code") == -9,
        "warehouse_ingest_completed": "Warehouse ingest completed" in run_log or "warehouse" in json.dumps(metadata).lower(),
        "no_decision_artifacts": counts["decisions"] == 0,
    }

    if counts["decisions"] > 0 and counts["trades"] > 0:
        verdict = "latest_run_has_trade_artifacts"
    elif counts["company_packets"] > 0 and counts["decisions"] == 0:
        verdict = "latest_run_packets_only_no_decisions"
    elif metadata.get("status") == "timed_out":
        verdict = "latest_run_timed_out"
    else:
        verdict = "latest_run_inconclusive"

    return {
        "status": "ok",
        "run_id": run_id,
        "path": str(run_dir),
        "metadata_status": metadata.get("status"),
        "supervisor_exit_code": metadata.get("supervisor_exit_code"),
        "duration_hours": metadata.get("duration_hours"),
        "hard_timeout_seconds": metadata.get("hard_timeout_seconds"),
        "counts": counts,
        "signals": signals,
        "verdict": verdict,
    }


def parse_gate_report(path: Path) -> dict[str, str]:
    text = read_text(path)
    result: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("Overall:"):
            result["overall"] = line.split(":", 1)[1].strip()
        elif line.startswith("- OK:") or line.startswith("- WARN:") or line.startswith("- FAIL:"):
            parts = line[2:].split(":", 1)
            if len(parts) == 2:
                status = parts[0].strip()
                name = parts[1].split("—", 1)[0].strip()
                result[name] = status
    return result


def build_board_packet(bundle: dict[str, Any]) -> str:
    readiness = parse_gate_report(REPORTS / "v2_readiness_gate.txt")
    run_health = bundle["latest_run_health"]

    lines = [
        "ACC V2 Triple Gate Board Packet",
        "===============================",
        f"Generated: {bundle['generated_at']}",
        "",
        "Executive Summary:",
    ]

    overall = readiness.get("overall", "unknown")
    lines.append(f"- V2 readiness overall: {overall}")
    lines.append(f"- Latest run verdict: {run_health.get('verdict', 'unknown')}")
    lines.append(f"- Latest run id: {run_health.get('run_id', 'none')}")

    counts = run_health.get("counts", {})
    if isinstance(counts, dict):
        lines.append(
            "- Latest run artifacts: "
            f"decisions={counts.get('decisions', 0)} "
            f"trades={counts.get('trades', 0)} "
            f"portfolio={counts.get('portfolio', 0)} "
            f"packets={counts.get('company_packets', 0)}"
        )

    lines.extend([
        "",
        "Readiness Checks:",
    ])

    for key in [
        "ML readiness",
        "Warehouse persistence",
        "Decision traces",
        "Token/cost telemetry",
        "Token budget guard",
        "Governance smoke",
        "Process supervisor",
        "Auto post-run reports",
    ]:
        if key in readiness:
            lines.append(f"- {readiness[key]}: {key}")

    lines.extend([
        "",
        "Operating Judgment:",
    ])

    if run_health.get("verdict") == "latest_run_has_trade_artifacts":
        lines.append("- Paper cycle produced trade artifacts. Continue short disciplined proof runs.")
    elif run_health.get("verdict") == "latest_run_packets_only_no_decisions":
        lines.append("- Latest cycle produced packets but no decisions. This may be cautious behavior or over-strict gating; inspect before assuming failure.")
    elif run_health.get("verdict") == "latest_run_timed_out":
        lines.append("- Latest cycle timed out. Supervisor worked, but worker graceful shutdown still needs improvement.")
    else:
        lines.append("- Latest cycle is inconclusive. Use short controlled proof, not serious paper run yet.")

    if readiness.get("Token budget guard") in {"WARN", "FAIL"}:
        lines.append("- Token budget status is not clean. Do not expand AI chatter.")
    else:
        lines.append("- Token budget guard is not blocking expansion, but keep calls disciplined.")

    lines.extend([
        "",
        "Recommended Next Actions:",
        "1. If governance smoke has not passed, run it in dry-run mode first.",
        "2. If latest run has zero decisions, inspect whether strict WAIT gating is correctly avoiding weak entries.",
        "3. Do not start a serious paper proof until readiness gate is OK or explicitly accepted with warnings.",
    ])

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ACC V2 triple gate: proof bundle, latest-run health, board packet.")
    parser.add_argument("--no-refresh", action="store_true", help="Do not refresh reports first.")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("ACC_V2_TRIPLE_GATE_TIMEOUT_SECONDS", "240")))
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)

    refresh_results: list[dict[str, Any]] = []

    if not args.no_refresh:
        commands = [
            ("ledger_usage_summary", [sys.executable, "tools/ledger_usage_summary.py"]),
            ("token_budget_guard", [sys.executable, "tools/token_budget_guard.py", "--no-refresh"]),
            ("v2_readiness_gate", [sys.executable, "tools/v2_readiness_gate.py", "--refresh"]),
        ]

        if (ROOT / "tools" / "v2_governance_smoke.py").exists():
            commands.append(("v2_governance_smoke_dry_run", [sys.executable, "tools/v2_governance_smoke.py"]))

        for name, cmd in commands:
            print(f"Running {name}...")
            result = run_cmd(name, cmd, timeout=args.timeout)
            refresh_results.append(result)
            print(f"- {name}: {'OK' if result.get('ok') else 'FAIL'} rc={result.get('returncode')}")

    bundle = {
        "generated_at": utc_now(),
        "refresh_results": refresh_results,
        "latest_run_health": latest_run_health(),
    }

    json_path = REPORTS / "v2_triple_gate.json"
    txt_path = REPORTS / "v2_triple_gate.txt"
    board_path = REPORTS / "v2_board_packet_latest.txt"

    json_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    board = build_board_packet(bundle)
    board_path.write_text(board, encoding="utf-8")

    lines = [
        "ACC V2 Triple Gate",
        "==================",
        f"Generated: {bundle['generated_at']}",
        "",
        "Refresh:",
    ]

    if refresh_results:
        for result in refresh_results:
            lines.append(f"- {'OK' if result.get('ok') else 'FAIL'}: {result['name']} rc={result.get('returncode')}")
    else:
        lines.append("- skipped")

    health = bundle["latest_run_health"]
    lines.extend([
        "",
        "Latest Run:",
        f"- run_id: {health.get('run_id', 'none')}",
        f"- verdict: {health.get('verdict', 'unknown')}",
        f"- metadata_status: {health.get('metadata_status', 'unknown')}",
    ])

    counts = health.get("counts", {})
    if isinstance(counts, dict):
        for key, value in counts.items():
            lines.append(f"- {key}: {value}")

    lines.extend([
        "",
        f"Wrote: {json_path}",
        f"Wrote: {txt_path}",
        f"Wrote: {board_path}",
    ])

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print("")
    print(board)

    failures = [r for r in refresh_results if not r.get("ok")]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
