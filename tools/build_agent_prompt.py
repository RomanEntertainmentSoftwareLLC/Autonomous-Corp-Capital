#!/usr/bin/env python3
"""Utility to render an agent prompt that includes retrieved memory context."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.prompt_builder import MemoryPromptBuilder

DEFAULT_SYSTEM = "You are the OpenClaw assistant. Obey instructions carefully."


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a prompt with retrieved memory snippets")
    parser.add_argument("user_message", help="Text the agent should respond to")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="System instructions to seed the prompt")
    parser.add_argument("--extra", help="Extra instructions appended before the user request", default=None)
    parser.add_argument("--hint", help="Optional query hint that differs from the user message", default=None)
    args = parser.parse_args()

    builder = MemoryPromptBuilder()
    prompt_data = builder.build_prompt(
        user_message=args.user_message,
        system_instructions=args.system,
        extra_instructions=args.extra,
        query_hint=args.hint,
    )

    print("=== BUILT PROMPT ===")
    print(prompt_data.prompt)
    if prompt_data.chunks:
        print("\n=== FULL CONTEXT CHUNKS ===")
        for chunk in prompt_data.chunks:
            print(f"- {chunk.source_file}#{chunk.chunk_index} (cache hit={prompt_data.cache_hit})")
    else:
        print("\n(no memory chunks were retrieved)")


if __name__ == "__main__":
    main()
