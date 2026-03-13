#!/usr/bin/env python3
"""List all registered strategy plugins."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradebot.strategies.registry import STRATEGY_REGISTRY


def main() -> None:
    print("Available strategies:")
    print("name               category         supports_ml  required config           description")
    print("--------------------------------------------------------------------------------")
    for name, cls in STRATEGY_REGISTRY.items():
        meta = getattr(cls, "metadata", None)
        if not meta:
            continue
        req = ",".join(meta.required_config)
        print(
            f"{meta.name:<18} {meta.category:<15} {str(meta.supports_ml):<12} {req:<25} {meta.description}"
        )


if __name__ == "__main__":
    main()
