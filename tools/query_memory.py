#!/usr/bin/env python3
"""Placeholder memory query tool for future Qdrant integration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradebot.memory_store import MemoryChunk, query_chunks


def format_chunk(chunk: MemoryChunk) -> str:
    snippet = chunk.text.replace("\n", " ")
    if len(snippet) > 200:
        snippet = snippet[:197] + "..."
    return f"[{chunk.source_file}@{chunk.chunk_index}] {snippet}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Query indexed memory chunks")
    parser.add_argument("query", help="Search keyword or phrase")
    parser.add_argument("--limit", type=int, default=5, help="Max chunks to return")
    args = parser.parse_args()

    print("[vector memory] querying indexed chunks (Qdrant + fallback)")
    chunks: List[MemoryChunk] = query_chunks(args.query, limit=args.limit)
    if not chunks:
        print("No matching chunks found. Run tools/index_memory.py first.")
        return
    for chunk in chunks:
        print(format_chunk(chunk))


if __name__ == "__main__":
    main()
