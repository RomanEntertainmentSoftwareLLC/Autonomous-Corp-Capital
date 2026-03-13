"""Helpers for filtering companies by lifecycle state."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"

EXCLUDED_STATES = {"RETIRED", "ARCHIVED"}


def load_state(company: str) -> str:
    path = COMPANIES_DIR / company / "metadata.yaml"
    if not path.exists():
        return "NEW"
    try:
        data = yaml.safe_load(path.open("r", encoding="utf-8")) or {}
    except yaml.YAMLError:
        return "NEW"
    return str(data.get("lifecycle_state", "NEW")).upper()


def should_include(state: str, include_paused: bool = False) -> bool:
    state = state.upper()
    if state in EXCLUDED_STATES:
        return False
    if state == "PAUSED" and not include_paused:
        return False
    return True
