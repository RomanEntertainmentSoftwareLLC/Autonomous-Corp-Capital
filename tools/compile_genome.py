#!/usr/bin/env python3
"""Compile a company genome into a runnable config."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.python_helper import ensure_repo_root

ensure_repo_root()

import yaml

from tools.genome_schema import FEATURE_FLAGS, INDICATOR_PARAMS, MODEL_OPTIONS
from tradebot.strategies.registry import strategy_by_name

COMPANIES_DIR = ROOT / "companies"
DEFAULT_CONFIG = ROOT / "tradebot" / "config.yaml"
STRATEGY_ALIASES = {
    "hybrid_ema_rsi": "ema_crossover",
    "ml": "ml_trader",
    "box": "breakout",
    "mean_reversion_v2": "mean_reversion_v2",
}


def load_genome(company: str) -> Dict[str, Any]:
    path = COMPANIES_DIR / company / "genome.yaml"
    if not path.exists():
        raise SystemExit(f"Genome not found for {company}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(company: str) -> Dict[str, Any]:
    path = COMPANIES_DIR / company / "config.yaml"
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    with DEFAULT_CONFIG.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def apply_genome(company: str, genome: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    strategy_type = genome.get("strategy_type")
    strategy_name = STRATEGY_ALIASES.get(strategy_type, strategy_type)
    if strategy_name:
        strategy_by_name(strategy_name)  # validate
    symbols = config.get("symbols", [])
    if not symbols:
        symbols = [{}]
    symbol = symbols[0]
    symbol["name"] = symbol.get("name", company)
    symbol["strategy"] = strategy_name or symbol.get("strategy", "ema_crossover")

    indicator_params = genome.get("indicator_parameters", {})
    for param in INDICATOR_PARAMS:
        if param in indicator_params:
            symbol[param] = indicator_params[param]
    features = genome.get("feature_flags", {})
    for flag in FEATURE_FLAGS:
        if flag in features:
            symbol[flag] = bool(features[flag])
    model_params = genome.get("model_parameters", {})
    model_type = genome.get("model_type")
    for param in MODEL_OPTIONS.get(model_type, {}):
        if param in model_params:
            symbol[param] = model_params[param]
    decision = genome.get("decision_thresholds", {})
    for key, value in decision.items():
        symbol[key] = value
    config["symbols"] = [symbol]

    risk_profile = genome.get("risk_profile", {})
    if risk_profile:
        config.setdefault("risk", {})
        config["risk"].update(risk_profile)
    return config


def write_config(company: str, config: Dict[str, Any]) -> None:
    path = COMPANIES_DIR / company / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile genome into company config")
    parser.add_argument("company", help="Company id")
    parser.add_argument("--dry-run", action="store_true", help="Print config without writing")
    args = parser.parse_args()

    genome = load_genome(args.company)
    config = load_config(args.company)
    new_config = apply_genome(args.company, genome, config)
    if args.dry_run:
        print(yaml.safe_dump(new_config, sort_keys=False))
    else:
        write_config(args.company, new_config)
        print(f"Updated {args.company}/config.yaml based on genome")


if __name__ == "__main__":
    main()
