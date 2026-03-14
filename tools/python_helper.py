"""Helper utilities for consistent Python invocations and root imports."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent


def ensure_repo_root() -> None:
    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def python_cmd(args: Iterable[str]) -> list[str]:
    return [sys.executable, *args]


def python_executable() -> str:
    return sys.executable
