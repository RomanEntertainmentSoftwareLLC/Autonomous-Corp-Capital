"""Orchestration CLI for the live-data virtual-currency paper run."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List
import urllib.error

from tools.agent_runtime import collect_agent_reports
from tools.live_decision_engine import build_decision, DecisionResult
from tools.live_market_feed import fetch_market_data
from tools.live_orchestra import orchestrate
from tools.live_paper_portfolio import PortfolioState
from tools.live_universe import target_symbol_list

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIVE_RUNS_ROOT = ROOT / "state" / "live_runs"
CURRENT_RUN_PATH = LIVE_RUNS_ROOT / "current_run.json"
LIVE_RUN_POLL_SECONDS = int(os.getenv("LIVE_RUN_POLL_SECONDS", "60"))
LIVE_RUN_BACKOFF_BASE = int(os.getenv("LIVE_RUN_BACKOFF_SECONDS", "60"))
COMPANIES = ["company_001", "company_002", "company_003", "company_004"]
MAX_EXECUTIONS_PER_CYCLE = 6
MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE = 2


def ensure_directories() -> None:
    LIVE_RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def create_run_id() -> str:
    return datetime.utcnow().strftime("run_%Y%m%d_%H%M%S")


def run_directory(run_id: str) -> Path:
    run_dir = LIVE_RUNS_ROOT / run_id
    for sub in ("data", "artifacts", "logs", "packets", "reports"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


def write_current_run(run_id: str, pid: int) -> None:
    ensure_directories()
    data = {"run_id": run_id, "pid": pid, "mode": "paper", "status": "running", "started_at": datetime.utcnow().isoformat()}
    CURRENT_RUN_PATH.write_text(json.dumps(data, indent=2))



def candidate_ranking_score(decision: Dict[str, Any]) -> float:
    policy_signal_score = abs(float(decision.get("policy_signal_score") or 0.0))
    ml_signal_score = abs(float(decision.get("ml_signal_score") or 0.0))
    model_confidence = abs(float(decision.get("model_score") or 0.5) - 0.5) * 2.0
    return round(policy_signal_score + ml_signal_score + model_confidence, 6)



def rank_and_select_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = sorted(candidates, key=lambda c: c["ranking_score"], reverse=True)
    selected: List[Dict[str, Any]] = []
    per_company_counts: Dict[str, int] = {}
    for candidate in ranked:
        if candidate.get("vetoed_by_risk"):
            candidate["execution_state"] = "skipped"
            candidate["skip_reason"] = "risk_veto"
            continue
        if candidate.get("decision") == "HOLD":
            candidate["execution_state"] = "skipped"
            candidate["skip_reason"] = "hold_candidate"
            continue
        company = str(candidate.get("company_id"))
        if len(selected) >= MAX_EXECUTIONS_PER_CYCLE:
            candidate["execution_state"] = "skipped"
            candidate["skip_reason"] = "global_execution_cap"
            continue
        if per_company_counts.get(company, 0) >= MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE:
            candidate["execution_state"] = "skipped"
            candidate["skip_reason"] = "company_execution_cap"
            continue
        candidate["execution_state"] = "executed"
        candidate["skip_reason"] = None
        selected.append(candidate)
        per_company_counts[company] = per_company_counts.get(company, 0) + 1
    return ranked



def latest_report(reports: Dict[str, List[Dict[str, Any]]], agent_name: str) -> Dict[str, Any]:
    agent_reports = reports.get(agent_name) or []
    return agent_reports[-1] if agent_reports else {}



def derive_lucian_posture(report: Dict[str, Any]) -> str:
    text = " ".join(
        str(report.get(key, ""))
        for key in ("decision", "approval_decision", "action_directive", "executive_summary", "reply_text", "rationale")
    ).lower()
    if not text:
        return "approve_top_candidate"
    if "do not approve" in text or "request more evidence" in text or "not approved" in text:
        return "company_veto"
    if "defer" in text:
        return "defer"
    if "hold" in text:
        return "hold"
    return "approve_top_candidate"



def derive_bianca_cap_multiplier(report: Dict[str, Any]) -> float:
    text = " ".join(
        str(report.get(key, ""))
        for key in ("spending_posture", "budget_posture", "reply_text", "recommendation", "rationale")
    ).lower()
    if not text:
        return 1.0
    if "hold new spending" in text or "preserve cash" in text or "keep spending constrained" in text or "caution level: high" in text:
        return 0.5
    if "caution" in text or "constrained" in text:
        return 0.75
    return 1.0



def build_company_packet(company: str, ranked_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    reports = collect_agent_reports(company)
    source_agents = [
        "Pam",
        "Iris",
        "Vera",
        "Rowan",
        "Orion",
        "Bianca",
        "Lucian",
        "Atlas",
        "Bob",
        "June",
        "Sloane",
    ]
    consulted = [agent for agent in source_agents if reports.get(agent)]
    missing = [agent for agent in source_agents if not reports.get(agent)]
    lucian_report = latest_report(reports, "Lucian")
    bianca_report = latest_report(reports, "Bianca")
    iris_report = latest_report(reports, "Iris")
    vera_report = latest_report(reports, "Vera")
    orion_report = latest_report(reports, "Orion")
    approval_posture = derive_lucian_posture(lucian_report)
    cap_multiplier = derive_bianca_cap_multiplier(bianca_report)
    top_candidates = [
        {
            "symbol": c.get("symbol"),
            "decision": c.get("decision"),
            "ranking_score": c.get("ranking_score"),
            "decision_path": c.get("decision_path"),
            "execution_state": c.get("execution_state"),
            "skip_reason": c.get("skip_reason"),
        }
        for c in ranked_candidates[:3]
    ]
    rationale_bits = []
    for agent_name, report in (("Iris", iris_report), ("Vera", vera_report), ("Orion", orion_report)):
        text = report.get("analysis_summary") or report.get("recommendation") or report.get("reply_text") or report.get("research_summary")
        if text:
            rationale_bits.append(f"{agent_name}: {text}")
    if not rationale_bits:
        rationale_bits.append("No real Iris/Vera/Orion runtime rationale available yet.")
    return {
        "company_id": company,
        "top_ranked_candidates": top_candidates,
        "approval_posture": approval_posture,
        "cap_multiplier": cap_multiplier,
        "sizing_posture": "reduced" if cap_multiplier < 1.0 else "baseline",
        "rationale": " | ".join(rationale_bits[:3]),
        "missing_input_flags": missing,
        "source_agents_consulted": consulted,
        "execution_changed_by_packet": False,
        "packet_effects": [],
    }



def apply_company_packets(ranked_candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    packets: Dict[str, Dict[str, Any]] = {}
    by_company: Dict[str, List[Dict[str, Any]]] = {company: [] for company in COMPANIES}
    for candidate in ranked_candidates:
        by_company.setdefault(str(candidate.get("company_id")), []).append(candidate)

    for company, company_candidates in by_company.items():
        packet = build_company_packet(company, company_candidates)
        packets[company] = packet
        allowed_execs = max(0, min(MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE, int(MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE * packet["cap_multiplier"] + 0.9999)))
        executed_for_company = 0
        for candidate in company_candidates:
            if candidate.get("execution_state") != "executed":
                continue
            if packet["approval_posture"] == "company_veto":
                candidate["execution_state"] = "skipped"
                candidate["skip_reason"] = "company_packet_veto"
                packet["execution_changed_by_packet"] = True
                packet["packet_effects"].append(f"vetoed:{candidate.get('symbol')}")
                continue
            if packet["approval_posture"] in {"hold", "defer"}:
                candidate["execution_state"] = "skipped"
                candidate["skip_reason"] = f"company_packet_{packet['approval_posture']}"
                packet["execution_changed_by_packet"] = True
                packet["packet_effects"].append(f"{packet['approval_posture']}:{candidate.get('symbol')}")
                continue
            if executed_for_company >= allowed_execs:
                candidate["execution_state"] = "skipped"
                candidate["skip_reason"] = "company_packet_cap"
                packet["execution_changed_by_packet"] = True
                packet["packet_effects"].append(f"cap:{candidate.get('symbol')}")
                continue
            candidate["size_multiplier"] = round(float(candidate.get("size_multiplier", 1.0)) * float(packet["cap_multiplier"]), 4)
            candidate["company_packet_posture"] = packet["approval_posture"]
            candidate["company_packet_cap_multiplier"] = packet["cap_multiplier"]
            executed_for_company += 1
        packet["resulting_execution_posture"] = packet["approval_posture"]
    return packets


def read_current_run() -> Dict[str, Any]:
    if not CURRENT_RUN_PATH.exists():
        raise FileNotFoundError("No current live run tracked")
    return json.loads(CURRENT_RUN_PATH.read_text())


def clear_current_run() -> None:
    if CURRENT_RUN_PATH.exists():
        CURRENT_RUN_PATH.unlink()


def start_run(duration_hours: float = 0.0) -> None:
    ensure_directories()
    run_id = create_run_id()
    run_dir = run_directory(run_id)
    symbol_list = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbol_list.split(",") if symbol_list else target_symbol_list()
    meta = {
        "run_id": run_id,
        "mode": "paper",
        "symbols": symbols,
        "duration_hours": duration_hours,
        "started_at": datetime.utcnow().isoformat(),
        "status": "scheduled",
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    command = [sys.executable, "-m", "tools.live_run", "run", "--run-id", run_id, "--duration-hours", str(duration_hours)]
    proc = subprocess.Popen(command, env=dict(os.environ, LIVE_RUN_MODE="paper"))
    (run_dir / "run.pid").write_text(str(proc.pid))
    write_current_run(run_id, proc.pid)
    print(f"Live-data paper run started: {run_id}")
    print(f"Logs at: {run_dir / 'logs' / 'run.log'}")


def stop_run(run_id: str | None = None) -> None:
    current = {}
    try:
        current = read_current_run()
    except FileNotFoundError:
        pass
    target_run = run_id or current.get("run_id")
    if not target_run:
        raise SystemExit("No run_id provided and no current run tracked")
    pid = current.get("pid") if current.get("run_id") == target_run else None
    run_dir = run_directory(target_run)
    pid_file = run_dir / "run.pid"
    if pid and pid_file.exists():
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        pid_file.unlink()
    meta_path = run_dir / "run_metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["ended_at"] = datetime.utcnow().isoformat()
        meta["status"] = "stopped"
        meta_path.write_text(json.dumps(meta, indent=2))
    if current.get("run_id") == target_run:
        clear_current_run()
    print(f"Live-data paper run {target_run} stopped safely.")


def record_snapshot(run_dir: Path, snapshot: Dict[str, Any]) -> None:
    with (run_dir / "data" / "market_feed.log").open("a", encoding="utf-8") as feed:
        feed.write(json.dumps(snapshot) + "\n")
        \


def run_worker(run_id: str, duration_hours: float = 0.0) -> None:
    run_dir = run_directory(run_id)
    pid_file = run_dir / "run.pid"
    symbols = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbols.split(",") if symbols else target_symbol_list()
    portfolio = PortfolioState(run_dir)
    with pid_file.open("w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    stop_flag = False
    backoff = 0
    end_time = datetime.utcnow() + timedelta(hours=duration_hours) if duration_hours > 0 else None
    last_prices: Dict[str, float] = {}
    cycle = 0

    def _signal_handler(*_: Any) -> None:
        nonlocal stop_flag
        stop_flag = True

    signal.signal(signal.SIGTERM, _signal_handler)
    log_path = run_dir / "logs" / "run.log"
    while not stop_flag and (not end_time or datetime.utcnow() < end_time):
        cycle += 1
        timestamp = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
        try:
            snapshots = fetch_market_data(symbols)
            backoff = 0
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                backoff = max(LIVE_RUN_BACKOFF_BASE, backoff * 2 or LIVE_RUN_BACKOFF_BASE)
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps({"timestamp": timestamp, "event": "rate_limit", "retry": backoff}) + "\n")

                time.sleep(backoff)
                continue
            raise
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"timestamp": timestamp, "event": "feed_error", "error": str(exc)}) + "\n")

            time.sleep(LIVE_RUN_POLL_SECONDS)
            continue
        anomalies: List[str] = []
        cycle_decisions: List[Dict[str, Any]] = []
        candidate_decisions: List[Dict[str, Any]] = []
        for snapshot in snapshots:
            record_snapshot(run_dir, snapshot)
        for company in COMPANIES:
            for snapshot in snapshots:
                symbol = snapshot["symbol"]
                decision = build_decision(snapshot, company, last_prices.get((company, symbol)))
                decision["vetoed_by_risk"] = abs(decision.get("signal_score", 0)) > 0.08
                decision["position_state"] = portfolio.positions[company].get(symbol, 0.0)
                decision["cash_snapshot"] = portfolio.cash.get(company, 0.0)
                decision["allocation_context"] = portfolio.allocations.get(company)
                decision["ranking_score"] = candidate_ranking_score(decision)
                decision["pretrade_selection_path"] = "ranked_then_company_packet"
                decision["pretrade_agent_participation"] = "company packet consulted after ranking"
                last_prices[(company, symbol)] = snapshot.get("price") or last_prices.get((company, symbol), 0.0)
                candidate_decisions.append(decision)

        ranked_candidates = rank_and_select_candidates(candidate_decisions)
        company_packets = apply_company_packets(ranked_candidates)
        for packet in company_packets.values():
            with (run_dir / "artifacts" / "company_packets.jsonl").open("a", encoding="utf-8") as packet_file:
                packet_file.write(json.dumps({"timestamp": timestamp, **packet}) + "\n")
        for decision in ranked_candidates:
            if decision["vetoed_by_risk"]:
                anomalies.append(f"veto:{decision['company_id']}:{decision['symbol']}")
                with (run_dir / "artifacts" / "risk.log").open("a", encoding="utf-8") as risk_file:
                    risk_file.write(json.dumps({"timestamp": timestamp, "company": decision["company_id"], "symbol": decision["symbol"], "veto": True}) + "\n")
            with (run_dir / "artifacts" / "paper_decisions.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(decision) + "\n")
            if decision.get("execution_state") != "executed":
                continue
            portfolio.apply_decision(decision)
            cycle_decisions.append(decision)
        orchestrate(run_dir, cycle, cycle_decisions, anomalies)
        strategy_entry = {
            "timestamp": timestamp,
            "decision": "ml+signal" if any(d.get("ml_scoring_active") for d in cycle_decisions) else "signal-only",
            "confidence": 0.0,
            "ml_scoring_active": any(d.get("ml_scoring_active") for d in cycle_decisions),
            "decision_path_counts": {
                "ml+signal": sum(1 for d in ranked_candidates if d.get("decision_path") == "ml+signal"),
                "signal-only fallback": sum(1 for d in ranked_candidates if d.get("decision_path") == "signal-only fallback"),
            },
            "ranking_summary": {
                "candidate_count": len(ranked_candidates),
                "executed_count": sum(1 for d in ranked_candidates if d.get("execution_state") == "executed"),
                "skipped_count": sum(1 for d in ranked_candidates if d.get("execution_state") == "skipped"),
                "company_packet_count": len(company_packets),
                "top_ranked": [
                    {
                        "company_id": d.get("company_id"),
                        "symbol": d.get("symbol"),
                        "decision": d.get("decision"),
                        "ranking_score": d.get("ranking_score"),
                        "execution_state": d.get("execution_state"),
                        "skip_reason": d.get("skip_reason"),
                    }
                    for d in ranked_candidates[: min(10, len(ranked_candidates))]
                ],
            },
            "company_packet_summary": {
                company: {
                    "approval_posture": packet.get("approval_posture"),
                    "cap_multiplier": packet.get("cap_multiplier"),
                    "source_agents_consulted": packet.get("source_agents_consulted"),
                    "execution_changed_by_packet": packet.get("execution_changed_by_packet"),
                }
                for company, packet in company_packets.items()
            },
            "notes": "Cycle ranked all candidates first, then applied real company packets before execution. Not all 62 agents are execution-impacting yet.",
        }
        risk_entry = {"timestamp": timestamp, "veto": bool(anomalies), "notes": "risk event" if anomalies else "all good"}
        with (run_dir / "artifacts" / "strategy.log").open("a", encoding="utf-8") as strategy:
            strategy.write(json.dumps(strategy_entry) + "\n")
        
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"timestamp": timestamp, "event": "heartbeat", "symbols": symbols}) + "\n")
        
        if cycle % 10 == 0:
            reallocation_note = {"timestamp": timestamp, "event": "allocation_review", "note": "Reallocation pending (planned)."}
            with (run_dir / "artifacts" / "risk.log").open("a", encoding="utf-8") as risk_file:
                risk_file.write(json.dumps(reallocation_note) + "\n")
        
        time.sleep(LIVE_RUN_POLL_SECONDS)
    pid_file.unlink(missing_ok=True)
def summary(run_id: str) -> None:
    run_dir = run_directory(run_id)
    logs = list((run_dir / "logs").glob("*.log"))
    summary = {
        "run_id": run_id,
        "captured": datetime.utcnow().isoformat(),
        "log_files": [str(p) for p in logs],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Summary bundle created at {summary_path}")


def verify_paper_only(run_id: str) -> None:
    run_dir = run_directory(run_id)
    meta = json.loads((run_dir / "run_metadata.json").read_text())
    if meta.get("mode") != "paper":
        raise SystemExit("Run is not paper-only")
    real_trade_path = run_dir / "artifacts" / "real_money_trades.log"
    if real_trade_path.exists():
        raise SystemExit("Real-money trades detected")
    print("Paper-only verification passed")


def validate() -> None:
    ensure_directories()
    symbols = target_symbol_list()
    snapshots = fetch_market_data(symbols)
    if not snapshots:
        raise SystemExit("Feed returned no snapshot data")
    for snapshot in snapshots:
        if snapshot.get("price") is None or not snapshot.get("timestamp"):
            raise SystemExit("Invalid snapshot data from feed")
    run_dir = run_directory("validate_temp")
    for path in (run_dir / "data" / "market_feed.log", run_dir / "artifacts" / "strategy.log", run_dir / "logs" / "run.log"):
        path.write_text("")
    (run_dir / "artifacts" / "real_money_trades.log").write_text("")
    print("Live-run infrastructure ready")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage the live-data paper run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start", help="Start the paper run")
    start_parser.add_argument("--duration-hours", type=float, default=0.0)
    stop_parser = subparsers.add_parser("stop", help="Stop the current paper run")
    stop_parser.add_argument("--run-id", help="Explicit run id to stop")
    run_parser = subparsers.add_parser("run", help="Run worker (internal)")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--duration-hours", type=float, default=0.0)
    summary_parser = subparsers.add_parser("summary", help="Generate summary bundle")
    summary_parser.add_argument("--run-id", required=True)
    verify_parser = subparsers.add_parser("verify", help="Verify paper-only mode")
    verify_parser.add_argument("--run-id", required=True)
    subparsers.add_parser("validate", help="Validate feed/dirs")
    args = parser.parse_args()
    if args.command == "start":
        start_run(duration_hours=args.duration_hours)
    elif args.command == "stop":
        stop_run(run_id=args.run_id)
    elif args.command == "run":
        run_worker(args.run_id, duration_hours=args.duration_hours)
    elif args.command == "summary":
        summary(args.run_id)
    elif args.command == "verify":
        verify_paper_only(args.run_id)
    elif args.command == "validate":
        validate()


if __name__ == "__main__":
    main()
