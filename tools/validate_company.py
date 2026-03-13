#!/usr/bin/env python3
"""Validation helpers for company configs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from tradebot.strategies.factory import STRATEGY_REGISTRY, resolve_strategy_name

from tools.mutation_params import SAFE_RISK_PARAMS, SAFE_SYMBOL_PARAMS

COMPANIES_DIR = Path(__file__).resolve().parent.parent / "companies"


class ValidationError(Exception):
    pass


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ValidationError(f"Config missing at {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _check_bounds(value: float, bounds: tuple[float, float], path: str, errors: List[str]) -> None:
    low, high = bounds
    if not (low <= value <= high):
        errors.append(f"{path}={value} outside [{low}, {high}]")


def validate_config(company: str, config: Dict[str, Any]) -> None:
    errors: List[str] = []

    symbols = config.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        errors.append("Config must define at least one symbol")
    else:
        for idx, symbol in enumerate(symbols, start=1):
            name = symbol.get("name", f"symbol_{idx}")
            strategy_name = resolve_strategy_name(symbol)
            if strategy_name not in STRATEGY_REGISTRY:
                available = ", ".join(sorted(STRATEGY_REGISTRY.keys()))
                errors.append(f"Unknown strategy '{strategy_name}' for {name}. Choose from: {available}")

            for param, bounds in SAFE_SYMBOL_PARAMS.items():
                value = symbol.get(param)
                if value is None:
                    continue
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{name}.{param} must be numeric")
                    continue
                _check_bounds(num, bounds, f"{name}.{param}", errors)

            fast = symbol.get("ema_fast")
            slow = symbol.get("ema_slow")
            if isinstance(fast, (int, float)) and isinstance(slow, (int, float)) and fast >= slow:
                errors.append(f"{name}: ema_fast ({fast}) must be less than ema_slow ({slow})")

            buy = symbol.get("rsi_buy")
            sell = symbol.get("rsi_sell")
            if isinstance(buy, (int, float)) and isinstance(sell, (int, float)) and buy >= sell:
                errors.append(f"{name}: rsi_buy ({buy}) must be less than rsi_sell ({sell})")

    risk = config.get("risk")
    if isinstance(risk, dict):
        for param, bounds in SAFE_RISK_PARAMS.items():
            value = risk.get(param)
            if value is None:
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                errors.append(f"risk.{param} must be numeric")
                continue
            _check_bounds(num, bounds, f"risk.{param}", errors)

    if errors:
        raise ValidationError("; ".join(errors))


def validate_company(company: str) -> None:
    config_path = COMPANIES_DIR / company / "config.yaml"
    config = _load_config(config_path)
    validate_config(company, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a company config")
    parser.add_argument("company", help="Company id to validate")
    args = parser.parse_args()
    try:
        validate_company(args.company)
        print(f"{args.company} config is valid")
    except ValidationError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
