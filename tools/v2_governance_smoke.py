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
REPORTS = ROOT / "reports"

CHAIN = [
    ("ledger", "tools/ledger_cost_review.py"),
    ("helena", "tools/helena_risk_review.py"),
    ("axiom", "tools/axiom_evaluator_review.py"),
    ("vivienne", "tools/vivienne_financial_review.py"),
    ("yam_yam", "tools/yam_yam_executive_review.py"),
]

OPTIONAL_GRANT = ("grant_cardone", "tools/grant_speech_review.py")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_tool(name: str, script: str, *, apply: bool, timeout: int) -> dict[str, Any]:
    cmd = [sys.executable, script]
    if not apply:
        cmd.append("--dry-run")

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
            "script": script,
            "cmd": cmd,
            "mode": "apply" if apply else "dry_run",
            "started_at": started,
            "ended_at": utc_now(),
            "returncode": completed.returncode,
            "ok": completed.returncode == 0,
            "output": completed.stdout or "",
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "script": script,
            "cmd": cmd,
            "mode": "apply" if apply else "dry_run",
            "started_at": started,
            "ended_at": utc_now(),
            "returncode": None,
            "ok": False,
            "timeout": True,
            "output": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "error": repr(exc),
        }

    except Exception as exc:
        return {
            "name": name,
            "script": script,
            "cmd": cmd,
            "mode": "apply" if apply else "dry_run",
            "started_at": started,
            "ended_at": utc_now(),
            "returncode": None,
            "ok": False,
            "error": repr(exc),
            "output": "",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ACC V2 governance smoke chain.")
    parser.add_argument("--apply", action="store_true", help="Run governance tools for real instead of --dry-run.")
    parser.add_argument("--include-grant", action="store_true", help="Also run Grant's controlled revenue review.")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("ACC_GOVERNANCE_SMOKE_TIMEOUT_SECONDS", "180")))
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)

    chain = list(CHAIN)
    if args.include_grant:
        chain.append(OPTIONAL_GRANT)

    started_at = utc_now()
    results = []

    print("ACC V2 Governance Smoke")
    print("=======================")
    print(f"Mode: {'apply' if args.apply else 'dry-run'}")
    print(f"Tools: {', '.join(name for name, _ in chain)}")
    print("")

    for name, script in chain:
        print(f"Running {name}: {script}")
        result = run_tool(name, script, apply=args.apply, timeout=args.timeout)
        results.append(result)

        status = "OK" if result["ok"] else "FAIL"
        extra = " timeout" if result.get("timeout") else ""
        print(f"- {name}: {status}{extra} rc={result.get('returncode')}")

    ok_count = sum(1 for r in results if r.get("ok"))

    summary = {
        "started_at": started_at,
        "ended_at": utc_now(),
        "mode": "apply" if args.apply else "dry_run",
        "ok_count": ok_count,
        "total": len(results),
        "success": ok_count == len(results),
        "chain_order": [name for name, _ in chain],
        "results": results,
    }

    json_path = REPORTS / "v2_governance_smoke_latest.json"
    txt_path = REPORTS / "v2_governance_smoke_latest.txt"

    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "ACC V2 Governance Smoke",
        "=======================",
        f"Started: {summary['started_at']}",
        f"Ended: {summary['ended_at']}",
        f"Mode: {summary['mode']}",
        f"Result: {ok_count}/{len(results)} OK",
        "",
        "Chain:",
    ]

    for result in results:
        lines.append(
            f"- {result['name']}: {'OK' if result.get('ok') else 'FAIL'} "
            f"rc={result.get('returncode')} script={result['script']}"
        )

    lines.extend(["", "Output excerpts:"])

    for result in results:
        output = (result.get("output") or "").strip()
        excerpt = "\n".join(output.splitlines()[-20:]) if output else "(no output)"
        lines.extend([
            "",
            f"## {result['name']}",
            excerpt,
        ])

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("")
    print(f"Report: {txt_path}")
    print(f"JSON:   {json_path}")
    print(f"Result: {ok_count}/{len(results)} OK")

    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
