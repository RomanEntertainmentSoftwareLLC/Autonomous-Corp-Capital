"""Secrets loading plan for later read-only enhancements."""

from pathlib import Path
from typing import Dict


ENV_PATH = Path(__file__).parent.parent / ".env"


def load_secrets(path: Path | None = None) -> Dict[str, str]:
    """Parse a simple .env file into key/value pairs."""
    target = path or ENV_PATH
    secrets: Dict[str, str] = {}

    if not target.exists():
        return secrets

    with target.open("r", encoding="utf-8") as fh:
        for line in fh:
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            if "=" not in cleaned:
                continue
            key, value = cleaned.split("=", 1)
            secrets[key.strip()] = value.strip()

    return secrets
