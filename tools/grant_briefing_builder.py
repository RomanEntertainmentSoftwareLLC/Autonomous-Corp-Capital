#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/opt/openclaw/.openclaw/workspace")
RUNS_DIR = ROOT / "state" / "live_runs"
MEMORY_DIR = ROOT / "ai_agents_memory"


COMPANIES = ["company_001", "company_002", "company_003", "company_004"]


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
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


def latest_run_dir() -> Path:
    runs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    if not runs:
        raise SystemExit(f"No run folders found under {RUNS_DIR}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def run_dir_from_arg(run_id: str | None) -> Path:
    if not run_id:
        return latest_run_dir()
    p = RUNS_DIR / run_id
    if not p.exists():
        raise SystemExit(f"Run folder not found: {p}")
    return p


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def latest_by_company(rows: list[dict[str, Any]], company_key: str = "company") -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        company = row.get(company_key)
        if not isinstance(company, str):
            continue
        latest[company] = row
    return latest


def position_value(snapshot: dict[str, Any]) -> float:
    positions_detail = snapshot.get("positions_detail") or {}
    total = 0.0
    if isinstance(positions_detail, dict):
        for detail in positions_detail.values():
            if not isinstance(detail, dict):
                continue
            qty = safe_float(detail.get("qty"))
            mark = safe_float(detail.get("mark_price"))
            total += qty * mark
    return total


def build_company_scoreboard(
    allocation: dict[str, Any],
    portfolio_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    decision_rows: list[dict[str, Any]],
    packet_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    per_alloc = allocation.get("per_company_allocation") or {}
    latest_portfolio = latest_by_company(portfolio_rows, "company")

    trades_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trade_rows:
        company = row.get("company_id")
        if isinstance(company, str):
            trades_by_company[company].append(row)

    decisions_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in decision_rows:
        company = row.get("company_id")
        if isinstance(company, str):
            decisions_by_company[company].append(row)

    packets_by_company: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in packet_rows:
        company = row.get("company_id")
        if isinstance(company, str):
            packets_by_company[company].append(row)

    companies: dict[str, Any] = {}

    for company in COMPANIES:
        snap = latest_portfolio.get(company, {})
        start_alloc = safe_float(per_alloc.get(company), 0.0)
        cash = safe_float(snap.get("cash"))
        pos_value = position_value(snap)
        equity = cash + pos_value if snap else 0.0

        realized = safe_float(snap.get("realized_pnl"))
        unrealized = safe_float(snap.get("unrealized_pnl"))
        pnl_vs_alloc = equity - start_alloc if start_alloc else realized + unrealized

        company_trades = trades_by_company.get(company, [])
        company_decisions = decisions_by_company.get(company, [])
        company_packets = packets_by_company.get(company, [])

        actions = Counter(str(t.get("action")) for t in company_trades if t.get("action"))
        decisions = Counter(str(d.get("decision")) for d in company_decisions if d.get("decision"))
        execution_states = Counter(str(d.get("execution_state")) for d in company_decisions if d.get("execution_state"))
        policy_names = Counter(str(d.get("policy_name")) for d in company_decisions if d.get("policy_name"))

        fallback_packets = sum(1 for p in company_packets if p.get("packet_generation_mode") == "fallback")
        fresh_packets = sum(1 for p in company_packets if p.get("fresh_committee") is True)

        missing_flags = Counter()
        timeout_count = 0
        for packet in company_packets:
            for flag in packet.get("missing_input_flags") or []:
                missing_flags[str(flag)] += 1
            fallback_reason = str(packet.get("fallback_reason") or "")
            if "timed out" in fallback_reason.lower():
                timeout_count += 1

        if pnl_vs_alloc > 0.01:
            status = "positive"
        elif pnl_vs_alloc < -0.01:
            status = "negative"
        elif snap:
            status = "flat"
        else:
            status = "no_snapshot"

        companies[company] = {
            "starting_allocation": round(start_alloc, 8),
            "cash": round(cash, 8),
            "position_value": round(pos_value, 8),
            "equity": round(equity, 8),
            "realized_pnl": round(realized, 8),
            "unrealized_pnl": round(unrealized, 8),
            "pnl_vs_allocation": round(pnl_vs_alloc, 8),
            "open_positions_count": int(safe_float(snap.get("open_positions_count"), 0.0)),
            "positions": snap.get("positions", {}),
            "trade_count": len(company_trades),
            "trade_actions": dict(actions),
            "decision_count": len(company_decisions),
            "decisions": dict(decisions),
            "execution_states": dict(execution_states),
            "policy_names": dict(policy_names),
            "packet_count": len(company_packets),
            "fallback_packets": fallback_packets,
            "fresh_committee_packets": fresh_packets,
            "timeout_count": timeout_count,
            "missing_input_flags": dict(missing_flags),
            "status": status,
        }

    ranked = sorted(
        companies.items(),
        key=lambda kv: kv[1]["pnl_vs_allocation"],
        reverse=True,
    )

    for idx, (company, _) in enumerate(ranked, start=1):
        companies[company]["rank"] = idx

    return {
        "companies": companies,
        "leader": ranked[0][0] if ranked else None,
        "laggard": ranked[-1][0] if ranked else None,
        "ranked": [
            {
                "company": company,
                "pnl_vs_allocation": data["pnl_vs_allocation"],
                "status": data["status"],
                "rank": data["rank"],
            }
            for company, data in ranked
        ],
    }


def build_market_summary(run_dir: Path) -> dict[str, Any]:
    rows = read_jsonl(run_dir / "data" / "market_feed.log")
    if not rows:
        return {
            "condition": "unknown",
            "bias": "unknown",
            "volatility": "unknown",
            "symbols_seen": 0,
            "summary": "No market feed rows were available.",
        }

    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        symbol = row.get("symbol")
        if isinstance(symbol, str):
            by_symbol[symbol].append(row)

    movers = []
    up = down = flat = 0
    abs_moves = []

    for symbol, items in by_symbol.items():
        if len(items) < 2:
            continue
        first = safe_float(items[0].get("price"))
        last = safe_float(items[-1].get("price"))
        if first <= 0:
            continue
        pct = ((last - first) / first) * 100.0
        abs_moves.append(abs(pct))
        if pct > 0.01:
            up += 1
        elif pct < -0.01:
            down += 1
        else:
            flat += 1
        movers.append({
            "symbol": symbol,
            "first": first,
            "last": last,
            "pct_change": round(pct, 6),
            "tier": items[-1].get("tier"),
        })

    total = up + down + flat
    if total == 0:
        condition = "unknown"
        bias = "unknown"
    else:
        up_ratio = up / total
        down_ratio = down / total
        if up_ratio >= 0.55:
            condition = "green"
            bias = "bullish"
        elif down_ratio >= 0.55:
            condition = "red"
            bias = "bearish"
        else:
            condition = "mixed"
            bias = "choppy"

    avg_abs = sum(abs_moves) / len(abs_moves) if abs_moves else 0.0
    if avg_abs >= 1.0:
        volatility = "high"
    elif avg_abs >= 0.25:
        volatility = "medium"
    else:
        volatility = "low"

    movers_sorted = sorted(movers, key=lambda m: abs(m["pct_change"]), reverse=True)

    return {
        "condition": condition,
        "bias": bias,
        "volatility": volatility,
        "symbols_seen": len(by_symbol),
        "symbols_with_change": total,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "avg_abs_pct_change": round(avg_abs, 6),
        "top_movers": movers_sorted[:10],
        "summary": f"Market appears {condition}/{bias} with {up} up, {down} down, {flat} flat, and {volatility} short-window volatility.",
    }


def parse_rpg_state(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    values: dict[str, Any] = {}
    for line in text.splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$", line)
        if not m:
            continue
        key = m.group(1).strip().lower().replace(" ", "_")
        value = m.group(2).strip()
        if key in {"field", "-------"}:
            continue
        values[key] = value

    numeric_keys = [
        "xp", "level", "sessions", "current_level_threshold",
        "next_level_threshold", "xp_to_next_level", "speed", "accuracy",
        "reliability", "judgment", "consistency", "usefulness",
        "cost_efficiency", "evidence_quality", "duplication_penalty",
        "waste_penalty", "fake_productivity_penalty", "intelligence",
        "total_xp",
    ]

    for key in numeric_keys:
        if key in values:
            values[key] = safe_float(values[key])

    return values


def build_axiom_metrics() -> dict[str, Any]:
    rpg_files = sorted(MEMORY_DIR.glob("*/RPG_STATE.md"))

    agents = {}
    weak_agents = []
    strong_agents = []
    unseasoned_agents = []

    for path in rpg_files:
        agent_id = path.parent.name
        if agent_id == "_TEMPLATE":
            continue

        stats = parse_rpg_state(path)
        sessions = safe_float(stats.get("sessions"))
        usefulness = safe_float(stats.get("usefulness"))
        judgment = safe_float(stats.get("judgment"))
        evidence = safe_float(stats.get("evidence_quality"))
        waste = safe_float(stats.get("waste_penalty"))
        fake = safe_float(stats.get("fake_productivity_penalty"))
        duplication = safe_float(stats.get("duplication_penalty"))
        intelligence = safe_float(stats.get("intelligence"))

        penalty_total = waste + fake + duplication

        if sessions <= 0:
            status = "unseasoned"
            unseasoned_agents.append(agent_id)
        elif penalty_total >= 20 or judgment < 10 or evidence < 20 or usefulness < 20:
            status = "weak_or_review"
            weak_agents.append({
                "agent_id": agent_id,
                "sessions": sessions,
                "usefulness": usefulness,
                "judgment": judgment,
                "evidence_quality": evidence,
                "waste_penalty": waste,
                "fake_productivity_penalty": fake,
                "duplication_penalty": duplication,
                "intelligence": intelligence,
                "reason": "low judgment/evidence/usefulness or elevated penalties",
                "grant_action": "call_out_or_warn",
                "axiom_action": "review_recommended",
            })
        elif usefulness >= 50 and evidence >= 40 and intelligence >= 20:
            status = "strong_or_improving"
            strong_agents.append({
                "agent_id": agent_id,
                "sessions": sessions,
                "usefulness": usefulness,
                "judgment": judgment,
                "evidence_quality": evidence,
                "waste_penalty": waste,
                "fake_productivity_penalty": fake,
                "duplication_penalty": duplication,
                "intelligence": intelligence,
                "reason": "useful output with meaningful evidence/intelligence metrics",
                "grant_action": "brief_praise_then_raise_expectations",
            })
        else:
            status = "neutral"

        agents[agent_id] = {
            "status": status,
            "stats": stats,
            "penalty_total": penalty_total,
        }

    weak_agents.sort(
        key=lambda a: (
            -a["waste_penalty"],
            a["judgment"],
            a["evidence_quality"],
            a["usefulness"],
        )
    )
    strong_agents.sort(
        key=lambda a: (
            -a["usefulness"],
            -a["evidence_quality"],
            -a["intelligence"],
        )
    )

    return {
        "agent_count": len(agents),
        "weak_agents": weak_agents[:12],
        "strong_agents": strong_agents[:12],
        "unseasoned_count": len(unseasoned_agents),
        "unseasoned_agents_sample": sorted(unseasoned_agents)[:20],
        "agents": agents,
    }


def build_target_state(allocation: dict[str, Any], scoreboard: dict[str, Any]) -> dict[str, Any]:
    starting_equity = safe_float(allocation.get("parent_total"), 0.0)

    company_values = scoreboard.get("companies", {})
    current_deployable_equity = sum(safe_float(c.get("equity")) for c in company_values.values())
    reserve = safe_float(allocation.get("reserve_amount"), 0.0)
    current_equity_estimate = reserve + current_deployable_equity

    total_pnl = current_equity_estimate - starting_equity

    # v1 targets: conservative floor/goal/stretch based on total virtual starting equity.
    floor_target_equity = starting_equity * 1.04
    goal_target_equity = starting_equity * 1.20
    stretch_target_equity = starting_equity * 2.00

    if current_equity_estimate >= stretch_target_equity:
        target_status = "hit_stretch"
    elif current_equity_estimate >= goal_target_equity:
        target_status = "hit_goal"
    elif current_equity_estimate >= floor_target_equity:
        target_status = "hit_floor"
    elif total_pnl >= 0:
        target_status = "green_but_below_floor"
    else:
        target_status = "negative"

    return {
        "starting_equity": round(starting_equity, 8),
        "current_equity_estimate": round(current_equity_estimate, 8),
        "reserve_amount": round(reserve, 8),
        "deployable_current_equity": round(current_deployable_equity, 8),
        "total_pnl_estimate": round(total_pnl, 8),
        "floor_target_equity": round(floor_target_equity, 8),
        "goal_target_equity": round(goal_target_equity, 8),
        "stretch_target_equity": round(stretch_target_equity, 8),
        "floor_profit_target": round(floor_target_equity - starting_equity, 8),
        "goal_profit_target": round(goal_target_equity - starting_equity, 8),
        "stretch_profit_target": round(stretch_target_equity - starting_equity, 8),
        "target_status": target_status,
    }


def build_committee_health(packet_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(packet_rows)
    fallback = sum(1 for p in packet_rows if p.get("packet_generation_mode") == "fallback")
    fresh = sum(1 for p in packet_rows if p.get("fresh_committee") is True)
    timeout = sum(1 for p in packet_rows if "timed out" in str(p.get("fallback_reason") or "").lower())

    missing = Counter()
    for p in packet_rows:
        for flag in p.get("missing_input_flags") or []:
            missing[str(flag)] += 1

    if total == 0:
        status = "unknown"
    elif fallback / total >= 0.75:
        status = "weak_fallback_heavy"
    elif fresh / total >= 0.50:
        status = "healthy_live_committee"
    else:
        status = "mixed"

    return {
        "packet_count": total,
        "fallback_packets": fallback,
        "fresh_committee_packets": fresh,
        "timeout_packets": timeout,
        "missing_input_flags": dict(missing),
        "status": status,
    }


def build_briefing(run_dir: Path) -> dict[str, Any]:
    artifacts = run_dir / "artifacts"

    allocation = read_json(artifacts / "allocation_state.json", {})
    portfolio_rows = read_jsonl(artifacts / "portfolio_state.jsonl")
    trade_rows = read_jsonl(artifacts / "paper_trades.jsonl")
    decision_rows = read_jsonl(artifacts / "paper_decisions.jsonl")
    packet_rows = read_jsonl(artifacts / "company_packets.jsonl")
    ledger_rows = read_jsonl(artifacts / "ledger_usage.jsonl")
    bridge_rows = read_jsonl(artifacts / "bridge_usage.jsonl")

    scoreboard = build_company_scoreboard(
        allocation=allocation,
        portfolio_rows=portfolio_rows,
        trade_rows=trade_rows,
        decision_rows=decision_rows,
        packet_rows=packet_rows,
    )

    market = build_market_summary(run_dir)
    target_state = build_target_state(allocation, scoreboard)
    axiom = build_axiom_metrics()
    committee = build_committee_health(packet_rows)

    leader = scoreboard.get("leader")
    laggard = scoreboard.get("laggard")

    review_flags = []

    if target_state["target_status"] in {"negative", "green_but_below_floor"}:
        review_flags.append("target_pressure_needed")

    if committee["status"] == "weak_fallback_heavy":
        review_flags.append("committee_fallback_heavy")

    if committee["timeout_packets"] > 0:
        review_flags.append("committee_timeouts_detected")

    if axiom["weak_agents"]:
        review_flags.append("axiom_weak_agents_present")

    if market["condition"] == "green" and target_state["target_status"] in {"negative", "green_but_below_floor"}:
        recommended_tone = "green_market_underperformance"
    elif target_state["target_status"] == "negative":
        recommended_tone = "discipline"
    elif target_state["target_status"] in {"hit_goal", "hit_stretch"}:
        recommended_tone = "victory_push_harder"
    elif committee["status"] == "weak_fallback_heavy":
        recommended_tone = "operational_warning"
    else:
        recommended_tone = "target_pressure"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "speech_audience": "all_non_swe",
        "recommended_speech_type": recommended_tone,
        "market": market,
        "target_state": target_state,
        "company_scoreboard": scoreboard,
        "committee_health": committee,
        "axiom_metrics": {
            "agent_count": axiom["agent_count"],
            "weak_agents": axiom["weak_agents"],
            "strong_agents": axiom["strong_agents"],
            "unseasoned_count": axiom["unseasoned_count"],
            "unseasoned_agents_sample": axiom["unseasoned_agents_sample"],
        },
        "usage_summary": {
            "ledger_rows": len(ledger_rows),
            "bridge_rows": len(bridge_rows),
            "token_counts_available": any(
                row.get("total_tokens") is not None for row in ledger_rows + bridge_rows
            ),
        },
        "grant_notes": [
            f"Leader: {leader}" if leader else "No company leader detected.",
            f"Laggard: {laggard}" if laggard else "No company laggard detected.",
            f"Target status: {target_state['target_status']}",
            f"Market condition: {market['condition']}",
            f"Committee health: {committee['status']}",
        ],
        "review_flags": review_flags,
        "source_files": {
            "allocation_state": str(artifacts / "allocation_state.json"),
            "portfolio_state": str(artifacts / "portfolio_state.jsonl"),
            "paper_trades": str(artifacts / "paper_trades.jsonl"),
            "paper_decisions": str(artifacts / "paper_decisions.jsonl"),
            "company_packets": str(artifacts / "company_packets.jsonl"),
            "market_feed": str(run_dir / "data" / "market_feed.log"),
            "rpg_memory_dir": str(MEMORY_DIR),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Grant Cardone briefing packet from latest ACC run artifacts.")
    parser.add_argument("--run-id", default=None, help="Specific run id. Defaults to latest run folder.")
    parser.add_argument("--out", default=None, help="Output path. Defaults to latest run artifacts/grant_briefing.json.")
    parser.add_argument("--print-summary", action="store_true", help="Print a short human summary after writing JSON.")
    args = parser.parse_args()

    run_dir = run_dir_from_arg(args.run_id)
    briefing = build_briefing(run_dir)

    out_path = Path(args.out) if args.out else run_dir / "artifacts" / "grant_briefing.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(briefing, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    latest_path = ROOT / "state" / "grant" / "latest_grant_briefing.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(briefing, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote: {out_path}")
    print(f"Wrote: {latest_path}")

    if args.print_summary:
        target = briefing["target_state"]
        market = briefing["market"]
        board = briefing["company_scoreboard"]
        axiom = briefing["axiom_metrics"]
        committee = briefing["committee_health"]

        print()
        print("GRANT BRIEFING SUMMARY")
        print("======================")
        print(f"Run: {briefing['run_id']}")
        print(f"Market: {market['condition']} / {market['bias']} / volatility={market['volatility']}")
        print(f"Current equity estimate: {target['current_equity_estimate']}")
        print(f"Total P/L estimate: {target['total_pnl_estimate']}")
        print(f"Target status: {target['target_status']}")
        print(f"Leader: {board['leader']}")
        print(f"Laggard: {board['laggard']}")
        print(f"Committee: {committee['status']} ({committee['fallback_packets']} fallback / {committee['packet_count']} packets)")
        print(f"Weak agents flagged: {len(axiom['weak_agents'])}")
        print(f"Strong agents flagged: {len(axiom['strong_agents'])}")
        print(f"Recommended speech type: {briefing['recommended_speech_type']}")


if __name__ == "__main__":
    main()
