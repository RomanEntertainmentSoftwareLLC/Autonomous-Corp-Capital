#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/opt/openclaw/.openclaw/workspace")
REPORTS = ROOT / "reports"

CHAIN = [
    ("ledger", ["python3", "tools/ledger_cost_review.py"]),
    ("helena", ["python3", "tools/helena_risk_review.py"]),
    ("axiom", ["python3", "tools/axiom_evaluator_review.py"]),
    ("vivienne", ["python3", "tools/vivienne_financial_review.py"]),
    ("selene", ["python3", "tools/selene_treasury_review.py"]),
    ("ariadne", ["python3", "tools/ariadne_workforce_review.py"]),
    ("grant", ["python3", "tools/grant_speech_review.py"]),
    ("yam_yam", ["python3", "tools/yam_yam_executive_review.py"]),
    ("june", ["python3", "tools/june_archive_review.py"]),
]


def _run(name: str, cmd: list[str], timeout: int = 360) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout)
        return {
            "name": name,
            "cmd": cmd,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-5000:],
            "stderr": (proc.stderr or "")[-5000:],
        }
    except Exception as exc:
        return {"name": name, "cmd": cmd, "ok": False, "error": str(exc), "stdout": "", "stderr": ""}


def main() -> None:
    parser = argparse.ArgumentParser(description="Manually run the full post-run governance chain against the latest run.")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to each review tool.")
    parser.add_argument("--stop-on-fail", action="store_true")
    parser.add_argument("--skip-grant", action="store_true")
    parser.add_argument("--skip-june", action="store_true")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    results = []

    for name, base_cmd in CHAIN:
        if name == "grant" and args.skip_grant:
            continue
        if name == "june" and args.skip_june:
            continue
        cmd = list(base_cmd)
        if args.dry_run:
            cmd.append("--dry-run")
        print(f"=== Running {name}: {' '.join(cmd)}")
        result = _run(name, cmd)
        results.append(result)
        print("OK" if result.get("ok") else "FAILED")
        if result.get("stdout"):
            print(result["stdout"][-1200:])
        if result.get("stderr"):
            print(result["stderr"][-1200:])
        if args.stop_on_fail and not result.get("ok"):
            break

    ok_count = sum(1 for r in results if r.get("ok"))
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "ok_count": ok_count,
        "total": len(results),
        "results": results,
    }
    out_json = REPORTS / f"post_run_governance_runner_{stamp}.json"
    out_txt = REPORTS / f"post_run_governance_runner_{stamp}.txt"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["ACC Post-Run Governance Runner", "=" * 31, "", f"Dry run: {args.dry_run}", f"OK: {ok_count}/{len(results)}", ""]
    for r in results:
        lines.append(f"- {'OK' if r.get('ok') else 'FAIL'} {r['name']} :: {' '.join(r.get('cmd', []))}")
        if not r.get("ok"):
            lines.append(f"  error: {r.get('error') or r.get('stderr') or r.get('stdout')}")
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("")
    print(f"Wrote: {out_txt}")
    print(f"Wrote: {out_json}")


if __name__ == "__main__":
    main()
