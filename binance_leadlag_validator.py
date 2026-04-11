#!/usr/bin/env python3
"""Binance-only lead/lag validator for market comparison logs.

Reads the existing Binance-vs-Robinhood JSONL log, recomputes a trustworthy
price gap from the raw Robinhood quote when available, and summarizes whether
Binance leads future Robinhood movement.

This script is intentionally standalone and does not wire into the live runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_LOG = Path(__file__).with_name("market_compare_paper_log.jsonl")
HORIZONS = (1, 2, 3, 5)
MIN_RECORDS = 6


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _extract_price(container: Any) -> Optional[float]:
    if not isinstance(container, dict):
        return None

    candidates: List[Any] = [
        container.get("price"),
        container.get("mid"),
        container.get("last_trade_price"),
        container.get("mark_price"),
        container.get("best_bid"),
        container.get("best_ask"),
        container.get("bid"),
        container.get("ask"),
    ]
    for candidate in candidates:
        price = _to_float(candidate)
        if price is not None:
            return price
    return None


def _extract_robinhood_price(record: Dict[str, Any]) -> Optional[float]:
    robinhood = record.get("robinhood") or {}
    price = _extract_price(robinhood)
    if price is not None:
        return price

    raw = robinhood.get("raw") or {}
    results = raw.get("results") or []
    if results and isinstance(results, list) and isinstance(results[0], dict):
        price = _extract_price(results[0])
        if price is not None:
            return price

    return None


def _extract_binance_price(record: Dict[str, Any]) -> Optional[float]:
    binance = record.get("binance") or {}
    return _extract_price(binance)


def _parse_ts_ms(value: Any) -> Optional[int]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None

    try:
        ts = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def _sign(value: float, eps: float = 1e-12) -> int:
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


def _gap_bucket(gap_bps: float) -> str:
    if gap_bps <= -5.0:
        return "<= -5 bps"
    if gap_bps <= -2.0:
        return "(-5, -2] bps"
    if gap_bps < 2.0:
        return "(-2, 2) bps"
    if gap_bps < 5.0:
        return "[2, 5) bps"
    return ">= 5 bps"


def _load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing log file: {path}")

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data["_line_no"] = line_no
                records.append(data)

    return records


def _summarize(samples: List[Dict[str, Any]], min_records: int) -> Dict[str, Any]:
    if len(samples) < min_records:
        raise ValueError(f"Need at least {min_records} valid records; found {len(samples)}")

    # Consecutive-sign persistence of the recomputed gap.
    persistence = 0
    previous_sign = None
    for sample in samples:
        current_sign = _sign(sample["gap_bps"])
        if current_sign == 0:
            persistence = persistence + 1 if previous_sign == 0 else 1
        elif current_sign == previous_sign:
            persistence += 1
        else:
            persistence = 1
        sample["persistence_count"] = persistence
        previous_sign = current_sign

    latest = samples[-1]

    horizons: Dict[int, Dict[str, Any]] = {}
    bucket_stats: Dict[str, Dict[int, Dict[str, List[float] | int]]] = defaultdict(
        lambda: defaultdict(lambda: {"moves_bps": [], "hits": 0, "n": 0})
    )

    overall_staleness: List[int] = []
    collector_skew: List[int] = []

    for idx, sample in enumerate(samples):
        binance_ts = sample.get("binance_ts_local_ms")
        robinhood_ts = sample.get("robinhood_ts_local_ms")
        source_ts = sample.get("robinhood_source_ts_ms")
        if isinstance(binance_ts, int) and isinstance(robinhood_ts, int):
            collector_skew.append(robinhood_ts - binance_ts)
        if isinstance(sample.get("loop_ts_ms"), int) and isinstance(source_ts, int):
            overall_staleness.append(sample["loop_ts_ms"] - source_ts)

        for horizon in HORIZONS:
            future_index = idx + horizon
            if future_index >= len(samples):
                continue
            future_price = samples[future_index]["robinhood_price"]
            current_price = sample["robinhood_price"]
            move_dollars = future_price - current_price
            move_bps = (move_dollars / current_price) * 10_000.0 if current_price > 0 else 0.0
            gap_sign = _sign(sample["gap_bps"])
            move_sign = _sign(move_bps)
            hit = gap_sign != 0 and move_sign != 0 and gap_sign == move_sign

            horizon_entry = horizons.setdefault(
                horizon,
                {"n": 0, "hit_count": 0, "move_dollars": [], "move_bps": []},
            )
            horizon_entry["n"] += 1
            horizon_entry["hit_count"] += int(hit)
            horizon_entry["move_dollars"].append(move_dollars)
            horizon_entry["move_bps"].append(move_bps)

            bucket = _gap_bucket(sample["gap_bps"])
            bucket_entry = bucket_stats[bucket][horizon]
            bucket_entry["n"] += 1
            bucket_entry["hits"] += int(hit)
            bucket_entry["moves_bps"].append(move_bps)

    overall_horizons: Dict[str, Any] = {}
    for horizon in HORIZONS:
        entry = horizons.get(horizon, {"n": 0, "hit_count": 0, "move_dollars": [], "move_bps": []})
        n = int(entry["n"])
        overall_horizons[str(horizon)] = {
            "n": n,
            "hit_rate": (entry["hit_count"] / n) if n else None,
            "avg_future_move_dollars": mean(entry["move_dollars"]) if entry["move_dollars"] else None,
            "avg_future_move_bps": mean(entry["move_bps"]) if entry["move_bps"] else None,
        }

    buckets_output: Dict[str, Any] = {}
    for bucket_name in ["<= -5 bps", "(-5, -2] bps", "(-2, 2) bps", "[2, 5) bps", ">= 5 bps"]:
        per_horizon = {}
        for horizon in HORIZONS:
            entry = bucket_stats[bucket_name].get(horizon, {"n": 0, "hits": 0, "moves_bps": []})
            n = int(entry["n"])
            per_horizon[str(horizon)] = {
                "n": n,
                "hit_rate": (entry["hits"] / n) if n else None,
                "avg_future_move_bps": mean(entry["moves_bps"]) if entry["moves_bps"] else None,
            }
        buckets_output[bucket_name] = per_horizon

    current_staleness = None
    if isinstance(latest.get("loop_ts_ms"), int) and isinstance(latest.get("robinhood_source_ts_ms"), int):
        current_staleness = latest["loop_ts_ms"] - latest["robinhood_source_ts_ms"]

    current_collector_skew = None
    if isinstance(latest.get("robinhood_ts_local_ms"), int) and isinstance(latest.get("binance_ts_local_ms"), int):
        current_collector_skew = latest["robinhood_ts_local_ms"] - latest["binance_ts_local_ms"]

    return {
        "source_log": str(latest["source_log"]),
        "valid_rows": len(samples),
        "latest_snapshot": {
            "line_no": latest["_line_no"],
            "loop_ts_ms": latest.get("loop_ts_ms"),
            "binance_price": latest["binance_price"],
            "robinhood_price": latest["robinhood_price"],
            "gap_dollars": latest["gap_dollars"],
            "gap_bps": latest["gap_bps"],
            "gap_bucket": latest["gap_bucket"],
            "persistence_count": latest["persistence_count"],
            "collector_skew_ms": current_collector_skew,
            "robinhood_staleness_ms": current_staleness,
        },
        "staleness": {
            "collector_skew_ms_mean": mean(collector_skew) if collector_skew else None,
            "collector_skew_ms_median": median(collector_skew) if collector_skew else None,
            "robinhood_staleness_ms_mean": mean(overall_staleness) if overall_staleness else None,
            "robinhood_staleness_ms_median": median(overall_staleness) if overall_staleness else None,
        },
        "overall_horizons": overall_horizons,
        "gap_buckets": buckets_output,
    }


def _extract_robinhood_source_ts_ms(record: Dict[str, Any]) -> Optional[int]:
    robinhood = record.get("robinhood") or {}
    raw = robinhood.get("raw") or {}
    results = raw.get("results") or []
    if not (results and isinstance(results, list) and isinstance(results[0], dict)):
        return None
    return _parse_ts_ms(results[0].get("timestamp"))


def _build_samples(records: List[Dict[str, Any]], source_log: Path) -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []
    for record in records:
        binance_price = _extract_binance_price(record)
        robinhood_price = _extract_robinhood_price(record)
        if binance_price is None or robinhood_price is None:
            continue

        loop_ts_ms = record.get("loop_ts_ms") if isinstance(record.get("loop_ts_ms"), int) else None
        binance_ts_local_ms = record.get("binance", {}).get("ts_local_ms")
        robinhood_ts_local_ms = record.get("robinhood", {}).get("ts_local_ms")
        robinhood_source_ts_ms = _extract_robinhood_source_ts_ms(record)

        gap_dollars = binance_price - robinhood_price
        gap_bps = (gap_dollars / robinhood_price) * 10_000.0 if robinhood_price > 0 else 0.0

        samples.append(
            {
                "_line_no": record["_line_no"],
                "source_log": str(source_log),
                "loop_ts_ms": loop_ts_ms,
                "binance_price": binance_price,
                "robinhood_price": robinhood_price,
                "gap_dollars": gap_dollars,
                "gap_bps": gap_bps,
                "gap_bucket": _gap_bucket(gap_bps),
                "binance_ts_local_ms": binance_ts_local_ms if isinstance(binance_ts_local_ms, int) else None,
                "robinhood_ts_local_ms": robinhood_ts_local_ms if isinstance(robinhood_ts_local_ms, int) else None,
                "robinhood_source_ts_ms": robinhood_source_ts_ms,
            }
        )
    return samples


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Binance lead/lag against Robinhood movement.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help="Path to the JSONL market comparison log")
    parser.add_argument(
        "--min-records",
        type=int,
        default=MIN_RECORDS,
        help="Minimum number of valid rows required before summary generation",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        records = _load_records(args.log)
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "log": str(args.log)}, indent=2), file=sys.stderr)
        return 1

    samples = _build_samples(records, args.log)
    if len(samples) < args.min_records:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Need at least {args.min_records} valid rows; found {len(samples)}",
                    "log": str(args.log),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    summary = _summarize(samples, args.min_records)
    print(json.dumps({"ok": True, "summary": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
