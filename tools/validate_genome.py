#!/usr/bin/env python3
"""Validate a company genome before compiling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Tuple

import yaml

from tradebot.strategies.registry import STRATEGY_REGISTRY

COMPANIES_DIR = Path("companies")
MODEL_OPTIONS = {
    "logistic_regression": {
        "penalty": (0.01, 10.0),
        "C": (0.01, 5.0),
    },
    "random_forest": {
        "n_estimators": (10, 200),
        "max_depth": (3, 20),
    },
}
FEATURE_FLAGS = [
    "use_ema_spread",
    "use_rsi",
    "use_price_change_1",
    "use_price_change_2",
    "use_price_change_3",
    "use_momentum_3",
    "use_slope_3",
    "use_pattern_flags",
]
INDICATOR_PARAMS = {
    "ema_fast": (3, 30),
    "ema_slow": (10, 60),
    "rsi_period": (5, 30),
    "rsi_buy": (10, 50),
    "rsi_sell": (60, 90),
    "momentum_period": (2, 20),
    "volatility_period": (5, 60),
}

def load_genome(path: Path) -> Dict[str, any]:
    if not path.exists():
        raise SystemExit(f"Genome missing at {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def check_range(value: float, bounds: Tuple[float, float], name: str, errors: list):
    if not (bounds[0] <= value <= bounds[1]):
        errors.append(f"{name}={value} outside [{bounds[0]}, {bounds[1]}]")

def validate_model(genome: Dict[str, any], errors: list):
    model_type = genome.get("model_type") or genome.get("model", {}).get("model_type")
    if model_type and model_type not in MODEL_OPTIONS:
        errors.append(f"Unknown model_type '{model_type}'")
        return
    params = genome.get("model", {}).get("model_parameters", {})
    for param, bounds in MODEL_OPTIONS.get(model_type, {}).items():
        value = params.get(param)
        if value is None:
            continue
        check_range(float(value), bounds, param, errors)
    conf = genome.get("model", {}).get("confidence_threshold")
    if conf is not None and not (0.1 <= float(conf) <= 0.98):
        errors.append(f"confidence_threshold {conf} out of [0.1,0.98]")


def validate_feature_flags(genome: Dict[str, any], errors: list):
    features = genome.get("feature_flags", {})
    if not features:
        errors.append("feature_flags missing or empty")
        return
    if not any(features.get(flag) for flag in FEATURE_FLAGS):
        errors.append("At least one feature flag must be enabled")


def validate_indicator_params(genome: Dict[str, any], errors: list):
    indicator_params = genome.get("indicator_parameters", {})
    for param, bounds in INDICATOR_PARAMS.items():
        value = indicator_params.get(param)
        if value is None:
            continue
        check_range(float(value), bounds, param, errors)

def strategy_valid(genome: Dict[str, any], errors: list):
    strategy = genome.get("strategy_type")
    if not strategy:
        errors.append("strategy_type is required")
        return
    strategy = strategy.replace("hybrid_", "hybrid_")
    if strategy not in STRATEGY_REGISTRY:
        errors.append(f"Unknown strategy_type '{strategy}'")

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a company genome")
    parser.add_argument("company", help="Company id")
    args = parser.parse_args()

    genome_path = COMPANIES_DIR / args.company / "genome.yaml"
    genome = load_genome(genome_path)
    errors = []
    strategy_valid(genome, errors)
    validate_feature_flags(genome, errors)
    validate_indicator_params(genome, errors)
    validate_model(genome, errors)

    if errors:
        print("Genome validation failed:")
        for err in errors:
            print("  -", err)
        raise SystemExit(1)

    print("Genome looks valid.")

if __name__ == "__main__":
    main()
