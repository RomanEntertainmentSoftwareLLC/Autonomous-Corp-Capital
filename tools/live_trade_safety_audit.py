#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)

    systemd = read(ROOT / "scripts" / "live_run_systemd.py")
    live_run = read(ROOT / "tools" / "live_run.py")

    checks: list[dict[str, Any]] = [
        {
            "name": "supervisor_has_live_trade_flag",
            "ok": 'parser.add_argument("--live-trade"' in systemd,
            "detail": "scripts/live_run_systemd.py exposes explicit --live-trade flag",
        },
        {
            "name": "paper_default_safe",
            "ok": '"live" if live_trade else "paper"' in systemd and "assert_live_trade_safety(live_trade)" in systemd,
            "detail": "supervisor defaults to paper and checks live-trade gate first",
        },
        {
            "name": "requires_enable_env",
            "ok": "ACC_ENABLE_LIVE_TRADING" in systemd,
            "detail": "live trading requires ACC_ENABLE_LIVE_TRADING",
        },
        {
            "name": "requires_confirm_phrase",
            "ok": "ACC_LIVE_TRADE_CONFIRM" in systemd and "I_UNDERSTAND_THIS_IS_REAL_MONEY" in systemd,
            "detail": "live trading requires exact real-money confirmation phrase",
        },
        {
            "name": "worker_receives_live_trade",
            "ok": "live_trade=bool(args.live_trade)" in systemd and 'child_cmd.append("--live-trade")' in systemd,
            "detail": "supervisor passes explicit live-trade request to worker child",
        },
        {
            "name": "worker_mode_env_set",
            "ok": 'child_env["LIVE_RUN_MODE"] = "live" if live_trade else "paper"' in systemd,
            "detail": "worker child receives LIVE_RUN_MODE based on explicit supervisor mode",
        },
        {
            "name": "legacy_live_run_has_flag",
            "ok": 'start_parser.add_argument("--live-trade"' in live_run and 'run_parser.add_argument("--live-trade"' in live_run,
            "detail": "tools/live_run.py has explicit --live-trade flags for legacy/internal CLI",
        },
        {
            "name": "legacy_live_run_blocks_env_only_live",
            "ok": 'Live trading requires explicit --live-trade' in live_run,
            "detail": "tools/live_run.py refuses env-only LIVE_RUN_MODE=live without flag",
        },
    ]

    ok_count = sum(1 for c in checks if c["ok"])
    fail_count = len(checks) - ok_count
    verdict = "live_trade_default_safe" if fail_count == 0 else "live_trade_safety_incomplete"

    summary = {
        "generated_at": utc_now(),
        "verdict": verdict,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "checks": checks,
    }

    json_path = REPORTS / "live_trade_safety_audit.json"
    txt_path = REPORTS / "live_trade_safety_audit.txt"

    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "ACC Live Trade Safety Audit",
        "===========================",
        f"Generated: {summary['generated_at']}",
        f"Verdict: {verdict}",
        f"OK={ok_count} FAIL={fail_count}",
        "",
        "Checks:",
    ]

    for check in checks:
        status = "OK" if check["ok"] else "FAIL"
        lines.append(f"- {status}: {check['name']} — {check['detail']}")

    lines.extend([
        "",
        f"Wrote: {json_path}",
        f"Wrote: {txt_path}",
    ])

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
