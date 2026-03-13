"""Helpers for reading/writing company metadata."""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml

COMPANIES_DIR = Path(__file__).resolve().parent.parent / "companies"


def metadata_path(company: str) -> Path:
    return COMPANIES_DIR / company / "metadata.yaml"


def read_metadata(company: str) -> Dict[str, Any]:
    path = metadata_path(company)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def write_metadata(company: str, data: Dict[str, Any]) -> None:
    path = metadata_path(company)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def append_note(company: str, note: str) -> None:
    metadata = read_metadata(company)
    existing = metadata.get("notes", "")
    metadata["notes"] = (existing + "\n" if existing else "") + note
    write_metadata(company, metadata)
