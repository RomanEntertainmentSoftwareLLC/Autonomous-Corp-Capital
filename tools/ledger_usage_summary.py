#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "live_runs"
REPORTS = ROOT / "reports"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def num(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def pick(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize ACC token/LLM usage telemetry from recent live runs.")
    parser.add_argument("--limit-runs", type=int, default=20)
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)

    run_dirs = sorted(STATE.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True)[: args.limit_runs]

    usage_rows: list[dict[str, Any]] = []
    source_counts = Counter()

    for run_dir in run_dirs:
        for name in ("ledger_usage.jsonl", "bridge_usage.jsonl"):
            path = run_dir / "artifacts" / name
            rows = read_jsonl(path)
            source_counts[name] += len(rows)
            for row in rows:
                row["_run_id"] = run_dir.name
                row["_source_file"] = name
                usage_rows.append(row)

    by_agent: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_model: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_provider: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    total_prompt = total_completion = total_tokens = total_cost = 0.0

    for row in usage_rows:
        agent = str(pick(row, "agent", "agent_id", "name", default="unknown"))
        model = str(pick(row, "model", "model_name", default="unknown"))
        provider = str(pick(row, "provider", default=model.split("/", 1)[0] if "/" in model else "unknown"))

        prompt_tokens = num(pick(row, "prompt_tokens", "input_tokens", "tokens_in", default=0))
        completion_tokens = num(pick(row, "completion_tokens", "output_tokens", "tokens_out", default=0))
        row_total = num(pick(row, "total_tokens", "tokens_total", default=prompt_tokens + completion_tokens))
        estimated_cost = num(pick(row, "estimated_cost", "cost", "cost_usd", "estimated_cost_usd", default=0))

        total_prompt += prompt_tokens
        total_completion += completion_tokens
        total_tokens += row_total
        total_cost += estimated_cost

        for bucket, key in ((by_agent, agent), (by_model, model), (by_provider, provider)):
            bucket[key]["calls"] += 1
            bucket[key]["prompt_tokens"] += prompt_tokens
            bucket[key]["completion_tokens"] += completion_tokens
            bucket[key]["total_tokens"] += row_total
            bucket[key]["estimated_cost"] += estimated_cost

    summary = {
        "generated_at": utc_now(),
        "run_dirs_scanned": [p.name for p in run_dirs],
        "usage_rows": len(usage_rows),
        "source_counts": dict(source_counts),
        "totals": {
            "calls": len(usage_rows),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "estimated_cost": total_cost,
        },
        "by_agent": by_agent,
        "by_model": by_model,
        "by_provider": by_provider,
        "verdict": "usage_found" if usage_rows else "no_usage_rows_found",
    }

    json_path = REPORTS / "ledger_usage_summary.json"
    txt_path = REPORTS / "ledger_usage_summary.txt"

    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def top_lines(title: str, data: dict[str, dict[str, float]]) -> list[str]:
        lines = [title, "-" * len(title)]
        ranked = sorted(data.items(), key=lambda kv: kv[1].get("total_tokens", 0), reverse=True)
        if not ranked:
            lines.append("(none)")
            return lines
        for key, vals in ranked[:15]:
            lines.append(
                f"{key}: calls={int(vals.get('calls', 0))} "
                f"tokens={int(vals.get('total_tokens', 0))} "
                f"cost={vals.get('estimated_cost', 0):.6f}"
            )
        return lines

    lines = [
        "ACC Ledger Usage Summary",
        "========================",
        f"Generated: {summary['generated_at']}",
        f"Verdict: {summary['verdict']}",
        f"Runs scanned: {len(run_dirs)}",
        f"Usage rows: {len(usage_rows)}",
        "",
        "Totals:",
        f"- calls: {len(usage_rows)}",
        f"- prompt_tokens: {int(total_prompt)}",
        f"- completion_tokens: {int(total_completion)}",
        f"- total_tokens: {int(total_tokens)}",
        f"- estimated_cost: {total_cost:.6f}",
        "",
        *top_lines("By agent", by_agent),
        "",
        *top_lines("By model", by_model),
        "",
        *top_lines("By provider", by_provider),
        "",
        f"Wrote: {json_path}",
        f"Wrote: {txt_path}",
    ]

    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
