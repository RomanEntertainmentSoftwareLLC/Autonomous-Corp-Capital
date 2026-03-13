#!/usr/bin/env python3
"""Batch self-play runner across multiple regimes."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable, List

from tradebot.sim_market import SyntheticMarketGenerator
from tools.self_play import load_manifest, Participant, load_company_config
from tools.lifecycle_filter import load_state as load_lifecycle_state, should_include as should_include_state

FITNESS_WEIGHTS = {
    "realized_pnl": 1.0,
    "unrealized_pnl": 0.25,
    "win_rate": 0.5,
    "drawdown": -2.0,
    "trade_count": -0.05,
}


def fitness(metrics: Dict[str, float]) -> float:
    return (
        metrics.get("realized_pnl", 0.0) * FITNESS_WEIGHTS["realized_pnl"]
        + metrics.get("unrealized_pnl", 0.0) * FITNESS_WEIGHTS["unrealized_pnl"]
        + metrics.get("win_rate", 0.0) * FITNESS_WEIGHTS["win_rate"]
        + metrics.get("drawdown", 0.0) * FITNESS_WEIGHTS["drawdown"]
        + metrics.get("trade_count", 0.0) * FITNESS_WEIGHTS["trade_count"]
    )


def load_specs(participant_names: Iterable[str], manifest: Path | None, include_paused: bool) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    if manifest:
        specs.extend(load_manifest(manifest))
    for name in participant_names:
        specs.append({"name": name, "config": load_company_config(name)})
    filtered: List[Dict[str, Any]] = []
    for spec in specs:
        state = load_lifecycle_state(spec["name"])
        if should_include_state(state, include_paused=include_paused):
            filtered.append(spec)
        else:
            print(f"Skipping {spec['name']} (state={state})")
    return filtered


def simulate_once(participants: List[Dict[str, Any]], regime: str, seed: int, iterations: int) -> Dict[str, Dict[str, float]]:
    market = SyntheticMarketGenerator(regime=regime, seed=seed, interval_seconds=10)
    ticks = list(market.generate(iterations))
    players = [Participant(entry["name"], entry["config"]) for entry in participants]
    adjustment = 0.0
    for tick in ticks:
        record_price = max(0.01, tick.price + adjustment)
        record = {"timestamp": tick.timestamp.isoformat() + "Z", "symbol": tick.symbol, "price": record_price}
        for player in players:
            player.tick(record)
        adjustment *= 0.9
    results: Dict[str, Dict[str, float]] = {}
    for player in players:
        summary = player.summarize(record_price)
        summary["fitness"] = fitness(summary)
        results[player.name] = summary
    print(f"Regime: {regime} (seed {seed})")
    print("name          fitness  account  realized  drawdown  win%  trades")
    for name, metrics in sorted(results.items(), key=lambda kv: kv[1]["fitness"], reverse=True):
        print(
            f"{name:<14} {metrics['fitness']:>7.2f}  ${metrics['account']:>7.2f}  {metrics['realized_pnl']:>8.2f}  {metrics['drawdown']:>8.2f}  {metrics['win_rate']:>4.1f}%  {metrics['trade_count']:>6}"
        )
    print()
    return results


def aggregate_results(batch: Dict[str, Dict[str, Dict[str, float]]]) -> None:
    aggregate: Dict[str, Dict[str, List[float]]] = {}
    for regime_results in batch.values():
        for name, metrics in regime_results.items():
            stats = aggregate.setdefault(name, {k: [] for k in ("fitness", "account", "realized_pnl", "drawdown", "win_rate", "trade_count")})
            for key in stats:
                stats[key].append(metrics[key])
    print("Aggregate performance across regimes:")
    print("name          fitness  account  realized  drawdown  win%  trades")
    for name, stats in sorted(aggregate.items(), key=lambda kv: sum(kv[1]["fitness"]) / len(kv[1]["fitness"]), reverse=True):
        metrics = {key: sum(values) / len(values) for key, values in stats.items()}
        print(
            f"{name:<14} {metrics['fitness']:>7.2f}  ${metrics['account']:>7.2f}  {metrics['realized_pnl']:>8.2f}  {metrics['drawdown']:>8.2f}  {metrics['win_rate']:>4.1f}%  {metrics['trade_count']:>6.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a batch of self-play tournaments across regimes")
    parser.add_argument("--participants", nargs='+', help="Company ids to include")
    parser.add_argument("--manifest", type=Path, help="YAML manifest of participants")
    parser.add_argument(
        "--regimes",
        nargs='+',
        default=["trending_up", "ranging", "high_volatility"],
        help="Synthetic regimes to run",
    )
    parser.add_argument("--seed", type=int, default=42, help="Base random seed")
    parser.add_argument("--iterations", type=int, default=50, help="Ticks per regime")
    parser.add_argument("--include-paused", action="store_true", help="Include PAUSED companies in batch runs")
    args = parser.parse_args()

    specs = load_specs(args.participants or [], args.manifest, args.include_paused)
    if not specs:
        raise SystemExit("No eligible participants after lifecycle filtering")

    batch_results: Dict[str, Dict[str, Dict[str, float]]] = {}
    for idx, regime in enumerate(args.regimes):
        the_seed = args.seed + idx
        batch_results[regime] = simulate_once(specs, regime, the_seed, args.iterations)

    aggregate_results(batch_results)


if __name__ == "__main__":
    main()
