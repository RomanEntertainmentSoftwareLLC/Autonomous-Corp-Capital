"""Memory chunk store with JSONL persistence + optional Qdrant vector backend."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Sequence

try:
    import torch
except ImportError:  # pragma: no cover - optional
    torch = None

if torch is not None:
    _pytree = getattr(torch.utils, "_pytree", None)
    if _pytree:
        def _patched_register_pytree_node(*args, **kwargs):
            kwargs.pop("serialized_type_name", None)
            return _pytree._register_pytree_node(*args, **kwargs)

        if not hasattr(_pytree, "register_pytree_node"):
            setattr(_pytree, "register_pytree_node", _patched_register_pytree_node)
        elif not hasattr(_pytree, "_register_pytree_node"):
            setattr(_pytree, "_register_pytree_node", _patched_register_pytree_node)

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as rest
    QDRANT_AVAILABLE = True
except ImportError:  # pragma: no cover - optional
    QdrantClient = None
    rest = None
    QDRANT_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMER_AVAILABLE = True
except ImportError:  # pragma: no cover - optional
    SentenceTransformer = None
    SENTENCE_TRANSFORMER_AVAILABLE = False

ROOT = Path(__file__).resolve().parent.parent
CHUNK_STORE_PATH = ROOT / "memory" / "index_chunks.jsonl"
COLLECTION_NAME = os.environ.get("OPENCLAW_MEMORY_COLLECTION", "memory_chunks")
QDRANT_HOST = os.environ.get("OPENCLAW_QDRANT_HOST", "127.0.0.1")
QDRANT_PORT = int(os.environ.get("OPENCLAW_QDRANT_PORT", "6333"))
EMBEDDING_MODEL_NAME = os.environ.get("OPENCLAW_MEMORY_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_BATCH_SIZE = int(os.environ.get("OPENCLAW_EMBEDDING_BATCH_SIZE", "64"))

_embedding_model: SentenceTransformer | None = None
_qdrant_client: QdrantClient | None = None


@dataclass
class MemoryChunk:
    source_file: str
    chunk_index: int
    text: str


def _ensure_store_path() -> None:
    CHUNK_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _get_embedding_model() -> SentenceTransformer | None:
    global _embedding_model
    if not SENTENCE_TRANSFORMER_AVAILABLE or SentenceTransformer is None:
        return None
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _get_qdrant_client() -> QdrantClient | None:
    if not QDRANT_AVAILABLE or QdrantClient is None:
        return None
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        _qdrant_client = QdrantClient(url=f"http://{QDRANT_HOST}", port=QDRANT_PORT)
        _qdrant_client.get_collections()
        return _qdrant_client
    except Exception:
        _qdrant_client = None
        return None


def _keyword_query(query: str, limit: int) -> List[MemoryChunk]:
    query_lower = query.lower()
    matches: List[MemoryChunk] = []
    for chunk in read_chunks():
        if query_lower in chunk.text.lower():
            matches.append(chunk)
        if len(matches) >= limit:
            break
    return matches


def _search_qdrant(query: str, limit: int) -> List[MemoryChunk]:
    client = _get_qdrant_client()
    if client is None:
        print("[memory] Qdrant unavailable; using keyword search")
        return []
    model = _get_embedding_model()
    if model is None:
        print("[memory] Embeddings unavailable; using keyword search")
        return []
    try:
        vector = model.encode([query], convert_to_numpy=True, show_progress_bar=False)[0].tolist()
        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=vector,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:  # pragma: no cover - best-effort
        print(f"[memory] Qdrant search failed ({exc}); falling back to keyword search")
        return []
    hits: List[MemoryChunk] = []
    for hit in response.points:
        payload = hit.payload or {}
        source = payload.get("source_file", "<unknown>")
        chunk_idx = payload.get("chunk_index", 0)
        text = payload.get("text", "")
        hits.append(MemoryChunk(source_file=source, chunk_index=int(chunk_idx), text=text))
    return hits


def _ensure_qdrant_collection(client: QdrantClient, vector_size: int) -> None:
    if not QDRANT_AVAILABLE or rest is None:
        return
    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE),
    )


def _index_to_qdrant(chunks: Sequence[MemoryChunk]) -> None:
    if not chunks:
        return
    client = _get_qdrant_client()
    if client is None:
        print("[memory] Qdrant unavailable; skipping vector indexing")
        return
    model = _get_embedding_model()
    if model is None:
        print("[memory] Embeddings unavailable; skipping vector indexing")
        return
    vector_size = model.get_sentence_embedding_dimension()
    if rest is None:
        print("[memory] Qdrant models unavailable; skipping vector indexing")
        return
    _ensure_qdrant_collection(client, vector_size)
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
        texts = [chunk.text for chunk in batch]
        try:
            vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        except Exception as exc:  # pragma: no cover
            print(f"[memory] Embedding generation failed ({exc}); stopping vector indexing")
            return
        points = []
        for chunk, vector in zip(batch, vectors):
            point_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.source_file}-{chunk.chunk_index}")
            points.append(
                rest.PointStruct(
                    id=str(point_id),
                    vector=vector.tolist(),
                    payload={
                        "source_file": chunk.source_file,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                    },
                )
            )
        try:
            client.upsert(collection_name=COLLECTION_NAME, points=points)
        except Exception as exc:
            print(f"[memory] Qdrant upsert failed ({exc}); stopping vector indexing")
            return


def index_chunks(chunks: Sequence[MemoryChunk]) -> None:
    """Persist a sequence of chunks locally and optionally in Qdrant."""
    _ensure_store_path()
    with CHUNK_STORE_PATH.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(asdict(chunk), ensure_ascii=False) + "\n")
    _index_to_qdrant(chunks)


def read_chunks() -> List[MemoryChunk]:
    if not CHUNK_STORE_PATH.exists():
        return []
    chunks: List[MemoryChunk] = []
    with CHUNK_STORE_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            chunks.append(MemoryChunk(**data))
    return chunks


def query_chunks(query: str, limit: int = 5) -> List[MemoryChunk]:
    if not query:
        return []
    vector_hits = _search_qdrant(query, limit)
    if vector_hits:
        return vector_hits
    return _keyword_query(query, limit)


def chunk_store_path() -> Path:
    return CHUNK_STORE_PATH
