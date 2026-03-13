#!/usr/bin/env python3
"""Memory-aware prompt builder that injects Qdrant-retrieved chunks."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradebot.memory_store import MemoryChunk, query_chunks

STATE_DIR = ROOT / "state"
CACHE_PATH = STATE_DIR / "memory_retrieval_cache.json"
USAGE_LOG_PATH = STATE_DIR / "memory_usage_log.jsonl"
DEFAULT_CHUNK_LIMIT = int(os.environ.get("OPENCLAW_MEMORY_CHUNK_LIMIT", "5"))
CACHE_TTL_SECONDS = int(os.environ.get("OPENCLAW_MEMORY_CACHE_TTL", "3600"))
MAX_CONTEXT_CHARS = int(os.environ.get("OPENCLAW_MEMORY_CONTEXT_CHARS", "1800"))


@dataclass
class PromptWithContext:
    prompt: str
    chunks: Sequence[MemoryChunk]
    cache_hit: bool


class RetrievalCache:
    def __init__(self, path: Path = CACHE_PATH, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self.path = path
        self.ttl = timedelta(seconds=ttl_seconds)
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError:
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)

    def _key(self, query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    def get(self, query: str) -> Optional[List[MemoryChunk]]:
        entry = self._data.get(self._key(query))
        if not entry:
            return None
        timestamp = datetime.fromisoformat(entry.get("timestamp", "1970-01-01T00:00:00+00:00"))
        if datetime.now(timezone.utc) - timestamp > self.ttl:
            self._data.pop(self._key(query), None)
            self._save()
            return None
        chunks = [MemoryChunk(**chunk) for chunk in entry.get("chunks", [])]
        return chunks

    def set(self, query: str, chunks: Sequence[MemoryChunk]) -> None:
        if not chunks:
            return
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chunks": [asdict(chunk) for chunk in chunks],
        }
        self._data[self._key(query)] = entry
        self._save()


class UsageLogger:
    def __init__(self, path: Path = USAGE_LOG_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, query: str, chunk_ids: Iterable[str], cache_hit: bool) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "chunks": list(chunk_ids),
            "cache_hit": cache_hit,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class MemoryPromptBuilder:
    """Build prompts enriched with retrieved memory chunks."""

    def __init__(
        self,
        chunk_limit: int = DEFAULT_CHUNK_LIMIT,
        cache_ttl_seconds: int = CACHE_TTL_SECONDS,
        max_context_chars: int = MAX_CONTEXT_CHARS,
    ) -> None:
        self.chunk_limit = chunk_limit
        self.cache = RetrievalCache(ttl_seconds=cache_ttl_seconds)
        self.logger = UsageLogger()
        self.max_context_chars = max_context_chars

    def build_prompt(
        self,
        user_message: str,
        system_instructions: str,
        extra_instructions: Optional[str] = None,
        query_hint: Optional[str] = None,
    ) -> PromptWithContext:
        query = (query_hint or user_message).strip()
        chunks = self.cache.get(query)
        cache_hit = True
        if chunks is None:
            cache_hit = False
            chunks = query_chunks(query, limit=self.chunk_limit)
            self.cache.set(query, chunks)
        chunk_ids = [f"{chunk.source_file}-{chunk.chunk_index}" for chunk in chunks]
        self.logger.log(query, chunk_ids, cache_hit)
        context_block = self._render_context(chunks)
        sections: List[str] = [system_instructions.strip()] if system_instructions.strip() else []
        if extra_instructions and extra_instructions.strip():
            sections.append(extra_instructions.strip())
        if context_block:
            sections.append("Relevant memory snippets:")
            sections.append(context_block)
        sections.append(f"User request: {user_message.strip()}")
        prompt = "\n\n".join(sections)
        return PromptWithContext(prompt=prompt, chunks=chunks, cache_hit=cache_hit)

    def _render_context(self, chunks: Sequence[MemoryChunk]) -> str:
        lines: List[str] = []
        for chunk in chunks:
            snippet = chunk.text.strip()
            if len(snippet) > self.max_context_chars:
                snippet = snippet[: self.max_context_chars - 3] + "..."
            lines.append(
                f"[{chunk.source_file}#{chunk.chunk_index}]\n{snippet}"
            )
        return "\n\n".join(lines)
