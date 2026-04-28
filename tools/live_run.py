"""Orchestration CLI for the live-data virtual-currency paper run."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List
import urllib.error
import urllib.request
from urllib.parse import quote_plus, urlparse

from tools.agent_runtime import collect_agent_reports
from tools.live_decision_engine import build_decision, DecisionResult
from tools.live_market_feed import fetch_market_data
from tools.live_orchestra import orchestrate
from tools.live_paper_portfolio import PortfolioState
from tools.rpg_state import apply_runtime_packet_rpg_updates, format_runtime_rpg_event
from tools.live_universe import target_symbol_list

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIVE_RUNS_ROOT = ROOT / "state" / "live_runs"
EVOLUTION_STATE_ROOT = ROOT / "state" / "companies"
CURRENT_RUN_PATH = LIVE_RUNS_ROOT / "current_run.json"
LIVE_RUN_POLL_SECONDS = int(os.getenv("LIVE_RUN_POLL_SECONDS", "10"))
LIVE_RUN_BACKOFF_BASE = int(os.getenv("LIVE_RUN_BACKOFF_SECONDS", "60"))
COMPANIES = ["company_001", "company_002", "company_003", "company_004"]
MAX_EXECUTIONS_PER_CYCLE = 6
MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE = 2
LIVE_COMMITTEE_TIMEOUT_SECONDS = int(os.getenv("LIVE_COMMITTEE_TIMEOUT_SECONDS", "25"))
LIVE_COMMITTEE_ROLES = ["Lucian", "Bianca", "Vera", "Iris", "Orion"]
COMMITTEE_REUSE_WINDOW_SECONDS = int(os.environ.get("COMMITTEE_REUSE_WINDOW_SECONDS", "600"))
BRIDGE_CALL_BUDGET_PER_RUN = int(os.environ.get("BRIDGE_CALL_BUDGET_PER_RUN", "120"))
MAX_OPEN_POSITIONS_PER_COMPANY = int(os.environ.get("ACC_MAX_OPEN_POSITIONS_PER_COMPANY", "6"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def virtual_currency_context(virtual_currency: float | None) -> Dict[str, Any]:
    if virtual_currency is None:
        return {
            "virtual_currency": None,
            "virtual_company_pool_total": None,
            "virtual_company_budget": None,
        }
    pool_total = float(virtual_currency) * 0.40
    company_budget = pool_total / max(len(COMPANIES), 1)
    return {
        "virtual_currency": round(float(virtual_currency), 6),
        "virtual_company_pool_total": round(pool_total, 6),
        "virtual_company_budget": round(company_budget, 6),
    }


def ensure_directories() -> None:
    LIVE_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    EVOLUTION_STATE_ROOT.mkdir(parents=True, exist_ok=True)


def create_run_id() -> str:
    return _utcnow().strftime("run_%Y%m%d_%H%M%S")


def run_directory(run_id: str) -> Path:
    run_dir = LIVE_RUNS_ROOT / run_id
    for sub in ("data", "artifacts", "logs", "packets", "reports"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


def write_current_run(run_id: str, pid: int, pgid: int | None = None) -> None:
    ensure_directories()
    data = {
        "run_id": run_id,
        "pid": pid,
        "pgid": pgid if pgid is not None else pid,
        "mode": "paper",
        "status": "running",
        "started_at": _utcnow().isoformat(),
    }
    CURRENT_RUN_PATH.write_text(json.dumps(data, indent=2))



def _bootstrap_last_prices_from_previous_run(current_run_id: str, symbols: List[str]) -> Dict[tuple[str, str], float]:
    requested_symbols = {str(symbol) for symbol in symbols if str(symbol)}
    if not requested_symbols:
        return {}
    eligible_runs: List[Path] = []
    for run_dir in LIVE_RUNS_ROOT.glob("run_*"):
        name = run_dir.name
        if (
            not run_dir.is_dir()
            or name >= current_run_id
            or not (name.startswith("run_") and len(name) == 19 and name[4:12].isdigit() and name[12] == "_" and name[13:19].isdigit())
        ):
            continue
        feed_path = run_dir / "data" / "market_feed.log"
        if feed_path.exists():
            eligible_runs.append(run_dir)
    for run_dir in sorted(eligible_runs, key=lambda path: path.name, reverse=True):
        feed_path = run_dir / "data" / "market_feed.log"
        symbol_prices: Dict[str, float] = {}
        try:
            rows = [line for line in feed_path.read_text().splitlines() if line.strip()]
        except Exception:
            continue
        for raw in rows:
            try:
                row = json.loads(raw)
            except Exception:
                continue
            symbol = str(row.get("symbol") or "")
            if symbol not in requested_symbols:
                continue
            try:
                price = float(row.get("price") or 0.0)
            except (TypeError, ValueError):
                continue
            if price > 0.0:
                symbol_prices[symbol] = price
        if symbol_prices:
            bootstrapped: Dict[tuple[str, str], float] = {}
            for company in COMPANIES:
                for symbol, price in symbol_prices.items():
                    bootstrapped[(company, symbol)] = price
            return bootstrapped
    return {}



def candidate_ranking_score(decision: Dict[str, Any]) -> float:
    policy_signal_score = abs(float(decision.get("policy_signal_score") or 0.0))
    ml_signal_score = abs(float(decision.get("ml_signal_score") or 0.0))
    model_confidence = abs(float(decision.get("model_score") or 0.5) - 0.5) * 2.0
    pattern_score = float(decision.get("pattern_score") or decision.get("pattern_contribution") or 0.0)
    score = round(policy_signal_score + ml_signal_score + model_confidence + pattern_score, 6)
    if score <= 0.0:
        candle_source = str(decision.get("candle_source") or decision.get("matched_context", {}).get("candle_source") or "").lower()
        candle_confidence = float(decision.get("candle_confidence") or decision.get("matched_context", {}).get("candle_confidence") or 0.0)
        if candle_source == "real_ohlc" and candle_confidence >= 0.7 and str(decision.get("decision") or "").upper() == "WAIT":
            return 0.0001
    return score


def _direction_from_score(value: Any) -> int:
    score = float(value or 0.0)
    if score > 0:
        return 1
    if score < 0:
        return -1
    return 0


def _promote_wait_candidate(candidate: Dict[str, Any]) -> bool:
    """Promote a WAIT candidate only when strict bullish evidence is confirmed.

    Earlier versions allowed a ranked WAIT candidate to become BUY when policy
    and ML scores aligned or a real-OHLC bootstrap looked confident. That made
    operator reports show final BUY actions even when weighted evidence_winner
    was WAIT. For V2 trading discipline, the selector may only promote WAIT
    when explicit pattern/3-candle confirmation agrees with the bullish signal.
    """
    if str(candidate.get("decision") or "").upper() != "WAIT":
        return False
    if float(candidate.get("position_state") or 0.0) > 0:
        return False
    if float(candidate.get("ranking_score") or 0.0) <= 0.0:
        return False

    evidence_winner = str(candidate.get("evidence_winner") or "").upper()
    if evidence_winner == "WAIT":
        candidate["decision_promotion_blocked_reason"] = "evidence_winner_wait"
        return False

    signal_votes = []
    for direction in (
        _direction_from_score(candidate.get("policy_signal_score")),
        _direction_from_score(candidate.get("ml_signal_score")),
    ):
        if direction:
            signal_votes.append(direction)
    if not signal_votes:
        candidate["decision_promotion_blocked_reason"] = "missing_signal_votes"
        return False
    signal_dir = signal_votes[0]
    if any(direction != signal_dir for direction in signal_votes[1:]):
        candidate["decision_promotion_blocked_reason"] = "signal_votes_disagree"
        return False
    if signal_dir <= 0:
        candidate["decision_promotion_blocked_reason"] = "non_bullish_signal"
        return False

    pattern_confirmation = candidate.get("pattern_confirmation") or {}
    pattern_dir = _direction_from_score(candidate.get("pattern_dir"))
    if not pattern_confirmation.get("satisfied") or pattern_dir <= 0:
        candidate["decision_promotion_blocked_reason"] = "missing_bullish_pattern_confirmation"
        return False

    orion_bias = _direction_from_score(candidate.get("orion_bias"))
    if candidate.get("orion_bias_applied") and orion_bias < 0:
        candidate["decision_promotion_blocked_reason"] = "orion_adverse_bias"
        return False

    candidate["decision"] = "BUY"
    candidate["decision_promoted_from"] = "WAIT"
    candidate["decision_promotion_reason"] = "strict_bullish_pattern_confirmation"
    return True



def rank_and_select_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = sorted(candidates, key=lambda c: c["ranking_score"], reverse=True)
    selected: List[Dict[str, Any]] = []
    per_company_counts: Dict[str, int] = {}
    for candidate in ranked:
        if candidate.get("vetoed_by_risk"):
            candidate["execution_state"] = "skipped"
            candidate["skip_reason"] = "risk_veto"
            continue
        _promote_wait_candidate(candidate)
        if candidate.get("decision") == "SELL" and float(candidate.get("position_state") or 0.0) <= 0.0:
            candidate["decision"] = "WAIT"
            candidate["decision_demoted_from"] = "SELL"
            candidate["decision_demotion_reason"] = "flat_account_sell_block"
        if (
            candidate.get("decision") == "BUY"
            and float(candidate.get("position_state") or 0.0) <= 0.0
            and int(candidate.get("open_positions_count") or 0) >= MAX_OPEN_POSITIONS_PER_COMPANY
        ):
            candidate["decision"] = "WAIT"
            candidate["decision_demoted_from"] = "BUY"
            candidate["decision_demotion_reason"] = "max_open_positions"
        if candidate.get("decision") not in {"BUY", "SELL"}:
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



def evolution_state_path(company: str) -> Path:
    return EVOLUTION_STATE_ROOT / company / "evolution_state.json"



def load_evolution_state(company: str) -> Dict[str, Any]:
    path = evolution_state_path(company)
    default = {"company_packet_cap_baseline": 1.0}
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
    except Exception:
        return default
    baseline = float(data.get("company_packet_cap_baseline", 1.0) or 1.0)
    return {"company_packet_cap_baseline": round(min(1.25, max(0.75, baseline)), 4)}



def save_evolution_state(company: str, state: Dict[str, Any]) -> None:
    path = evolution_state_path(company)
    path.parent.mkdir(parents=True, exist_ok=True)
    baseline = float(state.get("company_packet_cap_baseline", 1.0) or 1.0)
    payload = {"company_packet_cap_baseline": round(min(1.25, max(0.75, baseline)), 4)}
    path.write_text(json.dumps(payload, indent=2))


ORION_BIAS_BULL = 0.02
ORION_BIAS_BEAR = -0.02
ORION_STALE_AFTER_HOURS = 24.0
ORION_MATCH_FIELDS = ["analysis_summary", "research_summary", "ideas", "hypotheses", "evidence"]


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



def _stringify_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify_field(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{_stringify_field(k)} {_stringify_field(v)}" for k, v in value.items())
    return str(value)



def _orion_symbol_match_fields(report: Dict[str, Any], symbol: str) -> List[str]:
    symbol_text = str(symbol or "").upper()
    if not symbol_text:
        return []
    matches: List[str] = []
    for field in ORION_MATCH_FIELDS:
        value_text = _stringify_field(report.get(field)).upper()
        if symbol_text and symbol_text in value_text:
            matches.append(field)
    return matches



def _orion_direction_from_text(report: Dict[str, Any]) -> tuple[float, str]:
    text = " ".join(_stringify_field(report.get(field)) for field in ORION_MATCH_FIELDS).lower()
    bullish = any(phrase in text for phrase in ("bullish catalyst", "bullish", "positive catalyst", "upside catalyst", "buy", "long", "accumulate"))
    bearish = any(phrase in text for phrase in ("bearish catalyst", "bearish", "negative catalyst", "downside catalyst", "sell", "short", "distribute"))
    if bullish and not bearish:
        return ORION_BIAS_BULL, "bullish_catalyst"
    if bearish and not bullish:
        return ORION_BIAS_BEAR, "bearish_catalyst"
    return 0.0, "no_directional_catalyst"



def _orion_uncertainty_factor(report: Dict[str, Any]) -> float:
    text = " ".join(_stringify_field(report.get(field)) for field in ORION_MATCH_FIELDS).lower()
    uncertain = any(token in text for token in ("unclear", "uncertain", "insufficient", "mixed"))
    if report.get("missing_data") or uncertain:
        return 0.5
    return 1.0



def _normalize_orion_evidence_metadata(report: Dict[str, Any]) -> Dict[str, Any]:
    evidence = report.get("evidence")
    evidence_mode = None
    source_count = None
    latest_source_ts = None
    source_domains: List[str] = []
    if isinstance(evidence, list):
        evidence_mode = "structured" if any(isinstance(item, dict) for item in evidence) else "unstructured"
        source_count = 0
        domains = set()
        latest_ts = None
        for item in evidence:
            if not isinstance(item, dict):
                continue
            source_ts_raw = item.get("published_at") or item.get("retrieved_at")
            source_ts = _parse_report_timestamp({"timestamp": source_ts_raw}) if source_ts_raw else None
            url = str(item.get("url") or "")
            domain = urlparse(url).netloc.lower() if url else ""
            if item.get("title") and url and item.get("source") and source_ts_raw:
                source_count += 1
                if domain:
                    domains.add(domain)
                if source_ts and (latest_ts is None or source_ts > latest_ts):
                    latest_ts = source_ts
        latest_source_ts = latest_ts.isoformat() if latest_ts else None
        source_domains = sorted(domains)
    return {
        "evidence_mode": evidence_mode,
        "source_count": source_count,
        "latest_source_ts": latest_source_ts,
        "source_domains": source_domains,
    }



def _orion_has_evidence_metadata(report: Dict[str, Any]) -> bool:
    return bool(_normalize_orion_evidence_metadata(report).get("source_count"))



ORION_CACHE_FRESHNESS_HOURS = 1.0
ORION_CACHE_PATH = ROOT / "state" / "agents" / "orion" / "headlines_cache.jsonl"
ORION_SEARCH_GOVERNOR_PATH = ROOT / "state" / "agents" / "orion" / "search_governor.json"
ORION_SEARCH_DAILY_LIMIT = int(os.getenv("ORION_SEARCH_DAILY_LIMIT", "8"))
ORION_SEARCH_MONTHLY_LIMIT = int(os.getenv("ORION_SEARCH_MONTHLY_LIMIT", "250"))
ORION_LAST_FETCH_STATE = "unknown"


def _normalize_orion_query(symbol: str) -> str:
    return str(symbol or "").strip().upper()



def _load_orion_cache(symbol: str, max_age_hours: float = ORION_CACHE_FRESHNESS_HOURS) -> List[Dict[str, Any]] | None:
    symbol = _normalize_orion_query(symbol)
    if not ORION_CACHE_PATH.exists():
        return None
    try:
        for raw in ORION_CACHE_PATH.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            row_symbol = _normalize_orion_query(row.get("normalized_query") or row.get("symbol", ""))
            if row_symbol != symbol:
                continue
            cached_at = _parse_report_timestamp({"timestamp": row.get("timestamp") or row.get("cached_at")})
            if cached_at and (_utcnow() - cached_at) <= timedelta(hours=max_age_hours):
                return row.get("top_results") or row.get("articles") or []
    except Exception:
        pass
    return None


def _save_orion_cache(symbol: str, articles: List[Dict[str, Any]]) -> None:
    ORION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    top_results = []
    source_counts: Dict[str, int] = {}
    for article in articles[:3]:
        if not isinstance(article, dict):
            continue
        compact = {
            "title": str(article.get("title") or "").strip(),
            "url": str(article.get("url") or "").strip(),
            "source": str(article.get("source") or "unknown").strip(),
            "published_at": article.get("published_at"),
            "retrieved_at": article.get("retrieved_at"),
            "source_provenance": article.get("source_provenance"),
        }
        if compact["title"] and compact["url"]:
            top_results.append(compact)
            source_key = str(compact.get("source_provenance") or compact.get("source") or "unknown")
            source_counts[source_key] = source_counts.get(source_key, 0) + 1
    source_used = max(source_counts, key=source_counts.get) if source_counts else "unknown"
    summary = "; ".join(item["title"] for item in top_results[:3]) or f"{_normalize_orion_query(symbol)} cache entry"
    entry = {
        "normalized_query": _normalize_orion_query(symbol),
        "timestamp": _utcnow().isoformat(),
        "source_used": source_used,
        "top_results": top_results,
        "summary": summary,
    }
    with ORION_CACHE_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _load_orion_search_governor_state(now: datetime | None = None) -> Dict[str, Any]:
    now = now or _utcnow()
    today = now.date().isoformat()
    this_month = now.strftime("%Y-%m")
    default = {"monthly_used": 0, "daily_used": 0, "last_reset_day": today, "last_reset_month": this_month}
    if not ORION_SEARCH_GOVERNOR_PATH.exists():
        return default
    try:
        raw = json.loads(ORION_SEARCH_GOVERNOR_PATH.read_text())
    except Exception:
        return default
    state = {
        "monthly_used": max(0, int(raw.get("monthly_used", 0) or 0)),
        "daily_used": max(0, int(raw.get("daily_used", 0) or 0)),
        "last_reset_day": str(raw.get("last_reset_day") or today),
        "last_reset_month": str(raw.get("last_reset_month") or this_month),
    }
    if state["last_reset_day"] != today:
        state["daily_used"] = 0
        state["last_reset_day"] = today
    if state["last_reset_month"] != this_month:
        state["monthly_used"] = 0
        state["last_reset_month"] = this_month
    return state



def _save_orion_search_governor_state(state: Dict[str, Any]) -> None:
    ORION_SEARCH_GOVERNOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "monthly_used": max(0, int(state.get("monthly_used", 0) or 0)),
        "daily_used": max(0, int(state.get("daily_used", 0) or 0)),
        "last_reset_day": str(state.get("last_reset_day") or _utcnow().date().isoformat()),
        "last_reset_month": str(state.get("last_reset_month") or _utcnow().strftime("%Y-%m")),
    }
    ORION_SEARCH_GOVERNOR_PATH.write_text(json.dumps(payload, indent=2))



def _orion_search_budget_available(state: Dict[str, Any]) -> bool:
    return state["daily_used"] < ORION_SEARCH_DAILY_LIMIT and state["monthly_used"] < ORION_SEARCH_MONTHLY_LIMIT



def _orion_hermes_serpapi_headlines(symbol: str, max_age_hours: float = 24.0, limit: int = 3) -> List[Dict[str, Any]]:
    global ORION_LAST_FETCH_STATE
    results: List[Dict[str, Any]] = []
    ORION_LAST_FETCH_STATE = "no_fresh_results"
    provider_failed = False
    api_key = os.getenv("SERPAPI_API_KEY") or os.getenv("SERPAPI_KEY")
    if api_key:
        query = _normalize_orion_query(symbol)
        url = (
            "https://serpapi.com/search.json?"
            f"engine=google_news&q={quote_plus(query)}&hl=en&gl=us&api_key={quote_plus(api_key)}&num={int(limit)}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            articles = data.get("news_results") or data.get("organic_results") or []
            cutoff = _utcnow() - timedelta(hours=max_age_hours)
            for article in articles[:limit]:
                if not isinstance(article, dict):
                    continue
                published = article.get("date") or article.get("published_at") or article.get("publishedAt")
                if published:
                    pub_dt = _parse_report_timestamp({"timestamp": published})
                    if pub_dt and pub_dt < cutoff:
                        continue
                item = {
                    "title": str(article.get("title") or "").strip(),
                    "url": str(article.get("link") or article.get("url") or "").strip(),
                    "source": str(article.get("source") or article.get("publisher") or article.get("publication") or "serpapi").strip(),
                    "published_at": published,
                    "retrieved_at": _utcnow().isoformat(),
                    "source_provenance": "serpapi",
                }
                if item["title"] and item["url"]:
                    results.append(item)
            if results:
                ORION_LAST_FETCH_STATE = "ok"
        except Exception:
            provider_failed = True
            ORION_LAST_FETCH_STATE = "provider_fails"
    else:
        provider_failed = True
        ORION_LAST_FETCH_STATE = "provider_fails"
    if not results:
        results = _fetch_free_source_headlines(symbol, max_age_hours, limit)
        if results and not provider_failed:
            ORION_LAST_FETCH_STATE = "no_fresh_results"
        elif results and provider_failed:
            ORION_LAST_FETCH_STATE = "provider_fails"
        elif provider_failed:
            ORION_LAST_FETCH_STATE = "provider_fails"
        else:
            ORION_LAST_FETCH_STATE = "no_fresh_results"
    return results



def _orion_live_search(symbol: str, max_age_hours: float = 24.0, limit: int = 3) -> List[Dict[str, Any]]:
    return _orion_hermes_serpapi_headlines(symbol, max_age_hours=max_age_hours, limit=limit)



def _fetch_free_source_headlines(symbol: str, max_age_hours: float = 24.0, limit: int = 3) -> List[Dict[str, Any]]:
    """Fallback fetch using Yahoo Finance search (no API key required)."""
    query = symbol.upper()
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&news_count={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    news = data.get("news") or []
    results: List[Dict[str, Any]] = []
    cutoff = _utcnow() - timedelta(hours=max_age_hours)
    for item in news[:limit]:
        if not isinstance(item, dict):
            continue
        pub_ts = item.get("providerPublishTime")
        published_at = None
        if pub_ts:
            try:
                pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
                if pub_dt < cutoff:
                    continue
                published_at = pub_dt.isoformat()
            except (ValueError, TypeError, OSError):
                continue
        entry = {
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("link") or "").strip(),
            "source": str(item.get("publisher") or "yahoo_finance").strip(),
            "published_at": published_at,
            "retrieved_at": _utcnow().isoformat(),
            "source_provenance": "yahoo_fallback",
        }
        if entry["title"] and entry["url"]:
            results.append(entry)
    return results


def _orion_cache_window_hours(max_age_hours: float) -> float:
    return ORION_CACHE_FRESHNESS_HOURS if float(max_age_hours or 0.0) <= 24.0 else float(max_age_hours)


def _fetch_orion_headlines(symbol: str, max_age_hours: float = 24.0, limit: int = 3, actor_name: str = "Orion") -> List[Dict[str, Any]]:
    global ORION_LAST_FETCH_STATE
    if str(actor_name or "").strip().lower() != "orion":
        return []
    symbol = _normalize_orion_query(symbol)
    cached = _load_orion_cache(symbol, max_age_hours=_orion_cache_window_hours(max_age_hours))
    if cached is not None:
        ORION_LAST_FETCH_STATE = "cache_hit"
        return cached
    state = _load_orion_search_governor_state()
    if not _orion_search_budget_available(state):
        ORION_LAST_FETCH_STATE = "budget_exhausted"
        return []
    results = _orion_live_search(symbol, max_age_hours=max_age_hours, limit=limit)
    if results:
        state["daily_used"] += 1
        state["monthly_used"] += 1
        _save_orion_search_governor_state(state)
        _save_orion_cache(symbol, results)
    return results



def compute_orion_bias(decision: Dict[str, Any], report: Dict[str, Any], now: datetime | None = None) -> Dict[str, Any]:
    now = now or _utcnow().replace(tzinfo=timezone.utc)
    report_ts = _parse_report_timestamp(report)
    evidence_meta = _normalize_orion_evidence_metadata(report)
    has_structured_evidence = _orion_has_evidence_metadata(report)
    fetch_state = str(report.get("_orion_fetch_state") or "")
    if not has_structured_evidence and fetch_state in {"budget_exhausted", "provider_fails", "no_fresh_results"}:
        quality_state = fetch_state
    elif not has_structured_evidence and report.get("_orion_fetch_empty"):
        quality_state = "no_fresh_provider_results"
    else:
        quality_state = "evidence_backed" if has_structured_evidence else "legacy_text_only"
    default = {
        "orion_bias": 0.0,
        "orion_bias_reason": "no_report",
        "orion_report_timestamp": report_ts.isoformat() if report_ts else None,
        "orion_match_fields": [],
        "orion_bias_applied": False,
        "orion_quality_state": "degraded",
        "orion_fetch_state": fetch_state or None,
        **evidence_meta,
    }
    if not report:
        return default
    if _orion_report_is_stale(report, now):
        default["orion_bias_reason"] = "stale_report"
        return default
    match_fields = _orion_symbol_match_fields(report, str(decision.get("symbol") or ""))
    if not match_fields:
        default["orion_quality_state"] = quality_state
        default["orion_bias_reason"] = "no_symbol_match"
        return default
    base_bias, reason = _orion_direction_from_text(report)
    if base_bias == 0.0:
        if quality_state in {"budget_exhausted", "provider_fails", "no_fresh_results", "no_fresh_provider_results"}:
            default["orion_quality_state"] = quality_state
            default["orion_bias_reason"] = quality_state
            default["orion_match_fields"] = []
            return default
        default["orion_quality_state"] = quality_state
        default["orion_bias_reason"] = reason
        default["orion_match_fields"] = match_fields
        return default
    if not has_structured_evidence and quality_state in {"budget_exhausted", "provider_fails", "no_fresh_results", "no_fresh_provider_results"}:
        quality_state = "legacy_text_only"
    default["orion_quality_state"] = quality_state
    bias = round(base_bias * _orion_uncertainty_factor(report), 6)
    return {
        "orion_bias": bias,
        "orion_bias_reason": reason if abs(bias) == abs(base_bias) else f"{reason}_halved_for_uncertainty",
        "orion_report_timestamp": report_ts.isoformat() if report_ts else None,
        "orion_match_fields": match_fields,
        "orion_bias_applied": bias != 0.0,
        "orion_quality_state": quality_state,
        "orion_fetch_state": fetch_state or None,
        **evidence_meta,
    }



def apply_orion_bias_before_ranking(candidates: List[Dict[str, Any]], now: datetime | None = None) -> List[Dict[str, Any]]:
    now = now or _utcnow().replace(tzinfo=timezone.utc)
    report_cache: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        company = str(candidate.get("company_id"))
        symbol = str(candidate.get("symbol") or "")
        if company not in report_cache:
            report = latest_report(collect_agent_reports(company), "Orion") or {}
            current_evidence = report.get("evidence") or []
            has_fresh_evidence = bool(_normalize_orion_evidence_metadata(report).get("source_count"))
            symbol_match_fields = _orion_symbol_match_fields(report, symbol) if symbol else []
            if symbol and not has_fresh_evidence and symbol_match_fields:
                fetched = _fetch_orion_headlines(symbol, max_age_hours=24.0, limit=3, actor_name="Orion")
                fetch_state = ORION_LAST_FETCH_STATE
                if fetched:
                    current_evidence = fetched
                    report["evidence"] = current_evidence
                else:
                    report["_orion_fetch_empty"] = True
                if fetch_state and fetch_state not in {"ok", "cache_hit"}:
                    report["_orion_fetch_state"] = fetch_state
            report_cache[company] = report
        base_score = float(candidate.get("ranking_score") or candidate_ranking_score(candidate))
        candidate["ranking_score_before_orion"] = round(base_score, 6)
        meta = compute_orion_bias(candidate, report_cache[company], now=now)
        candidate.update(meta)
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



def _live_committee_payload_failed(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return True
    if payload.get("bridge_fallback_used"):
        return False
    if payload.get("bridge_failed"):
        return True
    if payload.get("bridge_error"):
        return True
    failure_markers = (
        str(payload.get("reply_text") or ""),
        str(payload.get("analysis_summary") or ""),
        str(payload.get("recommendation") or ""),
        str(payload.get("research_summary") or ""),
        str(payload.get("executive_summary") or ""),
        str(payload.get("summary") or ""),
    )
    lowered = " | ".join(failure_markers).lower()
    return "bridge call failed" in lowered


def _invoke_live_committee_agent(agent_id: str, message: str, run_id: str | None = None, cycle: int | None = None) -> Dict[str, Any]:
    cmd = [sys.executable, str(ROOT / "tools" / "pam.py"), "--agent", agent_id, message]
    env = dict(os.environ)
    if run_id is not None:
        env["ACC_RUN_ID"] = str(run_id)
    if cycle is not None:
        env["ACC_CYCLE"] = str(cycle)
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
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


def _proof_telemetry_enabled() -> bool:
    return os.environ.get("LIVE_RUN_PROOF_TELEMETRY", "").lower() in {"1", "true", "yes", "on"}


def _emit_paper_proof_telemetry(run_id: str) -> None:
    if not _proof_telemetry_enabled():
        return
    if os.environ.get("LIVE_RUN_PROOF_TELEMETRY_SUPPRESSED", "").lower() in {"1", "true", "yes", "on"}:
        return
    _invoke_live_committee_agent(
        _committee_agent_id("company_001", "Iris"),
        "Paper-proof telemetry probe. Return a minimal JSON object with status=ok.",
        run_id=run_id,
        cycle=0,
    )


def _run_live_committee(company: str, company_candidates: List[Dict[str, Any]], run_id: str | None = None, cycle: int | None = None) -> Dict[str, Dict[str, Any]]:
    message = _committee_cycle_message(company, company_candidates)
    outputs: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(LIVE_COMMITTEE_ROLES)) as pool:
        future_map = {
            pool.submit(_invoke_live_committee_agent, _committee_agent_id(company, role), message, run_id, cycle): role
            for role in LIVE_COMMITTEE_ROLES
        }
        for future in as_completed(future_map):
            role = future_map[future]
            outputs[role] = future.result()
    return outputs



def _committee_slate_signature(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "symbol": candidate.get("symbol"),
            "decision": candidate.get("decision"),
            "ranking_score": round(float(candidate.get("ranking_score") or 0.0), 4),
            "ranking_score_before_orion": round(float(candidate.get("ranking_score_before_orion") or 0.0), 4),
            "orion_bias": round(float(candidate.get("orion_bias") or 0.0), 4),
        }
        for candidate in candidates[:3]
    ]



def _sync_packet_top_ranked_candidates(packet: Dict[str, Any], company_candidates: List[Dict[str, Any]]) -> None:
    by_symbol = {str(candidate.get("symbol")): candidate for candidate in company_candidates}
    refreshed = []
    for top in list(packet.get("top_ranked_candidates") or []):
        current = by_symbol.get(str(top.get("symbol")))
        merged = dict(top)
        if current:
            for field in ("decision", "execution_state", "skip_reason", "ranking_score", "ranking_score_before_orion", "orion_bias", "decision_path"):
                if field in current:
                    merged[field] = current.get(field)
        refreshed.append(merged)
    packet["top_ranked_candidates"] = refreshed


def _latest_company_packet(company: str) -> Dict[str, Any] | None:
    try:
        current = read_current_run()
    except FileNotFoundError:
        return None
    run_id = str(current.get("run_id") or "")
    if not run_id:
        return None
    packets_path = LIVE_RUNS_ROOT / run_id / "artifacts" / "company_packets.jsonl"
    if not packets_path.exists():
        return None
    try:
        rows = [line for line in packets_path.read_text().splitlines() if line.strip()]
    except Exception:
        return None
    for raw in reversed(rows):
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if str(row.get("company_id") or "") == company:
            return row
    return None



def _bridge_calls_used_this_run() -> int:
    usage_path = ROOT / "state" / "agents" / "ledger" / "usage.jsonl"
    if not usage_path.exists():
        return 0
    try:
        current = read_current_run()
    except FileNotFoundError:
        current = {}
    started_at = _parse_report_timestamp({"timestamp": current.get("started_at")})
    used_calls = 0
    for raw in usage_path.read_text().splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception:
            continue
        if row.get("provider") != "openclaw_bridge":
            continue
        row_timestamp = _parse_report_timestamp(row)
        if started_at and row_timestamp and row_timestamp < started_at:
            continue
        used_calls += 1
    return used_calls



def _top_candidate_fresh_summary(company_candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    executable = [c for c in company_candidates if not c.get("vetoed_by_risk") and c.get("decision") in {"BUY", "SELL"}]
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



def build_company_packet(company: str, ranked_candidates: List[Dict[str, Any]], now: datetime | None = None, run_id: str | None = None, cycle: int | None = None) -> Dict[str, Any]:
    now = now or _utcnow()
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
    atlas_report = latest_report(saved_reports, "Atlas")
    atlas_confidence = str(atlas_report.get("confidence") or "").lower()
    atlas_recommendation = str(atlas_report.get("recommendation") or "")
    simulation_score = 0.05 if atlas_confidence == "high" else 0.02 if atlas_confidence == "medium" else 0.0
    if "delay" in atlas_recommendation.lower():
        simulation_score *= 0.5
    for candidate in ranked_candidates[:2]:
        candidate["simulation_score"] = round(simulation_score, 4)
        candidate["ranking_score"] = round(float(candidate.get("ranking_score") or 0.0) + simulation_score, 6)
    live_outputs: Dict[str, Dict[str, Any]] = {}
    committee_sources: Dict[str, Dict[str, Any]] = {}
    missing_input_flags: List[str] = []
    source_agents_consulted: List[str] = []
    has_actionable_candidates = any(
        not c.get("vetoed_by_risk") and c.get("decision") in {"BUY", "SELL"}
        for c in ranked_candidates
    )

    has_reviewable_wait_candidates = any(
        not c.get("vetoed_by_risk")
        and str(c.get("decision") or "").upper() == "WAIT"
        and float(c.get("ranking_score") or 0.0) > 0.0
        for c in ranked_candidates[:5]
    )

    if not has_actionable_candidates and not has_reviewable_wait_candidates:
        committee_sources["_committee"] = {
        "mode": "skipped",
        "reason": "no_actionable_or_reviewable_candidates",
    }
    else:
        recent_packet = _latest_company_packet(company)
        recent_packet_timestamp = None
        if recent_packet:
            recent_raw_timestamp = recent_packet.get("generated_at") or recent_packet.get("timestamp")
            if recent_raw_timestamp:
                try:
                    recent_packet_timestamp = datetime.fromisoformat(str(recent_raw_timestamp).replace("Z", "+00:00"))
                except ValueError:
                    recent_packet_timestamp = None
                if recent_packet_timestamp and recent_packet_timestamp.tzinfo is None:
                    recent_packet_timestamp = recent_packet_timestamp.replace(tzinfo=timezone.utc)
                if recent_packet_timestamp:
                    recent_packet_timestamp = recent_packet_timestamp.astimezone(timezone.utc)
        can_reuse_recent_packet = bool(
            recent_packet
            and recent_packet_timestamp
            and (now - recent_packet_timestamp).total_seconds() <= COMMITTEE_REUSE_WINDOW_SECONDS
            and _committee_slate_signature(top_candidates) == _committee_slate_signature(recent_packet.get("top_ranked_candidates") or [])
        )
        if can_reuse_recent_packet:
            prior_committee_sources = recent_packet.get("committee_sources") or {}
            for role in LIVE_COMMITTEE_ROLES:
                if role not in prior_committee_sources:
                    continue
                prior_meta = dict(prior_committee_sources[role] or {})
                prior_mode = prior_meta.get("mode")
                prior_meta["mode"] = "reused_cached"
                prior_meta["reused_from_mode"] = prior_mode
                prior_meta["reused_from_generated_at"] = recent_packet.get("generated_at") or recent_packet.get("timestamp")
                committee_sources[role] = prior_meta
            committee_sources["_committee"] = {
                "mode": "reused_cached",
                "reason": "matching_recent_slate_within_cooldown",
                "reused_from_generated_at": recent_packet.get("generated_at") or recent_packet.get("timestamp"),
            }
            return {
                "company_id": company,
                "packet_generation_mode": "cached_committee_reuse",
                "generated_at": now.isoformat(),
                "top_ranked_candidates": top_candidates,
                "approval_posture": recent_packet.get("approval_posture", "approve_top_candidate"),
                "cap_multiplier": recent_packet.get("cap_multiplier", 1.0),
                "sizing_posture": "reduced" if float(recent_packet.get("cap_multiplier") or 1.0) < 1.0 else "baseline",
                "rationale": recent_packet.get("rationale", ""),
                "missing_input_flags": list(recent_packet.get("missing_input_flags") or []),
                "source_agents_consulted": list(recent_packet.get("source_agents_consulted") or []),
                "committee_sources": committee_sources,
                "fresh_committee": False,
                "live_roles_responded": [],
                "fallback_reason": "reused_recent_committee_packet",
                "execution_changed_by_packet": False,
                "packet_effects": [],
            }
        if _bridge_calls_used_this_run() + len(LIVE_COMMITTEE_ROLES) > BRIDGE_CALL_BUDGET_PER_RUN:
            committee_sources["_committee"] = {"mode": "budget_throttled", "reason": "skipped_due_to_budget"}
        else:
            try:
                live_outputs = _run_live_committee(company, ranked_candidates, run_id=run_id, cycle=cycle)
            except Exception as exc:
                live_outputs = {}
                committee_sources["_committee"] = {"mode": "fallback", "reason": f"live_committee_failed:{exc}"}

    role_payloads: Dict[str, Dict[str, Any]] = {}
    failed_live_outputs: Dict[str, Dict[str, Any]] = {}
    for role in LIVE_COMMITTEE_ROLES:
        live_payload = live_outputs.get(role)
        if live_payload is not None and not _live_committee_payload_failed(live_payload):
            role_payloads[role] = live_payload
            source_agents_consulted.append(role)
            response_mode = "python_role_fallback" if live_payload.get("bridge_fallback_used") else "live_session"
            committee_sources[role] = {
                "mode": response_mode,
                "agent_id": _committee_agent_id(company, role),
                "summary": live_payload.get("analysis_summary")
                or live_payload.get("recommendation")
                or live_payload.get("research_summary")
                or live_payload.get("executive_summary")
                or live_payload.get("reply_text"),
            }
            if live_payload.get("bridge_error"):
                committee_sources[role]["bridge_error"] = live_payload.get("bridge_error")
            continue

        if live_payload is not None:
            failed_live_outputs[role] = live_payload

        missing_input_flags.append(role)
        saved = latest_report(saved_reports, role)
        if saved:
            committee_sources[role] = {
                "mode": "fallback_saved_after_live_failure" if role in failed_live_outputs else "fallback_saved",
                "summary": saved.get("analysis_summary") or saved.get("recommendation") or saved.get("research_summary") or saved.get("executive_summary") or saved.get("reply_text"),
            }
            if role in failed_live_outputs:
                committee_sources[role]["live_failure"] = failed_live_outputs[role].get("bridge_error") or failed_live_outputs[role].get("reply_text")
            if role in {"Lucian", "Bianca"}:
                committee_sources[role]["authority"] = "historical_only"
                continue
            role_payloads[role] = saved
            source_agents_consulted.append(role)
        elif role in failed_live_outputs:
            committee_sources[role] = {
                "mode": "live_session_failed",
                "agent_id": _committee_agent_id(company, role),
                "summary": failed_live_outputs[role].get("reply_text") or "bridge failure",
                "bridge_error": failed_live_outputs[role].get("bridge_error"),
            }
        else:
            committee_sources[role] = {"mode": "missing", "summary": "missing live committee output"}

    def _committee_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)[:800]
        return str(value)

    rationale_parts: List[str] = []
    for name in ("Iris", "Vera", "Orion"):
        payload = role_payloads.get(name)
        if not isinstance(payload, dict):
            continue
        value = (
            payload.get("analysis_summary")
            or payload.get("recommendation")
            or payload.get("research_summary")
            or payload.get("reply_text")
            or payload.get("summary", "")
        )
        text = _committee_text(value).strip()
        if text:
            rationale_parts.append(text)

    rationale = " | ".join(rationale_parts)
    approval_posture = derive_lucian_posture(role_payloads.get("Lucian", {}))
    cap_multiplier = derive_bianca_cap_multiplier(role_payloads.get("Bianca", {}))

    live_roles = [role for role, meta in committee_sources.items() if meta.get("mode") == "live_session"]
    fallback_roles = [role for role, meta in committee_sources.items() if meta.get("mode") == "python_role_fallback"]
    return {
        "company_id": company,
        "packet_generation_mode": "live_committee_sessions" if (live_roles or fallback_roles) else "fallback",
        "generated_at": now.isoformat(),
        "top_ranked_candidates": top_candidates,
        "approval_posture": approval_posture,
        "cap_multiplier": cap_multiplier,
        "sizing_posture": "reduced" if float(cap_multiplier) < 1.0 else "baseline",
        "rationale": rationale,
        "missing_input_flags": missing_input_flags,
        "source_agents_consulted": source_agents_consulted,
        "committee_sources": committee_sources,
        "fresh_committee": bool(live_roles or fallback_roles),
        "live_roles_responded": live_roles,
        "python_fallback_roles_responded": fallback_roles,
        "fallback_reason": committee_sources.get("_committee", {}).get("reason"),
        "execution_changed_by_packet": False,
        "packet_effects": [],
    }



def apply_company_packets(ranked_candidates: List[Dict[str, Any]], now: datetime | None = None, run_id: str | None = None, cycle: int | None = None) -> Dict[str, Dict[str, Any]]:
    packets: Dict[str, Dict[str, Any]] = {}
    by_company: Dict[str, List[Dict[str, Any]]] = {company: [] for company in COMPANIES}
    for candidate in ranked_candidates:
        by_company.setdefault(str(candidate.get("company_id")), []).append(candidate)

    for company, company_candidates in by_company.items():
        packet = build_company_packet(company, company_candidates, now=now, run_id=run_id, cycle=cycle)
        packets[company] = packet
        evolution_state = load_evolution_state(company)
        cap_baseline = float(evolution_state.get("company_packet_cap_baseline", 1.0) or 1.0)
        allowed_execs = max(0, min(MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE, int(MAX_EXECUTIONS_PER_COMPANY_PER_CYCLE * cap_baseline * packet["cap_multiplier"] + 0.9999)))
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
        _sync_packet_top_ranked_candidates(packet, company_candidates)
    return packets


def read_current_run() -> Dict[str, Any]:
    if not CURRENT_RUN_PATH.exists():
        raise FileNotFoundError("No current live run tracked")
    return json.loads(CURRENT_RUN_PATH.read_text())


def clear_current_run() -> None:
    if CURRENT_RUN_PATH.exists():
        CURRENT_RUN_PATH.unlink()


def prune_old_run_artifacts(current_run_id: str) -> None:
    bulky_paths = [
        ("artifacts", "paper_decisions.jsonl"),
        ("artifacts", "company_packets.jsonl"),
        ("artifacts", "strategy.log"),
        ("data", "market_feed.log"),
    ]
    eligible_runs: List[Path] = []
    for run_dir in LIVE_RUNS_ROOT.glob("run_*"):
        name = run_dir.name
        if (
            not run_dir.is_dir()
            or name >= current_run_id
            or not (name.startswith("run_") and len(name) == 19 and name[4:12].isdigit() and name[12] == "_" and name[13:19].isdigit())
        ):
            continue
        meta_path = run_dir / "run_metadata.json"
        if not meta_path.exists():
            continue
        try:
            status = json.loads(meta_path.read_text()).get("status")
        except Exception:
            continue
        if status in {"completed", "stopped"}:
            eligible_runs.append(run_dir)
    for run_dir in sorted(eligible_runs, key=lambda path: path.name, reverse=True)[2:]:
        for parts in bulky_paths:
            path = run_dir.joinpath(*parts)
            if path.exists():
                path.unlink()


def load_company_rankings(limit: int = 5) -> Dict[str, Any]:
    warehouse_path = ROOT / "data" / "warehouse.sqlite"
    rankings = {"source": None, "sort_by": "fitness", "top": []}
    if not warehouse_path.exists():
        return rankings
    try:
        with sqlite3.connect(warehouse_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT c.name,
                       cp.latest_fitness,
                       cp.latest_account_value,
                       cp.latest_realized_pnl,
                       cp.latest_unrealized_pnl,
                       cp.latest_trade_count,
                       cp.latest_win_rate,
                       cp.latest_drawdown,
                       cp.allocation_percent,
                       lrs.mode,
                       cp.lifecycle_state
                FROM companies c
                JOIN company_performance cp ON cp.company_id = c.id
                LEFT JOIN latest_run_summary lrs ON lrs.company = c.name
                ORDER BY cp.latest_fitness DESC, cp.latest_account_value DESC, c.name ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
    except sqlite3.Error:
        return rankings
    rankings["source"] = "company_performance"
    rankings["top"] = [
        {
            "rank": index,
            "company": row[0],
            "fitness": row[1],
            "account_value": row[2],
            "realized_pnl": row[3],
            "unrealized_pnl": row[4],
            "trade_count": row[5],
            "win_rate": row[6],
            "drawdown": row[7],
            "allocation_percent": row[8],
            "latest_mode": row[9],
            "lifecycle_state": row[10],
        }
        for index, row in enumerate(rows, start=1)
    ]
    return rankings



def write_bridge_usage_report(run_dir: Path, run_id: str, status: str | None, meta: Dict[str, Any]) -> None:
    def _read_jsonl_rows(path: Path, provider: str | None = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not path.exists():
            return rows
        for raw in path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if provider and row.get("provider") != provider:
                continue
            rows.append(row)
        return rows

    started_at = _parse_report_timestamp({"timestamp": meta.get("started_at")})
    ended_at = _parse_report_timestamp({"timestamp": meta.get("ended_at")}) or _utcnow()
    bridge_local_path = run_dir / "artifacts" / "bridge_usage.jsonl"
    bridge_global_path = ROOT / "state" / "agents" / "ledger" / "usage.jsonl"
    bridge_rows = _read_jsonl_rows(bridge_local_path, "openclaw_bridge")
    bridge_source = "run-local bridge_usage.jsonl" if bridge_rows else "global usage.jsonl"
    if not bridge_rows:
        bridge_rows = _read_jsonl_rows(bridge_global_path, "openclaw_bridge")
    rows: List[Dict[str, Any]] = []
    for row in bridge_rows:
        row_timestamp = _parse_report_timestamp(row)
        if started_at and row_timestamp and not (started_at <= row_timestamp <= ended_at):
            continue
        rows.append(row)
    total_calls = len(rows)
    success_count = sum(1 for row in rows if row.get("outcome") == "success")
    error_count = sum(1 for row in rows if row.get("outcome") == "error")
    budget_throttled_count = 0
    reused_cached_count = 0
    no_actionable_skip_count = 0
    packets_path = run_dir / "artifacts" / "company_packets.jsonl"
    if packets_path.exists():
        for raw in packets_path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            committee_meta = (row.get("committee_sources") or {}).get("_committee") or {}
            if committee_meta.get("reason") == "skipped_due_to_budget" or committee_meta.get("mode") == "budget_throttled":
                budget_throttled_count += 1
            if committee_meta.get("mode") == "reused_cached":
                reused_cached_count += 1
            if committee_meta.get("reason") == "no_actionable_candidates":
                no_actionable_skip_count += 1
    ledger_local_path = run_dir / "artifacts" / "ledger_usage.jsonl"
    ledger_global_path = ROOT / "state" / "agents" / "ledger" / "usage.jsonl"
    ledger_rows = _read_jsonl_rows(ledger_local_path)
    ledger_source = "run-local ledger_usage.jsonl" if ledger_rows else "global usage.jsonl"
    if not ledger_rows:
        ledger_rows = _read_jsonl_rows(ledger_global_path)
    token_rows = [row for row in ledger_rows if row.get("total_tokens") is not None]
    cost_rows = [row for row in ledger_rows if row.get("estimated_cost") is not None]
    prompt_tokens = sum(int(row.get("prompt_tokens") or 0) for row in token_rows)
    completion_tokens = sum(int(row.get("completion_tokens") or 0) for row in token_rows)
    total_tokens = sum(int(row.get("total_tokens") or 0) for row in token_rows)
    estimated_cost_total = round(sum(float(row.get("estimated_cost") or 0.0) for row in cost_rows), 6) if cost_rows else None
    per_company: Dict[str, int] = {}
    per_agent: Dict[str, int] = {}
    for row in rows:
        company = str(row.get("company") or "unscoped")
        agent = str(row.get("agent") or "unknown")
        per_company[company] = per_company.get(company, 0) + 1
        per_agent[agent] = per_agent.get(agent, 0) + 1
    lines = [
        "# Bridge Ledger Usage",
        f"Run: {run_id}",
        f"Status: {status or 'unknown'}",
        f"Bridge source: {bridge_source}",
        f"Ledger source: {ledger_source}",
        f"Scope: {'current run window' if started_at else 'visible bridge ledger records'}",
        f"Total bridge calls: {total_calls}",
        f"Success: {success_count}",
        f"Error: {error_count}",
        "",
        "Ledger telemetry:",
        f"- rows: {len(ledger_rows)}",
        f"- token_rows: {len(token_rows)}",
        f"- cost_rows: {len(cost_rows)}",
        f"- prompt_tokens: {prompt_tokens}",
        f"- completion_tokens: {completion_tokens}",
        f"- total_tokens: {total_tokens}",
        f"- estimated_cost_total: {estimated_cost_total if estimated_cost_total is not None else 'unavailable'}",
        "",
        "Cost controls:",
        f"- budget_throttled: {budget_throttled_count}",
        f"- reused_cached: {reused_cached_count}",
        f"- no_actionable_candidates: {no_actionable_skip_count}",
        "",
        "Per company:",
    ]
    if per_company:
        lines.extend(f"- {company}: {count}" for company, count in sorted(per_company.items()))
    else:
        lines.append("- none")
    lines.extend(["", "Per agent:"])
    if per_agent:
        lines.extend(f"- {agent}: {count}" for agent, count in sorted(per_agent.items()))
    else:
        lines.append("- none")
    (run_dir / "artifacts" / "ledger_usage.txt").write_text("\n".join(lines).rstrip() + "\n")



def write_agent_performance_report(run_dir: Path, run_id: str, status: str | None, last_packets: Dict[str, Dict[str, Any]]) -> None:
    roles = {"Lucian": "Executive", "Bianca": "CFO", "Vera": "Manager", "Iris": "Analyst", "Orion": "Operations", "Pam": "Coordinator", "Rowan": "Research", "Bob": "Operations", "Sloane": "Evolution", "Atlas": "Simulator", "June": "Archivist"}
    usage_path = ROOT / "state" / "agents" / "ledger" / "usage.jsonl"
    usage: Dict[tuple[str, str], int] = {}
    if usage_path.exists():
        for raw in usage_path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            agent_id = str(row.get("agent") or "")
            company = str(row.get("company") or "")
            for agent in roles:
                if company and agent_id.startswith(agent.lower() + "_"):
                    usage[(company, agent)] = usage.get((company, agent), 0) + int(row.get("total_tokens") or 0)
                    break
    lines = ["# Agent Performance", f"Run: {run_id}", f"Status: {status or 'unknown'}", ""]
    for company in sorted(last_packets):
        packet = last_packets[company]
        lines.append(f"## {company}")
        committee_sources = packet.get("committee_sources") or {}
        consulted = set(packet.get("source_agents_consulted") or [])
        agents = sorted(set(roles) | consulted | set(committee_sources))
        company_lines: List[str] = []
        for agent in agents:
            summary = "no measurable impact"
            verdict = "No visible contribution"
            meaningful = False
            if agent == "Lucian":
                lucian_meta = committee_sources.get("Lucian") or {}
                summary = f"approval_posture={packet.get('approval_posture', 'unknown')}"
                verdict = "Constraining" if packet.get("approval_posture") == "company_veto" else "Impacting"
                meaningful = packet.get("approval_posture") == "company_veto" or lucian_meta.get("mode") != "live_session" or lucian_meta.get("authority") == "historical_only"
            elif agent == "Bianca":
                bianca_meta = committee_sources.get("Bianca") or {}
                summary = f"cap_multiplier={packet.get('cap_multiplier', 'n/a')}"
                verdict = "Constraining" if float(packet.get("cap_multiplier") or 1.0) < 1.0 else "Impacting"
                meaningful = float(packet.get("cap_multiplier") or 1.0) < 1.0 or bianca_meta.get("mode") != "live_session" or bianca_meta.get("authority") == "historical_only"
            elif agent in committee_sources:
                summary = str((committee_sources.get(agent) or {}).get("summary") or "consulted, summary missing")
                verdict = "Advisory-only"
                meaningful = summary not in {"no measurable impact", "consulted, summary missing"}
            elif agent in consulted:
                summary = "consulted, summary missing"
                verdict = "Advisory-only"
            if not meaningful:
                continue
            tokens = usage.get((company, agent))
            token_text = str(tokens) if tokens is not None else "n/a"
            company_lines.append(f"- {agent} ({roles.get(agent, 'Unknown')}): {summary} | tokens={token_text} | verdict={verdict}")
        if company_lines:
            lines.extend(company_lines)
            lines.append("")
        else:
            lines.pop()
    (run_dir / "reports" / "agent_performance.md").write_text("\n".join(lines).rstrip() + "\n")



def write_company_meetings_report(run_dir: Path, run_id: str, status: str | None, last_packets: Dict[str, Dict[str, Any]]) -> None:
    lines = ["# Company Meetings", f"Run: {run_id}", f"Status: {status or 'unknown'}", ""]
    included = 0
    for company in sorted(last_packets):
        packet = last_packets[company]
        committee_sources = packet.get("committee_sources") or {}
        executed_actions = []
        for candidate in packet.get("top_ranked_candidates") or []:
            decision = str(candidate.get("decision") or "").upper()
            if candidate.get("execution_state") == "executed" and decision in {"BUY", "SELL"}:
                executed_actions.append(f"{decision} {candidate.get('symbol') or 'unknown'}")
        vetoed_symbols = [
            str(effect).split(":", 1)[1]
            for effect in (packet.get("packet_effects") or [])
            if str(effect).startswith("vetoed:")
        ]
        notable_veto = packet.get("approval_posture") == "company_veto" or bool(vetoed_symbols)
        budget_throttled = (committee_sources.get("_committee") or {}).get("reason") == "skipped_due_to_budget"
        if not executed_actions and not notable_veto and not budget_throttled:
            continue
        included += 1
        outcome_parts = []
        if executed_actions:
            outcome_parts.append("Actions: " + ", ".join(executed_actions))
        if notable_veto:
            outcome_parts.append("Major veto: " + (", ".join(vetoed_symbols) if vetoed_symbols else "company_veto"))
        if budget_throttled:
            outcome_parts.append("Budget throttle: skipped_due_to_budget")
        lines.append(f"## {company}")
        lines.append(f"- Outcome: {' | '.join(outcome_parts)}")
        lines.append("")
    anomaly_parts: List[str] = []
    risk_path = run_dir / "artifacts" / "risk.log"
    if risk_path.exists():
        risk_veto_count = 0
        for raw in risk_path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            if row.get("veto") is True:
                risk_veto_count += 1
        if risk_veto_count:
            anomaly_parts.append(f"risk_veto_events={risk_veto_count}")
    log_path = run_dir / "logs" / "run.log"
    if log_path.exists():
        rate_limit_count = 0
        feed_error_count = 0
        for raw in log_path.read_text().splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except Exception:
                continue
            event = row.get("event")
            if event == "rate_limit":
                rate_limit_count += 1
            elif event == "feed_error":
                feed_error_count += 1
        if rate_limit_count:
            anomaly_parts.append(f"rate_limit_events={rate_limit_count}")
        if feed_error_count:
            anomaly_parts.append(f"feed_error_events={feed_error_count}")
    if anomaly_parts:
        lines.append("## anomalies")
        for part in anomaly_parts:
            lines.append(f"- {part}")
        lines.append("")
    if included == 0 and not anomaly_parts:
        lines.append("- No buys, sells, major vetoes, major anomalies, or budget throttles.")
    (run_dir / "reports" / "company_meetings.md").write_text("\n".join(lines).rstrip() + "\n")



def write_daily_digest(run_id: str) -> None:
    run_dir = run_directory(run_id)
    meta_path = run_dir / "run_metadata.json"
    strategy_path = run_dir / "artifacts" / "strategy.log"
    packets_path = run_dir / "artifacts" / "company_packets.jsonl"
    ledger_path = ROOT / "state" / "agents" / "ledger" / "usage.jsonl"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    last_strategy = {}
    if strategy_path.exists():
        lines = [line.strip() for line in strategy_path.read_text().splitlines() if line.strip()]
        if lines:
            last_strategy = json.loads(lines[-1])
    last_packets: Dict[str, Dict[str, Any]] = {}
    symbol_counts: Dict[str, int] = {}
    company_packet_count = 0
    if packets_path.exists():
        for raw in packets_path.read_text().splitlines():
            if not raw.strip():
                continue
            row = json.loads(raw)
            company_packet_count += 1
            company = str(row.get("company_id") or "")
            if company:
                last_packets[company] = row
            for candidate in row.get("top_ranked_candidates") or []:
                symbol = candidate.get("symbol")
                if symbol:
                    symbol_counts[str(symbol)] = symbol_counts.get(str(symbol), 0) + 1
    digest = {
        "run_id": run_id,
        "status": meta.get("status"),
        "started_at": meta.get("started_at"),
        "finished_at": meta.get("ended_at"),
        "company_packet_count": company_packet_count,
        "executed_count": (last_strategy.get("ranking_summary") or {}).get("executed_count", 0),
        "skipped_count": (last_strategy.get("ranking_summary") or {}).get("skipped_count", 0),
        "top_company_activity": [
            {
                "company_id": company,
                "approval_posture": packet.get("approval_posture"),
                "resulting_execution_posture": packet.get("resulting_execution_posture"),
                "source_agents_consulted": packet.get("source_agents_consulted"),
            }
            for company, packet in sorted(last_packets.items())[:4]
        ],
        "top_symbols": [symbol for symbol, _count in sorted(symbol_counts.items(), key=lambda item: (-item[1], item[0]))[:5]],
        "ledger_usage_present": ledger_path.exists(),
        "company_rankings": load_company_rankings(),
    }
    (run_dir / "reports" / "daily_digest.json").write_text(json.dumps(digest, indent=2))
    write_company_meetings_report(run_dir, run_id, meta.get("status"), last_packets)
    write_agent_performance_report(run_dir, run_id, meta.get("status"), last_packets)
    write_bridge_usage_report(run_dir, run_id, meta.get("status"), meta)




def _run_governance_hook(run_id: str, hook: str, script_name: str, disable_env: str, timeout_env: str, hook_timeout_env: str, extra_args: list[str] | None = None) -> None:
    """Run a post-run governance script without making the live run fragile."""
    if os.getenv(disable_env, "0").strip().lower() in {"1", "true", "yes", "on"}:
        return
    run_dir = run_directory(run_id)
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifacts_dir / f"{hook}.log"
    err_path = artifacts_dir / f"{hook}_error.log"
    cmd = [
        sys.executable,
        str(ROOT / "tools" / script_name),
        "--run-id",
        run_id,
        "--timeout",
        os.getenv(timeout_env, "420"),
    ]
    if extra_args:
        cmd.extend(extra_args)
    started_at = _utcnow().isoformat()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=int(os.getenv(hook_timeout_env, "480")),
            env=dict(os.environ),
        )
        log_path.write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": hook,
                    "status": "success" if result.returncode == 0 else "failed",
                    "returncode": result.returncode,
                    "cmd": cmd,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        err_path.write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": hook,
                    "status": "error",
                    "cmd": cmd,
                    "error": repr(exc),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


def run_external_plan_context_snapshot(run_id):
    """Bind roadmap/planning docs into the live-run artifact stream.

    This is intentionally non-fatal. The external plan context helps governance
    agents remember roadmap/V2/V3/Hermes/Grant doctrine, but a snapshot failure
    must never kill a trading run.
    """
    if os.environ.get("DISABLE_EXTERNAL_PLAN_CONTEXT") == "1":
        print("External plan context snapshot disabled via DISABLE_EXTERNAL_PLAN_CONTEXT=1")
        return

    try:
        project_root = globals().get("ROOT", Path("/opt/openclaw/.openclaw/workspace"))
        cmd = [sys.executable, "tools/external_plan_context_snapshot.py"]
        if run_id:
            cmd.extend(["--run-id", str(run_id)])

        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            text=True,
            capture_output=True,
            timeout=120,
        )

        out_dir = Path("state") / "external_plan_context"
        out_dir.mkdir(parents=True, exist_ok=True)

        hook_log = out_dir / f"{run_id or 'NO_RUN'}_external_plan_context_hook.log"
        hook_log.write_text(
            (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""),
            encoding="utf-8",
        )

        if proc.returncode != 0:
            print(f"External plan context snapshot failed: {proc.returncode}; see {hook_log}")
        else:
            print(f"External plan context snapshot completed; see {hook_log}")

    except Exception as exc:
        try:
            out_dir = Path("state") / "external_plan_context"
            out_dir.mkdir(parents=True, exist_ok=True)
            error_log = out_dir / f"{run_id or 'NO_RUN'}_external_plan_context_hook_error.log"
            error_log.write_text(str(exc), encoding="utf-8")
        except Exception:
            pass

        print(f"External plan context snapshot skipped after error: {exc}")

def run_ledger_post_run_review(run_id: str) -> None:
    """Run Ledger's token/cost governance review after core reports exist."""
    _run_governance_hook(
        run_id,
        hook="ledger_review_hook",
        script_name="ledger_cost_review.py",
        disable_env="DISABLE_LEDGER_POST_RUN_REVIEW",
        timeout_env="LEDGER_REVIEW_TIMEOUT_SECONDS",
        hook_timeout_env="LEDGER_REVIEW_HOOK_TIMEOUT_SECONDS",
    )


def run_helena_post_run_review(run_id: str) -> None:
    """Run Helena's risk review before executive synthesis."""
    _run_governance_hook(
        run_id,
        hook="helena_review_hook",
        script_name="helena_risk_review.py",
        disable_env="DISABLE_HELENA_POST_RUN_REVIEW",
        timeout_env="HELENA_REVIEW_TIMEOUT_SECONDS",
        hook_timeout_env="HELENA_REVIEW_HOOK_TIMEOUT_SECONDS",
    )


def run_grant_post_run_speech(run_id: str) -> None:
    """Run Grant's controlled pressure speech.

    Listener note-taking is opt-in through GRANT_SPEECH_LISTENERS so we can test
    one listener such as bob_company_001 before broadcasting cliff notes broadly.
    """
    extra_args: list[str] = []
    listeners = os.getenv("GRANT_SPEECH_LISTENERS", "").strip()
    if listeners:
        extra_args.extend(["--listeners", listeners])
    speech_type = os.getenv("GRANT_SPEECH_TYPE", "").strip()
    if speech_type:
        extra_args.extend(["--speech-type", speech_type])
    _run_governance_hook(
        run_id,
        hook="grant_speech_hook",
        script_name="grant_speech_review.py",
        disable_env="DISABLE_GRANT_POST_RUN_SPEECH",
        timeout_env="GRANT_SPEECH_TIMEOUT_SECONDS",
        hook_timeout_env="GRANT_SPEECH_HOOK_TIMEOUT_SECONDS",
        extra_args=extra_args,
    )


def run_selene_post_run_review(run_id: str) -> None:
    """Run Selene's Master Treasurer review before executive synthesis."""
    _run_governance_hook(
        run_id,
        hook="selene_review_hook",
        script_name="selene_treasury_review.py",
        disable_env="DISABLE_SELENE_POST_RUN_REVIEW",
        timeout_env="SELENE_REVIEW_TIMEOUT_SECONDS",
        hook_timeout_env="SELENE_REVIEW_HOOK_TIMEOUT_SECONDS",
    )


def run_ariadne_post_run_review(run_id: str) -> None:
    """Run Ariadne's AI Agent Resources workforce review before executive synthesis."""
    _run_governance_hook(
        run_id,
        hook="ariadne_review_hook",
        script_name="ariadne_workforce_review.py",
        disable_env="DISABLE_ARIADNE_POST_RUN_REVIEW",
        timeout_env="ARIADNE_REVIEW_TIMEOUT_SECONDS",
        hook_timeout_env="ARIADNE_REVIEW_HOOK_TIMEOUT_SECONDS",
    )


def run_june_post_run_archive(run_id: str) -> None:
    """Run June's archive pass after Yam Yam has produced the executive review."""
    _run_governance_hook(
        run_id,
        hook="june_archive_hook",
        script_name="june_archive_review.py",
        disable_env="DISABLE_JUNE_POST_RUN_ARCHIVE",
        timeout_env="JUNE_ARCHIVE_TIMEOUT_SECONDS",
        hook_timeout_env="JUNE_ARCHIVE_HOOK_TIMEOUT_SECONDS",
    )

def run_axiom_post_run_review(run_id: str) -> None:
    """Run Axiom's post-run evaluator review as non-fatal governance.

    Axiom is an evaluator, not a trade-cycle participant. He should review the
    completed run after core artifacts and reports exist, then write his own
    review, RPG history, and memory notes. This is default governance; disable
    only for emergency/debug cases with DISABLE_AXIOM_POST_RUN_REVIEW=1.
    """
    if os.getenv("DISABLE_AXIOM_POST_RUN_REVIEW", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return

    run_dir = run_directory(run_id)
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifacts_dir / "axiom_review_hook.log"

    cmd = [
        sys.executable,
        str(ROOT / "tools" / "axiom_evaluator_review.py"),
        "--run-id",
        run_id,
        "--timeout",
        os.getenv("AXIOM_REVIEW_TIMEOUT_SECONDS", "420"),
    ]

    started_at = _utcnow().isoformat()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=int(os.getenv("AXIOM_REVIEW_HOOK_TIMEOUT_SECONDS", "480")),
            env=dict(os.environ),
        )
        log_path.write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": "axiom_post_run_review",
                    "status": "success" if result.returncode == 0 else "failed",
                    "returncode": result.returncode,
                    "cmd": cmd,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "review_path": str(ROOT / "state" / "axiom_reviews" / f"{run_id}_axiom_review.txt"),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        (artifacts_dir / "axiom_review_hook_error.log").write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": "axiom_post_run_review",
                    "status": "error",
                    "cmd": cmd,
                    "error": repr(exc),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


def run_vivienne_post_run_review(run_id: str) -> None:
    """Run Vivienne's post-run financial truth review as non-fatal governance.

    Vivienne is the Master CFO. She reviews target trustworthiness, portfolio
    coverage, P/L reality, and whether missing artifacts are creating fake wins
    or fake losses. She should run after Axiom and before Yam Yam so the Master
    CEO can synthesize evidence truth plus financial truth.
    """
    if os.getenv("DISABLE_VIVIENNE_POST_RUN_REVIEW", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return

    run_dir = run_directory(run_id)
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifacts_dir / "vivienne_review_hook.log"

    cmd = [
        sys.executable,
        str(ROOT / "tools" / "vivienne_financial_review.py"),
        "--run-id",
        run_id,
        "--timeout",
        os.getenv("VIVIENNE_REVIEW_TIMEOUT_SECONDS", "420"),
    ]

    started_at = _utcnow().isoformat()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=int(os.getenv("VIVIENNE_REVIEW_HOOK_TIMEOUT_SECONDS", "480")),
            env=dict(os.environ),
        )
        log_path.write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": "vivienne_post_run_review",
                    "status": "success" if result.returncode == 0 else "failed",
                    "returncode": result.returncode,
                    "cmd": cmd,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "review_path": str(ROOT / "state" / "vivienne_reviews" / f"{run_id}_vivienne_review.txt"),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        (artifacts_dir / "vivienne_review_hook_error.log").write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": "vivienne_post_run_review",
                    "status": "error",
                    "cmd": cmd,
                    "error": repr(exc),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

def run_yam_yam_post_run_review(run_id: str) -> None:
    """Run Yam Yam's post-run executive review as non-fatal governance.

    Yam Yam is the Master CEO. She should synthesize target state, Grant's
    briefing, Axiom's evaluator review, and run artifacts after the run is
    complete. This is default governance; disable only for emergency/debug
    cases with DISABLE_YAM_YAM_POST_RUN_REVIEW=1.
    """
    if os.getenv("DISABLE_YAM_YAM_POST_RUN_REVIEW", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return

    run_dir = run_directory(run_id)
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifacts_dir / "yam_yam_review_hook.log"

    cmd = [
        sys.executable,
        str(ROOT / "tools" / "yam_yam_executive_review.py"),
        "--run-id",
        run_id,
        "--timeout",
        os.getenv("YAM_YAM_REVIEW_TIMEOUT_SECONDS", "420"),
    ]

    started_at = _utcnow().isoformat()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=int(os.getenv("YAM_YAM_REVIEW_HOOK_TIMEOUT_SECONDS", "480")),
            env=dict(os.environ),
        )
        log_path.write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": "yam_yam_post_run_review",
                    "status": "success" if result.returncode == 0 else "failed",
                    "returncode": result.returncode,
                    "cmd": cmd,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "review_path": str(ROOT / "state" / "executive_reviews" / f"{run_id}_yam_yam_review.txt"),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        (artifacts_dir / "yam_yam_review_hook_error.log").write_text(
            json.dumps(
                {
                    "timestamp": _utcnow().isoformat(),
                    "started_at": started_at,
                    "run_id": run_id,
                    "hook": "yam_yam_post_run_review",
                    "status": "error",
                    "cmd": cmd,
                    "error": repr(exc),
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


def start_run(duration_hours: float = 0.0, virtual_currency: float | None = None, live_trade: bool = False) -> None:
    ensure_directories()
    if os.environ.get("LIVE_RUN_MODE", "paper").lower() == "live" and not live_trade:
        raise SystemExit("Live trading requires explicit --live-trade")
    run_id = create_run_id()
    run_dir = run_directory(run_id)
    symbol_list = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbol_list.split(",") if symbol_list else target_symbol_list()
    virtual_budget = virtual_currency_context(virtual_currency)
    run_mode = "live" if live_trade else "paper"
    meta = {
        "run_id": run_id,
        "mode": run_mode,
        "symbols": symbols,
        "duration_hours": duration_hours,
        "started_at": _utcnow().isoformat(),
        "status": "scheduled",
        "proof_telemetry": _proof_telemetry_enabled(),
        **virtual_budget,
        "virtual_currency_note": "testing-only virtual capital pool; not real brokerage cash",
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
    if _proof_telemetry_enabled() and not live_trade:
        _emit_paper_proof_telemetry(run_id)
    command = [sys.executable, "-m", "tools.live_run", "run", "--run-id", run_id, "--duration-hours", str(duration_hours)]
    if virtual_currency is not None:
        command.extend(["--virtual-currency", str(virtual_currency)])
    if live_trade:
        command.append("--live-trade")
    if _proof_telemetry_enabled():
        command.append("--proof-telemetry")
    child_env = dict(os.environ, LIVE_RUN_MODE=run_mode)
    child_env.setdefault("OPENCLAW_BIN", str(Path.home() / ".npm-global" / "bin" / "openclaw"))
    child_env["PATH"] = f"{Path.home() / '.npm-global' / 'bin'}:{child_env.get('PATH', '')}"
    if _proof_telemetry_enabled() and not live_trade:
        child_env["LIVE_RUN_PROOF_TELEMETRY_SUPPRESSED"] = "1"
    proc = subprocess.Popen(command, env=child_env, start_new_session=True)
    (run_dir / "run.pid").write_text(str(proc.pid))
    write_current_run(run_id, proc.pid)
    print(f"Live-data paper run started: {run_id}")
    print(f"Logs at: {run_dir / 'logs' / 'run.log'}")


def update_evolution_states_from_warehouse() -> None:
    warehouse_path = ROOT / "data" / "warehouse.sqlite"
    if not warehouse_path.exists():
        return
    try:
        with sqlite3.connect(warehouse_path) as conn:
            rows = conn.execute(
                """
                SELECT c.name, cp.latest_account_value, cp.latest_realized_pnl, cp.latest_unrealized_pnl
                FROM companies c
                JOIN company_performance cp ON cp.company_id = c.id
                """
            ).fetchall()
    except sqlite3.Error:
        return
    for company, account_value, realized_pnl, unrealized_pnl in rows:
        state = load_evolution_state(str(company))
        baseline = float(state.get("company_packet_cap_baseline", 1.0) or 1.0)
        total_pnl = float(realized_pnl or 0.0) + float(unrealized_pnl or 0.0)
        if total_pnl > 0 or float(account_value or 0.0) > 100.0:
            baseline += 0.05
        elif total_pnl < 0 or (account_value is not None and float(account_value) < 100.0):
            baseline -= 0.05
        state["company_packet_cap_baseline"] = baseline
        save_evolution_state(str(company), state)



def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True



def _wait_for_pid_exit(pid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_is_alive(pid):
            return True
        time.sleep(0.2)
    return not _pid_is_alive(pid)


def _process_group_is_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_process_group_exit(pgid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _process_group_is_alive(pgid):
            return True
        time.sleep(0.2)
    return not _process_group_is_alive(pgid)


def stop_run(run_id: str | None = None) -> None:
    current = {}
    try:
        current = read_current_run()
    except FileNotFoundError:
        pass
    target_run = run_id or current.get("run_id")
    if not target_run:
        raise SystemExit("No run_id provided and no current run tracked")
    run_dir = run_directory(target_run)
    pid_file = run_dir / "run.pid"
    pid = current.get("pid") if current.get("run_id") == target_run else None
    if pid is None and pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
        except Exception:
            pid = None
    if pid is None:
        raise SystemExit(f"Live-data paper run {target_run} stop failed: no worker PID available")

    worker_pid = int(pid)
    process_group_id = int(current.get("pgid") or worker_pid)
    graceful_stop = True
    forced_kill = False
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        graceful_stop = False
    else:
        if not _wait_for_process_group_exit(process_group_id, max(5.0, float(LIVE_RUN_POLL_SECONDS))):
            graceful_stop = False
            forced_kill = True
            try:
                os.killpg(process_group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if not _wait_for_process_group_exit(process_group_id, 5.0):
                raise SystemExit(
                    f"Live-data paper run {target_run} stop failed: worker process group for PGID {process_group_id} still alive after SIGTERM and SIGKILL"
                )

    if _process_group_is_alive(process_group_id):
        raise SystemExit(f"Live-data paper run {target_run} stop failed: worker process group for PGID {process_group_id} is still alive")
    if _pid_is_alive(worker_pid):
        graceful_stop = False
        forced_kill = True
        try:
            os.kill(worker_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if not _wait_for_pid_exit(worker_pid, 5.0):
            raise SystemExit(f"Live-data paper run {target_run} stop failed: worker PID {worker_pid} is still alive")

    if pid_file.exists():
        pid_file.unlink()
    meta_path = run_dir / "run_metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["ended_at"] = _utcnow().isoformat()
        meta["status"] = "stopped"
        meta_path.write_text(json.dumps(meta, indent=2))
        write_daily_digest(target_run)
    if current.get("run_id") == target_run:
        clear_current_run()
    if graceful_stop and not forced_kill:
        print(f"Live-data paper run {target_run} stopped safely.")
    else:
        print(f"Live-data paper run {target_run} stopped after forced kill.")


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



def build_live_candle(snapshot: Dict[str, Any], last_price: float | None) -> Dict[str, Any]:
    symbol = str(snapshot.get("symbol") or "")
    timestamp = snapshot.get("timestamp")
    price = float(snapshot.get("price") or 0.0)
    if not symbol or not timestamp or price <= 0.0:
        return build_pseudo_candle(snapshot, last_price)
    try:
        bucket = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).replace(second=0, microsecond=0).isoformat()
    except ValueError:
        return build_pseudo_candle(snapshot, last_price)

    def _new_active_candle() -> Dict[str, Any]:
        open_price = float(last_price if last_price not in (None, 0) else price)
        high = max(open_price, price)
        low = min(open_price, price)
        return {
            "timestamp": timestamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": price,
            "candle_source": "real_ohlc",
            "candle_confidence": 0.7,
        }

    state = getattr(build_live_candle, "_state", {})
    entry = state.get(symbol)
    if not entry:
        state[symbol] = {"active_bucket": bucket, "active_candle": _new_active_candle(), "emit_bucket": None, "emitted_candle": None}
        build_live_candle._state = state
        return dict(state[symbol]["active_candle"])

    active_candle = dict(entry.get("active_candle") or _new_active_candle())
    if entry.get("active_bucket") == bucket:
        active_candle["high"] = max(float(active_candle.get("high") or price), price)
        active_candle["low"] = min(float(active_candle.get("low") or price), price)
        active_candle["close"] = price
        entry["active_candle"] = active_candle
        state[symbol] = entry
        build_live_candle._state = state
        emitted_candle = entry.get("emitted_candle") if entry.get("emit_bucket") == bucket else None
        return dict(emitted_candle) if emitted_candle else dict(active_candle)

    finalized_candle = active_candle
    state[symbol] = {
        "active_bucket": bucket,
        "active_candle": _new_active_candle(),
        "emit_bucket": bucket,
        "emitted_candle": finalized_candle,
    }
    build_live_candle._state = state
    return dict(finalized_candle)



def run_worker(run_id: str, duration_hours: float = 0.0, virtual_currency: float | None = None, live_trade: bool = False) -> None:
    if os.environ.get("LIVE_RUN_MODE", "paper").lower() == "live" and not live_trade:
        raise SystemExit("Live trading requires explicit --live-trade")
    run_dir = run_directory(run_id)
    pid_file = run_dir / "run.pid"
    symbols = os.environ.get("LIVE_RUN_SYMBOLS")
    symbols = symbols.split(",") if symbols else target_symbol_list()
    virtual_budget = virtual_currency_context(virtual_currency)
    portfolio_parent_total = virtual_currency if virtual_currency is not None else None
    portfolio = PortfolioState(run_dir, parent_total=portfolio_parent_total, companies=COMPANIES)
    with pid_file.open("w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))
    meta_path = run_dir / "run_metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["status"] = "running"
        meta["worker_started_at"] = _utcnow().isoformat()
        meta_path.write_text(json.dumps(meta, indent=2))
    _emit_paper_proof_telemetry(run_id)
    stop_flag = False
    backoff = 0
    end_time = _utcnow() + timedelta(hours=duration_hours) if duration_hours > 0 else None
    last_prices: Dict[tuple[str, str], float] = _bootstrap_last_prices_from_previous_run(run_id, symbols)
    candle_history: Dict[str, List[Dict[str, Any]]] = {}
    cycle = 0

    def _signal_handler(*_: Any) -> None:
        nonlocal stop_flag
        stop_flag = True

    signal.signal(signal.SIGTERM, _signal_handler)
    log_path = run_dir / "logs" / "run.log"
    while not stop_flag and (not end_time or _utcnow() < end_time):
        cycle += 1
        timestamp = _utcnow().replace(tzinfo=timezone.utc).isoformat()
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
        cycle_last_prices = dict(last_prices)
        for company in COMPANIES:
            for snapshot in snapshots:
                symbol = snapshot["symbol"]
                price_key = (company, symbol)
                symbol_history = candle_history.setdefault(symbol, [])
                latest_candle = build_live_candle(snapshot, cycle_last_prices.get(price_key))
                symbol_history.append(latest_candle)
                candle_history[symbol] = symbol_history[-20:]
                snapshot["candle_source"] = latest_candle["candle_source"]
                snapshot["candle_confidence"] = latest_candle["candle_confidence"]
                portfolio.mark_price(company, symbol, float(snapshot.get("price") or 0.0))
                position_snapshot = portfolio.get_position_snapshot(company, symbol)
                snapshot.update(position_snapshot)
                decision = build_decision(snapshot, company, cycle_last_prices.get(price_key), candle_history=candle_history[symbol])
                decision["vetoed_by_risk"] = abs(decision.get("signal_score", 0)) > 0.08
                decision.update(position_snapshot)
                decision["cash_snapshot"] = portfolio.cash.get(company, 0.0)
                decision["allocation_context"] = portfolio.allocations.get(company)
                decision["cycle"] = cycle
                decision["ranking_score"] = candidate_ranking_score(decision)
                decision["pretrade_selection_path"] = "ranked_then_company_packet"
                decision["pretrade_agent_participation"] = "company packet consulted after ranking"
                decision.update(virtual_budget)
                decision["virtual_currency_note"] = "testing-only virtual capital pool; not real brokerage cash"
                last_prices[price_key] = snapshot.get("price") or last_prices.get(price_key, 0.0)
                candidate_decisions.append(decision)

        apply_orion_bias_before_ranking(candidate_decisions)
        ranked_candidates = rank_and_select_candidates(candidate_decisions)
        company_packets = apply_company_packets(ranked_candidates, now=_utcnow().replace(tzinfo=timezone.utc), run_id=run_id, cycle=cycle)
        for packet in company_packets.values():
            packet_record = {"timestamp": timestamp, **packet}
            with (run_dir / "artifacts" / "company_packets.jsonl").open("a", encoding="utf-8") as packet_file:
                packet_file.write(json.dumps(packet_record) + "\n")
            rpg_events = apply_runtime_packet_rpg_updates(packet_record, workspace_root=ROOT)
            if os.getenv("RPG_ECHO_RUNTIME", "1").strip().lower() not in {"0", "false", "no", "off"}:
                for rpg_event in rpg_events:
                    print(format_runtime_rpg_event(rpg_event), flush=True)
        for decision in ranked_candidates:
            if decision["vetoed_by_risk"]:
                anomalies.append(f"veto:{decision['company_id']}:{decision['symbol']}")
                with (run_dir / "artifacts" / "risk.log").open("a", encoding="utf-8") as risk_file:
                    risk_file.write(json.dumps({"timestamp": timestamp, "company": decision["company_id"], "symbol": decision["symbol"], "veto": True}) + "\n")
            if decision.get("execution_state") != "executed":
                continue
            with (run_dir / "artifacts" / "paper_decisions.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(decision) + "\n")
            portfolio.apply_decision(decision)
            cycle_decisions.append(decision)
        orchestrate(run_dir, cycle, cycle_decisions, anomalies)
        strategy_entry = {
            "timestamp": timestamp,
            "decision": "ml+signal" if any(d.get("ml_scoring_active") for d in cycle_decisions) else "signal-only",
            "confidence": 0.0,
            "ml_scoring_active": any(d.get("ml_scoring_active") for d in cycle_decisions),
            **virtual_budget,
            "virtual_currency_note": "testing-only virtual capital pool; not real brokerage cash",
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
                        "orion_bias": d.get("orion_bias"),
                        "orion_bias_reason": d.get("orion_bias_reason"),
                        "orion_report_timestamp": d.get("orion_report_timestamp"),
                        "orion_match_fields": d.get("orion_match_fields"),
                        "orion_bias_applied": d.get("orion_bias_applied"),
                        "detected_patterns": d.get("detected_patterns"),
                        "pattern_score": d.get("pattern_score"),
                        "pattern_engine_mode": d.get("pattern_engine_mode"),
                        "strat_pattern": d.get("strat_pattern"),
                        "strat_available": d.get("strat_available"),
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
                    if not (d.get("decision") in {"WAIT", "HOLD_POSITION"} and d.get("execution_state") == "skipped")
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
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        meta["ended_at"] = _utcnow().isoformat()
        if stop_flag:
            meta["status"] = "stopped"
        else:
            meta["status"] = "completed"
        meta_path.write_text(json.dumps(meta, indent=2))
    write_daily_digest(run_id)
    run_ledger_post_run_review(run_id)
    run_helena_post_run_review(run_id)
    run_axiom_post_run_review(run_id)
    run_vivienne_post_run_review(run_id)
    run_selene_post_run_review(run_id)
    run_ariadne_post_run_review(run_id)
    run_grant_post_run_speech(run_id)
    run_yam_yam_post_run_review(run_id)
    run_june_post_run_archive(run_id)
    update_evolution_states_from_warehouse()
    prune_old_run_artifacts(run_id)
    current = None
    try:
        current = read_current_run()
    except FileNotFoundError:
        current = None
    if current and current.get("run_id") == run_id:
        clear_current_run()

def summary(run_id: str) -> None:
    run_dir = run_directory(run_id)
    logs = list((run_dir / "logs").glob("*.log"))
    summary = {
        "run_id": run_id,
        "captured": _utcnow().isoformat(),
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
    start_parser.add_argument("--virtual-currency", type=float, default=None, help="Testing-only virtual capital pool; not real brokerage cash")
    start_parser.add_argument("--proof-telemetry", action="store_true", help="Emit one proof-only telemetry event before the worker loop")
    start_parser.add_argument("--live-trade", action="store_true", help="Explicitly enable live-trade mode")
    stop_parser = subparsers.add_parser("stop", help="Stop the current paper run")
    stop_parser.add_argument("--run-id", help="Explicit run id to stop")
    run_parser = subparsers.add_parser("run", help="Run worker (internal)")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--duration-hours", type=float, default=0.0)
    run_parser.add_argument("--virtual-currency", type=float, default=None, help="Testing-only virtual capital pool; not real brokerage cash")
    run_parser.add_argument("--proof-telemetry", action="store_true", help="Emit one proof-only telemetry event before the worker loop")
    run_parser.add_argument("--live-trade", action="store_true", help="Explicitly enable live-trade mode")
    summary_parser = subparsers.add_parser("summary", help="Generate summary bundle")
    summary_parser.add_argument("--run-id", required=True)
    verify_parser = subparsers.add_parser("verify", help="Verify paper-only mode")
    verify_parser.add_argument("--run-id", required=True)
    subparsers.add_parser("validate", help="Validate feed/dirs")
    args = parser.parse_args()
    if args.command == "start":
        if args.proof_telemetry:
            os.environ["LIVE_RUN_PROOF_TELEMETRY"] = "1"
        start_run(duration_hours=args.duration_hours, virtual_currency=args.virtual_currency, live_trade=args.live_trade)
    elif args.command == "stop":
        stop_run(run_id=args.run_id)
    elif args.command == "run":
        if args.proof_telemetry:
            os.environ["LIVE_RUN_PROOF_TELEMETRY"] = "1"
        run_worker(args.run_id, duration_hours=args.duration_hours, virtual_currency=args.virtual_currency, live_trade=args.live_trade)
    elif args.command == "summary":
        summary(args.run_id)
    elif args.command == "verify":
        verify_paper_only(args.run_id)
    elif args.command == "validate":
        validate()


if __name__ == "__main__":
    main()
