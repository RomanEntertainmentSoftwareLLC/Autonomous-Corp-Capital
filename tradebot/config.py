"""Configuration helpers for the trading prototype."""

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Safely load a YAML file and ensure it returns a dict."""

    if not path.exists():
        raise FileNotFoundError(f"Config not found at {path}")

    with open(path, "r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config at {path} is not a mapping")

    return data


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge override into base, recursively merging dictionaries."""

    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    """Load configuration by merging the shared base config with an optional company override."""

    base_config = _load_yaml(DEFAULT_CONFIG_PATH)
    if path is None:
        return deepcopy(base_config)

    config_path = Path(path)
    if config_path == DEFAULT_CONFIG_PATH:
        return deepcopy(base_config)

    company_config = _load_yaml(config_path)
    merged = _deep_merge(base_config, company_config)
    if "live_trading_enabled" not in merged:
        merged["live_trading_enabled"] = False
    return merged
