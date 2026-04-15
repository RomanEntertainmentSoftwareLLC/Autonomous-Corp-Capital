#!/usr/bin/env python3
"""Robinhood-style live visibility charts for ACC portfolios.

Renders a dark-theme PNG that updates from portfolio_state.jsonl history:
- Top: total system equity curve over time
- Middle: normalized company equity curves over time
- Bottom: realized vs unrealized P/L over time

Can also watch and continuously overwrite the same PNG.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent.parent
LIVE_RUNS_ROOT = ROOT / "state" / "live_runs"
ROBINHOOD_GREEN = "#00C805"
ROBINHOOD_RED = "#FF5A5F"
BG = "#0B0B0B"
PANEL = "#111111"
GRID = "#232323"
TEXT = "#EDEDED"
MUTED = "#8A8F98"
COMPANY_COLORS = ["#5AC8FA", "#AF52DE", "#FFD60A", "#FF9F0A"]


@dataclass
class PortfolioPoint:
    timestamp: datetime
    company: str
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    cash: float


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


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def compute_market_value(positions_detail: Dict[str, Any]) -> float:
    total = 0.0
    for meta in (positions_detail or {}).values():
        if not isinstance(meta, dict):
            continue
        qty = safe_float(meta.get("qty"))
        mark = safe_float(meta.get("mark_price"), safe_float(meta.get("entry_price")))
        total += qty * mark
    return total


def compute_equity(row: Dict[str, Any]) -> float:
    cash = safe_float(row.get("cash"))
    market_value = compute_market_value(row.get("positions_detail") or {})

    # Real per-company equity = cash + marked positions.
    equity = cash + market_value

    # Fallback only if the row truly has no usable components.
    if abs(equity) > 1e-12:
        return equity

    for field in ("equity", "account_value"):
        if field in row:
            value = safe_float(row.get(field), None)
            if value is not None:
                return value

    return cash


def load_portfolio_history(run_dir: Path) -> List[PortfolioPoint]:
    portfolio_path = run_dir / "artifacts" / "portfolio_state.jsonl"
    if not portfolio_path.exists():
        return []
    points: List[PortfolioPoint] = []
    for raw in portfolio_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        company = str(row.get("company") or "").strip()
        if not company:
            continue
        ts = parse_timestamp(row.get("timestamp") or row.get("generated_at") or row.get("created_at"))
        if ts is None:
            continue
        points.append(
            PortfolioPoint(
                timestamp=ts,
                company=company,
                equity=compute_equity(row),
                realized_pnl=safe_float(row.get("realized_pnl")),
                unrealized_pnl=safe_float(row.get("unrealized_pnl")),
                cash=safe_float(row.get("cash")),
            )
        )
    points.sort(key=lambda p: (p.timestamp, p.company))
    return points


def company_order(points: Iterable[PortfolioPoint]) -> List[str]:
    seen: List[str] = []
    for p in points:
        if p.company not in seen:
            seen.append(p.company)
    preferred = ["company_001", "company_002", "company_003", "company_004"]
    if not seen:
        return preferred
    ordered = [c for c in preferred if c in seen]
    for c in seen:
        if c not in ordered:
            ordered.append(c)
    return ordered[:4]


def series_by_company(points: List[PortfolioPoint]) -> Dict[str, List[PortfolioPoint]]:
    out: Dict[str, List[PortfolioPoint]] = defaultdict(list)
    for p in points:
        out[p.company].append(p)
    return out


def build_system_series(points: List[PortfolioPoint], companies: List[str]) -> List[Tuple[datetime, float, float, float]]:
    if not points:
        return []

    grouped: Dict[datetime, List[PortfolioPoint]] = defaultdict(list)
    for p in points:
        grouped[p.timestamp].append(p)

    last_equity: Dict[str, float] = {}
    last_realized: Dict[str, float] = {}
    last_unrealized: Dict[str, float] = {}
    series: List[Tuple[datetime, float, float, float]] = []

    for ts in sorted(grouped.keys()):
        for p in grouped[ts]:
            if p.company not in companies:
                continue
            last_equity[p.company] = p.equity
            last_realized[p.company] = p.realized_pnl
            last_unrealized[p.company] = p.unrealized_pnl

        if len(last_equity) < len(companies):
            continue

        total_equity = sum(last_equity[c] for c in companies)
        total_realized = sum(last_realized.get(c, 0.0) for c in companies)
        total_unrealized = sum(last_unrealized.get(c, 0.0) for c in companies)
        series.append((ts, total_equity, total_realized, total_unrealized))

    return series


def normalize_company_curve(points: List[PortfolioPoint]) -> List[Tuple[datetime, float]]:
    if not points:
        return []
    baseline = points[0].equity if abs(points[0].equity) > 1e-12 else 1.0
    return [(p.timestamp, ((p.equity / baseline) - 1.0) * 100.0) for p in points]


def style_axes(ax: plt.Axes) -> None:
    ax.set_facecolor(PANEL)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(True, color=GRID, linewidth=0.8, alpha=0.7)
    ax.tick_params(colors=TEXT)
    ax.xaxis.label.set_color(TEXT)
    ax.yaxis.label.set_color(TEXT)
    ax.title.set_color(TEXT)


def money_fmt(value: float, _pos: int | None = None) -> str:
    return f"${value:,.2f}"


def percent_fmt(value: float, _pos: int | None = None) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def compact_time_axis(ax: plt.Axes) -> None:
    locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)


def atomic_save(fig: plt.Figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f"{output.stem}.tmp{output.suffix}")
    fig.savefig(tmp, dpi=160, facecolor=BG, edgecolor=BG, format="png")
    tmp.replace(output)


def render(output: Path, run_dir: Path | None = None, max_points: int = 1200) -> Dict[str, Any]:
    run_dir = run_dir or latest_run_dir()
    if run_dir is None:
        raise FileNotFoundError("No live run directory found.")

    points = load_portfolio_history(run_dir)
    if not points:
        raise FileNotFoundError(f"No portfolio history found at {run_dir / 'artifacts' / 'portfolio_state.jsonl'}")

    companies = company_order(points)
    company_points = series_by_company(points)
    companies = [c for c in companies if c in company_points]
    system_series = build_system_series(points, companies)

    # Downsample lightly if the run gets long.
    def thin[T](items: List[T]) -> List[T]:
        if len(items) <= max_points:
            return items
        step = max(1, len(items) // max_points)
        return items[::step] + ([items[-1]] if items[-1] is not items[::step][-1] else [])

    system_series = thin(system_series)
    for company in list(company_points.keys()):
        company_points[company] = thin(company_points[company])

    system_times = [ts for ts, _eq, _rp, _up in system_series]
    system_equity = [eq for _ts, eq, _rp, _up in system_series]
    system_realized = [rp for _ts, _eq, rp, _up in system_series]
    system_unrealized = [up for _ts, _eq, _rp, up in system_series]

    system_baseline = system_equity[0] if system_equity else 0.0
    current_equity = system_equity[-1] if system_equity else 0.0
    current_realized = system_realized[-1] if system_realized else 0.0
    current_unrealized = system_unrealized[-1] if system_unrealized else 0.0
    total_pnl = current_realized + current_unrealized
    total_pct = ((current_equity / system_baseline) - 1.0) * 100.0 if system_baseline else 0.0

    fig = plt.figure(figsize=(14, 9), facecolor=BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[2.4, 1.5, 1.1], hspace=0.18)
    ax_main = fig.add_subplot(gs[0])
    ax_companies = fig.add_subplot(gs[1], sharex=ax_main)
    ax_pnl = fig.add_subplot(gs[2], sharex=ax_main)

    for ax in (ax_main, ax_companies, ax_pnl):
        style_axes(ax)
        compact_time_axis(ax)

    # Main chart: total equity curve.
    line_color = ROBINHOOD_GREEN if current_equity >= system_baseline else ROBINHOOD_RED
    ax_main.plot(system_times, system_equity, linewidth=2.5, color=line_color)
    ax_main.fill_between(system_times, system_equity, [system_baseline] * len(system_times), color=line_color, alpha=0.05)
    ax_main.axhline(system_baseline, color=MUTED, linewidth=1.0, linestyle="--", alpha=0.8)
    ax_main.yaxis.set_major_formatter(FuncFormatter(money_fmt))
    ax_main.set_ylabel("System equity")
    ax_main.set_title("ACC Paper Trading — Live Portfolio")

    header_left = f"${current_equity:,.2f}"
    pnl_sign = "+" if total_pnl >= 0 else ""
    header_right = f"{pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pct:.2f}%)"
    ax_main.text(0.01, 0.97, header_left, transform=ax_main.transAxes, va="top", ha="left", color=TEXT, fontsize=22, fontweight="bold")
    ax_main.text(0.01, 0.88, header_right, transform=ax_main.transAxes, va="top", ha="left", color=line_color, fontsize=12, fontweight="bold")
    ax_main.text(0.99, 0.97, run_dir.name, transform=ax_main.transAxes, va="top", ha="right", color=MUTED, fontsize=10)

    # Company comparison chart: normalized return curves.
    for idx, company in enumerate(companies):
        normalized = normalize_company_curve(company_points[company])
        if not normalized:
            continue
        xs = [ts for ts, _ in normalized]
        ys = [ret for _ts, ret in normalized]
        color = COMPANY_COLORS[idx % len(COMPANY_COLORS)]
        ax_companies.plot(xs, ys, linewidth=1.8, color=color, label=company)
        ax_companies.text(xs[-1], ys[-1], f" {company}", color=color, va="center", fontsize=9)
    ax_companies.axhline(0.0, color=MUTED, linewidth=1.0, linestyle="--", alpha=0.8)
    ax_companies.set_ylabel("Company return")
    ax_companies.yaxis.set_major_formatter(FuncFormatter(percent_fmt))
    ax_companies.set_title("Company Equity Curves")

    # P/L composition.
    ax_pnl.plot(system_times, system_realized, linewidth=2.0, color="#4CAF50", label="Realized P/L")
    ax_pnl.plot(system_times, system_unrealized, linewidth=2.0, color="#FF9800", label="Unrealized P/L")
    ax_pnl.fill_between(system_times, system_realized, color="#4CAF50", alpha=0.08)
    ax_pnl.fill_between(system_times, system_unrealized, color="#FF9800", alpha=0.08)
    ax_pnl.axhline(0.0, color=MUTED, linewidth=1.0, linestyle="--", alpha=0.8)
    ax_pnl.yaxis.set_major_formatter(FuncFormatter(money_fmt))
    ax_pnl.set_ylabel("P/L")
    ax_pnl.set_title("Realized vs Unrealized")
    ax_pnl.legend(loc="upper left", facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT)

    plt.setp(ax_main.get_xticklabels(), visible=False)
    plt.setp(ax_companies.get_xticklabels(), visible=False)
    ax_pnl.set_xlabel("Time")

    atomic_save(fig, output)
    plt.close(fig)

    latest_company_snapshots = []
    for company in companies:
        pts = company_points[company]
        if not pts:
            continue
        initial = pts[0].equity if pts else 0.0
        latest = pts[-1]
        latest_company_snapshots.append(
            {
                "company": company,
                "baseline_equity": initial,
                "account_value": latest.equity,
                "realized_pnl": latest.realized_pnl,
                "unrealized_pnl": latest.unrealized_pnl,
                "total_pnl": latest.realized_pnl + latest.unrealized_pnl,
                "pct_return": ((latest.equity / initial) - 1.0) * 100.0 if initial else 0.0,
            }
        )

    return {
        "output": str(output),
        "run_dir": str(run_dir),
        "points": len(points),
        "companies": latest_company_snapshots,
        "system_baseline": system_baseline,
        "total_equity": current_equity,
        "total_realized_pnl": current_realized,
        "total_unrealized_pnl": current_unrealized,
        "total_system_pnl": total_pnl,
        "total_system_pct": total_pct,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Robinhood-style visibility charts from live portfolio history")
    run_dir = latest_run_dir()
    default_output = (run_dir / "reports" / "visibility_charts.png") if run_dir else (ROOT / "visibility_charts.png")
    parser.add_argument("--output", type=Path, default=default_output, help="PNG output path")
    parser.add_argument("--run-dir", type=Path, default=None, help="Specific run directory to read from")
    parser.add_argument("--watch", action="store_true", help="Continuously update the same PNG")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between updates in watch mode")
    parser.add_argument("--max-points", type=int, default=1200, help="Maximum points per curve before light thinning")
    return parser.parse_args()


def compact_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    companies = {}
    for item in summary.get("companies", []):
        companies[item["company"]] = {
            "equity": round(float(item.get("account_value", 0.0)), 4),
            "pnl": round(float(item.get("total_pnl", 0.0)), 4),
            "pct": round(float(item.get("pct_return", 0.0)), 4),
        }

    return {
        "run_id": Path(summary["run_dir"]).name,
        "points": summary.get("points"),
        "system": {
            "baseline": round(float(summary.get("system_baseline", 0.0)), 4),
            "equity": round(float(summary.get("total_equity", 0.0)), 4),
            "realized_pnl": round(float(summary.get("total_realized_pnl", 0.0)), 4),
            "unrealized_pnl": round(float(summary.get("total_unrealized_pnl", 0.0)), 4),
            "total_pnl": round(float(summary.get("total_system_pnl", 0.0)), 4),
            "pct": round(float(summary.get("total_system_pct", 0.0)), 4),
        },
        "companies": companies,
    }

def main() -> None:
    args = parse_args()
    last_printed = None

    if args.watch:
        try:
            while True:
                summary = render(args.output, run_dir=args.run_dir, max_points=args.max_points)
                compact = compact_summary(summary)
                payload = json.dumps(compact, separators=(",", ":"))

                if payload != last_printed:
                    print(payload)
                    last_printed = payload

                time.sleep(max(0.5, args.interval))
        except KeyboardInterrupt:
            return
    else:
        summary = render(args.output, run_dir=args.run_dir, max_points=args.max_points)
        print(json.dumps(compact_summary(summary), indent=2))


if __name__ == "__main__":
    main()
