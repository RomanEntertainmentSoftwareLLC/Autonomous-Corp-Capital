from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from tools.agent_runtime import read_history


def load_agent_histories(state_path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    inbox = read_history(state_path / "inbox.jsonl")
    outbox = read_history(state_path / "outbox.jsonl")
    return inbox, outbox
