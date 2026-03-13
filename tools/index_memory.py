#!/usr/bin/env python3
"""Chunk workspace memory files for future vector indexing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradebot.memory_store import MemoryChunk, chunk_store_path, index_chunks

FILES_TO_INDEX = [
    ROOT / "AGENT_HANDOFF.md",
    ROOT / "NEXT_STEPS.md",
    ROOT / "README.md",
]
DOCS_DIR = ROOT / "docs"
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 200


def collect_files() -> Iterable[Path]:
    for path in FILES_TO_INDEX:
        if path.exists():
            yield path
    if DOCS_DIR.exists():
        for md in sorted(DOCS_DIR.rglob("*.md")):
            yield md


def chunk_text(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> List[str]:
    paragraphs = [para.strip() for para in text.split("\n\n") if para.strip()]
    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            new_chunk = []
            if overlap:
                acc = 0
                for prior_para in reversed(current_chunk):
                    if acc + len(prior_para) > overlap:
                        break
                    new_chunk.insert(0, prior_para)
                    acc += len(prior_para)
            current_chunk = new_chunk
            current_len = sum(len(p) for p in current_chunk)
        current_chunk.append(para)
        current_len += len(para)
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    if not chunks:
        text_len = len(text)
        start = 0
        while start < text_len:
            end = min(text_len, start + size)
            chunks.append(text[start:end])
            start = end - overlap if end - overlap > start else end
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk memory files into JSONL")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    args = parser.parse_args()

    chunks: List[MemoryChunk] = []
    for path in collect_files():
        text = path.read_text(encoding="utf-8")
        for idx, chunk in enumerate(chunk_text(text, size=args.chunk_size, overlap=args.overlap)):
            chunks.append(MemoryChunk(source_file=path.name, chunk_index=idx, text=chunk))
    index_chunks(chunks)
    print(f"Indexed {len(chunks)} chunks to {chunk_store_path()}")


if __name__ == "__main__":
    main()
