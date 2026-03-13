#!/usr/bin/env python3
"""Self-play runner for synthetic competitions."""

from __future__ import annotations

import argparse
import copy
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"

from tradebot.execution import ExecutionEngine
from tradebot.portfolio import Portfolio
from tradebot.risk import RiskManager
from tradebot.sim_market import SyntheticMarketGenerator
from tradebot.strategies.factory import build_strategy
from tools.lifecycle_filter import load_state as load_lifecycle_state, should_include as should_include_state


class Participant:
    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        symbol = config.get("symbols", [{}])[0]
        start_balance = symbol.get("starting_balance", 100.0)
        self.name = name
        self.symbol = symbol.get("name", "SIM/TEST")
        self.strategy = build_strategy(symbol)
        self.portfolio = Portfolio(cash=start_balance)
        self.risk = RiskManager(symbol, config.get("risk", {}) or {}, self.portfolio)
        self.execution = ExecutionEngine(self.portfolio)

    def tick(self, tick: Dict[str, Any]) -> str:
        signal = self.strategy.update(tick["price"])
        decision = self.risk.evaluate_signal(signal.__dict__, tick)
        final = self.execution.apply(decision, tick)
        return final.action

    def summarize(self, price: float) -> Dict[str, float]:
        trades = self.portfolio.trade_count
        wins = self.portfolio.win_trades
        win_rate = (wins / trades * 100) if trades else 0.0
        return {
            "account": self.portfolio.account_value(price),
            "realized_pnl": self.portfolio.realized_pnl,
            "unrealized_pnl": self.portfolio.unrealized_pnl(price),
            "drawdown": self.portfolio.max_drawdown,
            "trade_count": trades,
            "win_rate": win_rate,
        }


def load_company_config(name: str) -> Dict[str, Any]:
    path = COMPANIES_DIR / name / "config.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Company config not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    data = yaml.safe_load(path.open("r", encoding="utf-8")) or {}
    participants: List[Dict[str, Any]] = []
    for entry in data.get("participants", []):
        company = entry.get("company")
        if not company:
            continue
        alias = entry.get("alias") or company
        config = copy.deepcopy(load_company_config(company))
        symbol = config.get("symbols", [{}])[0]
        strategy_override = entry.get("strategy")
        if strategy_override:
            symbol["strategy"] = strategy_override
        for key, value in entry.get("overrides", {}).items():
            symbol[key] = value
        participants.append({"name": alias, "config": config})
    return participants


def filter_participants(specs: List[Dict[str, Any]], include_paused: bool) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for spec in specs:
        state = load_lifecycle_state(spec["name"])
        if should_include_state(state, include_paused=include_paused):
            filtered.append(spec)
        else:
            print(f"Skipping {spec['name']} (state={state})")
    return filtered


def run_self_play(
    participants: List[Dict[str, Any]],
    regime: str,
    seed: int,
    iterations: int,
    interaction: bool = False,
) -> None:
    market = SyntheticMarketGenerator(regime=regime, seed=seed, interval_seconds=10)
    ticks = list(market.generate(iterations))
    players: List[Participant] = [Participant(entry["name"], entry["config"]) for entry in participants]

    price_adjustment = 0.0
    for tick in ticks:
        adjusted_price = max(0.01, tick.price + price_adjustment)
        payload = {"timestamp": tick.timestamp.isoformat() + "Z", "symbol": tick.symbol, "price": adjusted_price}
        actions: Dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for player in players:
            action = player.tick(payload)
            actions[action] = actions.get(action, 0) + 1
        if interaction:
            net_flow = actions.get("BUY", 0) - actions.get("SELL", 0)
            slippage = 0.0005 * net_flow
            crowding = 0.001 if abs(net_flow) > len(players) / 2 else 0.0
            spread = 0.0002 * math.copysign(1, net_flow) if abs(net_flow) >= 2 else 0.0
            price_adjustment = slippage + crowding + spread
        else:
            price_adjustment = 0.0

    interaction_text = "with interaction effects" if interaction else "without interaction effects"
    print(f"Self-play results (regime={regime}, seed={seed}, {interaction_text}):")
    print("name          strategy           account  realized  unrealized  drawdown  win%  trades")
    results_payload: List[Dict[str, Any]] = []
    for player in players:
        strategy_name = player.strategy.metadata.name
        summary = player.summarize(ticks[-1].price)
        summary_payload = {"name": player.name, "strategy": strategy_name, **summary}
        results_payload.append(summary_payload)
        print(
            f"{player.name:<12} {strategy_name:<18} {summary['account']:>8.2f}  {summary['realized_pnl']:>8.2f}  {summary['unrealized_pnl']:>11.2f}  {summary['drawdown']:>8.2f}  {summary['win_rate']:>4.1f}%  {summary['trade_count']:>6}"
        )

    run_summary = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "regime": regime,
        "seed": seed,
        "iterations": len(ticks),
        "interaction": interaction,
        "participants": results_payload,
    }
    out_dir = ROOT / "results" / "self_play"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"self_play_{regime}_{seed}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(run_summary, fh, indent=2)
    print(f"Self-play results saved to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run self-play simulations across synthetic markets")
    parser.add_argument("--participants", nargs='+', help="List of company ids to include")
    parser.add_argument("--manifest", type=Path, help="YAML manifest describing participants")
    parser.add_argument("--regime", default="ranging", help="Synthetic market regime")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for determinism")
    parser.add_argument("--iterations", type=int, default=50, help="Ticks to simulate")
    parser.add_argument("--interaction", action="store_true", help="Enable simple interaction effects")
    parser.add_argument("--include-paused", action="store_true", help="Include PAUSED companies in self-play")
    args = parser.parse_args()

    specs: List[Dict[str, Any]] = []
    if args.manifest:
        specs.extend(load_manifest(args.manifest))
    if args.participants:
        for name in args.participants:
            specs.append({"name": name, "config": load_company_config(name)})

    specs = filter_participants(specs, include_paused=args.include_paused)

    if not specs:
        raise SystemExit("No eligible participants for self-play after lifecycle filtering")

    run_self_play(specs, args.regime, args.seed, args.iterations, interaction=args.interaction)


if __name__ == "__main__":
    main()
