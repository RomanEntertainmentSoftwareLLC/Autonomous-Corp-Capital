#!/usr/bin/env python3
"""Mutate safe numeric parameters of a company config."""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.python_helper import ensure_repo_root
from tools.genome_schema import FEATURE_FLAGS, INDICATOR_FLAGS, INDICATOR_PARAMS

ensure_repo_root()

import yaml

from tools.company_metadata import read_metadata, write_metadata
from tools.mutation_params import SAFE_RISK_PARAMS, SAFE_SYMBOL_PARAMS
from tools.validate_company import ValidationError, validate_config
from tradebot.strategies.registry import available_strategies, strategy_by_name

COMPANIES_DIR = Path(__file__).resolve().parent.parent / "companies"
GENOME_DIR = COMPANIES_DIR


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def dump_config(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def clamp(value: float, bounds: tuple[float, float]) -> float:
    low, high = bounds
    return max(low, min(value, high))


def mutate_numeric(old: float, bounds: tuple[float, float], rnd: random.Random, is_float: bool) -> float:
    low, high = bounds
    if is_float:
        delta = (rnd.random() * 0.4 - 0.2) * old
        candidate = old + delta
    else:
        step = 1
        candidate = old + rnd.randint(-2, 2) * step
    candidate = clamp(candidate, bounds)
    if not is_float:
        return int(round(candidate))
    return candidate


def _next_strategy(current: str) -> Optional[str]:
    choices = available_strategies()
    if not choices:
        return None
    if current in choices:
        idx = choices.index(current)
        return choices[(idx + 1) % len(choices)]
    return choices[0] if choices else None


def _can_apply_strategy(symbol: Dict[str, Any], target: str) -> Optional[str]:
    strategy_cls = strategy_by_name(target)
    metadata = getattr(strategy_cls, "metadata", None)
    if not metadata:
        return None
    missing = [key for key in metadata.required_config if key not in symbol]
    if missing:
        return f"missing config {', '.join(missing)}"
    return None


def load_genome(company: str) -> Dict[str, Any]:
    path = GENOME_DIR / company / "genome.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_genome(company: str, genome: Dict[str, Any]) -> None:
    path = GENOME_DIR / company / "genome.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(genome, fh, sort_keys=False)


def _mutate_feature_flag(genome: Dict[str, Any], flag: str, rnd: random.Random) -> bool:
    features = genome.setdefault("feature_flags", {})
    current = features.get(flag, True)
    if rnd.random() < 0.3:
        features[flag] = not current
        return True
    return False


def _mutate_indicator_flag(genome: Dict[str, Any], flag: str, rnd: random.Random) -> bool:
    indicators = genome.setdefault("indicator_flags", {})
    current = indicators.get(flag, True)
    if rnd.random() < 0.35:
        indicators[flag] = not current
        return True
    return False


def _mutate_indicator_params(
    params: Dict[str, Any], param: str, bounds: tuple[float, float], rnd: random.Random
) -> bool:
    old = params.get(param)
    if old is None:
        return False
    new = mutate_numeric(float(old), bounds, rnd, isinstance(old, float))
    if isinstance(old, int):
        new = int(round(new))
    if new != old:
        params[param] = new
        return True
    return False
def mutate_symbols(
    company: str,
    symbols: List[Dict[str, Any]],
    rnd: random.Random,
    summary: List[str],
    strategy_target: Optional[str] = None,
    strategy_switch: bool = False,
) -> None:
    for symbol in symbols:
        name = symbol.get("name", "UNKNOWN")
        for param, bounds in SAFE_SYMBOL_PARAMS.items():
            if param not in symbol:
                continue
            old = symbol[param]
            new = mutate_numeric(float(old), bounds, rnd, isinstance(old, float) or param in {"order_size"})
            if isinstance(old, int):
                new = int(new)
            if new != old:
                symbol[param] = new
                summary.append(f"{name}.{param}: {old}->{new}")
        # enforce relationships
        fast = symbol.get("ema_fast")
        slow = symbol.get("ema_slow")
        if isinstance(fast, (int, float)) and isinstance(slow, (int, float)) and fast >= slow:
            slow = clamp(fast + 1, SAFE_SYMBOL_PARAMS["ema_slow"])
            symbol["ema_slow"] = int(round(slow))
            summary.append(f"{name}.ema_slow adjusted to keep fast < slow")
        buy = symbol.get("rsi_buy")
        sell = symbol.get("rsi_sell")
        if isinstance(buy, (int, float)) and isinstance(sell, (int, float)) and buy >= sell:
            buy = clamp(sell - 1, SAFE_SYMBOL_PARAMS["rsi_buy"])
            symbol["rsi_buy"] = int(round(buy))
            summary.append(f"{name}.rsi_buy adjusted to stay below rsi_sell")

        genome = load_genome(company)
        genome_flags = genome.setdefault("indicator_flags", {})
        for flag in INDICATOR_FLAGS:
            if _mutate_indicator_flag(genome, flag, rnd):
                summary.append(f"{name}.indicator {flag} -> {genome_flags[flag]}")
        indicator_params = genome.setdefault("indicator_parameters", {})
        for param, bounds in INDICATOR_PARAMS.items():
            if param not in indicator_params:
                continue
            changed = _mutate_indicator_params(indicator_params, param, bounds, rnd)
            symbol[param] = indicator_params[param]
            if changed:
                summary.append(f"{name}.parameter {param} -> {indicator_params[param]}")
        feature_flags = genome.setdefault("feature_flags", {})
        if any(_mutate_feature_flag(genome, flag, rnd) for flag in FEATURE_FLAGS):
            summary.append(f"{name}.feature flags -> {feature_flags}")
        if not any(feature_flags.values()):
            feature_flags[FEATURE_FLAGS[0]] = True
            summary.append(f"{name}.feature flags restored {FEATURE_FLAGS[0]}")
        symbol.update(feature_flags)
        save_genome(company, genome)

        current_strategy = symbol.get("strategy", "ema_crossover")
        desired_strategy = strategy_target
        genome = load_genome(company)
        if strategy_switch and not desired_strategy:
            desired_strategy = _next_strategy(current_strategy)
        if desired_strategy and desired_strategy != current_strategy:
            reason = _can_apply_strategy(symbol, desired_strategy)
            if reason:
                summary.append(
                    f"{name}.strategy change to {desired_strategy} skipped ({reason})"
                )
            else:
                symbol["strategy"] = desired_strategy
                summary.append(
                    f"{name}.strategy: {current_strategy}->{desired_strategy}"
                )
                genome["strategy_type"] = desired_strategy
                save_genome(company, genome)


def mutate_risk(risk: Dict[str, Any], rnd: random.Random, summary: List[str]) -> None:
    for param, bounds in SAFE_RISK_PARAMS.items():
        if param not in risk:
            continue
        old = risk[param]
        new = mutate_numeric(float(old), bounds, rnd, isinstance(old, float))
        if isinstance(old, int):
            new = int(new)
        if new != old:
            risk[param] = new
            summary.append(f"risk.{param}: {old}->{new}")


def update_metadata(company: str, summary: List[str]) -> None:
    metadata = read_metadata(company)
    if metadata is None:
        metadata = {}
    now = datetime.now(timezone.utc).isoformat()
    note = f"{now}: mutated {len(summary)} parameters ({'; '.join(summary)})"
    existing = metadata.get("notes", "")
    metadata["notes"] = (existing + "\n" if existing else "") + note
    metadata["company_id"] = company
    if "generation" not in metadata:
        metadata["generation"] = 1
    write_metadata(company, metadata)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mutate safe numeric parameters in a company config")
    parser.add_argument("company", help="Company id to mutate")
    parser.add_argument("--seed", type=int, help="Optional seed for deterministic mutations")
    parser.add_argument("--strategy", choices=available_strategies(), help="Force a strategy for all symbols")
    parser.add_argument("--strategy-switch", action="store_true", help="Cycle each symbol to the next registered strategy")
    args = parser.parse_args()

    company_dir = COMPANIES_DIR / args.company
    if not company_dir.exists():
        print(f"Company '{args.company}' not found", file=sys.stderr)
        sys.exit(1)

    config_path = company_dir / "config.yaml"
    if not config_path.exists():
        print(f"Config missing for '{args.company}'", file=sys.stderr)
        sys.exit(1)

    config = load_config(config_path)
    rnd = random.Random(args.seed)
    summary: List[str] = []
    symbols = config.get("symbols", [])
    if isinstance(symbols, list):
        mutate_symbols(args.company, symbols, rnd, summary, strategy_target=args.strategy, strategy_switch=args.strategy_switch)
    risk = config.get("risk", {})
    if isinstance(risk, dict):
        mutate_risk(risk, rnd, summary)

    if not summary:
        print("No safe parameters found to mutate.")
        return

    try:
        validate_config(args.company, config)
    except ValidationError as exc:
        print(f"Validation failed after mutation: {exc}", file=sys.stderr)
        sys.exit(1)

    dump_config(config_path, config)
    update_metadata(args.company, summary)
    metadata = read_metadata(args.company)
    parent = metadata.get("parent_company") or "<none>"
    generation = metadata.get("generation", "<unknown>")
    print(f"Mutation summary for {args.company} (parent={parent}, generation={generation})")
    for item in summary:
        print(f" - {item}")
    print(f"Run python3 trade-bot.py --company {args.company} --mode backtest --iterations 4 --loop-feed to test")


if __name__ == "__main__":
    main()
