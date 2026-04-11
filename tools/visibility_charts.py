#!/usr/bin/env python3
"""Minimal matplotlib visibility charts for 4-company progress and system P/L."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
LEADERBOARD_PATH = ROOT / "leaderboard.json"
LIVE_RUNS_ROOT = ROOT / "state" / "live_runs"
BASELINE_ACCOUNT_VALUE = 100.0


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def latest_run_dir() -> Path | None:
    if not LIVE_RUNS_ROOT.exists():
        return None
    runs = [p for p in LIVE_RUNS_ROOT.iterdir() if p.is_dir() and p.name.startswith("run_")]
    if not runs:
        return None
    return max(runs, key=lambda p: p.stat().st_mtime)


def company_order_from_digest() -> List[str]:
    run_dir = latest_run_dir()
    if not run_dir:
        return []
    digest = load_json(run_dir / "reports" / "daily_digest.json", {})
    activities = digest.get("top_company_activity") or []
    order: List[str] = []
    for item in activities:
        company = str(item.get("company_id") or "").strip()
        if company and company not in order:
            order.append(company)
    return order


def leaderboard_rows() -> List[Dict[str, Any]]:
    data = load_json(LEADERBOARD_PATH, {})
    rows = data.get("rows") or []
    return [row for row in rows if isinstance(row, dict)]


def pick_company_snapshot(company: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    company_rows = [row for row in rows if str(row.get("company")) == company]
    if not company_rows:
        return {
            "company": company,
            "mode": "missing",
            "account_value": BASELINE_ACCOUNT_VALUE,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
        }
    for row in company_rows:
        if str(row.get("mode")) == "paper":
            return row
    return company_rows[0]


def build_company_series(companies: List[str], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not companies:
        companies = sorted({str(row.get("company")) for row in rows if row.get("company")})
    if len(companies) < 4:
        known = ["company_001", "company_002", "company_003", "company_004"]
        for company in known:
            if company not in companies:
                companies.append(company)
    companies = companies[:4]
    series: List[Dict[str, Any]] = []
    for company in companies:
        snapshot = pick_company_snapshot(company, rows)
        account_value = float(snapshot.get("account_value") or BASELINE_ACCOUNT_VALUE)
        realized = float(snapshot.get("realized_pnl") or 0.0)
        unrealized = float(snapshot.get("unrealized_pnl") or 0.0)
        series.append(
            {
                "company": company,
                "account_value": account_value,
                "progress": account_value - BASELINE_ACCOUNT_VALUE,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "total_pnl": realized + unrealized,
                "mode": str(snapshot.get("mode") or "<none>"),
            }
        )
    return series


def render(output: Path) -> Dict[str, Any]:
    rows = leaderboard_rows()
    companies = company_order_from_digest()
    series = build_company_series(companies, rows)

    total_realized = sum(item["realized_pnl"] for item in series)
    total_unrealized = sum(item["unrealized_pnl"] for item in series)
    total_system_pnl = total_realized + total_unrealized

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), constrained_layout=True)

    # Chart 1: 4-company portfolio progress.
    ax = axes[0]
    x = list(range(len(series)))
    progress_values = [item["progress"] for item in series]
    colors = ["#4C78A8" if value >= 0 else "#E45756" for value in progress_values]
    bars = ax.bar(x, progress_values, color=colors, width=0.62)
    ax.axhline(0.0, color="#444", linewidth=1)
    ax.set_title("4-Company Portfolio Progress")
    ax.set_ylabel(f"Progress vs ${BASELINE_ACCOUNT_VALUE:,.0f} baseline")
    ax.set_xticks(x)
    ax.set_xticklabels([item["company"] for item in series], rotation=0)
    for bar, item in zip(bars, series):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"${item['account_value']:,.0f}",
            ha="center",
            va="bottom" if bar.get_height() >= 0 else "top",
            fontsize=9,
        )
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            0,
            item["mode"],
            ha="center",
            va="bottom",
            fontsize=8,
            color="#666",
        )

    # Chart 2: total system P/L.
    ax = axes[1]
    ax.bar([0], [total_realized], color="#54A24B", width=0.5, label="Realized P/L")
    ax.bar([0], [total_unrealized], bottom=[total_realized], color="#F58518", width=0.5, label="Unrealized P/L")
    ax.axhline(0.0, color="#444", linewidth=1)
    ax.set_title("Total System Profit / Loss")
    ax.set_ylabel("P/L")
    ax.set_xticks([0])
    ax.set_xticklabels(["system"])
    ax.legend(loc="best")
    ax.text(
        0,
        total_system_pnl,
        f"${total_system_pnl:,.2f}",
        ha="center",
        va="bottom" if total_system_pnl >= 0 else "top",
        fontsize=10,
        fontweight="bold",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)

    return {
        "output": str(output),
        "companies": series,
        "total_realized_pnl": total_realized,
        "total_unrealized_pnl": total_unrealized,
        "total_system_pnl": total_system_pnl,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render minimal visibility charts from live artifacts")
    default_output = None
    run_dir = latest_run_dir()
    if run_dir:
        default_output = run_dir / "reports" / "visibility_charts.png"
    else:
        default_output = ROOT / "visibility_charts.png"
    parser.add_argument("--output", type=Path, default=default_output, help="PNG output path")
    args = parser.parse_args()

    summary = render(args.output)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
