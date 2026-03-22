"""Orchestration CLI for the live-data virtual-currency paper run."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
LIVE_COMMITTEE_TIMEOUT_SECONDS = int(os.getenv("LIVE_COMMITTEE_TIMEOUT_SECONDS", "25"))
LIVE_COMMITTEE_ROLES = ["Lucian", "Bianca", "Vera", "Iris", "Orion"]


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
    pattern_contribution = float(decision.get("pattern_contribution") or 0.0)
    return round(policy_signal_score + ml_signal_score + model_confidence + pattern_contribution, 6)



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


ORION_BIAS_MAX_ABS = 0.10
ORION_STALE_AFTER_HOURS = 24.0
ORION_SECONDARY_WEIGHT = 0.08


def _parse_report_timestamp(report: Dict[str, Any]) -> datetime | None:
    raw = report.get("timestamp")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)



def _orion_report_is_stale(report: Dict[str, Any], now: datetime) -> bool:
    report_ts = _parse_report_timestamp(report)
    if report_ts is None:
        return True
    return (now - report_ts) > timedelta(hours=ORION_STALE_AFTER_HOURS)



def _extract_symbol_tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, dict):
        tokens: set[str] = set()
        for key, nested in value.items():
            tokens.update(_extract_symbol_tokens(key))
            tokens.update(_extract_symbol_tokens(nested))
        return tokens
    if isinstance(value, (list, tuple, set)):
        tokens: set[str] = set()
        for item in value:
            tokens.update(_extract_symbol_tokens(item))
        return tokens
    text = str(value).upper()
    return set(re.findall(r"\b[A-Z]{2,10}\b", text))



def _orion_report_mentions_symbol(report: Dict[str, Any], symbol: str) -> bool:
    symbol_upper = str(symbol or "").upper()
    if not symbol_upper:
        return False
    symbol_fields = [
        report.get("symbol"),
        report.get("symbols"),
        report.get("ticker"),
        report.get("tickers"),
        report.get("asset"),
        report.get("assets"),
        report.get("pair"),
        report.get("pairs"),
        report.get("evidence"),
        report.get("ideas"),
        report.get("hypotheses"),
        report.get("analysis_summary"),
        report.get("recommendation"),
        report.get("research_summary"),
        report.get("reply_text"),
        report.get("summary"),
        report.get("rationale"),
    ]
    for field in symbol_fields:
        if symbol_upper in _extract_symbol_tokens(field):
            return True
    return False



def _orion_directional_multiplier(report: Dict[str, Any], decision: Dict[str, Any]) -> float:
    text = " ".join(
        str(report.get(key, ""))
        for key in ("analysis_summary", "recommendation", "research_summary", "reply_text", "summary", "rationale", "decision")
    ).lower()
    if not text:
        return 0.0

    bullish_hits = sum(
        phrase in text
        for phrase in (
            "bullish",
            "buy",
            "long",
            "overweight",
            "accumulate",
            "positive catalyst",
            "favorable",
            "constructive",
        )
    )
    bearish_hits = sum(
        phrase in text
        for phrase in (
            "bearish",
            "sell",
            "short",
            "underweight",
            "distribute",
            "negative catalyst",
            "unfavorable",
            "cautious",
        )
    )
    net = float(bullish_hits - bearish_hits)
    if net == 0.0:
        return 0.0

    target_sign = 0.0
    decision_text = str(decision.get("decision") or "").upper()
    if decision_text == "BUY":
        target_sign = 1.0
    elif decision_text == "SELL":
        target_sign = -1.0
    else:
        signal_score = float(decision.get("signal_score") or 0.0)
        ml_signal_score = float(decision.get("ml_signal_score") or 0.0)
        combined = signal_score + ml_signal_score
        if combined > 0:
            target_sign = 1.0
        elif combined < 0:
            target_sign = -1.0
    if target_sign == 0.0:
        return 0.0
    return 1.0 if (net > 0 and target_sign > 0) or (net < 0 and target_sign < 0) else -1.0



def _orion_damping_factor(report: Dict[str, Any]) -> float:
    damping = 1.0
    missing_data = report.get("missing_data")
    if missing_data:
        damping *= 0.5

    evidence = report.get("evidence")
    if evidence is None:
        damping *= 0.7
    elif isinstance(evidence, (list, tuple, set)):
        if len(evidence) == 0:
            damping *= 0.7
        elif len(evidence) == 1:
            damping *= 0.85

    text = " ".join(
        str(report.get(key, ""))
        for key in ("analysis_summary", "recommendation", "research_summary", "reply_text", "summary", "rationale")
    ).lower()
    if any(phrase in text for phrase in ("unclear", "mixed", "weak evidence", "limited evidence", "insufficient evidence", "uncertain", "tentative")):
        damping *= 0.6
    elif any(phrase in text for phrase in ("watch", "monitor", "possible", "maybe", "developing")):
        damping *= 0.8

    return max(0.0, min(1.0, damping))



def compute_orion_bias(decision: Dict[str, Any], report: Dict[str, Any], now: datetime | None = None) -> float:
    if not report:
        return 0.0
    now = now or datetime.utcnow().replace(tzinfo=timezone.utc)
    if _orion_report_is_stale(report, now):
        return 0.0
    if not _orion_report_mentions_symbol(report, str(decision.get("symbol") or "")):
        return 0.0

    direction = _orion_directional_multiplier(report, decision)
    if direction == 0.0:
        return 0.0

    base_score = float(decision.get("ranking_score") or candidate_ranking_score(decision))
    raw_bias = base_score * ORION_SECONDARY_WEIGHT * _orion_damping_factor(report) * direction
    return round(max(-ORION_BIAS_MAX_ABS, min(ORION_BIAS_MAX_ABS, raw_bias)), 6)



def apply_orion_bias_before_ranking(candidates: List[Dict[str, Any]], now: datetime | None = None) -> List[Dict[str, Any]]:
    now = now or datetime.utcnow().replace(tzinfo=timezone.utc)
    report_cache: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        company = str(candidate.get("company_id"))
        if company not in report_cache:
            report_cache[company] = latest_report(collect_agent_reports(company), "Orion")
        orion_report = report_cache[company]
        base_score = float(candidate.get("ranking_score") or candidate_ranking_score(candidate))
        candidate["ranking_score_before_orion"] = round(base_score, 6)
        candidate["orion_bias"] = compute_orion_bias(candidate, orion_report, now=now)
        candidate["ranking_score"] = round(base_score + float(candidate["orion_bias"]), 6)
    return candidates



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



def _committee_agent_id(company: str, role: str) -> str:
    return f"{role.lower()}_{company}"



def _committee_cycle_message(company: str, company_candidates: List[Dict[str, Any]]) -> str:
    top_lines = []
    for idx, candidate in enumerate(company_candidates[:3], start=1):
        top_lines.append(
            f"{idx}. {candidate.get('symbol')} decision={candidate.get('decision')} ranking_score={candidate.get('ranking_score')} "
            f"confidence={candidate.get('confidence')} orion_bias={candidate.get('orion_bias')} "
            f"policy_signal_score={candidate.get('policy_signal_score')} ml_signal_score={candidate.get('ml_signal_score')}"
        )
    slate = "\n".join(top_lines) if top_lines else "No ranked candidates available."
    return (
        f"Live committee consult for {company}. This is one bounded per-cycle company committee check, not per-symbol spam. "
        f"Review the already-ranked candidate slate below and respond only for your role. Preserve role boundaries and do not replace the engine.\n\n"
        f"Current ranked slate:\n{slate}\n\n"
        f"Need cycle guidance tied to the current ranked slate only."
    )



def _invoke_live_committee_agent(agent_id: str, message: str) -> Dict[str, Any]:
    cmd = [sys.executable, str(ROOT / "tools" / "pam.py"), "--agent", agent_id, message]
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=LIVE_COMMITTEE_TIMEOUT_SECONDS,
        check=False,
    )
    combined = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        raise RuntimeError(f"live_committee_agent_failed:{agent_id}:{combined}")
    try:
        return json.loads(result.stdout)
    except Exception as exc:
        raise RuntimeError(f"live_committee_parse_failed:{agent_id}:{combined}") from exc



def _run_live_committee(company: str, company_candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    message = _committee_cycle_message(company, company_candidates)
    outputs: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(LIVE_COMMITTEE_ROLES)) as pool:
        future_map = {
            pool.submit(_invoke_live_committee_agent, _committee_agent_id(company, role), message): role
            for role in LIVE_COMMITTEE_ROLES
        }
        for future in as_completed(future_map):
            role = future_map[future]
            outputs[role] = future.result()
    return outputs



def _top_candidate_fresh_summary(company_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    executable = [c for c in company_candidates if not c.get("vetoed_by_risk") and c.get("decision") != "HOLD"]
    top_candidate = executable[0] if executable else (company_candidates[0] if company_candidates else {})
    confidence = float(top_candidate.get("confidence") or 0.0)
    ranking_score = float(top_candidate.get("ranking_score") or 0.0)
    signal_strength = abs(float(top_candidate.get("policy_signal_score") or 0.0)) + abs(float(top_candidate.get("ml_signal_score") or 0.0))
    return {
        "top_candidate": top_candidate,
        "executable_candidates": executable,
        "confidence": confidence,
        "ranking_score": ranking_score,
        "signal_strength": signal_strength,
    }



def _fresh_orion_input(company: str, company_candidates: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    top = _top_candidate_fresh_summary(company_candidates)["top_candidate"]
    symbol = top.get("symbol") or "none"
    bias = float(top.get("orion_bias") or 0.0)
    direction = "supportive" if bias > 0 else "adverse" if bias < 0 else "neutral"
    return {
        "mode": "fresh",
        "timestamp": now.isoformat(),
        "summary": f"Fresh Orion thesis for {company}: {symbol} research posture is {direction}; bias={round(bias, 6)} based on current ranked slate.",
        "symbol": symbol,
        "bias": round(bias, 6),
    }



def _fresh_iris_input(company: str, company_candidates: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    top = _top_candidate_fresh_summary(company_candidates)
    candidate = top["top_candidate"]
    symbol = candidate.get("symbol") or "none"
    return {
        "mode": "fresh",
        "timestamp": now.isoformat(),
        "summary": f"Fresh Iris framing for {company}: top ranked candidate is {symbol} with decision {candidate.get('decision')} and confidence {round(top['confidence'], 4)}.",
    }



def _fresh_vera_input(company: str, company_candidates: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    top = _top_candidate_fresh_summary(company_candidates)
    candidate = top["top_candidate"]
    return {
        "mode": "fresh",
        "timestamp": now.isoformat(),
        "summary": f"Fresh Vera analysis for {company}: ranking strength={round(top['ranking_score'], 6)}, signal_strength={round(top['signal_strength'], 6)} on {candidate.get('symbol') or 'none'}.",
    }



def _fresh_lucian_posture(company: str, company_candidates: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    top = _top_candidate_fresh_summary(company_candidates)
    candidate = top["top_candidate"]
    posture = "approve_top_candidate"
    rationale = "Fresh Lucian approval: ranked slate acceptable for execution."
    if not top["executable_candidates"]:
        posture = "hold"
        rationale = "Fresh Lucian approval: no executable candidates survived the ranked slate."
    elif top["confidence"] < 0.2 or top["ranking_score"] < 0.2:
        posture = "hold"
        rationale = "Fresh Lucian approval: ranked slate is too weak for execution this cycle."
    elif candidate.get("vetoed_by_risk"):
        posture = "company_veto"
        rationale = "Fresh Lucian approval: top candidate is risk-vetoed, so committee blocks execution."
    return {
        "mode": "fresh",
        "timestamp": now.isoformat(),
        "approval_posture": posture,
        "summary": rationale,
    }



def _fresh_bianca_posture(company: str, company_candidates: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    top = _top_candidate_fresh_summary(company_candidates)
    candidate = top["top_candidate"]
    executable_count = len(top["executable_candidates"])
    cap_multiplier = 1.0
    posture = "baseline"
    if executable_count == 0:
        cap_multiplier = 0.0
        posture = "paused"
    elif top["confidence"] < 0.35:
        cap_multiplier = 0.5
        posture = "reduced"
    elif candidate.get("cash_snapshot") is not None and float(candidate.get("cash_snapshot") or 0.0) <= 0.0:
        cap_multiplier = 0.5
        posture = "cash_caution"
    return {
        "mode": "fresh",
        "timestamp": now.isoformat(),
        "cap_multiplier": cap_multiplier,
        "summary": f"Fresh Bianca sizing for {company}: posture={posture}, cap_multiplier={cap_multiplier}.",
    }



def _fallback_committee_packet(company: str, ranked_candidates: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    reports = collect_agent_reports(company)
    source_agents = ["Pam", "Iris", "Vera", "Rowan", "Orion", "Bianca", "Lucian", "Atlas", "Bob", "June", "Sloane"]
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
    committee_sources = {
        "Lucian": {"mode": "fallback_saved" if lucian_report else "code_only", "reason": reason},
        "Bianca": {"mode": "fallback_saved" if bianca_report else "code_only", "reason": reason},
        "Vera": {"mode": "fallback_saved" if vera_report else "code_only", "reason": reason},
        "Iris": {"mode": "fallback_saved" if iris_report else "code_only", "reason": reason},
        "Orion": {"mode": "fallback_saved" if orion_report else "code_only", "reason": reason},
    }
    return {
        "company_id": company,
        "packet_generation_mode": "fallback",
        "top_ranked_candidates": top_candidates,
        "approval_posture": approval_posture,
        "cap_multiplier": cap_multiplier,
        "sizing_posture": "reduced" if cap_multiplier < 1.0 else "baseline",
        "rationale": " | ".join(rationale_bits[:3]),
        "missing_input_flags": missing,
        "source_agents_consulted": consulted,
        "committee_sources": committee_sources,
        "fresh_committee": False,
        "fallback_reason": reason,
        "execution_changed_by_packet": False,
        "packet_effects": [],
    }



def build_company_packet(company: str, ranked_candidates: List[Dict[str, Any]], now: datetime | None = None) -> Dict[str, Any]:
    now = now or datetime.utcnow().replace(tzinfo=timezone.utc)
    top_candidates = [
        {
            "symbol": c.get("symbol"),
            "decision": c.get("decision"),
            "ranking_score": c.get("ranking_score"),
            "ranking_score_before_orion": c.get("ranking_score_before_orion"),
            "orion_bias": c.get("orion_bias"),
            "decision_path": c.get("decision_path"),
            "execution_state": c.get("execution_state"),
            "skip_reason": c.get("skip_reason"),
        }
        for c in ranked_candidates[:3]
    ]
    saved_reports = collect_agent_reports(company)
    live_outputs: Dict[str, Dict[str, Any]] = {}
    committee_sources: Dict[str, Dict[str, Any]] = {}
    missing_input_flags: List[str] = []
    source_agents_consulted: List[str] = []

    try:
        live_outputs = _run_live_committee(company, ranked_candidates)
    except Exception as exc:
        live_outputs = {}
        committee_sources["_committee"] = {"mode": "fallback", "reason": f"live_committee_failed:{exc}"}

    role_payloads: Dict[str, Dict[str, Any]] = {}
    for role in LIVE_COMMITTEE_ROLES:
        if role in live_outputs:
            role_payloads[role] = live_outputs[role]
            source_agents_consulted.append(role)
            committee_sources[role] = {
                "mode": "live_session",
                "agent_id": _committee_agent_id(company, role),
                "summary": live_outputs[role].get("analysis_summary")
                or live_outputs[role].get("recommendation")
                or live_outputs[role].get("research_summary")
                or live_outputs[role].get("executive_summary")
                or live_outputs[role].get("reply_text"),
            }
            continue

        missing_input_flags.append(role)
        saved = latest_report(saved_reports, role)
        if saved:
            role_payloads[role] = saved
            source_agents_consulted.append(role)
            committee_sources[role] = {"mode": "fallback_saved", "summary": saved.get("analysis_summary") or saved.get("recommendation") or saved.get("research_summary") or saved.get("executive_summary") or saved.get("reply_text")}
        else:
            if role == "Iris":
                code_only = _fresh_iris_input(company, ranked_candidates, now)
            elif role == "Vera":
                code_only = _fresh_vera_input(company, ranked_candidates, now)
            elif role == "Orion":
                code_only = _fresh_orion_input(company, ranked_candidates, now)
            elif role == "Bianca":
                code_only = _fresh_bianca_posture(company, ranked_candidates, now)
            else:
                code_only = _fresh_lucian_posture(company, ranked_candidates, now)
            role_payloads[role] = code_only
            source_agents_consulted.append(role)
            committee_sources[role] = {"mode": "code_only", "summary": code_only.get("summary")}

    rationale = " | ".join(
        role_payloads[name].get("analysis_summary")
        or role_payloads[name].get("recommendation")
        or role_payloads[name].get("research_summary")
        or role_payloads[name].get("reply_text")
        or role_payloads[name].get("summary", "")
        for name in ("Iris", "Vera", "Orion")
        if role_payloads.get(name)
    )
    approval_posture = derive_lucian_posture(role_payloads.get("Lucian", {}))
    if committee_sources.get("Lucian", {}).get("mode") == "code_only":
        approval_posture = role_payloads.get("Lucian", {}).get("approval_posture", approval_posture)
    cap_multiplier = derive_bianca_cap_multiplier(role_payloads.get("Bianca", {}))
    if committee_sources.get("Bianca", {}).get("mode") == "code_only":
        cap_multiplier = float(role_payloads.get("Bianca", {}).get("cap_multiplier", cap_multiplier))

    live_roles = [role for role, meta in committee_sources.items() if meta.get("mode") == "live_session"]
    return {
        "company_id": company,
        "packet_generation_mode": "live_committee_sessions" if live_roles else "fallback",
        "generated_at": now.isoformat(),
        "top_ranked_candidates": top_candidates,
        "approval_posture": approval_posture,
        "cap_multiplier": cap_multiplier,
        "sizing_posture": "reduced" if float(cap_multiplier) < 1.0 else "baseline",
        "rationale": rationale,
        "missing_input_flags": missing_input_flags,
        "source_agents_consulted": source_agents_consulted,
        "committee_sources": committee_sources,
        "fresh_committee": bool(live_roles),
        "live_roles_responded": live_roles,
        "fallback_reason": committee_sources.get("_committee", {}).get("reason"),
        "execution_changed_by_packet": False,
        "packet_effects": [],
    }



def apply_company_packets(ranked_candidates: List[Dict[str, Any]], now: datetime | None = None) -> Dict[str, Dict[str, Any]]:
    packets: Dict[str, Dict[str, Any]] = {}
    by_company: Dict[str, List[Dict[str, Any]]] = {company: [] for company in COMPANIES}
    for candidate in ranked_candidates:
        by_company.setdefault(str(candidate.get("company_id")), []).append(candidate)

    for company, company_candidates in by_company.items():
        packet = build_company_packet(company, company_candidates, now=now)
        packets[company] = packet
        allowed_execs = max(0, min(MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE, int(MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE * packet["cap_multiplier"] + 0.9999)))
        executed_for_company = 0
        for candidate in company_candidates:
            if candidate.get("execution_state") != "executed":
                continue
            candidate["committee_packet_generation_mode"] = packet.get("packet_generation_mode")
            candidate["committee_fresh_participation"] = packet.get("fresh_committee", False)
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



def build_pseudo_candle(snapshot: Dict[str, Any], last_price: float | None) -> Dict[str, Any]:
    price = float(snapshot.get("price") or 0.0)
    open_price = float(last_price if last_price not in (None, 0) else price)
    high = max(open_price, price)
    low = min(open_price, price)
    return {
        "timestamp": snapshot.get("timestamp"),
        "open": open_price,
        "high": high,
        "low": low,
        "close": price,
        "candle_source": "pseudo_snapshot_ohlc",
        "candle_confidence": 0.35,
    }



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
    candle_history: Dict[str, List[Dict[str, Any]]] = {}
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
                price_key = (company, symbol)
                symbol_history = candle_history.setdefault(symbol, [])
                latest_candle = build_pseudo_candle(snapshot, last_prices.get(price_key))
                symbol_history.append(latest_candle)
                candle_history[symbol] = symbol_history[-20:]
                snapshot["candle_source"] = latest_candle["candle_source"]
                snapshot["candle_confidence"] = latest_candle["candle_confidence"]
                decision = build_decision(snapshot, company, last_prices.get(price_key), candle_history=candle_history[symbol])
                decision["vetoed_by_risk"] = abs(decision.get("signal_score", 0)) > 0.08
                decision["position_state"] = portfolio.positions[company].get(symbol, 0.0)
                decision["cash_snapshot"] = portfolio.cash.get(company, 0.0)
                decision["allocation_context"] = portfolio.allocations.get(company)
                decision["ranking_score"] = candidate_ranking_score(decision)
                decision["pretrade_selection_path"] = "ranked_then_company_packet"
                decision["pretrade_agent_participation"] = "company packet consulted after ranking"
                last_prices[price_key] = snapshot.get("price") or last_prices.get(price_key, 0.0)
                candidate_decisions.append(decision)

        apply_orion_bias_before_ranking(candidate_decisions)
        ranked_candidates = rank_and_select_candidates(candidate_decisions)
        company_packets = apply_company_packets(ranked_candidates, now=datetime.utcnow().replace(tzinfo=timezone.utc))
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
                        "pattern_flags": d.get("pattern_flags"),
                        "pattern_dir": d.get("pattern_dir"),
                        "pattern_strength": d.get("pattern_strength"),
                        "pattern_contribution": d.get("pattern_contribution"),
                        "pattern_confirmation": d.get("pattern_confirmation"),
                        "candle_source": d.get("candle_source"),
                        "candle_confidence": d.get("candle_confidence"),
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
