#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path("/opt/openclaw/.openclaw/workspace")
MEMORY_ROOT = ROOT / "ai_agents_memory"
ROOT_MEMORY = ROOT / "MEMORY.md"


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _agent_memory_path(agent_id: str) -> Path:
    alias = {"yam_yam": "main"}.get(agent_id, agent_id)
    if alias == "main":
        return ROOT_MEMORY
    return MEMORY_ROOT / alias / "MEMORY.md"


def _ensure_section(text: str, section: str) -> str:
    marker = f"## {section}"
    if marker not in text:
        text = text.rstrip() + f"\n\n{marker}\n- \n"
    return text


def append_memory_notes(
    agent_ids: Iterable[str],
    notes: Iterable[str],
    section: str = "Current directives",
    source: str | None = None,
) -> list[Path]:
    cleaned = [str(n).strip() for n in notes if str(n).strip()]
    if not cleaned:
        return []

    date = _utc_date()
    source_prefix = f"[{source}] " if source else ""
    bullets = [f"- {date}: {source_prefix}{note}" for note in cleaned]
    written: list[Path] = []

    for agent_id in agent_ids:
        path = _agent_memory_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = "# MEMORY.md\n\n_Agent-local durable memory._\n\n"
        text = _ensure_section(text, section)

        marker = f"## {section}"
        head, tail = text.split(marker, 1)
        tail = tail.lstrip("\n")
        if "\n## " in tail:
            body, rest = tail.split("\n## ", 1)
            rest = "\n## " + rest
        else:
            body, rest = tail, ""

        existing = [line.rstrip() for line in body.splitlines() if line.strip() and line.strip() != "-"]
        for bullet in bullets:
            if bullet not in existing:
                existing.append(bullet)
        new_body = "\n".join(existing) + ("\n" if existing else "- \n")
        path.write_text(head + marker + "\n" + new_body + rest, encoding="utf-8")
        written.append(path)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Append durable notes to agent MEMORY.md files.")
    parser.add_argument("agents", nargs="+", help="Agent ids (use main or yam_yam for Yam Yam).")
    parser.add_argument("--note", action="append", default=[], help="Note to append. Can be repeated.")
    parser.add_argument("--section", default="Current directives")
    parser.add_argument("--source", default=None)
    args = parser.parse_args()

    written = append_memory_notes(args.agents, args.note, section=args.section, source=args.source)
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
